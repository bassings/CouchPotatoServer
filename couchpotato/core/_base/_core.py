from uuid import uuid4
import os
import platform
import signal
import time
import traceback
import webbrowser

from couchpotato.api import addApiView
from couchpotato.core.event import fireEvent, addEvent
from couchpotato.core.helpers.variable import cleanHost, md5, isSubFolder, compareVersions, hash_password
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.environment import Env
import threading


log = CPLog(__name__)

autoload = 'Core'


class Core(Plugin):

    ignore_restart = [
        'Core.restart', 'Core.shutdown',
        'Updater.check', 'Updater.autoUpdate',
    ]
    shutdown_started = False

    # Set by `md5Password`, consumed by `rotateSessionSecretAfterSave`. A
    # CLASS attribute, not one assigned in `__init__`, for two reasons:
    #
    # 1. Thread-local, not instance state -- defence-in-depth, NOT closing a
    #    reachable race today. `Settings.saveView` runs value-hook -> write ->
    #    `.committed` on one thread per call, and TWO calls cannot interleave
    #    through the shipped HTTP path: `callApiHandler` (`couchpotato/api.py`)
    #    holds `api_locks['settings.save']` -- one lock per ROUTE, shared by
    #    every settings save -- across the whole handler, and `saveView` is
    #    reached nowhere else in this tree. So plain instance state would be
    #    safe under the current wiring; it is thread-local anyway because that
    #    safety depends entirely on the lock staying exactly as it is, and on
    #    nothing ever calling `saveView` a second way. `threading.local()`
    #    removes the interleaving unconditionally rather than via that lock,
    #    at no cost. Proven with a real two-thread probe (bypassing the lock
    #    entirely, since the lock is what makes the race unreachable via HTTP):
    #    `test_password_rotation_after_commit.py::TestThePendingRotationFlagIsPerThreadNotShared`.
    # 2. Declared at class scope so it exists without `__init__` running.
    #    Plenty of this project's own tests build a bare `Core.__new__(Core)`
    #    to exercise `md5Password` in isolation (`test_password_storage.py`,
    #    `test_auth_required_gate.py`) -- an instance attribute set only in
    #    `__init__` would make those raise `AttributeError` on first use.
    #
    # The trade that buys, stated so a future test does not trip on it:
    # being class-scoped, every `Core` shares this, so the flag a bare
    # `Core.__new__(Core)` leaves behind sits on that thread's slot until
    # something consumes it -- `__init__`'s reset below only runs for real
    # `Core()` construction. Harmless in production, where the only writer
    # is `md5Password` and it assigns unconditionally on every save. It
    # matters for a TEST that calls `rotateSessionSecretAfterSave()` without
    # first calling `md5Password` on the same thread: it would inherit
    # whatever an unrelated earlier test left, and become order-dependent.
    # Set the intent explicitly in such a test rather than relying on the
    # flag being false.
    _pending_rotation = threading.local()

    def __init__(self):
        # Defensive reset: a prior password-save on THIS thread that never
        # reached `rotateSessionSecretAfterSave` (e.g. a test harness that
        # called `md5Password` directly, or a process that never got the
        # matching `.committed` event) must not leak into the next real save
        # this instance handles.
        self._pending_rotation.rotate = False

        addApiView('app.shutdown', self.shutdown, docs = {
            'desc': 'Shutdown the app.',
            'return': {'type': 'string: shutdown'}
        })
        addApiView('app.restart', self.restart, docs = {
            'desc': 'Restart the app.',
            'return': {'type': 'string: restart'}
        })
        addApiView('app.available', self.available, docs = {
            'desc': 'Check if app available.'
        })
        addApiView('app.version', self.versionView, docs = {
            'desc': 'Get version.'
        })

        addEvent('app.shutdown', self.shutdown)
        addEvent('app.restart', self.restart)
        addEvent('app.load', self.launchBrowser, priority = 1)
        addEvent('app.base_url', self.createBaseUrl)
        addEvent('app.api_url', self.createApiUrl)
        addEvent('app.version', self.version)
        addEvent('app.load', self.checkDataDir)
        addEvent('app.load', self.cleanUpFolders)
        addEvent('app.load.after', self.dependencies)

        addEvent('setting.save.core.password', self.md5Password)
        addEvent('setting.save.core.password.committed', self.rotateSessionSecretAfterSave)
        addEvent('setting.save.core.auth_required', self.guardAuthRequired)
        addEvent('setting.save.core.api_key', self.checkApikey)

        # Make sure we can close-down with ctrl+c properly
        if not Env.get('desktop'):
            self.signalHandler()

        # Set default urlopen timeout
        import socket
        socket.setdefaulttimeout(30)

    def dependencies(self):

        # Check if lxml is available
        try: from lxml import etree
        except Exception: log.error('LXML not available, please install for better/faster scraping support: `http://lxml.de/installation.html`')

        try:
            import OpenSSL
            v = OpenSSL.__version__
            v_needed = '0.15'
            if compareVersions(OpenSSL.__version__, v_needed) < 0:
                log.error('OpenSSL installed but %s is needed while %s is installed. Run `pip install pyopenssl --upgrade`', v_needed, v)

            try:
                import ssl
                log.debug('OpenSSL detected: pyopenssl (%s) using OpenSSL (%s)', v, ssl.OPENSSL_VERSION)
            except Exception:
                pass
        except Exception:
            log.error('OpenSSL not available, please install for better requests validation: `https://pyopenssl.readthedocs.org/en/latest/install.html`: %s', traceback.format_exc())

    def md5Password(self, value):
        """Hash a password on its way into config.ini.

        The name is historical and now misleading: this returns **bcrypt**, not
        MD5. It used to return `md5(value)`, so every password set through the
        settings UI or the first-run wizard was written to config.ini as an
        unsalted MD5 -- reversible for any password in a rainbow table.

        bcrypt was reached only by the login-time upgrade
        (`couchpotato/__init__.py:308`), which rehashes on a successful login
        and therefore never ran for anyone who had not logged in. Until
        `auth_required` landed, the server never asked anyone to log in. So the
        users this hashing exists to protect were exactly the ones still on
        MD5.

        bcrypt OVER `md5(value)`, not over the plaintext. That is not a choice
        made here: `login_post` computes `md5(form_password)` and passes it to
        `check_password`, so hashing the plaintext directly would lock out
        every existing and future user. Changing the inner encoding needs its
        own migration and login-time upgrade, and is not a tidy-up to fold in
        here.

        The event name (`setting.save.core.password`) and this method name stay
        as they are: renaming them is a separate change with its own blast
        radius, and a wrong name with a correct docstring is safer than a
        rename made at the same time as a security fix.
        """
        # Keep `auth_required` honest, in BOTH directions.
        #
        # The settings copy says "Setting one turns 'Require login' on", and
        # that was false: `auth_required` was written in exactly one place --
        # runner.py's startup migration -- gated on the key being ABSENT. After
        # the first boot of a passwordless install the key is an explicit 0, so
        # a user who then set a password through the wizard or the settings UI
        # got no authentication at all while both field descriptions told them
        # otherwise. Copy promising an auth behaviour the code does not
        # implement is the exact defect class this PR exists to close.
        #
        # Clearing the password turns it back OFF, and that half is not
        # symmetry for its own sake -- it closes a LOCKOUT. `auth_required = 1`
        # with no password denies every request (get_current_user) AND refuses
        # every login (login_post now requires a configured password), leaving
        # no way in short of hand-editing config.ini. Reachable simply by
        # setting a password and later clearing it. Neither of those two fixes
        # created that state alone; together they did.
        #
        # An operator who wants a password AND an open instance can still turn
        # "Require login" off explicitly afterwards -- that setting remains
        # theirs to set. This only moves it when the password itself changes.
        # Set, do NOT save. `Env.setting(attr, value=...)` calls `save()`
        # immediately, and `Settings.saveView` then does its own
        # `set(...); save()` after this hook returns -- so going through
        # Env.setting would persist auth_required in a SEPARATE, EARLIER write
        # than the password itself. A crash, a full volume or a kill between
        # those two saves leaves authentication ON with no password stored:
        # every request denied, every login refused, no way back short of
        # hand-editing config.ini. That is precisely the lockout this block
        # exists to prevent, reintroduced through a different door.
        #
        # Touching only the in-memory parser lets the caller's single
        # `save()` persist both -- and that save is atomic (T2.0), so the pair
        # lands together or not at all.
        #
        # Guarded, and NOT silently: hashing must not fail because a secondary
        # write did, but a swallowed failure here restores the very state this
        # prevents, so it is logged at ERROR naming the consequence.
        try:
            settings = Env.get('settings')
            settings.addSection('core')
            settings.set('core', 'auth_required', 1 if value else 0)
        except Exception:
            log.error('Password saved but could not update "auth_required" -- '
                      'authentication may not match the password you just set. '
                      'Check Settings > Server > Require login. %s',
                      traceback.format_exc())

        # End every existing session (D6/AC-SEC-38) -- but only once the new
        # password has actually COMMITTED, not merely been submitted.
        #
        # Changing a password is usually a RESPONSE to something -- a shared
        # laptop, a screenshot, a suspicion. Before this, every cookie issued
        # under the old password kept working until its own expiry, so the one
        # action the operator knows to take did not take anything away from
        # whoever prompted it. Rotating the signing secret is what makes the
        # change mean something, and the field's own description now says so.
        #
        # This hook cannot do the rotation itself. It is the VALUE hook, which
        # `Settings.saveView` calls BEFORE `self.save()` writes config.ini
        # (settings.py:507-512). Rotating here would sign every device out for
        # a password change that a subsequent failed save -- read-only config
        # directory, a permissions change, a full volume, any I/O error --
        # then never persists. After a restart the OLD password is still
        # authoritative, and every session opened under it is already gone:
        # nothing changed, and everyone is logged out. So this only RECORDS
        # the intent; `rotateSessionSecretAfterSave`, wired to
        # `setting.save.core.password.committed`, does the rotation once
        # `saveView` reaches that event -- which it only does after `save()`
        # returned without raising.
        #
        # NOT wired to `.after`, despite the name suggesting exactly this.
        # `fireEvent` auto-fires `'<name>.after'` for EVERY dispatch, including
        # the value-hook call itself (`event.py`) -- so a handler on
        # `setting.save.core.password.after` runs BEFORE `self.save()` too, as
        # a side effect of firing THIS hook, defeating the whole point.
        # Measured: rotation happened even when `self.save()` was made to
        # raise. `.committed`, fired explicitly by `saveView` after `self.save()`
        # succeeds, is not a name `fireEvent` auto-derives from anything, so it
        # is the one signal here guaranteed to fire exactly once and only
        # post-commit. See the comment at that `fireEvent` call in settings.py.
        #
        # Assigned UNCONDITIONALLY (`bool(value)`, never `if value: ... =
        # True`). `self.save()` raising means `saveView` never reaches the
        # `.committed` event, so a failed save leaves this thread's flag
        # exactly as this call set it. Only an unconditional assignment
        # guarantees the NEXT call to this hook on this thread -- whatever
        # value it carries, including a clear -- overwrites that leftover
        # before `.committed` is ever reached again, rather than a stale True
        # from a failed SET surviving to make a later CLEAR rotate.
        #
        # Only SET should rotate. Clearing the password turns `auth_required`
        # off two lines above, so every request is already served without a
        # session and there is nothing to revoke -- and rotating anyway would
        # put a secret row on installs that never enabled authentication,
        # which AC-QA-21 and AC-SEC-46 (`specs/PR2B-SESSION-COOKIE.md`) both
        # forbid.
        self._pending_rotation.rotate = bool(value)

        return hash_password(md5(value)) if value else ''

    def rotateSessionSecretAfterSave(self):
        """Rotate the session secret once the password change has committed.

        Wired to `setting.save.core.password.committed`, which `Settings.saveView`
        fires only after `self.save()` has written config.ini without raising
        -- so a save that fails never reaches this, and the operator is never
        signed out for a password change that was not actually persisted.
        Deliberately NOT `.after`: `fireEvent` auto-fires that name for every
        dispatch, including the value hook's OWN call, so it actually runs
        before `self.save()` too. See the comment on `md5Password`'s rotation
        block and the `fireEvent('...committed', ...)` call in settings.py.
        `md5Password` is the value hook that records intent, in a thread-local
        rather than instance attribute; see the class-level `_pending_rotation`
        comment for why.

        Consume-and-clear: read the flag, reset it, THEN act on the value read
        -- so an exception raised while rotating cannot leave the flag set for
        a later, unrelated `.committed` firing on this thread to pick up.

        Guarded, and the guard direction is now the OPPOSITE of what it was
        when rotation lived in the value hook: this runs entirely after the
        password write has already succeeded, so nothing here can abort that
        save. A rotation failure here only leaves the OLD signing secret live
        -- recoverable by signing out (which itself rotates) or a restart --
        never "authentication on, no password stored".
        """
        pending = getattr(self._pending_rotation, 'rotate', False)
        self._pending_rotation.rotate = False
        if not pending:
            return

        try:
            from couchpotato import rotate_session_secret
            rotate_session_secret()
        except Exception:
            log.error('Password saved, but the session signing secret '
                      'could not be rotated -- sessions opened with the '
                      'OLD password are still valid. Sign out to force a '
                      'rotation, or restart. %s', traceback.format_exc())

    def guardAuthRequired(self, value):
        """Refuse to turn "Require login" on while no password is stored.

        That combination is an unrecoverable lockout: `get_current_user` denies
        every request (no cookie can be valid) and `login_post` refuses every
        login, because it now requires a configured password -- deliberately,
        since a blank password accepting any credentials was one of the four
        bypasses this area closed. The only way back is shell access,
        hand-editing config.ini and a restart, on exactly the population least
        able to do that. It is one click from the settings UI and from the
        first-run wizard, and the password field's copy says it cannot happen.

        `md5Password` already closed the other entrance (clearing a password
        turns the requirement off) and its comment names this failure mode;
        `login_post`'s calls the state "one click away in the settings UI".
        Neither of them guarded the direct route.

        Returning 0 rather than raising: the setting simply does not take, the
        checkbox reverts on reload, and the WARNING says why. Turning it OFF is
        never blocked -- that is the direction that RESTORES access.

        Note this only works because `Settings.saveView` now routes the hook
        result through `_resolve_saved_value`. The previous
        `new_value if new_value else value` discarded a falsy return, so this
        guard would have been silently inert.
        """
        wants_auth = str(value).strip().lower() not in ('', '0', 'false', 'no', 'off')
        if not wants_auth:
            return 0

        if not Env.setting('password'):
            log.warning('Refused to turn "Require login" on: no password is set, '
                        'so nothing could satisfy it and you would be locked out '
                        'of your own server. Set a password first -- doing so '
                        'turns "Require login" on for you.')
            return 0

        return 1

    def checkApikey(self, value):
        return value if value and len(value) > 3 else uuid4().hex

    def checkDataDir(self):
        if isSubFolder(Env.get('data_dir'), Env.get('app_dir')):
            log.error('You should NOT use your CouchPotato directory to save your settings in. Files will get overwritten or be deleted.')

        return True

    def cleanUpFolders(self):
        only_clean = ['couchpotato', 'libs', 'init']
        self.deleteEmptyFolder(Env.get('app_dir'), show_error = False, only_clean = only_clean)

    def available(self, **kwargs):
        return {
            'success': True
        }

    def shutdown(self, **kwargs):
        if self.shutdown_started:
            return False

        def shutdown():
            self.initShutdown()

        threading.Thread(target=shutdown, daemon=True).start()

        return 'shutdown'

    def restart(self, **kwargs):
        if self.shutdown_started:
            return False

        def restart():
            self.initShutdown(restart=True)
        threading.Thread(target=restart, daemon=True).start()

        return 'restarting'

    def initShutdown(self, restart = False):
        if self.shutdown_started:
            log.info('Already shutting down')
            return

        log.info('Shutting down' if not restart else 'Restarting')

        self.shutdown_started = True

        fireEvent('app.do_shutdown', restart = restart)
        log.debug('Every plugin got shutdown event')

        loop = True
        starttime = time.time()
        while loop:
            log.debug('Asking who is running')
            still_running = fireEvent('plugin.running', merge = True)
            log.debug('Still running: %s', still_running)

            if len(still_running) == 0:
                break
            elif starttime < time.time() - 30:  # Always force break after 30s wait
                break

            running = list(set(still_running) - set(self.ignore_restart))
            if len(running) > 0:
                log.info('Waiting on plugins to finish: %s', running)
            else:
                loop = False

            time.sleep(1)

        log.debug('Safe to shutdown/restart')

        # Signal the server to stop (uvicorn handles this via sys.exit)
        try:
            import _thread
            _thread.interrupt_main()
        except Exception:
            log.error('Failed shutting down the server: %s', traceback.format_exc())

        fireEvent('app.after_shutdown', restart = restart)

    def launchBrowser(self):

        if Env.setting('launch_browser'):
            log.info('Launching browser')

            url = self.createBaseUrl()
            try:
                webbrowser.open(url, 2, 1)
            except Exception:
                try:
                    webbrowser.open(url, 1, 1)
                except Exception:
                    log.error('Could not launch a browser.')

    def createBaseUrl(self):
        host = Env.setting('host')
        if host == '0.0.0.0' or host == '':
            host = 'localhost'
        port = Env.setting('port')
        ssl = Env.setting('ssl_cert') and Env.setting('ssl_key')

        return '%s:%d%s' % (cleanHost(host, ssl = ssl).rstrip('/'), int(port), Env.get('web_base'))

    def createApiUrl(self):
        return '%sapi/%s' % (self.createBaseUrl(), Env.setting('api_key'))

    def version(self):
        ver = fireEvent('updater.info', single = True) or {'version': {}}

        if os.name == 'nt': platf = 'windows'
        elif 'Darwin' in platform.platform(): platf = 'osx'
        else: platf = 'linux'

        import version as version_module
        ver_str = getattr(version_module, 'VERSION', None)
        ver_branch = getattr(version_module, 'BRANCH', 'master')
        if ver_str:
            return '%s - v%s' % (platf, ver_str)
        return '%s - %s-%s - v2' % (platf, ver.get('version').get('type') or 'unknown', ver.get('version').get('hash') or 'unknown')

    def versionView(self, **kwargs):
        import version as version_module
        ver_str = getattr(version_module, 'VERSION', 'unknown')
        ver_branch = getattr(version_module, 'BRANCH', 'master')
        ver_date = getattr(version_module, 'BUILD_DATE', None)

        # Fall back to git commit date or version.py mtime
        if ver_date is None:
            try:
                import subprocess
                result = subprocess.run(
                    ['git', 'log', '-1', '--format=%ct'],
                    capture_output=True, text=True, timeout=5,
                    cwd=os.path.dirname(os.path.abspath(__file__))
                )
                if result.returncode == 0 and result.stdout.strip():
                    ver_date = int(result.stdout.strip())
            except Exception:
                pass

        if ver_date is None:
            try:
                import version as vm
                ver_date = int(os.path.getmtime(vm.__file__))
            except Exception:
                import time
                ver_date = int(time.time())

        return {
            'version': {
                'hash': 'v%s' % ver_str,
                'date': ver_date,
                'type': 'docker',
                'branch': ver_branch,
            }
        }

    def signalHandler(self):
        if Env.get('daemonized'): return

        def signal_handler(*args, **kwargs):
            fireEvent('app.shutdown', single = True)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


config = [{
    'name': 'core',
    'order': 1,
    'groups': [
        {
            'tab': 'general',
            'name': 'basics',
            'label': 'Server',
            'description': 'Needs restart before changes take effect.',
            'wizard': True,
            'options': [
                {
                    'name': 'auth_required',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Require login',
                    'description': 'Require login for the web interface. Turned on '
                                   'whenever you set a password, and off again if you '
                                   'clear it. Turn off here only for a trusted LAN.',
                },
                {
                    'name': 'username',
                    'default': '',
                    'label': 'Username',
                    # The "leave empty to disable authentication" copy that used to
                    # live here was not merely misleading, it described a real trap:
                    # the old gate was `if username and password`, so a blank
                    # username DID disable auth -- including for someone who had set
                    # a password. The off-switch is `auth_required` now, and this
                    # field means what it says.
                    'description': 'Username for web interface login. Leave empty to '
                                   'accept any username.',
                    'ui-meta' : 'rw',
                },
                {
                    'name': 'password',
                    'default': '',
                    'type': 'password',
                    'label': 'Password',
                    'description': 'Password for web interface login. Setting one turns '
                                   '"Require login" on; clearing it turns it off, so you '
                                   'cannot lock yourself out. Changing it signs you out '
                                   'of every device, including this one.',
                },
                {
                    'name': 'port',
                    'default': 5050,
                    'type': 'int',
                    'label': 'Port',
                    'description': 'Web interface port number. Default: 5050',
                },
                {
                    'name': 'use_https',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Enable HTTPS',
                    'description': 'Serve the web interface over HTTPS. Requires certificate and key below.',
                },
                {
                    'name': 'ssl_cert',
                    'label': 'SSL Certificate',
                    'description': 'Full path to your SSL certificate file (.crt or .pem)',
                    'show_when': {'core.use_https': True},
                },
                {
                    'name': 'ssl_key',
                    'label': 'SSL Private Key',
                    'description': 'Full path to your SSL private key file (.key)',
                    'show_when': {'core.use_https': True},
                },
                {
                    'name': 'ipv6',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Enable IPv6',
                    'description': 'Also listen on IPv6 addresses.',
                    'advanced': True,
                },
            ],
        },
        {
            'tab': 'general',
            'name': 'advanced',
            'label': 'Advanced',
            'description': 'API access, proxy, and system settings.',
            'advanced': True,
            'options': [
                {
                    'name': 'api_key',
                    'label': 'API Key',
                    'default': uuid4().hex,
                    'ui-meta' : 'ro',
                    'description': 'Used by third-party apps to communicate with CouchPotato.',
                },
                {
                    'name': 'url_base',
                    'default': '',
                    'label': 'URL Base',
                    'description': 'Set this if running behind a reverse proxy (e.g. /couchpotato).',
                },
                {
                    'name': 'data_dir',
                    'type': 'directory',
                    'label': 'Data Directory',
                    'description': 'Where cache, logs, and database are stored. Leave empty for default.',
                },
                {
                    'name': 'debug',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Debug Logging',
                    'description': 'Enable verbose debug logging. Increases log file size.',
                },
                {
                    'name': 'use_proxy',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Use Proxy',
                    'description': 'Route outbound connections via an HTTP(S) proxy.',
                },
                {
                    'name': 'proxy_server',
                    'label': 'Proxy Server',
                    'description': 'Proxy address, e.g. 127.0.0.1:8080. Leave empty for system default.',
                },
                {
                    'name': 'proxy_username',
                    'label': 'Proxy Username',
                    'description': 'HTTP Basic Auth username. Leave blank if not required.',
                },
                {
                    'name': 'proxy_password',
                    'type': 'password',
                    'label': 'Proxy Password',
                },
                {
                    'name': 'permission_folder',
                    'default': '0755',
                    'label': 'Folder Permissions',
                    'description': 'Unix file permissions for created folders (e.g. 0755).',
                },
                {
                    'name': 'permission_file',
                    'default': '0644',
                    'label': 'File Permissions',
                    'description': 'Unix file permissions for created files (e.g. 0644).',
                },
            ],
        },
    ],
}]
