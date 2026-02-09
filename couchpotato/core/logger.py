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

# Custom log level for "info2" (less important info, between DEBUG and INFO)
INFO2 = 19
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

    # Console handler with colors
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(ColorFormatter(fmt, datefmt))
        logger.addHandler(console_handler)

    # File handler (no colors)
    if log_path:
        file_handler = RotatingFileHandler(
            log_path, mode='a', maxBytes=500000,
            backupCount=10, encoding=encoding
        )
        file_handler.setFormatter(logging.Formatter(fmt, datefmt))
        logger.addHandler(file_handler)

    # Add privacy filter to root logger
    logger.addFilter(PrivacyFilter())

    # Quiet noisy libraries
    for name in ['enzyme', 'guessit', 'subliminal', 'apscheduler', 'uvicorn', 'requests']:
        logging.getLogger(name).setLevel(logging.ERROR)
    for name in ['gntp']:
        logging.getLogger(name).setLevel(logging.WARNING)
