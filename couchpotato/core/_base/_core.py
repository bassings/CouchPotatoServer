from uuid import uuid4
import os
import platform
import signal
import time
import traceback
import webbrowser
import sys

from couchpotato.api import addApiView
from couchpotato.core.event import fireEvent, addEvent
from couchpotato.core.helpers.variable import cleanHost, md5, isSubFolder, compareVersions
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

    def __init__(self):
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
        addEvent('setting.save.core.api_key', self.checkApikey)

        # Make sure we can close-down with ctrl+c properly
        if not Env.get('desktop'):
            self.signalHandler()

        # Set default urlopen timeout
        import socket
        socket.setdefaulttimeout(30)

        # Don't check ssl by default
        try:
            if sys.version_info >= (2, 7, 9):
                import ssl
                ssl._create_default_https_context = ssl._create_unverified_context
        except Exception:
            log.debug('Failed setting default ssl context: %s', traceback.format_exc())

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
        return md5(value) if value else ''

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
                    'name': 'username',
                    'default': '',
                    'label': 'Username',
                    'description': 'Username for web interface login. Leave empty to disable authentication.',
                    'ui-meta' : 'rw',
                },
                {
                    'name': 'password',
                    'default': '',
                    'type': 'password',
                    'label': 'Password',
                    'description': 'Password for web interface login.',
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
