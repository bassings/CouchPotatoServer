"""The EXECUTION layer of FEAT-011: acting on the operator's decision.

`decide_operator_replacement` (`replacement.py`, commit ba1b652a) is a pure
decision -- given the release documents already recorded for a film, it names
the single completed release whose file is the one to replace, or refuses. It
touches no filesystem and no database. This module tests the layer that ACTS
on that decision: the entry point that actually stages a hand-placed file
over the top of a library copy and destroys the old one.

This is the code path that has already destroyed an irreplaceable file twice
in withdrawn attempts (`replacement.py`'s own module docstring). Every safety
property below is non-negotiable, per the task brief, and gets its own test:

  1. AC-SEC-4 -- the destructive step is reachable ONLY through
     `swap.replace_atomically`, with a non-None `expected_source_size` and a
     `destination_identity` from `swap.identity_of`.
  2. AC-SEC-1 -- the path that gets destroyed is NEVER supplied by the
     caller. A request carrying `destination`, `dst`, `to`, `path`,
     `media_folder` or `base_folder` changes nothing.
  3. AC-SEC-2 -- the operator-chosen SOURCE is confined to the configured
     watch folder (`conf('from')`), resolved server-side with
     `os.path.realpath`, refused rather than clamped.
  3b. AC-SEC-3 -- `_destinationIsInsideTheLibrary` is applied against
     `conf('to')` and against no request-supplied folder.
  4. Owner decision 3 -- the operator's source is ALWAYS consumed on a
     verified swap, overriding `default_file_action`, and only after the
     swap verifies.
  5. Owner decision 4 -- a release document is written for the placed file.
  6. Owner decision 2 -- backgrounded, with a second activation REFUSED, not
     queued.

  Ordering -- bookkeeping happens before disposal (`renamer/main.py`'s own
     documented reasoning for the automatic path, reused here): a kill
     between the two must leave the RECOVERABLE half-finished state.

**The contract this file establishes, because none of it exists yet:**

  * `Renamer._executeOperatorReplacement(self, media_id, source_name)` is the
    synchronous worker that does the real destructive work. `source_name` is
    a bare name (or relative path) chosen from a listing already produced
    under `conf('from')` -- never a full path supplied by a caller. It
    returns `(outcome, destination_or_None)`. It holds the SAME re-entrancy
    guard `scan()` already uses (`self.renaming_started` under
    `media_lock('renamer-scan')`), so a scan and an operator replacement, or
    two operator replacements, cannot run concurrently -- reusing the
    existing mechanism rather than adding a second lock.
  * `Renamer.operatorReplaceView(self, **kwargs)` is the API-facing entry
    point. It reads only `media_id` and `source` out of `kwargs` -- every
    other key is ignored -- and runs `_executeOperatorReplacement` on a
    background thread rather than inline, returning promptly. The spawned
    thread is kept at `self._operator_thread` purely so a test can join it
    deterministically; nothing else may depend on that attribute existing.

Driven against a real filesystem throughout, asserting on bytes, exactly as
`test_replacement_end_to_end.py` and `test_replacement_operator_isolation.py`
already do for their layers -- a return value can be right for the wrong
reason, a file on disk cannot.
"""
import hashlib
import os
import threading
import time

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes
from couchpotato.core.plugins.renamer.replacement import (
    DECLINED_OUTSIDE_LIBRARY,
    OPERATOR_REPLACE,
)
from couchpotato.core.plugins.renamer.swap import (
    REFUSED_DESTINATION_IS_SYMLINK,
    REFUSED_SOURCE_IS_SYMLINK,
)

OLD = b'existing 720p copy' * 100
NEW = b'incoming 2160p copy' * 900


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def _tree_shas(root):
    """sha256 of every regular file under `root`, keyed by relative path.

    Used to prove "no filesystem write" over a whole folder rather than one
    named file -- a hostile input that quietly creates a NEW file elsewhere
    under the same tree would pass a single-file hash check and fail this
    one.
    """
    out = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                out[os.path.relpath(full, root)] = ('link', os.readlink(full))
            else:
                out[os.path.relpath(full, root)] = ('file', _sha(full))
    return out


@pytest.fixture
def world(tmp_path, monkeypatch):
    lib = tmp_path / 'library'
    lib.mkdir()
    dst = lib / 'The Thing.mkv'
    dst.write_bytes(OLD)

    watch = tmp_path / 'downloads'
    watch.mkdir()
    src = watch / 'incoming.mkv'
    src.write_bytes(NEW)

    existing_release = {
        '_id': 'r-old',
        'status': 'done',
        'files': {'movie': [str(dst)]},
        'copy_id': copy_id_for_sizes([len(OLD)]),
        'quality': '720p',
        'is_3d': False,
    }

    state = {
        'conf': {
            'from': str(watch),
            'to': str(lib),
            'default_file_action': 'move',
            'cleanup': False,
        },
        'releases': {'media-1': [existing_release]},
        'status_updates': [],
        'detached': [],
        'added': [],
        'calls': [],
    }

    def _fire(event, *args, **kwargs):
        if event == 'release.for_media':
            media_id = args[0] if args else kwargs.get('media_id')
            return list(state['releases'].get(media_id, []))
        if event == 'release.update_status':
            state['calls'].append('bookkeeping:release.update_status')
            state['status_updates'].append((args[0], kwargs.get('status')))
            return True
        if event == 'release.detach_file':
            state['calls'].append('bookkeeping:release.detach_file')
            state['detached'].append((args[0], args[1]))
            return True
        if event == 'release.add':
            group = args[0] if args else kwargs.get('group')
            movie_files = list((group.get('files') or {}).get('movie') or [])
            new_release = {
                '_id': 'r-new-%d' % (len(state['added']) + 1),
                'status': 'done',
                'files': {'movie': movie_files},
                'quality': (group.get('meta_data') or {}).get('quality', {}).get('identifier'),
                'is_3d': (group.get('meta_data') or {}).get('quality', {}).get('is_3d', False),
                'copy_id': copy_id_for_sizes([os.path.getsize(p) for p in movie_files]),
                'identity_source': group.get('identity_source'),
            }
            state['added'].append(new_release)
            media_id = (group.get('media') or {}).get('_id')
            state['releases'].setdefault(media_id, []).append(new_release)
            return True
        if event == 'quality.guess':
            return {'identifier': '2160p', 'is_3d': False}
        return None

    monkeypatch.setattr(
        'couchpotato.core.plugins.renamer.main.fireEvent', _fire,
    )

    plugin = Renamer.__new__(Renamer)
    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: state['conf'].get(key, default),
        raising=False,
    )
    Renamer.renaming_started = False
    Renamer._warned_dead_setting = True

    return {
        'plugin': plugin, 'src': str(src), 'dst': str(dst),
        'lib': lib, 'watch': watch, 'state': state,
        'old_dst_sha': _sha(dst), 'new_src_sha': _sha(src),
    }


class TestTheDestroyedPathIsNeverCallerSupplied:
    """AC-SEC-1. The destination is resolved server-side from the media and
    release records, never from a request parameter. A request naming one of
    the classic "which file do you mean" parameters must not be able to
    redirect the destructive step anywhere -- proven by planting a decoy file
    at exactly the path such a parameter would name, and hashing it after.
    """

    def test_a_decoy_destination_and_every_sibling_parameter_survive_byte_identical(
        self, world,
    ):
        victim = world['watch'].parent / 'victim.mkv'
        victim.write_bytes(b'do not touch me' * 50)
        victim_sha = _sha(victim)

        plugin = world['plugin']
        plugin.operatorReplaceView(
            media_id='media-1', source='incoming.mkv',
            destination=str(victim), dst=str(victim), to=str(victim.parent),
            path=str(victim), media_folder=str(victim.parent),
            base_folder=str(victim.parent),
        )
        plugin._operator_thread.join(timeout=5)
        assert not plugin._operator_thread.is_alive(), 'the view never backgrounded the work'

        assert _sha(victim) == victim_sha, (
            'a decoy path supplied under a destination-shaped parameter name '
            'was written to or deleted'
        )
        # And the legitimate replacement must still have gone ahead -- a
        # blanket refusal on any extra kwarg would also make this test pass
        # for the wrong reason.
        assert _sha(world['dst']) == world['new_src_sha'], (
            'the extra parameters were not merely ignored, they broke the '
            'legitimate replacement too'
        )


class TestTheOperatorSourceIsConfinedToTheWatchFolder:
    """AC-SEC-2. Resolved server-side with `os.path.realpath` and refused,
    never clamped, exactly as `softchroot.chroot2abs` is proven
    (`couchpotato/core/softchroot.py:167-205`). Each hostile source name
    below must be refused before anything is written, and the SAME refusal
    value must come back for all of them -- proving one shared confinement
    check rather than four unrelated code paths that happen to all refuse.
    """

    def _nested_world(self, tmp_path, monkeypatch):
        """A watch folder two levels below `tmp_path`, so the literal
        '../../etc/hosts' from the spec resolves to a real, hashable decoy
        file at `tmp_path/etc/hosts` rather than an untestable guess."""
        root = tmp_path
        lib = root / 'library'
        lib.mkdir()
        dst = lib / 'The Thing.mkv'
        dst.write_bytes(OLD)

        watch = root / 'a' / 'b'
        watch.mkdir(parents=True)
        src = watch / 'incoming.mkv'
        src.write_bytes(NEW)

        decoy_dir = root / 'etc'
        decoy_dir.mkdir()
        decoy = decoy_dir / 'hosts'
        decoy.write_bytes(b'127.0.0.1 localhost\n')

        outside_dir = root / 'outside'
        outside_dir.mkdir()
        outside_file = outside_dir / 'secret.mkv'
        outside_file.write_bytes(b'a file elsewhere on disk' * 20)

        existing_release = {
            '_id': 'r-old', 'status': 'done',
            'files': {'movie': [str(dst)]},
            'copy_id': copy_id_for_sizes([len(OLD)]),
            'quality': '720p', 'is_3d': False,
        }
        state = {
            'conf': {'from': str(watch), 'to': str(lib), 'default_file_action': 'move', 'cleanup': False},
            'releases': {'media-1': [existing_release]},
        }

        def _fire(event, *args, **kwargs):
            if event == 'release.for_media':
                return list(state['releases'].get(args[0] if args else kwargs.get('media_id'), []))
            if event == 'quality.guess':
                return {'identifier': '2160p', 'is_3d': False}
            return None

        monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent', _fire)
        plugin = Renamer.__new__(Renamer)
        monkeypatch.setattr(
            type(plugin), 'conf',
            lambda _self, key, default=None, **kw: state['conf'].get(key, default),
            raising=False,
        )
        Renamer.renaming_started = False
        Renamer._warned_dead_setting = True
        return plugin, root, watch, dst, decoy, outside_file

    def test_a_relative_traversal_out_of_the_watch_folder_is_refused(self, tmp_path, monkeypatch):
        plugin, root, _watch, dst, decoy, _outside = self._nested_world(tmp_path, monkeypatch)
        before = _tree_shas(root)
        outcome, resulting_dst = plugin._executeOperatorReplacement('media-1', '../../etc/hosts')
        assert outcome != OPERATOR_REPLACE
        assert resulting_dst is None
        assert _tree_shas(root) == before, 'a traversal outside the watch folder wrote or deleted something'

    def test_an_absolute_path_elsewhere_on_disk_is_refused(self, tmp_path, monkeypatch):
        plugin, root, _watch, dst, _decoy, outside = self._nested_world(tmp_path, monkeypatch)
        before = _tree_shas(root)
        outcome, resulting_dst = plugin._executeOperatorReplacement('media-1', str(outside))
        assert outcome != OPERATOR_REPLACE
        assert resulting_dst is None
        assert _tree_shas(root) == before, 'an absolute path outside the watch folder wrote or deleted something'

    def test_a_name_containing_a_nul_byte_is_refused_not_raised(self, tmp_path, monkeypatch):
        plugin, root, _watch, dst, _decoy, _outside = self._nested_world(tmp_path, monkeypatch)
        before = _tree_shas(root)
        outcome, resulting_dst = plugin._executeOperatorReplacement('media-1', 'evil\x00.mkv')
        assert outcome != OPERATOR_REPLACE
        assert resulting_dst is None
        assert _tree_shas(root) == before

    def test_a_symlink_whose_target_leaves_the_watch_folder_is_refused(self, tmp_path, monkeypatch):
        plugin, root, watch, dst, _decoy, outside = self._nested_world(tmp_path, monkeypatch)
        link = watch / 'looks_local.mkv'
        os.symlink(str(outside), str(link))
        before = _tree_shas(root)
        outcome, resulting_dst = plugin._executeOperatorReplacement('media-1', 'looks_local.mkv')
        assert outcome != OPERATOR_REPLACE
        assert resulting_dst is None
        assert _tree_shas(root) == before, (
            'a symlink resolving outside the watch folder wrote, deleted, or '
            'altered a link or its target'
        )

    def test_every_hostile_case_produces_the_same_named_refusal(self, tmp_path, monkeypatch):
        """A permissive implementation could refuse each hostile input for a
        DIFFERENT incidental reason (a raised-then-swallowed exception here,
        a generic 'not found' there) and every test above would still pass.
        This pins that they share one outcome value, proving one deliberate
        confinement check rather than four accidents that happen to refuse.
        """
        plugin, root, watch, dst, decoy, outside = self._nested_world(tmp_path, monkeypatch)
        link = watch / 'looks_local.mkv'
        os.symlink(str(outside), str(link))

        outcomes = {
            plugin._executeOperatorReplacement('media-1', '../../etc/hosts')[0],
            plugin._executeOperatorReplacement('media-1', str(outside))[0],
            plugin._executeOperatorReplacement('media-1', 'evil\x00.mkv')[0],
            plugin._executeOperatorReplacement('media-1', 'looks_local.mkv')[0],
        }
        assert len(outcomes) == 1, (
            'the four hostile source names produced different outcomes: %r' % outcomes
        )
        assert outcomes.pop() != OPERATOR_REPLACE


class TestLibraryContainmentIsCheckedAgainstConfToOnly:
    """AC-SEC-3. `_destinationIsInsideTheLibrary` is applied on the operator
    path against `conf('to')`, never against a request-supplied folder --
    proven by a media whose recorded destination has drifted outside the
    library root (a stale or corrupted release document), which must refuse
    rather than destroy whatever sits at that path.
    """

    def test_a_destination_outside_conf_to_is_declined_and_untouched(self, world, tmp_path):
        outside_dir = tmp_path / 'not_the_library'
        outside_dir.mkdir()
        outside_file = outside_dir / 'someone_elses_file.mkv'
        outside_file.write_bytes(b'not part of the configured library' * 30)
        outside_sha = _sha(outside_file)

        world['state']['releases']['media-1'][0]['files']['movie'] = [str(outside_file)]
        world['state']['releases']['media-1'][0]['copy_id'] = copy_id_for_sizes(
            [outside_file.stat().st_size],
        )

        outcome, resulting_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert outcome == DECLINED_OUTSIDE_LIBRARY
        assert resulting_dst is None
        assert _sha(outside_file) == outside_sha
        assert open(world['src'], 'rb').read() == NEW, 'the download must survive a refusal'

    def test_a_request_supplied_folder_cannot_widen_the_containment_boundary(self, world, tmp_path):
        """Even when the caller-facing view is handed a `media_folder` that
        points somewhere legitimate-looking, the containment check must never
        consult it -- only `conf('to')` decides."""
        outside_dir = tmp_path / 'not_the_library'
        outside_dir.mkdir()
        outside_file = outside_dir / 'someone_elses_file.mkv'
        outside_file.write_bytes(b'not part of the configured library' * 30)
        outside_sha = _sha(outside_file)

        world['state']['releases']['media-1'][0]['files']['movie'] = [str(outside_file)]
        world['state']['releases']['media-1'][0]['copy_id'] = copy_id_for_sizes(
            [outside_file.stat().st_size],
        )

        plugin = world['plugin']
        # `media_folder` names the very directory the destination sits in --
        # the most tempting parameter to accidentally trust.
        plugin.operatorReplaceView(
            media_id='media-1', source='incoming.mkv',
            media_folder=str(outside_dir),
        )
        plugin._operator_thread.join(timeout=5)

        assert _sha(outside_file) == outside_sha


class TestTheDestructiveStepOnlyHappensThroughTheAtomicSwap:
    """AC-SEC-4. Reaching the destructive step through anything OTHER than
    `swap.replace_atomically` -- called with a measured, non-None
    `expected_source_size` and a `destination_identity` from
    `swap.identity_of` -- is what let withdrawn attempt #1 overwrite a 2160p
    remux with a 720p file with no size check at all. The two e2e cases
    prove `refused_source_is_symlink` and `refused_destination_is_symlink`
    stay REACHABLE through this new path, using a symlink target that itself
    sits inside the watch/library root, so the earlier confinement checks
    (AC-SEC-2, AC-SEC-3) cannot be the thing that refuses it for an unrelated
    reason.
    """

    def test_replace_atomically_is_called_with_both_safety_kwargs_present(self, world, monkeypatch):
        import couchpotato.core.plugins.renamer.main as renamer_main
        from couchpotato.core.plugins.renamer.swap import replace_atomically as real_replace_atomically

        calls = []

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return real_replace_atomically(*args, **kwargs)

        monkeypatch.setattr(renamer_main, 'replace_atomically', _spy)

        outcome, resulting_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert outcome == OPERATOR_REPLACE
        assert resulting_dst == world['dst']
        assert len(calls) == 1, 'the destructive step must be reached exactly once'
        assert calls[0].get('expected_source_size') is not None, (
            'expected_source_size was not passed, or was passed as None -- '
            'this is the check that refuses a source that changed since it '
            'was measured'
        )
        assert calls[0].get('destination_identity') is not None, (
            'destination_identity was not passed, or was passed as None -- '
            'None means "asked for revalidation but could not establish a '
            'baseline", which swap.py itself treats as a refusal, not a skip'
        )

    def test_a_symlinked_source_is_refused_and_neither_link_nor_target_changes(self, world):
        real_target = world['watch'] / 'the_real_file.mkv'
        real_target.write_bytes(NEW)
        link = world['watch'] / 'incoming_link.mkv'
        os.symlink(str(real_target), str(link))
        target_sha = _sha(real_target)

        outcome, resulting_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming_link.mkv',
        )

        assert outcome == REFUSED_SOURCE_IS_SYMLINK
        assert resulting_dst is None
        assert os.path.islink(link), 'the symlink itself was replaced or removed'
        assert os.readlink(link) == str(real_target), 'the symlink now points somewhere else'
        assert _sha(real_target) == target_sha, "the symlink's target was modified"
        assert _sha(world['dst']) == world['old_dst_sha'], 'the library file was touched by a refused swap'

    def test_a_symlinked_destination_is_refused_and_neither_link_nor_target_changes(self, world):
        real_target = world['lib'] / 'the_real_current_copy.mkv'
        real_target.write_bytes(OLD)
        link = world['lib'] / 'The Thing.mkv'
        os.remove(link)
        os.symlink(str(real_target), str(link))
        target_sha = _sha(real_target)

        world['state']['releases']['media-1'][0]['files']['movie'] = [str(link)]

        outcome, resulting_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert outcome == REFUSED_DESTINATION_IS_SYMLINK
        assert resulting_dst is None
        assert os.path.islink(link), 'the destination symlink itself was replaced or removed'
        assert os.readlink(link) == str(real_target)
        assert _sha(real_target) == target_sha, "the destination symlink's target was modified"
        assert open(world['src'], 'rb').read() == NEW, 'the download must survive a refusal'


class TestTheOperatorsSourceIsAlwaysConsumedOnAVerifiedSwap:
    """Owner decision 3. Overrides `default_file_action` deliberately: on
    `copy` and `link` the automatic path leaves the source in the watch
    folder, and the next scan would find it again -- the repeating refusal
    FEAT-012 exists to end, on exactly the values that cause it. Consumption
    is proven to happen only AFTER the swap verifies: a failed swap must
    leave the source exactly as it was.
    """

    @pytest.mark.parametrize('action', ['move', 'copy', 'link', 'symlink_reversed'])
    def test_the_source_is_gone_from_the_watch_folder_after_a_successful_swap(
        self, world, action,
    ):
        world['state']['conf']['default_file_action'] = action

        outcome, resulting_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert outcome == OPERATOR_REPLACE
        assert _sha(world['dst']) == world['new_src_sha']
        assert not os.path.exists(world['src']), (
            '"%s" left the operator\'s source in the watch folder -- the next '
            'scan would find it again and repeat the refusal FEAT-012 exists '
            'to end' % action
        )

    def test_a_failed_swap_leaves_the_source_completely_untouched(self, world, monkeypatch):
        import couchpotato.core.plugins.renamer.swap as swap_module

        world['state']['conf']['default_file_action'] = 'move'
        monkeypatch.setattr(
            swap_module.shutil, 'copyfileobj',
            lambda a, b, **kw: (_ for _ in ()).throw(OSError('mount gone')),
        )

        outcome, resulting_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert outcome != OPERATOR_REPLACE
        assert resulting_dst is None
        assert os.path.exists(world['src']), (
            'the source was consumed even though the swap never verified'
        )
        assert open(world['src'], 'rb').read() == NEW
        assert _sha(world['dst']) == world['old_dst_sha']


class TestARecordIsWrittenForThePlacedFile:
    """Owner decision 4. Without a release document the media is
    permanently `declined_no_owner`: every later upgrade or replacement
    decision refuses on those grounds. Proven functionally, using the real
    `resolve_owning_release` against whatever the operator path actually
    persisted, rather than asserting on the shape of an internal call.
    """

    def test_a_new_release_document_claims_the_placed_file_at_its_detected_quality(self, world):
        from couchpotato.core.plugins.renamer.owner import (
            OWNER_RESOLVED,
            resolve_owning_release,
        )

        outcome, resulting_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )
        assert outcome == OPERATOR_REPLACE

        releases_now = world['state']['releases']['media-1']
        size_on_disk = os.path.getsize(resulting_dst)
        resolved, owner_outcome = resolve_owning_release(
            resulting_dst, releases_now, size_on_disk,
        )

        assert owner_outcome == OWNER_RESOLVED, (
            'no release document claims the placed file after a successful '
            'operator replacement -- the media is now permanently '
            'declined_no_owner on every later decision'
        )
        assert resolved['quality'] is not None
        assert resolved['quality'] == world['state']['added'][-1]['quality']
        assert resolved is not world['state']['releases']['media-1'][0], (
            'the OLD release must not be the one now claiming the new file'
        )

    def test_the_recorded_quality_is_the_incoming_files_detected_quality_not_the_old_ones(self, world):
        outcome, _resulting_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )
        assert outcome == OPERATOR_REPLACE
        assert len(world['state']['added']) == 1
        new_release = world['state']['added'][0]
        # The fixture's `quality.guess` fake always answers 2160p; the OLD
        # release on this fixture is 720p. A release recorded at the OLD
        # rung would mean the operator's whole reason for acting -- "this
        # copy is better" -- is invisible to every later decision.
        assert new_release['quality'] == '2160p'


class TestASecondActivationIsRefusedNotQueued:
    """Owner decision 2. A per-route lock (`couchpotato/api.py:56`) would
    QUEUE a second call behind the first -- exactly the shape the spec calls
    out as the trap: the operator sees no progress, clicks again, and the
    retry silently waits its turn rather than being told plainly that one is
    already running. This reuses `renaming_started` (AC-ARCH-7's mechanism),
    proven with two REAL threads against a real, deliberately slow staging
    step so the overlap is genuine rather than sequential.
    """

    def test_the_second_call_refuses_promptly_while_the_first_is_still_staging(
        self, world, monkeypatch,
    ):
        import couchpotato.core.plugins.renamer.main as renamer_main
        import couchpotato.core.plugins.renamer.swap as swap_module
        from couchpotato.core.plugins.renamer.swap import replace_atomically as real_replace_atomically

        entered_staging = threading.Event()
        release_staging = threading.Event()
        real_copyfileobj = swap_module.shutil.copyfileobj

        def _blocking_copyfileobj(reader, writer, **kwargs):
            entered_staging.set()
            release_staging.wait(timeout=5)
            return real_copyfileobj(reader, writer, **kwargs)

        monkeypatch.setattr(swap_module.shutil, 'copyfileobj', _blocking_copyfileobj)

        swap_calls = []

        def _spy(*args, **kwargs):
            swap_calls.append(1)
            return real_replace_atomically(*args, **kwargs)

        monkeypatch.setattr(renamer_main, 'replace_atomically', _spy)

        results = {}

        def _first():
            results['first'] = world['plugin']._executeOperatorReplacement(
                'media-1', 'incoming.mkv',
            )

        first_thread = threading.Thread(target=_first)
        first_thread.start()
        assert entered_staging.wait(timeout=5), 'the first call never reached staging'

        started_second_at = time.monotonic()
        second_outcome, second_dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )
        second_call_duration = time.monotonic() - started_second_at

        assert second_outcome != OPERATOR_REPLACE, (
            'a second activation while one was in flight was not refused'
        )
        assert second_dst is None
        assert second_call_duration < 1.0, (
            'the second call took %.2fs -- it BLOCKED (queued) behind the '
            'first rather than refusing promptly' % second_call_duration
        )

        release_staging.set()
        first_thread.join(timeout=5)

        assert results['first'][0] == OPERATOR_REPLACE
        assert len(swap_calls) == 1, (
            'more than one call reached the atomic swap for the same '
            'destination -- the guard did not serialise the two activations'
        )
        assert _sha(world['dst']) == world['new_src_sha']


class TestBookkeepingHappensBeforeDisposal:
    """The ordering `renamer/main.py` already documents for the automatic
    path (announce, revalidate, replace, THEN supersede-the-old-release,
    THEN dispose-of-the-source): a kill between the two best-effort steps
    must leave the RECOVERABLE state. Disposing first leaves the download
    gone and the release still claiming a file that no longer exists, which
    is the unbounded re-download loop D3 exists to prevent. Superseding
    first leaves the release correct and the download merely untidy --
    recoverable by a human.
    """

    def test_the_old_release_is_superseded_before_the_source_is_removed(self, world, monkeypatch):
        real_remove = os.remove
        order = world['state']['calls']

        def _tracking_remove(path, *a, **kw):
            if os.path.abspath(path) == os.path.abspath(world['src']):
                order.append('disposal:remove_source')
            return real_remove(path, *a, **kw)

        monkeypatch.setattr(os, 'remove', _tracking_remove)

        world['state']['conf']['default_file_action'] = 'move'
        outcome, _dst = world['plugin']._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert outcome == OPERATOR_REPLACE
        assert 'disposal:remove_source' in order, 'the source was never removed at all'
        bookkeeping_calls = [c for c in order if c.startswith('bookkeeping:')]
        assert bookkeeping_calls, 'no bookkeeping call (release.update_status / release.detach_file) was made'
        assert order.index(bookkeeping_calls[0]) < order.index('disposal:remove_source'), (
            'the source was disposed of before the superseded release was '
            'accounted for: order was %r' % order
        )
