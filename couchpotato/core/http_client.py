"""Standalone HTTP client extracted from Plugin base class.

Provides retry logic via tenacity, rate limiting per host, and proxy support.
"""

import time
import traceback
from urllib.parse import quote, urlparse
from urllib.request import getproxies

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from urllib3 import Timeout
from urllib3.exceptions import MaxRetryError

from couchpotato.core.helpers.encoding import ss
from couchpotato.core.helpers.variable import isLocalIP
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env

log = CPLog(__name__)

DEFAULT_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:45.0) Gecko/20100101 Firefox/45.0'
DISABLE_DURATION = 900  # 15 minutes
MAX_FAILURES_BEFORE_DISABLE = 5


class HttpClient:
    """HTTP client with per-host rate limiting, failure tracking, and proxy support."""

    def __init__(self, time_between_calls=0, user_agent=None):
        self.time_between_calls = time_between_calls
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.last_use = {}
        self.last_use_queue = {}
        self.failed_request = {}
        self.failed_disabled = {}
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
            loc = f"{proxy_username}:{proxy_password}@{proxy_server}" if proxy_username else proxy_server
            return {"http": f"http://{loc}", "https": f"https://{loc}"}
        return getproxies()

    def _check_disabled(self, host, show_error=True):
        """Check if a host is temporarily disabled due to failures."""
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
        """Enforce per-host rate limiting."""
        if self.time_between_calls == 0:
            return

        try:
            if host not in self.last_use_queue:
                self.last_use_queue[host] = []

            self.last_use_queue[host].append(url)

            while not self._shutting_down:
                wait = (self.last_use.get(host, 0) - time.time()) + self.time_between_calls

                if self.last_use_queue[host][0] != url:
                    time.sleep(0.1)
                    continue

                if wait > 0:
                    log.debug('Waiting for rate limit, %d seconds', max(1, wait))
                    time.sleep(min(wait, 30))
                else:
                    self.last_use_queue[host] = self.last_use_queue[host][1:]
                    self.last_use[host] = time.time()
                    break
        except Exception:
            log.error('Failed handling waiting call: %s', traceback.format_exc())
            time.sleep(self.time_between_calls)

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
            IOError/MaxRetryError/Timeout: On connection failure.
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
                'verify': False,
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

            self.failed_request[host] = 0
        except (OSError, MaxRetryError, Timeout):
            if show_error:
                log.error('Failed opening url: %s %s', url, traceback.format_exc(0))

            self._record_failure(host, status_code)
            raise

        self.last_use[host] = time.time()
        return result
