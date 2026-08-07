"""Filesystem paths never reach the log. AGENTS.md / CLAUDE.md security floor.

`traceback.format_exc()` writes every frame's ABSOLUTE source path. On a native
home-server install that discloses the operator's username and directory
layout -- `/home/<name>/...` or `/Users/<name>/...` -- to anyone who can read
the log, which on this project's own risk ranking is a privacy leak from a file
that also gets pasted into bug reports.

The project rule is explicit: "no secrets, credentials or private filesystem
paths in logs (honour PrivacyFilter)". PrivacyFilter had no path handling at
all before this.

The traceback must stay ACTIONABLE: the module path and line number are the
whole point of logging it, so the fix redacts the prefix and keeps the rest.
"""
import logging

from couchpotato.core.logger import PrivacyFilter


def _filtered(msg, *args):
    record = logging.LogRecord('t', logging.ERROR, __file__, 1, msg, args, None)
    PrivacyFilter().filter(record)
    return str(record.msg)


class TestFilesystemPathsAreRedacted:

    def test_a_unix_home_path_is_redacted(self):
        out = _filtered('boom: File "/home/scott/media/couchpotato/core/db.py", line 3')

        assert '/home/scott' not in out, out
        assert 'scott' not in out, out

    def test_a_macos_home_path_is_redacted(self):
        out = _filtered('File "/Users/jane.doe/repos/cp/couchpotato/api.py", line 9')

        assert '/Users/jane.doe' not in out, out

    def test_the_traceback_stays_actionable(self):
        """A filter that ate the whole line removes the reason it was logged."""
        out = _filtered('File "/home/scott/cp/couchpotato/core/db.py", line 42, in write')

        assert 'couchpotato/core/db.py' in out, out
        assert 'line 42' in out, out
        assert 'write' in out, out

    def test_an_ordinary_message_is_untouched(self):
        """The counterweight: this must not mangle normal logging."""
        out = _filtered('Scanned 12 folders, added 3 movies')

        assert out == 'Scanned 12 folders, added 3 movies'
