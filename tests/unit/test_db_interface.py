"""Tests for the database abstraction layer."""
import os
import sys
import tempfile
import shutil
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from couchpotato.core.db.interface import DatabaseInterface
from couchpotato.core.db.codernity_adapter import CodernityDBAdapter


@pytest.fixture
def tmp_db_path():
    path = tempfile.mkdtemp(prefix='cdb_adapter_test_')
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def adapter(tmp_db_path):
    a = CodernityDBAdapter()
    a.create(tmp_db_path)
    yield a
    if a.is_open:
        a.close()


class TestCodernityDBAdapterInterface:
    """Verify adapter implements DatabaseInterface correctly."""

    def test_is_database_interface(self):
        assert issubclass(CodernityDBAdapter, DatabaseInterface)

    def test_create_opens_db(self, adapter):
        assert adapter.is_open

    def test_close(self, adapter):
        adapter.close()
        assert not adapter.is_open

    def test_open_existing(self, tmp_db_path):
        a = CodernityDBAdapter()
        a.create(tmp_db_path)
        a.close()

        a2 = CodernityDBAdapter()
        a2.open(tmp_db_path)
        assert a2.is_open
        a2.close()


class TestCodernityDBAdapterCRUD:
    """Test CRUD operations through the adapter."""

    def test_insert_returns_id_and_rev(self, adapter):
        result = adapter.insert({'name': 'test'})
        assert '_id' in result
        assert '_rev' in result

    def test_get_by_id(self, adapter):
        result = adapter.insert({'name': 'findme', 'val': 123})
        doc = adapter.get('id', result['_id'])
        assert doc['name'] == 'findme'
        assert doc['val'] == 123

    def test_get_not_found_raises_keyerror(self, adapter):
        with pytest.raises(KeyError):
            adapter.get('id', b'x' * 32)

    def test_update(self, adapter):
        result = adapter.insert({'name': 'v1'})
        doc = adapter.get('id', result['_id'])
        doc['name'] = 'v2'
        adapter.update(doc)
        doc2 = adapter.get('id', result['_id'])
        assert doc2['name'] == 'v2'

    def test_delete(self, adapter):
        result = adapter.insert({'name': 'bye'})
        doc = adapter.get('id', result['_id'])
        adapter.delete(doc)
        with pytest.raises(KeyError):
            adapter.get('id', result['_id'])

    def test_all_iterates_documents(self, adapter):
        for i in range(5):
            adapter.insert({'i': i})
        docs = list(adapter.all('id'))
        assert len(docs) == 5

    def test_insert_multiple_and_count(self, adapter):
        for i in range(20):
            adapter.insert({'n': i})
        docs = list(adapter.all('id'))
        assert len(docs) == 20


class TestCodernityDBAdapterProperties:
    """Test adapter property access."""

    def test_path(self, adapter, tmp_db_path):
        assert adapter.path == tmp_db_path

    def test_indexes_names(self, adapter):
        assert 'id' in adapter.indexes_names

    def test_db_access(self, adapter):
        assert adapter.db is not None
        assert adapter.db.opened
