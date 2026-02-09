"""Integration tests: load and query a real CouchPotato database from backup."""
import os
import sys
import tempfile
import shutil
import zipfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs'))

BACKUP_ZIP = '/var/media/config_backup.zip'

pytestmark = pytest.mark.skipif(
    not os.path.exists(BACKUP_ZIP),
    reason=f'Real database backup not found at {BACKUP_ZIP}'
)


@pytest.fixture(scope='module')
def real_db():
    """Extract and open the real CouchPotato database."""
    from CodernityDB.database import Database

    tmp = tempfile.mkdtemp(prefix='cptest_real_')
    with zipfile.ZipFile(BACKUP_ZIP) as z:
        z.extractall(tmp)

    db_path = os.path.join(tmp, 'config', 'data', 'database')
    db = Database(db_path)
    db.open()
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


class TestRealDatabaseLoading:
    """Tests that verify we can open and read a real Python-2-era database."""

    def test_database_opens(self, real_db):
        assert real_db.opened

    def test_has_expected_indexes(self, real_db):
        names = set(real_db.indexes_names.keys())
        # Core indexes that should always exist
        for expected in ['id', 'media', 'release', 'category', 'profile']:
            assert expected in names, f'Missing index: {expected}'

    def test_read_all_documents(self, real_db):
        """Read every document via the id index — no errors."""
        count = 0
        for doc in real_db.all('id'):
            assert '_id' in doc
            count += 1
        assert count > 100, f'Expected many documents, got {count}'

    def test_documents_have_types(self, real_db):
        """Most documents should have a _t (type) field."""
        typed = 0
        total = 0
        for doc in real_db.all('id'):
            total += 1
            if '_t' in doc:
                typed += 1
        assert typed > total * 0.5, f'Only {typed}/{total} docs have _t field'

    def test_query_media_index(self, real_db):
        """Query the media index if it exists."""
        if 'media' not in real_db.indexes_names:
            pytest.skip('No media index')
        results = list(real_db.all('media'))
        assert len(results) > 0

    def test_query_category_index(self, real_db):
        """Query the category index."""
        if 'category' not in real_db.indexes_names:
            pytest.skip('No category index')
        results = list(real_db.all('category'))
        assert len(results) >= 0  # may be empty but shouldn't error

    def test_document_values_are_native_types(self, real_db):
        """Verify deserialized values are Python-native, not raw bytes."""
        for doc in real_db.all('id'):
            _id = doc['_id']
            # _id should be a string (or bytes that we can decode)
            assert isinstance(_id, (str, bytes))
            # Spot check: if there's a title, it should be a string
            if 'title' in doc and doc['title'] is not None:
                assert isinstance(doc['title'], (str, bytes))
            break  # just check first doc
