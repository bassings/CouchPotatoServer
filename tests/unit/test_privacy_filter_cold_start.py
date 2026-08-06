"""Pin the PrivacyFilter api-key redaction against a cold start."""
import logging
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
