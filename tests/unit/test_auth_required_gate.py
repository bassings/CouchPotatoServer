"""Auth is gated on an explicit setting, not inferred from two other fields.

`get_current_user` used to gate on `if username and password:` and return
`True` -- fully public -- otherwise. Driven directly, that gives:

    username='admin' password='secret'  -> denied without a cookie
    username=''      password='secret'  -> PUBLIC
    username='admin' password=''        -> PUBLIC
    username=''      password=''        -> PUBLIC

So an operator who set a password but left the username blank had a wide-open
server and no indication of it. The settings copy made that the likely
mistake rather than an unlikely one: "Leave empty to disable authentication"
sat on the **username** field, so the field that silently disabled auth was the
one whose own description promised it would.

The gate is now the explicit `auth_required` setting:

  - ON  -> a valid session cookie is required, whatever username/password hold.
  - OFF -> open, which is now a state someone chose rather than one they
           stumbled into.
  - A blank username means "any username is accepted", not "auth off".

The default is a plain `0` rather than a tri-state `None`. Spec-verified, and
worth restating because the tidy-looking version is broken: `registerDefaults`
materialises the literal `auth_required = None` into `config.ini` on first
boot, and `Env.setting`'s own default is `''`, so `Env.setting('auth_required',
type='bool')` reads falsy and auth stays OFF on every install, silently, with
no failing test and no log line. A one-shot startup migration writes an
explicit `1` when the key is absent and a password is set, so existing
password-protected installs stay protected and the value is greppable
afterwards -- which matters because grepping `config.ini` is the documented
lock-out recovery path.
"""
import sys
import types
from pathlib import Path

import pytest

from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_helper import session_cookie, stored_session_secret  # noqa: E402


@pytest.fixture
def settings():
    """One dict behind BOTH `Env.setting` and `Env.get('settings')`.

    The password hook writes through `Env.get('settings').set(...)` rather than
    `Env.setting(value=...)`, deliberately -- see
    TestAuthRequiredAndPasswordArePersistedTogether. A fixture that stubbed
    only one of the two would let these tests disagree with the code about
    where settings live, so both views share the same storage.
    """
    data = {'api_key': 'THEKEY'}
    original_setting = Env.setting
    original_get = Env.get

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            data[key] = kwargs['value']
            return
        return data.get(key, kwargs.get('default', ''))

    class FakeSettings:
        def addSection(self, section):
            pass

        def set(self, section, option, value):
            data[option] = value

        def save(self):
            raise AssertionError(
                'the password hook must not save on its own: auth_required '
                'would land on disk before the password'
            )

        def get(self, attr, default=None, section='core', type=None):
            return data.get(attr, default)

    def mock_get(key, default=None):
        if key == 'settings':
            return FakeSettings()
        return original_get(key, default) if key != 'dev' else False

    Env.setting = staticmethod(mock_setting)
    Env.get = staticmethod(mock_get)
    yield data
    Env.setting = original_setting
    Env.get = original_get


def _request(cookie=None):
    return types.SimpleNamespace(cookies=({'user': cookie} if cookie else {}))


@pytest.fixture
def session():
    """A signing secret in the property store, and a valid cookie for it.

    The cookie used to BE `api_key`, so these tests could write 'THEKEY' and
    have it accepted. It is now an HMAC-signed token, minted by the one test
    helper (AC-ARCH-14) rather than constructed here.
    """
    with stored_session_secret():
        yield session_cookie()


def _current_user(request):
    from couchpotato import get_current_user
    return get_current_user(request)


class TestAuthRequiredOn:
    """Six cases: both auth_required states across the credential combinations."""

    @pytest.mark.parametrize('username,password', [
        ('admin', 'secret'),
        ('', 'secret'),      # the trap: password set, username blank
    ])
    def test_no_cookie_is_denied(self, settings, username, password):
        settings.update({'username': username, 'password': password, 'auth_required': 1})

        assert _current_user(_request()) is None, (
            'auth_required is ON but a request with no session cookie was '
            'served (username=%r password=%r)' % (username, password)
        )

    @pytest.mark.parametrize('username', ['admin', ''])
    def test_auth_required_with_no_password_still_denies(self, settings, username):
        """FAILS CLOSED, and the expectation has now moved twice -- recorded
        because the second move reversed the first.

        Originally these two cases were folded into `test_no_cookie_is_denied`,
        so the suite asserted the LOCKOUT was correct. I split them out and
        made them assert the opposite: that a requirement nothing can satisfy
        should not be enforced.

        That was wrong. Measured against a real `create_app`, serving without
        authentication in this state gave an unauthenticated caller a 200 on
        /wanted/, the api_key embedded in that page, and a reachable
        `movie.delete?delete_from=all`. It traded a recoverable lockout for
        remote deletion of the library -- inverting this project's own
        precedence, where irrecoverable data loss and security both outrank
        operability.

        So the original expectation was right and my reasoning for changing it
        was not. What HAS changed is everything around it: `Core
        .guardAuthRequired` stops the UI and wizard creating the state,
        `saveView` reports the value it actually stored so the checkbox cannot
        lie, and the remedy is now logged at ERROR. The state is reachable only
        by hand-editing config.ini or restoring a backup, both of which need
        the filesystem access that fixing it also needs.

        See tests/unit/test_auth_required_lockout_guard.py.
        """
        settings.update({'username': username, 'password': '', 'auth_required': 1})

        assert _current_user(_request()) is None, (
            'auth_required is ON with no password and the request was SERVED. '
            'An unauthenticated caller then reads the api_key out of the page '
            'and can delete the library (username=%r)' % (username,)
        )

    def test_a_valid_cookie_is_accepted(self, settings, session):
        settings.update({'username': 'admin', 'password': 'secret', 'auth_required': 1})

        assert _current_user(_request(session)) is True

    def test_a_wrong_cookie_is_denied(self, settings, session):
        settings.update({'username': 'admin', 'password': 'secret', 'auth_required': 1})

        assert _current_user(_request('not-the-key')) is None

    def test_the_api_key_is_no_longer_a_valid_cookie(self, settings, session):
        """D5: no compatibility window. Every browser that logged in before
        this change holds exactly this value, and it stops working on the
        first request after upgrade -- the way back in is the login page with
        the password the operator already has."""
        settings.update({'username': 'admin', 'password': 'secret', 'auth_required': 1})

        assert _current_user(_request('THEKEY')) is None

    def test_a_blank_username_does_not_disable_auth(self, settings, session):
        """The whole point. This combination was PUBLIC before."""
        settings.update({'username': '', 'password': 'secret', 'auth_required': 1})

        assert _current_user(_request()) is None, (
            'a blank username disabled authentication even with auth_required '
            'ON -- the exact trap the old `if username and password` gate set'
        )
        assert _current_user(_request(session)) is True, (
            'a blank username must mean "any username is accepted", not '
            '"nobody can log in"'
        )


class TestAuthRequiredOff:
    """Open is a state someone chose, and it must actually be open."""

    @pytest.mark.parametrize('username,password', [
        ('admin', 'secret'),
        ('', 'secret'),
        ('', ''),
    ])
    def test_everything_is_public(self, settings, username, password):
        settings.update({'username': username, 'password': password, 'auth_required': 0})

        assert _current_user(_request()) is True


class TestTheDefault:

    def test_absent_auth_required_with_a_password_is_treated_as_ON(self, settings):
        """Existing password-protected installs must not fall open on upgrade.

        `auth_required` is absent from every config.ini written before this
        change. Reading it as falsy would silently unprotect exactly the
        installs that had bothered to set a password.
        """
        settings.update({'username': 'admin', 'password': 'secret'})
        settings.pop('auth_required', None)

        assert _current_user(_request()) is None, (
            'an upgraded install with a password set became PUBLIC because '
            'auth_required was absent'
        )

    def test_absent_auth_required_without_a_password_stays_open(self, settings):
        """An install with no password never had auth; do not lock it out."""
        settings.update({'username': '', 'password': ''})
        settings.pop('auth_required', None)

        assert _current_user(_request()) is True


class TestSavingAPasswordKeepsAuthRequiredHonest:
    """The settings copy promises "Setting one turns 'Require login' on".

    It was not true. `auth_required` was written in exactly ONE place --
    `runner.py`'s startup migration -- and that is gated on the key being
    ABSENT. After the first boot of a passwordless install the key is an
    explicit `0`, so a user who then sets a password through the wizard or the
    settings UI got no authentication at all, while both field descriptions
    told them they had.

    That is the same defect class this PR exists to close: copy that promises
    an auth behaviour the code does not implement. It was introduced by the
    copy added in this PR, which makes it worse, not better.

    The second half is a lockout that neither fix caused alone. With
    `auth_required = 1` and the password cleared, `get_current_user` denies
    every request AND `login_post` refuses every credential (it now requires a
    configured password), so the operator is locked out entirely and can only
    recover by hand-editing config.ini. Reachable by setting a password and
    then clearing it. Saving the password keeps the two settings consistent in
    BOTH directions, which closes it.
    """

    @pytest.fixture
    def core(self):
        from couchpotato.core._base._core import Core
        return Core.__new__(Core)

    def test_setting_a_password_turns_auth_required_on(self, settings, core):
        settings['auth_required'] = 0

        core.md5Password('hunter2')

        assert settings['auth_required'] == 1, (
            'a password was set and authentication stayed OFF, while the '
            'settings copy says setting one turns login on'
        )

    def test_the_new_password_is_still_what_gets_stored(self, settings, core):
        """The hook's return value is what lands in config.ini; the
        auth_required write must not displace it."""
        settings['auth_required'] = 0

        stored = core.md5Password('hunter2')

        assert stored.startswith(('$2a$', '$2b$', '$2y$')), stored

    def test_clearing_the_password_turns_auth_required_off(self, settings, core):
        """Otherwise the operator is locked out with no way back in.

        auth_required=1 + no password means every request is denied and every
        login is refused, because login now requires a configured password.
        """
        settings['auth_required'] = 1

        core.md5Password('')

        assert settings['auth_required'] == 0, (
            'clearing the password left authentication ON, which denies every '
            'request AND refuses every login: an unrecoverable lockout short '
            'of hand-editing config.ini'
        )

    def test_the_lockout_state_is_not_reachable_through_the_save_hook(self, settings, core):
        """End-to-end on the state itself, not just the flag."""
        settings.update({'username': 'admin', 'password': 'old'})
        settings['auth_required'] = 1

        core.md5Password('')          # operator clears the password
        settings['password'] = ''     # ...which is then stored

        # Nobody is locked out: with no password, the instance is open.
        assert _current_user(_request()) is True


class TestAuthRequiredAndPasswordArePersistedTogether:
    """One save, not two -- or a crash between them recreates the lockout.

    `Env.setting(attr, value=...)` (`environment.py:63-76`) calls `s.save()`
    immediately and independently. `Settings.saveView` then does its own
    `self.set(section, option, new_value); self.save()` AFTER `fireEvent`
    returns. So writing `auth_required` through `Env.setting` from inside the
    password hook persists it in a SEPARATE, EARLIER save than the password
    itself.

    Setting a password: `auth_required = 1` lands on disk first. A crash, a
    full volume, or a kill between the two saves leaves authentication ON with
    no password stored -- every request denied, every login refused, and no way
    back in short of hand-editing config.ini. Exactly the lockout the change
    was written to close, reintroduced through a different door.

    So the hook must only touch the in-memory parser and let the caller's
    single save persist both. `Settings.save()` is atomic (T2.0), so one save
    means the pair lands or neither does.
    """

    def test_the_hook_does_not_save_by_itself(self, monkeypatch):
        """Pins the mechanism, because the crash window cannot be reproduced.

        Nothing observable distinguishes "wrote both in one save" from "wrote
        them in two" once both have completed -- the difference only appears if
        the process dies in between. So the assertion is on the mechanism: the
        hook must not trigger a save of its own.
        """
        from couchpotato.core._base._core import Core
        from couchpotato.environment import Env

        saves = []

        class FakeSettings:
            p = object()

            def addSection(self, section):
                pass

            def set(self, section, option, value):
                pass

            def save(self):
                saves.append(1)

            def get(self, attr, default=None, section='core', type=None):
                return default

        monkeypatch.setattr(Env, 'get', staticmethod(
            lambda key, default=None: FakeSettings() if key == 'settings' else default))

        Core.__new__(Core).md5Password('hunter2')

        assert saves == [], (
            'the password hook triggered %d independent save(s). auth_required '
            'then lands on disk BEFORE the password, and a crash in between '
            'leaves authentication on with no password: locked out.' % len(saves)
        )

    def test_the_value_still_reaches_the_settings_object(self, monkeypatch):
        """Not saving must not mean not setting -- the caller's save needs the
        value already in the parser."""
        from couchpotato.core._base._core import Core
        from couchpotato.environment import Env

        written = {}

        class FakeSettings:
            def addSection(self, section):
                pass

            def set(self, section, option, value):
                written[(section, option)] = value

            def save(self):
                raise AssertionError('the hook must not save')

            def get(self, attr, default=None, section='core', type=None):
                return default

        monkeypatch.setattr(Env, 'get', staticmethod(
            lambda key, default=None: FakeSettings() if key == 'settings' else default))

        Core.__new__(Core).md5Password('hunter2')

        assert written.get(('core', 'auth_required')) == 1, written


class TestTheStartupMigrationRunsBeforeDefaultsAreMaterialised:
    """The migration's correctness IS its position in runner.py.

    `runner.py` resolves `auth_required` only when the key is **absent**:

        if Env.setting('auth_required', default=None) in (None, ''):
            resolved = 1 if Env.setting('password') else 0

    That is what stops a password-protected install falling open on upgrade.
    It only holds because the block runs BEFORE `loader.preload()`/
    `loader.run()`, which fire `settings.register` and reach
    `Settings.registerDefaults` -> `setDefault`, materialising the registered
    default of `0` into the config.

    Move the block below the loader and the check sees `0` rather than absent,
    skips, and every existing install with a password becomes public -- with no
    failing test, no log line, and a diff that looks like tidying.

    So the ordering is pinned. A source-order assertion is a blunt instrument,
    but the alternative is a comment, and this repo has already learned what
    comments are worth when the code stops matching them.

    **What it pins is the CALL SITE**, and that changed under it once already.
    The block became a module-level function (M2, AC-ARCH-10), which moved the
    `Env.setting('auth_required', value=` literal to the top of the file --
    where it precedes everything and the ordering assertion is satisfied no
    matter where the function is actually CALLED. The same edit put the words
    "loader.run()" inside that function's docstring, so `str.find` matched the
    prose rather than the statement. Both halves of the guard were measuring
    text that has nothing to do with the ordering.

    Hence: lines, not character offsets; the CALL, not the definition; and each
    pattern asserted to match exactly once, because a pattern that matches
    twice silently measures whichever came first.
    """

    @staticmethod
    def _statement_lines(source, prefix):
        """Line numbers of real statements starting with `prefix`.

        Comment lines are excluded, so a prohibition written in prose next to
        the code cannot be mistaken for the code.
        """
        return [
            number for number, line in enumerate(source.splitlines(), start=1)
            if line.strip().startswith(prefix) and not line.strip().startswith('#')
        ]

    def test_the_migration_precedes_loader_run(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[2] /
                  'couchpotato' / 'runner.py').read_text(encoding='utf-8')

        calls = self._statement_lines(source, 'resolve_auth_required_setting()')
        loader_runs = self._statement_lines(source, 'loader.run()')

        assert len(calls) == 1, (
            'expected exactly one call to resolve_auth_required_setting(), '
            'found %d at lines %s. Zero means the startup migration is gone; '
            'more than one means this assertion is measuring whichever comes '
            'first.' % (len(calls), calls)
        )
        assert len(loader_runs) == 1, (
            'expected exactly one loader.run() statement, found %d at lines %s'
            % (len(loader_runs), loader_runs)
        )
        assert calls[0] < loader_runs[0], (
            'the auth_required migration now runs AFTER loader.run() (line %d '
            'vs %d). registerDefaults will have written auth_required = 0 by '
            'then, so the "absent" check skips and every upgraded install that '
            'had a password set becomes PUBLIC.' % (calls[0], loader_runs[0])
        )

    def test_the_migration_still_writes_the_setting_back(self):
        """The other half. An ordering assertion is satisfied perfectly by a
        migration that no longer writes anything."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[2] /
                  'couchpotato' / 'runner.py').read_text(encoding='utf-8')

        writes = self._statement_lines(source, "Env.setting('auth_required', value=")

        assert len(writes) == 1, (
            'expected exactly one write-back of auth_required in runner.py, '
            'found %d at lines %s. Zero means an install that predates the '
            'setting never gets an explicit value written down, and grepping '
            'config.ini is the documented lockout recovery.' % (len(writes), writes)
        )


class TestAuthRequiredArrivesAsAStringAtStartup:
    """At `runner.py:288` the value is a STRING, and `bool('0')` is True.

    `auth_is_required()` is called from `runner.py:288`, before `loader.run()`
    (`:333`) has reached `registerDefaults` -> `setType`. Until that runs,
    `Settings.getType` cannot find the option and falls back to `'unicode'`
    (`settings.py:375-379`), which is not a key in `_type_adapters`
    (`settings.py:16-21`) -- so `_coerce_value` returns the raw ConfigParser
    string untouched.

    So on the startup path the value is `'0'` or `'1'`, never an int. Every
    other test in this file hands back real Python ints, which means the
    `isinstance(configured, str)` branch had no coverage at all while being the
    only thing standing between an operator and a lockout:

        bool('0') is True

    Drop that branch and an install with an explicit `auth_required = 0` and no
    password comes up with authentication ON and no credential that can satisfy
    it. That is the same lockout this branch has already had to close twice, so
    it gets a test rather than a comment.
    """

    def test_the_premise_holds_an_unregistered_option_is_not_coerced(self):
        """Verify the REASON, not just the behaviour.

        If someone later registers the type earlier and this stops being true,
        this fails and points at the branch below rather than leaving it as
        unexplained defensive code nobody dares delete.
        """
        from couchpotato.core.settings import Settings, _coerce_value

        s = Settings.__new__(Settings)
        s.types = {}
        assert s.getType('core', 'auth_required') == 'unicode', (
            'auth_required now has a registered type at lookup time; if that '
            'is true at runner.py:288 as well, the string branch in '
            'auth_is_required may no longer be needed'
        )
        assert _coerce_value('0', 'unicode') == '0', (
            "'unicode' is not in _type_adapters, so the raw string must pass "
            'through uncoerced'
        )

    def test_the_trap_this_guards_is_real(self):
        """Anti-vacuity: without the branch, `'0'` reads as True."""
        assert bool('0') is True

    @pytest.mark.parametrize('stored', ['0', 'false', 'False', 'no', 'off', ' 0 ', ''])
    def test_a_falsy_string_leaves_auth_off(self, settings, stored):
        settings['auth_required'] = stored
        settings['password'] = ''

        assert _current_user(_request()) is True, (
            'auth_required was the string %r, which the operator set to turn '
            'authentication OFF. It came up ON instead, and with no password '
            'stored nothing can satisfy it -- the operator is locked out of '
            'their own server.' % (stored,)
        )

    @pytest.mark.parametrize('stored', ['1', 'true', 'True', 'yes', 'on', ' 1 '])
    def test_a_truthy_string_turns_auth_on(self, settings, session, stored):
        settings['auth_required'] = stored
        settings['password'] = 'hashed'

        assert _current_user(_request()) is None, (
            'auth_required was the string %r and the server stayed PUBLIC' % (stored,)
        )
        assert _current_user(_request(session)) is True

    def test_an_unrecognised_string_with_a_password_stays_shut(self, settings, session):
        """Garbage in config.ini must not open the server.

        A hand-edited config.ini is the documented lock-out recovery path, so
        typos in this field are expected. This test found a real defect: `'yess'`
        is in neither the truthy nor the falsy set, and the original branch
        returned False for anything it did not recognise -- so a single typo
        silently made a password-protected server PUBLIC.
        """
        settings['auth_required'] = 'yess'
        settings['password'] = 'hashed'

        assert _current_user(_request()) is None, (
            'a typo in auth_required made the server public'
        )
        assert _current_user(_request(session)) is True, (
            'the password can still satisfy the gate'
        )

    def test_an_unrecognised_string_without_a_password_does_not_lock_out(self, settings):
        """...but "fail closed" must not mean "fail unopenable".

        Reading garbage as ON would turn auth on for an install with no
        password, which nothing can then satisfy -- the lockout this branch has
        already had to close twice. So an unrecognised value derives from the
        password instead of picking a fixed side, which errs shut exactly when
        there is a credential to open it with.
        """
        settings['auth_required'] = 'yess'
        settings['password'] = ''

        assert _current_user(_request()) is True, (
            'a typo in auth_required locked the operator out of a server that '
            'has no password to log in with'
        )
