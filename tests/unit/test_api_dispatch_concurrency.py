"""Regression test for REG-002: blocking API handlers must not stall the
event loop.

Every FastAPI route dispatches to the synchronous ``callApiHandler``. Before
the fix, that call happened directly on the event loop, so a slow handler
(e.g. the chart scrapers) blocked every other concurrent request for its
entire duration. This test proves a fast request completes promptly even
while a slow request registered through the same dispatcher is still
in-flight.
"""
import asyncio
import os
import time

import pytest
from httpx import ASGITransport, AsyncClient

from couchpotato.api import (
    addApiView,
    api,
    api_docs,
    api_docs_missing,
    api_locks,
    api_nonblock,
)
from couchpotato.environment import Env


@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """Set up minimal Env for testing (mirrors test_fastapi_web.py)."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    Env.set('web_base', '/')
    Env.set('api_base', '/api/testkey123/')
    Env.set('static_path', '/static/')
    Env.set('app_dir', os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    Env.set('dev', False)

    settings_data = {
        'username': '',
        'password': '',
        'api_key': 'testkey123',
        'dark_theme': False,
    }

    original_setting = Env.setting

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            settings_data[key] = kwargs['value']
            return
        if key in settings_data:
            return settings_data[key]
        return kwargs.get('default', '')

    Env.setting = staticmethod(mock_setting)

    yield settings_data

    Env.setting = original_setting
    api.clear()
    api.update(old_api)
    api_locks.clear()
    api_locks.update(old_locks)
    api_nonblock.clear()
    api_nonblock.update(old_nonblock)
    api_docs.clear()
    api_docs.update(old_docs)
    api_docs_missing.clear()
    api_docs_missing.extend(old_missing)


@pytest.fixture
def app(setup_env):
    from couchpotato import create_app
    return create_app('testkey123', '/')


def test_slow_handler_does_not_block_concurrent_fast_handler(app):
    """A slow blocking API handler must not stall an unrelated concurrent request.

    Fails on the pre-fix code: callApiHandler runs synchronously on the event
    loop inside _dispatch_api, so the fast request queues up behind the slow
    one and only returns after ~1.5s (instead of near-instantly).

    No pytest-asyncio plugin is installed in this project, so the coroutine
    is driven directly via asyncio.run() rather than an async test function.
    """
    SLOW_SECONDS = 1.5

    def slow_sleep():
        time.sleep(SLOW_SECONDS)
        return {'success': True, 'slow': True}

    def fast_ping():
        return {'success': True, 'fast': True}

    addApiView('slowtest.sleep', slow_sleep)
    addApiView('fasttest.ping', fast_ping)

    async def run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url='http://testserver') as client:
            # Both elapsed times are measured from this single shared start
            # point (not from inside each coroutine) — that's what makes the
            # assertion meaningful. If the event loop were fully blocked by
            # slow_sleep's inline time.sleep(), call_fast's own
            # `await asyncio.sleep(0.2)` would never get a chance to run
            # until the slow request finished, so fast_elapsed would end up
            # close to SLOW_SECONDS too. Measuring per-coroutine elapsed time
            # from *inside* each coroutine (i.e. only around the client.get
            # call) would hide that: once unblocked, the actual GET is fast
            # regardless, and the test would pass even against the buggy code.
            start = time.monotonic()

            async def call_slow():
                resp = await client.get('/api/testkey123/slowtest.sleep')
                return resp, time.monotonic() - start

            async def call_fast():
                await asyncio.sleep(0.2)
                resp = await client.get('/api/testkey123/fasttest.ping')
                return resp, time.monotonic() - start

            return await asyncio.gather(call_slow(), call_fast())

    (slow_resp, slow_elapsed), (fast_resp, fast_elapsed) = asyncio.run(run())

    assert slow_resp.status_code == 200
    assert slow_resp.json() == {'success': True, 'slow': True}
    assert fast_resp.status_code == 200
    assert fast_resp.json() == {'success': True, 'fast': True}

    assert slow_elapsed >= SLOW_SECONDS
    # Generous margin: the fast request should return in well under the slow
    # handler's sleep duration, proving it wasn't queued up behind it on the
    # event loop.
    assert fast_elapsed < 1.0, (
        'fast request took %.2fs — it appears to have been blocked behind '
        'the slow handler on the event loop (REG-002 regression)' % fast_elapsed
    )
