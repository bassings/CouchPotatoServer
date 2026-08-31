"""T7d item 1 (HIGH, round two on C2): the decision-time size guard in
`_runOperatorReplacement` (`renamer/main.py` around :1680) FAILS OPEN on a
dictionary lookup miss instead of refusing.

    recorded_size = getattr(self, '_operator_candidate_sizes', None) or {}
    decision_time_size = recorded_size.get(source_name)
    if decision_time_size is not None and decision_time_size != expected_source_size:
        ...refuse...

When `recorded_size.get(source_name)` returns `None` -- no matter WHY --
the `if` is skipped entirely and the guard falls back to the behaviour C2
was raised to kill: a fresh `os.path.getsize(source)` compared against
itself, which can never disagree with whatever the file looks like right
now, however much it grew or shrank since anyone actually looked at it.

`test_replacement_operator_size_capture.py` already pins the one case
where the guard DOES work: the operator went through
`_listOperatorCandidates()` in this same process, immediately before, with
the source spelled exactly as `_listOperatorCandidatesWithReason` spelled
it. This file pins the three lookup-miss shapes the branch review measured
destroying a real file, all of which reach that same fall-through:

  1. No candidate listing was ever produced in this process at all (a
     caller that never went through the picker -- which the code's own
     comment above `recorded_size` describes as an accepted case rather
     than a bug).
  2. The candidate listing WAS produced, but the operator's `source_name`
     is spelled differently from the bare name the listing recorded it
     under (`./incoming.mkv` vs `incoming.mkv`) -- both resolve to the
     identical file via `_resolveOperatorSource`, but the dict lookup is a
     literal string compare, not a resolved-path compare.
  3. The source sits in a subfolder, which every ordinary scene release
     does. `_listOperatorCandidatesWithReason` lists `conf('from')` with a
     single non-recursive `os.listdir`, so a subfolder entry is never
     even offered as a candidate and therefore never recorded -- while
     `_resolveOperatorSource` accepts a relative path into that same
     subfolder by its own docstring, so nothing stops a client from
     submitting one anyway.

Each scenario grows the source AFTER the point a baseline could have been
recorded (or, for scenario 1, simply never records one), then executes the
replacement and asserts it is REFUSED. The fix this file drives is FAIL
CLOSED: "no baseline was requested" and "a baseline was requested and is
missing" are different situations (mirroring `swap.py`'s own
`_IDENTITY_NOT_REQUESTED` sentinel for the destination side), and only the
first may fall back to a single fresh measurement. All three scenarios
below are the second situation.
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


def _build_world(tmp_path, monkeypatch, src_relpath):
    """Same shape as `test_replacement_operator_size_capture.py`'s `world`
    fixture, parameterised on where under the watch folder the source
    lives, so the subfolder scenario can reuse it unchanged.
    """
    lib = tmp_path / 'library'
    lib.mkdir()
    dst = lib / 'The Thing.mkv'
    dst.write_bytes(OLD)

    watch = tmp_path / 'downloads'
    watch.mkdir()
    src = watch / src_relpath
    src.parent.mkdir(parents=True, exist_ok=True)
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


@pytest.fixture
def world(tmp_path, monkeypatch):
    return _build_world(tmp_path, monkeypatch, 'incoming.mkv')


class TestNoRecordedBaselineRefusesRatherThanFallingBackToASelfComparison:
    """Scenario 1. A caller that reaches `_executeOperatorReplacement`
    without this process ever having produced a candidate listing has no
    baseline to compare against -- and today that is treated as "nothing
    to compare, so allow", not as "cannot verify, so refuse". The file
    below is never grown or tampered with; the point is that an ABSENT
    baseline must refuse on its own, because nothing in this process can
    say whether the file matches what the operator actually saw.
    """

    def test_execution_with_no_prior_candidate_listing_is_refused(self, world):
        plugin = world['plugin']
        assert not hasattr(plugin, '_operator_candidate_sizes'), (
            'fixture broken: a baseline already exists, which defeats the '
            'scenario this test drives'
        )

        outcome, destination = plugin._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert outcome != OPERATOR_REPLACE, (
            'a replacement executed with no recorded decision-time baseline '
            'at all was allowed to proceed -- outcome was %r. There is '
            'nothing in this process to say the source still matches what '
            'the operator saw, so this must refuse rather than fall back '
            'to comparing a fresh stat against itself' % (outcome,)
        )
        assert destination is None
        assert _sha(world['dst']) == world['old_dst_sha'], (
            'the library file was replaced with no baseline ever having '
            'been recorded for the source'
        )


class TestARespelledSourceNameMissesTheRecordedBaselineByDictKey:
    """Scenario 2. `_resolveOperatorSource` treats `incoming.mkv` and
    `./incoming.mkv` as the same file (both normalise to the same lexical
    path under the watch folder), but `recorded_size.get(source_name)` is a
    literal string lookup keyed on whatever
    `_listOperatorCandidatesWithReason` happened to spell the name as. A
    caller -- or a client replaying the exact bytes of an earlier request
    with a trivially different spelling -- can submit an equivalent name
    the resolver accepts and the size dictionary has never heard of.
    """

    def test_a_relative_spelling_of_a_listed_source_still_gets_the_guard(
        self, world,
    ):
        plugin = world['plugin']

        candidates = plugin._listOperatorCandidates()
        assert 'incoming.mkv' in candidates, (
            'fixture broken: the source is not even offered as a candidate'
        )

        with open(world['src'], 'ab') as fh:
            fh.write(b'X' * 75000)
        grown_src_sha = _sha(world['src'])

        outcome, destination = plugin._executeOperatorReplacement(
            'media-1', './incoming.mkv',
        )

        assert outcome != OPERATOR_REPLACE, (
            'the source grew by 75000 bytes after the candidate list was '
            'produced, and submitting the SAME file under a different, '
            'equally-valid spelling ("./incoming.mkv" instead of '
            '"incoming.mkv") bypassed the recorded baseline entirely -- '
            'outcome was %r' % (outcome,)
        )
        assert destination is None
        assert _sha(world['dst']) == world['old_dst_sha'], (
            'the library file was overwritten by a source that changed '
            'after listing, because the recorded size was keyed on a '
            'string the request did not repeat exactly'
        )
        assert _sha(world['src']) == grown_src_sha, (
            'the source was modified or removed despite the replacement '
            'being refused'
        )


class TestASubfolderSourceHasNoRecordedBaselineBecauseListingIsNotRecursive:
    """Scenario 3. `_listOperatorCandidatesWithReason` runs a single
    `os.listdir(watch)` with no recursion, so a file inside a subfolder --
    the ordinary shape for a scene release -- is never returned by
    `_listOperatorCandidates()` and therefore never gets an entry in
    `_operator_candidate_sizes`, even though `_resolveOperatorSource`'s own
    docstring says a relative path into a subfolder is an accepted source
    name. The guard is therefore inert for the common case, not an edge
    case.
    """

    @pytest.fixture
    def subfolder_world(self, tmp_path, monkeypatch):
        return _build_world(
            tmp_path, monkeypatch, os.path.join('Release.Folder', 'movie.mkv'),
        )

    def test_a_source_in_a_subfolder_is_never_offered_as_a_candidate(
        self, subfolder_world,
    ):
        plugin = subfolder_world['plugin']

        candidates = plugin._listOperatorCandidates()

        assert os.path.join('Release.Folder', 'movie.mkv') not in candidates, (
            'the candidate listing already recurses into subfolders -- if '
            'this now fails, the fix landed and this probe (and the one '
            'below) should be replaced with the positive case: a subfolder '
            'source IS listed and DOES get a recorded baseline'
        )

    def test_a_source_in_a_subfolder_that_grows_after_being_seen_is_still_replaced(
        self, subfolder_world,
    ):
        plugin = subfolder_world['plugin']
        rel = os.path.join('Release.Folder', 'movie.mkv')

        # The operator (or the picker on their behalf) is shown this file
        # once, by whatever means -- the point under test is only that no
        # baseline ends up recorded for it, which is true regardless of
        # how it was surfaced.
        plugin._listOperatorCandidates()

        with open(subfolder_world['src'], 'ab') as fh:
            fh.write(b'X' * 75000)
        grown_src_sha = _sha(subfolder_world['src'])

        outcome, destination = plugin._executeOperatorReplacement(
            'media-1', rel,
        )

        assert outcome != OPERATOR_REPLACE, (
            'a subfolder source grew by 75000 bytes after being resolvable '
            'and was replaced anyway -- outcome was %r. Real scene '
            'releases land in a subfolder, so this is the ORDINARY case, '
            'not a corner one' % (outcome,)
        )
        assert destination is None
        assert _sha(subfolder_world['dst']) == subfolder_world['old_dst_sha'], (
            'the library file was overwritten by a subfolder source that '
            'changed after being made available, because subfolder '
            'candidates never get a recorded baseline in the first place'
        )
        assert _sha(subfolder_world['src']) == grown_src_sha, (
            'the source was modified or removed despite the replacement '
            'being refused'
        )
