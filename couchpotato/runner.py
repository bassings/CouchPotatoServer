from uuid import uuid4
import locale
import logging
import os.path
import subprocess
import sys
import time
import traceback
import warnings
import re
import tarfile
import shutil

from argparse import ArgumentParser, ArgumentTypeError
from couchpotato.core.cache import SQLiteCache
from couchpotato.core.event import fireEventAsync, fireEvent
from couchpotato.core.helpers.encoding import sp
from couchpotato.core.helpers.variable import getDataDir, tryInt, getFreeSpace
import requests
from urllib3 import disable_warnings
from couchpotato.core.softchroot import SoftChrootInitError


def log_authentication_posture():
    """State, once, what this instance will actually enforce. AC-OPS-47.

    Only the DISABLED direction used to log. With authentication on, the sole
    statement of posture was `ensure_session_secret`'s first-creation INFO,
    which AC-OPS-41 deliberately silences from the second boot onward -- so a
    restarted instance said nothing about its own authentication at all.

    At 3am the first two questions are "is this instance actually requiring a
    login" and "why is the browser not keeping the cookie", and both were
    answerable only by inferring from an ABSENT warning plus a `config.ini`
    grep.

    `secure` belongs on this line because it is DERIVED, not configured (D4):
    half a TLS pair silently produces a non-Secure cookie, and the reverse
    produces an undeliverable one whose only symptom is a login loop. Without a
    startup value there is nothing to compare that loop against.

    A named function rather than an inline block so it can be driven by a test
    without starting a server.
    """
    from couchpotato import auth_is_required, session_cookie_attributes
    from couchpotato.core.logger import CPLog

    # `log` is created inside the startup functions in this module rather than
    # at import time, so this function makes its own.
    log = CPLog(__name__)

    if not auth_is_required():
        # WARNING, not INFO: an unauthenticated instance is a decision, and the
        # log is where an operator checks whether they made it.
        log.warning('Serving with authentication DISABLED -- anyone who can '
                    'reach this port has full control of the library. Set a '
                    'password and turn on "Require login" in Settings.')
        return

    secure = session_cookie_attributes().get('secure')
    log.info('Serving with authentication ENABLED. Sessions are signed tokens, '
             'not the api_key, and the session cookie is %s. %s',
             'marked Secure' if secure else 'NOT marked Secure',
             'The browser will only send it over https.' if secure else
             'This server does not terminate TLS (no ssl_cert and ssl_key), '
             'so a Secure cookie would be undeliverable.')


def resolve_auth_required_setting():
    """Decide `auth_required` once, at startup, and write the answer down.

    Returns the value it wrote, or None if it wrote nothing.

    ABSENT means "this `config.ini` predates the setting", which is every
    upgraded install. Deriving from `bool(password)` is what keeps an install
    that had bothered to set one protected instead of falling open on upgrade.
    Writing the resolved value back means that from the second boot onward it is
    an explicit 0 or 1 the operator can find with `grep` -- and that matters
    because grepping `config.ini` is the documented lockout recovery: a setting
    that exists only as an inference cannot be recovered from.

    An EXPLICIT value is never touched, in either direction. An operator who
    turned authentication off on a box that still has a password stored made a
    decision, and a boot is not the place to reverse it.

    Extracted from `runner()` for AC-ARCH-10 so it can be driven against a
    settings double with no server, no database and no loader. **Its CALL SITE
    must stay above `loader.run()`** -- `registerDefaults` materialises the
    registered default of 0 into the config, after which "absent" is never true
    again and every upgraded install with a password quietly becomes public.
    An executed test cannot see that, so the source-order guard in
    `tests/unit/test_auth_required_gate.py` stays as well.
    """
    # Function-local. `runner.py` has no module-level `Env` -- `runCouchPotato`
    # takes it as a PARAMETER (`CouchPotato.py:99` passes the same class this
    # imports), and `log` is built after `setup_logging`. Importing here keeps
    # this callable on its own, which is the whole point of extracting it.
    from couchpotato.core.logger import CPLog
    from couchpotato.environment import Env

    log = CPLog(__name__)

    configured = Env.setting('auth_required', default=None)
    if configured not in (None, ''):
        return None

    resolved = 1 if Env.setting('password') else 0

    try:
        Env.setting('auth_required', value=resolved)
    except Exception:
        # KEEP THE RESOLVED VALUE IN MEMORY. `Env.setting(value=)` sets the
        # parser BEFORE it saves, so the correct answer is already there when
        # the save raises -- and it must stay.
        #
        # An earlier version removed it, reasoning that absent means the next
        # boot re-derives. Traced end to end in review, that was a security
        # hole: `loader.run()` runs after this and calls `registerDefaults` for
        # the `core` section, and `Settings.setDefault` sets any option
        # `has_option()` reports absent -- which it now was -- to the
        # registered default of **0**. `loader.run()` then fires
        # `settings.save`, persisting `auth_required = 0`.
        #
        # So on a box with a password and a temporarily unwritable config
        # directory (an ordinary bind-mounted Docker volume) authentication
        # turned itself OFF, `log_authentication_posture()` had already logged
        # "ENABLED", and once the fault cleared the 0 reached disk and the
        # install stayed public. Measured before the fix:
        #
        #     after a FAILED write, present : False
        #     after registerDefaults, value : 0      <- auth OFF
        #
        # Keeping the value makes `setDefault` a no-op, enforces the DERIVED
        # answer for this run, and lets the trailing save persist the correct
        # value if the fault clears. `config.ini` itself is untouched either
        # way -- `Settings.save()` writes a sibling temp file and renames it
        # (AC-DATA-12) -- so nothing is lost by keeping it.
        log.error('Could not write the resolved auth_required value to the '
                  'settings file. Authentication for THIS run is enforced '
                  'from the value derived above (%s), which is kept in memory '
                  'so a failed write cannot turn authentication off. Check '
                  'that the config directory is writable. %s',
                  resolved, traceback.format_exc())
        return None

    log.info('auth_required was not set; resolved to %s from the stored '
             'password and written to the settings file', resolved)
    return resolved


def _port_argument(value):
    """argparse `type=` for `--port`: an int in the valid TCP port range.

    Raising `ArgumentTypeError` makes argparse print a message naming the
    offending value and exit(2) -- AC-OPS-21 requires an invalid port to
    fail loudly at startup, naming the port, not be silently accepted and
    fall through to some default later.
    """
    try:
        port = int(value)
    except ValueError:
        raise ArgumentTypeError('%r is not a valid port (must be an integer)' % value)
    if not (1 <= port <= 65535):
        raise ArgumentTypeError('%r is not a valid port (must be 1-65535)' % value)
    return port


def _resolve_port(cli_port, configured_port):
    """The `--port` precedence rule (AC-OPS-21): `cli_port` (options.port)
    overrides `configured_port` (config.ini's value) when given. `cli_port`
    being `None` means `--port` was never passed, so `configured_port`
    passes through unchanged -- this is what keeps omitting `--port`
    byte-identical to today's behaviour (AC-OPS-20).
    """
    return cli_port if cli_port is not None else configured_port


def getOptions(args):

    # Options
    parser = ArgumentParser(prog='CouchPotato.py')
    parser.add_argument('--data_dir',
                        dest='data_dir', help='Absolute or ~/ path of the data dir')
    parser.add_argument('--config_file',
                        dest='config_file', help='Absolute or ~/ path of the settings file (default DATA_DIR/config.ini)')
    parser.add_argument('--debug', action='store_true',
                        dest='debug', help='Debug mode')
    parser.add_argument('--console_log', action='store_true',
                        dest='console_log', help="Log to console")
    parser.add_argument('--quiet', action='store_true',
                        dest='quiet', help='No console logging')
    parser.add_argument('--daemon', action='store_true',
                        dest='daemon', help='Daemonize the app')
    parser.add_argument('--pid_file',
                        dest='pid_file', help='Path to pidfile needed for daemon')
    parser.add_argument('--port', type=_port_argument, default=None,
                        dest='port', help='Port to bind. Overrides config.ini\'s '
                        '"port" setting; omit to keep today\'s behaviour '
                        'unchanged (config.ini wins, nothing is written back '
                        'to it). Selects a port only -- the bind address '
                        'still comes entirely from config.ini\'s "host".')

    options = parser.parse_args(args)

    data_dir = os.path.expanduser(options.data_dir if options.data_dir else getDataDir())

    if not options.config_file:
        options.config_file = os.path.join(data_dir, 'config.ini')

    if not options.pid_file:
        options.pid_file = os.path.join(data_dir, 'couchpotato.pid')

    options.config_file = os.path.expanduser(options.config_file)
    options.pid_file = os.path.expanduser(options.pid_file)

    return options


def _resolve_migration_script(base_path):
    """Return the absolute path to the standalone CodernityDB->SQLite
    migration script (REFACTOR-01), or raise if it cannot be found.

    The live server process must not import the migration code or
    CodernityDB itself -- it only needs to know where the script lives so it
    can hand off to it as a subprocess.
    """
    script_path = sp(os.path.join(base_path, 'scripts', 'migrate_codernity_to_sqlite.py'))
    if not os.path.isfile(script_path):
        raise RuntimeError(
            'Found a legacy CodernityDB database but the migration script is '
            'missing (expected at %s). Refusing to continue: the app will '
            'not silently create a fresh, empty database in place of your '
            'existing library. Reinstall CouchPotato so scripts/'
            'migrate_codernity_to_sqlite.py is present, then restart.'
            % script_path
        )
    return script_path


def _open_or_create_database(db, data_dir, base_path):
    """Open the SQLite database, migrating a legacy CodernityDB database in
    place first if one is found. Returns True if the resulting database has
    pre-existing data (it was already there, or was just migrated from
    CodernityDB); False for a brand new, empty database.

    A legacy CodernityDB is migrated by running scripts/
    migrate_codernity_to_sqlite.py ONCE as a subprocess (REFACTOR-01) --
    preserving the historical zero-touch upgrade experience without the
    migration code living in the live application tree. The script itself
    renames the CodernityDB directory to database.bak on success, so this
    function does not repeat that rename.

    If the migration subprocess fails, this function raises instead of
    falling through to fresh-database creation -- silently creating an empty
    database over an unmigrated library would be a silent data-loss bug.
    """
    sqlite_db_dir = sp(os.path.join(data_dir, 'database_v2'))
    sqlite_db_file = os.path.join(sqlite_db_dir, 'couchpotato.db')
    codernity_db_path = sp(os.path.join(data_dir, 'database'))
    codernity_backup_path = sp(os.path.join(data_dir, 'database.bak'))

    # Check if SQLite database exists
    if os.path.isfile(sqlite_db_file):
        print("INFO: Opening existing SQLite database...")
        db.open(sqlite_db_dir)
        print("INFO: SQLite database opened successfully.")
        return True

    # Check if old CodernityDB exists and needs migration
    if os.path.isdir(codernity_db_path) and not os.path.isdir(codernity_backup_path):
        migration_script = _resolve_migration_script(base_path)
        print("INFO: Found CodernityDB database, running one-time migration to SQLite...")
        result = subprocess.run(
            [sys.executable, migration_script, '--data-dir', data_dir],
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                'CodernityDB migration failed (exit code %s); see the '
                'migration output above for details. Your original '
                'CodernityDB data is untouched at %s -- refusing to create '
                'a fresh database in its place. Fix the underlying problem '
                'and restart CouchPotato to retry the migration.'
                % (result.returncode, codernity_db_path)
            )
        print("INFO: Migration complete. Opening new SQLite database...")
        db.open(sqlite_db_dir)
        print("INFO: CodernityDB migrated. Now using SQLite.")
        return True

    # Fresh install - create new SQLite database
    print("INFO: No existing database found, creating fresh SQLite database...")
    db.create(sqlite_db_dir)
    print("INFO: SQLite database created successfully.")
    return False


def runCouchPotato(options, base_path, args, data_dir=None, log_dir=None, Env=None, desktop=None):

    try:
        locale.setlocale(locale.LC_ALL, "")
        encoding = locale.getpreferredencoding()
    except (OSError, locale.Error):
        encoding = None

    # for OSes that are poorly configured I'll just force UTF-8
    if not encoding or encoding in ('ANSI_X3.4-1968', 'US-ASCII', 'ASCII'):
        encoding = 'UTF-8'

    Env.set('encoding', encoding)

    # Do db stuff
    # SQLite is the primary database; CodernityDB is only for migration
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    db = SQLiteAdapter()
    db_exists = _open_or_create_database(db, data_dir, base_path)

    # Force creation of cachedir
    log_dir = sp(log_dir)
    cache_dir = sp(os.path.join(data_dir, 'cache'))
    python_cache = sp(os.path.join(cache_dir, 'python'))

    if not os.path.exists(cache_dir):
        os.mkdir(cache_dir)
    if not os.path.exists(python_cache):
        os.mkdir(python_cache)

    from couchpotato.core.http_client import create_session
    session = create_session()

    # Register environment settings
    Env.set('app_dir', sp(base_path))
    Env.set('data_dir', sp(data_dir))
    Env.set('log_path', sp(os.path.join(log_dir, 'CouchPotato.log')))
    Env.set('db', db)
    Env.set('http_opener', session)
    Env.set('cache_dir', cache_dir)
    Env.set('cache', SQLiteCache(python_cache))
    Env.set('console_log', options.console_log)
    Env.set('quiet', options.quiet)
    Env.set('desktop', desktop)
    Env.set('daemonized', options.daemon)
    Env.set('args', args)
    Env.set('options', options)

    # Determine debug
    debug = options.debug or Env.setting('debug', default=False, type='bool')
    Env.set('debug', debug)

    # Development
    development = Env.setting('development', default=False, type='bool')
    Env.set('dev', development)

    # Only suppress SSL warnings if SSL verification is explicitly disabled
    if not Env.setting('ssl_verify', default=True, type='bool'):
        disable_warnings()

    # Use reloader
    reloader = debug is True and development and not Env.get('desktop') and not options.daemon

    # Configure logging
    from couchpotato.core.logger import setup_logging, CPLog
    console = (debug or options.console_log) and not options.quiet and not options.daemon
    setup_logging(
        log_path=Env.get('log_path'),
        debug=debug,
        console=console,
        encoding=Env.get('encoding'),
    )
    log = CPLog(__name__)
    log.debug('Started with options %s', options)

    # Check soft-chroot dir exists:
    try:
        soft_chroot = Env.get('softchroot')
        soft_chroot_dir = Env.setting('soft_chroot', section='core', default=None, type='unicode')
        soft_chroot.initialize(soft_chroot_dir)
    except SoftChrootInitError as exc:
        log.error(exc)
        return
    except Exception:
        log.error('Unable to check whether SOFT-CHROOT is defined')
        return

    # Check available space
    try:
        total_space, available_space = getFreeSpace(data_dir)
        if available_space < 100:
            log.error('Shutting down as CP needs some space to work. Only %sMB left', available_space)
            return
    except Exception:
        log.error('Failed getting diskspace: %s', traceback.format_exc())

    def customwarn(message, category, filename, lineno, file=None, line=None):
        log.warning('%s %s %s line:%s', category.__name__, message, filename, lineno)
    warnings.showwarning = customwarn

    # Resolve `auth_required` ONCE, at startup, and write it back. The body
    # lives in `resolve_auth_required_setting` above so it can be executed by a
    # test rather than only string-searched (M2, AC-ARCH-10).
    #
    # THIS CALL'S POSITION IS PART OF THE BEHAVIOUR. It must stay above
    # `loader.run()`: `registerDefaults` materialises the registered default of
    # 0 into the config, after which the "absent" check never fires again and
    # every upgraded install that had a password set comes up PUBLIC -- with no
    # failing test, no log line, and a diff that looks like tidying. An
    # executed unit test cannot pin an ordering, so
    # `tests/unit/test_auth_required_gate.py` guards it by source order.
    from couchpotato import auth_is_required
    resolve_auth_required_setting()

    # Create FastAPI app
    from couchpotato import create_app
    web_base = ('/' + Env.setting('url_base').lstrip('/') + '/') if Env.setting('url_base') else '/'
    Env.set('web_base', web_base)

    # AFTER `web_base` is set, and that ordering is load-bearing rather than
    # tidy: the posture line reports the derived `secure` value, which comes
    # from `session_cookie_attributes()`, which reads `Env.get('web_base')`.
    # Called any earlier the server dies on boot with
    # `AttributeError: type object 'Env' has no attribute '_web_base'`.
    # It did: the first version of this call sat above, and every unit test
    # passed because they monkeypatched `session_cookie_attributes` -- mocking
    # the one thing that breaks. Only the E2E, which starts a real server,
    # caught it.
    log_authentication_posture()

    api_key = Env.setting('api_key')
    if not api_key:
        api_key = uuid4().hex
        Env.setting('api_key', value=api_key)

    api_base = r'%sapi/%s/' % (web_base, api_key)
    Env.set('api_base', api_base)

    # Basic config
    host = Env.setting('host', default='0.0.0.0')

    config = {
        'use_reloader': reloader,
        # --port overrides config.ini when given; omitted (None) means
        # config.ini's value passes through unchanged (AC-OPS-20/21). Only
        # the port is affected -- `host` above is untouched, so --port
        # cannot become a way to expose an instance more widely than
        # config.ini already does (AC-SEC-16).
        'port': _resolve_port(getattr(options, 'port', None), tryInt(Env.setting('port', default=5050))),
        'host': host if host and len(host) > 0 else '0.0.0.0',
        'ssl_cert': Env.setting('ssl_cert', default=None),
        'ssl_key': Env.setting('ssl_key', default=None),
    }

    # Create FastAPI application
    static_dir = sp(os.path.join(base_path, 'couchpotato', 'static'))
    application = create_app(api_key, web_base, static_dir=static_dir)
    Env.set('app', application)
    Env.set('static_path', '%sstatic/' % web_base)

    # Load configs & plugins
    loader = Env.get('loader')
    loader.preload(root=sp(base_path))
    loader.run()

    # Fill database with needed stuff
    fireEvent('database.setup')
    if not db_exists:
        fireEvent('app.initialize', in_order=True)
    fireEvent('app.migrate')

    # Some logging and fire load event
    try:
        log.info('Starting server on port %(port)s', config)
    except Exception:
        pass
    # Clean orphaned movie entries (Py2 migration: dead IMDB IDs with no metadata)
    try:
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies
        n_orphans = clean_orphaned_movies(db)
        if n_orphans:
            log.info('Removed %d orphaned movie entries with no metadata.', n_orphans)
    except Exception as e:
        log.warning('Orphan cleanup skipped: %s', e)

    # Fix release quality values (detect from name instead of searched quality)
    try:
        from couchpotato.core.migration.fix_release_quality import fix_release_quality
        n_fixed, n_checked = fix_release_quality(db)
        if n_fixed:
            log.info('Fixed quality detection for %d of %d releases.', n_fixed, n_checked)
    except Exception as e:
        log.warning('Release quality fix skipped: %s', e)

    # Reorder default profiles seeded worst-first (BUG-016: 'Best' led with
    # 720p, so it never reached 1080p). Only untouched default profiles are
    # rewritten; customised ones are left alone.
    try:
        from couchpotato.core.migration.fix_profile_quality_order import fix_profile_quality_order
        n_fixed, n_checked = fix_profile_quality_order(db)
        if n_fixed:
            log.info('Reordered %d of %d quality profiles best-first.', n_fixed, n_checked)
    except Exception as e:
        log.warning('Profile quality order fix skipped: %s', e)

    # Create the session signing secret ONCE, here, before the first request is
    # served (D2). Not on a request path: the property store has no uniqueness
    # constraint on `identifier`, so concurrent first-time creates produce
    # duplicate rows and lost writes (measured on `Settings.setProperty`: four
    # concurrent creates gave two rows), and a per-request property read takes
    # the adapter's process-wide RLock.
    #
    # Skipped when authentication is off, so an install that never enabled it
    # never grows the row.
    #
    # A failure here is logged rather than fatal: the process still serves the
    # login page and `config.ini` is still editable, which is the documented
    # way back in. Exiting would take away the page that explains the problem.
    if auth_is_required():
        from couchpotato import ensure_session_secret
        try:
            ensure_session_secret(db)
        except Exception:
            log.error('Could not create or read the session signing secret, so '
                      'NO login can succeed. To recover: set "auth_required = 0" '
                      'in the [core] section of config.ini and restart, then '
                      'check the database is writable. %s', traceback.format_exc())

    fireEventAsync('app.load')

    # Run with uvicorn
    _start_uvicorn_or_exit(application, config, debug, log)


def _run_uvicorn(application, config, debug):
    """Start the uvicorn ASGI server for `application`.

    `access_log=False` keeps request paths -- which embed the URL-based
    api_key (see CLAUDE.md "Known Technical Debt") -- out of uvicorn's
    access log, which would otherwise land in stdout/`docker logs` on every
    request. REG-003 item 3.
    """
    import uvicorn

    ssl_kwargs = {}
    if config['ssl_cert'] and config['ssl_key']:
        ssl_kwargs = {
            'ssl_certfile': config['ssl_cert'],
            'ssl_keyfile': config['ssl_key'],
        }

    uvicorn.run(
        application,
        host=config['host'],
        port=config['port'],
        reload=config['use_reloader'],
        log_level='debug' if debug else 'info',
        access_log=False,
        **ssl_kwargs
    )


def _start_uvicorn_or_exit(application, config, debug, log):
    """Start uvicorn; on failure, log an error NAMING the port and exit
    non-zero.

    AC-OPS-21: an invalid or already-bound port must fail loudly at
    startup, not be logged and swallowed while the process exits 0 as if it
    had started -- that silent shape is exactly what would reintroduce the
    shared-server coupling `--port` exists to remove: a harness spawning
    one server per worker would see every worker report success and only
    discover a missing server once specs start timing out, naming a URL
    instead of the real cause.
    """
    try:
        _run_uvicorn(application, config, debug)
    except SystemExit:
        # uvicorn handles a bind conflict itself: it logs
        # "[Errno 48] error while attempting to bind on address ..." and raises
        # SystemExit(3). That is a BaseException, so `except Exception` below
        # never sees it. Re-raise rather than converting it: the exit code and
        # uvicorn's own message are already correct and already name the port,
        # and swallowing them here would replace a good diagnostic with a
        # worse one.
        #
        # The previous shape special-cased `e.errno == 48`, which was
        # unreachable twice over: SystemExit is not an Exception, and errno 48
        # is macOS. Linux, including the python:3.14-alpine production base,
        # uses 98.
        raise
    except Exception:
        log.error('Failed starting on port %s: %s', config.get('port'), traceback.format_exc())
        sys.exit(1)
