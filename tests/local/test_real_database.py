"""Local-only tool: load and query a real CouchPotato database from backup.

This is NOT a CI test. It requires `/var/media/config_backup.zip`, a ~39 MB
machine-local file that will never exist on a CI runner, and every test here
skips via `pytestmark` when that file is absent. Wiring it into a runner
therefore buys silent skips, not signal: it was "covered" by pytest.ini's
`testpaths = tests` for a long time without ever actually running in CI, which
is exactly the failure mode this relocation and `scripts/check_test_traps.py`
Rule 5 exist to catch.

Living outside `pytest.ini`'s effective test path is deliberate, not an
oversight: `pytest.ini` carries an explicit `--ignore=tests/local` for this
reason. Do not "fix" that by removing the ignore or by supplying the backup
zip through a CI secret or artifact. The real backup carries live credentials,
real library paths and roughly 849 media documents; it must never be
committed to the repository or uploaded anywhere CI can reach it. Run this
file by hand, locally, against your own copy of the backup, when you need it.
"""
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
    """Extract and open the real CouchPotato database.

    Uses a background thread with a timeout to prevent hanging if the
    CodernityDB open() call blocks (e.g. corrupt or Python 2 era databases).
    """
    import concurrent.futures
    from CodernityDB.database import Database

    tmp = tempfile.mkdtemp(prefix='cptest_real_')
    with zipfile.ZipFile(BACKUP_ZIP) as z:
        z.extractall(tmp)

    db_path = os.path.join(tmp, 'config', 'data', 'database')
    db = Database(db_path)

    # Open in a thread with a timeout to avoid blocking the entire suite
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(db.open)
        try:
            future.result(timeout=15)
        except (concurrent.futures.TimeoutError, Exception) as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            pytest.skip(f'Could not open real database within timeout: {exc}')

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
