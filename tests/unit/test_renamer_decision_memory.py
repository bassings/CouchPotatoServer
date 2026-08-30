"""FEAT-012: the renamer remembers it has already looked at a file.

Step one of the TDD build. Pins the core defect from the spec's Problem
section, measured on production: a refusal that is CORRECT (the collision
really cannot be resolved automatically) gets re-decided from scratch on
every scheduled scan forever, because the code has no memory of "I already
looked at this and nothing has changed" -- only of the refusal itself, which
it re-derives every time.

Binding decision 1 (specs/FEAT-012-renamer-remembers-its-decisions.md): the
skip lives entirely in `Renamer.scan` and is evaluated BEFORE
`fireEvent('scanner.scan', ...)`. That is why this test drives the real
`Renamer.scan()` entry point rather than the lower-level
`_moveRenamedFiles` that the existing replacement tests use -- the cost this
spec removes is the folder walk and identity resolution inside
`scanner.scan` itself, not just the log line that follows it.

The scenario is the spec's own production incident: a single-file group whose
identity was never asserted (no `identity_source`), colliding with an
existing library file. That refusal is `declined_unverified_identity` and it
is correct and must keep firing -- once. Nothing here is a REPLACE scenario,
so this test needs no `upgrade_replace` wiring at all.

Currently RED: nothing remembers anything yet, so `scan()` calls
`fireEvent('scanner.scan', ...)` unconditionally on every invocation. Five
identical scans of one unchanged group currently ask the scanner five times.
"""
import logging
import os
import subprocess

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from tests.unit.conftest import sanitized_git_env

# env=sanitized_git_env() on every git call here, enforced by
# tests/unit/test_fixtures_do_not_leak_gitdir.py and not optional: git exports
# GIT_DIR into a pre-push hook launched from a worktree, so an unsanitised
# call operates on the REAL repository rather than its own cwd. That is a
# recorded incident in this repo, not a hypothetical.
REPO_ROOT = subprocess.run(
    ['git', 'rev-parse', '--show-toplevel'],
    capture_output=True, text=True, check=True,
    env=sanitized_git_env(),
).stdout.strip()


@pytest.fixture(autouse=True)
def _dead_setting_flag_does_not_leak():
    """`_warned_dead_setting` is a class attribute other test modules also
    set. Restore it around this file so a leaked value in either direction
    cannot make a test in this file, or a test after it, pass for the wrong
    reason."""
    original = Renamer._warned_dead_setting
    Renamer._warned_dead_setting = True
    yield
    Renamer._warned_dead_setting = original


@pytest.fixture
def world(tmp_path, monkeypatch):
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    group_folder = downloads / 'Minions.and.Monsters.2015.1080p.BluRay.x264-GRP'
    group_folder.mkdir()
    src = group_folder / 'movie.mkv'
    src.write_bytes(b'incoming download bytes' * 100)

    library = tmp_path / 'library'
    library.mkdir()
    dst = library / 'Minions and Monsters.mkv'
    # The pre-existing library copy: this collision is what makes the group
    # "declined" rather than a plain successful move, exactly as in the
    # production incident.
    dst.write_bytes(b'existing library bytes' * 50)
    original_dst_bytes = dst.read_bytes()
    original_src_bytes = src.read_bytes()

    conf_values = {
        'to': str(library),
        # An empty folder template plus a literal file name makes the
        # destination path exactly predictable without duplicating
        # doReplace's own token-substitution logic in the fixture.
        'folder_name': '',
        'file_name': dst.name,
        'default_file_action': 'move',
        'cleanup': False,
    }

    def _group():
        return {
            'media': {
                '_id': 'media-1',
                'info': {'titles': ['Minions and Monsters'], 'year': 2015},
            },
            'meta_data': {'quality': {'identifier': '1080p', 'is_3d': False}},
            'files': {'movie': [str(src)]},
            'parentdir': str(group_folder),
            'dirname': group_folder.name,
            # Deliberately absent: no `identity_source` is exactly what
            # makes the outcome `declined_unverified_identity`, the refusal
            # the spec's production incident names by name.
        }

    scan_calls = {'scanner.scan': 0}
    notify_calls = []

    def _fire(event, *args, **kwargs):
        if event == 'scanner.scan':
            scan_calls['scanner.scan'] += 1
            return {'group-1': _group()}
        if event == 'notify':
            # Captured, not asserted on by the original test -- this is
            # binding decision 3's out-of-band surface (item 5): one
            # fireEvent('notify', ...) per parked group, nothing more.
            notify_calls.append(kwargs if kwargs else (args[0] if args else None))
            return None
        return None

    monkeypatch.setattr(
        'couchpotato.core.plugins.renamer.main.fireEvent', _fire,
    )

    plugin = Renamer.__new__(Renamer)
    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: conf_values.get(key, default),
        raising=False,
    )
    monkeypatch.setattr(
        type(plugin), 'shuttingDown', lambda _self: False, raising=False,
    )

    return {
        'plugin': plugin,
        'downloads': str(downloads),
        'src': str(src),
        'dst': str(dst),
        'original_dst_bytes': original_dst_bytes,
        'original_src_bytes': original_src_bytes,
        'scan_calls': scan_calls,
        'notify_calls': notify_calls,
        'group_factory': _group,
    }


class TestAnUnchangedDeclinedGroupIsNotRescanned:
    """AC-QA-3 / AC-QA-4 / binding decision 1.

    The refusal must be computed once, not merely logged once: what has to
    stop is the expensive scanner walk itself, not just a repeated WARNING
    line printed from a decision that is still being remade every time.
    """

    def test_scanner_scan_is_asked_for_at_most_once_across_five_scans(
        self, world, caplog,
    ):
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                world['plugin'].scan(base_folder=world['downloads'])

        # Positive control (the spec's own instruction for every silence
        # criterion): the refusal must actually have fired at least once, or
        # "the scanner was only asked once" could pass because the decision
        # path was never reached at all -- proving nothing about a memory.
        refusals = [
            r for r in caplog.records
            if 'Destination already exists' in r.getMessage()
            and 'media-1' in r.getMessage()
        ]
        assert refusals, (
            'the refusal was never logged at all, so this run proves '
            'nothing about remembering it -- the decision path itself was '
            'never reached'
        )

        assert world['scan_calls']['scanner.scan'] == 1, (
            'fireEvent("scanner.scan", ...) was called %d times for 5 '
            'identical scans of one unchanged, already-declined group. '
            'This is the folder rescan and identity resolution the '
            'production incident paid for roughly 1,100 times over 36 '
            'hours; an unchanged, already-decided group must not trigger '
            'it again.' % world['scan_calls']['scanner.scan']
        )

        # "Already decided" must never become "already done" (AC-QA-12):
        # both the library file and the download must survive, byte for
        # byte, no matter how many times an unchanged scan runs.
        assert world['dst'] and open(world['dst'], 'rb').read() == world['original_dst_bytes'], (
            'the collided library file was modified by a scan that should '
            'only ever have refused'
        )
        assert open(world['src'], 'rb').read() == world['original_src_bytes'], (
            'the download was modified by a scan that should only ever '
            'have refused'
        )


class TestFolderScannerIsUntouched:
    """AC-SIMP-2 / binding decision 1 -- the data-loss guard.

    `folder_scanner.py` is shared with `manage.updateLibrary`, whose cleanup
    at `manage.py:274-275` deletes any 'done' movie absent from the scan
    result: the media document, its releases, watch history, tags, profile
    and review state, with no backup taken automatically. Nothing about the
    renamer's memory may ever change what that shared scanner returns.

    This is a structural guard, not a missing-behaviour test: the diff is
    genuinely empty right now, so this assertion PASSES today, by design.
    Its value is as a tripwire for a LATER change, and CLAUDE.md's guard
    doctrine (search "load-bearing") requires proving a guard by breaking
    the thing it protects and watching the guard fail -- which means
    editing `folder_scanner.py`, even transiently. That mutate-observe-
    restore proof is deliberately NOT done in this step: this step writes
    tests only and touches no production file. The proof belongs to the
    step that commits this test.
    """

    def test_folder_scanner_has_no_diff_against_master(self):
        result = subprocess.run(
            ['git', 'diff', '--quiet', 'master', '--',
             'couchpotato/core/plugins/scanner/folder_scanner.py'],
            cwd=REPO_ROOT,
            env=sanitized_git_env(),
        )
        assert result.returncode == 0, (
            'couchpotato/core/plugins/scanner/folder_scanner.py differs '
            'from master. This module is shared with manage.updateLibrary, '
            'whose cleanup deletes any "done" movie absent from the scan '
            'result -- the one irrecoverable loss AC-SIMP-2 exists to '
            'prevent. Run `git diff master -- '
            'couchpotato/core/plugins/scanner/folder_scanner.py` to see '
            'what changed.'
        )


class TestDestinationChangesInvalidateTheMemory:
    """AC-QA-6 (a) and (b) / design constraint: "the destination appearing
    or disappearing" must expire a remembered refusal.

    Both scenarios below leave `world['downloads']` -- the folder the
    memory actually fingerprints -- completely untouched; only the library
    file at `world['dst']` changes. That is deliberate: it isolates the gap.
    `_folderSignature` walks `scan_folder` (the downloads folder) only, so
    today NOTHING about the destination feeds the remembered key, and a
    destination change is invisible to it.

    Sub-case (c), "a destination that did not exist and now does", is not
    exercised here: every outcome in `REMEMBER_ELIGIBLE_OUTCOMES` is reached
    only from inside `if os.path.exists(dst):` in `_moveRenamedFiles`
    (main.py), so a remembered decision can only ever have been recorded
    with the destination already present -- "appearing" cannot be a later
    transition for an entry that already exists. It collapses into the
    "changed in place" case below, which is exercised.
    """

    def test_destination_deleted_forces_a_redecide_and_files_the_download(
        self, world, caplog,
    ):
        """AC-QA-6(a), the operator's actual remedy from the production
        incident: they delete the stale library file so the download can
        finally land. This must work on the next SCHEDULED scan, with no
        restart -- a remedy that silently does nothing is worse than the
        loop, because the operator believes it is handled."""
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must park the group before this test '
            'can prove anything about invalidating that park'
        )

        os.remove(world['dst'])

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])

        assert world['scan_calls']['scanner.scan'] == 2, (
            'fireEvent("scanner.scan", ...) was not called again after the '
            'blocking library file was deleted -- the memory kept treating '
            'the group as unchanged because the destination is not part of '
            'its fingerprint, so the operator\'s remedy from the '
            'production incident (deleting the stale file) would silently '
            'do nothing until the container is restarted'
        )
        assert os.path.exists(world['dst']), (
            'the download was never filed even after the blocking '
            'destination was cleared -- "already decided" outlived its '
            'own cause'
        )
        assert open(world['dst'], 'rb').read() == world['original_src_bytes'], (
            'a file exists at the destination but its bytes are not the '
            'download -- the wrong thing landed there'
        )

    def test_destination_changed_in_place_forces_a_redecide(
        self, world, caplog,
    ):
        """AC-QA-6(b): the file at the destination path is replaced with
        different bytes at the same path, without ever disappearing. A
        signature keyed only on the downloads folder cannot see this
        either."""
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must park the group before this test '
            'can prove anything about invalidating that park'
        )

        world['dst'] and open(world['dst'], 'wb').write(
            b'a different library file entirely, same path' * 10
        )

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])

        assert world['scan_calls']['scanner.scan'] == 2, (
            'fireEvent("scanner.scan", ...) was not called again after the '
            'destination file at the same path was replaced with '
            'different bytes -- an in-place destination change is '
            'invisible to a signature keyed only on the downloads folder'
        )


class TestBoundedLogHoldsIndependentlyOfMemory:
    """AC-OPS-3 restated, with the memory out of the picture entirely.

    FEAT-009B already required this exact bound once (its AC-OPS-6) and
    shipped unmet -- measured at 40 records for 20 calls, growing linearly
    -- because the bound was only ever proven on a path that happened to go
    through `log_suppressed`. `_moveRenamedFiles` is also reachable through
    a TARGETED scan (`media_folder` / `release_download`), which per D8
    neither reads nor writes the memory at all, so the backstop must hold
    on its own. This test calls `_moveRenamedFiles` directly, bypassing
    `scan()` and the memory completely.
    """

    def test_an_unchanged_collision_does_not_grow_the_log_linearly(
        self, world, caplog,
    ):
        group = world['group_factory']()
        rename_files = {world['src']: world['dst']}

        with caplog.at_level(logging.INFO):
            for _ in range(20):
                world['plugin']._moveRenamedFiles(rename_files, group)

        records = [
            r for r in caplog.records if r.levelno >= logging.INFO
        ]
        assert records, (
            'the refusal never logged at all, so this run proves nothing '
            'about a bound -- the decision path itself was never reached'
        )
        assert len(records) <= 4, (
            '_moveRenamedFiles produced %d records at INFO or above for '
            '20 direct calls against one completely unchanged collision, '
            'with the per-folder memory never involved. AC-OPS-3 requires '
            'this bound to hold independently of the memory -- exactly '
            'what FEAT-009B already required and shipped unmet, measured '
            'then at 40 records for 20 calls -- because the refusal record '
            'in _moveRenamedFiles is a plain log.warning/log.info, not '
            'wrapped in the existing log_suppressed helper.' % len(records)
        )


class TestParkedGroupIsDiscoverableViaNotify:
    """Binding decision 3 / AC-OPS-5 / AC-SEC-8 (item 5): entering a parked
    state must fire exactly one fireEvent('notify', ...), using the
    existing durable notification document and the existing
    notification.list API, so the film is discoverable without reading the
    log. No new route, template or setting.

    Currently RED: nothing in the renamer fires 'notify' at all, at any
    point, so a parked film is discoverable nowhere but the log -- which is
    exactly what AC-OPS-4's bounded restatement means an operator will not
    be reading in real time.
    """

    def test_notify_fires_once_on_park_and_not_again_on_repeat_scans(
        self, world,
    ):
        for _ in range(3):
            world['plugin'].scan(base_folder=world['downloads'])

        assert world['notify_calls'], (
            'fireEvent("notify", ...) was never called across 3 scans of '
            'a group parked as declined_unverified_identity. Binding '
            'decision 3 requires exactly one notify per parked group so '
            'the film is discoverable through notification.list without '
            'reading the log; today it is discoverable nowhere but the '
            'log.'
        )
        assert len(world['notify_calls']) == 1, (
            'fireEvent("notify", ...) fired %d times across 3 scans of '
            'one unchanged parked group; it must fire exactly once, on '
            'entering the parked state, not once per scan -- otherwise '
            'this recreates the production flood in a different channel.'
            % len(world['notify_calls'])
        )


class TestRestartRedecides:
    """AC-SEC-5 / AC-SIMP-5 / item 3: a process restart is the operator's
    cheapest correct remedy, and it must re-decide -- a memory that
    survives a restart removes the one action a human would expect to
    clear a stuck state. Nothing is persisted (AC-SIMP-5): the memory is
    plain state on the `Renamer` instance, never written through `get_db()`
    or `Env`, so a freshly constructed instance -- standing in for the
    process that comes back after a restart -- must know nothing about a
    folder an EARLIER instance parked.
    """

    def test_a_freshly_constructed_renamer_redecides_a_folder_parked_by_another_instance(
        self, world,
    ):
        world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must park the group before this test '
            'can prove anything about a restart clearing it'
        )

        # Confirm the ORIGINAL instance really did park it (a second scan on
        # the same instance must stay skipped), or the "restart" half below
        # would prove nothing -- a memory that never held anything trivially
        # "survives" no restart.
        world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the original instance did not actually park the '
            'group -- it re-asked the scanner on an unchanged repeat scan, '
            'so this test cannot isolate what a restart does'
        )

        # `conf`/`shuttingDown` were monkeypatched onto the CLASS
        # (`type(plugin)`), so a second instance inherits them without
        # redoing any of that wiring -- exactly as a real restart would
        # reconstruct the plugin against the same settings.
        restarted = Renamer.__new__(Renamer)
        restarted.scan(base_folder=world['downloads'])

        assert world['scan_calls']['scanner.scan'] == 2, (
            'a freshly constructed Renamer, standing in for the process '
            'coming back after a restart, did not re-decide a folder '
            'parked by a DIFFERENT (the pre-restart) instance -- if the '
            'memory is somehow surviving across instances, a stuck '
            'refusal would outlive the one remedy an operator expects a '
            'restart to provide'
        )
