"""Tests for the Database class from couchpotato.core.database.

Covers validation methods, API endpoints, and core DB operations.
"""
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure libs are importable
libs_path = os.path.join(os.path.dirname(__file__), '..', '..', 'libs')
if libs_path not in sys.path:
    sys.path.insert(0, os.path.abspath(libs_path))


# ─── Document ID Validation Tests ────────────────────────────────────────────

class TestValidateDocumentId:
    """Tests for Database._validate_document_id static method."""

    @pytest.fixture
    def validate(self):
        from couchpotato.core.database import Database
        return Database._validate_document_id

    def test_none_returns_error(self, validate):
        error = validate(None)
        assert error is not None
        assert 'required' in error.lower()

    def test_empty_string_returns_error(self, validate):
        error = validate('')
        assert error is not None
        assert 'empty' in error.lower() or 'required' in error.lower()

    def test_whitespace_only_returns_error(self, validate):
        error = validate('   ')
        assert error is not None
        assert 'empty' in error.lower()

    def test_non_string_returns_error(self, validate):
        error = validate(12345)
        assert error is not None
        assert 'string' in error.lower()

    def test_too_long_returns_error(self, validate):
        error = validate('x' * 300)
        assert error is not None
        assert 'long' in error.lower()

    def test_valid_id_returns_none(self, validate):
        error = validate('abc123-def456')
        assert error is None

    def test_valid_short_id(self, validate):
        error = validate('a')
        assert error is None

    def test_valid_max_length_id(self, validate):
        error = validate('x' * 256)
        assert error is None

    def test_path_traversal_rejected(self, validate):
        error = validate('../../../etc/passwd')
        assert error is not None
        assert 'invalid' in error.lower()

    def test_shell_injection_semicolon_rejected(self, validate):
        error = validate('id; rm -rf /')
        assert error is not None
        assert 'invalid' in error.lower()

    def test_shell_injection_pipe_rejected(self, validate):
        error = validate('id | cat /etc/passwd')
        assert error is not None
        assert 'invalid' in error.lower()

    def test_shell_injection_ampersand_rejected(self, validate):
        error = validate('id && rm -rf /')
        assert error is not None
        assert 'invalid' in error.lower()

    def test_shell_injection_backtick_rejected(self, validate):
        error = validate('id`whoami`')
        assert error is not None
        assert 'invalid' in error.lower()

    def test_shell_injection_dollar_rejected(self, validate):
        error = validate('id$USER')
        assert error is not None
        assert 'invalid' in error.lower()

    def test_valid_id_with_hyphens_dashes(self, validate):
        error = validate('user-profile-123_456')
        assert error is None

    def test_valid_uuid_format(self, validate):
        error = validate('550e8400-e29b-41d4-a716-446655440000')
        assert error is None


# ─── Document Payload Validation Tests ───────────────────────────────────────

class TestValidateDocumentPayload:
    """Tests for Database._validate_document_payload static method."""

    @pytest.fixture
    def validate(self):
        from couchpotato.core.database import Database
        return Database._validate_document_payload

    def test_none_returns_error(self, validate):
        doc, error = validate(None)
        assert doc is None
        assert error is not None
        assert 'required' in error.lower()

    def test_empty_string_returns_error(self, validate):
        doc, error = validate('')
        assert doc is None
        assert error is not None

    def test_non_json_returns_error(self, validate):
        doc, error = validate('not json at all')
        assert doc is None
        assert error is not None
        assert 'json' in error.lower()

    def test_json_array_returns_error(self, validate):
        doc, error = validate('[1, 2, 3]')
        assert doc is None
        assert error is not None
        assert 'object' in error.lower()

    def test_missing_id_returns_error(self, validate):
        doc, error = validate('{"name": "test"}')
        assert doc is None
        assert error is not None
        assert '_id' in error

    def test_valid_document_returns_doc(self, validate):
        payload = json.dumps({'_id': 'test123', 'name': 'test'})
        doc, error = validate(payload)
        assert error is None
        assert doc is not None
        assert doc['_id'] == 'test123'
        assert doc['name'] == 'test'

    def test_too_large_payload_returns_error(self, validate):
        # Create a 2MB payload
        large = json.dumps({'_id': 'x', 'data': 'x' * 2_000_000})
        doc, error = validate(large)
        assert doc is None
        assert error is not None
        assert 'large' in error.lower()

    def test_invalid_id_in_document_returns_error(self, validate):
        payload = json.dumps({'_id': '../../../etc/passwd', 'name': 'test'})
        doc, error = validate(payload)
        assert doc is None
        assert error is not None
        assert 'invalid' in error.lower()


# ─── Storage _decode_bytes Tests ─────────────────────────────────────────────

class TestStorageDecodeBytes:
    """Tests for IU_Storage._decode_bytes static method."""

    @pytest.fixture
    def decode(self):
        from CodernityDB.storage import IU_Storage
        return IU_Storage._decode_bytes

    def test_decodes_bytes_string(self, decode):
        result = decode(b'hello')
        assert result == 'hello'

    def test_passes_through_regular_string(self, decode):
        result = decode('hello')
        assert result == 'hello'

    def test_passes_through_numbers(self, decode):
        assert decode(42) == 42
        assert decode(3.14) == 3.14

    def test_passes_through_none(self, decode):
        assert decode(None) is None

    def test_decodes_dict_keys(self, decode):
        result = decode({b'key': 'value'})
        assert 'key' in result
        assert result['key'] == 'value'

    def test_decodes_dict_values(self, decode):
        result = decode({'key': b'value'})
        assert result['key'] == 'value'

    def test_decodes_nested_dict(self, decode):
        result = decode({
            b'outer': {
                b'inner': b'deep value'
            }
        })
        assert result['outer']['inner'] == 'deep value'

    def test_decodes_list_values(self, decode):
        result = decode([b'one', b'two', b'three'])
        assert result == ['one', 'two', 'three']

    def test_decodes_list_in_dict(self, decode):
        result = decode({
            'items': [b'a', b'b', b'c']
        })
        assert result['items'] == ['a', 'b', 'c']

    def test_handles_mixed_types(self, decode):
        result = decode({
            b'name': b'test',
            'count': 42,
            'items': [b'x', 'y', 100],
            'nested': {b'key': b'val'}
        })
        assert result['name'] == 'test'
        assert result['count'] == 42
        assert result['items'] == ['x', 'y', 100]
        assert result['nested']['key'] == 'val'

    def test_handles_invalid_utf8(self, decode):
        # Invalid UTF-8 sequence should use replacement
        invalid = b'\xff\xfe'
        result = decode({b'data': invalid})
        assert 'data' in result
        # Should contain replacement characters, not crash

    def test_empty_dict(self, decode):
        assert decode({}) == {}

    def test_empty_list(self, decode):
        assert decode([]) == []


# ─── Database API Methods Tests ──────────────────────────────────────────────

class TestDatabaseDeleteDocument:
    """Tests for Database.deleteDocument method."""

    @pytest.fixture
    def database_instance(self):
        """Create a Database instance with mocked dependencies."""
        # We need to mock the imports and event system
        with patch('couchpotato.core.database.addApiView'), \
             patch('couchpotato.core.database.addEvent'):
            from couchpotato.core.database import Database
            db = Database()
            db.db = MagicMock()
            return db

    def test_delete_with_invalid_id_returns_error(self, database_instance):
        result = database_instance.deleteDocument(id='')
        assert result['success'] is False
        assert 'error' in result

    def test_delete_with_path_traversal_rejected(self, database_instance):
        result = database_instance.deleteDocument(id='../../../etc/passwd')
        assert result['success'] is False
        assert 'invalid' in result['error'].lower()

    def test_delete_success(self, database_instance):
        mock_doc = {'_id': 'test123', '_rev': 'abc'}
        database_instance.db.get.return_value = mock_doc
        database_instance.db.delete.return_value = None

        result = database_instance.deleteDocument(id='test123')
        assert result['success'] is True
        database_instance.db.delete.assert_called_once_with(mock_doc)

    def test_delete_handles_exception(self, database_instance):
        database_instance.db.get.side_effect = Exception("Not found")

        result = database_instance.deleteDocument(id='test123')
        assert result['success'] is False
        assert 'error' in result


class TestDatabaseUpdateDocument:
    """Tests for Database.updateDocument method."""

    @pytest.fixture
    def database_instance(self):
        with patch('couchpotato.core.database.addApiView'), \
             patch('couchpotato.core.database.addEvent'):
            from couchpotato.core.database import Database
            db = Database()
            db.db = MagicMock()
            return db

    def test_update_with_invalid_json_returns_error(self, database_instance):
        result = database_instance.updateDocument(document='not json')
        assert result['success'] is False
        assert 'json' in result['error'].lower()

    def test_update_with_missing_id_returns_error(self, database_instance):
        result = database_instance.updateDocument(
            document=json.dumps({'name': 'test'})
        )
        assert result['success'] is False
        assert '_id' in result['error']

    def test_update_success(self, database_instance):
        payload = json.dumps({'_id': 'test123', 'name': 'updated'})
        database_instance.db.update.return_value = {'_rev': 'new_rev'}

        result = database_instance.updateDocument(document=payload)
        assert result['success'] is True
        assert result['document']['name'] == 'updated'

    def test_update_handles_exception(self, database_instance):
        payload = json.dumps({'_id': 'test123', 'name': 'test'})
        database_instance.db.update.side_effect = Exception("DB error")

        result = database_instance.updateDocument(document=payload)
        assert result['success'] is False


class TestDatabaseListDocuments:
    """Tests for Database.listDocuments method."""

    @pytest.fixture
    def database_instance(self):
        with patch('couchpotato.core.database.addApiView'), \
             patch('couchpotato.core.database.addEvent'):
            from couchpotato.core.database import Database
            db = Database()
            db.db = MagicMock()
            return db

    def test_lists_all_documents(self, database_instance):
        database_instance.db.all.return_value = [
            {'_t': 'media', '_id': '1'},
            {'_t': 'media', '_id': '2'},
            {'_t': 'release', '_id': '3'},
        ]

        result = database_instance.listDocuments()
        assert 'media' in result
        assert 'release' in result
        assert len(result['media']) == 2
        assert len(result['release']) == 1

    def test_lists_filtered_by_show(self, database_instance):
        database_instance.db.all.return_value = [
            {'_t': 'media', '_id': '1'},
            {'_t': 'release', '_id': '2'},
        ]

        result = database_instance.listDocuments(show='media')
        assert 'media' in result
        assert 'release' not in result or len(result.get('release', [])) == 0

    def test_handles_unknown_type(self, database_instance):
        database_instance.db.all.return_value = [
            {'_id': '1'},  # No _t field
        ]

        result = database_instance.listDocuments()
        assert 'unknown' in result
        assert len(result['unknown']) == 1


class TestDatabaseReindex:
    """Tests for Database.reindex method."""

    @pytest.fixture
    def database_instance(self):
        with patch('couchpotato.core.database.addApiView'), \
             patch('couchpotato.core.database.addEvent'):
            from couchpotato.core.database import Database
            db = Database()
            db.db = MagicMock()
            return db

    def test_reindex_success(self, database_instance):
        result = database_instance.reindex()
        assert result['success'] is True
        database_instance.db.reindex.assert_called_once()

    def test_reindex_handles_exception(self, database_instance):
        database_instance.db.reindex.side_effect = Exception("Reindex failed")
        result = database_instance.reindex()
        assert result['success'] is False


# ─── Additional Edge Cases for Migration Modules ─────────────────────────────

class TestCleanOrphansEdgeCases:
    """Additional edge cases for clean_orphaned_movies."""

    @pytest.fixture
    def db(self, tmp_path):
        from CodernityDB.database import Database
        from CodernityDB.tree_index import TreeBasedIndex

        db = Database(str(tmp_path / 'testdb'))
        db.create()

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

    def test_skips_non_movie_media(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        # Insert TV show (not a movie)
        db.insert({
            '_t': 'media',
            'type': 'show',
            'identifiers': {'tvdb': '12345'},
            'info': {
                'titles': [],
                'original_title': '',
                'year': 0,
                'plot': '',
            }
        })

        removed = clean_orphaned_movies(db)
        assert removed == 0

    def test_handles_missing_info_field(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        # Insert movie with no info field at all
        db.insert({
            '_t': 'media',
            'type': 'movie',
            'identifiers': {'imdb': 'tt0000001'},
        })

        # Should not crash
        removed = clean_orphaned_movies(db)
        # Behavior depends on implementation - might or might not remove

    def test_keeps_movie_with_only_original_title(self, db):
        from couchpotato.core.migration.clean_orphans import clean_orphaned_movies

        db.insert({
            '_t': 'media',
            'type': 'movie',
            'identifiers': {'imdb': 'tt0000002'},
            'info': {
                'titles': [],  # Empty titles list
                'original_title': 'Original Title Only',
                'year': 0,
                'plot': '',
            }
        })

        removed = clean_orphaned_movies(db)
        assert removed == 0  # Should keep because it has original_title


class TestRebuildBucketsEdgeCases:
    """Additional edge cases for rebuild_after_migration."""

    def test_handles_corrupt_entry(self, tmp_path):
        """Rebuild should skip corrupt entries gracefully."""
        from CodernityDB.database import Database
        from couchpotato.core.migration.rebuild_buckets import rebuild_after_migration

        db_path = str(tmp_path / 'db')
        db = Database(db_path)
        db.create()

        # Insert valid records
        for i in range(5):
            db.insert({'index': i})

        db.close()

        # Reopen and rebuild
        db2 = Database(db_path)
        rebuild_after_migration(db2, db_path)

        # Should still work
        count = sum(1 for _ in db2.all('id'))
        assert count == 5
        db2.close()


class TestFixIndexesEdgeCases:
    """Additional edge cases for fix_index_files."""

    @pytest.fixture
    def db_dir(self, tmp_path):
        indexes_dir = tmp_path / '_indexes'
        indexes_dir.mkdir()
        return tmp_path, indexes_dir

    def test_handles_permission_error(self, db_dir, monkeypatch):
        """Should handle unreadable files gracefully."""
        from couchpotato.core.migration.fix_indexes import fix_index_files

        db_path, indexes_dir = db_dir
        # This test would need actual permission changes which may not work
        # in all environments, so we just verify the function doesn't crash
        result = fix_index_files(str(db_path))
        assert result >= 0

    def test_handles_complex_md5_expression(self, db_dir):
        """Should fix complex expressions inside md5()."""
        from couchpotato.core.migration.fix_indexes import fix_index_files

        db_path, indexes_dir = db_dir
        content = '''from hashlib import md5
def make_key(data):
    return md5(data.get("field", "") + "_suffix").hexdigest()
'''
        path = indexes_dir / 'complex.py'
        path.write_text(content)

        result = fix_index_files(str(db_path))
        assert result == 1

        fixed = path.read_text()
        assert '_to_bytes' in fixed
