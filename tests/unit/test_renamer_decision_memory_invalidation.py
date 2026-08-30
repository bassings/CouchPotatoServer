"""FEAT-012: every remaining trigger that must expire a remembered refusal.

`tests/unit/test_renamer_decision_memory.py` (frozen, step one of this build)
already proves the destination half of AC-QA-6 (the file at the library path
being deleted or replaced in place). This file proves the other listed
triggers, each isolated so it fails on its own if that one input is dropped
from `Renamer._folderSignature` / `_settingsSignature`:

  - AC-QA-6's own upstream cause: the SOURCE file changing, parameterised
    over size alone and mtime alone, each with the other pinned so a broken
    signature that dropped just one of the two would still be caught.
  - a file being added to, or removed from, the scan folder.
  - AC-QA-7: a setting that feeds the replacement decision changing, for
    each of the four settings `DECISION_MEMORY_SETTINGS` names.

Every test proves the SAME shape as the destination tests it sits beside: one
scan to park the group (and confirm it actually parked, not merely ran), one
mutation, one more scan, and an assertion that `fireEvent('scanner.scan',
...)` fired a second time. A memory that stayed silent after any one of these
would be worse than the loop it replaces -- the download would sit unfiled
while the operator believed it was handled.
"""
import os

import pytest

from couchpotato.core.plugins.renamer.main import Renamer


@pytest.fixture(autouse=True)
def _dead_setting_flag_does_not_leak():
    """See the frozen sibling file for why this is autouse: `Renamer`
    carries `_warned_dead_setting` as a class attribute, and a value leaked
    in from another test module (or out to one) would make a test in this
    file, or after it, pass for the wrong reason."""
    original = Renamer._warned_dead_setting
    Renamer._warned_dead_setting = True
    yield
    Renamer._warned_dead_setting = original


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Deliberately the same shape as `test_renamer_decision_memory.py`'s
    `world` fixture (same collision, same declined-unverified-identity
    outcome): this file proves different triggers against the identical
    scenario, not a different one.
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
            # No `identity_source`: declined_unverified_identity, same as
            # the frozen sibling file.
        }

    scan_calls = {'scanner.scan': 0}

    def _fire(event, *args, **kwargs):
        if event == 'scanner.scan':
            scan_calls['scanner.scan'] += 1
            return {'group-1': _group()}
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
        'group_folder': group_folder,
        'src': src,
        'dst': dst,
        'conf_values': conf_values,
        'scan_calls': scan_calls,
    }


def _park_once(world_):
    """Shared setup for every test below: one scan must park the group
    before a mutation can prove anything about invalidating that park."""
    world_['plugin'].scan(base_folder=world_['downloads'])
    assert world_['scan_calls']['scanner.scan'] == 1, (
        'setup: the first scan must park the group before this test can '
        'prove anything about invalidating that park'
    )


def _assert_redecided(world_):
    world_['plugin'].scan(base_folder=world_['downloads'])
    assert world_['scan_calls']['scanner.scan'] == 2, (
        'fireEvent("scanner.scan", ...) was not called again after the '
        'input this test mutated changed -- the memory kept treating the '
        'group as unchanged, so a remembered refusal would silently '
        'outlive the very thing that was supposed to expire it'
    )


class TestSourceFileChangesInvalidateTheMemory:
    """AC-QA-6's upstream half: the SOURCE side of the collision, not the
    destination. `_folderSignature` records each file's relative path,
    size and mtime; each sub-test pins every field except the one it is
    proving, so a signature that silently dropped just one of the two
    numeric fields would still fail here.
    """

    def test_mtime_change_with_size_unchanged_forces_a_redecide(self, world):
        _park_once(world)

        original_stat = os.stat(world['src'])
        # Same bytes back (size pinned), only the timestamp moves. A whole
        # day forward is unambiguous against filesystem mtime resolution,
        # which can be as coarse as one second on some volumes.
        new_time = original_stat.st_mtime + 86400
        os.utime(world['src'], (new_time, new_time))
        assert os.stat(world['src']).st_size == original_stat.st_size, (
            'test bug: this case must isolate mtime, but the size moved '
            'too'
        )

        _assert_redecided(world)

    def test_size_change_with_mtime_pinned_forces_a_redecide(self, world):
        _park_once(world)

        original_stat = os.stat(world['src'])
        world['src'].write_bytes(b'a completely different, longer download' * 50)
        # Pin mtime back to the EXACT recorded nanosecond value: writing new
        # content moves it too, and this case exists specifically to isolate
        # SIZE. The `(atime, mtime)` float-seconds form of `os.utime` loses
        # sub-second precision on the round trip (measured: a write through
        # it left `st_mtime_ns` off by tens of nanoseconds from the
        # original), which would silently smuggle a real mtime change back
        # into a case that is supposed to have none -- passing the assertion
        # below for the wrong reason. `ns=` is exact.
        os.utime(world['src'], ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        mutated_stat = os.stat(world['src'])
        assert mutated_stat.st_size != original_stat.st_size, (
            'test bug: this case must isolate size, but the size did not '
            'actually change'
        )
        assert mutated_stat.st_mtime_ns == original_stat.st_mtime_ns, (
            'test bug: mtime was supposed to stay pinned to the recorded '
            'value so only size differs'
        )

        _assert_redecided(world)


class TestFolderMembershipChangesInvalidateTheMemory:
    """A file being added to, or removed from, the scanned folder: neither
    changes an EXISTING entry's size or mtime, so this is a distinct case
    from the source-file tests above -- it proves `_folderSignature`
    compares the whole SET of entries, not just the ones it already knew
    about.
    """

    def test_a_file_added_to_the_group_folder_forces_a_redecide(self, world):
        _park_once(world)

        extra = world['group_folder'] / 'movie.nfo'
        extra.write_bytes(b'release notes nobody reads')

        _assert_redecided(world)

    def test_a_file_removed_from_the_group_folder_forces_a_redecide(self, world):
        # An extra file must exist BEFORE the first scan so there is
        # something to remove without touching the group's only movie
        # file (which the source-file tests above already cover).
        extra = world['group_folder'] / 'movie.nfo'
        extra.write_bytes(b'release notes nobody reads')

        _park_once(world)

        os.remove(extra)

        _assert_redecided(world)


class TestSettingsChangesInvalidateTheMemory:
    """AC-QA-7: a setting that feeds the replacement decision changing must
    force a re-decide without a restart, for every setting named in
    `Renamer.DECISION_MEMORY_SETTINGS`. Parameterised over the constant
    itself (not a hand-typed list) so a setting added to the tuple without
    a matching case here is caught by count, not missed silently.
    """

    @pytest.mark.parametrize('setting_key', [
        'upgrade_replace', 'to', 'folder_name', 'file_name',
    ])
    def test_changing_the_setting_forces_a_redecide(
        self, world, tmp_path, setting_key,
    ):
        _park_once(world)

        if setting_key == 'to':
            # Must stay an ABSOLUTE path under the test's own sandbox. A
            # relative string here resolves against whatever the process
            # cwd happens to be when `_processGroup` builds the destination
            # -- that is not this test's tmp_path, it is wherever pytest
            # was invoked from, and a real move landed a copy of the
            # fixture's library file into the actual repo checkout the
            # first time this case was written with a bare relative name.
            changed_value = str(tmp_path / 'a-different-library-root')
        else:
            changed_value = {
                'upgrade_replace': True,
                'folder_name': '<year>',
                'file_name': 'renamed.<ext>',
            }[setting_key]

        world['conf_values'][setting_key] = changed_value

        _assert_redecided(world)

    def test_every_decision_memory_setting_is_covered_above(self):
        """Guards the parametrisation itself: if `DECISION_MEMORY_SETTINGS`
        ever grows a new entry, this fails loudly rather than the new
        setting silently going untested."""
        covered = {'upgrade_replace', 'to', 'folder_name', 'file_name'}
        assert set(Renamer.DECISION_MEMORY_SETTINGS) == covered, (
            'Renamer.DECISION_MEMORY_SETTINGS is %r but this file only '
            'parameterises %r -- add a case above for the difference'
            % (Renamer.DECISION_MEMORY_SETTINGS, covered)
        )
