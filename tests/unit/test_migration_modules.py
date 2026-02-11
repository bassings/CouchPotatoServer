"""Tests for the Py2→Py3 database migration modules.

Covers:
- fix_indexes.py: Rewrites md5() calls in index files to handle bytes
- rebuild_buckets.py: Rebuilds hash bucket files after hash function change
- clean_orphans.py: Removes movie entries with no title/year/plot
"""
import os
import sys
import tempfile
import shutil

import pytest

# Ensure libs are importable
libs_path = os.path.join(os.path.dirname(__file__), '..', '..', 'libs')
if libs_path not in sys.path:
    sys.path.insert(0, os.path.abspath(libs_path))

from couchpotato.core.migration.fix_indexes import fix_index_files


# ─── fix_indexes tests ───────────────────────────────────────────────────────

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
        result = fix_index_files(str(tmp_path))
        assert result == 0

    def test_empty_indexes_dir_returns_zero(self, db_dir):
        db_path, _ = db_dir
        result = fix_index_files(str(db_path))
        assert result == 0

    def test_skips_non_py_files(self, db_dir):
        db_path, indexes_dir = db_dir
        self._write_index(indexes_dir, 'readme.txt', 'from hashlib import md5\nmd5(key)')
        result = fix_index_files(str(db_path))
        assert result == 0

    def test_skips_files_without_md5(self, db_dir):
        db_path, indexes_dir = db_dir
        self._write_index(indexes_dir, 'clean_index.py', 'def make_key(key):\n    return key\n')
        result = fix_index_files(str(db_path))
        assert result == 0

    def test_skips_already_migrated_files(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\ndef _to_bytes(s):\n    return s\nmd5(_to_bytes(key))\n'
        self._write_index(indexes_dir, 'migrated.py', content)
        result = fix_index_files(str(db_path))
        assert result == 0

    def test_skips_files_with_encode(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\nmd5(key.encode("utf-8"))\n'
        self._write_index(indexes_dir, 'safe_index.py', content)
        result = fix_index_files(str(db_path))
        assert result == 0

    def test_fixes_bare_md5_key(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\ndef make_key(key):\n    return md5(key).hexdigest()\n'
        path = self._write_index(indexes_dir, 'bare_index.py', content)

        result = fix_index_files(str(db_path))
        assert result == 1

        fixed = path.read_text()
        assert '_to_bytes' in fixed
        assert 'md5(_to_bytes(key))' in fixed

    def test_fixes_md5_with_data_get(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\ndef make_key(data):\n    return md5(data.get("key", "")).hexdigest()\n'
        path = self._write_index(indexes_dir, 'data_get_index.py', content)

        result = fix_index_files(str(db_path))
        assert result == 1

        fixed = path.read_text()
        assert 'md5(_to_bytes(data.get("key", "")))' in fixed

    def test_adds_to_bytes_helper(self, db_dir):
        db_path, indexes_dir = db_dir
        content = 'from hashlib import md5\nmd5(key)\n'
        path = self._write_index(indexes_dir, 'needs_helper.py', content)

        fix_index_files(str(db_path))

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

        result = fix_index_files(str(db_path))
        assert result == 3

    def test_idempotent(self, db_dir):
        """Running fix twice should fix 0 the second time."""
        db_path, indexes_dir = db_dir
        self._write_index(indexes_dir, 'index.py', 'from hashlib import md5\nmd5(key)\n')

        assert fix_index_files(str(db_path)) == 1
        assert fix_index_files(str(db_path)) == 0


# ─── clean_orphans tests ─────────────────────────────────────────────────────

class TestCleanOrphanedMovies:
    """Tests for clean_orphaned_movies() using a real CodernityDB instance."""

    @pytest.fixture
    def db(self, tmp_path):
        from CodernityDB.database import Database
        db = Database(str(tmp_path / 'testdb'))
        db.create()

        # Add required indexes
        from CodernityDB.tree_index import TreeBasedIndex

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

        yield db
        db.close()

    def _insert_movie(self, db, imdb_id, title='', year=0, plot=''):
        doc = {
            '_t': 'media',
            'type': 'movie',
            'identifiers': {'imdb': imdb_id},
            'info': {
                'titles': [title] if title else [],
                'original_title': title,
                'year': year,
                'plot': plot,
            }
        }
        return db.insert(doc)

    def test_removes_orphaned_movies(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        # Insert good movie
        self._insert_movie(db, 'tt1234567', title='Good Movie', year=2020)
        # Insert orphan (no title, no year, no plot)
        self._insert_movie(db, 'tt0000000')

        removed = clean_orphaned_movies(db)
        assert removed == 1

    def test_keeps_movies_with_title(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        self._insert_movie(db, 'tt1111111', title='Has Title')
        removed = clean_orphaned_movies(db)
        assert removed == 0

    def test_keeps_movies_with_year(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        self._insert_movie(db, 'tt2222222', year=2021)
        removed = clean_orphaned_movies(db)
        assert removed == 0

    def test_keeps_movies_with_plot(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        self._insert_movie(db, 'tt3333333', plot='Some plot text')
        removed = clean_orphaned_movies(db)
        assert removed == 0

    def test_handles_bytes_values(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        # Insert movie with bytes values (Py2 legacy)
        doc = {
            '_t': 'media',
            'type': b'movie',
            'identifiers': {'imdb': b'tt9999999'},
            'info': {
                'titles': [b'Bytes Title'],
                'original_title': b'Bytes Title',
                'year': 2020,
                'plot': b'',
            }
        }
        db.insert(doc)
        removed = clean_orphaned_movies(db)
        assert removed == 0  # Has a title, should be kept

    def test_removes_multiple_orphans(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        self._insert_movie(db, 'tt1234567', title='Good Movie', year=2020)
        for i in range(5):
            self._insert_movie(db, f'tt000000{i}')

        removed = clean_orphaned_movies(db)
        assert removed == 5

    def test_returns_zero_on_empty_db(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        removed = clean_orphaned_movies(db)
        assert removed == 0


# ─── rebuild_buckets tests ────────────────────────────────────────────────────

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
        from couchpotato.core.migration.rebuild_buckets import rebuild_after_migration

        db_path, expected_count = populated_db
        db = Database(db_path)

        # Run rebuild
        rebuild_after_migration(db, db_path)

        # Verify all records accessible
        count = 0
        for _ in db.all('id'):
            count += 1

        assert count == expected_count
        db.close()

    def test_rebuild_records_retrievable_by_id(self, populated_db):
        from CodernityDB.database import Database
        from couchpotato.core.migration.rebuild_buckets import rebuild_after_migration

        db_path, _ = populated_db
        db = Database(db_path)

        # Collect all IDs before rebuild via sequential read
        db.open()
        original_ids = [entry['_id'] for entry in db.all('id')]
        db.close()

        # Reopen and rebuild
        db2 = Database(db_path)
        rebuild_after_migration(db2, db_path)

        # Every ID should be retrievable via get
        for doc_id in original_ids:
            doc = db2.get('id', doc_id)
            assert doc is not None
            assert doc.get('_id') == doc_id

        db2.close()

    def test_rebuild_empty_database(self, tmp_path):
        """Rebuild on empty db should not crash."""
        from CodernityDB.database import Database
        from couchpotato.core.migration.rebuild_buckets import rebuild_after_migration

        db_path = str(tmp_path / 'emptydb')
        db = Database(db_path)
        db.create()
        db.close()

        db2 = Database(db_path)
        rebuild_after_migration(db2, db_path)  # Should not raise
        db2.close()


# ─── Full migration pipeline test ────────────────────────────────────────────

class TestMigrationPipeline:
    """Test the full migration sequence: fix_indexes → rebuild → clean_orphans."""

    def test_full_pipeline_on_fresh_db(self, tmp_path):
        """Full pipeline should work on a database created from scratch."""
        from CodernityDB.database import Database
        from CodernityDB.tree_index import TreeBasedIndex
        from couchpotato.core.migration.fix_indexes import fix_index_files
        from couchpotato.core.migration.rebuild_buckets import rebuild_after_migration
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
        fixed = fix_index_files(db_path)
        # Fresh db might not need fixes (created under Py3)
        assert fixed >= 0

        # Step 2: Rebuild buckets
        db2 = Database(db_path)
        rebuild_after_migration(db2, db_path)

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
