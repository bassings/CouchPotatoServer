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
import threading
import time

# Custom log level for "info2" (release-rejection reasons, provider
# circuit-breaker trips, etc). Must be ABOVE INFO (20) so it is visible at
# the default production log level -- setup_logging(debug=False) sets the
# root logger to INFO, and anything below that threshold is dropped before
# it ever reaches a handler. REG-003 item 4.
INFO2 = 21
logging.addLevelName(INFO2, 'INFO')

# Privacy filter patterns
_REPLACE_PRIVATE = ['api', 'apikey', 'api_key', 'password', 'username', 'h', 'uid', 'key', 'passkey',
                    'token', 'authkey', 'torrent_pass', 'sid', 'secret']

#: Names redacted even OUTSIDE a query string, i.e. bare `name=value` in prose.
#:
#: The query-param pass below only matches `?name=` and `&name=`, so anything
#: logged outside a URL went through in the clear. Three live call sites did
#: exactly that: `notifications/telegrambot.py:37` logs `token=%s` at ERROR
#: (so it reaches production logs, and a Telegram bot token is a full
#: send-as-this-bot credential), `downloaders/synology.py:125` logs `sid=%s`,
#: and `http_client.py:236` logs whole URLs whose parameter names were not all
#: in the list above.
#:
#: Deliberately NARROWER than _REPLACE_PRIVATE: `h`, `uid`, `key` and
#: `username` are too generic to match bare assignments safely -- `key=` alone
#: appears in ordinary dict-dumping messages, and eating those destroys the
#: diagnostic the operator needed. A redaction nobody can read around is one
#: that gets switched off.
#:
#: Matched case-INSENSITIVELY and with an optional `[\w-]*` prefix, so
#: `access_token=`, `bot_token=` and `X-Plex-Token=` are caught as well as
#: `token=`. That is not hypothetical tidiness:
#: `notifications/plex/server.py:85` builds `...?X-Plex-Token=%s` and hands it
#: to `urlopen`, and `http_client.py:236` logs the whole URL at INFO -- so the
#: Plex auth token was written to the log on every notification, matched by
#: neither pass (the query-string one wants an exact lowercase `token` right
#: after `?`/`&`; this one was case-sensitive and anchored on `\b`).
#: `secret` was added for the session signing secret (AC-SEC-41). None of the
#: names above matches it: it is stored as the `session_secret` property, and
#: the obvious way to write it in a debug line is `session_secret=<64 hex>` --
#: which the `[\w-]*` prefix catches, along with `client_secret=` and
#: `app_secret=`. Unlike the api_key there is no verbatim-value pass for it: the
#: secret ROTATES, so a cached copy in this filter would be stale exactly when
#: it mattered, and re-reading it per record would take the adapter's
#: process-wide lock on every log line.
_REPLACE_PRIVATE_BARE = ['api_key', 'apikey', 'password', 'passkey', 'token', 'authkey',
                         'torrent_pass', 'secret']

#: Names too SHORT to carry a prefix match. `sid` is three characters, and
#: `[\w-]*sid=` would eat ordinary words. Matched exactly, case-insensitively.
_REPLACE_PRIVATE_BARE_EXACT = ['sid']

#: Home-directory prefixes, redacted to the directory name alone.
#:
#: `traceback.format_exc()` writes every frame's ABSOLUTE source path, so an
#: unhandled error in a native install logs `/home/<name>/...` or
#: `/Users/<name>/...` -- the operator's username and directory layout, in a
#: file that routinely gets pasted into bug reports. The project security floor
#: says no private filesystem paths in logs, and this filter had no path
#: handling at all.
#:
#: The tail is KEPT deliberately. The module path, line number and function are
#: the entire reason a traceback is logged; a filter that ate the line would
#: remove the diagnosis along with the leak, which is how redaction gets
#: switched off.
_HOME_PREFIX_RE = re.compile(r'(?:/home/|/Users/)[^/\s"\':,)]+')


#: Seconds a `log_suppressed` key stays quiet after its first record.
#:
#: Five minutes, chosen against the ring rather than by feel. The ring is
#: 500,000 bytes x 11 files and the records this bounds cost roughly 266 bytes
#: each, so at two records per key per window three keys cost about 1.5 KB an
#: hour -- the ring holds years of that. At sixty seconds it would be five
#: times that and still churn the ring in about two weeks of a stuck install,
#: which is the case where the operator most needs the OTHER lines to survive.
#: Short enough that an operator who restarts and reloads sees the message
#: immediately, because the first record after a quiet period is never withheld.
LOG_SUPPRESSION_WINDOW = 300

#: key -> [emitted_at, suppressed_since_then]. Process-wide and small: one
#: entry per call site, never per request, per IP or per message, so a stranger
#: cannot grow it.
_log_suppression_state = {}
_log_suppression_lock = threading.Lock()


def reset_log_suppression():
    """Forget every window. For tests; nothing in the app calls it."""
    with _log_suppression_lock:
        _log_suppression_state.clear()


def without_paths(error):
    """Describe an exception without naming any file it mentions.

    `OSError.__str__` appends `filename` whenever it is SET -- not only when
    errno is set. `OSError()` with just a filename renders as
    `[Errno None] None: '/mnt/nas/Films/Secret Movie.mkv'`, so any branch that
    reaches `str()` for an OSError leaks the path, and `traceback.format_exc()`
    puts that same line in its output regardless of frame limit.

    So OSError is rebuilt from errno and strerror and NEVER stringified.
    Everything else keeps its message: the leak is specific to OSError, and
    dropping every message to guard against it would cost the diagnosis the
    log exists for.

    Lives here rather than on a plugin because it was duplicated once and the
    copy got it wrong -- it gated on `errno is not None` and fell through to
    `str()` for exactly the case above.
    """
    if isinstance(error, OSError):
        detail = error.strerror or type(error).__name__
        if error.errno is not None:
            return '[errno %s] %s' % (error.errno, detail)
        return detail

    message = str(error)
    return '%s: %s' % (type(error).__name__, message) if message else type(error).__name__


def log_suppressed(log_method, key, message, *args, window=LOG_SUPPRESSION_WINDOW,
                   now=None):
    """Emit `message` at most twice per `window` per `key`, visibly.

    For log calls an UNAUTHENTICATED caller can trigger once per request. Three
    of them live on the authentication surface (`couchpotato/__init__.py`), all
    at ERROR, all firing on every request while the install is in a state the
    operator is probably trying to fix. Measured: 1,000 unauthenticated
    requests wrote 533,043 bytes, so roughly 10,300 of them evict the entire
    5.5 MB ring -- and that ring is the only diagnostic a self-hosted install
    has. Anyone who can reach the port could erase the evidence of everything
    else that happened.

    The bound must not cost the diagnosis, which is the reason those lines are
    at ERROR and name the `config.ini` remedy in full. So a window emits:

      1. the FIRST occurrence, complete and unmodified;
      2. one notice that further identical messages are being withheld, so
         "this happened once" and "this is happening on every request" do not
         read identically;
      3. nothing else -- until the window passes, when the next occurrence is
         emitted in full WITH the number that were withheld.

    `args` are passed through un-interpolated: `CPLog` is `%`-style and
    `PrivacyFilter` redacts `record.msg % record.args` itself, so formatting
    here would route secrets and private paths around the filter.

    `now` is injectable so the window is testable without sleeping and without
    patching a module-level `time.time` -- which on this repo also freezes
    `date.today()` and has produced a recorded false positive. The default
    clock is `time.monotonic`, not `time.time`: a clock step (NTP, a container
    resuming) must not silence a call site for hours or unsuppress it early.
    """
    current = time.monotonic() if now is None else now

    with _log_suppression_lock:
        state = _log_suppression_state.get(key)

        if state is not None and current - state[0] < window:
            state[1] += 1
            if state[1] > 1:
                return
            # Exactly one notice per window, on the SECOND occurrence: the
            # count is not known yet, and repeating the message it is
            # suppressing would double the bytes this exists to save.
            notice = ('The message above is repeating. Further identical '
                      'messages are suppressed for up to %d seconds, and the '
                      'number withheld will be reported with the next one.'
                      % window)
            log_method(notice)
            return

        withheld = state[1] if state is not None else 0
        _log_suppression_state[key] = [current, 0]

    if withheld:
        # Appended as a LITERAL, already interpolated and containing no `%`:
        # the format string still belongs to the caller, whose `args` are
        # applied to it downstream by `PrivacyFilter`.
        message = '%s (%d identical messages were suppressed since the last one.)' % (
            message, withheld)

    log_method(message, *args)


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

        # Bare `name=value`, outside any query string.
        #
        # Stops at whitespace or at any of `&,;)]}'"` so the REST of the
        # message survives -- `token=SECRET and the response was 404` must keep
        # the 404. A filter that swallows the line removes the reason the line
        # was logged, and the operator turns it off.
        #
        # Longer names take an optional `[\w-]*` prefix and are matched
        # case-insensitively, so `access_token=` and `X-Plex-Token=` are caught
        # too; short ones (see _REPLACE_PRIVATE_BARE_EXACT) are matched exactly,
        # because prefix-matching three characters eats ordinary words.
        for replace in _REPLACE_PRIVATE_BARE:
            msg = re.sub(r'[\w-]*%s=[^\s&,;)\]}\'"]+' % replace,
                         lambda m: m.group(0).split('=', 1)[0] + '=xxx', msg,
                         flags=re.IGNORECASE)
        msg = _HOME_PREFIX_RE.sub('<home>', msg)

        # The TRACEBACK too, and it needs materialising here to reach it.
        #
        # Stdlib formats `record.exc_info` inside `Formatter.format()`, which
        # runs AFTER filters -- so every frame's absolute source path reached
        # the file untouched, and the api_key scrubbing below was bypassed for
        # the same reason. Measured with this filter attached:
        #
        #     traceback reached the log      : True
        #     absolute repo path in the log  : True
        #     redaction marker <home> present: False
        #
        # `Formatter.format()` reuses `record.exc_text` when it is already
        # set, so rendering it here and scrubbing it is what makes the
        # redaction actually apply. Two live call sites pass `exc_info=True`
        # (`couchpotato/ui/__init__.py:441` and `:466`), and without this the
        # whole point of the redaction is lost: an operator pastes
        # couchpotato.log into an issue and their home directory is in it.
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _HOME_PREFIX_RE.sub('<home>', record.exc_text)

        for replace in _REPLACE_PRIVATE_BARE_EXACT:
            msg = re.sub(r'\b%s=[^\s&,;)\]}\'"]+' % replace,
                         lambda m: m.group(0).split('=', 1)[0] + '=xxx', msg,
                         flags=re.IGNORECASE)

        # Replace api key.
        #
        # Re-read while it is FALSY, not just while it is None. The old
        # `is None` guard cached an empty string permanently, so a single log
        # record reaching a handler before the key was generated disabled this
        # redaction for the life of the process. Measured: a filter whose first
        # record arrives pre-key then emits the key verbatim, while one whose
        # first record arrives after it redacts correctly.
        #
        # The window is real, not hypothetical: `runner.py` calls
        # setup_logging and then `log.debug('Started with options %s', options)`
        # unconditionally, BEFORE the api_key is generated. (An earlier version
        # of this comment claimed the only calls in between were error paths
        # that return immediately. That was wrong, and it was the premise the
        # whole justification rested on.) The
        # E2E harness now attaches a console handler and CI uploads that stream
        # as an artefact, so this redaction is load-bearing in a way it was not
        # when the caching was written. One dict lookup per record is a fair
        # price for removing the failure mode entirely.
        if not self._api_key:
            # NO re-entrancy guard here, deliberately, and the reasoning is
            # recorded because a previous round got it wrong in both
            # directions.
            #
            # A guard was added on the belief that this lookup re-enters the
            # filter: `Env.setting` -> `Settings.get`, and something logs when
            # the property is absent. It does not. `Settings.get`'s only log
            # is its META-option warning, which `api_key` is not; the absent
            # path raises out of `self.p.get` into `except Exception: return
            # default` and logs nothing. The DEBUG line that does exist,
            # 'Property "%s" not yet stored', is in `getProperty`, reached by
            # `Env.prop` and not by this call. The "124 nested lookups" that
            # justified the guard were measured against a test fake written to
            # log -- the recursion was manufactured by the fixture that then
            # found it.
            #
            # And the guard was not free: a single shared flag meant that while
            # one thread was inside the lookup, another skipped redaction
            # entirely and emitted the api_key VERBATIM. Demonstrated. If a
            # future change ever does make this path log, the fix is a
            # thread-local flag, never a shared one.
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
