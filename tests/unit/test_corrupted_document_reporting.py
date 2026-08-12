"""T22: `Database.deleteCorrupted` cannot delete anything on the SQLite
adapter -- `db.get(..., with_storage=False)` and `db._delete_id_index(...)`
are CodernityDB survivors this adapter never implemented, so the handler has
been a silent no-op (DEBUG-only, inside a blanket `except Exception:`) for
the entire life of the SQLite adapter.

Decision (2026-08-12, recorded in specs/REMEDIATION-2026-08.md T22): report,
don't delete. The trigger is a JSON decode failure on a stored document, and
the raw row is still there, in principle repairable by hand. Implementing
the delete against the real adapter API would make the automatic recovery
work for the first time -- but it would also turn "a movie/release/setting
sits there unreadable and noisy" into "permanently gone", which moves the
loss UP CLAUDE.md's data-risk ranking (irreplaceable) for a mechanism
nothing has needed working: the no-op has been in production for the whole
SQLite era with no report of the missing auto-delete.

So `deleteCorrupted`/`database.delete_corrupted` are renamed to
`reportCorrupted`/`database.corrupted_document`, which must:

  1. NEVER delete the document -- proven here against a REAL SQLiteAdapter,
     not a fake that could not tell a no-op apart from a real deletion (the
     defect this task exists to fix was exactly that: nothing here noticed
     for years).
  2. Log at ERROR, naming the document id, saying plainly it was NOT deleted.
  3. Bound the log via `log_suppressed`, keyed PER document id -- this fires
     from read paths (`Settings.getProperty`, release/media listing), so an
     unbounded log would flood the ring buffer on every request that
     touches the one corrupt row.
  4. Never leak a filesystem path or credential into the message.
"""
import inspect
import logging
import pathlib
import re

import pytest

from couchpotato.core.database import Database
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.logger import PrivacyFilter, reset_log_suppression


@pytest.fixture(autouse=True)
def _clear_suppression_state():
    """`log_suppressed`'s state is process-wide (logger.py), so a key used
    by one test leaks into the next without this."""
    reset_log_suppression()
    yield
    reset_log_suppression()


@pytest.fixture
def db(tmp_path):
    adapter = SQLiteAdapter()
    adapter.create(str(tmp_path / 'corrupted'))
    yield adapter
    adapter.close()


@pytest.fixture
def database(db):
    # __new__, not Database(): __init__ registers API views and events
    # against the real global registries, which nothing here needs and
    # which would leak handlers across tests the way test_replacement_wiring
    # documents for `addEvent`. `getDB()` returns `self.db` unchanged when
    # it is already set, so setting it directly bypasses the module-level
    # `get_db` import without needing to patch it.
    obj = Database.__new__(Database)
    obj.db = db
    return obj


def _error_records(caplog):
    return [r for r in caplog.records
            if r.levelno == logging.ERROR and r.name == 'couchpotato.core.database']


class TestTheDocumentIsNeverDeleted:
    """The whole point of T22. The old handler PRETENDED to delete and
    silently failed to (a TypeError and an AttributeError, both swallowed at
    DEBUG). The new one must not delete ON PURPOSE either -- proven against a
    real adapter, because a fake cannot distinguish "did not delete because
    it is broken" from "did not delete because it is designed not to"."""

    def test_the_document_is_still_present_after_reportCorrupted_runs(self, database, db):
        inserted = db.insert({'_t': 'movie', 'title': 'Corrupt Me'})
        doc_id = inserted['_id']

        database.reportCorrupted(doc_id, traceback_error='ValueError: bad json')

        # db.get('id', ...) raises KeyError if the row is gone -- so simply
        # not raising here IS the assertion that the row survived.
        still_there = db.get('id', doc_id)
        assert still_there['_id'] == doc_id

    def test_no_adapter_delete_is_ever_invoked(self, database, db, monkeypatch):
        """Belt and braces: assert `delete` is never called, not only that
        the row survives -- a delete-then-reinsert bug would pass the test
        above but still be destructive (a fresh `_rev`, lost update history).

        The document MUST actually exist first: a mutant that tries
        `db.get(id)` then `db.delete(...)` only for a real row would pass
        this test vacuously against a missing id, because `get` raises
        before `delete` is ever reached (confirmed while mutation-testing
        this guard -- the id-only version of this test stayed green under
        exactly that mutant)."""
        inserted = db.insert({'_t': 'movie', 'title': 'Corrupt Me Too'})
        called = []
        monkeypatch.setattr(db, 'delete', lambda *a, **k: called.append((a, k)))

        database.reportCorrupted(inserted['_id'], traceback_error='boom')

        assert called == [], 'reportCorrupted must never call db.delete'


class TestItLogsAtErrorNamingTheDocument:

    def test_emits_exactly_one_error_record(self, database, caplog):
        with caplog.at_level(logging.ERROR):
            database.reportCorrupted('doc-123', traceback_error='ValueError: bad json')

        assert len(_error_records(caplog)) == 1

    def test_the_message_names_the_document_id(self, database, caplog):
        with caplog.at_level(logging.ERROR):
            database.reportCorrupted('doc-123', traceback_error='ValueError: bad json')

        message = _error_records(caplog)[0].getMessage()
        assert 'doc-123' in message

    def test_the_message_says_plainly_it_was_not_deleted(self, database, caplog):
        with caplog.at_level(logging.ERROR):
            database.reportCorrupted('doc-123', traceback_error='ValueError: bad json')

        message = _error_records(caplog)[0].getMessage().lower()
        assert 'not' in message and 'delet' in message, (
            'the message must say plainly the document was NOT deleted: %r' % message
        )

    def test_the_traceback_error_is_included(self, database, caplog):
        with caplog.at_level(logging.ERROR):
            database.reportCorrupted(
                'doc-123', traceback_error='ValueError: distinctive marker 9f3a2c')

        message = _error_records(caplog)[0].getMessage()
        assert 'distinctive marker 9f3a2c' in message

    def test_it_does_not_log_at_debug_instead(self, database, caplog):
        """The old handler's whole failure was DEBUG-only visibility --
        pin ERROR-or-louder explicitly, not just "some record happened"."""
        with caplog.at_level(logging.DEBUG):
            database.reportCorrupted('doc-123', traceback_error='boom')

        levels = {r.levelno for r in caplog.records
                  if r.name == 'couchpotato.core.database'}
        assert logging.ERROR in levels


class TestSuppression:
    """`log_suppressed`'s contract: first occurrence in full, one "further
    messages withheld" notice, then silence until the window passes."""

    def test_repeats_for_the_same_id_are_suppressed(self, database, caplog):
        with caplog.at_level(logging.ERROR):
            for _ in range(5):
                database.reportCorrupted('doc-123', traceback_error='boom')

        records = _error_records(caplog)
        assert len(records) == 2, (
            'expected the first occurrence plus one withheld-notice, got %d: %r'
            % (len(records), [r.getMessage() for r in records])
        )

    def test_two_different_ids_do_not_suppress_each_other(self, database, caplog):
        with caplog.at_level(logging.ERROR):
            database.reportCorrupted('doc-AAA', traceback_error='boom')
            database.reportCorrupted('doc-BBB', traceback_error='boom')

        records = _error_records(caplog)
        assert len(records) == 2
        messages = [r.getMessage() for r in records]
        assert any('doc-AAA' in m for m in messages), messages
        assert any('doc-BBB' in m for m in messages), messages


class TestNoPrivateDataLeaks:
    """`PrivacyFilter` is attached to the real production handlers
    (`setup_logging`, logger.py), not to caplog's -- so a message that
    reaches caplog unredacted is not itself a leak. What WOULD be a leak is
    the args reaching `log_suppressed` pre-interpolated, which bypasses
    `PrivacyFilter`'s `record.msg % record.args` redaction pass entirely
    (`logger.py`'s own docstring names this as the reason `args` are
    forwarded, not formatted, at the call site).
    """

    def test_args_are_not_pre_interpolated_into_msg(self, database, caplog):
        with caplog.at_level(logging.ERROR):
            database.reportCorrupted('doc-123', traceback_error='marker')

        record = _error_records(caplog)[0]
        assert record.args, (
            'the message was pre-interpolated before reaching the logger -- '
            'PrivacyFilter redacts via record.args, so a private value '
            'formatted in early bypasses it entirely'
        )

    def test_a_home_directory_path_in_the_traceback_is_redacted_by_PrivacyFilter(
            self, database, caplog):
        """End-to-end check with the real filter, not merely asserting
        `record.args` is truthy: a home path embedded in the caller-supplied
        `traceback_error` must not survive in the logged message once
        `PrivacyFilter` runs on it, which is the actual leak the brief
        requires closed."""
        leaky = ('OSError: [Errno 2] No such file or directory: '
                 '/Users/scott/secret/library/movie.mkv')
        with caplog.at_level(logging.ERROR):
            database.reportCorrupted('doc-123', traceback_error=leaky)

        record = _error_records(caplog)[0]
        PrivacyFilter().filter(record)

        assert '/Users/scott' not in record.getMessage()
        assert '<home>' in record.getMessage()


class TestTheNameNoLongerLies:
    """`deleteCorrupted`/`database.delete_corrupted` promised deletion they
    never performed -- a wrong name with a correct docstring is a trap for
    the next reader. Renamed so the name matches what the code does."""

    def test_the_old_method_name_is_gone(self):
        assert not hasattr(Database, 'deleteCorrupted')

    def test_the_new_method_name_exists(self):
        assert hasattr(Database, 'reportCorrupted')

    def test_the_event_is_registered_under_the_new_name(self):
        source = inspect.getsource(Database.__init__)
        assert "'database.corrupted_document'" in source, (
            "Database.__init__ must addEvent('database.corrupted_document', "
            "self.reportCorrupted)"
        )
        assert 'delete_corrupted' not in source
        assert 'deleteCorrupted' not in source

    #: Matches actual USAGE of the old names -- a registration, a fire, a
    #: call, a definition -- not prose that mentions them while explaining
    #: the rename (this codebase documents renames by naming the old
    #: identifier, e.g. `couchpotato/__init__.py`'s `_write_session_secret`
    #: docstring, and rewriting every such mention would make the history
    #: harder to find by grep, not safer). The trap this guards against is a
    #: LIVE call site still wired to the dead event or method, not the old
    #: name appearing anywhere at all.
    _FUNCTIONAL_OLD_NAME_PATTERNS = [
        re.compile(r"""(addEvent|fireEvent)\(\s*['"]database\.delete_corrupted['"]"""),
        re.compile(r'\bdef\s+deleteCorrupted\b'),
        re.compile(r'\.deleteCorrupted\('),
    ]

    def test_no_remaining_functional_references_to_the_old_names(self):
        """Structural guard for the four call sites (settings.py,
        release/main.py x2, media/_base/media/main.py) plus anywhere else in
        the shipped application. Scoped to `couchpotato/`, not `tests/` or
        `specs/`."""
        root = pathlib.Path(__file__).resolve().parents[2] / 'couchpotato'
        hits = []
        for path in root.rglob('*.py'):
            text = path.read_text(encoding='utf-8', errors='ignore')
            for pattern in self._FUNCTIONAL_OLD_NAME_PATTERNS:
                if pattern.search(text):
                    hits.append('%s (%s)' % (path, pattern.pattern))
        assert hits == [], (
            'a live call site is still wired to the renamed event/method: %r' % hits
        )
