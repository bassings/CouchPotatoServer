"""Pin the PrivacyFilter api-key redaction against a cold start."""
import logging
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, '.')
sys.path.insert(0, 'libs')

from couchpotato.core.logger import PrivacyFilter

KEY = 'deadbeefdeadbeefdeadbeefdeadbeef'


def _record(msg):
    return logging.LogRecord('t', logging.INFO, 'p', 1, msg, None, None)


def test_the_key_is_redacted_even_if_the_first_record_predates_it():
    """A record logged before the api_key exists must not disable redaction.

    The filter used to cache on `is None`, so the empty string it stored on a
    pre-key record was never re-read: every later line carrying the key in a
    URL path went out verbatim, for the life of the process. The E2E harness
    now attaches a console handler and CI uploads that stream, so this is
    load-bearing.
    """
    f = PrivacyFilter()
    settings = {'api_key': ''}

    with patch('couchpotato.environment.Env') as env:
        # Env.get('dev') MUST be falsy. On a bare MagicMock it is truthy, and
        # PrivacyFilter.filter then returns immediately without redacting
        # anything -- so this test would fail (or pass) for a reason unrelated
        # to the caching it exists to pin.
        env.get.side_effect = lambda name, **kw: {'dev': False}.get(name, False)
        env.setting.side_effect = lambda name, **kw: settings.get(name)
        early = _record('starting up, no key yet')
        f.filter(early)

        # The key is generated after startup, as runner.py does.
        settings['api_key'] = KEY
        later = _record('url http://h/api/%s/movie.list' % KEY)
        f.filter(later)

    assert KEY not in later.msg, (
        'the api_key leaked because the filter cached an empty key from an '
        'earlier record: %s' % later.msg
    )
    assert 'API_KEY' in later.msg


def test_a_concurrent_record_is_still_redacted_while_the_key_is_being_read():
    """No record may escape unredacted because another thread is mid-lookup.

    This replaces a test that pinned a recursion which cannot happen. The
    belief was that `Env.setting` -> `Settings.get` logs when the property is
    absent, so reading the key from inside the filter re-enters it; measured
    against a fake written to log, that produced 124 nested lookups. Against
    the REAL `Settings.get` it produces one: its only log is a META-option
    warning that `api_key` never triggers, and the absent path returns through
    `except Exception` silently. The recursion was manufactured by the fixture
    that found it.

    The guard added for it was not free. A single shared flag meant a second
    thread took the "someone is already reading" branch, left `_api_key`
    falsy, and skipped the redaction entirely -- emitting the key verbatim.
    That is what this test pins, because it is the property that matters and
    it is the one nothing was checking.
    """
    key = 'SUPERSECRETAPIKEY0123456789abcdef'
    f = PrivacyFilter()
    lookup_started = threading.Event()
    concurrent_done = threading.Event()
    seen = {'n': 0}
    seen_lock = threading.Lock()

    class SlowEnv:
        @staticmethod
        def get(name, **kw):
            return False if name == 'dev' else None

        @staticmethod
        def setting(name, **kw):
            with seen_lock:
                seen['n'] += 1
                first = seen['n'] == 1
            if first:
                # Only the WARMER blocks, and it blocks on an event rather
                # than a sleep so the window is deterministic. A sleep made
                # this pass whenever the main thread was descheduled past it.
                # Later callers return at once: without the buggy guard the
                # concurrent record does its own lookup, and if it blocked
                # too the test would deadlock rather than discriminate.
                lookup_started.set()
                concurrent_done.wait(timeout=5)
            return key

    with patch('couchpotato.environment.Env', SlowEnv):
        warmer = threading.Thread(target=lambda: f.filter(_record('warming the cache')))
        warmer.start()
        try:
            assert lookup_started.wait(timeout=5), 'the lookup never started'
            concurrent = _record('GET /api/%s/movie.list' % key)
            f.filter(concurrent)
        finally:
            concurrent_done.set()
            warmer.join(timeout=5)

    assert key not in concurrent.msg, (
        'a record was emitted with the api_key verbatim because another thread '
        'was reading the key at the time: %s' % concurrent.msg
    )
    assert 'API_KEY' in concurrent.msg
