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
  2. `auth_is_required()` refuses to ENFORCE it even if the value reaches
     config.ini by another route -- a hand-edit, a restored backup, a future
     writer. The lockout is then unreachable by construction rather than by
     everyone remembering to go through the guarded path.

Both are needed. (1) alone leaves config.ini hand-editing open, which is the
documented recovery path and therefore the one most likely to be used wrong.
(2) alone would store a setting the UI shows as ON while nothing enforces it --
copy promising an auth behaviour the code does not implement, which is the exact
defect class PR 2 existed to remove.
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


class TestTheEnforcementPointRefusesTheLockout:
    """Layer 2: `auth_is_required()` will not enforce what nothing can satisfy."""

    def test_auth_required_without_a_password_is_not_enforced(self, settings):
        from couchpotato import auth_is_required, get_current_user

        settings['auth_required'] = 1
        settings['password'] = ''

        assert auth_is_required() is False, (
            'authentication is enforced with no password stored: every request '
            'is denied and every login refused, so the operator is locked out '
            'of their own server with no route back but editing config.ini'
        )
        assert get_current_user(_request()) is True

    @pytest.mark.parametrize('stored', [1, '1', 'true', 'yes', 'on'])
    def test_every_truthy_spelling_is_covered(self, settings, stored):
        """The string path is the STARTUP path (runner.py runs before the
        option's type is registered), so a guard that only handled the int
        would leave the lockout reachable on exactly the boot where it bites."""
        from couchpotato import auth_is_required

        settings['auth_required'] = stored
        settings['password'] = ''
        assert auth_is_required() is False, 'stored %r still enforced' % (stored,)

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
