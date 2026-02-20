"""Tests for has_releases filter in media.list."""
import pytest
from unittest.mock import patch, MagicMock


def make_media(media_id, status='active', profile_id='prof1'):
    return {'_id': media_id, '_t': 'media', 'status': status, 'profile_id': profile_id,
            'title': f'Movie {media_id}', 'type': 'movie', 'identifiers': {'imdb': f'tt{media_id}'}}


def make_release(release_id, media_id, status='available'):
    return {'_id': release_id, '_t': 'release', 'media_id': media_id, 'status': status,
            'identifier': f'{media_id}.AAC.1080p', 'quality': '1080p', 'files': {}}


@pytest.fixture
def media_plugin():
    """Create a MediaPlugin with mocked dependencies."""
    from couchpotato.core.media._base.media.main import MediaPlugin
    plugin = MediaPlugin.__new__(MediaPlugin)
    return plugin


def test_has_releases_true_returns_only_media_with_releases(media_plugin):
    """has_releases=True should only return media that have at least one release."""
    media_a = make_media('media_a')  # has a release
    media_b = make_media('media_b')  # no releases

    release_a = make_release('rel_1', 'media_a', 'available')

    with patch('couchpotato.core.media._base.media.main.get_db') as mock_db, \
         patch('couchpotato.core.media._base.media.main.fireEvent') as mock_fire:

        db = MagicMock()
        mock_db.return_value = db

        # all() returns both media
        db.all.return_value = [{'_id': 'media_a'}, {'_id': 'media_b'}]
        db.get_many.return_value = [{'_id': 'media_a'}, {'_id': 'media_b'}]

        def fire_side_effect(event, *args, **kwargs):
            if event == 'release.with_status':
                return [release_a]
            if event == 'media.with_status':
                return [{'_id': 'media_a'}, {'_id': 'media_b'}]
            if event == 'media.get':
                mid = args[0] if args else None
                if mid == 'media_a':
                    return {**media_a, 'releases': [release_a]}
                return None
            return None

        mock_fire.side_effect = fire_side_effect
        db.all.return_value = [{'_id': 'media_a', 'title': 'Movie media_a'},
                                {'_id': 'media_b', 'title': 'Movie media_b'}]

        total, movies = media_plugin.list(types=['movie'], status=['active'], has_releases=True)

        assert total == 1
        assert movies[0]['_id'] == 'media_a'


def test_has_releases_false_returns_only_media_without_releases(media_plugin):
    """has_releases=False should only return media that have no releases."""
    media_a = make_media('media_a')  # has a release
    media_b = make_media('media_b')  # no releases
    release_a = make_release('rel_1', 'media_a', 'available')

    with patch('couchpotato.core.media._base.media.main.get_db') as mock_db, \
         patch('couchpotato.core.media._base.media.main.fireEvent') as mock_fire:

        db = MagicMock()
        mock_db.return_value = db
        db.get_many.return_value = [{'_id': 'media_a'}, {'_id': 'media_b'}]
        db.all.return_value = [{'_id': 'media_a', 'title': 'Movie media_a'},
                                {'_id': 'media_b', 'title': 'Movie media_b'}]

        def fire_side_effect(event, *args, **kwargs):
            if event == 'release.with_status':
                return [release_a]
            if event == 'media.with_status':
                return [{'_id': 'media_a'}, {'_id': 'media_b'}]
            if event == 'media.get':
                mid = args[0] if args else None
                return {**media_b, 'releases': []} if mid == 'media_b' else None
            return None

        mock_fire.side_effect = fire_side_effect

        total, movies = media_plugin.list(types=['movie'], status=['active'], has_releases=False)

        assert total == 1
        assert movies[0]['_id'] == 'media_b'


def test_has_releases_none_returns_all_media(media_plugin):
    """has_releases=None (default) should return all media unfiltered by release presence."""
    media_a = make_media('media_a')
    media_b = make_media('media_b')
    release_a = make_release('rel_1', 'media_a', 'done')

    with patch('couchpotato.core.media._base.media.main.get_db') as mock_db, \
         patch('couchpotato.core.media._base.media.main.fireEvent') as mock_fire:

        db = MagicMock()
        mock_db.return_value = db
        db.get_many.return_value = [{'_id': 'media_a'}, {'_id': 'media_b'}]
        db.all.return_value = [{'_id': 'media_a', 'title': 'Movie media_a'},
                                {'_id': 'media_b', 'title': 'Movie media_b'}]

        def fire_side_effect(event, *args, **kwargs):
            if event == 'media.with_status':
                return [{'_id': 'media_a'}, {'_id': 'media_b'}]
            if event == 'media.get':
                mid = args[0] if args else None
                return ({**media_a, 'releases': [release_a]} if mid == 'media_a'
                        else {**media_b, 'releases': []})
            return None

        mock_fire.side_effect = fire_side_effect

        total, movies = media_plugin.list(types=['movie'], status=['active'], has_releases=None)

        assert total == 2
