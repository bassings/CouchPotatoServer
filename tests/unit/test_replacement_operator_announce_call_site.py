"""T7d item 4 (HIGH, round two on M17): `_announceImminentReplacement`'s
`operator_initiated` flag is proven only at the function itself.

`test_replacement_announce_marks_operator.py` calls
`_announceImminentReplacement` directly and passes `operator_initiated=True`
(or `False`) itself -- which proves the RENDERER honours the flag correctly,
and nothing more. Nothing in the suite drives the REAL call site inside
`_runOperatorReplacement` (`renamer/main.py`, the `about_to_replace=lambda:
self._announceImminentReplacement(..., operator_initiated=True)` passed to
`replace_atomically`) and checks what it actually passes there. Mutating
that one call site's literal `True` to `False` leaves the entire Python unit
suite green (3763 passed) -- the one forensic record written before an
irreversible deletion would silently stop being able to say a human asked
for it, and nothing would notice.

This file drives the real operator path end to end (same fixture shape as
`test_replacement_operator_size_capture.py`: a real library file, a real
watch folder, `fireEvent` faked just enough for a genuine replacement to
complete) and asserts on the RENDERED warning text produced by that real
call, which is the only place a wrong `operator_initiated` value at the
actual call site can be observed.
"""
import hashlib
import logging
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
    """Same shape as `test_replacement_operator_size_capture.py`'s `world`
    fixture."""
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

    # T7e: produce the candidate listing the operator would have seen
    # before they could choose anything, which is what records the
    # decision-time size baseline the source-size guard now requires
    # outright (round three on C2 -- a missing baseline refuses instead of
    # falling back to comparing a fresh stat against itself). Without this
    # the fixture drives a state no real operator submission can reach: in
    # production `operatorReplaceView` always records one itself before
    # handing off to this same worker.
    plugin._listOperatorCandidatesWithReason()
    assert getattr(plugin, '_operator_candidate_sizes', None), (
        'fixture broken: the candidate listing recorded no decision-time '
        'baseline, so the replacement below would be refused for a reason '
        'this file is not testing'
    )

    return {
        'plugin': plugin, 'src': str(src), 'dst': str(dst),
        'lib': lib, 'watch': watch, 'state': state,
    }


class TestTheRealOperatorCallSiteMarksItsOwnAnnouncementAsOperatorInitiated:
    def test_a_real_operator_replacement_logs_operator_requested_not_automatic(
        self, world, caplog,
    ):
        plugin = world['plugin']

        with caplog.at_level(logging.WARNING):
            outcome, destination = plugin._executeOperatorReplacement(
                'media-1', 'incoming.mkv',
            )

        assert outcome == OPERATOR_REPLACE, (
            'fixture broken: the replacement itself did not succeed, so no '
            'announcement was produced to check at all (outcome was %r)'
            % (outcome,)
        )
        assert destination == world['dst']

        announcements = [
            r.getMessage() for r in caplog.records
            if 'About to replace a library copy' in r.getMessage()
        ]
        assert announcements, (
            'the pre-destruction announcement never fired at all for a '
            'real operator-initiated replacement -- this is the ONE '
            'forensic record that can explain a destroyed library file, '
            'and it is missing entirely'
        )

        assert any('OPERATOR-requested' in m for m in announcements), (
            'the real operator call site in _runOperatorReplacement did '
            'not mark its own announcement as operator-initiated -- got: '
            '%r. If a library file is later found destroyed, the log '
            'cannot say whether a human asked for it or the automatic '
            'upgrade path decided on its own, which is exactly the gap '
            'M17 exists to close (branch review 2026-08-31)' % announcements
        )
        assert not any('an automatic replacement' in m for m in announcements), (
            'a real, human-driven operator replacement was announced as '
            '"an automatic replacement" -- got: %r' % announcements
        )
