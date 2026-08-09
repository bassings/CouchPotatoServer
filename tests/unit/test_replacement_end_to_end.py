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
        # `to` is the configured library root. Replacement refuses a
        # destination outside it, so a fixture without one would exercise the
        # containment refusal on every test and prove nothing about the rest.
        'conf': {
            'upgrade_replace': True,
            'cleanup': False,
            'to': str(lib),
            'default_file_action': 'move',
        },
        'status_updates': [],
        'detached': [],
        'releases': [release],
    }

    def _fire(event, *args, **kwargs):
        if event == 'release.for_media':
            return state['releases']
        if event == 'release.update_status':
            state['status_updates'].append((args[0], kwargs.get('status')))
            return True
        if event == 'release.detach_file':
            state['detached'].append((args[0], args[1]))
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

    def _set_fire(handler):
        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.main.fireEvent', handler,
        )

    _set_fire(_fire)

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
            # How determineMedia identified this movie. Anything other than
            # an ASSERTED source refuses replacement, so a fixture without
            # this would exercise that refusal on every test.
            'identity_source': 'nfo',
        }

    return {
        'plugin': plugin, 'src': str(src), 'dst': str(dst),
        'state': state, 'group': _group, 'old_sha': _sha(dst), 'lib': lib,
        'fire': _fire, 'set_fire': _set_fire,
    }


def _run(world, incoming='2160p', dst=None):
    world['plugin']._moveRenamedFiles(
        {world['src']: dst or world['dst']}, world['group'](incoming),
    )


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
        # Staging no longer goes through `moveFile` -- it is a plain
        # copyfile, deliberately, so the source survives until after the
        # swap. Breaking moveFile here would therefore break nothing and this
        # test would pass against a swap that succeeded.
        import couchpotato.core.plugins.renamer.swap as swap_module
        monkeypatch.setattr(
            swap_module.shutil, 'copyfile',
            lambda a, b, **kw: (_ for _ in ()).throw(OSError('mount gone')),
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


class TestADestinationOutsideTheLibraryIsNeverDestroyed:
    """A naming template, a crafted media title or a `media_folder` override
    can resolve outside the configured library: `doReplace` preserves path
    separators and `..`, and `os.path.join` honours an absolute component.

    Refusing to WRITE somewhere odd would be over-reach -- the ordinary move
    has always done that. Refusing to DESTROY a file outside the library the
    operator gave us is not.
    """

    @staticmethod
    def _claimed_by_a_release(world, path):
        """Point the existing release at `path`.

        Without this the test passes for the WRONG reason: no release claims
        the outside file, so ownership resolution refuses as
        `declined_no_owner` and the containment check is never reached.
        Verified by mutation -- with containment disabled, the first version
        of these two tests still passed.
        """
        from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes
        world['state']['releases'][0]['files'] = {'movie': [str(path)]}
        world['state']['releases'][0]['copy_id'] = copy_id_for_sizes(
            [os.path.getsize(str(path))]
        )

    def test_a_destination_above_the_library_root_is_refused(self, world, tmp_path):
        outside = tmp_path / 'not-the-library.mkv'
        outside.write_bytes(OLD)
        self._claimed_by_a_release(world, outside)
        before = _sha(str(outside))

        _run(world, dst=str(outside))

        assert _sha(str(outside)) == before, 'a file outside the library was destroyed'
        assert world['state']['status_updates'] == []

    def test_a_traversal_out_of_the_library_is_refused(self, world, tmp_path):
        outside = tmp_path / 'escaped.mkv'
        outside.write_bytes(OLD)
        traversal = os.path.join(
            world['state']['conf']['to'], '..', 'escaped.mkv',
        )
        self._claimed_by_a_release(world, traversal)
        before = _sha(str(outside))

        _run(world, dst=traversal)

        assert _sha(str(outside)) == before, (
            'a `..` in the destination walked out of the library and the file '
            'there was destroyed'
        )

    def test_an_unset_library_root_refuses_rather_than_permitting(self, world):
        """Unable to prove containment is not permission. An install with no
        `to` configured gets no upgrade replacement, which is inconvenient and
        recoverable; the alternative is not."""
        world['state']['conf']['to'] = None
        _run(world)
        assert _sha(world['dst']) == world['old_sha']

    def test_the_ordinary_case_inside_the_library_still_replaces(self, world):
        """The control. Without it, a guard that refuses everything would look
        identical to one that works."""
        _run(world)
        assert open(world['dst'], 'rb').read() == NEW


class TestTheDownloadIsDisposedOfAfterTheSwapNotDuringIt:
    """`default_file_action` describes how a download reaches the library. It
    was never a statement about how a temporary file is staged, and honouring
    it during staging is what left dangling links in the download folder:
    `symlink_reversed` pointed the source at the `.part` path, and `os.replace`
    then renamed that path away.

    Applied here instead, after the swap, every mode has something coherent to
    mean.
    """

    def test_move_removes_the_download(self, world):
        world['state']['conf']['default_file_action'] = 'move'
        _run(world)
        assert open(world['dst'], 'rb').read() == NEW
        assert not os.path.exists(world['src'])

    def test_copy_leaves_the_download_in_place(self, world):
        world['state']['conf']['default_file_action'] = 'copy'
        _run(world)
        assert open(world['dst'], 'rb').read() == NEW
        assert open(world['src'], 'rb').read() == NEW

    def test_symlink_reversed_points_at_the_LIBRARY_not_at_a_staging_path(self, world):
        """The finding, stated as an assertion: the link must resolve to the
        real library file. Pointing it at the staging name produced a link
        that was already dangling by the time the swap finished."""
        world['state']['conf']['default_file_action'] = 'symlink_reversed'
        _run(world)

        assert os.path.islink(world['src']), 'no link was left for the downloader'
        assert os.path.realpath(world['src']) == os.path.realpath(world['dst'])
        assert os.path.exists(world['src']), (
            'the download folder holds a DANGLING link: the downloader and '
            'the seeding client can no longer reach the file'
        )
        assert open(world['src'], 'rb').read() == NEW

    def test_link_leaves_the_download_as_an_independent_copy(self, world):
        """`link` is the SHIPPING DEFAULT, so this is the common config.

        It falls through with `copy`: nothing happens to the source. A
        hardlink back is deliberately not recreated -- the swap replaced the
        destination inode, so the old link would point at the destroyed file,
        and a new one cannot span filesystems anyway (the library and the
        download folder are routinely different mounts here).

        The behaviour change is real and worth pinning rather than leaving
        incidental: after a replacement the download is an independent copy
        rather than a hardlink, which costs disk until it is cleaned up.
        """
        world['state']['conf']['default_file_action'] = 'link'
        _run(world)

        assert open(world['dst'], 'rb').read() == NEW
        assert os.path.exists(world['src']), 'the download was removed under "link"'
        assert not os.path.islink(world['src'])
        assert os.stat(world['src']).st_ino != os.stat(world['dst']).st_ino, (
            'the download was hardlinked to the new library file; that link '
            'would break the next time the file is replaced'
        )

    def test_no_staging_file_is_left_behind_in_the_library(self, world):
        _run(world)
        strays = [
            n for n in os.listdir(os.path.dirname(world['dst']))
            if n.startswith('.cp-upgrade-')
        ]
        assert not strays, 'a .part file survived a successful swap: %r' % strays

    def test_a_failed_disposal_does_not_undo_a_completed_swap(self, world, monkeypatch):
        """The bytes are already in the library. Nothing that happens to the
        download afterwards can justify raising through a replacement that
        succeeded."""
        world['state']['conf']['default_file_action'] = 'move'
        monkeypatch.setattr(
            os, 'remove',
            lambda *a, **k: (_ for _ in ()).throw(OSError('permission denied')),
        )
        _run(world)
        assert open(world['dst'], 'rb').read() == NEW


class TestTheSupersededReleaseIsActuallyReleased:
    def test_a_refused_status_update_is_reported_not_swallowed(self, world, caplog):
        """`Release.updateStatus` CATCHES database errors and contention and
        returns False, and the dispatcher contains handler exceptions too --
        so a try/except around the fireEvent never sees the ordinary failure.

        The old bytes are already gone at this point. A release left at `done`
        while claiming a destroyed file is what produces the re-download loop
        this bookkeeping exists to prevent, so it must be loud.
        """
        import logging

        def _fire(event, *args, **kwargs):
            if event == 'release.update_status':
                return False
            return world['fire'](event, *args, **kwargs)

        world['set_fire'](_fire)
        with caplog.at_level(logging.ERROR):
            _run(world)

        assert open(world['dst'], 'rb').read() == NEW, 'the swap did not happen'
        assert any(
            'REFUSED' in r.getMessage() for r in caplog.records
        ), 'a refused status update was silently discarded'

    def test_a_successful_update_detaches_the_replaced_path(self, world):
        """Marking it `ignored` changes only the status. The document keeps
        its `files['movie']` path and `copy_id`, `release.for_media` returns
        ignored releases, and ownership resolution then sees a second claimant
        for a destination whose bytes it did not produce -- so the operator's
        NEXT upgrade refuses as ambiguous because of this one.
        """
        detached = []

        def _fire(event, *args, **kwargs):
            if event == 'release.detach_file':
                detached.append((args[0], args[1]))
                return True
            return world['fire'](event, *args, **kwargs)

        world['set_fire'](_fire)
        _run(world)

        assert detached == [('r-720p', world['dst'])], (
            'the superseded release still claims the replaced path'
        )


class TestASourceThatMovedSinceTheScanIsRefused:
    """The scanner measures the group, derives a quality rung from that
    measurement, and the renamer runs later. A downloader still appending in
    between gives a file whose rung describes an earlier, smaller version of
    itself -- and acting on it destroys a complete library copy on the
    strength of a rung the bytes have not earned.

    `meta_data['size']` is a float in MEGABYTES, summed across the group's
    movie files (`getFileSize` divides by 1024 twice). Getting the units wrong
    here is not a rounding error: it makes the comparison never match, the
    guard refuses everything, and the feature looks broken -- or, with the
    comparison the other way round, it matches nothing and the guard is inert
    while every test passes. The first implementation read `meta_data['size']`
    as a dict keyed by path, which is not its shape at all: it returned None
    for every group, so the check never ran. Mutation testing found that; no
    test did, because none of them drove the renamer with a recorded size.
    """

    @staticmethod
    def _with_recorded_size(world, megabytes):
        group = world['group']()
        group['meta_data']['size'] = megabytes
        return group

    def _run_with(self, world, group):
        world['plugin']._moveRenamedFiles({world['src']: world['dst']}, group)

    def test_a_source_matching_the_scan_still_replaces(self, world):
        """The control, and the units check. If MB and bytes were confused,
        this refuses and the feature is dead rather than dangerous."""
        actual_mb = os.path.getsize(world['src']) / 1024 / 1024
        self._run_with(world, self._with_recorded_size(world, actual_mb))
        assert open(world['dst'], 'rb').read() == NEW

    def test_a_source_that_grew_since_the_scan_is_refused(self, world):
        scanned_mb = os.path.getsize(world['src']) / 1024 / 1024
        with open(world['src'], 'ab') as handle:
            handle.write(b'z' * (4 * 1024 * 1024))     # well past the tolerance

        self._run_with(world, self._with_recorded_size(world, scanned_mb))

        assert _sha(world['dst']) == world['old_sha'], (
            'a library copy was destroyed by a file that was still downloading'
        )
        assert world['state']['status_updates'] == []

    def test_a_source_that_shrank_since_the_scan_is_refused(self, world):
        scanned_mb = (os.path.getsize(world['src']) + 8 * 1024 * 1024) / 1024 / 1024
        self._run_with(world, self._with_recorded_size(world, scanned_mb))
        assert _sha(world['dst']) == world['old_sha']

    def test_a_group_with_no_recorded_size_is_not_refused(self, world):
        """Skipped, not fabricated. A size invented here would compare equal
        to itself and read exactly like a guard that works."""
        group = world['group']()
        group['meta_data'].pop('size', None)
        self._run_with(world, group)
        assert open(world['dst'], 'rb').read() == NEW

    def test_sub_tolerance_growth_is_accepted_deliberately(self, world):
        """The documented limitation, pinned so it cannot drift silently. A
        file that grew by a few hundred kilobytes has not changed quality
        rung, and the MB round trip needs room."""
        scanned_mb = os.path.getsize(world['src']) / 1024 / 1024
        with open(world['src'], 'ab') as handle:
            handle.write(b'z' * 1000)

        self._run_with(world, self._with_recorded_size(world, scanned_mb))
        assert open(world['dst'], 'rb').read() != OLD

    def test_the_recorded_size_is_read_as_MEGABYTES_not_bytes(self, world):
        """Directly against the unit, because getting it wrong is silent in
        both directions. A byte count in that field must NOT be mistaken for a
        matching size."""
        as_bytes = os.path.getsize(world['src'])
        self._run_with(world, self._with_recorded_size(world, as_bytes))
        assert _sha(world['dst']) == world['old_sha'], (
            'the scanner figure was read as bytes; the units are megabytes'
        )

    def test_a_source_that_cannot_be_measured_is_refused(self, world):
        """Driven against the helper directly, on purpose.

        `_moveRenamedFiles` checks `os.path.exists(src)` before it gets here,
        so this branch is only reachable in the race between those two calls.
        Mutation testing showed it: flipping the OSError branch to `return
        True` changed no test, because nothing could reach it through the
        ordinary path.

        Unreachable-today is not the same as wrong, and the direction matters
        on a destructive path: unable to measure is not unchanged.
        """
        group = world['group']()
        group['meta_data']['size'] = 42.0
        # None means "do not proceed". The helper returns the measured SIZE
        # on success, so that the caller can hand it to replace_atomically as
        # `expected_source_size` and close the window between this check and
        # the staging copy.
        assert world['plugin']._sourceStillMatchesTheScan(
            group, '/definitely/not/here.mkv'
        ) is None


class TestNoFilesystemPathReachesTheLogDuringAReplacement:
    """PrivacyFilter only rewrites the `/home/<name>` and `/Users/<name>`
    prefixes. It does not remove the library layout, the film title, a NAS
    path or a Windows path, so anything else this flow logs goes into the
    rotating ring and into `docker logs` verbatim.

    Staging used to go through `moveFile`, whose every branch logs both full
    paths at INFO ('Reverse symlink "%s" to "%s"'). Moving staging off that
    mover was done for the dangling-link bug; this test is what stops the
    privacy half regressing independently of it.
    """

    def test_a_successful_replacement_logs_no_path(self, world, caplog):
        import logging

        with caplog.at_level(logging.DEBUG):
            _run(world)

        assert open(world['dst'], 'rb').read() == NEW, 'nothing was replaced'

        leaked = [
            r.getMessage() for r in caplog.records
            if world['dst'] in r.getMessage() or world['src'] in r.getMessage()
        ]
        assert not leaked, 'a filesystem path reached the log: %r' % leaked

    def test_the_record_still_identifies_the_media_and_both_rungs(self, world, caplog):
        """The privacy rule must not cost the diagnosis. Whoever debugs a bad
        swap needs to know which movie and which two rungs; the path adds
        nothing the database cannot give them from the id."""
        import logging

        with caplog.at_level(logging.WARNING):
            _run(world)

        announced = [
            r.getMessage() for r in caplog.records
            if 'About to replace' in r.getMessage()
        ]
        assert announced
        assert 'media-1' in announced[0]
        assert '720p' in announced[0] and '2160p' in announced[0]


class TestAGuessedMovieIdentityNeverAuthorisesDestruction:
    """`folder_scanner.determineMedia` has five ways to name a group. Four
    assert an identity for this exact release -- the downloader's imdb id, a
    CP tag, an NFO, an id in the filename. The fifth is `movie.search` on a
    title and year parsed out of the filename, which returns the best match
    rather than a verified answer.

    That was harmless while the scanner only added files: a wrong guess
    mis-filed a download. It is not harmless here, because the guess decides
    whose releases get fetched and therefore whose library copy gets
    destroyed.
    """

    @pytest.mark.parametrize('source', ['download_id', 'cp_tag', 'nfo', 'filename'])
    def test_an_asserted_identity_replaces(self, world, source):
        group = world['group']()
        group['identity_source'] = source
        world['plugin']._moveRenamedFiles({world['src']: world['dst']}, group)
        assert open(world['dst'], 'rb').read() == NEW, source

    def test_a_searched_identity_is_refused(self, world):
        group = world['group']()
        group['identity_source'] = 'search'
        world['plugin']._moveRenamedFiles({world['src']: world['dst']}, group)

        assert _sha(world['dst']) == world['old_sha'], (
            "a fuzzy title match destroyed a library file"
        )
        assert world['state']['status_updates'] == []

    def test_a_group_with_no_recorded_source_is_refused(self, world):
        """determineMedia writes the field on every path, so its absence
        means this group did not come from there and nothing has vouched for
        it. Refused rather than trusted."""
        group = world['group']()
        group.pop('identity_source', None)
        world['plugin']._moveRenamedFiles({world['src']: world['dst']}, group)
        assert _sha(world['dst']) == world['old_sha']

    def test_the_download_survives_the_refusal(self, world):
        group = world['group']()
        group['identity_source'] = 'search'
        world['plugin']._moveRenamedFiles({world['src']: world['dst']}, group)
        assert open(world['src'], 'rb').read() == NEW


class TestAClaimedQualityThatTheBytesContradictIsRefused:
    """`media_parser.getMetaData` PREFERS a snatched release's claimed quality
    over the scanner's own detection, so a mislabelled release description
    arrives at the decision as fact. Ranked on that label alone, a 700 MB file
    claiming 2160p outranks a genuine 1080p library copy and replaces it.

    Only the absurd is caught. The bands overlap heavily and encoding
    efficiency varies, so anything tighter would refuse real upgrades.
    """

    @staticmethod
    def _with_bands(world, low_mb):
        def _fire(event, *args, **kwargs):
            if event == 'quality.single':
                return {'identifier': args[0], 'size': (low_mb, low_mb * 10)}
            return world['fire'](event, *args, **kwargs)
        world['set_fire'](_fire)

    def test_a_file_far_below_its_claimed_band_is_refused(self, world):
        # The download is ~17 KB; a 2160p band starting at 10,000 MB.
        self._with_bands(world, 10000)
        _run(world)
        assert _sha(world['dst']) == world['old_sha'], (
            'a tiny file claiming 2160p destroyed the library copy'
        )

    def test_a_file_inside_its_band_still_replaces(self, world):
        actual_mb = os.path.getsize(world['src']) / 1024 / 1024
        self._with_bands(world, actual_mb)
        _run(world)
        assert open(world['dst'], 'rb').read() == NEW

    def test_a_file_just_under_the_band_is_still_allowed(self, world):
        """The bands are advisory. Refusing everything below the nominal floor
        would reject genuine, well-encoded upgrades, so only a file nowhere
        near its rung is treated as contradicted."""
        actual_mb = os.path.getsize(world['src']) / 1024 / 1024
        self._with_bands(world, actual_mb * 1.5)
        _run(world)
        assert open(world['dst'], 'rb').read() == NEW

    def test_an_unknown_band_does_not_refuse(self, world):
        """Nothing to check against is not evidence of a problem, and every
        one of those cases is refused elsewhere for its own reason."""
        _run(world)     # the base fixture answers None to quality.single
        assert open(world['dst'], 'rb').read() == NEW


class TestAFailedDisposalDoesNotLeakThePath:
    """The leak I introduced while removing leaks everywhere else.

    `traceback.format_exc()` puts `OSError.filename` in its final line
    regardless of the frame limit, so `[Errno 13] Permission denied:
    '/mnt/downloads/Some.Movie.2001/incoming.mkv'` reached the rotating ring
    verbatim. PrivacyFilter only rewrites a `/home/<name>` prefix, so a NAS
    mount or anything under /downloads goes straight through.

    Every deliberate record on this path is careful about paths. The one place
    that formatted an EXCEPTION rather than a message was not, which is where
    this class of leak always comes from.
    """

    def test_a_permission_error_on_the_download_does_not_name_it(
        self, world, caplog, monkeypatch
    ):
        import logging

        world['state']['conf']['default_file_action'] = 'move'
        real_remove = os.remove

        def _refuse(path, *a, **k):
            if str(path) == world['src']:
                raise PermissionError(13, 'Permission denied', world['src'])
            return real_remove(path, *a, **k)

        monkeypatch.setattr(os, 'remove', _refuse)

        with caplog.at_level(logging.DEBUG):
            _run(world)

        assert open(world['dst'], 'rb').read() == NEW, 'the swap did not happen'

        messages = ' '.join(r.getMessage() for r in caplog.records)
        assert world['src'] not in messages, (
            'the download path reached the log through an exception: %s'
            % messages
        )
        # The bound must not cost the diagnosis.
        assert 'Permission denied' in messages
        assert '13' in messages
        assert 'media-1' in messages

    def test_the_swap_is_not_undone_by_a_failed_disposal(self, world, monkeypatch):
        world['state']['conf']['default_file_action'] = 'move'
        monkeypatch.setattr(
            os, 'remove',
            lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, 'nope', '/x')),
        )
        _run(world)
        assert open(world['dst'], 'rb').read() == NEW


class TestTheDetachResultIsReadNotCaught:
    """`detachFile` wraps its own database call and RETURNS False; fireEvent's
    dispatcher contains handler exceptions too. A try/except here would only
    ever fire for something that broke before detachFile's own guard, while
    looking like it handled the ordinary failure.

    That is the same mistake `_supersedeRelease` documents 25 lines above, and
    the review was right that making it twice in one file is worse than making
    it once.
    """

    def test_a_refused_detach_is_reported(self, world, caplog):
        import logging

        def _fire(event, *args, **kwargs):
            if event == 'release.detach_file':
                return False
            return world['fire'](event, *args, **kwargs)

        world['set_fire'](_fire)
        with caplog.at_level(logging.WARNING):
            _run(world)

        assert open(world['dst'], 'rb').read() == NEW
        assert any(
            'still lists the replaced path' in r.getMessage()
            for r in caplog.records
        ), 'a refused detach was silently discarded'

    def test_an_empty_event_result_is_also_a_refusal(self, world, caplog):
        """`fireEvent(single=True)` returns `[]` when nothing handled the
        event, and `[] is not True`. An unregistered handler must not read as
        success -- the same `[]`-versus-None boundary that made the rank guard
        dead in production earlier in this feature."""
        import logging

        def _fire(event, *args, **kwargs):
            if event == 'release.detach_file':
                return []
            return world['fire'](event, *args, **kwargs)

        world['set_fire'](_fire)
        with caplog.at_level(logging.WARNING):
            _run(world)

        assert any(
            'still lists the replaced path' in r.getMessage()
            for r in caplog.records
        )

    def test_a_successful_detach_says_nothing(self, world, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            _run(world)
        assert not any(
            'still lists the replaced path' in r.getMessage()
            for r in caplog.records
        )


class TestTheWindowBetweenTheCheckAndTheStagingCopyIsClosed:
    """`_sourceStillMatchesTheScan` reads the source size, and
    `replace_atomically` reads it again before staging. Two self-consistent
    reads: a downloader appending BETWEEN them was invisible to both, so the
    swap staged a file larger than the one the quality rung describes and its
    own size check compared the staged copy against the newer measurement and
    passed.

    Passing the renamer's measurement through as `expected_source_size` is
    what closes it. Mutation testing found this twice -- dropping the argument
    at the call site changed nothing, because every test measured the source
    once and never moved it afterwards.

    The injection point is argument evaluation order: `expected_source_size`
    is already computed when `identity_of(dst)` runs, so growing the file
    inside that call lands exactly in the window.
    """

    def test_a_source_that_grows_after_the_check_is_refused(self, world, monkeypatch):
        import couchpotato.core.plugins.renamer.main as renamer_main

        real_identity_of = renamer_main.identity_of
        grew = {}

        def _grow_then_identify(path):
            if not grew:
                with open(world['src'], 'ab') as handle:
                    handle.write(b'the downloader was not finished' * 500)
                grew['yes'] = True
            return real_identity_of(path)

        monkeypatch.setattr(renamer_main, 'identity_of', _grow_then_identify)

        _run(world)

        assert grew, 'the injection point never ran; this test proves nothing'
        assert _sha(world['dst']) == world['old_sha'], (
            'a file that was still being written replaced the library copy'
        )
        assert world['state']['status_updates'] == []

    def test_an_unchanged_source_still_replaces_through_the_same_path(self, world, monkeypatch):
        """Control. Without it, a guard that refused everything would look
        identical to one that closes the window."""
        import couchpotato.core.plugins.renamer.main as renamer_main

        real_identity_of = renamer_main.identity_of
        seen = {}

        def _identify(path):
            seen['called'] = True
            return real_identity_of(path)

        monkeypatch.setattr(renamer_main, 'identity_of', _identify)
        _run(world)

        assert seen.get('called')
        assert open(world['dst'], 'rb').read() == NEW


class TestTheOperatorsOwnSizeBandsAreWhatIsEnforced:
    """`size_min`/`size_max` are what the settings UI edits (`quality.size.save`
    -> `saveSize`), and they land as separate keys on the quality DOCUMENT.
    `quality.single` returns `mergeDicts(static_quality, document)`, and the
    static `size` tuple exists only in the static half -- so nothing the
    operator changes ever reaches it.

    Reading `size` therefore enforced the SHIPPED defaults against a library
    they had deliberately retuned, silently. `quality.guess` compares against
    size_min/size_max (quality/main.py:470); this now follows the same source
    of truth instead of inventing a second one.
    """

    @staticmethod
    def _band(world, *, static_low, operator_low=None):
        doc = {'identifier': '2160p', 'size': (static_low, static_low * 10)}
        if operator_low is not None:
            doc['size_min'] = operator_low
            doc['size_max'] = operator_low * 10

        def _fire(event, *args, **kwargs):
            if event == 'quality.single':
                return dict(doc)
            return world['fire'](event, *args, **kwargs)

        world['set_fire'](_fire)

    def test_a_relaxed_operator_floor_is_honoured(self, world):
        """The shipped 2160p floor is 10,000 MB. An operator who lowered it
        must not have that decision quietly overridden."""
        actual_mb = os.path.getsize(world['src']) / 1024 / 1024
        self._band(world, static_low=10000, operator_low=actual_mb)

        _run(world)

        assert open(world['dst'], 'rb').read() == NEW, (
            "the operator's own size_min was ignored in favour of the "
            'shipped default'
        )

    def test_a_tightened_operator_floor_is_also_honoured(self, world):
        """Both directions. A guard that only ever relaxed would be
        indistinguishable from one that stopped checking."""
        actual_mb = os.path.getsize(world['src']) / 1024 / 1024
        self._band(world, static_low=actual_mb, operator_low=actual_mb * 100)

        _run(world)

        assert _sha(world['dst']) == world['old_sha'], (
            'a file below the operator-configured floor still replaced'
        )

    def test_the_static_tuple_is_the_fallback_when_no_document_value_exists(self, world):
        self._band(world, static_low=10000)     # no size_min at all
        _run(world)
        assert _sha(world['dst']) == world['old_sha']


class TestAFailedReverseSymlinkNeverDestroysTheDownload:
    """`os.remove(source)` then `symlink(...)` left a window where a failed
    link destroyed the download and created nothing -- and the warning then
    said "the download is still on disk", which was false.

    A message that reassures about data safety while the data is gone is worse
    than no message, so the ordering is fixed rather than the wording: link at
    a temporary name, then rename it over the source.
    """

    def test_a_failing_symlink_leaves_the_download_intact(self, world, monkeypatch):
        import couchpotato.core.plugins.renamer.main as renamer_main

        world['state']['conf']['default_file_action'] = 'symlink_reversed'
        monkeypatch.setattr(
            renamer_main, 'symlink',
            lambda *a, **k: (_ for _ in ()).throw(OSError(1, 'Operation not permitted')),
        )

        _run(world)

        assert open(world['dst'], 'rb').read() == NEW, 'the swap did not happen'
        assert os.path.exists(world['src']), (
            'the download was destroyed by a failed reverse symlink'
        )
        with open(world['src'], 'rb') as handle:
            assert handle.read() == NEW, 'the download was replaced by nothing'

    def test_the_warning_is_true_when_it_says_the_download_survived(self, world, monkeypatch, caplog):
        import logging

        import couchpotato.core.plugins.renamer.main as renamer_main

        world['state']['conf']['default_file_action'] = 'symlink_reversed'
        monkeypatch.setattr(
            renamer_main, 'symlink',
            lambda *a, **k: (_ for _ in ()).throw(OSError(1, 'Operation not permitted')),
        )

        with caplog.at_level(logging.WARNING):
            _run(world)

        claimed = [
            r.getMessage() for r in caplog.records
            if 'still on disk' in r.getMessage()
        ]
        assert claimed, 'the failure was not reported at all'
        assert os.path.exists(world['src']), (
            'the log claims the download is still on disk and it is not'
        )

    def test_no_temporary_link_is_left_behind_on_failure(self, world, monkeypatch):
        import couchpotato.core.plugins.renamer.main as renamer_main

        world['state']['conf']['default_file_action'] = 'symlink_reversed'
        real_symlink = renamer_main.symlink
        calls = {'n': 0}

        def _link_then_fail_the_rename(target, link_name):
            calls['n'] += 1
            real_symlink(target, link_name)

        monkeypatch.setattr(renamer_main, 'symlink', _link_then_fail_the_rename)

        # Scoped to the LINK rename only. `swap.py` uses the same
        # `os.replace`, so patching it wholesale broke the atomic swap and the
        # disposal never ran -- the test then passed for the wrong reason.
        real_replace = os.replace

        def _fail_only_the_link_rename(src, dst, *a, **k):
            if str(src).endswith('.cp-link-tmp'):
                raise OSError(1, 'nope')
            return real_replace(src, dst, *a, **k)

        monkeypatch.setattr(renamer_main.os, 'replace', _fail_only_the_link_rename)

        _run(world)

        assert open(world['dst'], 'rb').read() == NEW, (
            'the swap itself was broken, so this test proves nothing about '
            'the disposal'
        )
        assert calls['n'] == 1, 'the link was never attempted'
        strays = [
            n for n in os.listdir(os.path.dirname(world['src']))
            if n.endswith('.cp-link-tmp')
        ]
        assert not strays, 'a temporary link survived the failure: %r' % strays
        assert os.path.exists(world['src'])

    def test_the_happy_path_still_produces_a_link_to_the_library(self, world):
        world['state']['conf']['default_file_action'] = 'symlink_reversed'
        _run(world)
        assert os.path.islink(world['src'])
        assert os.path.realpath(world['src']) == os.path.realpath(world['dst'])
