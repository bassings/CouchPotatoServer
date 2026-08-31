"""C2: the operator replacement's source-size guard must compare against a
size captured when the operator's decision was made, not a fresh stat taken
at execution and compared with itself.

`_runOperatorReplacement` (`renamer/main.py:1272`) currently does:

    expected_source_size = os.path.getsize(source)   # taken NOW
    ...
    replace_atomically(..., expected_source_size=expected_source_size, ...)

and `replace_atomically` (`swap.py:190`) stats the SAME file again a moment
later and compares the two values. Both numbers come from the same stat call
in effect -- microseconds apart, on a source nothing has touched in between
in the ordinary case -- so the comparison can never disagree, whatever the
file has done since the operator actually made their decision.

The automatic path does not have this defect. `_sourceStillMatchesTheScan`
(`renamer/main.py:888`, used at `:514`) compares a fresh measurement against
`meta_data['size']`, a value the SCANNER recorded earlier -- an independent
figure from a different point in time, which is what makes the comparison
capable of failing at all. This file pins the same property for the operator
path: the guard must anchor to a size captured at the operator's decision
point, not to itself.

`_listOperatorCandidates()` is that decision point -- it is the call that
produces the listing the operator picks from, and in the real UI
(`movie_detail.html`) the operator's confirmation is built directly on its
response. Reproduces the review's own executed probe: list candidates, grow
the source afterwards (a stalled NAS copy or paused torrent resuming, the
exact 20.3 GB cross-mount case the spec is written around), then execute.

The existing test at `test_replacement_operator_execution.py`'s
`TestTheDestructiveStepOnlyHappensThroughTheAtomicSwap
.test_replace_atomically_is_called_with_both_safety_kwargs_present` only
asserts `expected_source_size is not None` -- a stand-in true of a plain
`os.path.getsize(source)` call just as much as of a properly captured value,
which is why that test stayed green through the whole withdrawn history of
this defect. This file asserts the actual property: a source that changed
after the decision moment must be refused, not silently replaced.
"""
import hashlib
import os

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes
from couchpotato.core.plugins.renamer.replacement import OPERATOR_REPLACE

OLD = b'existing 720p copy' * 100
NEW = b'incoming 2160p copy' * 900


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Same shape as `test_replacement_operator_execution.py`'s `world`
    fixture -- a real library file, a real watch folder, `fireEvent` faked
    just enough that a genuine replacement can complete end to end, so a
    green outcome here is a green outcome for the wrong reason only if the
    guard truly does not exist.
    """
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
        'added': [],
    }

    def _fire(event, *args, **kwargs):
        if event == 'release.for_media':
            media_id = args[0] if args else kwargs.get('media_id')
            return list(state['releases'].get(media_id, []))
        if event in ('release.update_status', 'release.detach_file'):
            return True
        if event == 'release.add':
            group = args[0] if args else kwargs.get('group')
            movie_files = list((group.get('files') or {}).get('movie') or [])
            new_release = {
                '_id': 'r-new-%d' % (len(state['added']) + 1),
                'status': 'done',
                'files': {'movie': movie_files},
                'copy_id': copy_id_for_sizes(
                    [os.path.getsize(p) for p in movie_files],
                ),
                'identity_source': group.get('identity_source'),
            }
            state['added'].append(new_release)
            media_id = (group.get('media') or {}).get('_id')
            state['releases'].setdefault(media_id, []).append(new_release)
            return True
        if event == 'quality.guess':
            return {'identifier': '2160p', 'is_3d': False}
        if event == 'media.get':
            return {'_id': 'media-1', 'identifier': 'tt-media-1'}
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


class TestTheSourceSizeGuardComparesAgainstTheDecisionTimeSize:
    """AC-DATA-3. A source that keeps growing after the operator's decision
    moment must be refused, not treated as unchanged, because the value it
    is compared against today is taken from the very same file microseconds
    later and can therefore never disagree.
    """

    def test_a_source_that_grows_after_the_candidate_list_is_produced_is_refused(
        self, world,
    ):
        plugin = world['plugin']

        # The operator's decision moment: the candidate listing is
        # produced, and in the real UI this is the response the operator's
        # confirmation is built on. Any guard genuinely anchored to
        # "decision time" must take its reference size no later than here.
        candidates = plugin._listOperatorCandidates()
        assert 'incoming.mkv' in candidates, (
            'fixture broken: the source is not even offered as a candidate'
        )

        # The download continues after that moment -- a resumed stalled
        # copy across the NAS mount the spec is written around, or a
        # paused torrent that resumes. 75000 bytes, matching the review's
        # own probe.
        with open(world['src'], 'ab') as fh:
            fh.write(b'X' * 75000)
        grown_src_sha = _sha(world['src'])

        outcome, destination = plugin._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert outcome != OPERATOR_REPLACE, (
            'the source grew by 75000 bytes after the candidate list was '
            'produced and the replacement went ahead anyway -- the guard '
            'compared a fresh stat against itself instead of the size '
            'captured at the operator\'s decision moment (outcome was %r)'
            % (outcome,)
        )
        assert destination is None, (
            'a refused replacement must not report a destination'
        )
        assert _sha(world['dst']) == world['old_dst_sha'], (
            'the library file was overwritten by a source that changed '
            'after the operator saw the candidate list -- in production '
            'the source is then deleted on a reported REPLACE, so both '
            'copies of the film would now be gone with no undo'
        )
        # The source itself must survive a refusal untouched: the whole
        # point of refusing is that the operator gets to look again.
        assert _sha(world['src']) == grown_src_sha, (
            'the source was modified or removed despite the replacement '
            'being refused'
        )
