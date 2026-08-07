"""`/login/` must not issue a session when no password is configured.

The credential check was:

    if (form.get('username') == username or not username) and \\
       (check_password(form_password_md5, password) or not password):

`or not password` short-circuits the whole comparison to True whenever the
stored password is empty, so **any** submitted credentials were accepted and a
valid `user` cookie -- the api_key -- was written to the browser.

Why that matters, given that a blank password also means `get_current_user`
returns True and the UI is open anyway: PR 2 introduces `auth_required`. The
dangerous state is auth_required ON with no password set, which is reachable
by exactly one click in the settings UI. The instance then *looks* protected --
there is a login page, it asks for credentials, it rejects nothing -- and
admits everyone. A door that is locked in appearance only is worse than an
open one, because it stops the operator looking for the lock.

The cookie is the api_key, so this is not merely a UI bypass: it hands the
caller the credential the whole API authenticates with.
"""
import os

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import addApiView, api, api_locks, api_nonblock, api_docs, api_docs_missing
from couchpotato.environment import Env

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_helper import stored_session_secret  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    """Env with configurable username/password, restored afterwards."""
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
    Env.set('data_dir', str(tmp_path))

    data = {'username': 'admin', 'password': '', 'api_key': 'testkey123'}
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


def _client():
    from couchpotato import create_app
    return TestClient(create_app('testkey123', '/'), follow_redirects=False)


def _logged_in(response) -> bool:
    """Did the response hand back a session cookie?"""
    return 'user' in response.cookies


class TestBlankPasswordIssuesNoSession:

    def test_arbitrary_credentials_are_refused_when_no_password_is_set(self, settings):
        settings['password'] = ''

        response = _client().post('/login/', data={'username': 'admin', 'password': 'anything-at-all'})

        assert not _logged_in(response), (
            'a session cookie was issued for an arbitrary password while no '
            'password is configured. The cookie value is the api_key, so this '
            'hands the caller the credential the whole API authenticates with.'
        )

    def test_an_empty_submission_is_refused_when_no_password_is_set(self, settings):
        settings['password'] = ''

        response = _client().post('/login/', data={'username': 'admin', 'password': ''})

        assert not _logged_in(response), 'an empty password was accepted as valid'

    def test_a_wrong_username_is_refused_when_no_password_is_set(self, settings):
        settings['password'] = ''

        response = _client().post('/login/', data={'username': 'someone-else', 'password': 'x'})

        assert not _logged_in(response)


class TestConfiguredPasswordStillWorks:
    """The fix must not buy safety by breaking login."""

    def test_the_correct_password_still_logs_in(self, settings):
        from couchpotato.core.helpers.variable import hash_password, md5

        settings['password'] = hash_password(md5('correct-horse'))

        with stored_session_secret():
            response = _client().post('/login/', data={'username': 'admin', 'password': 'correct-horse'})

        assert _logged_in(response), (
            'a correctly configured login was refused: the guard disabled the '
            'feature instead of fixing it'
        )

    def test_a_wrong_password_is_still_refused(self, settings):
        from couchpotato.core.helpers.variable import hash_password, md5

        settings['password'] = hash_password(md5('correct-horse'))

        response = _client().post('/login/', data={'username': 'admin', 'password': 'wrong'})

        assert not _logged_in(response)


class TestGetKeyDoesNotLeakTheApiKey:
    """`/getkey/` had the identical `or not password` flaw, and it is worse here.

    `login_post` at least issues a cookie. This endpoint returns the api_key
    itself in a JSON body, over GET, with the credentials in the query string --
    so the request line lands in access logs, proxy logs and browser history,
    and an unauthenticated caller received the key outright whenever no
    password was configured.

    NOT deleted here, though the spec calls for that eventually: its only
    referrer is `couchpotato/simple_healthcheck.py:76`, whose own removal is
    blocked on AC-OPS-12's production grep. Closing the hole does not depend on
    resolving that, so it is closed now and the deletion follows separately.
    """

    def test_no_password_configured_does_not_hand_out_the_api_key(self, settings):
        from couchpotato.core.helpers.variable import md5

        settings['password'] = ''

        # `u` is the md5 of the username, which is not a secret -- it is
        # whatever the operator typed, commonly `admin`, and it is displayed in
        # the settings UI. An earlier version of this test passed `u=anything`
        # and went green against the UNFIXED code, because the username check
        # rejected it before the password check was ever reached. That is the
        # incidentally-passing shape: it looked like a leak test and was
        # measuring the wrong clause.
        body = _client().get('/getkey/?u=%s&p=anything' % md5('admin')).json()

        assert body.get('api_key') is None, (
            'an unauthenticated GET received the api_key because no password '
            'is configured. The credentials are in the query string, so this '
            'is also logged wherever request lines are logged.'
        )
        assert body.get('success') is False

    def test_the_correct_password_still_returns_the_key(self, settings):
        from couchpotato.core.helpers.variable import hash_password, md5

        settings['password'] = hash_password(md5('correct-horse'))

        body = _client().get('/getkey/?u=%s&p=%s' % (md5('admin'), md5('correct-horse'))).json()

        assert body.get('api_key') == 'testkey123', (
            'the fix broke the endpoint for a correctly configured install'
        )

    def test_a_wrong_password_returns_nothing(self, settings):
        from couchpotato.core.helpers.variable import hash_password, md5

        settings['password'] = hash_password(md5('correct-horse'))

        body = _client().get('/getkey/?u=%s&p=%s' % (md5('admin'), md5('wrong'))).json()

        assert body.get('api_key') is None
