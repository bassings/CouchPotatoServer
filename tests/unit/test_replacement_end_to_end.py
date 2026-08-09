"""Upgrade replacement, end to end through `_moveRenamedFiles` (FEAT-009B B4b).

The first tests in this project where a library file is actually destroyed, so
they run against a real filesystem and assert on bytes rather than on return
values.

Two previous attempts at this feature were withdrawn after deleting a 2160p
remux. The shape of both failures was the same: the code did what it was told
and what it was told was wrong. So the assertions here are deliberately about
OUTCOMES ON DISK -- what survived, what did not -- not about which branch ran.

The default-off case is first because it is the one that protects every
existing install: `remove_lower_quality_copies` is already persisted True
everywhere, and if that could still enable replacement, upgrading would begin
deleting library files unprompted.
"""
import hashlib
import logging
import os

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes

OLD = b'existing 720p copy' * 100
NEW = b'incoming 2160p copy' * 900


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    lib = tmp_path / 'library'
    lib.mkdir()
    dst = lib / 'The Thing.mkv'
    dst.write_bytes(OLD)

    dl = tmp_path / 'downloads'
    dl.mkdir()
    src = dl / 'incoming.mkv'
    src.write_bytes(NEW)

    release = {
        '_id': 'r-720p',
        'files': {'movie': [str(dst)]},
        'copy_id': copy_id_for_sizes([len(OLD)]),
        'quality': '720p',
        'is_3d': False,
    }

    state = {
        'conf': {'upgrade_replace': True, 'cleanup': False},
        'status_updates': [],
        'releases': [release],
    }

    def _fire(event, *args, **kwargs):
        if event == 'release.for_media':
            return state['releases']
        if event == 'release.update_status':
            state['status_updates'].append((args[0], kwargs.get('status')))
            return True
        if event == 'quality.is_better':
            order = ['2160p', 'bd50', '1080p', '720p']
            try:
                return order.index(args[0]['identifier']) < order.index(args[1]['identifier'])
            except (KeyError, ValueError, TypeError):
                return False
        if event == 'quality.rank':
            order = ['2160p', 'bd50', '1080p', '720p']
            try:
                return order.index(args[0]['identifier'])
            except (KeyError, ValueError, TypeError):
                return None
        return None

    monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent', _fire)

    plugin = Renamer.__new__(Renamer)
    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: state['conf'].get(key, default),
        raising=False,
    )
    monkeypatch.setattr(
        type(plugin), 'moveFile',
        lambda _self, a, b, use_default=False: __import__('shutil').move(a, b),
        raising=False,
    )
    Renamer._warned_dead_setting = True     # silence the deprecation notice here

    def _group(incoming='2160p'):
        return {
            'media': {'_id': 'media-1'},
            'meta_data': {'quality': {'identifier': incoming, 'is_3d': False}},
            'files': {'movie': [str(src)]},
            'parentdir': str(dl),
        }

    return {
        'plugin': plugin, 'src': str(src), 'dst': str(dst),
        'state': state, 'group': _group, 'old_sha': _sha(dst), 'lib': lib,
    }


def _run(world, incoming='2160p'):
    world['plugin']._moveRenamedFiles({world['src']: world['dst']}, world['group'](incoming))


class TestNothingHappensUnlessTheOperatorOptedIn:
    """First, because it protects every existing install."""

    def test_with_the_new_key_off_the_library_file_is_untouched(self, world):
        world['state']['conf'] = {'upgrade_replace': False}
        _run(world)
        assert _sha(world['dst']) == world['old_sha']
        assert open(world['src'], 'rb').read() == NEW, 'the download must survive'
        assert world['state']['status_updates'] == []

    def test_the_dead_key_alone_cannot_enable_it(self, world):
        """`remove_lower_quality_copies` is already True on every install. If
        it could still enable replacement, upgrading would start deleting."""
        world['state']['conf'] = {'remove_lower_quality_copies': True}
        _run(world)
        assert _sha(world['dst']) == world['old_sha']
        assert open(world['src'], 'rb').read() == NEW


class TestABetterCopyReplacesAndTheOldReleaseIsSupersede:
    def test_the_library_file_becomes_the_new_bytes(self, world):
        _run(world)
        assert open(world['dst'], 'rb').read() == NEW

    def test_the_superseded_release_is_taken_off_done(self, world):
        """D3. `os.replace` already destroyed the old file, so the only thing
        left to account for is the record. Leaving it at `done` while it still
        claims the path is what produced the unbounded re-download loop in
        FEAT-009 designs #2 and #4."""
        _run(world)
        assert world['state']['status_updates'] == [('r-720p', 'ignored')]

    def test_no_staging_file_is_left_in_the_library(self, world):
        _run(world)
        assert [p.name for p in world['lib'].iterdir()] == ['The Thing.mkv']


class TestOnlyAStrictlyBetterRungReplaces:
    """Both directions in one class, because a single case cannot catch an
    inverted comparison: if the ranking were reversed, the equal rung would
    replace and the better one would refuse, and a test of either alone would
    still look right."""

    @pytest.mark.parametrize('incoming,should_replace', [
        ('720p', False),      # equal to what is on disk
        ('1080p', True),      # strictly better
        ('2160p', True),      # strictly better, two rungs up
    ])
    def test_the_outcome_matches_the_rung(self, world, incoming, should_replace):
        _run(world, incoming)
        if should_replace:
            assert open(world['dst'], 'rb').read() == NEW
            assert world['state']['status_updates'] == [('r-720p', 'ignored')]
        else:
            assert _sha(world['dst']) == world['old_sha']
            assert open(world['src'], 'rb').read() == NEW
            assert world['state']['status_updates'] == []


class TestTheDownloadSurvivesEveryRefusal:
    def test_an_unowned_destination_keeps_both_files(self, world):
        world['state']['releases'] = []
        _run(world)
        assert _sha(world['dst']) == world['old_sha']
        assert open(world['src'], 'rb').read() == NEW

    def test_a_multi_file_group_keeps_both_files(self, world):
        """D7: cd1 committing while cd2 fails is unrecoverable, so multi-file
        groups are refused outright."""
        group = world['group']()
        group['files']['movie'] = [world['src'], world['src'] + '.cd2']
        world['plugin']._moveRenamedFiles({world['src']: world['dst']}, group)
        assert _sha(world['dst']) == world['old_sha']
        assert open(world['src'], 'rb').read() == NEW


class TestAFailedSwapIsNotTreatedAsSuccess:
    """Found by mutation testing, not by review: changing `if ok:` to
    `if True:` passed every test, because nothing exercised a FAILING swap
    through this path.

    The consequence is worse than a missed refusal. On a failed swap the code
    would have marked the old release superseded and set `moved_any` -- so the
    database would say the 720p copy was replaced while the 720p file was
    still on disk, and `cleanup` would then be free to delete the download
    that was never installed.
    """

    def test_a_failing_swap_leaves_the_release_at_done_and_the_files_alone(
        self, world, monkeypatch
    ):
        monkeypatch.setattr(
            type(world['plugin']), 'moveFile',
            lambda _s, a, b, use_default=False: (_ for _ in ()).throw(OSError('mount gone')),
            raising=False,
        )
        _run(world)

        assert _sha(world['dst']) == world['old_sha'], 'the library file changed'
        assert open(world['src'], 'rb').read() == NEW, 'the download was lost'
        assert world['state']['status_updates'] == [], (
            'the release was marked superseded even though nothing was replaced'
        )

    def test_a_refused_swap_leaves_the_release_at_done(self, world):
        """A symlinked destination is refused by swap.py before anything is
        touched -- the database must not record a supersession either."""
        os.remove(world['dst'])
        os.symlink(world['src'], world['dst'])
        _run(world)
        assert world['state']['status_updates'] == []
        assert os.path.islink(world['dst'])


class TestTheRecordNamesTheMediaNotThePath:
    def test_no_destination_path_reaches_the_log(self, world, caplog):
        """D8. `PrivacyFilter` rewrites only the `/home/<name>` prefix, so a
        raw path would put library layout and film titles into the rotating
        ring and `docker logs` on every replacement."""
        # logging.INFO, not 'INFO'. couchpotato/core/logger.py calls
        # addLevelName(21, 'INFO'), so the STRING resolves to 21 and every real
        # INFO record (level 20) is dropped -- the capture comes back empty and
        # reads as "the code never logged". check_test_traps flags this, and
        # flagged this very line.
        with caplog.at_level(logging.INFO):
            _run(world)
        replaced = [r.getMessage() for r in caplog.records if 'Replaced a library copy' in r.getMessage()]
        assert replaced, 'the replacement was not recorded at all'
        assert world['dst'] not in replaced[0]
        assert 'media-1' in replaced[0]
        assert '720p' in replaced[0] and '2160p' in replaced[0]


class TestAFailedSupersedeDoesNotUndoASuccessfulSwap:
    def test_the_file_stays_replaced_and_the_scan_continues(self, world, monkeypatch):
        """The bytes are already swapped; raising here would not undo that and
        would abort a scan that has otherwise succeeded. A stale `done`
        release is recoverable by the next scan -- the file is not."""
        real_fire = __import__(
            'couchpotato.core.plugins.renamer.main', fromlist=['fireEvent']
        ).fireEvent

        def _fire(event, *a, **k):
            if event == 'release.update_status':
                raise RuntimeError('database went away')
            return real_fire(event, *a, **k)

        monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent', _fire)
        _run(world)                                   # must not raise
        assert open(world['dst'], 'rb').read() == NEW
