"""HTTP request mocking helpers."""
from unittest.mock import MagicMock
import json


class MockHTTPResponse:
    """Configurable fake HTTP response."""

    def __init__(self, body='', status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode('utf-8')

    def json(self):
        return json.loads(self.text)

    def read(self):
        return self.content


class MockHTTPClient:
    """Records requests and returns configured responses."""

    def __init__(self):
        self.requests = []
        self.responses = {}
        self.default_response = MockHTTPResponse('{}')

    def add_response(self, url_pattern, response):
        """Register a response for URLs containing the pattern."""
        self.responses[url_pattern] = response

    def request(self, url, **kwargs):
        self.requests.append({'url': url, **kwargs})
        for pattern, response in self.responses.items():
            if pattern in url:
                return response
        return self.default_response

    def get_requests_for(self, url_pattern):
        return [r for r in self.requests if url_pattern in r['url']]
