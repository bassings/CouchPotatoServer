"""Tests for movie collections."""
import os

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import api, api_locks, callApiHandler
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.environment import Env


@pytest.fixture
def db(tmp_path):
    adapter = SQLiteAdapter()
    adapter.create(str(tmp_path / "collectionsdb"))
    yield adapter
    adapter.close()


@pytest.fixture
def collections_plugin(db):
    old_db = Env.get('db')
    old_api = dict(api)
    old_locks = dict(api_locks)
    Env.set('db', db)
    api.clear()
    api_locks.clear()

    from couchpotato.core.plugins.collection import CollectionPlugin
    CollectionPlugin()

    yield db

    Env.set('db', old_db)
    api.clear()
    api.update(old_api)
    api_locks.clear()
    api_locks.update(old_locks)


def make_media(db, title='The Matrix'):
    result = db.insert({
        '_t': 'media',
        'type': 'movie',
        'status': 'active',
        'title': title,
        'info': {'titles': [title], 'year': 1999},
        'identifiers': {'imdb': 'tt0133093'},
    })
    return db.get('id', result['_id'])


class TestSQLiteCollectionIndex:
    def test_collection_index_returns_only_collections_sorted_by_name(self, db):
        db.insert({'_t': 'media', 'title': 'Not a collection'})
        db.insert({'_t': 'collection', 'name': 'Weekend Watch', 'media_ids': []})
        db.insert({'_t': 'collection', 'name': 'Marvel Movies', 'media_ids': []})

        collections = list(db.all('collection'))

        assert [c['name'] for c in collections] == ['Marvel Movies', 'Weekend Watch']


class TestCollectionApi:
    def test_create_and_list_collections(self, collections_plugin):
        created = callApiHandler('collection.create', name='Weekend Watch', description='Friday night')

        assert created['success'] is True
        assert created['collection']['_t'] == 'collection'
        assert created['collection']['name'] == 'Weekend Watch'
        assert created['collection']['description'] == 'Friday night'
        assert created['collection']['media_ids'] == []
        assert created['collection']['created_at']
        assert created['collection']['updated_at']

        listed = callApiHandler('collection.list')
        assert listed['success'] is True
        assert [c['name'] for c in listed['collections']] == ['Weekend Watch']

    def test_update_collection_name_and_description(self, collections_plugin):
        created = callApiHandler('collection.create', name='Old Name')
        collection_id = created['collection']['_id']

        updated = callApiHandler(
            'collection.update',
            id=collection_id,
            name='New Name',
            description='Updated description',
        )

        assert updated['success'] is True
        assert updated['collection']['name'] == 'New Name'
        assert updated['collection']['description'] == 'Updated description'
        assert updated['collection']['updated_at'] >= updated['collection']['created_at']

    def test_add_and_remove_media_from_collection(self, collections_plugin):
        media = make_media(collections_plugin)
        created = callApiHandler('collection.create', name='Sci-Fi')
        collection_id = created['collection']['_id']

        added = callApiHandler('collection.add_media', id=collection_id, media_id=media['_id'])
        added_again = callApiHandler('collection.add_media', id=collection_id, media_id=media['_id'])

        assert added['success'] is True
        assert added_again['collection']['media_ids'] == [media['_id']]

        listed = callApiHandler('collection.list')
        assert listed['collections'][0]['movies'][0]['_id'] == media['_id']

        removed = callApiHandler('collection.remove_media', id=collection_id, media_id=media['_id'])
        assert removed['success'] is True
        assert removed['collection']['media_ids'] == []

    def test_delete_collection(self, collections_plugin):
        created = callApiHandler('collection.create', name='Temporary')

        deleted = callApiHandler('collection.delete', id=created['collection']['_id'])

        assert deleted == {'success': True}
        assert callApiHandler('collection.list')['collections'] == []

    def test_collection_create_requires_name(self, collections_plugin):
        result = callApiHandler('collection.create', name='  ')

        assert result['success'] is False
        assert 'name' in result['error'].lower()


class TestCollectionsUi:
    def test_collections_page_is_routable_from_new_ui(self, tmp_path):
        old_setting = Env.setting
        old_app_dir = Env.get('app_dir')
        old_web_base = getattr(Env, '_web_base', None)
        old_api_base = getattr(Env, '_api_base', None)
        old_static_path = getattr(Env, '_static_path', None)

        settings = {
            'username': '',
            'password': '',
            'api_key': 'testkey123',
            'rate_limit_max': 0,
            'cors_origins': '',
        }

        def mock_setting(key=None, *args, **kwargs):
            if 'value' in kwargs:
                settings[key] = kwargs['value']
                return
            return settings.get(key, kwargs.get('default', ''))

        try:
            Env.setting = staticmethod(mock_setting)
            Env.set('web_base', '/')
            Env.set('api_base', '/api/testkey123/')
            Env.set('static_path', '/static/')
            Env.set('app_dir', os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

            from couchpotato import create_app
            client = TestClient(create_app('testkey123', '/'))

            response = client.get('/collections/')

            assert response.status_code == 200
            assert 'Collections' in response.text
            assert 'hx-get="/partial/collections"' in response.text
        finally:
            Env.setting = old_setting
            Env.set('app_dir', old_app_dir)
            Env.set('web_base', old_web_base)
            Env.set('api_base', old_api_base)
            Env.set('static_path', old_static_path)
