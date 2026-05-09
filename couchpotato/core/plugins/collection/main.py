import time
import traceback

from CodernityDB.database import RecordDeleted, RecordNotFound

from couchpotato import get_db
from couchpotato.api import addApiView
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.logger import CPLog
from couchpotato.core.media_lock import media_lock
from couchpotato.core.plugins.base import Plugin
from .index import CollectionIndex


log = CPLog(__name__)


class CollectionPlugin(Plugin):

    _database = {
        'collection': CollectionIndex,
    }

    def __init__(self):
        addApiView('collection.list', self.listView, docs={
            'desc': 'List movie collections',
        })
        addApiView('collection.create', self.create)
        addApiView('collection.update', self.update)
        addApiView('collection.delete', self.delete)
        addApiView('collection.add_media', self.addMedia)
        addApiView('collection.remove_media', self.removeMedia)

    def _now(self):
        return time.time()

    def _clean_name(self, name):
        return toUnicode(name or '').strip()

    def _clean_description(self, description):
        return toUnicode(description or '').strip()

    def _error(self, message):
        return {'success': False, 'error': message}

    def _get_collection(self, collection_id):
        doc = get_db().get('id', collection_id)
        if doc.get('_t') != 'collection':
            raise KeyError('Collection not found: %s' % collection_id)
        doc.setdefault('description', '')
        doc.setdefault('media_ids', [])
        return doc

    def _get_media(self, media_id):
        doc = get_db().get('id', media_id)
        if doc.get('_t') != 'media':
            raise KeyError('Media not found: %s' % media_id)
        return doc

    def _with_movies(self, collection):
        movies = []
        db = get_db()
        for media_id in collection.get('media_ids', []) or []:
            try:
                media = db.get('id', media_id)
                if media.get('_t') == 'media':
                    movies.append(media)
            except (KeyError, RecordDeleted, RecordNotFound):
                continue
            except Exception:
                log.debug('Failed loading collection media %s: %s', media_id, traceback.format_exc())
        collection = dict(collection)
        collection['movies'] = movies
        return collection

    def list(self, include_movies=True):
        collections = []
        for row in get_db().all('collection'):
            collection = row.get('doc', row)
            collections.append(self._with_movies(collection) if include_movies else collection)
        return collections

    def listView(self, **kwargs):
        include_movies = str(kwargs.get('include_movies', '1')).lower() not in ('0', 'false', 'no')
        return {
            'success': True,
            'collections': self.list(include_movies=include_movies),
        }

    def create(self, name='', description='', **kwargs):
        name = self._clean_name(name)
        if not name:
            return self._error('Collection name is required')

        now = self._now()
        collection = {
            '_t': 'collection',
            'name': name,
            'description': self._clean_description(description),
            'media_ids': [],
            'created_at': now,
            'updated_at': now,
        }
        result = get_db().insert(collection)
        collection.update(result)
        return {'success': True, 'collection': collection}

    def update(self, id='', name='', description='', **kwargs):
        name = self._clean_name(name)
        if not id:
            return self._error('Collection id is required')
        if not name:
            return self._error('Collection name is required')

        with media_lock('collection-%s' % id):
            try:
                collection = self._get_collection(id)
            except Exception:
                return self._error('Collection not found')

            collection['name'] = name
            collection['description'] = self._clean_description(description)
            collection.setdefault('created_at', self._now())
            collection['updated_at'] = self._now()
            result = get_db().update(collection)
            collection.update(result)
            return {'success': True, 'collection': collection}

    def delete(self, id='', **kwargs):
        if not id:
            return self._error('Collection id is required')
        try:
            collection = self._get_collection(id)
        except Exception:
            return self._error('Collection not found')
        get_db().delete(collection)
        return {'success': True}

    def addMedia(self, id='', media_id='', **kwargs):
        if not id:
            return self._error('Collection id is required')
        if not media_id:
            return self._error('Media id is required')

        with media_lock('collection-%s' % id):
            try:
                collection = self._get_collection(id)
                self._get_media(media_id)
            except Exception:
                return self._error('Collection or media not found')

            media_ids = list(collection.get('media_ids', []) or [])
            if media_id not in media_ids:
                media_ids.append(media_id)
                collection['media_ids'] = media_ids
                collection.setdefault('created_at', self._now())
                collection['updated_at'] = self._now()
                result = get_db().update(collection)
                collection.update(result)
            return {'success': True, 'collection': self._with_movies(collection)}

    def removeMedia(self, id='', media_id='', **kwargs):
        if not id:
            return self._error('Collection id is required')
        if not media_id:
            return self._error('Media id is required')

        with media_lock('collection-%s' % id):
            try:
                collection = self._get_collection(id)
            except Exception:
                return self._error('Collection not found')

            media_ids = [x for x in (collection.get('media_ids', []) or []) if x != media_id]
            if media_ids != collection.get('media_ids', []):
                collection['media_ids'] = media_ids
                collection.setdefault('created_at', self._now())
                collection['updated_at'] = self._now()
                result = get_db().update(collection)
                collection.update(result)
            return {'success': True, 'collection': self._with_movies(collection)}
