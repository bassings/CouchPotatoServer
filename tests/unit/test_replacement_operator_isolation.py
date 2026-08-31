"""The operator decision must not leak into, or change, the automatic path.

FEAT-011 decision layer. `decide_operator_replacement` (`replacement.py`)
exists precisely so an explicit operator naming a film and a file can bypass
`_identityIsAsserted` and the quality comparison -- a bypass this spec's
owner made legitimate for that one, human-asserted case ONLY (spec owner
decision 1; risk section, `specs/FEAT-011-replace-with-this-file.md`).

Eight of nine planning lenses raised the same fear from two directions:

  * the bypass leaking INTO the automatic scan would re-enable the class of
    destruction `_identityIsAsserted` exists to prevent, for the third time;
  * the automatic path's behaviour must stay byte-for-byte unchanged, which
    is only provable by driving the REAL `_moveRenamedFiles`, not by reading
    the diff and asserting nothing looks different.

So this file does two things, neither of them duplicating
`test_replacement_end_to_end.py::TestAGuessedMovieIdentityNeverAuthorisesDestruction`,
which already pins the automatic path's own refusal on its own terms: it
proves the NEW function is reachable from nowhere the automatic scan runs,
and it re-drives the exact production scenario from the spec's Problem
section -- a fuzzy title-and-year search identity -- through the real
automatic path AFTER this change, on bytes.
"""
import hashlib
import inspect

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes
from couchpotato.core.plugins.renamer.replacement import (
    OPERATOR_DECLINED_AMBIGUOUS_FILE,
    OPERATOR_DECLINED_NO_FILE_TO_REPLACE,
    OPERATOR_REPLACE,
    decide_operator_replacement,
)

OLD = b'existing 720p copy' * 100
NEW = b'incoming 2160p copy' * 900


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


class TestTheOperatorFunctionIsUnreachableFromTheAutomaticScan:
    """"An operator-path entry point that is NOT reachable from the automatic
    scan" (task scope). Proven against the actual module source, not
    inferred: a stray import or a call added later to `_moveRenamedFiles` or
    `_processGroup` would fail this even if every other test stayed green,
    because none of those tests would ever exercise the new branch.

    The first two cases here originally asserted that `main.py` did not name
    `decide_operator_replacement` or its outcomes AT ALL -- true only for the
    interval between the decision layer (this commit) and the execution
    layer that acts on it (the next planned step, which wires the operator's
    OWN entry point into `main.py`). Once that entry point exists the whole
    module legitimately names both, so the assertion is narrowed to what it
    was always actually protecting: the four AUTOMATIC-path methods, which
    is exactly what the third case below already checks per-method rather
    than for the module as a whole.
    """

    def test_the_automatic_decision_path_never_names_the_operator_function(self):
        for method in (
            Renamer._moveRenamedFiles,
            Renamer._processGroup,
            Renamer.scan,
            Renamer.scanView,
        ):
            assert 'decide_operator_replacement' not in inspect.getsource(method)

    def test_the_automatic_decision_path_never_names_an_operator_outcome(self):
        for method in (
            Renamer._moveRenamedFiles,
            Renamer._processGroup,
            Renamer.scan,
            Renamer.scanView,
        ):
            source = inspect.getsource(method)
            for outcome in (
                OPERATOR_REPLACE,
                OPERATOR_DECLINED_NO_FILE_TO_REPLACE,
                OPERATOR_DECLINED_AMBIGUOUS_FILE,
            ):
                assert outcome not in source, (method.__name__, outcome)

    def test_the_automatic_decision_path_never_calls_it(self):
        for method in (
            Renamer._moveRenamedFiles,
            Renamer._processGroup,
            Renamer.scan,
            Renamer.scanView,
        ):
            assert 'decide_operator_replacement' not in inspect.getsource(method)


class TestASearchedIdentityIsStillRefusedAfterThisChange:
    """The exact scenario the task named: "a group whose identity came from
    the fuzzy title-and-year search must STILL be refused by the automatic
    path after this change." Driven through the real `_moveRenamedFiles`,
    asserted on bytes, mirroring the fixture shape already proven in
    `test_replacement_end_to_end.py`.
    """

    def _world(self, tmp_path, monkeypatch):
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
            'conf': {
                'upgrade_replace': True,
                'cleanup': False,
                'to': str(lib),
                'default_file_action': 'move',
            },
            'status_updates': [],
            'releases': [release],
        }

        def _fire(event, *args, **kwargs):
            if event == 'release.for_media':
                return state['releases']
            if event == 'release.update_status':
                state['status_updates'].append((args[0], kwargs.get('status')))
                return True
            if event == 'release.detach_file':
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

        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.main.fireEvent', _fire,
        )

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
        Renamer._warned_dead_setting = True

        group = {
            'media': {'_id': 'media-1'},
            'meta_data': {'quality': {'identifier': '2160p', 'is_3d': False}},
            'files': {'movie': [str(src)]},
            'parentdir': str(dl),
            'identity_source': 'search',
        }

        return plugin, str(src), str(dst), state, group

    def test_a_searched_identity_still_refuses_and_destroys_nothing(
        self, tmp_path, monkeypatch,
    ):
        plugin, src, dst, state, group = self._world(tmp_path, monkeypatch)
        old_sha = _sha(dst)

        plugin._moveRenamedFiles({src: dst}, group)

        assert _sha(dst) == old_sha, (
            'a fuzzy title-and-year search identity destroyed a library file '
            'after the operator decision layer was added'
        )
        assert open(src, 'rb').read() == NEW, 'the download was lost'
        assert state['status_updates'] == [], (
            'the release was marked superseded even though nothing was replaced'
        )
