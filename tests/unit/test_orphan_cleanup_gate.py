"""BUG-017: the orphan-movie cleanup must run once, not on every boot.

`couchpotato.core.migration.clean_orphans.clean_orphaned_movies` deletes any
media record it classifies as an orphan. On production it deleted a real
library entry ("Passengers", tt1355644) on a routine restart, because
`runner.py` called it unconditionally on every startup rather than gating it
as a one-time migration.

These tests pin the gate `runner.py` is expected to grow around that call,
keyed by the existing `Env.prop` property store (no schema change -- see
specs/BUG-017-orphan-cleanup-runs-every-boot.md). They do NOT touch
`clean_orphans.py` (AC-SIMP-6): its classification logic, including the fact
it only reads `info.*` and ignores the top-level `title`/`identifiers`, is
recorded debt, not this task.

`clean_orphaned_movies` itself is driven for real via a `SQLiteAdapter` in
every test except AC-DATA-1's, which deliberately mocks it -- see that
test's docstring for why the two need different techniques. AC-QA-4 is the
one that must survive deleting the gate; the others pin narrower contract
details (call count, marker value, log wording) that a real end-to-end test
cannot cleanly isolate on its own.

Expects `couchpotato.runner` to expose:

    _run_orphan_cleanup(db, log) -> None

called from the startup path in place of the current unconditional
try/except block, using the property `migration.clean_orphans.applied` as
the one-time marker. This function does not exist yet -- every test below
fails on import until it does, which is the correct RED for this step.
"""
import logging
from unittest.mock import patch

import pytest

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.logger import CPLog
from couchpotato.core.settings import Settings
from couchpotato.environment import Env
from couchpotato.runner import _run_orphan_cleanup

ORPHAN_MARKER = 'migration.clean_orphans.applied'

#: The logger name runner.py's own `log = CPLog(__name__)` resolves to
#: inside `couchpotato/runner.py`, so caplog can scope to it precisely
#: instead of picking up unrelated noise from the rest of the suite.
RUNNER_LOGGER = 'couchpotato.runner'


class _RealPropertySettings(Settings):
    """The REAL `getProperty`/`setProperty` -- `Env.prop`'s actual target --
    without `Settings.__init__`'s API-view/event registration or
    `setFile`'s config.ini read, neither of which belongs in a unit test and
    neither of which `Env.prop` touches. Mirrors the `FakeSettings` pattern
    in tests/unit/test_session_secret_store.py, which documents the same
    reasoning for the same class.

    `self.log` is set (real `Settings.__init__` only sets it inside
    `setFile`, which nothing here calls) because `getProperty` logs via
    `self.log.debug` on its miss path -- reading an unset property with the
    real default `Settings()` singleton crashes with AttributeError on a
    None `.log` outside a full app boot, which is exactly the crash the
    'marker absent' half of this fixture would hit if left unset.
    """

    def __init__(self):
        self.log = CPLog('test-orphan-cleanup-gate')
        self.file = None
        self.p = None
        self.directories_delimiter = '::'


def _make_db(tmp_path, name='orphan-gate'):
    adapter = SQLiteAdapter()
    adapter.create(str(tmp_path / name))
    return adapter


def _orphan_doc(imdb):
    """A movie record `clean_orphaned_movies` classifies as an orphan: no
    titles, no year, no plot. Deliberately not the richer production
    "Passengers" shape (title/identifiers/landed release) -- that gap is
    `clean_orphans.py`'s own classification bug, recorded debt and out of
    scope here (AC-SIMP-6); this file's job is only the gate around the
    call, and needs a fixture the real function agrees is an orphan.
    """
    return {
        '_t': 'media',
        'type': 'movie',
        'identifiers': {'imdb': imdb},
        'info': {},
    }


def _good_doc(imdb, title):
    """A movie record with real metadata -- `clean_orphaned_movies` must
    never remove this regardless of the gate's state."""
    return {
        '_t': 'media',
        'type': 'movie',
        'identifiers': {'imdb': imdb},
        'info': {
            'titles': [title],
            'original_title': title,
            'year': 2020,
            'plot': '',
        },
    }


@pytest.fixture
def env(tmp_path):
    """`Env` wired to a real, throwaway `SQLiteAdapter` -- the same db/
    property-store seam `_run_orphan_cleanup` and `Env.prop` will actually
    read and write in production, just pointed at tmp_path instead of the
    real data dir.
    """
    db = _make_db(tmp_path)
    old_db = Env.get('db')
    old_settings = Env.get('settings')

    Env.set('db', db)
    Env.set('settings', _RealPropertySettings())

    yield type('EnvHandle', (), {'db': db})

    Env.set('db', old_db)
    Env.set('settings', old_settings)
    db.close()


class TestMarkerAlreadySetSkipsTheCall:
    """AC-DATA-1."""

    def test_marker_already_set_skips_the_cleanup_call_and_the_orphan_survives(self, env):
        """Asserts the function is never INVOKED, not just that this one
        fixture happens to survive -- the complement to AC-QA-4's real,
        unmocked double-direction test below, which proves the observable
        behaviour but can't by itself distinguish "skipped" from "ran and
        coincidentally removed nothing".

        Patches `clean_orphans.clean_orphaned_movies` at its OWN module
        rather than `couchpotato.runner.clean_orphaned_movies`: the existing
        two migrations right below this one in runner.py
        (fix_release_quality, fix_profile_quality_order) both import their
        function locally inside their try block rather than at module level,
        and the orphan cleanup being replaced here currently does the same
        -- so this is the call-site shape already established for every
        migration in this function, not a new constraint invented for this
        test.
        """
        orphan = env.db.insert(_orphan_doc('tt0000003'))
        Env.prop(ORPHAN_MARKER, value='true')
        log = CPLog(RUNNER_LOGGER)

        with patch(
            'couchpotato.core.migration.clean_orphans.clean_orphaned_movies'
        ) as mock_clean:
            _run_orphan_cleanup(env.db, log)

        mock_clean.assert_not_called()
        survivor = env.db.get('id', orphan['_id'])
        assert survivor['identifiers']['imdb'] == 'tt0000003'


class TestMarkerSetAfterACompletedRun:
    """AC-DATA-2."""

    def test_marker_is_set_after_a_run_that_removed_nothing(self, env):
        """A migration that scanned and found nothing removable has still
        run -- it must not be retried every boot for the rest of this
        install's life just because nothing needed cleaning up this time.
        """
        env.db.insert(_good_doc('tt1234567', 'A Real Movie'))
        assert Env.prop(ORPHAN_MARKER) is None
        log = CPLog(RUNNER_LOGGER)

        _run_orphan_cleanup(env.db, log)

        assert Env.prop(ORPHAN_MARKER), (
            'the marker must be set even though clean_orphaned_movies '
            'removed zero records -- a completed no-op scan is still a '
            'completed migration (AC-DATA-2)'
        )


class TestMarkerNotSetWhenCleanupRaises:
    """AC-DATA-3."""

    def test_marker_not_set_when_cleanup_raises_and_the_warning_is_still_logged(self, env, caplog):
        """A failed migration must be retryable on the next boot, so the
        marker write has to be conditional on success -- but the existing
        behaviour of swallowing the exception into a log.warning (so a
        cleanup bug cannot abort startup) must survive unchanged; only the
        marker write becomes conditional.
        """
        env.db.insert(_orphan_doc('tt7777777'))
        log = CPLog(RUNNER_LOGGER)

        with patch(
            'couchpotato.core.migration.clean_orphans.clean_orphaned_movies',
            side_effect=RuntimeError('boom'),
        ):
            with caplog.at_level(logging.WARNING, logger=RUNNER_LOGGER):
                _run_orphan_cleanup(env.db, log)  # must not raise out of here

        assert Env.prop(ORPHAN_MARKER) is None, (
            'a failed run must not be marked applied -- it has to retry on '
            'the next start (AC-DATA-3)'
        )
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any('orphan' in r.getMessage().lower() for r in warnings), (
            'the existing "Orphan cleanup did not complete, will retry on '
            'next start: ..." warning must still fire on failure -- only '
            'the marker write is newly conditional'
        )


class TestMarkerWriteFailureStillLogsTheCount:
    """Regression test for fix round one, FIX 1.

    A reviewer of commit 312f2472f measured this against the code as it
    shipped: `_run_orphan_cleanup` wrote the marker BEFORE logging the
    removed count, so a marker write that raised (locked or read-only
    database, disk full, another writer) meant the count line was never
    reached -- the ONLY line on the runner logger read "Orphan cleanup
    skipped", indistinguishable from a no-op skip, on a boot that had just
    deleted real records. Measured on that reviewer's fixture: three
    records destroyed, log said skipped.

    The fix moves the count log above the marker write, so a failed marker
    write now produces BOTH the count line and the failure line.
    """

    def test_a_failed_marker_write_still_logs_the_removed_count(self, env, caplog):
        env.db.insert(_orphan_doc('tt5555555'))
        log = CPLog(RUNNER_LOGGER)

        original_prop = Env.prop

        def prop_that_fails_only_on_write(identifier, value=None, default=None):
            if value is None:
                return original_prop(identifier, default=default)
            raise OSError('database is locked')

        with patch('couchpotato.environment.Env.prop', side_effect=prop_that_fails_only_on_write):
            with caplog.at_level(logging.INFO, logger=RUNNER_LOGGER):
                _run_orphan_cleanup(env.db, log)  # must not raise out of here

        messages = [r.getMessage().lower() for r in caplog.records]
        assert any('orphan cleanup ran: removed 1' in m for m in messages), (
            'the count of what was actually removed must be logged even '
            'when the marker write that follows it fails -- otherwise a '
            'boot that destroyed real records logs only "skipped" (FIX 1)'
        )
        assert any('did not complete' in m or 'will retry' in m for m in messages), (
            'the marker-write failure itself must ALSO be logged, so an '
            'operator sees both what happened and that it will retry (FIX 1)'
        )
        assert Env.prop(ORPHAN_MARKER) is None, (
            'a failed marker write must leave the marker unset so the next '
            'boot retries the migration'
        )


class TestMarkerReadFailureDoesNotRunTheCleanup:
    """Regression test for fix round two, FIX A -- supersedes round one's
    FIX 5, which is now the bug.

    Round one wrapped the marker READ in its own nested try/except so a
    read failure was treated as "not yet applied" and the migration still
    ran to completion. Round two's adversarial review measured the actual
    cost of that: with the marker genuinely already set (a completed
    migration) and the read raising anyway, the nested except swallowed
    the read failure so completely that nothing downstream could tell it
    had happened. The cleanup ran a SECOND time, for real, with no warning
    logged at any level -- a completed destructive migration silently ran
    again.

    The nested try/except is deleted. The marker read now sits directly
    inside the outer try, so a read failure is caught by the SAME handler
    that already handles a failed `clean_orphaned_movies()` call or a
    failed marker write: it logs the "did not complete, will retry"
    warning, does NOT run the cleanup, and leaves the marker unset so the
    next boot retries. This is a genuine behaviour change from round one:
    a marker read failure now fails SAFE (nothing runs) rather than fail
    OPEN (the migration runs regardless of the marker's real state).
    """

    def test_marker_read_raising_prevents_a_second_destructive_run(self, env, caplog):
        """Matches the scenario the round-two review measured directly:
        the marker is genuinely already applied, and the read raises
        anyway. Proves the cleanup is not invoked a second time and a
        warning is logged, where round one's code deleted the record and
        logged nothing.
        """
        Env.prop(ORPHAN_MARKER, value='true')
        orphan = env.db.insert(_orphan_doc('tt9999999'))
        log = CPLog(RUNNER_LOGGER)

        original_prop = Env.prop

        def prop_that_fails_only_on_read(identifier, value=None, default=None):
            if value is None:
                raise AttributeError("'NoneType' object has no attribute 'debug'")
            return original_prop(identifier, value=value, default=default)

        with patch(
            'couchpotato.core.migration.clean_orphans.clean_orphaned_movies'
        ) as mock_clean:
            with patch('couchpotato.environment.Env.prop', side_effect=prop_that_fails_only_on_read):
                with caplog.at_level(logging.WARNING, logger=RUNNER_LOGGER):
                    _run_orphan_cleanup(env.db, log)  # must not raise out of here

        mock_clean.assert_not_called()
        survivor = env.db.get('id', orphan['_id'])
        assert survivor['identifiers']['imdb'] == 'tt9999999', (
            'a marker read failure must not let a completed migration run '
            'a second time'
        )
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            'did not complete' in m.lower() or 'will retry' in m.lower()
            for m in warnings
        ), (
            'a marker read failure must be logged as a warning -- silently '
            'running the migration again with no warning at any level is '
            'exactly the defect this fix removes'
        )

    def test_marker_read_raising_leaves_the_marker_unset_when_never_applied(self, env, caplog):
        """The other direction: an install that has never run the
        migration, whose read also fails. The marker must stay unset (so
        the next boot retries) and the cleanup must not run blind.
        """
        orphan = env.db.insert(_orphan_doc('tt9999998'))
        assert Env.prop(ORPHAN_MARKER) is None
        log = CPLog(RUNNER_LOGGER)

        original_prop = Env.prop

        def prop_that_fails_only_on_read(identifier, value=None, default=None):
            if value is None:
                raise AttributeError("'NoneType' object has no attribute 'debug'")
            return original_prop(identifier, value=value, default=default)

        with patch(
            'couchpotato.core.migration.clean_orphans.clean_orphaned_movies'
        ) as mock_clean:
            with patch('couchpotato.environment.Env.prop', side_effect=prop_that_fails_only_on_read):
                with caplog.at_level(logging.WARNING, logger=RUNNER_LOGGER):
                    _run_orphan_cleanup(env.db, log)  # must not raise out of here

        mock_clean.assert_not_called()
        survivor = env.db.get('id', orphan['_id'])
        assert survivor['identifiers']['imdb'] == 'tt9999998'
        assert Env.prop(ORPHAN_MARKER) is None, (
            'a marker read failure on a never-applied install must leave '
            'the marker unset so the next boot retries, not run the '
            'migration blind and not silently skip it forever either'
        )


class TestStartupLogDistinguishesSkipFromRun:
    """AC-OPS-5.

    Updated for fix round one, FIX 2: a reviewer found that
    `grep "Orphan cleanup skipped"` matched two log lines with opposite
    meanings -- the finished-and-good "already applied" INFO line, and the
    armed-and-will-retry failure WARNING line, which used to share the same
    "skipped" prefix. The failure line is now worded "Orphan cleanup did
    not complete, will retry on next start: %s" so the two states are
    distinguishable by text alone, not only by log level.

    The "ran" assertion below is also tightened: a reviewer flagged the
    original `'ran' in m or 'removed' in m` as a substring-on-prose smell
    that could match a log line that merely mentions those words rather
    than the real success message. It now checks the actual message
    prefix.
    """

    def test_startup_log_distinguishes_skip_from_run(self, env, caplog):
        """Drives the real startup path twice on the same db, same as
        AC-DATA-1's proof shape: first boot has no marker and runs (and
        removes the seeded orphan, so a "ran" line is guaranteed rather than
        depending on whether zero-removed runs also log); second boot has
        the marker and skips. An operator reading the log must be able to
        tell the two apart without cross-referencing the database.
        """
        env.db.insert(_orphan_doc('tt8888888'))
        log = CPLog(RUNNER_LOGGER)

        with caplog.at_level(logging.INFO, logger=RUNNER_LOGGER):
            _run_orphan_cleanup(env.db, log)
        run_messages = [r.getMessage().lower() for r in caplog.records]
        caplog.clear()

        with caplog.at_level(logging.INFO, logger=RUNNER_LOGGER):
            _run_orphan_cleanup(env.db, log)
        skip_messages = [r.getMessage().lower() for r in caplog.records]

        assert any('orphan cleanup ran: removed' in m for m in run_messages), (
            'the run that actually cleaned the database must log the exact '
            '"ran: removed N" line, not merely something that happens to '
            'contain "ran" or "removed" (AC-OPS-5)'
        )
        assert any('orphan cleanup skipped: already applied' in m for m in skip_messages), (
            'the run that was skipped because the marker is already applied '
            'must say so with the exact "skipped: already applied" wording, '
            'which is now the ONLY meaning that prefix carries in this '
            'logger -- the failure path no longer shares it (AC-OPS-5, FIX 2)'
        )


class TestGateIsLoadBearing:
    """AC-QA-4 -- the point of this task. One db, one fixture, both
    directions, proven with the REAL clean_orphaned_movies (no mocking):
    with the marker absent an orphan is removed; with the marker present an
    identically-shaped orphan inserted afterwards survives the same call.

    This is the test that must fail if the gate is deleted: an unconditional
    call would remove the second orphan too, since it is a genuine orphan by
    clean_orphans.py's own rules. Every other test in this file pins a
    narrower contract detail (call count, marker value, log wording) that
    this one does not by itself distinguish.
    """

    def test_marker_absent_removes_the_orphan_marker_present_keeps_it(self, env):
        log = CPLog(RUNNER_LOGGER)

        # Direction one: no marker yet -> the orphan is removed.
        first = env.db.insert(_orphan_doc('tt0000001'))
        assert Env.prop(ORPHAN_MARKER) is None

        _run_orphan_cleanup(env.db, log)

        with pytest.raises(KeyError):
            env.db.get('id', first['_id'])
        assert Env.prop(ORPHAN_MARKER), (
            'the first run must have set the marker -- direction two below '
            'depends on it, and AC-DATA-2 pins this on its own'
        )

        # Direction two: marker now set -> a fresh, identically-shaped
        # orphan inserted AFTER the first run survives the same call.
        second = env.db.insert(_orphan_doc('tt0000002'))

        _run_orphan_cleanup(env.db, log)

        survivor = env.db.get('id', second['_id'])
        assert survivor['identifiers']['imdb'] == 'tt0000002', (
            'an orphan-shaped record inserted after the marker was set must '
            'survive a later run -- if this fails, the gate is not '
            "preventing the call, only AC-DATA-1's mock made it look like it was"
        )
