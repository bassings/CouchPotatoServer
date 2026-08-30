"""M16 (branch review 2026-08-31): the operator's source file is deleted from
the watch folder with no log record on the success path.

`_disposeOfOperatorSource` (`renamer/main.py`) only logs when `os.remove`
FAILS -- the `except OSError` branch. On a successful, ordinary removal (the
common case) nothing at all is recorded naming that this feature removed a
file the operator placed by hand from their download folder, and it does so
unconditionally, overriding `default_file_action`, even for an operator whose
configuration says copy.

Driven directly against `_disposeOfOperatorSource` rather than the whole
operator entry point: the defect is scoped entirely to this one method, and a
unit test on it is the tightest possible pin -- a full end-to-end drive would
only add unrelated fixture surface without narrowing what is asserted.
"""
import logging
import os

from couchpotato.core.plugins.renamer.main import Renamer


class TestASuccessfulSourceRemovalIsLoggedNotSilent:
    def test_removing_the_operator_source_on_success_leaves_a_log_record(
        self, tmp_path, caplog,
    ):
        plugin = Renamer.__new__(Renamer)

        source = tmp_path / 'incoming.mkv'
        source.write_bytes(b'a placed download')

        with caplog.at_level(logging.INFO):
            plugin._disposeOfOperatorSource(str(source), media_id='media-1')

        assert not os.path.exists(str(source)), (
            'setup: the source was not actually removed -- fixture is broken'
        )

        messages = [r.getMessage() for r in caplog.records]
        assert messages, (
            'the operator-placed source was removed from the watch folder '
            'and nothing at all was logged about it -- the only log call in '
            '_disposeOfOperatorSource is inside its except OSError branch, '
            'so a successful removal is completely silent (M16, branch '
            'review 2026-08-31)'
        )
        assert any('media-1' in m for m in messages), (
            'a record was emitted but it does not name the media the '
            'source belonged to: %r' % messages
        )
