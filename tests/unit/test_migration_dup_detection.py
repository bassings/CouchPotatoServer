"""Regression test for the CodernityDB->SQLite migration duplicate-detection
branch (REG-004 Item 4).

Once the UNIQUE (provider, identifier) index exists, migrating a legacy DB
that contains duplicate media makes sqlite_db.insert() raise
sqlite3.IntegrityError for the second+ doc sharing an identifier. That is a
DATA-LOSS event on a disaster-recovery path, so it must be counted separately
(as a duplicate, NOT a generic error), the surviving docs must still migrate,
and it must be logged loudly. No real CodernityDB is needed.
"""
import logging
import sqlite3
from unittest.mock import patch

from couchpotato.core.migration import codernity_to_sqlite


class _FakeCodernity:
    def __init__(self, docs):
        self._docs = docs
        self.closed = False

    def exists(self):
        return True

    def open(self):
        pass

    def all(self, index):
        assert index == 'id'
        return iter(self._docs)

    def close(self):
        self.closed = True


class _FakeSqliteDB:
    """sqlite_db double: create() is a no-op; insert() raises IntegrityError
    for any doc whose _id is in ``dup_ids`` (mimicking the UNIQUE index
    rejecting a duplicate identifier), and records the rest."""

    def __init__(self, errors_by_id):
        # _id -> IntegrityError message string to raise on insert.
        self.errors_by_id = dict(errors_by_id)
        self.created = False
        self.inserted = []

    def create(self, path):
        self.created = True

    def insert(self, doc):
        msg = self.errors_by_id.get(doc.get('_id'))
        if msg is not None:
            raise sqlite3.IntegrityError(msg)
        self.inserted.append(doc)
        return {'_id': doc.get('_id'), '_rev': 'r1'}


def test_migration_counts_duplicate_separately_and_warns(tmp_path, caplog):
    docs = [
        {'_id': 'm1', '_t': 'media', 'identifiers': {'imdb': 'tt1111111'}},
        # m2 collides with m1's identifier -> IntegrityError on insert.
        {'_id': 'm2', '_t': 'media', 'identifiers': {'imdb': 'tt1111111'}},
        {'_id': 'm3', '_t': 'media', 'identifiers': {'imdb': 'tt2222222'}},
    ]
    fake_codernity = _FakeCodernity(docs)
    fake_sqlite = _FakeSqliteDB(errors_by_id={
        'm2': 'UNIQUE constraint failed: media_identifiers.provider, media_identifiers.identifier',
    })

    with (
        patch.object(codernity_to_sqlite, 'SuperThreadSafeDatabase',
                     return_value=fake_codernity),
        patch('couchpotato.core.migration.fix_indexes.fix_index_files',
              return_value=0),
        caplog.at_level(logging.WARNING, logger='couchpotato.core.migration.codernity_to_sqlite'),
    ):
        migrated = codernity_to_sqlite.migrate_codernity_to_sqlite(
            str(tmp_path / 'codernity'), str(tmp_path / 'sqlite'), fake_sqlite
        )

    # The duplicate was NOT counted as a migrated doc; the other two survive.
    assert migrated == 2
    assert [d['_id'] for d in fake_sqlite.inserted] == ['m1', 'm3']

    # The duplicate is surfaced loudly (per-doc + summary), naming it a
    # duplicate skip and pointing at database.bak -- NOT swallowed into the
    # generic error bucket.
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any('DROPPED a duplicate-identifier document m2' in w for w in warnings), (
        "expected the per-doc duplicate-skip warning naming m2"
    )
    assert any('duplicate-identifier document(s) were skipped' in w for w in warnings), (
        "expected the migration summary duplicate warning"
    )
    assert any('database.bak' in w for w in warnings), (
        "duplicate warnings must point at the preserved original (database.bak)"
    )
    # It must NOT be logged as a generic 'Failed to migrate' error.
    assert not any('Failed to migrate document m2' in w for w in warnings), (
        "a duplicate must be counted/reported distinctly from a generic error"
    )

    assert fake_codernity.closed, "the source DB must be closed in the finally block"


def test_non_identifier_integrity_error_counted_as_generic_error(tmp_path, caplog):
    """An IntegrityError that is NOT about media_identifiers (e.g. a
    documents._id PRIMARY KEY violation from a duplicate/malformed source _id)
    must be counted as a GENERIC error, not mislabeled as an already-migrated
    duplicate identifier."""
    docs = [
        {'_id': 'm1', '_t': 'media', 'identifiers': {'imdb': 'tt1111111'}},
        # m2 fails on the documents._id PRIMARY KEY, not the identifier index.
        {'_id': 'm2', '_t': 'media', 'identifiers': {'imdb': 'tt2222222'}},
        {'_id': 'm3', '_t': 'media', 'identifiers': {'imdb': 'tt3333333'}},
    ]
    fake_codernity = _FakeCodernity(docs)
    fake_sqlite = _FakeSqliteDB(errors_by_id={
        'm2': 'UNIQUE constraint failed: documents._id',
    })

    with (
        patch.object(codernity_to_sqlite, 'SuperThreadSafeDatabase',
                     return_value=fake_codernity),
        patch('couchpotato.core.migration.fix_indexes.fix_index_files',
              return_value=0),
        caplog.at_level(logging.WARNING, logger='couchpotato.core.migration.codernity_to_sqlite'),
    ):
        migrated = codernity_to_sqlite.migrate_codernity_to_sqlite(
            str(tmp_path / 'codernity'), str(tmp_path / 'sqlite'), fake_sqlite
        )

    assert migrated == 2
    assert [d['_id'] for d in fake_sqlite.inserted] == ['m1', 'm3']

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    # Counted/reported as a GENERIC error...
    assert any('Failed to migrate document m2' in w for w in warnings), (
        "a non-identifier IntegrityError must be reported as a generic error"
    )
    # ...and NOT as a duplicate-identifier skip (neither per-doc nor summary).
    assert not any('DROPPED a duplicate-identifier document' in w for w in warnings), (
        "a _id PRIMARY KEY violation must not be mislabeled as a duplicate identifier"
    )
    assert not any('duplicate-identifier document(s) were skipped' in w for w in warnings), (
        "duplicates must be 0, so no summary duplicate warning should fire"
    )
