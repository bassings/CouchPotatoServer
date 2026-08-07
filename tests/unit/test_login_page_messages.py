"""The login page says WHY it is showing. AC-A11Y-4/5/6, AC-DESIGN-3/5.

Three things converge on this page and, before this change, none of them was
visible:

  * the operator pressed sign out (which under D1 ends every session on every
    device, so the confirmation has to say that and not "this browser");
  * their session ended -- expired, revoked, or invalidated by the upgrade
    D5 describes, where the reassurance the operator needs is that their
    EXISTING password still works;
  * their last attempt was rejected. `login_post` used to answer a wrong
    password with `RedirectResponse(url=web_base)`, identical to a successful
    one, so the failure was discarded entirely and the browser was bounced
    back to a login page with nothing on it.

A user who has never logged in, and a user with a valid session, must see
none of them.

Everything here drives the real routes. The reason strings live in one place
(`couchpotato.LOGIN_MESSAGES`) and are read back out of the RENDERED page, so a
message that stops reaching the template fails here rather than passing on the
strength of the constant existing.
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
from session_helper import (  # noqa: E402
    SESSION_COOKIE_NAME,
    TEST_SESSION_SECRET,
    session_cookie,
    stored_session_secret,
)

PASSWORD = 'hunter2'
API_KEY = 'notarealapikey' + '0' * 18

#: WCAG-visible copy must not leak the mechanism (AC-DESIGN-3). `302` and `401`
#: are in the list because "HTTP 302" is the shape this page's failure used to
#: take, and a status code tells the person reading it nothing they can act on.
FORBIDDEN_IN_COPY = ('token', 'hmac', 'cookie', 'signature', '401', '302')


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
    Env.set('app_dir', os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    Env.set('dev', False)
    Env.set('data_dir', str(tmp_path))

    data = {
        'username': '',
        'password': hash_password(md5(PASSWORD)),
        'api_key': API_KEY,
        'auth_required': 1,
        'rate_limit_max': 0,
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
    yield data

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


@pytest.fixture
def client(settings):
    from couchpotato import create_app
    return TestClient(create_app(API_KEY, '/'), follow_redirects=False)


def _message_region(html: str):
    """The rendered status/alert region's (role, visible text), or None.

    Parsed out of the real response rather than matched as a substring
    anywhere on the page: a message rendered outside its live region would
    otherwise satisfy a naive `in` assertion while announcing nothing.
    """
    match = re.search(
        r'<div[^>]*\bdata-testid="login-message"[^>]*>(.*?)</div>', html, re.S)
    if not match:
        return None
    opening = html[match.start():match.start() + match.group(0).index('>') + 1]
    role = re.search(r'\brole="([^"]+)"', opening)
    text = re.sub(r'<[^>]+>', ' ', match.group(1))
    return (role.group(1) if role else None), ' '.join(text.split())


def _rate_limited_page(settings):
    """A real 429, from the real middleware, on a second app.

    The `rate_limited` message is the only one no login ROUTE can produce: the
    middleware answers before the route runs (spec gap 13). Driving it here
    keeps it inside the same "every message is really rendered" guard as the
    other five, which is what stops copy nobody has looked at from shipping.
    """
    from couchpotato import create_app

    settings['rate_limit_max'] = 1
    settings['rate_limit_window'] = 60
    try:
        limited = TestClient(create_app(API_KEY, '/'), follow_redirects=False)
        headers = {'accept': 'text/html'}
        limited.post('/login/', data={'password': 'wrong'}, headers=headers)
        response = limited.post('/login/', data={'password': 'wrong'}, headers=headers)
    finally:
        settings['rate_limit_max'] = 0

    assert response.status_code == 429, response.status_code
    return response


class TestNoMessageWhenThereIsNothingToSay:
    """AC-A11Y-5's negative half, which is what stops this becoming noise."""

    def test_a_first_visit_shows_no_message_at_all(self, client):
        response = client.get('/login/')

        assert response.status_code == 200
        assert _message_region(response.text) is None, (
            'a user who has never logged in is being told their session ended'
        )

    def test_an_unrecognised_reason_shows_no_message(self, client):
        response = client.get('/login/?reason=whatever-i-typed')

        assert _message_region(response.text) is None

    @pytest.mark.parametrize('reason', ['rejected', 'empty_password', 'sign_out_failed',
                                        'rate_limited'])
    def test_a_server_owned_reason_cannot_be_requested_by_url(self, client, reason):
        """Only `signed_out` and `session_ended` are navigational.

        The rest are the direct result of a POST the server just handled. If a
        URL could ask for them, any link could tell the operator their last
        attempt was rejected, or that a sign-out they never pressed failed --
        on the one page where they are deciding whether to trust what they see.
        """
        response = client.get('/login/?reason=%s' % reason)

        assert _message_region(response.text) is None, (
            '%r is reachable from a link' % reason)

    def test_a_hostile_reason_is_never_reflected(self, client):
        payload = '<img src=x onerror=alert(1)>'

        response = client.get('/login/', params={'reason': payload})

        assert _message_region(response.text) is None
        assert 'onerror=alert(1)' not in response.text, (
            'the reason parameter reached the page unescaped'
        )

    def test_a_signed_in_user_never_reaches_the_login_page(self, client):
        with stored_session_secret():
            client.cookies.set(SESSION_COOKIE_NAME, session_cookie())
            response = client.get('/login/?reason=signed_out')

        # 307 is `RedirectResponse`'s default and is the pre-existing
        # behaviour; what this pins is that the page was not RENDERED.
        assert response.status_code in (302, 307), (
            'a user holding a valid session was shown the login page and its '
            '"you have been signed out" message'
        )


class TestTheThreeReasons:
    """AC-A11Y-5: three distinguishable strings, each reachable."""

    def test_signing_out_says_it_covered_every_device(self, client):
        response = client.get('/login/?reason=signed_out')

        region = _message_region(response.text)
        assert region is not None, 'sign-out produced no message'
        role, text = region
        assert role in ('alert', 'status'), role
        assert 'signed out' in text.lower()
        assert 'every device' in text.lower() or 'all devices' in text.lower(), (
            'the sign-out confirmation does not state that D1 ended the '
            'session on every device: %r' % text
        )

    def test_an_ended_session_says_the_password_still_works(self, client):
        """The D5 upgrade case rides on this string.

        An operator whose working login stopped working after an update needs
        to be told, on the page they are looking at, that they have not lost
        their password. Without it the obvious next move is to go hunting in
        config.ini.
        """
        response = client.get('/login/?reason=session_ended')

        region = _message_region(response.text)
        assert region is not None
        role, text = region
        assert role in ('alert', 'status'), role
        lowered = text.lower()
        assert 'sign in again' in lowered or 'log in again' in lowered, text
        assert 'update' in lowered, (
            'the ended-session message does not mention the update, so the '
            'D5 upgrade case has no copy at all: %r' % text
        )
        assert 'password still works' in lowered or 'existing password' in lowered, text

    def test_a_rejected_attempt_says_so(self, client):
        response = client.post('/login/', data={'username': '', 'password': 'wrong'})

        region = _message_region(response.text)
        assert region is not None, (
            'a rejected sign-in rendered no message. `login_post` used to '
            'answer a failure with the same redirect as a success, which '
            'discarded it entirely.'
        )
        role, text = region
        assert role in ('alert', 'status'), role
        assert 'not accepted' in text.lower() or 'incorrect' in text.lower(), text

    def test_an_empty_password_gets_its_own_message(self, client):
        """AC-A11Y-4 names this case separately from a wrong password."""
        response = client.post('/login/', data={'username': '', 'password': ''})

        region = _message_region(response.text)
        assert region is not None
        _, text = region
        assert 'enter your password' in text.lower(), text

    def test_the_three_reasons_are_distinguishable(self, client):
        """Identical copy for three different situations helps nobody."""
        signed_out = _message_region(client.get('/login/?reason=signed_out').text)[1]
        ended = _message_region(client.get('/login/?reason=session_ended').text)[1]
        rejected = _message_region(
            client.post('/login/', data={'username': '', 'password': 'wrong'}).text)[1]

        assert len({signed_out, ended, rejected}) == 3, (
            (signed_out, ended, rejected))

    @pytest.mark.parametrize('reason', ['signed_out', 'session_ended'])
    def test_the_message_lives_inside_the_main_landmark(self, client, reason):
        """WCAG 3.3.1 wants the status where the content is, not floating."""
        html = client.get('/login/?reason=%s' % reason).text

        main = re.search(r'<main\b.*?</main>', html, re.S)
        assert main, 'the login page has no <main> landmark'
        assert 'data-testid="login-message"' in main.group(0), (
            'the status region is outside the main landmark'
        )


class TestTheCopyNeverLeaksTheMechanism:
    """AC-DESIGN-3."""

    def test_no_message_mentions_the_mechanism(self):
        from couchpotato import LOGIN_MESSAGES

        assert LOGIN_MESSAGES, 'no login messages are defined at all'
        for key, (_tone, text) in LOGIN_MESSAGES.items():
            lowered = text.lower()
            for banned in FORBIDDEN_IN_COPY:
                assert banned not in lowered, (
                    '%s message names %r, which tells the operator nothing '
                    'they can act on: %r' % (key, banned, text))

    def test_every_defined_message_is_rendered_by_some_real_path(self, client, settings):
        """A constant nothing renders is copy that cannot be reviewed."""
        from couchpotato import LOGIN_MESSAGES

        rendered = set()
        for reason in ('signed_out', 'session_ended'):
            rendered.add(_message_region(client.get('/login/?reason=%s' % reason).text)[1])
        rendered.add(_message_region(
            client.post('/login/', data={'username': '', 'password': 'wrong'}).text)[1])
        rendered.add(_message_region(
            client.post('/login/', data={'username': '', 'password': ''}).text)[1])
        rendered.add(_message_region(
            TestTheSignOutFailurePage()._failing_logout(client).text)[1])
        rendered.add(_message_region(_rate_limited_page(settings).text)[1])

        for key, (_tone, text) in LOGIN_MESSAGES.items():
            # A message with a placeholder is rendered with it filled in, so
            # match on the fixed part in front of it.
            fixed = text.split('{', 1)[0].strip()
            assert any(fixed in seen for seen in rendered), (
                'the %r message is never rendered' % key)


class TestAFailedSignInReturnsToTheForm:
    """AC-DESIGN-5, AC-QA-13."""

    def test_a_wrong_password_renders_the_form_rather_than_redirecting(self, client):
        response = client.post('/login/', data={'username': '', 'password': 'wrong'})

        assert response.status_code == 200, (
            'a failed sign-in answered %d. A redirect discards the failure, '
            'which is the defect.' % response.status_code)
        assert 'name="password"' in response.text

    def test_a_failed_sign_in_sets_no_cookie(self, client):
        response = client.post('/login/', data={'username': '', 'password': 'wrong'})

        assert SESSION_COOKIE_NAME not in response.cookies
        assert 'set-cookie' not in response.headers

    def test_the_failure_page_costs_no_redirects(self, settings):
        """An unbounded / -> /login/ bounce is the lockout shape to avoid."""
        from couchpotato import create_app

        following = TestClient(create_app(API_KEY, '/'), follow_redirects=True)
        response = following.post('/login/', data={'username': '', 'password': 'wrong'})

        assert response.history == [], (
            'the failure path redirected %d times' % len(response.history))
        assert response.status_code == 200

    def test_the_submitted_username_is_preserved(self, settings):
        settings['username'] = 'admin'
        from couchpotato import create_app
        client = TestClient(create_app(API_KEY, '/'), follow_redirects=False)

        response = client.post('/login/', data={'username': 'admin', 'password': 'wrong'})

        assert re.search(r'id="username"[^>]*value="admin"', response.text) \
            or re.search(r'value="admin"[^>]*id="username"', response.text), (
                'the operator has to retype their username after every typo')

    def test_the_preserved_username_is_html_escaped(self, client):
        payload = '"><script>alert(1)</script>'

        response = client.post('/login/', data={'username': payload, 'password': 'wrong'})

        assert '<script>alert(1)</script>' not in response.text, (
            'the submitted username was reflected unescaped')
        assert '&lt;script&gt;' in response.text, (
            'the username was not reflected at all, escaped or otherwise')

    def test_an_absurdly_long_username_is_not_reflected_whole(self, client):
        response = client.post(
            '/login/', data={'username': 'a' * 100000, 'password': 'wrong'})

        assert response.status_code == 200
        assert 'a' * 1000 not in response.text, (
            'a 100 KB username was reflected into the page verbatim')

    def test_the_password_field_is_never_pre_filled(self, client):
        response = client.post('/login/', data={'username': 'x', 'password': 'wrong'})

        password_input = re.search(r'<input[^>]*id="password"[^>]*>', response.text)
        assert password_input, response.text
        assert 'value=' not in password_input.group(0), (
            'the rejected password was written back into the page: %s'
            % password_input.group(0))

    def test_focus_lands_on_the_password_field_after_a_failure(self, client):
        response = client.post('/login/', data={'username': 'x', 'password': 'wrong'})

        password_input = re.search(r'<input[^>]*id="password"[^>]*>', response.text)
        username_input = re.search(r'<input[^>]*id="username"[^>]*>', response.text)
        assert 'autofocus' in password_input.group(0), (
            'after a rejected attempt the caret is not in the field the user '
            'has to retype: %s' % password_input.group(0))
        assert 'autofocus' not in username_input.group(0)

    def test_focus_lands_on_the_username_field_on_a_first_visit(self, client):
        """AC-A11Y-8's landing target, and the pre-existing behaviour."""
        response = client.get('/login/?reason=signed_out')

        username_input = re.search(r'<input[^>]*id="username"[^>]*>', response.text)
        assert 'autofocus' in username_input.group(0), (
            'focus after sign-out is left on document.body')

    def test_a_correct_password_still_signs_in(self, client):
        """The guard must not buy its safety by breaking login."""
        with stored_session_secret():
            response = client.post('/login/', data={'username': '', 'password': PASSWORD})

        assert response.status_code == 302
        assert response.cookies.get(SESSION_COOKIE_NAME)


class TestTheRoutesThatSendPeopleHere:
    """The reason has to be attached where the redirect is issued."""

    def test_a_rejected_session_is_told_its_session_ended(self, client):
        client.cookies.set(SESSION_COOKIE_NAME, 'not-a-token')

        response = client.get('/wanted/')

        assert response.status_code == 302
        assert 'reason=session_ended' in response.headers.get('location', ''), (
            'a client whose session was refused is redirected to a login page '
            'with nothing on it: %r' % response.headers.get('location'))

    def test_a_caller_who_never_had_a_session_is_told_nothing(self, client):
        response = client.get('/wanted/')

        assert response.status_code == 302
        assert 'reason=' not in response.headers.get('location', ''), (
            'a first-time visitor is told their session ended')

    def test_signing_out_lands_on_the_confirmation(self, client):
        with stored_session_secret():
            client.cookies.set(SESSION_COOKIE_NAME, session_cookie())
            import couchpotato
            original = couchpotato.rotate_session_secret
            couchpotato.rotate_session_secret = lambda *a, **k: TEST_SESSION_SECRET
            try:
                response = client.post('/logout/')
            finally:
                couchpotato.rotate_session_secret = original

        assert response.status_code == 303
        assert 'reason=signed_out' in response.headers.get('location', ''), (
            response.headers.get('location'))


class TestTheSignOutFailurePage:
    """Spec gap 7: the D1 failure path had no copy and no page.

    The BEHAVIOUR must not change -- nothing was revoked, so the cookie is
    deliberately left in place and the status stays 500. Only the presentation
    is fixed: a plain-text 500 on the sign-out path is the one screen where the
    operator most needs to be told the truth clearly.
    """

    def _failing_logout(self, client):
        import couchpotato

        original = couchpotato.rotate_session_secret

        def explode(*args, **kwargs):
            raise RuntimeError('property store is down')

        couchpotato.rotate_session_secret = explode
        try:
            with stored_session_secret():
                client.cookies.set(SESSION_COOKIE_NAME, session_cookie())
                return client.post('/logout/')
        finally:
            couchpotato.rotate_session_secret = original

    def test_a_failed_sign_out_renders_a_real_page(self, client):
        response = self._failing_logout(client)

        assert response.status_code == 500
        assert response.headers['content-type'].startswith('text/html'), (
            'the sign-out failure is still plain text: %r'
            % response.headers.get('content-type'))
        assert '<html' in response.text.lower()

    def test_the_failure_page_says_the_sessions_are_still_valid(self, client):
        response = self._failing_logout(client)

        region = _message_region(response.text)
        assert region is not None, 'the failure page carries no status region'
        role, text = region
        assert role == 'alert', role
        lowered = text.lower()
        assert 'still' in lowered and ('signed in' in lowered or 'valid' in lowered
                                       or 'active' in lowered), text
        for banned in FORBIDDEN_IN_COPY:
            assert banned not in lowered, (banned, text)

    def test_the_failure_page_offers_another_go(self, client):
        response = self._failing_logout(client)

        assert re.search(r'<form[^>]*method="post"[^>]*action="/logout/"', response.text) \
            or re.search(r'<form[^>]*action="/logout/"[^>]*method="post"', response.text), (
                'the failure page is a dead end -- no way to retry the '
                'sign-out that failed')

    def test_the_failure_page_does_not_show_a_sign_in_form(self, client):
        """Showing the sign-in form is the lie this whole path avoids."""
        response = self._failing_logout(client)

        assert 'name="password"' not in response.text, (
            'a failed sign-out rendered the sign-in form, which looks exactly '
            'like a successful sign-out while every session is still valid')

    def test_the_failure_page_still_does_not_clear_the_cookie(self, client):
        response = self._failing_logout(client)

        assert 'set-cookie' not in response.headers, (
            'the browser was signed out while the token in somebody else\'s '
            'hands stayed valid')
