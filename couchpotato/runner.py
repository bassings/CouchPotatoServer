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

from argparse import ArgumentParser
from couchpotato.core.cache import SQLiteCache
from couchpotato.core.event import fireEventAsync, fireEvent
from couchpotato.core.helpers.encoding import sp
from couchpotato.core.helpers.variable import getDataDir, tryInt, getFreeSpace
import requests
from urllib3 import disable_warnings
from couchpotato.core.softchroot import SoftChrootInitError


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

    # Create FastAPI app
    from couchpotato import create_app
    web_base = ('/' + Env.setting('url_base').lstrip('/') + '/') if Env.setting('url_base') else '/'
    Env.set('web_base', web_base)

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
        'port': tryInt(Env.setting('port', default=5050)),
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

    fireEventAsync('app.load')

    # Run with uvicorn
    try:
        _run_uvicorn(application, config, debug)
    except Exception as e:
        log.error('Failed starting: %s', traceback.format_exc())
        if hasattr(e, 'errno') and e.errno == 48:
            log.info('Port (%s) is already in use', config.get('port'))


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
