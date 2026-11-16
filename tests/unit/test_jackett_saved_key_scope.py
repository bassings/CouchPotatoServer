"""SEC-004 P2, AC-SEC-9 rule (a): the saved Jackett key only ever goes to the saved URL.

``jackettTest`` and ``jackettSync`` used to combine a request-supplied
``jackett_url`` with the saved ``jackett_api_key``, so a request that named any
host sent the stored key to it. Here the real provider reads a real ``Settings``
over a temporary ``config.ini``; only the network call (``urlopen``) is
replaced, by a recorder, so what each request would have sent is observable.

Hosts are ``.invalid`` and every credential is a ``placeholder-`` string.
"""
import pytest

from couchpotato.environment import Env
from tests.helpers.combine_groups import group_settings, sha

SAVED_URL = 'http://saved-jackett.invalid:9117'
SAVED_KEY = 'placeholder-saved-jackett-key'
OTHER_URL = 'http://caller-supplied.invalid:9117'
OTHER_KEY = 'placeholder-callers-own-key'

INDEXERS_XML = (
    '<indexers><indexer id="alpha" configured="true"><title>Alpha</title></indexer></indexers>'
)

OPERATIONS = ('jackettTest', 'jackettSync')


@pytest.fixture
def world(tmp_path, monkeypatch):
    stored = {'torrentpotato': {'jackett_url': SAVED_URL, 'jackett_api_key': SAVED_KEY}}
    with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
        monkeypatch.setattr(Env, '_settings', settings)
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        provider = TorrentPotato.__new__(TorrentPotato)
        requested = []

        def recording_urlopen(url, **kwargs):
            requested.append(url)
            return INDEXERS_XML

        monkeypatch.setattr(provider, 'urlopen', recording_urlopen)
        yield settings, provider, requested


def run(provider, operation, **params):
    return getattr(provider, operation)(**params)


@pytest.mark.parametrize('operation', OPERATIONS)
class TestASuppliedUrlNeedsItsOwnKey:

    def test_a_url_without_a_key_is_refused_before_any_request(self, world, operation):
        settings, provider, requested = world
        before = sha(settings.file)

        result = run(provider, operation, jackett_url=OTHER_URL)

        assert result['success'] is False
        assert requested == [], 'a request was made with the saved key'
        assert sha(settings.file) == before

    def test_the_refusal_does_not_echo_the_url_or_either_key(self, world, operation):
        _, provider, _ = world

        result = run(provider, operation, jackett_url=OTHER_URL)

        for private in (OTHER_URL, 'caller-supplied', SAVED_KEY, SAVED_URL):
            assert private not in str(result)

    def test_the_saved_url_named_again_without_a_key_is_still_refused(self, world, operation):
        """A request that supplies a URL supplies its own key. There is no
        exception for a URL that happens to equal the saved one."""
        _, provider, requested = world

        result = run(provider, operation, jackett_url=SAVED_URL)

        assert result['success'] is False
        assert requested == []

    def test_a_blank_key_does_not_count_as_a_key(self, world, operation):
        _, provider, requested = world

        result = run(provider, operation, jackett_url=OTHER_URL, jackett_api_key='')

        assert result['success'] is False
        assert requested == []

    def test_a_url_with_its_own_key_is_used_with_that_key_and_never_the_saved_one(
            self, world, operation):
        _, provider, requested = world

        run(provider, operation, jackett_url=OTHER_URL, jackett_api_key=OTHER_KEY)

        assert len(requested) == 1
        assert requested[0].startswith(OTHER_URL)
        assert OTHER_KEY in requested[0]
        assert SAVED_KEY not in requested[0]

    @pytest.mark.parametrize('url, key', [
        (['a', 'b'], OTHER_KEY),
        (OTHER_URL, ['a', 'b']),
        (OTHER_URL, {'k': 'v'}),
    ])
    def test_a_non_string_value_is_refused_before_any_request(self, world, operation, url, key):
        """`getParams` can hand a route a list or a dict for a repeated or
        bracketed key, and an f-string would write its repr into the request."""
        _, provider, requested = world

        result = run(provider, operation, jackett_url=url, jackett_api_key=key)

        assert result['success'] is False
        assert requested == []


@pytest.mark.parametrize('operation', OPERATIONS)
class TestTheFirstPartyCallersStillWork:
    """The Settings button and the wizard both send no parameters."""

    def test_no_parameters_uses_the_saved_url_with_the_saved_key(self, world, operation):
        _, provider, requested = world

        result = run(provider, operation)

        assert result['success'] is True
        assert len(requested) == 1
        assert requested[0].startswith(SAVED_URL)
        assert SAVED_KEY in requested[0]

    def test_a_key_alone_goes_to_the_saved_url_and_the_saved_key_is_not_used(
            self, world, operation):
        _, provider, requested = world

        run(provider, operation, jackett_api_key=OTHER_KEY)

        assert len(requested) == 1
        assert requested[0].startswith(SAVED_URL)
        assert OTHER_KEY in requested[0]
        assert SAVED_KEY not in requested[0]
