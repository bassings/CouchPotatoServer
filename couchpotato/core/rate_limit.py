"""Simple in-memory rate limiting middleware for FastAPI.

Uses a sliding window counter per client IP.
Default: 60 requests/minute.
"""
import time
import threading

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit requests per IP using a sliding window."""

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
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

    def _is_rate_limited(self, ip: str) -> bool:
        """Check if IP is rate limited and record the request if not."""
        now = time.time()
        with self._lock:
            self._cleanup_old(ip, now)
            timestamps = self._requests.get(ip, [])
            if len(timestamps) >= self.max_requests:
                return True
            self._requests.setdefault(ip, []).append(now)
            return False

    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else '127.0.0.1'
        if self._is_rate_limited(client_ip):
            return JSONResponse(
                content={'success': False, 'error': 'Rate limit exceeded'},
                status_code=429,
            )
        return await call_next(request)
