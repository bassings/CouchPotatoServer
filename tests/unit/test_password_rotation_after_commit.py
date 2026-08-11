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
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from couchpotato import SESSION_SECRET_PROPERTY, ensure_session_secret  # noqa: E402
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock  # noqa: E402
from couchpotato.core import event as event_module  # noqa: E402
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter  # noqa: E402
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
    """An install that has never had a session secret at all (D12/AC-SEC-46)."""
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


class TestARealSaveFiresTheRotationExactlyOnce:
    """Regression guard for the specific way the FIRST version of this file
    passed for the wrong reason.

    Wired to `.after` instead of `.committed`, `TestASuccessfulSaveActuallyRotates`
    above still went green -- `fireEvent` auto-fires `'<name>.after'` for every
    dispatch (`event.py`), including the value hook's own call, so the handler
    ran once BEFORE `self.set()`/`self.save()` and once again after. A
    consume-and-clear hook only acts on the first of those, so the save
    "rotated" -- just at the same premature moment as the original defect --
    and nothing about that first pass distinguished it from the correct
    behaviour. Counting calls is what tells them apart.
    """

    def test_one_password_save_calls_rotate_session_secret_once(self, env, monkeypatch):
        import couchpotato

        calls = []
        real_rotate = couchpotato.rotate_session_secret

        def spy(*args, **kwargs):
            calls.append(1)
            return real_rotate(*args, **kwargs)

        monkeypatch.setattr(couchpotato, 'rotate_session_secret', spy)

        env.settings.saveView(section='core', name='password', value='hunter3')

        assert len(calls) == 1, (
            'a single password save called rotate_session_secret %d times; '
            'this is the exact double-firing shape (`.after` firing once '
            'before the commit and once after it) that made the previous '
            'wiring look correct while rotating at the wrong time' % len(calls)
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
    enabled authentication (AC-QA-21, AC-SEC-46)."""

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
            'authentication wrote a session_secret row -- D12/AC-SEC-46 both '
            'forbid this'
        )
