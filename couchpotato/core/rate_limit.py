"""Simple in-memory rate limiting middleware for FastAPI.

Uses a sliding window counter per client IP.
Default: 60 requests/minute.
"""
import math
import time
import threading
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from couchpotato.core.logger import CPLog, log_suppressed

log = CPLog(__name__)


def _wait_phrase(seconds: int) -> str:
    """`'1 second'` / `'45 seconds'` / `'2 minutes'`.

    Rendered here rather than in the copy so the message can say WHEN without
    the copy having to know about pluralisation, and so "1 seconds" cannot
    reach a page.
    """
    if seconds >= 120:
        return '%d minutes' % int(math.ceil(seconds / 60.0))
    return '%d second%s' % (seconds, '' if seconds == 1 else 's')


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit requests per IP using a sliding window."""

    _LOCALHOST_IPS = ('127.0.0.1', '::1', 'localhost')

    def __init__(self, app, max_requests: int = 600, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _cleanup_old(self, ip: str, now: float):
        """Remove timestamps outside the current window."""
        if ip in self._requests:
            cutoff = now - self.window_seconds
            self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]
            if not self._requests[ip]:
                del self._requests[ip]

    def _is_rate_limited(self, ip: str):
        """Seconds to wait if `ip` is over the limit, else None (and recorded).

        Returns the wait rather than a bare bool so the refusal can tell the
        person WHEN to try again. A slot frees when the oldest request still
        inside the window falls out of it.
        """
        now = time.time()
        with self._lock:
            self._cleanup_old(ip, now)
            timestamps = self._requests.get(ip, [])
            if len(timestamps) >= self.max_requests:
                return max(1, int(math.ceil(min(timestamps) + self.window_seconds - now)))
            self._requests.setdefault(ip, []).append(now)
            return None

    _EXEMPT_PREFIXES = ('/static/', '/favicon.ico', '/file.cache/')

    #: Routes the HTML exemption below must never cover, whatever the caller
    #: says it accepts.
    #:
    #: The exemption used to key on `Accept: text/html`, which is the header
    #: EVERY BROWSER SENDS -- so it exempted precisely the shape an online
    #: password-guessing attack takes and throttled only the shape that does
    #: not. Measured with `rate_limit_max = 5`: twelve consecutive
    #: `POST /login/` with `Accept: text/html` all returned 302 and none
    #: returned 429, while `Accept: application/json` was limited from the
    #: sixth. `login_post` also runs bcrypt, so it is the most expensive route
    #: in the tree to hammer.
    #:
    #: The exemption itself STAYS. Deleting it would throttle ordinary browsing
    #: -- the UI loads partials and `logs.html` polls every ten seconds -- and
    #: locking the operator out of their own LAN server is a worse defect than
    #: the one being fixed. Only the key changes, from the header to the path.
    _ALWAYS_LIMITED_ROUTES = ('/login', '/logout', '/getkey')

    def _is_auth_route(self, path: str) -> bool:
        """Is `path` one of the credential-checking routes?

        Matched on the LAST SEGMENT, not with `startswith`. Every route is
        served under `web_base`, so on an install at `/couchpotato/` a prefix
        test would miss `/couchpotato/login/` and leave exactly the route this
        exists to protect unthrottled -- on the installs most likely to be
        behind a shared, reachable host.
        """
        return '/' + path.rstrip('/').rsplit('/', 1)[-1] in self._ALWAYS_LIMITED_ROUTES

    def _refusal(self, request, path: str, retry_after: int):
        """The 429, as a page when a person is reading it and JSON otherwise.

        This response is produced BEFORE the route runs, so the login route can
        never render it -- which is why AC-A11Y-4's rate-limited case has to be
        met here. Without it, somebody guessing at their own password receives
        a JSON blob with nothing about what happened or when to retry.

        Deliberately says nothing about whether the username or the password
        was the wrong one: the limit counts attempts, and a message that
        distinguished them would confirm a username to whoever tripped it.
        """
        headers = {'Retry-After': str(retry_after)}

        if self._is_auth_route(path) and 'text/html' in request.headers.get('accept', ''):
            try:
                from couchpotato import render_login_page

                response = render_login_page(
                    reason='rate_limited', status_code=429,
                    message_values={'wait': _wait_phrase(retry_after)})
                response.headers['Retry-After'] = str(retry_after)
                return response
            except Exception:
                # Falling back to JSON is worse for the reader but it is still
                # a 429; raising here would turn a refusal into a 500 with a
                # traceback, on the one path an attacker controls. Bounded,
                # because this is reachable without credentials.
                # `traceback.format_exc()` as an ARG, not `exc_info=True`:
                # `log_suppressed` is `(log_method, key, message, *args,
                # window=..., now=None)` and forwards `*args` to the logger so
                # `PrivacyFilter` can scrub them. It has no `exc_info`, so
                # passing one raised `TypeError` INSIDE the except that exists
                # to contain the failure -- turning a render error into exactly
                # the 500-with-unbounded-traceback the comment above forbids,
                # on the one path an unauthenticated caller controls, with
                # nothing in the application log.
                log_suppressed(log.error, 'rate_limit_page_render_failed',
                               'Could not render the rate-limited page; sending '
                               'JSON instead. The refusal itself is unaffected. %s',
                               traceback.format_exc())

        return JSONResponse(
            content={'success': False, 'error': 'Rate limit exceeded'},
            status_code=429,
            headers=headers,
        )

    async def dispatch(self, request, call_next):
        path = request.scope.get('path', '')
        auth_route = self._is_auth_route(path)

        # Don't rate-limit static assets or cached files.
        if any(path.startswith(p) for p in self._EXEMPT_PREFIXES):
            return await call_next(request)

        # Don't rate-limit HTML page loads (non-API browser navigation) --
        # unless the page load is a credential check.
        if not auth_route:
            accept = request.headers.get('accept', '')
            if 'text/html' in accept and '/api/' not in path:
                return await call_next(request)

        client_ip = request.client.host if request.client else '127.0.0.1'

        # Exempt localhost requests (UI runs on same host)
        if client_ip in self._LOCALHOST_IPS:
            return await call_next(request)

        retry_after = self._is_rate_limited(client_ip)
        if retry_after is not None:
            return self._refusal(request, path, retry_after)
        return await call_next(request)
