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
import threading
import time
from unittest.mock import patch

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
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

    def test_race_loss_preserves_winners_profile_not_losing_calls(self):
        """PR #152 review: when this add() LOSES the insert race, it must
        preserve the WINNER's profile_id (the just-inserted movie's), exactly
        as a genuine 'found' re-add does -- not stomp it with this (losing)
        call's params/default profile.

        A genuine found re-add validates the existing doc's profile and stashes
        it in previous_profile so the force_readd branch keeps it. The race-loss
        re-fetch branch must do the same; otherwise two concurrent add()s with
        different profile_ids let the loser overwrite the winner's profile.
        """

        class _RacingProfileFakeDB:
            def __init__(self, winner_doc, valid_profile_id):
                self.winner_doc = winner_doc
                self.valid_profile_id = valid_profile_id
                self.lookup_calls = 0
                self.updated = []

            def get(self, index, key, with_doc=False):
                if index == 'media':
                    self.lookup_calls += 1
                    if self.lookup_calls == 1:
                        raise KeyError('not found yet')
                    return {'doc': dict(self.winner_doc), '_id': self.winner_doc['_id']}
                if index == 'id':
                    # The winner's profile resolves to a real profile doc;
                    # anything else (e.g. the losing call's profile) is absent.
                    if key == self.valid_profile_id:
                        return {'_id': key, '_t': 'profile'}
                    raise KeyError('no profile: %s' % key)
                raise KeyError('not found: %s/%s' % (index, key))

            def insert(self, data):
                raise sqlite3.IntegrityError(
                    'UNIQUE constraint failed: media_identifiers.provider, media_identifiers.identifier'
                )

            def update(self, data):
                self.updated.append(dict(data))
                return {'_id': data['_id'], '_rev': 'rev2'}

            def delete(self, data):
                return True

        winner_doc = {
            '_id': 'winner-media-id',
            '_t': 'media',
            'type': 'movie',
            'status': 'active',
            'profile_id': 'profile-A',   # the winner's profile
            'category_id': None,
            'identifiers': {'imdb': 'tt0133093'},
            'info': {'titles': ['The Matrix']},
            'tags': [],
        }
        fake_db = _RacingProfileFakeDB(winner_doc, valid_profile_id='profile-A')

        plugin = MovieBase.__new__(MovieBase)
        plugin.conf = lambda *a, **k: False

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
                # The LOSING call passes a DIFFERENT profile.
                params=_base_params(profile_id='profile-B'),
                force_readd=True,
                search_after=False,
                update_after=False,
                notify_after=False,
            )

        assert result is not False
        assert fake_db.updated, "force_readd should have persisted the movie via db.update"
        assert fake_db.updated[-1]['profile_id'] == 'profile-A', (
            "race-loss must preserve the winner's profile (profile-A), not "
            "overwrite it with the losing call's profile (profile-B)"
        )

    def test_real_threads_racing_add_same_imdb_produce_one_doc(self, tmp_path):
        """REG-004 review: real threads calling MovieBase.add() concurrently
        against a real SQLiteAdapter for the same imdb id must produce exactly
        ONE media doc, with no exception surfacing.

        This is the end-to-end guarantee of the two layers working together:
        media_lock serializes the get-or-insert critical section, and the
        UNIQUE (provider, identifier) backstop absorbs the residual window
        where a late thread's SELECT on the shared SQLite connection hasn't
        yet observed the winner's just-committed row (a real shared-connection
        read-visibility race). The lock's serialization is proven in isolation
        by test_media_lock_serializes_add_without_db_backstop below.
        """
        adapter = SQLiteAdapter()
        adapter.create(str(tmp_path / 'race_db'))

        plugin = MovieBase.__new__(MovieBase)
        # search_on_add lookup must not touch real settings.
        plugin.conf = lambda *a, **k: False

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                return []
            if event == 'media.get':
                return {'_id': args[0], 'title': 'The Matrix'}
            return None

        params = {
            'identifier': 'tt0133093',
            'info': {'titles': ['The Matrix'], 'title': 'The Matrix'},
            'profile_id': 'profile-1',
        }

        n_threads = 4
        barrier = threading.Barrier(n_threads)
        errors = []

        def worker():
            barrier.wait()  # maximize real contention on the critical section
            try:
                plugin.add(
                    params=dict(params),
                    force_readd=True,
                    search_after=False,
                    update_after=False,
                    notify_after=False,
                )
            except Exception as e:  # noqa: BLE001 - surface any thread failure
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        with (
            patch('couchpotato.core.media.movie._base.main.get_db', return_value=adapter),
            patch('couchpotato.core.media.movie._base.main.fireEvent', side_effect=fake_fire_event),
        ):
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

        try:
            assert not errors, f"add() raised under concurrency: {errors}"
            assert all(not t.is_alive() for t in threads), "a thread hung"

            media_docs = [d for d in adapter.all('id') if d.get('_t') == 'media']
            assert len(media_docs) == 1, (
                f"expected exactly one media doc, got {len(media_docs)}"
            )
        finally:
            adapter.close()

    def test_media_lock_serializes_add_without_db_backstop(self):
        """REG-004 review: prove media_lock ALONE serializes the get-or-insert,
        independent of the DB-level UNIQUE backstop.

        Uses an in-memory DB with instantly-consistent reads and NO uniqueness
        enforcement, whose insert() sleeps to widen the race window. If the
        lock serializes the critical section, only the first of N racing
        threads ever reaches insert (the rest find the doc), so there is
        exactly one insert and one media doc. Without the lock, every thread
        would miss during the sleep and insert, yielding N docs -- so this
        test would fail, isolating the lock's contribution.
        """

        class _ConsistentFakeDB:
            def __init__(self, insert_delay=0.05):
                self._docs = {}       # _id -> doc
                self._by_imdb = {}    # imdb -> _id
                self._lock = threading.Lock()
                self.insert_delay = insert_delay
                self.inserts = 0
                self._counter = 0

            def get(self, index, key, with_doc=False):
                if index == 'media':
                    imdb = key.split('-', 1)[1] if '-' in key else key
                    with self._lock:
                        _id = self._by_imdb.get(imdb)
                    if _id is None:
                        raise KeyError(key)
                    return {'doc': dict(self._docs[_id]), '_id': _id}
                if index == 'id':
                    with self._lock:
                        if key in self._docs:
                            return dict(self._docs[key])
                    raise KeyError(key)
                raise KeyError(key)

            def insert(self, data):
                # Widen the get->insert window so a broken lock would let a
                # second thread miss and also insert.
                time.sleep(self.insert_delay)
                with self._lock:
                    self.inserts += 1
                    self._counter += 1
                    _id = 'media-%d' % self._counter
                    doc = dict(data)
                    doc['_id'] = _id
                    doc['_rev'] = 'r1'
                    self._docs[_id] = doc  # NO uniqueness enforcement
                    imdb = data.get('identifiers', {}).get('imdb')
                    if imdb:
                        self._by_imdb.setdefault(imdb, _id)
                    return {'_id': _id, '_rev': 'r1'}

            def update(self, data):
                with self._lock:
                    self._docs[data['_id']] = dict(data)
                return {'_id': data['_id'], '_rev': 'r2'}

            def media_count(self):
                with self._lock:
                    return sum(1 for d in self._docs.values() if d.get('_t') == 'media')

        fake_db = _ConsistentFakeDB()

        plugin = MovieBase.__new__(MovieBase)
        plugin.conf = lambda *a, **k: False

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                return []
            if event == 'media.get':
                return {'_id': args[0], 'title': 'The Matrix'}
            return None

        params = {
            'identifier': 'tt0133093',
            'info': {'titles': ['The Matrix'], 'title': 'The Matrix'},
            'profile_id': 'profile-1',
        }

        n_threads = 4
        barrier = threading.Barrier(n_threads)
        errors = []

        def worker():
            barrier.wait()
            try:
                plugin.add(
                    params=dict(params),
                    force_readd=True,
                    search_after=False,
                    update_after=False,
                    notify_after=False,
                )
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        with (
            patch('couchpotato.core.media.movie._base.main.get_db', return_value=fake_db),
            patch('couchpotato.core.media.movie._base.main.fireEvent', side_effect=fake_fire_event),
        ):
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

        assert not errors, f"add() raised under concurrency: {errors}"
        assert fake_db.inserts == 1, (
            "media_lock must serialize the get-or-insert so only the first "
            f"thread inserts; got {fake_db.inserts} inserts (lock not working)"
        )
        assert fake_db.media_count() == 1
