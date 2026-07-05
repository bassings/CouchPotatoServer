"""Tests for clean_orphans.py: removes movie entries with no title/year/plot.

Runs on every startup (not just during CodernityDB migration -- unlike
fix_indexes/rebuild_buckets/codernity_to_sqlite, which moved to the
standalone scripts/migrate_codernity_to_sqlite.py in REFACTOR-01; see
tests/unit/test_migrate_codernity_script.py), so it stays in
couchpotato/core/migration/.
"""
import os
import sys

import pytest

# Ensure libs are importable
libs_path = os.path.join(os.path.dirname(__file__), '..', '..', 'libs')
if libs_path not in sys.path:
    sys.path.insert(0, os.path.abspath(libs_path))


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

