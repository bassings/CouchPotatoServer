"""M4 (branch review 2026-08-31): a killed operator replacement leaves a
full-size staged copy in the library folder that nothing ever reports.

`_reportStaleStagingFiles` (`renamer/main.py`) already exists and is already
proven against the automatic path (`_moveRenamedFiles` calls it at the one
site `grep -n _reportStaleStagingFiles` used to find). The operator entry
point, `_runOperatorReplacement`, never calls it at all: a process killed
between `replace_atomically`'s staging step and its `os.replace` on an
OPERATOR-initiated replacement leaves a `.cp-upgrade-*.part` file -- a
complete, undiscoverable copy of whatever the operator was replacing -- and
the next operator replacement for that same film gives no hint it is there.

This test does not need to kill a process mid-swap to prove the gap: the
diagnostic is a plain directory scan for abandoned `.cp-upgrade-*.part`
files, run once before the swap (mirroring the automatic path's own call
site), so a pre-existing stale staging file in the library directory is
enough to show whether the operator path ever looks.
"""
import hashlib
import logging
import os
import time

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
        if event == 'release.update_status':
            return True
        if event == 'release.detach_file':
            return True
        if event == 'release.add':
            group = args[0] if args else kwargs.get('group')
            movie_files = list((group.get('files') or {}).get('movie') or [])
            new_release = {
                '_id': 'r-new-1',
                'status': 'done',
                'files': {'movie': movie_files},
                'quality': (group.get('meta_data') or {}).get('quality', {}).get('identifier'),
                'is_3d': (group.get('meta_data') or {}).get('quality', {}).get('is_3d', False),
                'copy_id': copy_id_for_sizes([os.path.getsize(p) for p in movie_files]),
            }
            state['added'].append(new_release)
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
        'plugin': plugin, 'src': str(src), 'dst': str(dst), 'lib': str(lib),
    }


def _stale_part(directory, age_hours):
    """A `.cp-upgrade-*.part` file old enough to count as abandoned, exactly
    the shape `replace_atomically` leaves behind when a process is killed
    between staging and the atomic swap."""
    name = '.cp-upgrade-deadbeef.part'
    path = os.path.join(directory, name)
    with open(path, 'wb') as handle:
        handle.write(b'a complete download nobody can see' * 100)
    old = time.time() - age_hours * 3600
    os.utime(path, (old, old))
    return name


class TestAPreExistingStaleStagingFileIsReportedOnTheOperatorPath:
    def test_an_abandoned_part_file_is_named_in_the_log_before_an_operator_swap(
        self, world, caplog,
    ):
        from couchpotato.core.logger import reset_log_suppression
        reset_log_suppression()

        stale_name = _stale_part(world['lib'], age_hours=48)

        with caplog.at_level(logging.WARNING):
            outcome, destination = world['plugin']._executeOperatorReplacement(
                'media-1', 'incoming.mkv',
            )

        assert outcome == OPERATOR_REPLACE, (
            'the replacement itself did not succeed -- fixture is broken'
        )
        assert destination == world['dst']
        assert _sha(world['dst']) == hashlib.sha256(NEW).hexdigest()

        messages = [r.getMessage() for r in caplog.records]
        assert any(stale_name in m for m in messages), (
            'an operator replacement ran with a 48-hour-old abandoned '
            '.cp-upgrade-*.part file sitting in the same library directory '
            'and nothing reported it -- _runOperatorReplacement never calls '
            '_reportStaleStagingFiles (M4, branch review 2026-08-31); '
            'log records were: %r' % messages
        )
