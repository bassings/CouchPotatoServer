"""FEAT-012: the operator's kill switch for a stale park.

H6 (branch review 2026-08-31) / AC-QA-10, AC-DATA-12, AC-OPS-10. AC-QA-10
names one API call as the remedy for any stale park: "one API call restores
the previous behaviour for the affected group without restarting the
container." As shipped, `renamer.scan` through `scanView()` -- the ONLY
entry point an operator has -- is answered from the memory exactly like a
scheduled scan, and even the one call shape that happens to bypass the
memory READ (supplying `media_folder`) never clears the remembered entry, so
the very next scheduled scan parks the group right back.

Both tests below drive `scanView()`, not `scan()` directly, because AC-QA-10
is about the button an operator actually presses -- `fireEvent('renamer.scan',
...)` is stubbed to route straight to `plugin.scan(**kwargs)`, standing in
for the real `addEvent('renamer.scan', self.scan)` wiring
(`couchpotato/core/plugins/renamer/main.py:135`), exactly as production
dispatches it.

Currently RED both ways:

  - an operator-triggered `renamer.scan` with no `media_folder` -- the
    general "force a scan" action -- is answered from memory exactly like a
    scheduled scan, so there is no way to ask again at all;
  - even the one call shape that DOES reach `_processGroup` again
    (`media_folder` set) never pops `self._decision_memory[scan_folder]`,
    so the memory it bypassed once is still sitting there, unpopped, for
    the very next scheduled scan.
"""
import logging

import pytest

from couchpotato.core.plugins.renamer.main import Renamer


@pytest.fixture(autouse=True)
def _dead_setting_flag_does_not_leak():
    """See `test_renamer_decision_memory.py` for why this is autouse:
    `Renamer` carries `_warned_dead_setting` as a class attribute, and a
    value leaked in from another test module (or out to one) would make a
    test in this file, or after it, pass for the wrong reason."""
    original = Renamer._warned_dead_setting
    Renamer._warned_dead_setting = True
    yield
    Renamer._warned_dead_setting = original


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Deliberately the same collision, the same declined_unverified_identity
    outcome, as the two sibling decision-memory test files: this file
    proves a different escape hatch against the identical scenario, not a
    different one.
    """
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    group_folder = downloads / 'Minions.and.Monsters.2015.1080p.BluRay.x264-GRP'
    group_folder.mkdir()
    src = group_folder / 'movie.mkv'
    src.write_bytes(b'incoming download bytes' * 100)

    library = tmp_path / 'library'
    library.mkdir()
    dst = library / 'Minions and Monsters.mkv'
    dst.write_bytes(b'existing library bytes' * 50)

    conf_values = {
        # The configured watch folder. A targeted `scanView(media_folder=...)`
        # call carries no `base_folder` of its own -- production never
        # passes one either, the UI only ever sends `media_folder` -- so
        # `scan()` must be able to resolve `scan_folder` from `conf('from')`
        # alone for that call shape to reach anything at all.
        'from': str(downloads),
        'to': str(library),
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
            # Deliberately absent: no `identity_source` is what makes the
            # outcome `declined_unverified_identity`, the same refusal the
            # sibling test files use.
        }

    scan_calls = {'scanner.scan': 0}
    plugin = Renamer.__new__(Renamer)

    def _fire(event, *args, **kwargs):
        if event == 'scanner.scan':
            scan_calls['scanner.scan'] += 1
            return {'group-1': _group()}
        if event == 'renamer.scan':
            # Stands in for `addEvent('renamer.scan', self.scan)`: the real
            # event bus dispatches `scanView`'s `fireEvent` straight to
            # `self.scan`. This test needs that wiring live so it can drive
            # `scanView()` -- the operator's only entry point, and the one
            # AC-QA-10 names -- rather than calling `scan()` directly.
            return plugin.scan(**kwargs)
        if event == 'notify':
            return None
        return None

    monkeypatch.setattr(
        'couchpotato.core.plugins.renamer.main.fireEvent', _fire,
    )
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
        'library': str(library),
        'group_folder': group_folder,
        'scan_calls': scan_calls,
    }


class TestOperatorTriggeredScanForcesARedecide:
    """AC-QA-10 / AC-OPS-10: the one API call an operator has must always
    re-decide, whether or not anything on disk or in settings changed --
    that is the entire point of a manual override. Restated as the
    generic "force a scan" action: no `media_folder`, exactly the shape
    the UI's "Force Scan" control sends.
    """

    def test_scan_view_with_no_media_folder_forces_a_redecide_of_a_parked_group(
        self, world, caplog,
    ):
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must park the group before this test '
            'can prove anything about the operator forcing a re-decide'
        )

        with caplog.at_level(logging.WARNING):
            result = world['plugin'].scanView(base_folder=world['downloads'])

        assert result == {'success': True}
        assert world['scan_calls']['scanner.scan'] == 2, (
            'renamer.scan through scanView() -- the documented kill '
            'switch for a stale park (AC-QA-10) -- was answered from '
            'memory exactly like a scheduled scan. An operator forcing a '
            'scan has no way to ask again: the button they press reports '
            'success while silently doing nothing.'
        )


class TestForcedScanActuallyClearsTheRememberedEntry:
    """AC-DATA-12 / AC-OPS-10: bypassing the memory check once is not the
    same as clearing it. The review measured this precisely: a
    `media_folder`-carrying `scanView()` call already reaches
    `_processGroup` again today, but it "left the entry in place" -- the
    NEXT scheduled scan (no `media_folder`, exactly what the internal
    cron sends) is answered from the SAME stale memory the operator
    thought they had just cleared.

    Proves both halves in sequence: the bypass (the second scan count),
    and that the entry was actually removed rather than merely skipped
    once (the third scan count, standing in for the next scheduled tick
    after the operator's forced call).

    `media_folder` is set to `world['library']` -- the SAME path
    `conf('to')` already resolves to -- deliberately, not to some other
    folder: `_processGroup` builds its destination as
    `media_folder or conf('to')` (`main.py:1852`), so a `media_folder`
    that differs from the library root would move the destination itself
    and confound the folder signature with a real, unrelated file move.
    Using the library root keeps the destination identical to the
    untargeted scan's, which is what isolates the ONE thing under test
    here: whether targeting bypasses the read-check without popping the
    entry, not what a `media_folder` override does to a destination path.
    """

    def test_a_targeted_forced_scan_clears_the_memory_for_the_next_scheduled_scan(
        self, world, caplog,
    ):
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must park the group before this test '
            'can prove anything about a forced scan clearing that park'
        )

        # The operator, told the file is parked, forces a re-decide
        # through the per-item UI action, which sends `media_folder`.
        with caplog.at_level(logging.WARNING):
            world['plugin'].scanView(media_folder=world['library'])
        assert world['scan_calls']['scanner.scan'] == 2, (
            'setup: the targeted, media_folder-carrying scanView() call '
            'must itself reach the scanner again, or this test cannot '
            'isolate whether the memory it bypassed was actually cleared'
        )

        # The next SCHEDULED scan: no media_folder, exactly what
        # `checkSnatched` sends on its own timer, with nothing on disk or
        # in settings having changed since the operator's forced call a
        # moment ago.
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])

        assert world['scan_calls']['scanner.scan'] == 3, (
            'the next scheduled scan after an operator-forced re-decide '
            'was answered from memory again -- the forced scan bypassed '
            'the memory CHECK for its own call but never popped the '
            'entry, so the stale park the operator thought they had just '
            'cleared silently reasserted itself on the very next '
            'scheduled tick'
        )
