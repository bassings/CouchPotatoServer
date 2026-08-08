"""There has to be a way to sign out. D8, AC-PROD-2, AC-DESIGN-1/2, AC-A11Y-7.

This tranche exists to close a regression THIS PR created. Once `logout`
became an authenticated POST (AC-SEC-37), the only way a browser had ever
reached it -- typing `/logout/` -- started answering 405, and the new UI has
never had a sign-out control at all (`grep` for logout across
`couchpotato/ui/` returned nothing). Measured on the tranche B tip:

    GET  /logout/                  -> 405
    GET  /login/                   -> 200
    POST /logout/ unauthenticated  -> 303, nothing revoked

So the operator could not end a session by any means available to them.

The copy is pinned in the SAME test as the behaviour it describes
(AC-DESIGN-2). Under D1 a sign-out rotates the shared signing secret, which
ends every session on every device -- and a control labelled "Log out" implies
the opposite. A label and a revocation that drift apart on this page mean the
operator believes they closed one browser when they closed all of them, or
worse, the reverse.
"""
import os
import re
import socket
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_helper import SESSION_COOKIE_NAME  # noqa: E402

API_KEY = 'notarealapikey' + '0' * 18
PASSWORD = 'hunter2'
STORED_PASSWORD = hash_password(md5(PASSWORD))
REPO_ROOT = Path(__file__).resolve().parents[2]

LOGOUT_ACTION = '/logout/'


class FakeSettings(Settings):
    """The REAL `getProperty` / `setProperty` over an in-memory config."""

    def __init__(self, data):
        from couchpotato.core.logger import CPLog
        self.data = data
        self.log = CPLog('test-settings')
        self.file = None
        self.p = None
        self.directories_delimiter = '::'

    def get(self, attr, default=None, section='core', type=None):
        return self.data.get(attr, default)

    def set(self, section, option, value):
        self.data[option] = value

    def addSection(self, section):
        pass

    def save(self):
        pass


@pytest.fixture
def env(tmp_path):
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    old_timeout = socket.getdefaulttimeout()

    db = SQLiteAdapter()
    db.create(str(tmp_path / 'db'))

    settings = FakeSettings({
        'username': '',
        'password': STORED_PASSWORD,
        'api_key': API_KEY,
        'auth_required': 1,
        'rate_limit_max': 0,
        'cors_origins': '',
        'ssl_cert': '',
        'ssl_key': '',
    })

    Env.set('db', db)
    Env.set('settings', settings)
    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(REPO_ROOT))
    Env.set('data_dir', str(tmp_path))
    Env.set('dev', False)
    Env.set('desktop', True)

    from couchpotato import ensure_session_secret
    secret = ensure_session_secret(db)

    from couchpotato import create_app
    app = create_app(API_KEY, '/')

    yield type('EnvHandle', (), {
        'db': db, 'settings': settings, 'secret': secret, 'app': app,
    })

    Env.set('desktop', False)
    socket.setdefaulttimeout(old_timeout)
    db.close()
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


def _log_in(env):
    session = TestClient(env.app, follow_redirects=False)
    response = session.post('/login/', data={'username': '', 'password': PASSWORD})
    assert response.status_code == 302, response.text
    assert session.cookies.get(SESSION_COOKIE_NAME), response.headers.get('set-cookie')
    return session


def _page(env):
    session = _log_in(env)
    response = session.get('/')
    assert response.status_code == 200, response.status_code
    return response.text


def _sign_out_forms(html: str):
    """Every sign-out control on the page, found by what it SAYS.

    Deliberately NOT keyed on `action="/logout/"`. Doing that made the
    end-to-end test below vacuous, and it was caught only by mutating: pointing
    the sidebar form at `/sign-out/` left the mobile one still matching, the
    filtered list still non-empty, and the whole chain green against a control
    that answers 404. Identifying a control by its label and then following
    the action IT declares is the only way that test proves anything.
    """
    return [
        form for form in re.findall(r'<form\b.*?</form>', html, re.S)
        if re.search(r'aria-label="[^"]*(?:sign out|log out)[^"]*"', form, re.I)
    ]


def _forms_posting_to_logout(html: str):
    """Every `<form>` on the page whose action is the logout route.

    Kept INDEPENDENT of `_sign_out_forms`: the accessible-name test below has
    to be able to fail when the label is missing, which it cannot if the only
    way to find the control is by reading that same label.
    """
    return [
        form for form in re.findall(r'<form\b.*?</form>', html, re.S)
        if 'action="%s"' % LOGOUT_ACTION in form and 'method="post"' in form.lower()
    ]


def _section(html: str, start_pattern: str, end_pattern: str) -> str:
    start = re.search(start_pattern, html)
    assert start, 'could not find %r in the rendered shell' % start_pattern
    end = re.search(end_pattern, html[start.end():])
    assert end, 'could not find %r after %r' % (end_pattern, start_pattern)
    return html[start.start():start.end() + end.start()]


def _sidebar(html: str) -> str:
    return _section(html, r'<aside\b', r'</aside>')


def _mobile_menu(html: str) -> str:
    return _section(html, r'<div[^>]*id="mobile-menu"', r'<!-- MOBILE BOTTOM NAV -->')


class TestTheControlExists:
    """AC-PROD-2 / AC-DESIGN-1."""

    def test_an_authenticated_page_offers_a_way_out(self, env):
        html = _page(env)

        assert _forms_posting_to_logout(html), (
            'no control on an authenticated page reaches the logout route, so '
            'the only way to end a session is a POST the browser cannot be '
            'made to issue by typing a URL'
        )

    def test_the_desktop_sidebar_carries_one(self, env):
        assert _forms_posting_to_logout(_sidebar(_page(env)))

    def test_the_mobile_menu_carries_one(self, env):
        assert _forms_posting_to_logout(_mobile_menu(_page(env))), (
            'the sign-out control is desktop-only, so a phone user cannot '
            'sign out at all'
        )

    def test_it_is_a_post_and_not_a_link(self, env):
        """`logout` is POST-only (AC-SEC-37), so an <a href> is a 405."""
        html = _page(env)

        assert 'href="%s"' % LOGOUT_ACTION not in html, (
            'a plain link to the logout route renders, which answers 405'
        )

    def test_it_survives_a_page_that_is_not_the_default(self, env):
        """"Every authenticated page", not just the one the tests happen to load."""
        session = _log_in(env)

        for path in ('/wanted/', '/settings/', '/add/'):
            response = session.get(path)
            assert response.status_code == 200, (path, response.status_code)
            assert _forms_posting_to_logout(response.text), path


class TestTheControlIsAbsentWhenThereIsNoSession:
    """AC-DESIGN-1's second half.

    An install with no password has no session to end, and a sign-out control
    there is a button that logs the operator out of nothing.
    """

    def test_nothing_renders_when_authentication_is_off(self, env):
        env.settings.data['auth_required'] = 0
        env.settings.data['password'] = ''

        response = TestClient(env.app, follow_redirects=False).get('/')

        assert response.status_code == 200
        assert _forms_posting_to_logout(response.text) == [], (
            'a sign-out control renders on an install that has no login'
        )
        assert 'sign out' not in response.text.lower()


class TestTheLabelMatchesWhatTheButtonDoes:
    """AC-DESIGN-2, driven end to end so copy and behaviour cannot drift.

    Two independent authenticated clients. One presses the control; the other
    must lose its session. The rendered label is asserted in the SAME test, so
    a label saying "this browser" alongside a revocation that ends every
    session fails here rather than being noticed by a user.
    """

    def test_the_label_states_the_scope_the_route_actually_has(self, env):
        phone = _log_in(env)
        laptop = _log_in(env)

        page = phone.get('/')
        assert page.status_code == 200
        forms = _forms_posting_to_logout(page.text)
        assert forms, 'there is no control to read a label from'
        label = ' '.join(re.sub(r'<[^>]+>', ' ', forms[0]).split())

        # Behaviour first: the second client must genuinely be revoked, so the
        # copy assertion below is describing something that happened.
        assert laptop.get('/').status_code == 200
        assert phone.post('/logout/').status_code in (302, 303)
        after = laptop.get('/')
        assert after.status_code == 302 and 'login' in after.headers.get('location', ''), (
            'the second client kept its session, so this test would happily '
            'accept a label promising "all devices" from a route that ends one'
        )

        lowered = label.lower()
        assert 'sign out' in lowered or 'log out' in lowered, label
        assert 'everywhere' in lowered or 'all devices' in lowered \
            or 'every device' in lowered, (
                'the control is labelled %r, which reads as "this browser". '
                'It ends every session on every device.' % label)


class TestTheWholeChainClosesTheRegression:
    """D11, driven across every boundary rather than one component at a time.

    The defects that survive review here live BETWEEN functions that each look
    right alone: the template renders a form, the route accepts a POST, the
    redirect names a reason, the login page holds a message for that reason.
    Each of those has its own test above; none of them would notice the
    template posting to a path the router does not serve, or naming a reason
    the login page discards.

    So this walks the chain using only what the previous step handed over --
    the form's own `action` and `method`, the redirect's own `Location` -- and
    ends on the words a person actually reads.
    """

    @pytest.mark.parametrize('index', [0, 1])
    def test_a_user_can_sign_out_using_only_what_the_page_gives_them(self, env, index):
        """Once per control, so a broken action on either one is caught.

        Parametrised rather than "take the first": the desktop and the mobile
        control declare their own `action`, and a test that reads only one of
        them passes while the other 404s. Measured -- that is exactly what the
        first version of this test did.
        """
        session = _log_in(env)

        page = session.get('/')
        forms = _sign_out_forms(page.text)
        assert len(forms) == 2, (
            'expected a sign-out control in both the sidebar and the mobile '
            'menu, found %d' % len(forms))
        form = forms[index]
        action = re.search(r'action="([^"]*)"', form).group(1)
        method = re.search(r'method="([^"]*)"', form).group(1)

        submitted = session.request(method.upper(), action)
        assert submitted.status_code == 303, (
            'the control the page renders does not reach a working route: '
            '%s %s answered %d' % (method.upper(), action, submitted.status_code))

        landing = submitted.headers['location']
        confirmation = session.get(landing)
        assert confirmation.status_code == 200, (landing, confirmation.status_code)
        assert 'data-testid="login-message"' in confirmation.text, (
            'signing out lands on a login page with nothing on it')
        assert 'signed out' in confirmation.text.lower()

        # And the session really is over, not merely reported as over.
        assert session.get('/').status_code == 302


class TestTheControlIsUsableWithoutAMouse:
    """AC-A11Y-7."""

    def test_it_is_a_focusable_button_in_the_tab_order(self, env):
        for scope in (_sidebar, _mobile_menu):
            form = _forms_posting_to_logout(scope(_page(env)))[0]
            button = re.search(r'<button\b[^>]*>', form)
            assert button, 'the control is not a <button>: %s' % form
            assert 'type="submit"' in button.group(0), button.group(0)
            assert 'tabindex="-1"' not in button.group(0), (
                'the control is removed from the tab order')
            assert 'disabled' not in button.group(0), (
                'a `disabled` control cannot hold focus; use aria-disabled')

    def test_it_has_an_accessible_name_even_when_the_sidebar_is_collapsed(self, env):
        """The visible label collapses to `w-0 opacity-0` with the sidebar."""
        form = _forms_posting_to_logout(_sidebar(_page(env)))[0]
        button = re.search(r'<button\b[^>]*>', form).group(0)

        name = re.search(r'aria-label="([^"]+)"', button)
        assert name, (
            'the collapsed sidebar leaves the button with a zero-width label '
            'and no aria-label: %s' % button)
        lowered = name.group(1).lower()
        assert 'sign out' in lowered or 'log out' in lowered, name.group(1)

    def test_the_accessible_name_contains_the_visible_label(self, env):
        """WCAG 2.5.3 Label in Name -- speech input must be able to say it."""
        form = _forms_posting_to_logout(_sidebar(_page(env)))[0]
        aria = re.search(r'aria-label="([^"]+)"', form).group(1)
        visible = ' '.join(re.sub(r'<[^>]+>', ' ', form).split())

        assert aria.lower() in visible.lower(), (aria, visible)

    def test_the_icon_is_hidden_from_assistive_technology(self, env):
        form = _forms_posting_to_logout(_sidebar(_page(env)))[0]
        svg = re.search(r'<svg\b[^>]*>', form)

        assert svg, 'the control has no icon, so it does not match the pattern'
        assert 'aria-hidden="true"' in svg.group(0), svg.group(0)
        assert 'viewBox="0 0 24 24"' in svg.group(0), svg.group(0)
        assert 'stroke-width="1.5"' in svg.group(0), svg.group(0)


class TestItAddsNoAnimationAndNoNewColour:
    """AC-A11Y-14's grep half and AC-A11Y-15, scoped to the new markup."""

    def test_the_control_uses_only_design_tokens(self, env):
        for scope in (_sidebar, _mobile_menu):
            form = _forms_posting_to_logout(scope(_page(env)))[0]
            assert not re.search(r'#[0-9a-fA-F]{3,8}\b', form), (
                'the sign-out control introduces a raw hex colour: %s' % form)

    def test_the_control_adds_no_animation(self, env):
        for scope in (_sidebar, _mobile_menu):
            form = _forms_posting_to_logout(scope(_page(env)))[0]
            assert 'animate-' not in form, form
            # `transition-colors` is the shell's existing hover treatment and
            # base.html's prefers-reduced-motion block already caps every
            # transition at 0.01ms, so it is allowed; a transform or opacity
            # animation would not be.
            assert 'transition-transform' not in form, form
