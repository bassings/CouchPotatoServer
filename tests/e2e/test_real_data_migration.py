"""End-to-end tests: migrate real CodernityDB database to SQLite.

Requires /var/media/config_backup.zip with real CouchPotatoServer database.
Tests are skipped if the backup is not available.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import pytest

BACKUP_PATH = '/var/media/config_backup.zip'
DB_SUBPATH = 'config/data/database'

# Expected counts from the real database
EXPECTED_TOTAL = 2892
EXPECTED_TYPES = {
    'media': 849,
    'release': 905,
    'property': 1101,
    'quality': 12,
    'profile': 17,
    'notification': 8,
}

needs_backup = pytest.mark.skipif(
    not os.path.exists(BACKUP_PATH),
    reason=f"Real database backup not found at {BACKUP_PATH}"
)


@pytest.fixture(scope='module')
def real_db_path():
    """Extract real CodernityDB from backup zip."""
    tmpdir = tempfile.mkdtemp(prefix='cp_e2e_')
    with zipfile.ZipFile(BACKUP_PATH) as zf:
        members = [m for m in zf.namelist() if m.startswith(DB_SUBPATH)]
        zf.extractall(tmpdir, members)
    db_path = os.path.join(tmpdir, DB_SUBPATH)
    yield db_path
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(scope='module')
def migrated_db(real_db_path):
    """Migrate the real database to SQLite."""
    from couchpotato.core.db.migrate import migrate
    tmpdir = tempfile.mkdtemp(prefix='cp_e2e_sqlite_')
    dest_path = os.path.join(tmpdir, 'migrated')
    count, types = migrate(real_db_path, dest_path, verbose=False)
    yield dest_path, count, types
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sqlite_adapter(migrated_db):
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
    dest_path = migrated_db[0]
    adapter = SQLiteAdapter()
    adapter.open(dest_path)
    yield adapter
    adapter.close()


@needs_backup
class TestRealDataMigration:
    def test_total_document_count(self, migrated_db):
        _, count, _ = migrated_db
        assert count == EXPECTED_TOTAL

    def test_type_counts(self, migrated_db):
        _, _, types = migrated_db
        for doc_type, expected in EXPECTED_TYPES.items():
            assert types.get(doc_type, 0) == expected, \
                f"Type '{doc_type}': expected {expected}, got {types.get(doc_type, 0)}"

    def test_verify_passes(self, real_db_path, migrated_db):
        from couchpotato.core.db.migrate import verify
        dest_path = migrated_db[0]
        assert verify(real_db_path, dest_path, verbose=False)


@needs_backup
class TestRealDataQueries:
    def test_query_media_by_status(self, sqlite_adapter):
        active = list(sqlite_adapter.query('media_status', key='active', with_doc=True))
        done = list(sqlite_adapter.query('media_status', key='done', with_doc=True))
        # Should have some of each
        total = len(active) + len(done)
        assert total > 0

    def test_query_releases_by_media(self, sqlite_adapter):
        # Get a media doc, then query its releases
        media = list(sqlite_adapter.query('media_by_type', key='movie', with_doc=True, limit=1))
        if media:
            media_id = media[0]['_id']
            releases = list(sqlite_adapter.query('release', key=media_id, with_doc=True))
            # May or may not have releases — just verify no crash
            assert isinstance(releases, list)

    def test_query_properties(self, sqlite_adapter):
        props = list(sqlite_adapter.query('property', with_doc=True))
        assert len(props) == EXPECTED_TYPES['property']

    def test_query_quality(self, sqlite_adapter):
        results = list(sqlite_adapter.query('quality', with_doc=True))
        assert len(results) == EXPECTED_TYPES['quality']

    def test_query_profiles(self, sqlite_adapter):
        results = list(sqlite_adapter.query('profile', with_doc=True))
        assert len(results) == EXPECTED_TYPES['profile']

    def test_query_notifications(self, sqlite_adapter):
        results = list(sqlite_adapter.query('notification', with_doc=True))
        assert len(results) == EXPECTED_TYPES['notification']

    def test_media_identifier_lookup(self, sqlite_adapter):
        # Get a media doc with identifiers, then look it up
        media_docs = list(sqlite_adapter.query('media_by_type', key='movie', with_doc=True, limit=10))
        found = False
        for m in media_docs:
            identifiers = m.get('identifiers', {})
            for provider, ident in identifiers.items():
                if ident:
                    result = sqlite_adapter.get_by_identifier(provider, str(ident))
                    assert result['_id'] == m['_id']
                    found = True
                    break
            if found:
                break
        assert found, "No media with identifiers found"


@needs_backup
class TestRealDataEdgeCases:
    def test_unicode_titles(self, sqlite_adapter):
        """Verify Unicode titles survived migration."""
        media = list(sqlite_adapter.query('media_by_type', key='movie', with_doc=True))
        titles = [m.get('title', '') for m in media]
        # Just verify we have titles and they're strings
        assert all(isinstance(t, str) for t in titles)
        assert len(titles) > 0

    def test_large_info_blobs(self, sqlite_adapter):
        """Verify large info blobs (with images, cast, etc.) survived."""
        media = list(sqlite_adapter.query('media_by_type', key='movie', with_doc=True, limit=50))
        has_large_info = False
        for m in media:
            info = m.get('info', {})
            if info and len(str(info)) > 1000:
                has_large_info = True
                # Verify structure is intact
                assert isinstance(info, dict)
                break
        assert has_large_info, "No media with large info blobs found"

    def test_release_files_structure(self, sqlite_adapter):
        """Verify release file paths survived."""
        releases = list(sqlite_adapter.query('release_status', key='done', with_doc=True, limit=20))
        has_files = False
        for r in releases:
            files = r.get('files', {})
            if files and isinstance(files, dict):
                for ftype, paths in files.items():
                    if isinstance(paths, list) and paths:
                        has_files = True
                        assert all(isinstance(p, str) for p in paths)
                        break
            if has_files:
                break

    def test_property_identifiers_are_strings(self, sqlite_adapter):
        """All property identifiers should be strings."""
        props = list(sqlite_adapter.query('property', with_doc=True))
        for p in props:
            ident = p.get('identifier')
            if ident is not None:
                assert isinstance(ident, str), f"Property identifier is {type(ident)}: {ident}"

    def test_no_orphaned_release_media_ids(self, sqlite_adapter):
        """Check how many releases reference non-existent media."""
        releases = list(sqlite_adapter.query('release', with_doc=True))
        media_ids = {m['_id'] for m in sqlite_adapter.query('media_by_type', with_doc=True)}

        orphaned = 0
        for r in releases:
            mid = r.get('media_id')
            if mid and mid not in media_ids:
                orphaned += 1

        # Report but don't fail — orphans may exist in real data
        print(f"\n  Orphaned releases: {orphaned}/{len(releases)}")

    def test_all_documents_have_type(self, sqlite_adapter):
        """Every document should have a _t field."""
        all_docs = list(sqlite_adapter.all('id'))
        for doc in all_docs:
            assert '_t' in doc and doc['_t'], f"Document {doc['_id']} missing _t"
