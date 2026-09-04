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
            'the existing "Orphan cleanup skipped: ..." warning must still '
            'fire on failure -- only the marker write is newly conditional'
        )


class TestStartupLogDistinguishesSkipFromRun:
    """AC-OPS-5."""

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

        assert any('ran' in m or 'removed' in m for m in run_messages), (
            'the run that actually cleaned the database must say so (AC-OPS-5)'
        )
        assert any('skip' in m and 'applied' in m for m in skip_messages), (
            'the run that was skipped because the marker is already applied '
            'must say so, using words an operator can distinguish from the '
            '"ran" line above (AC-OPS-5)'
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
