"""T14: the password-change rotation must commit AFTER the save, not before.

`Core.md5Password` is registered as the VALUE hook for `setting.save.core.password`
(`_core.py:57`), which `Settings.saveView` calls BEFORE `self.save()` writes
`config.ini` (`settings.py:507-514`):

    new_value = fireEvent('setting.save.%s.%s' % (section, option), value, single=True)  # <- md5Password ran HERE
    self.set(section, option, stored)
    self.save()                                                                          # <- config.ini written HERE
    fireEvent('setting.save.%s.%s.after' % (section, option), single=True)               # <- and HERE

Rotating the session signing secret from the value hook meant a save that then
failed -- a read-only config directory, a permissions change, a full volume, any
I/O error -- had already signed the operator out of every device for a password
change that was never persisted. After a restart the OLD password is still
authoritative, so every session opened under it is already gone: nothing
changed, and everyone is logged out. The fix moves rotation to a NEW event,
`setting.save.core.password.committed`, fired by `saveView` only after
`self.save()` has returned without raising.

**NOT `.after`, despite that reading as the obvious name.** `fireEvent`'s own
tail (`couchpotato/core/event.py`) auto-fires `'<name>.after'` for EVERY
dispatch, including the value-hook call itself three lines above -- so a
handler on `setting.save.core.password.after` runs a first time immediately
after the value hook, BEFORE `self.set()`/`self.save()`, and only a second
time for real afterwards. A consume-and-clear hook (which this is; see
`_core.py`'s `rotateSessionSecretAfterSave`) sees the premature firing and
never the real one -- measured directly against this file's own harness before
`.committed` existed: the secret rotated even when `self.save()` was made to
raise. `.committed` is a name `fireEvent` never auto-derives from anything
else, so it is the only signal in `saveView` guaranteed to fire exactly once,
and only post-commit.

**This was attempted once and withdrawn**, and this rediscovered why on the
first real run: three attempts to measure T14 produced nothing usable, because
the harness fired only the value hook
(`fireEvent('setting.save.core.password', value, single=True)`) and never the
write or an `.after`-shaped event that real production traffic always fires
around it. Against a harness like that, "a failing save does not rotate" would
pass for a harness in which NOTHING rotates under ANY circumstance -- an
assertion that cannot fail is not coverage. So this file drives the REAL
`Settings.saveView`, backed by a REAL `Settings` object writing to a REAL
config.ini on disk, not `FakeSettings` (whose `save()` is `pass` and so cannot
be made to fail at the actual commit point). `TestASuccessfulSaveActuallyRotates`
below is deliberately the first class in the file and is treated as the
precondition for every other class: if it does not pass, nothing below it means
anything. Its FIRST version passed while wired to `.after` -- for the wrong
reason, because of the double-firing above -- which is exactly the "looks like
coverage and isn't" failure mode this task exists to avoid; `TestARealSaveFiresTheRotationExactlyOnce`
is the guard against a regression back to that shape.
"""
import sys
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from couchpotato import (  # noqa: E402
    SESSION_COOKIE_NAME, SESSION_SECRET_PROPERTY, SESSION_LIFETIME,
    ensure_session_secret, get_current_user, mint_session_token,
)
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock  # noqa: E402
from couchpotato.core import event as event_module  # noqa: E402
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter  # noqa: E402
from couchpotato.core.helpers.variable import check_password, md5  # noqa: E402
from couchpotato.core.settings import Settings  # noqa: E402
from couchpotato.environment import Env  # noqa: E402
from env_helper import env_restored  # noqa: E402


def _secret_rows(db):
    return [row for row in db._query_index('property', key=SESSION_SECRET_PROPERTY)
            if row.get('identifier') == SESSION_SECRET_PROPERTY]


def _build_env(tmp_path, bootstrap_secret=True):
    """A real `Core`, a real `Settings` writing a real `config.ini`, a real
    `SQLiteAdapter` -- the whole `setting.save.core.password` chain as
    production runs it, through `Settings.saveView` directly.

    Real `Settings` rather than `test_session_revocation.py`'s `FakeSettings`
    on purpose: `FakeSettings.save()` is `pass`, so nothing could ever inject a
    failure at the actual commit point, which is exactly what
    `TestAFailedSaveDoesNotRotate` needs to do.
    """
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    old_events = {name: list(handlers) for name, handlers in event_module.events.items()}

    db = SQLiteAdapter()
    db.create(str(tmp_path / 'db'))

    settings = Settings()
    settings.setFile(str(tmp_path / 'config.ini'))

    with env_restored():
        Env.set('db', db)
        Env.set('settings', settings)
        # Skips `Core.signalHandler`, which would otherwise replace this
        # process's SIGINT/SIGTERM handlers for the rest of the pytest run.
        Env.set('desktop', True)

        from couchpotato.core._base._core import Core
        Core()

        secret_before = ensure_session_secret(db) if bootstrap_secret else None

        yield type('EnvHandle', (), {
            'db': db, 'settings': settings, 'secret_before': secret_before,
        })()

        Env.set('desktop', False)
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
        event_module.events.clear()
        event_module.events.update(old_events)


@pytest.fixture
def env(tmp_path):
    """The protected install: a session secret already exists."""
    yield from _build_env(tmp_path)


@pytest.fixture
def fresh_env(tmp_path):
    """An install that has never had a session secret at all
    (D12/AC-SEC-46, `specs/PR2B-SESSION-COOKIE.md`)."""
    yield from _build_env(tmp_path, bootstrap_secret=False)


class TestASuccessfulSaveActuallyRotates:
    """Step 1: the instrument. Nothing below this class means anything until
    it passes -- see the module docstring for why the previous attempt at
    T14 could not tell a working guard from a harness that never rotates."""

    def test_setting_a_password_through_the_real_save_path_changes_the_secret(self, env):
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert before == env.secret_before, (
            'sanity check failed before the real assertion even runs: the '
            'property store is not returning what ensure_session_secret wrote'
        )

        result = env.settings.saveView(section='core', name='password', value='hunter3')

        assert result.get('success') is not False, (
            'the save itself was refused, so nothing below is testing what it '
            'claims to: %r' % result
        )

        after = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert after != before, (
            'a successful password change through the REAL Settings.saveView '
            'path did not rotate the session secret. This harness cannot '
            'detect rotation under any circumstance, so a "failing save does '
            'not rotate" assertion built on it would be vacuous.'
        )
        assert len(bytes.fromhex(after)) == 32, after

    def test_the_rows_do_not_accumulate(self, env):
        """Same instrument, the other failure shape a stub could hide:
        rotation that inserts a second row instead of updating the one row."""
        env.settings.saveView(section='core', name='password', value='hunter3')
        env.settings.saveView(section='core', name='password', value='hunter4')

        rows = _secret_rows(env.db)
        assert len(rows) == 1, 'password changes accumulated %d secret rows' % len(rows)

    def test_a_generated_password_with_an_asterisk_saves_and_authenticates(self, env):
        """The mask guard must accept ordinary generated symbols through the
        real hash, marker and secret-rotation chain. The old isolated test in
        test_settings_credential_masking supplied no Core hook, so it could
        only assert plaintext storage, which production must refuse now.
        """
        password = 'Tr0ub4dor&3*x'
        result = env.settings.saveView(
            section='core', name='password', value=password)

        assert result.get('success') is not False, result
        stored = env.settings.get('password')
        assert stored != password
        assert check_password(md5(password), stored)
        assert str(env.settings.get('auth_required')) == '1'
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) != env.secret_before


class TestARealSaveFiresTheRotationExactlyOnce:
    """Regression guard for the specific way the FIRST version of this file
    passed for the wrong reason -- and, per review (M1, 2026-08-11), the
    specific way a NAIVE version of THIS guard also passes for the wrong
    reason, which is why it is written the way it now is.

    The first attempt at this class counted calls to `rotate_session_secret`
    and asserted exactly one. That does not distinguish the two wirings at
    all: `rotateSessionSecretAfterSave` consumes and clears the flag on its
    FIRST firing (`_core.py`), so under `.after` -- fired once BEFORE
    `self.set()`/`self.save()` and once again after, per the module docstring
    -- the premature firing consumes the flag, rotates, and the second firing
    then finds nothing pending and returns early. The call COUNT is 1 under
    both the correct wiring and the `.after` regression; only the ORDER
    differs (rotate-then-save under the regression, save-then-rotate when
    correct). Measured directly: rewiring `.committed` back to `.after` left
    the original, count-based version of this test GREEN.

    The tests that DO catch the `.after` regression are
    `TestAFailedSaveDoesNotRotate::test_a_save_that_raises_at_self_save_does_not_rotate`
    (rotation has already happened by the time the injected failure would
    have mattered) and
    `TestThePendingFlagCannotLeakAcrossAttempts::test_a_failed_set_does_not_make_the_next_clear_rotate`.
    Both need a failure injected to notice the reordering. This class exists
    so there is a THIRD, more direct guard that asserts the ordering itself,
    without needing to inject anything failing.
    """

    def test_the_save_commits_before_the_rotation_runs(self, env, monkeypatch):
        import couchpotato

        sequence = []
        real_save = env.settings.save
        real_rotate = couchpotato.rotate_session_secret

        def spy_save():
            sequence.append(('save', env.settings.get('session_rotation_pending')))
            return real_save()

        def spy_rotate(*args, **kwargs):
            sequence.append('rotate')
            return real_rotate(*args, **kwargs)

        monkeypatch.setattr(env.settings, 'save', spy_save)
        monkeypatch.setattr(couchpotato, 'rotate_session_secret', spy_rotate)

        env.settings.saveView(section='core', name='password', value='hunter3')

        assert sequence == [('save', 1), 'rotate', ('save', '0')], (
            'the password and pending marker must commit first, then the '
            'secret rotate, then the marker clear; observed %r. Rotating '
            'before the first save signs users out for a password that may '
            'never commit, while clearing the marker before rotation loses '
            'crash recovery.' % sequence
        )


class TestAFailedSaveDoesNotRotate:
    """Step 2: the failure is injected at `self.save()` -- the real commit
    point `Settings.saveView` calls at settings.py:512 -- not at anything
    upstream of it (not `rotate_session_secret`, not the value hook)."""

    def test_a_save_that_raises_at_self_save_does_not_rotate(self, env, monkeypatch):
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)

        def explode():
            raise OSError('config directory is read-only')

        monkeypatch.setattr(env.settings, 'save', explode)

        with pytest.raises(OSError):
            env.settings.saveView(section='core', name='password', value='hunter3')

        after = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert after == before, (
            'the session secret rotated even though Settings.save() raised. '
            'Every existing session was ended for a password change that was '
            'never persisted -- after a restart the OLD password is still '
            'authoritative and there is no session left that can sign in '
            'under it either.'
        )

    def test_a_failed_save_leaves_config_ini_holding_the_old_password(self, env, monkeypatch):
        """The paired half: confirms the failure really is at the commit
        point -- config.ini on disk (what a restart reads) keeps the OLD
        password, not merely that this test asserts on the in-memory secret."""
        baseline = env.settings.saveView(section='core', name='password', value='original-pw')
        assert baseline.get('success') is not False, baseline
        original_stored = env.settings.get('password')
        assert original_stored, 'baseline save did not actually store a password'

        def explode():
            raise OSError('config directory is read-only')

        monkeypatch.setattr(env.settings, 'save', explode)

        with pytest.raises(OSError):
            env.settings.saveView(section='core', name='password', value='hunter3')

        # in-memory parser was updated by saveView before save() ran, but the
        # file on disk (what a restart actually reads) was never written
        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('password') == original_stored, (
            'config.ini on disk changed even though Settings.save() raised -- '
            'the failure was not actually happening at the commit point'
        )

    def test_error_after_replace_keeps_old_cookies_blocked(self, env, monkeypatch):
        original = env.settings.saveView(
            section='core', name='password', value='original-password')
        assert original.get('success') is not False, original
        original_hash = env.settings.get('password')
        old_cookie = mint_session_token(
            env.settings.getProperty(SESSION_SECRET_PROPERTY), SESSION_LIFETIME)
        request = SimpleNamespace(cookies={SESSION_COOKIE_NAME: old_cookie})
        assert get_current_user(request) is True

        save = env.settings.save

        def raise_after_replace():
            save()
            raise OSError('directory close failed after replace')

        monkeypatch.setattr(env.settings, 'save', raise_after_replace)
        with pytest.raises(OSError, match='after replace'):
            env.settings.saveView(
                section='core', name='password', value='new-password')

        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('password') != original_hash
        assert on_disk.get('session_rotation_pending') == '1'
        assert str(env.settings.get('session_rotation_pending')) == '1'
        assert get_current_user(request) is None


class TestConcurrentPasswordCommits:
    def test_older_callback_cannot_clear_newer_rotation_intent(
            self, env, monkeypatch):
        import threading

        baseline = env.settings.saveView(
            section='core', name='password', value='original-password')
        assert baseline.get('success') is not False, baseline

        at_a_marker_clear = threading.Event()
        release_a = threading.Event()
        b_started = threading.Event()
        b_at_rotation = threading.Event()
        failures = []
        real_clear = env.settings.clearSessionRotationPending
        real_rotate = __import__('couchpotato').rotate_session_secret

        def controlled_clear():
            if threading.current_thread().name == 'password-A':
                at_a_marker_clear.set()
                if not release_a.wait(5):
                    raise AssertionError('A was not released')
            return real_clear()

        def controlled_rotate(*args, **kwargs):
            if threading.current_thread().name == 'password-B':
                b_at_rotation.set()
                raise SystemExit('stop B after password commit')
            return real_rotate(*args, **kwargs)

        monkeypatch.setattr(env.settings, 'clearSessionRotationPending', controlled_clear)
        monkeypatch.setattr('couchpotato.rotate_session_secret', controlled_rotate)

        def save_a():
            try:
                env.settings.saveView(
                    section='core', name='password', value='password-A')
            except BaseException as exc:
                failures.append(('A', exc))

        def save_b():
            b_started.set()
            try:
                env.settings.saveView(
                    section='core', name='password', value='password-B')
            except SystemExit:
                pass
            except BaseException as exc:
                failures.append(('B', exc))

        a = threading.Thread(target=save_a, name='password-A')
        b = threading.Thread(target=save_b, name='password-B')
        a.start()
        try:
            assert at_a_marker_clear.wait(5), 'A never reached marker clearing'
            secret_after_a = env.settings.getProperty(SESSION_SECRET_PROPERTY)
            cookie = mint_session_token(secret_after_a, SESSION_LIFETIME)
            b.start()
            assert b_started.wait(5), 'B did not start'
            assert not b_at_rotation.wait(2), (
                'B committed while A still owned the password-change '
                'transaction, so A can clear B\'s pending marker')
        finally:
            release_a.set()
            a.join(5)
            if b.ident is not None:
                b.join(5)

        assert not a.is_alive() and not b.is_alive()
        assert not failures, failures
        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert check_password(md5('password-B'), on_disk.get('password'))
        assert on_disk.get('session_rotation_pending') == '1'
        assert on_disk.getProperty(SESSION_SECRET_PROPERTY) == secret_after_a
        assert get_current_user(
            SimpleNamespace(cookies={SESSION_COOKIE_NAME: cookie})) is None


class TestInternalMarkerClear:
    def test_marker_clear_reports_a_save_that_did_not_persist(self, env, monkeypatch):
        env.settings.addSection('core')
        env.settings.p.set('core', 'session_rotation_pending', '1')
        env.settings.save()
        monkeypatch.setattr(env.settings, 'save', lambda: None)

        with pytest.raises(RuntimeError, match='marker was not cleared'):
            env.settings.clearSessionRotationPending()

    def test_committed_rotation_clears_marker_even_if_ui_metadata_is_read_only(
            self, env, monkeypatch):
        rotate = __import__('couchpotato').rotate_session_secret

        def mark_read_only_after_rotation(*args, **kwargs):
            secret = rotate(*args, **kwargs)
            env.settings.p.set('core', 'session_rotation_pending_internal_meta', 'ro')
            return secret

        monkeypatch.setattr('couchpotato.rotate_session_secret',
                            mark_read_only_after_rotation)
        result = env.settings.saveView(
            section='core', name='password', value='new-password')
        assert result.get('success') is not False, result

        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('session_rotation_pending') == '0'

    def test_startup_reconciles_even_if_ui_metadata_is_read_only(self, env):
        env.settings.addSection('core')
        env.settings.p.set('core', 'session_rotation_pending', '1')
        env.settings.p.set('core', 'session_rotation_pending_internal_meta', 'ro')
        env.settings.save()

        restarted = Settings()
        restarted.setFile(str(env.settings.file))
        from couchpotato.runner import reconcile_session_rotation_pending
        assert reconcile_session_rotation_pending(settings=restarted, db=env.db)

        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('session_rotation_pending') == '0'


class TestARotationFailureDoesNotEscapeTheHook:
    """M2 (review): the `try/except` inside `rotateSessionSecretAfterSave`,
    exercised directly rather than through `fireEvent`.

    Every OTHER test in this file that patches `rotate_session_secret` to
    raise reaches `rotateSessionSecretAfterSave` through `fireEvent`, whose
    own dispatch loop already catches every handler exception
    (`couchpotato/core/event.py`, `runHandler` / `createHandle`'s
    `try/except Exception: log.error(...)`). Through that path alone, the
    `try/except` inside the hook itself is unobservable: deleting it there
    still leaves the exception caught one frame up, by `fireEvent`. Verified
    by review measurement: 41 tests stayed green with the inner `try/except`
    deleted.

    Kept anyway, as deliberate defence-in-depth: `rotateSessionSecretAfterSave`
    is a plain public method, exactly like `md5Password` -- which several of
    this project's own tests already call directly, bypassing `fireEvent`
    entirely (`test_password_storage.py`, `test_auth_required_gate.py`). Any
    future caller that reaches this method the same way -- a different
    dispatch mechanism, a migration script, a test -- gets no protection from
    `fireEvent`'s catch, and the guarantee the method's own docstring makes
    ("a rotation failure here only leaves the OLD signing secret live... never
    'authentication on, no password stored'") would silently stop holding for
    that caller. This test is what makes deleting the `try/except` a red
    build again, by calling the method directly.
    """

    def test_a_rotation_failure_does_not_raise_out_of_the_hook_called_directly(self, monkeypatch, caplog):
        import logging

        from couchpotato.core._base._core import Core

        core = Core.__new__(Core)
        core.md5Password('a-new-password')  # records intent on the real thread-local

        def explode():
            raise RuntimeError('store down near /sensitive/library')

        monkeypatch.setattr('couchpotato.rotate_session_secret', explode)

        with caplog.at_level(logging.ERROR):
            core.rotateSessionSecretAfterSave()  # must not raise

        assert any('rotat' in record.getMessage().lower() for record in caplog.records), (
            'a rotation failure was swallowed with no trace -- nothing tells '
            'the operator they are still signed in under the OLD secret'
        )
        assert '/sensitive/library' not in caplog.text


class TestThePendingFlagCannotLeakAcrossAttempts:
    """The unconditional `bool(value)` assignment in `md5Password`.

    If the flag were only ever set truthy (`if value: flag = True`), a SET
    whose `save()` then raises leaves it stuck at True -- nothing before the
    NEXT save on this option would ever clear it back to False. The very next
    save, even a CLEAR, which must never rotate, would inherit that stale
    True and rotate anyway.
    """

    def test_a_failed_set_does_not_make_the_next_clear_rotate(self, env, monkeypatch):
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)

        def explode():
            raise OSError('disk full')

        monkeypatch.setattr(env.settings, 'save', explode)
        with pytest.raises(OSError):
            env.settings.saveView(section='core', name='password', value='attempted-new-password')
        monkeypatch.undo()

        result = env.settings.saveView(section='core', name='password', value='')
        assert result.get('success') is not False, result

        after = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert after == before, (
            'a failed password SET left a stale rotation flag that a later, '
            'successful CLEAR then acted on. Clearing must never rotate: it '
            'turns auth_required off, so there is nothing left to revoke.'
        )

    def test_a_failed_set_still_rotates_on_a_later_successful_set(self, env, monkeypatch):
        """The recovery half: the flag must not get stuck refusing to fire
        either. An operator who retries after a transient failure needs the
        retry to actually revoke the old sessions."""
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)

        def explode():
            raise OSError('disk full')

        monkeypatch.setattr(env.settings, 'save', explode)
        with pytest.raises(OSError):
            env.settings.saveView(section='core', name='password', value='attempted-new-password')
        monkeypatch.undo()

        env.settings.saveView(section='core', name='password', value='hunter5')

        after = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert after != before, (
            'after a failed attempt, a retried SET that actually succeeded '
            'did not rotate -- the operator has no way left to revoke old '
            'sessions for a password that DID change'
        )


class TestClearingNeverRotates:
    """D10: clearing turns `auth_required` off, so every request is already
    served without a session -- there is nothing to revoke, and rotating
    anyway risks the other half of D10, a secret row on an install that never
    enabled authentication (AC-QA-21, AC-SEC-46 -- both
    `specs/PR2B-SESSION-COOKIE.md`; AC-QA-21 is a different requirement in
    `specs/FEAT-009B-UPGRADE-REPLACEMENT.md`)."""

    def test_clearing_does_not_rotate_an_existing_secret(self, env):
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)

        result = env.settings.saveView(section='core', name='password', value='')

        assert result.get('success') is not False, result
        after = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert after == before, (
            'clearing the password rotated the session secret, which the '
            'field only promises for SETTING one'
        )

    def test_clearing_creates_no_secret_row_on_an_install_that_never_had_one(self, fresh_env):
        assert _secret_rows(fresh_env.db) == [], 'fixture is not actually fresh'

        result = fresh_env.settings.saveView(section='core', name='password', value='')

        assert result.get('success') is not False, result
        assert _secret_rows(fresh_env.db) == [], (
            'clearing a password on an install that never enabled '
            'authentication wrote a session_secret row -- D12 and AC-SEC-46 '
            '(`specs/PR2B-SESSION-COOKIE.md`) both forbid this'
        )


class TestThePendingRotationFlagIsPerThreadNotShared:
    """L1 (review): the `_pending_rotation` class comment's own claim, made
    testable -- and qualified, because review measurement showed the claim
    was overstated as first written.

    `_pending_rotation` is `threading.local()` so direct callback use on two
    threads cannot read or clear another thread's intent. Production
    `saveView` serialises password transactions itself, and `callApiHandler`
    also holds `api_locks['settings.save']` across the HTTP handler. Neither
    lock applies to this direct-callback test.

    This test bypasses `api_locks` entirely -- it calls `md5Password` /
    `rotateSessionSecretAfterSave` directly on two real OS threads with no
    lock at all -- because that is the only way to exercise the property the
    class comment claims, given the lock closes off the real path today.
    """

    def test_a_concurrent_clear_on_another_thread_does_not_steal_a_sets_rotation(self, monkeypatch):
        import threading as _threading

        from couchpotato.core._base._core import Core

        # Bare instance, like several existing tests in this suite
        # (`test_password_storage.py`, `test_auth_required_gate.py`): no
        # `__init__`, so `core._pending_rotation` resolves to the shared
        # CLASS attribute -- which is the point, since that attribute is what
        # is under test here.
        core = Core.__new__(Core)

        calls = []
        monkeypatch.setattr('couchpotato.rotate_session_secret', lambda: calls.append('SET') or 'fake-secret')

        # Two Events, not one Barrier: a Barrier only guarantees both threads
        # have REACHED a point, not that the CLEAR's write has landed before
        # the SET's read afterwards -- a single barrier here left the two
        # post-barrier statements racing each other with no ordering
        # guarantee at all, which made an earlier version of this test pass
        # by luck under BOTH the correct code and a shared-flag mutant.
        # `clear_done` forces a strict happens-before: the CLEAR's write is
        # guaranteed complete before the SET thread ever reads the flag.
        clear_may_proceed = _threading.Event()
        clear_done = _threading.Event()
        errors = []

        def set_password():
            core.md5Password('a-new-password')  # this thread's intent: True
            clear_may_proceed.set()
            assert clear_done.wait(timeout=5), 'the CLEAR thread never finished'
            try:
                core.rotateSessionSecretAfterSave()
            except Exception as exc:  # pragma: no cover - surfaced via `errors`
                errors.append(exc)

        def clear_password_on_another_thread():
            assert clear_may_proceed.wait(timeout=5), 'the SET thread never signalled'
            core.md5Password('')  # a DIFFERENT thread's intent: False
            clear_done.set()

        t_set = _threading.Thread(target=set_password)
        t_clear = _threading.Thread(target=clear_password_on_another_thread)
        t_set.start()
        t_clear.start()
        t_set.join(timeout=5)
        t_clear.join(timeout=5)

        assert not errors, errors
        assert calls == ['SET'], (
            'a password SET on one thread lost its own rotation to an '
            'unrelated CLEAR that ran on a different thread (%r) -- the '
            'password changed but no session was revoked, which is exactly '
            'the interleaving `threading.local()` exists to prevent' % calls
        )


class TestRotationIntentSurvivesAProcessStop:
    def test_silently_refused_auth_required_update_refuses_password_save(
            self, env, monkeypatch):
        env.settings.saveView(section='core', name='password', value='original-pw')
        env.settings.set('core', 'auth_required', 0)
        env.settings.save()
        persisted = Settings()
        persisted.setFile(str(env.settings.file))
        old_password = persisted.get('password')
        old_secret = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        real_set = env.settings.set

        def refuse_auth_required(section, option, value):
            if option == 'auth_required':
                return None  # Settings.set's actual refusal convention.
            return real_set(section, option, value)

        monkeypatch.setattr(env.settings, 'set', refuse_auth_required)
        result = env.settings.saveView(
            section='core', name='password', value='new-password')

        assert result.get('success') is False
        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('password') == old_password
        assert on_disk.get('auth_required') == '0'
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == old_secret

    def test_missing_password_hook_refuses_even_without_a_core_section(self, env):
        event_module.events.pop('setting.save.core.password', None)
        env.settings.p.remove_section('core')

        result = env.settings.saveView(
            section='core', name='password', value='new-password')

        assert result.get('success') is False
        assert not env.settings.p.has_option('core', 'password')
        assert _secret_rows(env.db)[0]['value'] == env.secret_before

    @pytest.mark.parametrize('stale_marker', [0, 1])
    def test_marker_write_failure_refuses_password_save(
            self, env, monkeypatch, caplog, stale_marker):
        env.settings.saveView(section='core', name='password', value='original-pw')
        env.settings.set('core', 'session_rotation_pending', stale_marker)
        env.settings.save()
        persisted = Settings()
        persisted.setFile(str(env.settings.file))
        old_password = persisted.get('password')
        old_secret = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        real_set = env.settings.set

        def fail_marker_write(section, option, value):
            if option == 'session_rotation_pending':
                raise OSError('marker write refused near /sensitive/library')
            return real_set(section, option, value)

        monkeypatch.setattr(env.settings, 'set', fail_marker_write)
        result = env.settings.saveView(
            section='core', name='password', value='new-password')

        assert result.get('success') is False
        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('password') == old_password
        assert on_disk.get('session_rotation_pending') == str(stale_marker)
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == old_secret
        assert '/sensitive/library' not in caplog.text

    def test_hash_hook_failure_cannot_store_the_plaintext_password(
            self, env, monkeypatch):
        env.settings.saveView(section='core', name='password', value='original-pw')
        persisted = Settings()
        persisted.setFile(str(env.settings.file))
        old_password = persisted.get('password')

        def hash_failed(_value):
            raise OSError('hashing failed')

        monkeypatch.setattr('couchpotato.core._base._core.hash_password', hash_failed)
        result = env.settings.saveView(
            section='core', name='password', value='new-plaintext-secret')

        assert result.get('success') is False
        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('password') == old_password
        assert on_disk.get('session_rotation_pending') == '0'

    def test_failed_password_save_cannot_leak_into_a_later_settings_save(
            self, env, monkeypatch):
        env.settings.saveView(section='core', name='password', value='original-pw')
        persisted = Settings()
        persisted.setFile(str(env.settings.file))
        original_password = persisted.get('password')
        assert persisted.get('session_rotation_pending') == '0'

        def disk_full():
            raise OSError('disk full')

        monkeypatch.setattr(env.settings, 'save', disk_full)
        with pytest.raises(OSError, match='disk full'):
            env.settings.saveView(section='core', name='password', value='new-pw')
        monkeypatch.undo()

        # A later unrelated save serialises the in-memory parser. It must not
        # turn the failed password attempt into a delayed, unacknowledged
        # password change or persist a marker for a change that never landed.
        env.settings.set('core', 'port', 5051)
        env.settings.save()
        after = Settings()
        after.setFile(str(env.settings.file))
        assert after.get('password') == original_password
        assert after.get('session_rotation_pending') == '0'

    def test_startup_reconciles_before_any_request_can_be_served(self):
        runner_path = Path(__file__).resolve().parents[2] / 'couchpotato/runner.py'
        module = ast.parse(runner_path.read_text(encoding='utf-8'))
        startup = next(node for node in module.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == 'runCouchPotato')
        calls = {
            node.func.id: node.lineno
            for node in ast.walk(startup)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {
                'reconcile_session_rotation_pending',
                'ensure_session_secret', '_start_uvicorn_or_exit',
            }
        }
        assert set(calls) == {
            'reconcile_session_rotation_pending',
            'ensure_session_secret', '_start_uvicorn_or_exit',
        }, calls
        assert (calls['reconcile_session_rotation_pending']
                < calls['ensure_session_secret']
                < calls['_start_uvicorn_or_exit']), calls

    def test_completed_password_change_clears_durable_rotation_intent(self, env):
        result = env.settings.saveView(
            section='core', name='password', value='new-password')
        assert result.get('success') is not False, result
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) != env.secret_before

        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('session_rotation_pending') == '0', (
            'the successful rotation left the durable intent set; every '
            'ordinary restart would needlessly sign all browsers out again'
        )

    def test_password_commit_persists_rotation_intent_before_the_secret_changes(
            self, env, monkeypatch):
        def stop_between_writes():
            raise SystemExit('simulated process stop before secret rotation')

        monkeypatch.setattr('couchpotato.rotate_session_secret', stop_between_writes)

        with pytest.raises(SystemExit, match='simulated process stop'):
            env.settings.saveView(section='core', name='password', value='new-password')

        on_disk = Settings()
        on_disk.setFile(str(env.settings.file))
        assert on_disk.get('password'), 'the password did not commit before the stop'
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == env.secret_before
        assert on_disk.get('session_rotation_pending') == '1', (
            'the password committed but no durable rotation intent did; '
            'a restart would accept cookies signed under the old password'
        )

    def test_restart_reconciles_the_committed_password_before_serving(self, env, monkeypatch):
        def stop_between_writes():
            raise SystemExit('simulated process stop before secret rotation')

        monkeypatch.setattr('couchpotato.rotate_session_secret', stop_between_writes)
        with pytest.raises(SystemExit, match='simulated process stop'):
            env.settings.saveView(section='core', name='password', value='new-password')
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == env.secret_before

        # A new Settings instance reads only durable config.ini, like a new
        # process. The old Core thread-local flag cannot help this call.
        restarted = Settings()
        restarted.setFile(str(env.settings.file))
        assert restarted.get('session_rotation_pending') == '1'
        Env.set('settings', restarted)
        monkeypatch.undo()

        from couchpotato.runner import reconcile_session_rotation_pending
        reconcile_session_rotation_pending(settings=restarted, db=env.db)

        recovered_secret = restarted.getProperty(SESSION_SECRET_PROPERTY)
        assert recovered_secret != env.secret_before
        on_disk = Settings()
        on_disk.setFile(str(restarted.file))
        assert on_disk.get('session_rotation_pending') == '0'
        assert not reconcile_session_rotation_pending(settings=on_disk, db=env.db)
        assert on_disk.getProperty(SESSION_SECRET_PROPERTY) == recovered_secret

    def test_restart_refuses_old_sessions_when_rotation_fails(
            self, env, monkeypatch, caplog):
        def stop_between_writes():
            raise SystemExit('simulated process stop before secret rotation')

        monkeypatch.setattr('couchpotato.rotate_session_secret', stop_between_writes)
        with pytest.raises(SystemExit, match='simulated process stop'):
            env.settings.saveView(section='core', name='password', value='new-password')
        monkeypatch.undo()

        restarted = Settings()
        restarted.setFile(str(env.settings.file))
        assert restarted.get('session_rotation_pending') == '1'

        def unreadable_store(db=None):
            raise OSError('private path /sensitive/library must stay out of logs')

        monkeypatch.setattr('couchpotato.rotate_session_secret', unreadable_store)
        from couchpotato.runner import reconcile_session_rotation_pending

        caplog.clear()
        with pytest.raises(SystemExit) as stopped:
            reconcile_session_rotation_pending(settings=restarted, db=env.db)

        assert stopped.value.code == 1
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == env.secret_before
        on_disk = Settings()
        on_disk.setFile(str(restarted.file))
        assert on_disk.get('session_rotation_pending') == '1'
        assert 'could not be rotated' in caplog.text
        assert '/sensitive/library' not in caplog.text

    def test_current_process_refuses_old_cookie_while_rotation_is_pending(
            self, env, monkeypatch):
        old_cookie = mint_session_token(env.secret_before, SESSION_LIFETIME)
        request = SimpleNamespace(cookies={SESSION_COOKIE_NAME: old_cookie})

        def failed_rotation():
            raise OSError('signing store unavailable')

        monkeypatch.setattr('couchpotato.rotate_session_secret', failed_rotation)
        result = env.settings.saveView(
            section='core', name='password', value='new-password')

        assert result.get('success') is not False, result
        assert str(env.settings.get('session_rotation_pending')) == '1'
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == env.secret_before
        assert get_current_user(request) is None
        with pytest.raises(RuntimeError, match='revocation is pending'):
            ensure_session_secret(env.db)

    def test_no_pending_change_does_not_create_a_secret(self, fresh_env):
        from couchpotato.runner import reconcile_session_rotation_pending

        assert not reconcile_session_rotation_pending(
            settings=fresh_env.settings, db=fresh_env.db)
        assert _secret_rows(fresh_env.db) == []

    def test_failed_marker_clear_retries_safely_on_restart(self, env, monkeypatch):
        real_save = env.settings.save
        saves = 0

        def fail_second_save():
            nonlocal saves
            saves += 1
            if saves == 2:
                raise OSError('config not writable after rotation')
            return real_save()

        monkeypatch.setattr(env.settings, 'save', fail_second_save)
        result = env.settings.saveView(
            section='core', name='password', value='new-password')
        assert result.get('success') is not False, result
        first_rotation = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert first_rotation != env.secret_before

        restarted = Settings()
        restarted.setFile(str(env.settings.file))
        assert restarted.get('session_rotation_pending') == '1'

        from couchpotato.runner import reconcile_session_rotation_pending
        assert reconcile_session_rotation_pending(settings=restarted, db=env.db)
        assert restarted.getProperty(SESSION_SECRET_PROPERTY) != first_rotation
        after = Settings()
        after.setFile(str(restarted.file))
        assert after.get('session_rotation_pending') == '0'
