"""Turning on "Require login" without a password must not lock the operator out.

The state: `auth_required = 1` with `password = ''`. `get_current_user` denies
every request (no cookie can be valid), and `login_post` refuses every login
(it now requires a configured password -- deliberately, because a blank password
accepting any credentials was one of the four bypasses PR 2 closed). There is
then no way back in except shell access, hand-editing config.ini and a restart,
on exactly the population least able to do that.

It is one click from the settings UI and from the first-run wizard, and the
password field's own copy tells the operator it cannot happen.

`md5Password` already closed the OTHER entrance (clearing a password turns the
requirement off). This closes the direct one, in two independent places:

  1. `Settings.saveView` refuses to store the incoherent value at all, so the
     checkbox reverts on reload rather than silently appearing to be on.
  2. `saveView` REPORTS the value it actually stored, so the UI cannot leave
     the checkbox ticked and announce "Saved" while the server stays public.

`auth_is_required()` deliberately does NOT disarm. An earlier version of this
branch made it serve without authentication in this state, on the reasoning
that a requirement nothing can satisfy should not be enforced. Measured against
a real `create_app`, that gave an unauthenticated caller a 200 on /wanted/, the
api_key embedded in that page, and a reachable
`movie.delete?delete_from=all` -- trading a recoverable lockout for remote
library deletion, which inverts this project's own precedence (irrecoverable
data loss and security both outrank operability).

So it FAILS CLOSED and logs the remedy at ERROR. The state is only reachable by
hand-editing config.ini or restoring a backup -- both require filesystem
access, which is exactly what fixing it needs.
"""
import types

import pytest

from couchpotato.environment import Env


@pytest.fixture
def settings():
    """One dict behind Env.setting and Env.get('settings')."""
    data = {'api_key': 'THEKEY'}
    original_setting, original_get = Env.setting, Env.get

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            data[key] = kwargs['value']
            return
        return data.get(key, kwargs.get('default', ''))

    Env.setting = staticmethod(mock_setting)
    yield data
    Env.setting, Env.get = original_setting, original_get


def _request(cookie=None):
    return types.SimpleNamespace(cookies=({'user': cookie} if cookie else {}))


class TestTheEnforcementPointFailsClosed:
    """`auth_is_required()` keeps enforcing even when nothing can satisfy it.

    The alternative was measured and is worse: serving without authentication
    hands a remote caller the api_key out of the page and a reachable
    `movie.delete?delete_from=all`.
    """

    @pytest.mark.parametrize('stored', [1, True, '1', 'true', 'yes', 'on'])
    def test_auth_required_without_a_password_still_denies(self, settings, stored):
        from couchpotato import auth_is_required, get_current_user

        settings['auth_required'] = stored
        settings['password'] = ''

        assert auth_is_required() is True, (
            'stored %r fell OPEN with no password. An unauthenticated caller '
            'then reads the api_key from the served page and can delete the '
            'library remotely -- worse than the lockout it avoids, and the '
            'lockout is fixable from the filesystem the operator already has.'
            % (stored,)
        )
        assert get_current_user(_request()) is None

    def test_the_remedy_is_logged_at_error(self, settings, caplog):
        """The locked-out operator's only signal. It must name the fix."""
        from couchpotato import auth_is_required

        settings['auth_required'] = 1
        settings['password'] = ''

        with caplog.at_level('ERROR'):
            auth_is_required()

        assert 'auth_required = 0' in caplog.text, (
            'the lockout log does not tell the operator how to get back in'
        )
        assert 'config.ini' in caplog.text

    def test_a_password_protected_instance_is_unaffected(self, settings):
        """Anti-vacuity: the guard must not disable auth generally."""
        from couchpotato import auth_is_required, get_current_user

        settings['auth_required'] = 1
        settings['password'] = 'hashed'

        assert auth_is_required() is True
        assert get_current_user(_request()) is None
        assert get_current_user(_request('THEKEY')) == 'THEKEY'


class TestTheSavePathRefusesTheLockout:
    """Layer 1: the incoherent value is never stored in the first place."""

    def _settings_object(self, stored_password):
        from couchpotato.core.settings import Settings

        s = Settings.__new__(Settings)
        s.p = None
        s.types = {}
        s.options = {}
        s.log = types.SimpleNamespace(
            warning=lambda *a, **k: None, info=lambda *a, **k: None,
            debug=lambda *a, **k: None, error=lambda *a, **k: None,
        )
        s.directories_delimiter = '::'
        return s

    def test_the_hook_refuses_to_turn_auth_on_without_a_password(self, settings):
        from couchpotato.core._base._core import Core

        settings['password'] = ''
        core = Core.__new__(Core)

        assert core.guardAuthRequired(1) == 0, (
            'the save hook allowed auth_required=1 with no password stored'
        )

    def test_the_hook_allows_it_once_a_password_exists(self, settings):
        from couchpotato.core._base._core import Core

        settings['password'] = 'hashed'
        core = Core.__new__(Core)

        assert core.guardAuthRequired(1) == 1

    def test_turning_it_off_is_always_allowed(self, settings):
        """Never block the direction that RESTORES access."""
        from couchpotato.core._base._core import Core

        core = Core.__new__(Core)
        for pw in ('', 'hashed'):
            settings['password'] = pw
            assert core.guardAuthRequired(0) == 0


class TestSaveViewCanStoreAFalsyHookResult:
    """The guard above is inert unless `saveView` can actually store its 0.

    `saveView` did `new_value if new_value else value`, so a hook returning 0
    was DISCARDED and the caller's original truthy value stored instead -- the
    refusal would have been silently ignored. And `fireEvent(single=True)`
    returns `[]` (not None) when nothing handles the event, so "no handler" and
    "handler said 0" have to be told apart deliberately.

    Measured before the fix: the guard returned 0 and config.ini still received 1.
    """

    def test_no_handler_falls_back_to_the_submitted_value(self):
        from couchpotato.core.settings import _resolve_saved_value

        # fireEvent(single=True) returns [] for an unhandled event.
        assert _resolve_saved_value([], 'submitted') == 'submitted'
        assert _resolve_saved_value(None, 'submitted') == 'submitted'

    def test_a_falsy_hook_result_wins(self):
        from couchpotato.core.settings import _resolve_saved_value

        assert _resolve_saved_value(0, 1) == 0, (
            'a hook returning 0 was discarded, so any guard that refuses by '
            'returning a falsy value is inert'
        )
        assert _resolve_saved_value('', 'submitted') == ''

    def test_a_truthy_hook_result_still_wins(self):
        from couchpotato.core.settings import _resolve_saved_value

        assert _resolve_saved_value('hashed', 'plaintext') == 'hashed'


class TestTheGuardDoesNotLieAboutTheCommonCase:
    """The warning must only fire when auth_required actually means ON.

    Raised by claude-review on #227. The first version of the guard checked the
    password BEFORE interpreting `configured`, so it fired for anything that was
    not None/'' -- including an explicit 0.

    That is the state every default install reaches: `runner.py`'s startup
    migration writes back an explicit `auth_required = 0` for any install with
    no password, deliberately, so the value is greppable in config.ini. From the
    next request onward the guard logged '"Require login" is on but no password
    is stored' on EVERY page load, for the single most common configuration this
    project ships.

    Nothing broke -- `auth_is_required()` still returned False -- but the log
    asserted the opposite of the truth, on exactly the mechanism `runner.py`'s
    own comment says operators depend on ("the log is where an operator checks
    whether they made it"). It is the same defect class this PR calls out and
    fixes three times elsewhere in its own diff.
    """

    @pytest.mark.parametrize('stored', [0, False, '0', 'false', 'no', 'off'])
    def test_auth_off_with_no_password_logs_nothing(self, settings, caplog, stored):
        from couchpotato import auth_is_required

        settings['auth_required'] = stored
        settings['password'] = ''

        with caplog.at_level('WARNING'):
            assert auth_is_required() is False

        assert 'Require login' not in caplog.text, (
            'auth_required is explicitly OFF (%r) and the guard warned that it '
            'is on. Every default install logs this on every request.' % (stored,)
        )

    @pytest.mark.parametrize('stored', [1, True, '1', 'true', 'yes', 'on'])
    def test_auth_on_with_no_password_still_warns(self, settings, caplog, stored):
        """Anti-vacuity: silencing the false warning must not silence the real one."""
        from couchpotato import auth_is_required

        settings['auth_required'] = stored
        settings['password'] = ''

        with caplog.at_level('WARNING'):
            assert auth_is_required() is True

        assert 'Require login' in caplog.text, (
            'auth_required is ON (%r) with no password and NOTHING was logged. '
            'The operator sees an unprotected server and no explanation.' % (stored,)
        )

    def test_auth_on_with_a_password_logs_nothing(self, settings, caplog):
        from couchpotato import auth_is_required

        settings['auth_required'] = 1
        settings['password'] = 'hashed'

        with caplog.at_level('WARNING'):
            assert auth_is_required() is True

        assert 'Require login' not in caplog.text


class TestSaveViewReportsWhatItActuallyStored:
    """A rewritten value must not be reported as an accepted one.

    Raised by claude-review on #227. `guardAuthRequired` turns a submitted `1`
    into `0`, and `saveView` returned a bare `{'success': True}`. The write DID
    happen, so the client's failure path never fired: it kept `1` in local
    state, cleared the dirty flag, left the "Require login" checkbox ticked and
    announced "Saved" -- while the server stayed public.

    The UI stating the opposite of the truth about whether authentication is on
    is the same defect class as the username/password copy this branch already
    corrected.
    """

    def _save_view(self, hook_result, submitted):
        """Drive `Settings.saveView` with a stubbed hook and capture the result."""
        import couchpotato.core.settings as settings_module
        from couchpotato.core.settings import Settings

        s = Settings.__new__(Settings)
        s.types = {}
        s.options = {}
        s.directories_delimiter = '::'
        s.log = types.SimpleNamespace(warning=lambda *a, **k: None,
                                      info=lambda *a, **k: None,
                                      debug=lambda *a, **k: None,
                                      error=lambda *a, **k: None)
        stored = {}
        s.set = lambda section, option, value: stored.__setitem__(option, value)
        s.save = lambda: None
        s.isOptionWritable = lambda section, option: True
        s.isOptionMeta = lambda section, option: False

        original_fire = settings_module.fireEvent
        original_env = settings_module.Env if hasattr(settings_module, 'Env') else None

        def fake_fire(event, *args, **kwargs):
            if event.endswith('.after'):
                return None
            return hook_result

        settings_module.fireEvent = fake_fire
        try:
            import couchpotato.environment as env_module
            original_get = env_module.Env.get
            env_module.Env.get = staticmethod(
                lambda k, d=None: types.SimpleNamespace(
                    chroot2abs=lambda p: p) if k == 'softchroot' else original_get(k, d))
            try:
                result = s.saveView(section='core', name='auth_required', value=submitted)
            finally:
                env_module.Env.get = original_get
        finally:
            settings_module.fireEvent = original_fire

        return result, stored.get('auth_required')

    def test_a_rewritten_value_is_reported_as_changed(self):
        result, stored = self._save_view(hook_result=0, submitted=1)

        assert stored == 0, 'the guard did not take effect at all'
        assert result['value'] == 0, (
            'saveView reported success without saying WHAT it stored, so the '
            'client keeps the submitted 1 and the checkbox stays ticked while '
            'the server is public'
        )
        assert result['changed'] is True
        assert result['submitted'] == 1

    def test_an_accepted_value_is_not_reported_as_changed(self):
        """Anti-vacuity: `changed` must not simply always be True."""
        result, stored = self._save_view(hook_result=1, submitted=1)

        assert stored == 1
        assert result['value'] == 1
        assert result['changed'] is False

    def test_no_handler_still_reports_the_submitted_value(self):
        """`fireEvent(single=True)` returns [] with no handler -- the common case."""
        result, stored = self._save_view(hook_result=[], submitted='some-value')

        assert stored == 'some-value'
        assert result['value'] == 'some-value'
        assert result['changed'] is False
