from logging import handlers
from uuid import uuid4
import locale
import logging
import os.path
import sys
import time
import traceback
import warnings
import re
import tarfile
import shutil

from CodernityDB.database_super_thread_safe import SuperThreadSafeDatabase
from argparse import ArgumentParser
from diskcache import Cache as DiskCache
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
                        dest='config_file', help='Absolute or ~/ path of the settings file (default DATA_DIR/settings.conf)')
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
        options.config_file = os.path.join(data_dir, 'settings.conf')

    if not options.pid_file:
        options.pid_file = os.path.join(data_dir, 'couchpotato.pid')

    options.config_file = os.path.expanduser(options.config_file)
    options.pid_file = os.path.expanduser(options.pid_file)

    return options


def runCouchPotato(options, base_path, args, data_dir=None, log_dir=None, Env=None, desktop=None):

    try:
        locale.setlocale(locale.LC_ALL, "")
        encoding = locale.getpreferredencoding()
    except (locale.Error, IOError):
        encoding = None

    # for OSes that are poorly configured I'll just force UTF-8
    if not encoding or encoding in ('ANSI_X3.4-1968', 'US-ASCII', 'ASCII'):
        encoding = 'UTF-8'

    Env.set('encoding', encoding)

    # Do db stuff
    db_path = sp(os.path.join(data_dir, 'database'))
    old_db_path = os.path.join(data_dir, 'couchpotato.db')

    # Remove database folder if both exists
    if os.path.isdir(db_path) and os.path.isfile(old_db_path):
        db = SuperThreadSafeDatabase(db_path)
        db.open()
        db.destroy()

    # Check if database exists
    db = SuperThreadSafeDatabase(db_path)
    db_exists = db.exists()

    # TEMPORARY: Force database creation for Python 3 migration
    print("INFO: Forcing fresh database creation for Python 3 migration...")
    db.create()
    print("INFO: Database created successfully.")

    # Force creation of cachedir
    log_dir = sp(log_dir)
    cache_dir = sp(os.path.join(data_dir, 'cache'))
    python_cache = sp(os.path.join(cache_dir, 'python'))

    if not os.path.exists(cache_dir):
        os.mkdir(cache_dir)
    if not os.path.exists(python_cache):
        os.mkdir(python_cache)

    session = requests.Session()
    session.max_redirects = 5

    # Register environment settings
    Env.set('app_dir', sp(base_path))
    Env.set('data_dir', sp(data_dir))
    Env.set('log_path', sp(os.path.join(log_dir, 'CouchPotato.log')))
    Env.set('db', db)
    Env.set('http_opener', session)
    Env.set('cache_dir', cache_dir)
    Env.set('cache', DiskCache(python_cache))
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

    # Disable logging for some modules
    for logger_name in ['enzyme', 'guessit', 'subliminal', 'apscheduler', 'uvicorn', 'requests']:
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    for logger_name in ['gntp']:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Disable SSL warning
    disable_warnings()

    # Use reloader
    reloader = debug is True and development and not Env.get('desktop') and not options.daemon

    # Logger
    logger = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%m-%d %H:%M:%S')
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)
    logging.addLevelName(19, 'INFO')

    # To screen
    if (debug or options.console_log) and not options.quiet and not options.daemon:
        hdlr = logging.StreamHandler(sys.stderr)
        hdlr.setFormatter(formatter)
        logger.addHandler(hdlr)

    # To file
    hdlr2 = handlers.RotatingFileHandler(Env.get('log_path'), 'a', 500000, 10, encoding=Env.get('encoding'))
    hdlr2.setFormatter(formatter)
    logger.addHandler(hdlr2)

    # Start logging & enable colors
    import color_logs
    from couchpotato.core.logger import CPLog
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
    except:
        log.error('Unable to check whether SOFT-CHROOT is defined')
        return

    # Check available space
    try:
        total_space, available_space = getFreeSpace(data_dir)
        if available_space < 100:
            log.error('Shutting down as CP needs some space to work. Only %sMB left', available_space)
            return
    except:
        log.error('Failed getting diskspace: %s', traceback.format_exc())

    def customwarn(message, category, filename, lineno, file=None, line=None):
        log.warning('%s %s %s line:%s', (category.__name__, message, filename, lineno))
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
    application = create_app(api_key, web_base)
    Env.set('app', application)

    # Static file mounting
    from fastapi.staticfiles import StaticFiles
    static_path = '%sstatic/' % web_base
    static_dir = sp(os.path.join(base_path, 'couchpotato', 'static'))
    if os.path.isdir(static_dir):
        application.mount(static_path.rstrip('/'), StaticFiles(directory=static_dir), name='static')
    Env.set('static_path', static_path)

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
    except:
        pass
    fireEventAsync('app.load')

    # Run with uvicorn
    import uvicorn

    ssl_kwargs = {}
    if config['ssl_cert'] and config['ssl_key']:
        ssl_kwargs = {
            'ssl_certfile': config['ssl_cert'],
            'ssl_keyfile': config['ssl_key'],
        }

    try:
        uvicorn.run(
            application,
            host=config['host'],
            port=config['port'],
            reload=config['use_reloader'],
            log_level='debug' if debug else 'info',
            **ssl_kwargs
        )
    except Exception as e:
        log.error('Failed starting: %s', traceback.format_exc())
        if hasattr(e, 'errno') and e.errno == 48:
            log.info('Port (%s) is already in use', config.get('port'))
