"""Pin the PrivacyFilter api-key redaction against a cold start."""
import logging
import os
import sys
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


def test_looking_up_the_key_does_not_re_enter_the_filter():
    """The lookup must not recurse through the handler it is attached to.

    `Settings.get` logs at DEBUG when a property is not yet stored, and this
    filter sits on the handler that record passes through, so reading the key
    from inside the filter re-enters the filter. Measured with the key absent
    and debug logging on: 124 nested lookups for a SINGLE record, ending in a
    RecursionError the filter's own `except` swallows.

    With the old `is None` cache that happened once per process. Re-reading
    while falsy -- the fix for the cold-start leak -- made it happen on every
    record, which is a cost that fix should not carry. Two guards, one test.
    """
    calls = {'n': 0}
    f = PrivacyFilter()

    class FakeEnv:
        @staticmethod
        def get(name, **kw):
            return False if name == 'dev' else None

        @staticmethod
        def setting(name, **kw):
            calls['n'] += 1
            # Faithful to Settings.getProperty, which logs when absent.
            logging.getLogger('probe').debug('Property "%s" not yet stored', name)
            return None

    with patch('couchpotato.environment.Env', FakeEnv):
        handler = logging.StreamHandler(open(os.devnull, 'w'))
        handler.addFilter(f)
        log = logging.getLogger('probe')
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)
        try:
            calls['n'] = 0
            log.debug('a record logged before the key exists')
        finally:
            log.removeHandler(handler)

    assert calls['n'] == 1, (
        'the api_key lookup re-entered the filter %d times for one record'
        % calls['n']
    )
