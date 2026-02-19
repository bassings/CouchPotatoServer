"""Tests for the SQLite database adapter."""
import json
import os
import tempfile

import pytest

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def db(tmp_path):
    """Create a fresh SQLite database for each test."""
    adapter = SQLiteAdapter()
    adapter.create(str(tmp_path / "testdb"))
    yield adapter
    adapter.close()


@pytest.fixture
def sample_media():
    return {
        '_t': 'media',
        'status': 'active',
        'title': 'The Matrix',
        'type': 'movie',
        'profile_id': None,
        'category_id': None,
        'identifiers': {'imdb': 'tt0133093', 'tmdb': 603},
        'info': {'genres': ['Action', 'Sci-Fi'], 'year': 1999},
        'tags': ['classic', 'sci-fi'],
    }


@pytest.fixture
def sample_release():
    return {
        '_t': 'release',
        'status': 'done',
        'media_id': 'abc123',
        'identifier': 'tt0133093.720p',
        'quality': '720p',
        'is_3d': False,
        'last_edit': 1700000000,
        'files': {'movie': ['/media/The Matrix.mkv']},
        'info': {},
    }


@pytest.fixture
def sample_quality():
    return {
        '_t': 'quality',
        'identifier': '1080p',
        'order': 1,
        'size_min': 5000,
        'size_max': 20000,
    }


@pytest.fixture
def sample_profile():
    return {
        '_t': 'profile',
        'label': 'Best',
        'order': 0,
        'core': True,
        'hide': False,
        'qualities': ['2160p', '1080p', '720p'],
        'wait_for': [0, 0, 0],
        'finish': [True, True, True],
    }


@pytest.fixture
def sample_notification():
    return {
        '_t': 'notification',
        'message': 'Downloaded The Matrix (720p)',
        'time': 1700000000,
        'read': False,
    }


@pytest.fixture
def sample_property():
    return {
        '_t': 'property',
        'identifier': 'manage.last_update',
        'value': '1700000000.0',
    }


class TestSQLiteAdapterLifecycle:
    def test_create_and_open(self, tmp_path):
        adapter = SQLiteAdapter()
        path = str(tmp_path / "newdb")
        adapter.create(path)
        assert adapter.is_open
        adapter.close()
        assert not adapter.is_open

        adapter.open(path)
        assert adapter.is_open
        adapter.close()

    def test_close_when_not_open(self):
        adapter = SQLiteAdapter()
        adapter.close()  # Should not raise

    def test_operations_when_closed(self):
        adapter = SQLiteAdapter()
        with pytest.raises(RuntimeError):
            adapter.get('id', 'test')

    def test_path_property(self, tmp_path):
        adapter = SQLiteAdapter()
        path = str(tmp_path / "testdb")
        adapter.create(path)
        assert adapter.path == path
        adapter.close()


class TestSQLiteAdapterCRUD:
    def test_insert_and_get(self, db, sample_media):
        result = db.insert(sample_media)
        assert '_id' in result
        assert '_rev' in result

        doc = db.get('id', result['_id'])
        assert doc['title'] == 'The Matrix'
        assert doc['_t'] == 'media'
        assert doc['identifiers']['imdb'] == 'tt0133093'

    def test_insert_with_custom_id(self, db, sample_media):
        sample_media['_id'] = 'custom123'
        result = db.insert(sample_media)
        assert result['_id'] == 'custom123'

        doc = db.get('id', 'custom123')
        assert doc['title'] == 'The Matrix'

    def test_update(self, db, sample_media):
        result = db.insert(sample_media)
        doc = db.get('id', result['_id'])
        doc['status'] = 'done'
        update_result = db.update(doc)
        assert update_result['_rev'] != result['_rev']

        updated = db.get('id', result['_id'])
        assert updated['status'] == 'done'

    def test_update_nonexistent(self, db):
        with pytest.raises(KeyError):
            db.update({'_id': 'nonexistent', '_t': 'media', 'title': 'X'})

    def test_delete(self, db, sample_media):
        result = db.insert(sample_media)
        assert db.delete({'_id': result['_id']})

        with pytest.raises(KeyError):
            db.get('id', result['_id'])

    def test_delete_nonexistent(self, db):
        assert not db.delete({'_id': 'nonexistent'})

    def test_get_nonexistent(self, db):
        with pytest.raises(KeyError):
            db.get('id', 'nonexistent')


class TestSQLiteAdapterIndexQueries:
    def test_media_status_query(self, db, sample_media):
        db.insert(sample_media)
        sample2 = dict(sample_media, title='Inception', status='done')
        db.insert(sample2)

        active = list(db.query('media_status', key='active', with_doc=True))
        assert len(active) == 1
        assert active[0]['doc']['title'] == 'The Matrix'

        done = list(db.query('media_status', key='done', with_doc=True))
        assert len(done) == 1
        assert done[0]['doc']['title'] == 'Inception'

    def test_media_by_type_query(self, db, sample_media):
        db.insert(sample_media)
        movies = list(db.query('media_by_type', key='movie', with_doc=True))
        assert len(movies) == 1

    def test_release_by_media_id(self, db, sample_release):
        db.insert(sample_release)
        releases = list(db.query('release', key='abc123', with_doc=True))
        assert len(releases) == 1
        assert releases[0]['doc']['identifier'] == 'tt0133093.720p'

    def test_release_status_query(self, db, sample_release):
        db.insert(sample_release)
        done = list(db.query('release_status', key='done', with_doc=True))
        assert len(done) == 1

    def test_release_id_query(self, db, sample_release):
        db.insert(sample_release)
        results = list(db.query('release_id', key='tt0133093.720p', with_doc=True))
        assert len(results) == 1

    def test_quality_query(self, db, sample_quality):
        db.insert(sample_quality)
        results = list(db.query('quality', key='1080p', with_doc=True))
        assert len(results) == 1
        assert results[0]['doc']['size_min'] == 5000

    def test_profile_query(self, db, sample_profile):
        db.insert(sample_profile)
        results = list(db.query('profile', with_doc=True))
        assert len(results) == 1
        assert results[0]['doc']['label'] == 'Best'

    def test_notification_query(self, db, sample_notification):
        db.insert(sample_notification)
        results = list(db.query('notification', with_doc=True))
        assert len(results) == 1
        assert results[0]['doc']['message'] == 'Downloaded The Matrix (720p)'

    def test_notification_unread_query(self, db, sample_notification):
        db.insert(sample_notification)
        # Insert a read notification
        read_notif = dict(sample_notification, message='Old notification', read=True, time=1600000000)
        db.insert(read_notif)

        unread = list(db.query('notification_unread', with_doc=True))
        assert len(unread) == 1
        assert unread[0]['doc']['message'] == 'Downloaded The Matrix (720p)'

    def test_property_query(self, db, sample_property):
        db.insert(sample_property)
        results = list(db.query('property', key='manage.last_update', with_doc=True))
        assert len(results) == 1
        assert results[0]['doc']['value'] == '1700000000.0'

    def test_category_query(self, db):
        cat = {'_t': 'category', 'label': 'Action', 'order': 0}
        db.insert(cat)
        results = list(db.query('category', with_doc=True))
        assert len(results) == 1

    def test_all_index(self, db, sample_media, sample_release):
        db.insert(sample_media)
        db.insert(sample_release)
        all_docs = list(db.all('id'))
        assert len(all_docs) == 2


class TestSQLiteAdapterDenormalized:
    def test_media_identifiers_populated(self, db, sample_media):
        result = db.insert(sample_media)
        doc = db.get_by_identifier('imdb', 'tt0133093')
        assert doc['title'] == 'The Matrix'

    def test_media_identifiers_updated_on_update(self, db, sample_media):
        result = db.insert(sample_media)
        doc = db.get('id', result['_id'])
        doc['identifiers']['imdb'] = 'tt9999999'
        db.update(doc)

        doc2 = db.get_by_identifier('imdb', 'tt9999999')
        assert doc2['title'] == 'The Matrix'

        with pytest.raises(KeyError):
            db.get_by_identifier('imdb', 'tt0133093')

    def test_media_tags_populated(self, db, sample_media):
        db.insert(sample_media)
        results = list(db.query('media_tag', key='classic', with_doc=True))
        assert len(results) == 1
        assert results[0]['doc']['title'] == 'The Matrix'

    def test_media_identifiers_cleaned_on_delete(self, db, sample_media):
        result = db.insert(sample_media)
        db.delete({'_id': result['_id']})
        with pytest.raises(KeyError):
            db.get_by_identifier('imdb', 'tt0133093')


class TestSQLiteAdapterLimitOffset:
    def test_limit(self, db):
        for i in range(5):
            db.insert({'_t': 'property', 'identifier': f'key{i}', 'value': str(i)})
        results = list(db.all('property', limit=3))
        assert len(results) == 3

    def test_offset(self, db):
        for i in range(5):
            db.insert({'_t': 'property', 'identifier': f'key{i}', 'value': str(i)})
        all_results = list(db.all('property'))
        offset_results = list(db.all('property', offset=2))
        assert len(offset_results) == 3
        assert offset_results[0]['_id'] == all_results[2]['_id']


class TestSQLiteAdapterBulkInsert:
    def test_bulk_insert(self, db):
        docs = [
            {'_t': 'quality', '_id': f'q{i}', 'identifier': f'{i}p', 'order': i}
            for i in range(10)
        ]
        count = db.insert_bulk(docs)
        assert count == 10

        all_docs = list(db.all('quality'))
        assert len(all_docs) == 10


class TestSQLiteAdapterJSONHandling:
    def test_nested_json_preserved(self, db):
        media = {
            '_t': 'media',
            'title': 'Test',
            'type': 'movie',
            'status': 'active',
            'identifiers': {},
            'info': {
                'deeply': {'nested': {'data': [1, 2, 3]}},
                'unicode': '日本語テスト 🎬',
            },
        }
        result = db.insert(media)
        doc = db.get('id', result['_id'])
        assert doc['info']['deeply']['nested']['data'] == [1, 2, 3]
        assert doc['info']['unicode'] == '日本語テスト 🎬'

    def test_null_values(self, db):
        media = {
            '_t': 'media',
            'title': 'Test',
            'type': 'movie',
            'status': None,
            'identifiers': {},
            'info': None,
        }
        result = db.insert(media)
        doc = db.get('id', result['_id'])
        assert doc['status'] is None
        assert doc['info'] is None


class TestSQLiteAdapterCompat:
    """Test compatibility with CodernityDB adapter patterns."""

    def test_add_index(self, db):
        name = db.add_index('test_index')
        assert name == 'test_index'
        assert 'test_index' in db.indexes_names

    def test_reindex_noop(self, db):
        db.reindex('id')  # Should not raise

    def test_compact(self, db):
        db.compact()  # Should not raise

    def test_get_with_doc(self, db, sample_media):
        result = db.insert(sample_media)
        # get with index_name='id' should always return full doc
        doc = db.get('id', result['_id'], with_doc=True)
        assert doc['title'] == 'The Matrix'

    def test_named_index_get_with_doc(self, db, sample_property):
        db.insert(sample_property)
        doc = db.get('property', 'manage.last_update', with_doc=True)
        assert doc['doc']['value'] == '1700000000.0'
