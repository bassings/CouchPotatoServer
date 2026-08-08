"""Password guessing is throttled whatever the caller claims to accept.

AC-SEC-42, and AC-A11Y-4's rate-limited case (spec gap 13).

Measured on the tip before this change, with `rate_limit_max = 5`::

    12 x POST /login/  Accept: text/html         -> 302, 302, ... 302   (none limited)
    12 x POST /login/  Accept: application/json  -> 302 x5 then 429     (limited)

`text/html` is the header every browser sends, so the exemption at
`couchpotato/core/rate_limit.py:52-55` exempted precisely the shape an online
password-guessing attack takes and throttled only the shape that does not.
`login_post` runs bcrypt, so it is also the most expensive route in the tree.

The exemption exists for a real reason -- a browsing operator on the LAN must
not be throttled out of their own server -- so it stays, keyed on the PATH
instead. The auth routes are never exempt; everything else still is.

The 429 is produced by the middleware BEFORE the route runs, so it can never
render a login page from the route. That is why the human-readable message
belongs here: without it, a person guessing at their own password gets a JSON
blob with no indication of what to do or when.
"""
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

API_KEY = 'notarealapikey' + '0' * 18
PASSWORD = 'hunter2'
#: bcrypt is deliberately slow (~166 ms a call here) and every attempt below
#: the limit pays it, so the limit is kept small: the assertions are about
#: which requests are counted, not about the number itself.
MAX = 3
#: Hashed once for the module rather than once per test, for the same reason.
STORED_PASSWORD = hash_password(md5(PASSWORD))

BROWSER = {'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}


@pytest.fixture
def settings(tmp_path):
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(Path(__file__).resolve().parents[2]))
    Env.set('data_dir', str(tmp_path))
    Env.set('dev', False)

    data = {
        'username': '',
        'password': STORED_PASSWORD,
        'api_key': API_KEY,
        'auth_required': 1,
        'rate_limit_max': MAX,
        'rate_limit_window': 60,
        'cors_origins': '',
        'ssl_cert': '',
        'ssl_key': '',
    }
    original = Env.setting

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            data[key] = kwargs['value']
            return
        return data.get(key, kwargs.get('default', ''))

    Env.setting = staticmethod(mock_setting)
    try:
        yield data
    finally:
        Env.setting = original
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


def app_client(settings, web_base='/'):
    from couchpotato import create_app
    return TestClient(create_app(API_KEY, web_base), follow_redirects=False)


@pytest.fixture
def client(settings):
    return app_client(settings)


def guess(client, times=MAX * 2, path='/login/'):
    """`times` wrong-password POSTs shaped exactly as a browser sends them."""
    return [client.post(path, data={'username': '', 'password': 'wrong-%d' % i},
                        headers=BROWSER).status_code
            for i in range(times)]


class TestGuessingThroughTheLoginFormIsThrottled:
    """AC-SEC-42."""

    def test_a_browser_shaped_login_post_is_rate_limited(self, client):
        codes = guess(client)

        assert 429 in codes, (
            '%d wrong-password POSTs shaped as a browser sends them were all '
            'answered %r; online password guessing is unthrottled'
            % (len(codes), set(codes))
        )

    def test_it_is_limited_from_the_request_after_the_configured_maximum(self, client):
        codes = guess(client, times=MAX + 3)

        assert codes[:MAX].count(429) == 0, codes
        assert codes[MAX:] == [429] * 3, codes

    def test_a_correct_password_is_throttled_too(self, client):
        """Otherwise the limit is bypassed by whoever eventually guesses right.

        A limiter that only counts FAILURES stops counting at the moment it
        matters, and it also turns the response time into an oracle.
        """
        for i in range(MAX):
            client.post('/login/', data={'username': '', 'password': 'wrong-%d' % i},
                        headers=BROWSER)

        response = client.post('/login/', data={'username': '', 'password': PASSWORD},
                               headers=BROWSER)

        assert response.status_code == 429, response.status_code

    def test_the_credential_oracle_at_getkey_is_limited_as_well(self, client):
        """`/getkey/` returns the api_key for a username and password.

        It is the same guessing attack with a better prize, and it answers GET,
        so a browser reaches it with the same `text/html` header.
        """
        codes = [client.get('/getkey/', params={'u': 'x', 'p': 'wrong-%d' % i},
                            headers=BROWSER).status_code
                 for i in range(MAX + 2)]

        assert 429 in codes, codes

    def test_it_holds_under_a_web_base(self, settings):
        """An install served at `/couchpotato/` must not be exempt.

        A plain `path.startswith('/login')` test would miss it and leave
        exactly the route this exists to protect unthrottled -- on the installs
        most likely to be behind a shared, reachable host.
        """
        Env.set('web_base', '/couchpotato/')
        try:
            client = app_client(settings, web_base='/couchpotato/')
            codes = guess(client, path='/couchpotato/login/')
        finally:
            Env.set('web_base', '/')

        assert 429 in codes, codes


class TestTheOperatorIsNotThrottledOutOfTheirOwnServer:
    """The direction that must not regress. Ranked above the limit itself.

    Removing the exemption wholesale would throttle ordinary browsing: the new
    UI loads partials, and `logs.html` polls every ten seconds. A limit that
    locks the operator out of their own LAN server is a worse defect than the
    one it fixes.
    """

    def test_ordinary_page_navigation_is_still_exempt(self, client):
        codes = [client.get('/', headers=BROWSER).status_code for _ in range(MAX * 10)]

        assert 429 not in codes, (
            'ordinary page loads are now rate limited, which locks a browsing '
            'operator out of their own server'
        )

    def test_static_assets_are_still_exempt(self, client):
        codes = [client.get('/static/anything.css', headers=BROWSER).status_code
                 for _ in range(MAX * 10)]

        assert 429 not in codes, codes


class TestTheRateLimitedResponseIsUsable:
    """AC-A11Y-4's third case, which no login-page render can reach."""

    def _limited(self, client):
        response = None
        for i in range(MAX + 2):
            response = client.post('/login/', data={'username': '', 'password': 'w%d' % i},
                                   headers=BROWSER)
        assert response.status_code == 429, response.status_code
        return response

    def test_it_is_a_page_and_not_a_json_blob(self, client):
        response = self._limited(client)

        assert 'text/html' in response.headers.get('content-type', ''), (
            response.headers.get('content-type')
        )

    def test_it_says_there_were_too_many_attempts_and_when_to_retry(self, client):
        response = self._limited(client)

        text = re.sub(r'<[^>]+>', ' ', response.text)
        text = ' '.join(text.split())
        assert 'too many' in text.lower(), text
        assert re.search(r'\b\d+ (second|minute)', text), (
            'the page does not say when to try again, so the only move left is '
            'to keep pressing the button: %r' % text
        )

    def test_it_carries_a_retry_after_header(self, client):
        response = self._limited(client)

        assert response.headers.get('retry-after', '').isdigit(), (
            response.headers.get('retry-after')
        )

    def test_the_message_is_in_the_pages_live_region(self, client):
        """Same region as the other two login messages (AC-A11Y-4).

        A person using a screen reader must be told why the form did nothing.
        """
        response = self._limited(client)

        match = re.search(
            r'<div[^>]*\bdata-testid="login-message"[^>]*>(.*?)</div>',
            response.text, re.S)
        assert match, 'the rate-limit message is not in the status region'
        opening = response.text[match.start():match.start() + match.group(0).index('>') + 1]
        assert re.search(r'\brole="(alert|status)"', opening), opening

    def test_it_does_not_say_which_of_the_two_was_wrong(self, client):
        """The whole point of one message for both.

        A rate-limit page that says "that password was wrong, and also slow
        down" confirms the username, which is the harder half to guess on an
        install where it is not blank.
        """
        response = self._limited(client)

        match = re.search(
            r'<div[^>]*\bdata-testid="login-message"[^>]*>(.*?)</div>',
            response.text, re.S)
        assert match
        message = ' '.join(re.sub(r'<[^>]+>', ' ', match.group(1)).split()).lower()

        assert 'username' not in message, message
        assert 'was wrong' not in message and 'incorrect' not in message, message
        assert 'not accepted' not in message, message

    def test_it_leaks_no_mechanism(self, client):
        response = self._limited(client)

        match = re.search(
            r'<div[^>]*\bdata-testid="login-message"[^>]*>(.*?)</div>',
            response.text, re.S)
        message = ' '.join(re.sub(r'<[^>]+>', ' ', match.group(1)).split()).lower()
        for forbidden in ('token', 'hmac', 'cookie', 'signature', '429', '302'):
            assert forbidden not in message, (forbidden, message)

    def test_a_json_caller_still_gets_json(self, client):
        """Scripts and the userscript must not start receiving HTML."""
        codes = []
        for i in range(MAX + 2):
            response = client.post('/login/', data={'password': 'w%d' % i},
                                   headers={'accept': 'application/json'})
            codes.append(response)

        last = codes[-1]
        assert last.status_code == 429
        assert last.json()['success'] is False

    def test_a_rate_limited_api_call_is_untouched(self, client):
        """The pre-existing JSON contract for `/api/`, unchanged."""
        for _ in range(MAX):
            client.get('/api/%s/app.available' % API_KEY)
        response = client.get('/api/%s/app.available' % API_KEY)

        assert response.status_code == 429
        assert 'rate limit' in response.json()['error'].lower()


class TestTheRefusalSurvivesAFailureToRenderIt:
    """A degraded install must still get a 429, not a 500.

    The fallback exists because the comment above it says so: "raising here
    would turn a refusal into a 500 with a traceback, on the one path an
    attacker controls". The fallback ITSELF raised.

    `log_suppressed`'s signature is `(log_method, key, message, *args,
    window=..., now=None)` -- it has no `exc_info`, because it forwards `*args`
    to the logger so `PrivacyFilter` can scrub them. Passing `exc_info=True`
    raised `TypeError` inside the `except` that was supposed to contain the
    failure, so a render error became exactly the 500-with-traceback the
    comment forbids, on an unauthenticated path, with nothing in the
    application log. The uvicorn traceback that does appear is unbounded, which
    is L1 arriving through a different door.

    Executed before the fix::

        log_suppressed(log.error, 'k', 'msg', exc_info=True)
        -> TypeError: log_suppressed() got an unexpected keyword argument 'exc_info'
    """

    def test_a_render_failure_still_returns_429_with_retry_after(self, client, monkeypatch):
        import couchpotato

        def explode(*args, **kwargs):
            raise RuntimeError('login.html is missing from the image')

        # Patch `couchpotato`, NOT `couchpotato.core.rate_limit`. The call site
        # is a FUNCTION-LOCAL `from couchpotato import render_login_page`, so
        # the name is resolved from the source module at call time and a patch
        # on the rate_limit namespace never participates. The first version of
        # this test did exactly that and passed while touching nothing.
        # Warm up to the limit FIRST, with rendering still working: the login
        # route renders the same page on a rejected attempt, so patching before
        # this loop breaks the warm-up rather than the refusal, and the test
        # fails for the wrong reason.
        for i in range(MAX):
            client.post('/login/', data={'password': 'w%d' % i},
                        headers={'accept': 'text/html'})

        monkeypatch.setattr(couchpotato, 'render_login_page', explode)

        response = client.post('/login/', data={'password': 'final'},
                               headers={'accept': 'text/html'})

        assert response.status_code == 429, (
            'a failure to RENDER the refusal turned the refusal itself into %d. '
            'The fallback exists precisely to stop that.' % response.status_code
        )
        assert response.headers.get('retry-after'), (
            'the 429 lost its Retry-After, so the caller cannot tell when to '
            'come back'
        )


class TestARateLimitedSignOutDoesNotShowTheSignInForm:
    """Finding M7. Being throttled while signing OUT is not a failed sign-in.

    `/logout` is in `_ALWAYS_LIMITED_ROUTES` (correctly: under D1 it rotates
    the shared secret, so it is a state-changing route worth throttling). But
    the refusal rendered `reason='rate_limited'`, whose copy reads "Too many
    sign-in attempts from this address", on the standard sign-in page.

    So an operator who clicks Sign out is shown a SIGN-IN FORM and told they
    made too many sign-in attempts, which they did not. The page looks exactly
    like a completed sign-out while every session on every device is still
    valid. That is the same lie
    `test_the_failure_page_does_not_show_a_sign_in_form` refuses on the
    sign-out 500 path, arriving through the limiter instead.

    The `signout_failed` mode already exists for that path; this reuses it.
    """

    def _limited_logout(self, client):
        for i in range(MAX):
            client.post('/login/', data={'password': 'w%d' % i},
                        headers={'accept': 'text/html'})
        return client.post('/logout/', headers={'accept': 'text/html'})

    def test_it_is_still_refused(self, client):
        assert self._limited_logout(client).status_code == 429

    def test_it_does_not_render_a_sign_in_form(self, client):
        response = self._limited_logout(client)

        assert 'name="password"' not in response.text, (
            'a throttled sign-out rendered the sign-in form, which looks like '
            'a completed sign-out while every session is still valid')

    def test_it_does_not_blame_the_operator_for_sign_in_attempts(self, client):
        response = self._limited_logout(client)

        assert 'sign-in attempts' not in response.text.lower(), (
            'the throttled sign-out told the operator they had made too many '
            'SIGN-IN attempts; they were signing out')

    def test_it_says_the_sessions_are_still_signed_in(self, client):
        """The operator's actual question is "am I signed out?" -- no."""
        response = self._limited_logout(client)

        assert 'still signed in' in response.text.lower(), (
            'the page never says the sign-out did not happen, which is the '
            'one fact the operator needs')

    def test_a_throttled_login_still_gets_the_sign_in_copy(self, client):
        """Counterweight: the /login copy must not change."""
        for i in range(MAX):
            client.post('/login/', data={'password': 'w%d' % i},
                        headers={'accept': 'text/html'})
        response = client.post('/login/', data={'password': 'x'},
                               headers={'accept': 'text/html'})

        assert response.status_code == 429
        assert 'sign-in attempts' in response.text.lower(), response.text[:400]


class TestViewingTheLoginPageDoesNotSpendACredentialAttempt:
    """The limit counts credential ATTEMPTS, not page views.

    `_is_auth_route` keyed on the path alone, so `GET /login/` -- rendering the
    form -- consumed a slot. With `rate_limit_max=1` the browser's initial GET
    takes the only one and the correct-password POST that follows is refused
    for the whole window. More generally, opening or refreshing the form
    silently reduces how many times you may try your own password.

    `/getkey` is deliberately NOT in this exemption: it is a GET that returns
    the api_key for a username and password, so it IS a credential check
    whatever the method.
    """

    def test_a_get_of_the_login_page_leaves_the_attempt_budget_intact(self, client):
        # `accept: text/html`, because this models a BROWSER opening the form,
        # which is the reported defect. A GET of /login/ is no longer counted
        # as a credential attempt, but it is still subject to the GENERAL
        # limit like any other page -- and the general limit exempts ordinary
        # navigation. Both are deliberate: not spending a password attempt is
        # the fix; leaving page loads entirely unlimited would not be.
        html = {'accept': 'text/html'}
        for _ in range(MAX + 3):
            assert client.get('/login/', headers=html).status_code == 200

        response = client.post('/login/', data={'password': 'wrong'},
                               headers={'accept': 'text/html'})

        assert response.status_code != 429, (
            'viewing the login form spent the credential-attempt budget, so a '
            'user who refreshed the page cannot try their own password'
        )

    def test_posting_credentials_is_still_limited(self, client):
        """The counterweight: the exemption must not disarm the limiter."""
        codes = [client.post('/login/', data={'password': 'w%d' % i},
                             headers={'accept': 'text/html'}).status_code
                 for i in range(MAX + 2)]

        assert 429 in codes, (
            'the login POST is no longer rate limited at all: %s' % codes)

    def test_getkey_stays_limited_on_get(self, client):
        """`/getkey` returns the api_key for credentials, so a GET of it IS an
        attempt. Exempting it by method would open the exact door AC-SEC-42
        closed."""
        codes = [client.get('/getkey/').status_code for _ in range(MAX + 2)]

        assert 429 in codes, (
            '/getkey/ is no longer limited on GET: %s' % codes)


class TestTheLocalhostExemptionDoesNotCoverAuthRoutes:
    """High finding on #229: deployment topology could disable the throttle.

    `dispatch` computes `auth_route` up front precisely so credential routes
    are counted even when the request looks like an ordinary page load -- and
    then exempted every request whose peer is 127.0.0.1 before any counting
    happened.

    Nothing in this tree configures uvicorn's `proxy_headers` or
    `forwarded_allow_ips`, so `request.client.host` is the TCP peer. On the
    ordinary self-hosted shape -- nginx, Caddy or Traefik on the SAME host, or
    a proxy container talking to a port-mapped app -- every remote request
    arrives as 127.0.0.1. So `POST /login/` was unthrottled for the entire
    internet, with bcrypt's ~166ms the only brake.

    Measured before the fix, driving the real app with `client=('127.0.0.1',
    40000)`: 15 consecutive `POST /login/`, not one 429.

    The rest of the exemption STAYS. It exists so the UI on the same host is
    not throttled while loading partials and polling logs, and removing it
    would throttle ordinary browsing. Only the credential routes are carved
    out of it.

    The existing suite could not catch this: Starlette's `TestClient` reports
    a scope client host of `testclient`, so the exemption path was never
    exercised. Hence the explicit `client=` below.
    """

    def _local(self, settings):
        from couchpotato import create_app
        # `client=` is the whole point: the default TestClient reports a host
        # of `testclient`, which is not in _LOCALHOST_IPS, so every other test
        # in this file sails past the exemption without touching it.
        return TestClient(create_app(API_KEY, '/'), follow_redirects=False,
                          client=('127.0.0.1', 40000))

    def test_a_login_post_from_localhost_is_still_throttled(self, settings):
        local = self._local(settings)

        codes = [local.post('/login/', data={'password': 'w%d' % i},
                            headers={'accept': 'text/html'}).status_code
                 for i in range(MAX + 3)]

        assert 429 in codes, (
            'password guessing from 127.0.0.1 is unlimited, so behind a '
            'same-host reverse proxy the throttle does not exist: %s' % codes)

    def test_getkey_from_localhost_is_still_throttled(self, settings):
        local = self._local(settings)

        codes = [local.get('/getkey/').status_code for _ in range(MAX + 3)]

        assert 429 in codes, codes

    def test_same_host_xhr_stays_exempt(self, settings):
        """The counterweight, and the reason the exemption exists at all.

        `accept: */*`, NOT `text/html`. A page NAVIGATION is already exempted
        earlier by the HTML rule, so asserting on one proves nothing about
        this branch -- the first version of this test did exactly that and
        stayed green when the localhost exemption was deleted entirely.

        What the exemption actually protects is the UI's own XHR: htmx
        fragment loads and the ten-second log poll, which the browser sends
        with `*/*`. Throttling those would be a worse defect than the one
        being fixed.
        """
        local = self._local(settings)

        codes = [local.get('/partial/movies', headers={'accept': '*/*'}).status_code
                 for _ in range(MAX + 5)]

        assert 429 not in codes, (
            'the UI\'s own same-host XHR is now throttled, so fragment loads '
            'and the log poll break: %s' % codes)


class TestTheCounterIsSerialised:
    """The limiter's read-modify-write must stay inside the lock.

    `_is_rate_limited` reads the timestamp list, decides, and appends -- and
    FastAPI runs sync handlers in a threadpool, so two requests racing that
    sequence without a lock could each see `len < max` and both be admitted.
    The window would then hold `max + 1` entries and the limit would be off by
    one per race, which for a credential route is a real weakening.

    It is correct today because the whole sequence sits in `with self._lock`.
    Asserted STRUCTURALLY rather than by spawning threads: a race test that
    passes proves only that the race did not happen to occur on this run, and
    would be exactly the intermittent-red this suite has already been
    corrected for once.
    """

    def test_the_read_modify_write_is_inside_the_lock(self):
        import inspect
        import textwrap

        from couchpotato.core.rate_limit import RateLimitMiddleware

        source = textwrap.dedent(inspect.getsource(RateLimitMiddleware._is_rate_limited))
        body = source[source.index('now = time.time()'):]
        lock_at = body.index('with self._lock:')

        for statement in ('self._requests.get(ip', 'self._requests.setdefault(ip',
                          'self._cleanup_old(ip'):
            assert body.index(statement) > lock_at, (
                '%r happens OUTSIDE `with self._lock:`, so two threadpool '
                'requests can both read a count below the limit and both be '
                'admitted -- the limit is then off by one per race, on a '
                'credential route.' % statement)
