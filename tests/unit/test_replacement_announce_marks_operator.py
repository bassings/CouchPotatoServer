"""M17 (branch review 2026-08-31): the one WARNING preceding an irreversible
file destruction cannot tell an operator-initiated replacement from an
automatic one.

`_announceImminentReplacement` (`renamer/main.py`) is, by its own docstring,
"the only thing that can explain the deletion afterwards": it fires in the
last moment before `os.replace` destroys the old library file, from BOTH the
automatic upgrade path and the operator's manual "replace with this file"
path, with no parameter distinguishing the two. When a library file is found
destroyed, the log cannot say whether a human asked for it or the upgrade
logic decided it on its own -- the first question anyone diagnosing it asks.

AC-FIX (M17): an `operator_initiated` flag, defaulting to automatic, that
puts a distinct token into the rendered WARNING only when a human asked for
the destruction.
"""
import logging

from couchpotato.core.plugins.renamer.main import Renamer


def _group():
    return {
        'media': {'_id': 'media-1'},
        'meta_data': {'quality': {'identifier': '1080p', 'is_3d': False}},
    }


def _superseded():
    return {'_id': 'r-old', 'quality': '720p'}


class TestTheAnnouncementNamesWhetherAnOperatorRequestedIt:
    def test_an_operator_initiated_replacement_is_marked_in_the_warning(
        self, caplog, tmp_path,
    ):
        plugin = Renamer.__new__(Renamer)

        with caplog.at_level(logging.WARNING):
            plugin._announceImminentReplacement(
                str(tmp_path / 'incoming.mkv'),
                str(tmp_path / 'The Thing.mkv'),
                _superseded(), _group(),
                operator_initiated=True,
            )

        messages = [r.getMessage() for r in caplog.records]
        assert any('operator' in m.lower() for m in messages), (
            'an operator-initiated replacement produced a WARNING '
            'indistinguishable from the automatic path -- '
            '_announceImminentReplacement has no operator_initiated '
            'parameter, so the one record that can explain a destroyed '
            'library file afterwards cannot say whether a human asked for '
            'it (M17, branch review 2026-08-31); messages were: %r'
            % messages
        )

    def test_an_automatic_replacement_is_not_marked_as_operator_initiated(
        self, caplog, tmp_path,
    ):
        plugin = Renamer.__new__(Renamer)

        with caplog.at_level(logging.WARNING):
            plugin._announceImminentReplacement(
                str(tmp_path / 'incoming.mkv'),
                str(tmp_path / 'The Thing.mkv'),
                _superseded(), _group(),
                operator_initiated=False,
            )

        messages = [r.getMessage() for r in caplog.records]
        assert messages, 'the automatic-path announcement never fired at all'
        assert not any('operator' in m.lower() for m in messages), (
            'the automatic path was marked as operator-initiated -- the '
            'marker must be exclusive to the operator path or it tells an '
            'operator nothing (messages were: %r)' % messages
        )
