"""M6 (branch review 2026-08-31): the operator replacement's replay guard is
incidental, not the identity-at-decision-time check FEAT-011 AC-DATA-4 names.

`_runOperatorReplacement` computes `destination_identity=identity_of(destination)`
in the same breath it hands it to `replace_atomically` (`renamer/main.py`,
just before the call inside `_runOperatorReplacement`), so within a single
call the value can never disagree with itself -- it is a comparison against
itself, the same shape C2 already fixed for the source-size guard. Across TWO
calls the same weakness shows up differently: nothing remembers that a
destination has ALREADY been replaced once, so a stale retry -- a network
resend, a doubled click that lands after the first request has already
finished, or a retry issued because the operator never saw a response (H1) --
walks straight back through the whole flow and performs a SECOND destructive
swap against a file that has already been replaced.

The production path this pins: a verified swap completes, bookkeeping runs
(the superseded release is taken off `done` and a new release is added
claiming the same destination), and then `_disposeOfOperatorSource` fails to
remove the operator's source (a read-only or momentarily-busy watch folder --
tolerated, with only a WARNING, by design). The source is still sitting
there. Nothing about the FIRST call's decision was recorded anywhere a
SECOND call could see it, so the second call re-decides from scratch, finds
the newly-added release as the (now single) completed release, and replaces
it again.

The fixture below deliberately mutates release documents the way the real
`SQLiteAdapter`-backed handlers do (status flips to `ignored`, the detached
path is actually removed from `files['movie']`) rather than only logging the
calls -- a fixture that stops at "the call happened" cannot see this defect,
because the very shape of the bug depends on what `release.for_media` returns
on the SECOND call, which depends on those documents having actually
changed.
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
        'replace_atomically_calls': 0,
    }

    def _fire(event, *args, **kwargs):
        if event == 'release.for_media':
            media_id = args[0] if args else kwargs.get('media_id')
            # A fresh list each call, exactly like a real query -- but the
            # release DOCUMENTS inside it are the same mutable objects the
            # handlers below edit, matching how a real adapter's documents
            # are read back changed after a real write.
            return list(state['releases'].get(media_id, []))

        if event == 'release.update_status':
            release_id = args[0]
            status = kwargs.get('status')
            for release in state['releases'].get('media-1', []):
                if release['_id'] == release_id:
                    release['status'] = status
            return True

        if event == 'release.detach_file':
            release_id, path = args[0], args[1]
            for release in state['releases'].get('media-1', []):
                if release['_id'] == release_id:
                    movie = release.setdefault('files', {}).setdefault('movie', [])
                    if path in movie:
                        movie.remove(path)
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

    # Simulates the disposal failure named in the docstring above: a
    # read-only or momentarily-busy watch folder means the operator's
    # source is never actually removed, so it is still there for a second
    # call to find.
    real_remove = os.remove

    def _remove_that_cannot_touch_the_source(path, *args, **kwargs):
        if os.path.abspath(path) == os.path.abspath(str(src)):
            raise OSError(30, 'Read-only file system')
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(
        'couchpotato.core.plugins.renamer.main.os.remove',
        _remove_that_cannot_touch_the_source,
    )

    return {
        'plugin': plugin, 'src': str(src), 'dst': str(dst),
        'state': state,
    }


class TestAReplayAfterDisposalFailsIsRefusedNotRepeated:
    """AC-DATA-4. A stale retry against a destination that has ALREADY been
    replaced must be refused, not silently re-executed as a second
    destructive swap.
    """

    def test_a_second_call_after_the_first_completes_does_not_swap_again(
        self, world, monkeypatch,
    ):
        import couchpotato.core.plugins.renamer.main as renamer_main
        from couchpotato.core.plugins.renamer.swap import (
            replace_atomically as real_replace_atomically,
        )

        swap_calls = []

        def _spy(*args, **kwargs):
            swap_calls.append(1)
            return real_replace_atomically(*args, **kwargs)

        monkeypatch.setattr(renamer_main, 'replace_atomically', _spy)

        plugin = world['plugin']

        first_outcome, first_destination = plugin._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )
        assert first_outcome == OPERATOR_REPLACE, (
            'the first replacement did not even succeed -- fixture is broken'
        )
        assert first_destination == world['dst']
        assert _sha(world['dst']) == hashlib.sha256(NEW).hexdigest(), (
            'the first swap did not actually install the incoming file'
        )
        # Disposal was made to fail on purpose (see the `world` fixture) --
        # confirm the source really is still there, which is the precondition
        # for the replay this test drives.
        assert os.path.exists(world['src']), (
            'the operator source was removed despite the disposal failure '
            'being forced -- fixture is broken'
        )

        destination_identity_after_first = os.stat(world['dst'])
        first_identity_tuple = (
            destination_identity_after_first.st_dev,
            destination_identity_after_first.st_ino,
            destination_identity_after_first.st_size,
            destination_identity_after_first.st_mtime_ns,
        )

        second_outcome, second_destination = plugin._executeOperatorReplacement(
            'media-1', 'incoming.mkv',
        )

        assert second_outcome != OPERATOR_REPLACE, (
            'a replay against an already-replaced destination performed a '
            'SECOND destructive swap instead of being refused -- the replay '
            'guard is comparing a fresh stat against itself rather than '
            'against the identity captured when the first replacement was '
            'decided (M6, branch review 2026-08-31)'
        )
        assert second_destination is None

        destination_identity_after_second = os.stat(world['dst'])
        second_identity_tuple = (
            destination_identity_after_second.st_dev,
            destination_identity_after_second.st_ino,
            destination_identity_after_second.st_size,
            destination_identity_after_second.st_mtime_ns,
        )
        assert second_identity_tuple == first_identity_tuple, (
            'the library file was rewritten a second time -- its identity '
            'changed between the first and second calls'
        )

        assert len(swap_calls) == 1, (
            'replace_atomically was invoked %d times for two calls against '
            'the same destination -- the second call reached the atomic '
            'swap instead of being refused before it' % len(swap_calls)
        )
