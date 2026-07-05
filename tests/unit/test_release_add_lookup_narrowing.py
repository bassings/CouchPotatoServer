"""Regression tests for the narrowed lookup excepts in release.add() (REG-004).

release.add() has two get-or-create sites:
  - media lookup   (~line 147): db.get('media', ...) -> movie.add() on miss
  - release lookup (~line 181): db.get('release_identifier', ...) -> insert on miss

Both excepts were narrowed from a bare `except Exception:` to
`except (RecordNotFound, KeyError):`. This locks in that behavior:

  - a GENUINE not-found (RecordNotFound/KeyError) still falls through to the
    create path (movie.add / db.insert), and
  - a DIFFERENT error (e.g. a transient sqlite3.OperationalError) is NOT
    mistaken for "not found" -- it is no longer swallowed into the create
    path (which could mask a real DB error and spawn duplicates); it
    propagates to add()'s outer handler, which logs and returns False without
    creating anything.
"""
import sqlite3
from unittest.mock import patch

import pytest

from CodernityDB.database import RecordNotFound
from couchpotato.core.plugins.release.main import Release


def _group():
    return {
        'identifier': 'tt0133093',
        'meta_data': {
            'audio': 'DTS',
            'quality': {'identifier': '720p', 'is_3d': 0},
        },
        'files': {'movie': ['/media/The Matrix.mkv']},
    }


class _FakeDB:
    def __init__(self, media_error=None, release_error=None):
        self.media_error = media_error
        self.release_error = release_error
        self.inserted = []
        self.updated = []

    def get(self, index, key, with_doc=False):
        if index == 'media':
            if self.media_error is not None:
                raise self.media_error
            return {'doc': {'_id': 'media-1'}, '_id': 'media-1'}
        if index == 'release_identifier':
            if self.release_error is not None:
                raise self.release_error
            return {'doc': {'_id': 'rel-1', '_rev': 'r1', 'media_id': 'media-1'},
                    '_id': 'rel-1'}
        raise KeyError('unexpected index: %s/%s' % (index, key))

    def insert(self, data):
        self.inserted.append(dict(data))
        return {'_id': 'rel-new', '_rev': 'r1'}

    def update(self, data):
        self.updated.append(dict(data))
        return {'_id': data.get('_id', 'x'), '_rev': 'r2'}


def _make_fire_event(recorder):
    def fire_event(event, *args, **kwargs):
        recorder.append(event)
        if event == 'movie.add':
            return {'_id': 'media-1'}
        if event == 'media.restatus':
            return None
        return None
    return fire_event


def _run_add(fake_db):
    plugin = Release.__new__(Release)
    events = []
    with (
        patch('couchpotato.core.plugins.release.main.get_db', return_value=fake_db),
        patch('couchpotato.core.plugins.release.main.fireEvent',
              side_effect=_make_fire_event(events)),
    ):
        result = plugin.add(_group())
    return result, events


class TestReleaseAddMediaLookupNarrowing:
    def test_genuine_miss_falls_through_to_movie_add(self):
        """A real not-found on the media lookup creates the movie via
        movie.add() and the release proceeds."""
        fake_db = _FakeDB(media_error=KeyError('not found'))
        result, events = _run_add(fake_db)

        assert result is True
        assert 'movie.add' in events, "genuine miss must fall through to movie.add"

    def test_recordnotfound_miss_falls_through_to_movie_add(self):
        """RecordNotFound (the CodernityDB backend's miss signal) behaves the
        same as KeyError."""
        fake_db = _FakeDB(media_error=RecordNotFound('not found'))
        result, events = _run_add(fake_db)

        assert result is True
        assert 'movie.add' in events

    def test_non_miss_error_is_not_swallowed_as_missing(self):
        """A DIFFERENT error (transient OperationalError) must NOT be treated
        as 'movie missing': movie.add() is never fired and add() returns False
        (the error propagates to the outer handler)."""
        fake_db = _FakeDB(media_error=sqlite3.OperationalError('database is locked'))
        result, events = _run_add(fake_db)

        assert result is False
        assert 'movie.add' not in events, (
            "an unexpected DB error must not be mistaken for 'not found' and "
            "trigger a spurious movie.add() (would mask the error / duplicate)"
        )
        assert fake_db.inserted == []


class TestReleaseAddReleaseLookupNarrowing:
    def test_genuine_miss_falls_through_to_insert(self):
        """A real not-found on the release lookup inserts a new release."""
        fake_db = _FakeDB(release_error=KeyError('not found'))
        result, events = _run_add(fake_db)

        assert result is True
        assert len(fake_db.inserted) == 1, "genuine miss must insert a new release"

    def test_non_miss_error_is_not_swallowed_as_missing(self):
        """A DIFFERENT error on the release lookup must NOT be treated as
        'release missing': no insert happens and add() returns False."""
        fake_db = _FakeDB(release_error=sqlite3.OperationalError('database is locked'))
        result, events = _run_add(fake_db)

        assert result is False
        assert fake_db.inserted == [], (
            "an unexpected DB error must not be mistaken for 'not found' and "
            "trigger a spurious release insert (would mask the error / duplicate)"
        )
