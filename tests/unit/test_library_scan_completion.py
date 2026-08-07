"""A full library scan must record that it completed.

`Manage.updateLibrary` ends with:

    if not self.shuttingDown():
        db = get_db()
        db.reindex()

    Env.prop(last_update_key, time.time())

`SQLiteAdapter.reindex` is `def reindex(self, index_name: str)` -- it takes a
required argument, and all four call sites pass none:

    couchpotato/core/database.py:218
    couchpotato/core/database.py:316
    couchpotato/core/plugins/manage.py:243
    couchpotato/core/plugins/release/main.py:155

So the call raises `TypeError`, the enclosing `except` catches it, and the
scan logs "Failed updating library" and **never writes the completion
timestamp** -- which means the next scan starts from scratch and repeats the
whole thing, for ever.

The method is a documented no-op on SQLite ("indexes are automatically
maintained"). So the fix is to delete the calls rather than give the parameter
a default: four places ceremonially invoking a function that does nothing is
worse than not calling it, and a default would preserve the ceremony while
hiding that it never did anything.

`db.opened` (`database.py:402`) and `db._delete_id_index` (`:209`) are absent
from the adapter too. Those are NOT touched here -- see the test at the bottom,
which pins the gap rather than papering over it.
"""
import threading
import time
from unittest.mock import patch

import pytest


MOVIES = [
    {'_id': 'terminal', 'status': 'done', 'identifiers': {'imdb': 'tt1'}, 'releases': []},
]


def _run_update_library(tmp_path):
    """Drive updateLibrary and return the Env mock, so the caller can assert
    on what was PERSISTED rather than on the absence of an exception.

    Deliberately does not swallow exceptions: a failure here that left the
    assertions untested is the whole shape this file exists to catch.
    """
    from couchpotato.core.plugins.manage import Manage

    library = tmp_path / 'library'
    library.mkdir()

    def fake_fire(event, *args, **kwargs):
        if event == 'media.list':
            return (len(MOVIES), MOVIES)
        return None

    class FakeDB:
        """`get_db()` still has to return SOMETHING -- `updateLibrary` calls it.

        It no longer needs a `reindex` trap: T3.2 removed the call, so the trap
        could never fire and reading it suggested a defect that is gone. Any
        unexpected database use fails loudly as an AttributeError instead, which
        is the honest version of the same protection.
        """

    plugin = Manage.__new__(Manage)
    plugin._progress_lock = threading.Lock()
    plugin.in_progress = False

    # cleanup=True on purpose, but NOT for the reason first written here.
    #
    # The original comment said `db.reindex()` sits inside the
    # `if self.conf('cleanup') and full` block, so cleanup had to be on for the
    # broken call to be reached. T3.2 deleted that call, so there is no longer
    # any reindex() in updateLibrary for cleanup to reach, and pointing the next
    # reader at an already-fixed defect is exactly the stale-comment shape this
    # branch keeps finding.
    #
    # It stays on because it is the shipped default and therefore the path users
    # are on. What these two assertions actually pin is the completion timestamp
    # at `manage.py`'s `Env.prop(last_update_key, ...)`, which sits OUTSIDE the
    # cleanup block and so runs either way. The regression guard for the
    # reindex-call deletion itself is the source scan in
    # TestAdapterCompatSurface below.
    with patch.object(Manage, 'conf', lambda self, key, **kw: True), \
         patch.object(Manage, 'directories', lambda self: [str(library)]), \
         patch.object(Manage, 'isDisabled', lambda self: False), \
         patch.object(Manage, 'shuttingDown', lambda self: False), \
         patch('couchpotato.core.plugins.manage.fireEvent', side_effect=fake_fire), \
         patch('couchpotato.core.plugins.manage.get_db', return_value=FakeDB()), \
         patch('couchpotato.core.plugins.manage.Env') as env:
        env.prop.return_value = 0
        plugin.updateLibrary(full=True)
        return env


def _completion_writes(env):
    """Env.prop calls that WRITE (two positional args), not read (one)."""
    return [c for c in env.prop.call_args_list if len(c.args) >= 2]


class TestScanRecordsCompletion:

    def test_a_full_scan_writes_its_completion_timestamp(self, tmp_path):
        env = _run_update_library(tmp_path)

        writes = _completion_writes(env)
        assert writes, (
            'the scan never recorded completion. Every run therefore repeats '
            'the entire library scan, and the log says "Failed updating '
            'library" each time.'
        )

    def test_the_recorded_value_is_a_plausible_timestamp(self, tmp_path):
        """Assert on the stored VALUE, not merely that a write happened.

        A write of `None` or `0` would satisfy the test above while leaving the
        next scan to redo everything -- the same outcome by a different route.
        """
        env = _run_update_library(tmp_path)

        stored = _completion_writes(env)[-1].args[1]
        assert isinstance(stored, (int, float)), 'stored %r' % (stored,)
        assert abs(stored - time.time()) < 60, (
            'completion timestamp is %r, not close to now' % (stored,)
        )


class TestAdapterCompatSurface:
    """What the adapter actually provides, pinned so the gaps stay visible."""

    def test_reindex_is_never_called_with_no_argument(self):
        """The signature requires `index_name`; a bare call is a TypeError.

        Checked against the source rather than by driving all four call sites,
        two of which need a live database. If `reindex` ever regains a real
        implementation this test still holds: the point is that the callers and
        the signature must agree.
        """
        from pathlib import Path
        import re

        root = Path(__file__).resolve().parents[2] / 'couchpotato'
        offenders = []
        for path in root.rglob('*.py'):
            for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                # Comments are SKIPPED, not scanned. The comment left at the
                # manage.py call site explains the removal and necessarily
                # quotes `db.reindex()`, so a naive scan flags the note that
                # documents the fix. That is the same false-positive shape this
                # repo has hit twice before -- a guard reporting its own
                # explanation as a violation.
                if line.lstrip().startswith('#'):
                    continue
                if re.search(r'\breindex\(\s*\)', line):
                    offenders.append('%s:%d' % (path.relative_to(root.parent), n))

        assert not offenders, (
            'reindex() called with no argument, but the adapter signature is '
            '`reindex(self, index_name)` -- a guaranteed TypeError: %s' % offenders
        )

    @pytest.mark.parametrize('attr', ['opened', '_delete_id_index'])
    def test_known_missing_adapter_attributes_are_still_missing(self, attr):
        """Pins a KNOWN GAP rather than asserting correctness.

        `database.py:402` reads `db.opened` and `:209` calls
        `db._delete_id_index`; neither exists on `SQLiteAdapter`. They are on
        the fossil v1 migration path, and deleting that path needs its
        reachability confirmed first -- which is not done here.

        This test exists so the gap cannot be forgotten: if someone ADDS these
        to the adapter, it fails and forces the question of whether the
        migration path should have been deleted instead.
        """
        from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

        assert not hasattr(SQLiteAdapter, attr), (
            'SQLiteAdapter now has `%s`. Either the v1 migration path was '
            'revived deliberately -- in which case update this test and say '
            'why -- or it was added to silence a crash that should have been '
            'fixed by deleting the dead path.' % attr
        )
