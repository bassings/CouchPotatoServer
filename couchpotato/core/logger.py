"""
CouchPotato logging system.

Provides CPLog factory that returns stdlib logging.Logger instances with
context-aware formatting and privacy filtering. Replaces the old custom
CPLog class that did manual string formatting.

Usage::

    from couchpotato.core.logger import CPLog
    log = CPLog(__name__)
    log.info('Something happened: %s', detail)
"""
import logging
import re
import sys

# Custom log level for "info2" (release-rejection reasons, provider
# circuit-breaker trips, etc). Must be ABOVE INFO (20) so it is visible at
# the default production log level -- setup_logging(debug=False) sets the
# root logger to INFO, and anything below that threshold is dropped before
# it ever reaches a handler. REG-003 item 4.
INFO2 = 21
logging.addLevelName(INFO2, 'INFO')

# Privacy filter patterns
_REPLACE_PRIVATE = ['api', 'apikey', 'api_key', 'password', 'username', 'h', 'uid', 'key', 'passkey']


class ColorFormatter(logging.Formatter):
    """Formatter that adds ANSI color codes based on log level."""

    COLORS = {
        logging.CRITICAL: '\x1b[31m',  # red
        logging.ERROR: '\x1b[31m',     # red
        logging.WARNING: '\x1b[33m',   # yellow
        logging.INFO: '\x1b[0m',       # normal
        INFO2: '\x1b[0m',              # normal
        logging.DEBUG: '\x1b[36m',     # cyan
    }
    RESET = '\x1b[0m'

    def format(self, record):
        msg = super().format(record)
        color = self.COLORS.get(record.levelno, self.RESET)
        return f'{color}{msg}{self.RESET}'


class PrivacyFilter(logging.Filter):
    """Filter that redacts sensitive information from log messages."""

    _api_key = None
    _is_develop = None

    def filter(self, record):
        # Lazy init
        if self._is_develop is None:
            try:
                from couchpotato.environment import Env
                self._is_develop = Env.get('dev')
            except Exception:
                self._is_develop = False

        if self._is_develop:
            return True

        # Format the message first so we can filter it
        if record.args:
            try:
                msg = record.msg % record.args
                record.msg = msg
                record.args = None
            except Exception:
                pass

        msg = str(record.msg)

        for replace in _REPLACE_PRIVATE:
            msg = re.sub(r'(\?%s=)[^\&]+' % replace, r'?%s=xxx' % replace, msg)
            msg = re.sub(r'(&%s=)[^\&]+' % replace, r'&%s=xxx' % replace, msg)

        # Replace api key
        if self._api_key is None:
            try:
                from couchpotato.environment import Env
                self._api_key = Env.setting('api_key') or ''
            except Exception:
                self._api_key = ''

        if self._api_key:
            msg = msg.replace(self._api_key, 'API_KEY')

        record.msg = msg
        return True


class CPLog:
    """Factory that creates stdlib loggers with a context prefix.

    Backward-compatible: returns an object with .debug(), .info(), etc.
    Now delegates directly to stdlib logging instead of manual formatting.
    """

    def __init__(self, context=''):
        if context.endswith('.main'):
            context = context[:-5]
        self.context = context[-25:]
        self.logger = logging.getLogger(context)

    def _log(self, level, msg, *args, **kwargs):
        # Prefix with context
        msg = '[%+25.25s] %s' % (self.context, msg)
        self.logger.log(level, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def info2(self, msg, *args, **kwargs):
        self._log(INFO2, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._log(logging.CRITICAL, msg, *args, exc_info=True, **kwargs)


def setup_logging(log_path=None, debug=False, console=True, encoding='utf-8'):
    """Configure the root logger with console and file handlers.

    Called from runner.py during app startup.

    Args:
        log_path: Path to log file (enables RotatingFileHandler)
        debug: Enable DEBUG level (default INFO)
        console: Enable console output
        encoding: File encoding
    """
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger()
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    fmt = '%(asctime)s %(levelname)s %(message)s'
    datefmt = '%m-%d %H:%M:%S'

    # Privacy filter must be attached to each HANDLER, not the root logger.
    # A Logger's own `.filters` only run for records that *originate* on
    # that logger (see Logger.handle()); CPLog always logs through a named
    # child logger, whose records reach the root's handlers via
    # `callHandlers()` without ever consulting the root logger's own
    # filters. Handler.handle() re-checks its filters for every record it
    # emits regardless of which logger it came from, so attaching there
    # actually redacts secrets (api_key, passkey, ...) in logged URLs.
    # REG-003 item 5.

    # Console handler with colors
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(ColorFormatter(fmt, datefmt))
        console_handler.addFilter(PrivacyFilter())
        logger.addHandler(console_handler)

    # File handler (no colors)
    if log_path:
        file_handler = RotatingFileHandler(
            log_path, mode='a', maxBytes=500000,
            backupCount=10, encoding=encoding
        )
        file_handler.setFormatter(logging.Formatter(fmt, datefmt))
        file_handler.addFilter(PrivacyFilter())
        logger.addHandler(file_handler)

    # Quiet noisy libraries
    for name in ['enzyme', 'guessit', 'subliminal', 'apscheduler', 'uvicorn', 'requests']:
        logging.getLogger(name).setLevel(logging.ERROR)
    for name in ['gntp']:
        logging.getLogger(name).setLevel(logging.WARNING)
