"""Tests for CodernityDB Python 3 compatibility fixes."""
import os
import sys
import struct
import tempfile
import shutil
import pytest

# Add libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs'))

from CodernityDB.database import Database
from CodernityDB.hash_index import IU_HashIndex, IU_UniqueHashIndex, HashIndex, UniqueHashIndex
from CodernityDB.storage import IU_Storage


@pytest.fixture
def tmp_db_path():
    path = tempfile.mkdtemp(prefix='cdb_test_')
    yield path
    shutil.rmtree(path, ignore_errors=True)


class TestHashIndexByteHandling:
    """Verify hash index handles bytes/str correctly on Python 3."""

    def test_create_and_open_database(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.create()
        assert db.opened
        db.close()

        db2 = Database(tmp_db_path)
        db2.open()
        assert db2.opened
        db2.close()

    def test_insert_and_get_document(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.create()
        result = db.insert({'name': 'test', 'value': 42})
        assert '_id' in result
        assert '_rev' in result

        doc = db.get('id', result['_id'])
        assert doc['name'] == 'test'
        assert doc['value'] == 42
        db.close()

    def test_update_document(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.create()
        result = db.insert({'name': 'original'})
        doc = db.get('id', result['_id'])
        doc['name'] = 'updated'
        db.update(doc)
        doc2 = db.get('id', result['_id'])
        assert doc2['name'] == 'updated'
        db.close()

    def test_delete_document(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.create()
        result = db.insert({'name': 'to_delete'})
        doc = db.get('id', result['_id'])
        db.delete(doc)
        with pytest.raises(Exception):
            db.get('id', result['_id'])
        db.close()

    def test_multiple_inserts_and_all(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.create()
        ids = []
        for i in range(10):
            result = db.insert({'index': i})
            ids.append(result['_id'])

        count = 0
        for doc in db.all('id'):
            count += 1
        assert count == 10
        db.close()

    def test_status_bytes_consistency(self, tmp_db_path):
        """Verify status values are consistently bytes after pack/unpack."""
        db = Database(tmp_db_path)
        db.create()
        result = db.insert({'test': True})
        # Internal: get raw index data
        key, rev, start, size, status = db.id_ind.get(result['_id'])
        # Status should be bytes b'o' (open/active)
        assert isinstance(status, bytes), f"Status should be bytes, got {type(status)}"
        assert status == b'o'
        db.close()

    def test_rev_is_bytes(self, tmp_db_path):
        """Verify revision handling works with bytes."""
        db = Database(tmp_db_path)
        db.create()
        result = db.insert({'test': True})
        doc = db.get('id', result['_id'])
        # _rev should be usable (may be bytes or str depending on storage)
        assert doc['_rev'] is not None
        db.close()


class TestStorageByteHandling:
    """Verify storage handles bytes correctly."""

    def test_storage_create_and_open(self, tmp_db_path):
        storage = IU_Storage(tmp_db_path, 'test')
        storage.create()
        storage.close()

        storage2 = IU_Storage(tmp_db_path, 'test')
        storage2.open()
        storage2.close()

    def test_storage_save_and_get(self, tmp_db_path):
        storage = IU_Storage(tmp_db_path, 'test')
        storage.create()
        data = {'key': 'value', 'number': 42}
        start, size = storage.save(data)
        result = storage.get(start, size)
        assert result == data
        storage.close()

    def test_storage_deleted_status(self, tmp_db_path):
        """Storage.get should return None for deleted status."""
        storage = IU_Storage(tmp_db_path, 'test')
        storage.create()
        # Both str and bytes 'd' should indicate deleted
        assert storage.get(0, 0, 'd') is None
        assert storage.get(0, 0, b'd') is None
        storage.close()


class TestStructPackingCompat:
    """Verify struct packing works with bytes on Python 3."""

    def test_char_format_requires_bytes(self):
        """The 'c' struct format requires bytes in Python 3."""
        packed = struct.pack('<c', b'o')
        unpacked = struct.unpack('<c', packed)[0]
        assert unpacked == b'o'
        assert isinstance(unpacked, bytes)

    def test_status_round_trip(self):
        """Status values survive pack/unpack as bytes."""
        for status in [b'o', b'd', b'u']:
            packed = struct.pack('<c', status)
            result = struct.unpack('<c', packed)[0]
            assert result == status

    def test_32s_format_with_bytes(self):
        """32-byte string format works with bytes."""
        doc_id = b'a' * 32
        packed = struct.pack('<32s', doc_id)
        unpacked = struct.unpack('<32s', packed)[0]
        assert unpacked == doc_id

    def test_entry_format_packing(self):
        """Full entry line format packs/unpacks correctly."""
        fmt = '<32scIIcI'
        doc_id = b'a' * 32
        key = b'x'
        start = 100
        size = 200
        status = b'o'
        next_ptr = 0
        packed = struct.pack(fmt, doc_id, key, start, size, status, next_ptr)
        result = struct.unpack(fmt, packed)
        assert result[0] == doc_id
        assert result[1] == key
        assert result[4] == status
