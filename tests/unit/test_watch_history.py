"""Unit tests for media watch history behaviour."""
from unittest.mock import MagicMock, patch

from couchpotato.core.media._base.media.main import MediaPlugin


def make_media(media_id, watched=False, status='done'):
    media = {
        '_id': media_id,
        '_t': 'media',
        'type': 'movie',
        'status': status,
        'title': f'Movie {media_id}',
        'info': {'year': 2026, 'titles': [f'Movie {media_id}']},
        'identifiers': {'imdb': f'tt{media_id}'},
    }
    if watched:
        media.update({
            'watched': True,
            'watched_at': '2026-05-09T01:00:00Z',
            'watched_by': 'Scott',
            'watched_source': 'manual',
        })
    return media


def test_mark_watched_records_watch_metadata_without_changing_media_status():
    """markWatched sets watch fields but preserves existing media status."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    movie = make_media('movie-1', status='active')
    db = MagicMock()
    db.get.return_value = movie

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
         patch('couchpotato.core.media._base.media.main.fireEvent') as fire_event:
        result = plugin.markWatched(id='movie-1', watched_by='Scott')

    assert result['success'] is True
    assert result['media'] is movie
    assert movie['status'] == 'active'
    assert movie['watched'] is True
    assert movie['watched_by'] == 'Scott'
    assert movie['watched_source'] == 'manual'
    assert movie['watched_at'].endswith('Z')
    db.update.assert_called_once_with(movie)
    fire_event.assert_called_once_with('notify.frontend', type='movie.update', data=movie)


def test_mark_unwatched_clears_watch_metadata_without_changing_media_status():
    """markUnwatched removes watch fields but preserves existing media status."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    movie = make_media('movie-1', watched=True, status='done')
    db = MagicMock()
    db.get.return_value = movie

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
         patch('couchpotato.core.media._base.media.main.fireEvent'):
        result = plugin.markUnwatched(id='movie-1')

    assert result['success'] is True
    assert movie['status'] == 'done'
    assert movie['watched'] is False
    assert 'watched_at' not in movie
    assert 'watched_by' not in movie
    assert 'watched_source' not in movie
    db.update.assert_called_once_with(movie)


def test_list_can_filter_watched_movies():
    """media.list accepts watched=True and returns only watched media."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    watched = make_media('movie-a', watched=True)
    unwatched = make_media('movie-b', watched=False)

    with patch('couchpotato.core.media._base.media.main.get_db') as mock_db, \
         patch('couchpotato.core.media._base.media.main.fireEvent') as mock_fire:
        db = MagicMock()
        mock_db.return_value = db
        db.get_many.side_effect = lambda index, key=None: (
            [{'_id': 'movie-a'}, {'_id': 'movie-b'}] if index == 'media_by_type'
            else [{'_id': 'movie-a'}] if index == 'media_watched' and key is True
            else []
        )
        db.all.return_value = [{'_id': 'movie-a'}, {'_id': 'movie-b'}]

        def fire_side_effect(event, *args, **kwargs):
            if event == 'media.get':
                return watched if args[0] == 'movie-a' else unwatched
            return []

        mock_fire.side_effect = fire_side_effect

        total, movies = plugin.list(types=['movie'], watched=True)

    assert total == 1
    assert movies == [watched]


def test_watch_history_lists_watched_movies_newest_first():
    """watchHistory returns watched media sorted by watched_at descending."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    older = make_media('old', watched=True)
    older['watched_at'] = '2026-05-01T10:00:00Z'
    newer = make_media('new', watched=True)
    newer['watched_at'] = '2026-05-09T10:00:00Z'

    with patch.object(plugin, 'list', return_value=(2, [older, newer])) as list_media:
        result = plugin.watchHistory()

    assert result['success'] is True
    assert result['total'] == 2
    assert [movie['_id'] for movie in result['movies']] == ['new', 'old']
    list_media.assert_called_once_with(types=['movie'], watched=True)
