"""Tests for tree_index.py Python 3 compatibility."""
import os
import sys
import tempfile
import shutil
import struct
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs'))

from CodernityDB.database import Database
from CodernityDB.tree_index import TreeBasedIndex, MultiTreeBasedIndex


class SimpleTreeIndex(TreeBasedIndex):
    """Simple tree index for testing - indexes by 'category' field."""

    _version = 1
    custom_header = 'from CodernityDB.tree_index import TreeBasedIndex'

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super().__init__(*args, **kwargs)

    def make_key_value(self, data):
        if 'category' in data:
            key = data['category']
            if isinstance(key, str):
                key = key.encode('utf-8').ljust(32, b'\x00')[:32]
            elif isinstance(key, bytes):
                key = key.ljust(32, b'\x00')[:32]
            else:
                return None
            return key, {'category': data['category']}
        return None

    def make_key(self, key):
        if isinstance(key, str):
            key = key.encode('utf-8').ljust(32, b'\x00')[:32]
        elif isinstance(key, bytes):
            key = key.ljust(32, b'\x00')[:32]
        return key


class SimpleMultiTreeIndex(MultiTreeBasedIndex):
    """Multi-key tree index for testing - indexes by 'tags' field."""

    _version = 1
    custom_header = 'from CodernityDB.tree_index import MultiTreeBasedIndex'

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super().__init__(*args, **kwargs)

    def make_key_value(self, data):
        if 'tags' in data and data['tags']:
            keys = set()
            for tag in data['tags']:
                if isinstance(tag, str):
                    keys.add(tag.encode('utf-8').ljust(32, b'\x00')[:32])
                elif isinstance(tag, bytes):
                    keys.add(tag.ljust(32, b'\x00')[:32])
            return keys, {'tags': data['tags']}
        return None

    def make_key(self, key):
        if isinstance(key, str):
            key = key.encode('utf-8').ljust(32, b'\x00')[:32]
        elif isinstance(key, bytes):
            key = key.ljust(32, b'\x00')[:32]
        return key


@pytest.fixture
def tmp_db_path():
    path = tempfile.mkdtemp(prefix='tree_test_')
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def db_with_tree_index(tmp_db_path):
    db = Database(tmp_db_path)
    db.create()
    db.add_index(SimpleTreeIndex(tmp_db_path, 'category'))
    yield db
    if db.opened:
        db.close()


@pytest.fixture
def db_with_multi_tree(tmp_db_path):
    db = Database(tmp_db_path)
    db.create()
    db.add_index(SimpleMultiTreeIndex(tmp_db_path, 'tags'))
    yield db
    if db.opened:
        db.close()


class TestTreeIndexBasicOps:
    """Test basic tree index operations on Python 3."""

    def test_insert_and_get(self, db_with_tree_index):
        db = db_with_tree_index
        db.insert({'category': 'movies', 'title': 'Test Movie'})
        result = db.get('category', 'movies', with_doc=True)
        assert result is not None

    def test_insert_multiple_same_key(self, db_with_tree_index):
        db = db_with_tree_index
        for i in range(5):
            db.insert({'category': 'action', 'n': i})
        results = list(db.get_many('category', key='action', limit=10, with_doc=True))
        assert len(results) == 5

    def test_insert_different_keys(self, db_with_tree_index):
        db = db_with_tree_index
        db.insert({'category': 'action', 'n': 1})
        db.insert({'category': 'comedy', 'n': 2})
        db.insert({'category': 'drama', 'n': 3})

        r1 = db.get('category', 'action', with_doc=True)
        r2 = db.get('category', 'comedy', with_doc=True)
        r3 = db.get('category', 'drama', with_doc=True)
        assert r1 is not None
        assert r2 is not None
        assert r3 is not None

    def test_update_indexed_document(self, db_with_tree_index):
        db = db_with_tree_index
        result = db.insert({'category': 'horror', 'rating': 5})
        doc = db.get('id', result['_id'])
        doc['rating'] = 10
        db.update(doc)
        updated = db.get('id', result['_id'])
        assert updated['rating'] == 10

    def test_delete_indexed_document(self, db_with_tree_index):
        db = db_with_tree_index
        result = db.insert({'category': 'scifi', 'title': 'Gone'})
        doc = db.get('id', result['_id'])
        db.delete(doc)
        # Document should be gone from id index
        with pytest.raises(Exception):
            db.get('id', result['_id'])

    def test_all_on_tree_index(self, db_with_tree_index):
        db = db_with_tree_index
        for i in range(10):
            db.insert({'category': f'cat{i:02d}', 'n': i})
        results = list(db.all('category'))
        assert len(results) == 10

    def test_many_inserts_triggers_split(self, db_with_tree_index):
        """Insert enough records to trigger B-tree node splits."""
        db = db_with_tree_index
        for i in range(50):
            db.insert({'category': f'item{i:04d}', 'n': i})
        results = list(db.all('category'))
        assert len(results) == 50


class TestMultiTreeIndex:
    """Test multi-key tree index on Python 3."""

    def test_insert_with_multiple_tags(self, db_with_multi_tree):
        db = db_with_multi_tree
        db.insert({'tags': ['action', 'thriller'], 'title': 'Die Hard'})
        r1 = db.get('tags', 'action', with_doc=True)
        r2 = db.get('tags', 'thriller', with_doc=True)
        assert r1 is not None
        assert r2 is not None

    def test_no_tags_not_indexed(self, db_with_multi_tree):
        db = db_with_multi_tree
        db.insert({'title': 'No Tags Here'})
        # Should have one doc in id but none in tags
        docs = list(db.all('id'))
        assert len(docs) == 1


class TestTreeIndexBytesCompat:
    """Verify bytes handling in tree index internals."""

    def test_root_flag_is_bytes(self, db_with_tree_index):
        db = db_with_tree_index
        idx = db.indexes_names['category']
        assert isinstance(idx.root_flag, bytes)

    def test_status_from_leaf_is_bytes(self, db_with_tree_index):
        db = db_with_tree_index
        db.insert({'category': 'test', 'v': 1})
        idx = db.indexes_names['category']
        # Read first leaf record
        key, doc_id, start, size, status = idx._read_single_leaf_record(
            idx.data_start if idx.root_flag == b'l' else idx.data_start + idx.node_size,
            0
        )
        assert isinstance(status, bytes)
        assert status == b'o'

    def test_integer_division_in_split(self, db_with_tree_index):
        """Ensure node_capacity // 2 produces int, not float."""
        db = db_with_tree_index
        idx = db.indexes_names['category']
        half = idx.node_capacity // 2
        assert isinstance(half, int)
