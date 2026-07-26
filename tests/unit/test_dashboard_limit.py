"""The dashboard.soon / dashboard.late `limit_offset` parameter crashes.

`Dashboard.getSoonView()` narrows its result count with:

    splt = splitString(limit_offset) if isinstance(limit_offset, (str, unicode)) else limit_offset

`unicode` does not exist in Python 3, and the `isinstance()` call is evaluated
as soon as `limit_offset` is truthy -- so any caller passing the documented
parameter gets a NameError instead of a list of movies. Only the default
(no `limit_offset`) path ever worked.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.plugins.dashboard import Dashboard


def _media(media_id):
    return {
        '_id': media_id,
        '_t': 'movie',
        'title': 'Movie %s' % media_id,
        'profile_id': 'p1',
        'status': 'active',
        'info': {
            'year': time.gmtime().tm_year,
            'release_date': {'theater': int(time.time()) - 86400, 'dvd': 0},
        },
    }


def _run(limit_offset, count=5):
    """Drive getSoonView with `count` eligible movies."""
    dashboard = object.__new__(Dashboard)
    medias = {str(i): _media(str(i)) for i in range(count)}

    def fake_fire_event(name, *args, **kwargs):
        if name == 'profile.all':
            return [{'_id': 'p1', 'qualities': ['1080p', '720p']}]
        if name == 'quality.pre_releases':
            return ['cam', 'ts', 'tc', 'r5', 'scr']
        if name == 'media.with_status':
            return [{'_id': i} for i in medias]
        if name == 'movie.searcher.could_be_released':
            return True
        if name == 'release.for_media':
            return []
        return None

    db = MagicMock()
    db.all.return_value = [{'_id': i} for i in medias]
    db.get.side_effect = lambda _index, media_id: medias[media_id]

    with patch('couchpotato.core.plugins.dashboard.get_db', return_value=db), \
            patch('couchpotato.core.plugins.dashboard.fireEvent', side_effect=fake_fire_event):
        return dashboard.getSoonView(limit_offset=limit_offset)


class TestLimitOffset:

    def test_string_limit_does_not_raise(self):
        """Bug repro: `dashboard.soon?limit_offset=2` is the documented API
        shape and raised NameError on `unicode`."""
        result = _run('2')

        assert len(result['movies']) == 2

    def test_comma_separated_limit_and_offset(self):
        """splitString() exists to handle the 'limit,offset' form; only the
        limit is consumed today."""
        result = _run('3,10')

        assert len(result['movies']) == 3

    def test_list_limit_is_accepted(self):
        """The non-string branch: a caller may pass an already-split list."""
        result = _run(['2', '0'])

        assert len(result['movies']) == 2

    def test_default_limit_is_unchanged(self):
        """Regression guard: the no-parameter path was the only one that
        worked, and must keep working (default limit is 12)."""
        result = _run(None, count=20)

        assert len(result['movies']) == 12

    @pytest.mark.parametrize('bad', ['abc', ''])
    def test_junk_limit_does_not_crash(self, bad):
        """tryInt() yields 0 for junk. Whatever the resulting count, the view
        must answer rather than raise -- this is a public API surface."""
        result = _run(bad)

        assert 'movies' in result
