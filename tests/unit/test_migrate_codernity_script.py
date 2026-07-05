"""Tests for scripts/migrate_codernity_to_sqlite.py (REFACTOR-01).

The one-time CodernityDB->SQLite migration used to live inside
couchpotato/core/migration/ and run inline in couchpotato/runner.py on every
startup check. REFACTOR-01 moved the migration LOGIC (fix_index_files,
rebuild_after_migration, migrate_codernity_to_sqlite) out of the live
application tree into this standalone, directly-runnable script; runner.py
now only detects a legacy database and hands off to it as a subprocess (see
tests/unit/test_runner_migration.py for that side of the wiring).

Covers:
- fix_index_files(): rewrites md5() calls in index files to handle bytes
- rebuild_after_migration(): rebuilds hash bucket files after hash function change
- migrate_codernity_to_sqlite(): the migration itself, including the REG-004
  duplicate-identifier vs. generic-error attribution
- main() / the CLI: argument handling, database.bak rename on success,
  leaving everything untouched on failure

clean_orphaned_movies() is NOT part of this move -- it runs on every startup
(not just during CodernityDB migration) and stays in
couchpotato/core/migration/clean_orphans.py; see
tests/unit/test_clean_orphans.py. It only appears here in the full-pipeline
test, which exercises it alongside the two modules that did move.
"""
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate_codernity_to_sqlite.py"

# Ensure libs (CodernityDB) and scripts/ are importable, mirroring how the
# script bootstraps its own sys.path when run standalone.
sys.path.insert(0, str(REPO_ROOT / "libs"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import migrate_codernity_to_sqlite  # noqa: E402


# ─── fix_index_files tests ───────────────────────────────────────────────────

class TestFixIndexFiles:
    """Tests for fix_index_files() which patches md5() calls in .py index files."""

    @pytest.fixture
    def db_dir(self, tmp_path):
        indexes_dir = tmp_path / '_indexes'
        indexes_dir.mkdir()
        return tmp_path, indexes_dir

    def _write_index(self, indexes_dir, name, content):
        path = indexes_dir / name
        path.write_text(content)
        return path

    def test_no_indexes_dir_returns_zero(self, tmp_path):
        result = migrate_codernity_to_sqlite.fix_index_files(str(tmp_path))
        assert result == 0

    def test_empty_indexes_dir_returns_zero(self, db_dir):
        db_path, _ = db_dir
        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 0

    def test_skips_non_py_files(self, db_dir):
        db_path, indexes_dir = db_dir
        self._write_index(indexes_dir, 'readme.txt', 'from hashlib import md5\nmd5(key)')
        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 0

    def test_skips_files_without_md5(self, db_dir):
        db_path, indexes_dir = db_dir
        self._write_index(indexes_dir, 'clean_index.py', 'def make_key(key):\n    return key\n')
        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 0

    def test_skips_already_migrated_files(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\ndef _to_bytes(s):\n    return s\nmd5(_to_bytes(key))\n'
        self._write_index(indexes_dir, 'migrated.py', content)
        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 0

    def test_skips_files_with_encode(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\nmd5(key.encode("utf-8"))\n'
        self._write_index(indexes_dir, 'safe_index.py', content)
        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 0

    def test_fixes_bare_md5_key(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\ndef make_key(key):\n    return md5(key).hexdigest()\n'
        path = self._write_index(indexes_dir, 'bare_index.py', content)

        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 1

        fixed = path.read_text()
        assert '_to_bytes' in fixed
        assert 'md5(_to_bytes(key))' in fixed

    def test_fixes_md5_with_data_get(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\ndef make_key(data):\n    return md5(data.get("key", "")).hexdigest()\n'
        path = self._write_index(indexes_dir, 'data_get_index.py', content)

        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 1

        fixed = path.read_text()
        assert 'md5(_to_bytes(data.get("key", "")))' in fixed

    def test_adds_to_bytes_helper(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\nmd5(key)\n'
        path = self._write_index(indexes_dir, 'needs_helper.py', content)

        migrate_codernity_to_sqlite.fix_index_files(str(db_path))

        fixed = path.read_text()
        assert 'def _to_bytes(s):' in fixed
        assert "s.encode('utf-8')" in fixed

    def test_fixes_multiple_files(self, db_dir):
        db_path, indexes_dir = db_dir
        for i in range(3):
            self._write_index(
                indexes_dir, f'index_{i}.py',
                'from hashlib import md5\nmd5(key)\n'
            )

        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 3

    def test_idempotent(self, db_dir):
        """Running fix twice should fix 0 the second time."""
        db_path, indexes_dir = db_dir
        self._write_index(indexes_dir, 'index.py', 'from hashlib import md5\nmd5(key)\n')

        assert migrate_codernity_to_sqlite.fix_index_files(str(db_path)) == 1
        assert migrate_codernity_to_sqlite.fix_index_files(str(db_path)) == 0

    def test_handles_permission_error(self, db_dir):
        """Should handle a directory with unreadable/odd files gracefully."""
        db_path, indexes_dir = db_dir
        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result >= 0

    def test_handles_complex_md5_expression(self, db_dir):
        """Should fix complex expressions inside md5()."""
        db_path, indexes_dir = db_dir
        content = '''from hashlib import md5
def make_key(data):
    return md5(data.get("field", "") + "_suffix").hexdigest()
'''
        path = indexes_dir / 'complex.py'
        path.write_text(content)

        result = migrate_codernity_to_sqlite.fix_index_files(str(db_path))
        assert result == 1

        fixed = path.read_text()
        assert '_to_bytes' in fixed


# ─── rebuild_after_migration tests ───────────────────────────────────────────

class TestRebuildBuckets:
    """Tests for rebuild_after_migration() using a real CodernityDB instance.

    These test that after inserting records and rebuilding, all records
    remain accessible via both the id index and secondary indexes.
    """

    @pytest.fixture
    def populated_db(self, tmp_path):
        """Create a database with some records, close it, return path."""
        from CodernityDB.database import Database

        db_path = str(tmp_path / 'rebuilddb')
        db = Database(db_path)
        db.create()

        # Insert test documents
        docs = []
        for i in range(20):
            doc = db.insert({
                '_t': 'media',
                'type': 'movie',
                'title': f'Movie {i}',
                'status': 'done' if i % 2 == 0 else 'active',
            })
            docs.append(doc)

        db.close()
        return db_path, len(docs)

    def test_rebuild_preserves_all_records(self, populated_db):
        from CodernityDB.database import Database

        db_path, expected_count = populated_db
        db = Database(db_path)

        migrate_codernity_to_sqlite.rebuild_after_migration(db, db_path)

        count = 0
        for _ in db.all('id'):
            count += 1

        assert count == expected_count
        db.close()

    def test_rebuild_records_retrievable_by_id(self, populated_db):
        from CodernityDB.database import Database

        db_path, _ = populated_db
        db = Database(db_path)

        db.open()
        original_ids = [entry['_id'] for entry in db.all('id')]
        db.close()

        db2 = Database(db_path)
        migrate_codernity_to_sqlite.rebuild_after_migration(db2, db_path)

        for doc_id in original_ids:
            doc = db2.get('id', doc_id)
            assert doc is not None
            assert doc.get('_id') == doc_id

        db2.close()

    def test_rebuild_empty_database(self, tmp_path):
        """Rebuild on empty db should not crash."""
        from CodernityDB.database import Database

        db_path = str(tmp_path / 'emptydb')
        db = Database(db_path)
        db.create()
        db.close()

        db2 = Database(db_path)
        migrate_codernity_to_sqlite.rebuild_after_migration(db2, db_path)  # Should not raise
        db2.close()

    def test_handles_corrupt_entry(self, tmp_path):
        """Rebuild should skip corrupt entries gracefully."""
        from CodernityDB.database import Database

        db_path = str(tmp_path / 'db')
        db = Database(db_path)
        db.create()

        for i in range(5):
            db.insert({'index': i})

        db.close()

        db2 = Database(db_path)
        migrate_codernity_to_sqlite.rebuild_after_migration(db2, db_path)

        count = sum(1 for _ in db2.all('id'))
        assert count == 5
        db2.close()


# ─── migrate_codernity_to_sqlite dup-detection tests (REG-004 Item 4) ────────

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
        patch.object(migrate_codernity_to_sqlite, 'SuperThreadSafeDatabase',
                     return_value=fake_codernity),
        patch.object(migrate_codernity_to_sqlite, 'fix_index_files',
                     return_value=0),
        caplog.at_level(logging.WARNING, logger='migrate_codernity_to_sqlite'),
    ):
        migrated = migrate_codernity_to_sqlite.migrate_codernity_to_sqlite(
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
        patch.object(migrate_codernity_to_sqlite, 'SuperThreadSafeDatabase',
                     return_value=fake_codernity),
        patch.object(migrate_codernity_to_sqlite, 'fix_index_files',
                     return_value=0),
        caplog.at_level(logging.WARNING, logger='migrate_codernity_to_sqlite'),
    ):
        migrated = migrate_codernity_to_sqlite.migrate_codernity_to_sqlite(
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


# ─── Full migration pipeline test (cross-module, includes clean_orphans) ─────

class TestMigrationPipeline:
    """Test the full migration sequence: fix_indexes -> rebuild -> clean_orphans.

    clean_orphaned_movies() itself did NOT move (it runs on every startup,
    not just during CodernityDB migration -- see clean_orphans.py docstring
    and tests/unit/test_clean_orphans.py), but the pipeline it was originally
    designed to follow still spans both the moved and the stayed-put modules.
    """

    def test_full_pipeline_on_fresh_db(self, tmp_path):
        from CodernityDB.database import Database
        from CodernityDB.tree_index import TreeBasedIndex
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        db_path = str(tmp_path / 'pipelinedb')
        db = Database(db_path)
        db.create()

        # Add media_by_type index
        class MediaByTypeIndex(TreeBasedIndex):
            custom_header = 'from CodernityDB.tree_index import TreeBasedIndex'

            def __init__(self, *args, **kwargs):
                kwargs['key_format'] = '16s'
                kwargs['node_capacity'] = 100
                super().__init__(*args, **kwargs)

            def make_key_value(self, data):
                t = data.get('_t')
                if t and t in ('media',):
                    key = data.get('type', b'')
                    if isinstance(key, str):
                        key = key.encode('utf-8')
                    return key[:16].ljust(16, b'\x00'), None
                return None

            def make_key(self, key):
                if isinstance(key, str):
                    key = key.encode('utf-8')
                return key[:16].ljust(16, b'\x00')

        db.add_index(MediaByTypeIndex(db.path, 'media_by_type'))

        # Insert good movies
        for i in range(10):
            db.insert({
                '_t': 'media',
                'type': 'movie',
                'identifiers': {'imdb': f'tt{i:07d}'},
                'info': {
                    'titles': [f'Movie {i}'],
                    'original_title': f'Movie {i}',
                    'year': 2020 + i,
                    'plot': f'Plot for movie {i}',
                },
            })

        # Insert orphans
        for i in range(3):
            db.insert({
                '_t': 'media',
                'type': 'movie',
                'identifiers': {'imdb': f'tt999999{i}'},
                'info': {
                    'titles': [],
                    'original_title': '',
                    'year': 0,
                    'plot': '',
                },
            })

        db.close()

        # Step 1: Fix indexes
        fixed = migrate_codernity_to_sqlite.fix_index_files(db_path)
        # Fresh db might not need fixes (created under Py3)
        assert fixed >= 0

        # Step 2: Rebuild buckets
        db2 = Database(db_path)
        migrate_codernity_to_sqlite.rebuild_after_migration(db2, db_path)

        # Step 3: Clean orphans
        removed = clean_orphaned_movies(db2)
        assert removed == 3

        # Verify: 10 good movies remain
        remaining = 0
        for record in db2.all('id'):
            doc = db2.get('id', record['_id'])
            if doc.get('_t') == 'media':
                remaining += 1

        assert remaining == 10

        db2.close()


# ─── CLI smoke tests ──────────────────────────────────────────────────────────

class TestCLISmoke:
    def test_help_runs_and_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), '--help'],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert '--data-dir' in result.stdout

    def test_missing_required_data_dir_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_module_imports_cleanly_and_exposes_expected_api(self):
        assert callable(migrate_codernity_to_sqlite.migrate_codernity_to_sqlite)
        assert callable(migrate_codernity_to_sqlite.fix_index_files)
        assert callable(migrate_codernity_to_sqlite.rebuild_after_migration)
        assert callable(migrate_codernity_to_sqlite.main)


# ─── main() / CLI behavior tests ──────────────────────────────────────────────

class TestMainCLI:
    def test_missing_codernity_dir_returns_nonzero(self, tmp_path):
        rc = migrate_codernity_to_sqlite.main(['--data-dir', str(tmp_path)])
        assert rc == 1

    def test_existing_backup_dir_refuses_to_run_migration(self, tmp_path):
        (tmp_path / 'database').mkdir()
        (tmp_path / 'database.bak').mkdir()

        with patch.object(migrate_codernity_to_sqlite, 'migrate_codernity_to_sqlite') as mock_migrate:
            rc = migrate_codernity_to_sqlite.main(['--data-dir', str(tmp_path)])

        assert rc == 1
        mock_migrate.assert_not_called()

    def test_successful_migration_renames_database_to_bak_and_exits_zero(self, tmp_path):
        (tmp_path / 'database').mkdir()

        with patch.object(migrate_codernity_to_sqlite, 'migrate_codernity_to_sqlite',
                           return_value=5) as mock_migrate:
            rc = migrate_codernity_to_sqlite.main(['--data-dir', str(tmp_path)])

        assert rc == 0
        mock_migrate.assert_called_once()
        assert not (tmp_path / 'database').exists()
        assert (tmp_path / 'database.bak').is_dir()

    def test_failed_migration_returns_nonzero_and_leaves_original_untouched(self, tmp_path):
        (tmp_path / 'database').mkdir()

        def _boom(*args, **kwargs):
            raise RuntimeError('simulated migration failure')

        with patch.object(migrate_codernity_to_sqlite, 'migrate_codernity_to_sqlite', side_effect=_boom):
            rc = migrate_codernity_to_sqlite.main(['--data-dir', str(tmp_path)])

        assert rc == 1
        # No rename on failure -- the original CodernityDB must be untouched.
        assert (tmp_path / 'database').is_dir()
        assert not (tmp_path / 'database.bak').exists()

    def test_codernity_path_and_sqlite_path_overrides_are_honored(self, tmp_path):
        codernity_dir = tmp_path / 'custom_codernity'
        codernity_dir.mkdir()
        sqlite_dir = tmp_path / 'custom_sqlite'

        with patch.object(migrate_codernity_to_sqlite, 'migrate_codernity_to_sqlite',
                           return_value=0) as mock_migrate:
            rc = migrate_codernity_to_sqlite.main([
                '--data-dir', str(tmp_path),
                '--codernity-path', str(codernity_dir),
                '--sqlite-path', str(sqlite_dir),
            ])

        assert rc == 0
        called_codernity_path, called_sqlite_path, _sqlite_db = mock_migrate.call_args[0]
        assert called_codernity_path == str(codernity_dir)
        assert called_sqlite_path == str(sqlite_dir)
        assert not codernity_dir.exists()
        assert (tmp_path / 'database.bak').is_dir()
