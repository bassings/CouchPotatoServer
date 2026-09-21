"""Standalone HTTP client extracted from Plugin base class.

Provides rate limiting per host, and proxy support.
"""

import re
import threading
import time
import traceback
from urllib.parse import quote, urlparse
from urllib.request import getproxies

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import MaxRetryError
from urllib3.util.retry import Retry

from couchpotato.core.helpers.encoding import ss
from couchpotato.core.helpers.variable import isLocalIP
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env

log = CPLog(__name__)

DEFAULT_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:45.0) Gecko/20100101 Firefox/45.0'
DEFAULT_RETRY_TOTAL = 3
DEFAULT_RETRY_BACKOFF = 0.5
DEFAULT_POOL_CONNECTIONS = 10
DEFAULT_POOL_MAXSIZE = 10


def create_session(retry_total=DEFAULT_RETRY_TOTAL, retry_backoff=DEFAULT_RETRY_BACKOFF,
                   pool_connections=DEFAULT_POOL_CONNECTIONS, pool_maxsize=DEFAULT_POOL_MAXSIZE):
    """Create a requests.Session with retry strategy and connection pooling.

    Args:
        retry_total: Max number of retries per request.
        retry_backoff: Exponential backoff factor between retries.
        pool_connections: Number of connection pools to cache.
        pool_maxsize: Max connections per pool.

    Returns:
        Configured requests.Session.
    """
    session = requests.Session()
    session.max_redirects = 5

    retry = Retry(
        total=retry_total,
        backoff_factor=retry_backoff,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST", "HEAD"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )

    session.mount('http://', adapter)
    session.mount('https://', adapter)

    return session
DISABLE_DURATION = 900  # 15 minutes
MAX_FAILURES_BEFORE_DISABLE = 5

_PROXY_SCHEME_RE = re.compile(r'^(https?)://(.*)$', re.IGNORECASE)


def _split_proxy_scheme(proxy_server):
    """Split a user-typed `proxy_server` setting into (scheme, host).

    `scheme` defaults to 'http' (lower-case) when the value has none.
    Surrounding whitespace on the whole value is stripped first, and a typed
    scheme is matched case-insensitively then normalised to lower-case.
    Anything that does not look like an http/https scheme prefix is treated
    as part of the host, not as an error -- Settings has always accepted a
    bare `host:port`, and that must keep working unchanged.
    """
    value = (proxy_server or '').strip()
    match = _PROXY_SCHEME_RE.match(value)
    if match:
        return match.group(1).lower(), match.group(2)
    return 'http', value


class HttpClient:
    """HTTP client with per-host rate limiting, failure tracking, and proxy support."""

    def __init__(self, time_between_calls=0, user_agent=None, ssl_verify=True):
        self.time_between_calls = time_between_calls
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.ssl_verify = ssl_verify
        self.last_use = {}
        self.last_use_queue = {}
        self.failed_request = {}
        self.failed_disabled = {}
        self._lock = threading.Lock()
        self._rate_event = threading.Event()
        self._rate_event.set()  # Initially open
        self._shutting_down = False

    def shutdown(self):
        self._shutting_down = True

    def _get_proxy_config(self):
        """Read proxy settings from Env."""
        use_proxy = Env.setting('use_proxy')
        if not use_proxy:
            return None

        proxy_server = Env.setting('proxy_server')
        proxy_username = Env.setting('proxy_username')
        proxy_password = Env.setting('proxy_password')

        if proxy_server:
            # Pre-existing, not fixed here (this branch only touches the
            # return statement below): proxy_username/proxy_password are not
            # percent-encoded before being interpolated into this URL. A
            # password containing '@' or ':' produces an ambiguous
            # userinfo@host split that urllib3 may parse incorrectly.
            #
            # The proxy URL's scheme is the scheme of the hop to the PROXY,
            # never the eventual target's scheme -- the "http"/"https" key
            # below only selects which TARGET scheme routes through this
            # proxy, and both keys deliberately carry the SAME proxy URL: a
            # user with one proxy reaches it the same way regardless of
            # whether the target is http or https.
            #
            # That scheme honours whatever the user typed into
            # `proxy_server` (couchpotato/core/_base/_core.py:630 advertises
            # "Route outbound connections via an HTTP(S) proxy", so a typed
            # scheme is a real, supported input, not noise to strip), and
            # defaults to http:// when they typed none. This sits between
            # two past defects on opposite sides of it. Unconditional
            # https:// (the original code) broke every ordinary proxy:
            # Squid and corporate proxies take a plaintext hop and rely on
            # CONNECT to tunnel an https:// target through, and an
            # https://-scheme proxy URL instead tells urllib3 to open TLS
            # straight to the proxy, which almost none speak. Unconditional
            # http:// (this file's own previous fix) broke the opposite,
            # smaller case: an installation whose proxy IS a
            # TLS-terminating listener could no longer be reached over TLS,
            # and if that listener also accepts plaintext, the username and
            # password crossed the hop unencrypted. Neither extreme is
            # right; honouring the configured scheme is.
            scheme, host = _split_proxy_scheme(proxy_server)
            loc = f"{proxy_username}:{proxy_password}@{host}" if proxy_username else host
            proxy_url = f"{scheme}://{loc}"
            return {"http": proxy_url, "https": proxy_url}
        return getproxies()

    def _check_disabled(self, host, show_error=True):
        """Check if a host is temporarily disabled due to failures."""
        with self._lock:
            disabled_time = self.failed_disabled.get(host, 0)
            if disabled_time > 0:
                if disabled_time > (time.time() - DISABLE_DURATION):
                    msg = f'Disabled calls to {host} for 15 minutes because so many failed requests.'
                    log.info2(msg)
                    if not show_error:
                        raise Exception(msg)
                    return True
                else:
                    self.failed_request.pop(host, None)
                    self.failed_disabled.pop(host, None)
        return False

    def _record_failure(self, host, status_code=None):
        """Track failed requests per host, disable after threshold."""
        try:
            with self._lock:
                if status_code == 429:
                    self.failed_request[host] = 1
                    self.failed_disabled[host] = time.time()
                    return

                count = self.failed_request.get(host, 0) + 1
                self.failed_request[host] = count

                if count > MAX_FAILURES_BEFORE_DISABLE and not isLocalIP(host):
                    self.failed_disabled[host] = time.time()
        except Exception:
            log.debug('Failed logging failed requests for host %s: %s', host, traceback.format_exc())

    def _wait_for_rate_limit(self, host, url=''):
        """Enforce per-host rate limiting using event-based waiting instead of busy-wait."""
        if self.time_between_calls == 0:
            return

        try:
            with self._lock:
                if host not in self.last_use_queue:
                    self.last_use_queue[host] = []
                self.last_use_queue[host].append(url)

            while not self._shutting_down:
                with self._lock:
                    wait = (self.last_use.get(host, 0) - time.time()) + self.time_between_calls
                    is_front = self.last_use_queue.get(host, [None])[0] == url

                if not is_front:
                    # Wait on event instead of busy-polling; woken when a slot finishes
                    self._rate_event.clear()
                    self._rate_event.wait(timeout=0.5)
                    continue

                if wait > 0:
                    log.debug('Waiting for rate limit, %d seconds', max(1, wait))
                    self._rate_event.clear()
                    self._rate_event.wait(timeout=min(wait, 30))
                else:
                    with self._lock:
                        self.last_use_queue[host] = self.last_use_queue[host][1:]
                        self.last_use[host] = time.time()
                    # Signal other waiters that a slot opened
                    self._rate_event.set()
                    break
        except Exception:
            log.error('Failed handling waiting call: %s', traceback.format_exc())
            self._rate_event.clear()
            self._rate_event.wait(timeout=self.time_between_calls)

    def request(self, url, timeout=30, data=None, headers=None, files=None,
                show_error=True, stream=False):
        """Make an HTTP request with retry, rate limiting, and failure tracking.

        Args:
            url: URL to request.
            timeout: Request timeout in seconds.
            data: POST data dict (if non-empty, uses POST method).
            headers: Optional headers dict.
            files: Optional files dict for multipart upload.
            show_error: Whether to log errors.
            stream: Whether to stream the response.

        Returns:
            Response content (bytes) or Response object if stream=True.
            Empty string if host is disabled and show_error=True.

        Raises:
            Exception: If host is disabled and show_error=False.
            IOError/MaxRetryError: On connection failure.
        """
        url = quote(ss(url), safe="%/:=&?~#+!$,;'@()*[]")

        if headers is None:
            headers = {}
        if data is None:
            data = {}

        parsed_url = urlparse(url)
        host = f'{parsed_url.hostname}{(":" + str(parsed_url.port)) if parsed_url.port else ""}'

        # Fill default headers
        headers.setdefault('Referer', f'{parsed_url.scheme}://{host}')
        headers.setdefault('Host', None)
        headers.setdefault('User-Agent', self.user_agent)
        headers.setdefault('Accept-encoding', 'gzip')
        headers.setdefault('Connection', 'keep-alive')
        headers.setdefault('Cache-Control', 'max-age=0')

        # Check if host is disabled
        if self._check_disabled(host, show_error):
            return ''

        proxy_url = self._get_proxy_config()
        self._wait_for_rate_limit(host, url)

        r = Env.get('http_opener')
        status_code = None

        try:
            kwargs = {
                'headers': headers,
                'data': data if len(data) > 0 else None,
                'timeout': timeout,
                'files': files,
                'verify': self.ssl_verify,
                'stream': stream,
                'proxies': proxy_url,
            }
            method = 'post' if len(data) > 0 or files else 'get'

            data_keys = [x for x in data.keys()] if isinstance(data, dict) else 'with data'
            log.info('Opening url: %s %s, data: %s', method, url, data_keys)
            response = r.request(method, url, **kwargs)

            status_code = response.status_code
            if response.status_code == requests.codes.ok:
                result = response if stream else response.content
            else:
                response.raise_for_status()
                result = response.content  # shouldn't reach here normally

            with self._lock:
                self.failed_request[host] = 0
        except (OSError, MaxRetryError) as e:
            # Check for HTTP 400 errors from Jackett indexers (TV/Anime-only indexers)
            is_http_400 = (
                hasattr(e, 'response') and
                e.response is not None and
                e.response.status_code == 400
            )
            is_jackett = '/potato/' in url or '/torznab/' in url

            if is_http_400 and is_jackett:
                # Expected error for TV/Anime-only indexers that don't support movie searches
                log.warning('Jackett indexer returned 400 Bad Request (likely TV/Anime-only, no movie support): %s', url.split('?')[0])
            elif show_error:
                log.error('Failed opening url: %s %s', url, traceback.format_exc(0))

            self._record_failure(host, status_code)
            raise

        with self._lock:
            self.last_use[host] = time.time()
        return result
