"""Integration tests for CodernityDB → SQLite migration.

Uses a temporary CodernityDB database populated from sample_data.json,
then migrates to SQLite and verifies.
"""
import hashlib
import json
import os
import sqlite3
import sys

import pytest

# Ensure libs are importable
libs_path = os.path.join(os.path.dirname(__file__), '..', '..', 'libs')
if libs_path not in sys.path:
    sys.path.insert(0, os.path.abspath(libs_path))

from CodernityDB.database import Database

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.db.migrate import read_codernity_docs, clean_doc_for_sqlite, migrate, verify


FIXTURES_PATH = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'sample_data.json')


def digest_tree(root: str) -> dict:
    """Map every file under `root` to the SHA-256 of its contents.

    Used to assert a directory is byte-identical before and after an
    operation. Compares contents rather than mtimes: a rewrite that happens
    to reproduce the same bytes is not damage, and a filesystem's mtime
    granularity is too coarse to trust for a fast test.
    """
    digests = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            with open(full, 'rb') as handle:
                digests[os.path.relpath(full, root)] = hashlib.sha256(handle.read()).hexdigest()
    return digests


@pytest.fixture
def sample_data():
    with open(FIXTURES_PATH) as f:
        return json.load(f)


@pytest.fixture
def codernity_db(tmp_path, sample_data):
    """Create a temporary CodernityDB populated with sample data."""
    db_path = str(tmp_path / "source_db")
    db = Database(db_path)
    db.create()

    # Insert all sample documents
    all_docs = []
    for doc_type in ['media', 'release', 'quality', 'profile', 'notification', 'property']:
        for doc in sample_data.get(doc_type, []):
            inserted = db.insert(doc)
            all_docs.append(inserted)

    db.close()
    return db_path, len(all_docs)


class TestReadCodernitydocs:
    def test_read_all_docs(self, codernity_db):
        db_path, expected_count = codernity_db
        docs = read_codernity_docs(db_path)
        assert len(docs) == expected_count

    def test_docs_have_required_fields(self, codernity_db):
        db_path, _ = codernity_db
        docs = read_codernity_docs(db_path)
        for doc in docs:
            assert '_id' in doc
            assert '_t' in doc or '_rev' in doc  # All docs should have type or at least rev


class TestCleanDocForSqlite:
    def test_removes_rev(self):
        doc = {'_id': 'abc', '_rev': '123', '_t': 'media', 'title': 'Test'}
        cleaned = clean_doc_for_sqlite(doc)
        assert '_rev' not in cleaned
        assert '_id' in cleaned
        assert cleaned['title'] == 'Test'

    def test_removes_key(self):
        doc = {'_id': 'abc', '_t': 'media', 'key': 'indexkey', 'title': 'Test'}
        cleaned = clean_doc_for_sqlite(doc)
        assert 'key' not in cleaned


class TestMigrate:
    def test_full_migration(self, codernity_db, tmp_path):
        source_path, expected_count = codernity_db
        dest_path = str(tmp_path / "dest_db")

        count, types = migrate(source_path, dest_path, verbose=False)
        assert count == expected_count

        # Verify we can read from SQLite
        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        all_docs = list(adapter.all('id'))
        assert len(all_docs) == expected_count
        adapter.close()

    def test_type_counts_correct(self, codernity_db, tmp_path, sample_data):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")

        count, types = migrate(source_path, dest_path, verbose=False)

        for doc_type in ['media', 'release', 'quality', 'profile', 'notification', 'property']:
            expected = len(sample_data.get(doc_type, []))
            assert types.get(doc_type, 0) == expected, f"Type {doc_type}: expected {expected}, got {types.get(doc_type, 0)}"

    def test_media_identifiers_migrated(self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)

        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        # The sample data has imdb identifiers
        # query with_doc=True yields {'doc': {...}, '_id': '...'} (CodernityDB compat)
        media_docs = list(adapter.query('media_status', with_doc=True))
        has_identifiers = any(d.get('doc', d).get('identifiers') for d in media_docs)
        assert has_identifiers
        adapter.close()


class TestVerify:
    def test_verify_passes(self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)
        assert verify(source_path, dest_path, verbose=False)

    def test_verify_fails_with_missing_docs(self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)

        # Delete a document from SQLite
        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        docs = list(adapter.all('id', limit=1))
        adapter.delete({'_id': docs[0]['_id']})
        adapter.close()

        assert not verify(source_path, dest_path, verbose=False)


class TestMigrationDataIntegrity:
    def test_json_fields_preserved(self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)

        adapter = SQLiteAdapter()
        adapter.open(dest_path)

        # Check media info blobs
        media = list(adapter.query('media_by_type', key='movie', with_doc=True))
        for m in media:
            if m.get('info'):
                assert isinstance(m['info'], dict)

        # Check release files
        releases = list(adapter.query('release_status', key='done', with_doc=True))
        for r in releases:
            if r.get('files'):
                assert isinstance(r['files'], dict)

        adapter.close()

    def test_all_doc_types_present(self, codernity_db, tmp_path, sample_data):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)

        adapter = SQLiteAdapter()
        adapter.open(dest_path)

        for doc_type in ['media', 'release', 'quality', 'profile', 'notification', 'property']:
            docs = list(adapter.query(doc_type if doc_type != 'media' else 'media_by_type', with_doc=True))
            expected = len(sample_data.get(doc_type, []))
            assert len(docs) == expected, f"Type {doc_type}: expected {expected}, got {len(docs)}"

        adapter.close()


class TestMigrationIsRepeatable:
    """AC-DATA-23: the migration survives being run a second time.

    An operator whose first run was interrupted -- a full disk, a Ctrl-C, a
    container restart part-way through 849 documents -- will simply run it
    again. Two things must hold for that to be safe, and neither is obvious
    from reading migrate():

    1. The second run must not double the library. That rests entirely on
       insert_bulk using INSERT OR REPLACE; a future change to plain INSERT,
       or a denormalised side table that appends rather than replaces, breaks
       it silently and the operator finds out by scrolling a library with
       every film in it twice.
    2. The CodernityDB source must come back untouched. Until the operator
       trusts the SQLite copy, that directory is their only rollback, and
       migrate() opens it with a library written for Python 2. A read path
       that quietly rewrites index or storage files would be destroying the
       escape hatch at the exact moment it is most likely to be needed.
    """

    def test_running_the_migration_twice_does_not_duplicate_documents(self, codernity_db, tmp_path):
        source_path, expected_count = codernity_db
        dest_path = str(tmp_path / "dest_db")

        first_count, first_types = migrate(source_path, dest_path, verbose=False)
        second_count, second_types = migrate(source_path, dest_path, verbose=False)

        assert first_count == expected_count
        assert second_count == expected_count
        assert second_types == first_types

        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        try:
            ids = [doc['_id'] for doc in adapter.all('id')]
        finally:
            adapter.close()

        assert len(ids) == expected_count, (
            'the second migration run changed the document count from '
            f'{expected_count} to {len(ids)}'
        )
        assert len(set(ids)) == len(ids), 'the second migration run duplicated document ids'
        assert verify(source_path, dest_path, verbose=False)

        # verify() only compares the `documents` table. media_identifiers is
        # the denormalised side table, and duplicated rows there are exactly
        # what produced this project's live "same film added twice" defects --
        # so check it directly rather than inferring it from a passing verify.
        conn = sqlite3.connect(os.path.join(dest_path, 'couchpotato.db'))
        try:
            rows = conn.execute(
                "SELECT media_id, provider, identifier FROM media_identifiers"
            ).fetchall()
        finally:
            conn.close()

        assert rows, 'no identifier rows were written, so this assertion proves nothing'
        assert len(set(rows)) == len(rows), 'the second migration run duplicated media_identifiers rows'

    def test_the_codernitydb_source_is_byte_identical_after_migrating_and_verifying(
            self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")

        before = digest_tree(source_path)
        # Guards the guard: an empty mapping would make the comparison below
        # hold no matter what migrate() did to the source.
        assert before, 'the fixture produced no source files to hash'

        # The whole documented operator flow, not just one call: `migrate
        # --verify` reads the source twice, and the second read is the one a
        # naive "just reopen it" implementation is most likely to dirty.
        migrate(source_path, dest_path, verbose=False)
        migrate(source_path, dest_path, verbose=False)
        verify(source_path, dest_path, verbose=False)

        after = digest_tree(source_path)
        changed = sorted(
            name for name in set(before) | set(after)
            if before.get(name) != after.get(name)
        )
        assert not changed, (
            'migrating mutated the CodernityDB source, which is the operator\'s '
            f'only rollback until they trust the SQLite copy: {changed}'
        )
