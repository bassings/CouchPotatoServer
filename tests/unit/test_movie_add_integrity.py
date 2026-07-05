"""Regression tests for REG-004 (P0 data-integrity fixes) in movie.add().

Covers:
  - the `rel['status'] is 'available'` identity-comparison bug (never true
    for a JSON-deserialized status string, so stale available releases were
    never cleaned up on re-add).
  - the get-or-insert insert race: movie.add() must not create a duplicate
    media doc when it loses a concurrent insert race for the same IMDb id
    (the unique (provider, identifier) index on media_identifiers raises
    sqlite3.IntegrityError in that case; movie.add() must catch it and
    re-fetch the winner's doc instead of failing or duplicating).
"""
import json
import sqlite3
from unittest.mock import patch

from couchpotato.core.media.movie._base.main import MovieBase


def _base_params(imdb_id='tt0133093', profile_id='profile-1'):
    return {
        'identifier': imdb_id,
        'info': {'titles': ['The Matrix'], 'title': 'The Matrix'},
        'profile_id': profile_id,
    }


class _FakeDB:
    """Minimal db double for an *existing* media doc (the "found" branch)."""

    def __init__(self, existing):
        self.existing = existing
        self.deleted = []
        self.updated = []

    def get(self, index, key, with_doc=False):
        if index == 'media' and self.existing is not None:
            return {'doc': dict(self.existing), '_id': self.existing['_id']}
        raise KeyError('not found: %s/%s' % (index, key))

    def update(self, data):
        self.updated.append(dict(data))
        return {'_id': data['_id'], '_rev': 'rev2'}

    def delete(self, data):
        self.deleted.append(data)
        return True


class _RacingFakeDB:
    """Simulates losing a concurrent movie.add() insert race: another
    thread/process inserts the same imdb id between our lookup and our
    insert, so our db.insert() hits the UNIQUE(provider, identifier) index.
    """

    def __init__(self, winner_doc):
        self.winner_doc = winner_doc
        self.insert_calls = 0
        self.lookup_calls = 0
        self.updated = []
        self.deleted = []

    def get(self, index, key, with_doc=False):
        if index == 'media':
            self.lookup_calls += 1
            if self.lookup_calls == 1:
                raise KeyError('not found yet')
            # Re-fetch after losing the insert race: the concurrent
            # insert has already landed.
            return {'doc': dict(self.winner_doc), '_id': self.winner_doc['_id']}
        raise KeyError('not found: %s/%s' % (index, key))

    def insert(self, data):
        self.insert_calls += 1
        raise sqlite3.IntegrityError(
            'UNIQUE constraint failed: media_identifiers.provider, media_identifiers.identifier'
        )

    def update(self, data):
        self.updated.append(dict(data))
        return {'_id': data['_id'], '_rev': 'rev2'}

    def delete(self, data):
        self.deleted.append(data)
        return True


def _fire_event_returning(releases, media_dict):
    def fake_fire_event(event, *args, **kwargs):
        if event == 'release.for_media':
            return releases
        if event == 'media.get':
            return media_dict
        raise AssertionError('Unexpected fireEvent: %r %r %r' % (event, args, kwargs))
    return fake_fire_event


class TestStaleAvailableReleaseCleanup:
    """The `is 'available'` bug (main.py:175 in add(), :229 in edit())."""

    def test_stale_available_release_deleted_on_readd(self):
        plugin = MovieBase.__new__(MovieBase)

        existing_media = {
            '_id': 'media-1',
            '_t': 'media',
            'type': 'movie',
            'status': 'active',
            'profile_id': None,
            'category_id': None,
            'identifiers': {'imdb': 'tt0133093'},
            'info': {'titles': ['The Matrix']},
            'tags': [],
        }

        # Mirror production: rel['status'] comes from json.loads() of the
        # stored document -- a freshly-allocated str, never the interned
        # 'available' literal that appears in the source code. This is
        # exactly why `is` silently never matches in practice.
        stale_release = json.loads('{"_id": "rel-1", "status": "available"}')

        fake_db = _FakeDB(existing=existing_media)

        with (
            patch('couchpotato.core.media.movie._base.main.get_db', return_value=fake_db),
            patch(
                'couchpotato.core.media.movie._base.main.fireEvent',
                side_effect=_fire_event_returning(
                    [stale_release], {'_id': 'media-1', 'title': 'The Matrix'}
                ),
            ),
        ):
            result = plugin.add(
                params=_base_params(),
                force_readd=True,
                search_after=False,
                update_after=False,
                notify_after=False,
            )

        assert result is not False
        assert fake_db.deleted == [stale_release], (
            "Stale 'available' release was not deleted -- the `is` identity "
            "comparison bug is active (should be `==`)"
        )


class TestMovieAddInsertRace:
    """The get-or-insert race: two movie.add() calls for the same imdb id."""

    def test_losing_insert_race_reuses_winner_doc_instead_of_duplicating(self):
        plugin = MovieBase.__new__(MovieBase)

        winner_doc = {
            '_id': 'winner-media-id',
            '_t': 'media',
            'type': 'movie',
            'status': 'active',
            'profile_id': None,
            'category_id': None,
            'identifiers': {'imdb': 'tt0133093'},
            'info': {'titles': ['The Matrix']},
            'tags': [],
        }
        fake_db = _RacingFakeDB(winner_doc)

        with (
            patch('couchpotato.core.media.movie._base.main.get_db', return_value=fake_db),
            patch(
                'couchpotato.core.media.movie._base.main.fireEvent',
                side_effect=_fire_event_returning(
                    [], {'_id': 'winner-media-id', 'title': 'The Matrix'}
                ),
            ),
        ):
            result = plugin.add(
                params=_base_params(),
                force_readd=True,
                search_after=False,
                update_after=False,
                notify_after=False,
            )

        assert result is not False, "add() should recover from the insert race, not fail"
        assert fake_db.insert_calls == 1, "must attempt the insert exactly once"
        assert fake_db.lookup_calls == 2, (
            "must re-fetch the doc the race winner inserted after catching "
            "IntegrityError, instead of giving up or duplicating"
        )
