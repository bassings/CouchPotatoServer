"""Integration tests for duplicate movie detection during library refresh.

Reproduces the bug where CouchPotatoServer creates duplicate movie entries
after a database upgrade/migration + library refresh.

Root cause identified in SQLiteAdapter._query_index (sqlite_adapter.py):

  Bug 1 — 'media' index lookup ignores the key:
    The lookup `db.get('media', 'imdb-tt12345')` overwrites both the SQL
    and the params list, so it returns ALL media docs regardless of the key.
    With limit=1, it always returns the first media document in the database.
    This causes release.add() to link releases to the wrong movie, and
    movie.add() to overwrite an existing movie record with a different movie's
    data — creating duplicate IMDb entries.

  Bug 2 — 'release_identifier' index not handled:
    `db.get('release_identifier', ...)` falls through to the generic case,
    which returns ALL documents (limit=1 = first doc, of any type). When the
    first doc happens to be a media record, that record gets overwritten with
    release data. When the first doc is an existing release (coincidentally),
    the wrong release is updated. The "insert new release" branch is never
    reached, so duplicate releases accumulate on repeated scans.

Production symptom: 77 duplicate movie entries after migration + library
refresh, each duplicate with the same IMDb ID, where Entry A has 2 releases
with the same file path listed twice, and Entry B has 1 correct release.
"""
import json
import os
import sys
import time

import pytest

# Ensure repo root is importable
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
LIBS_PATH = os.path.join(REPO_ROOT, 'libs')
if LIBS_PATH not in sys.path:
    sys.path.insert(0, LIBS_PATH)

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_movie(imdb_id, title, status='done'):
    """Return a minimal media document dict."""
    return {
        '_t': 'media',
        'type': 'movie',
        'title': title,
        'status': status,
        'identifiers': {'imdb': imdb_id},
        'info': {'titles': [title], 'year': 2020},
        'files': {},
        'tags': [],
        'last_edit': int(time.time()),
    }


def make_release(media_id, imdb_id, audio='DTS', quality='720p',
                 file_path='/media/movie.mkv'):
    """Return a minimal release document dict."""
    return {
        '_t': 'release',
        'media_id': media_id,
        'identifier': f'{imdb_id}.{audio}.{quality}',
        'quality': quality,
        'is_3d': 0,
        'last_edit': int(time.time()),
        'status': 'done',
        'files': {'movie': [file_path]},
    }


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite database for each test."""
    adapter = SQLiteAdapter()
    adapter.create(str(tmp_path / 'test_db'))
    yield adapter
    adapter.close()


# ---------------------------------------------------------------------------
# Bug 1: 'media' index lookup
# ---------------------------------------------------------------------------

class TestMediaIndexLookup:
    """db.get('media', 'imdb-XXXX') must return the correct movie."""

    def test_lookup_single_movie(self, db):
        """Basic lookup on a single-movie database returns that movie."""
        db.insert(make_movie('tt13320622', 'The Lost City'))
        result = db.get('media', 'imdb-tt13320622', with_doc=True)
        doc = result['doc']
        assert doc['identifiers']['imdb'] == 'tt13320622'
        assert doc['title'] == 'The Lost City'

    def test_lookup_raises_for_missing_id(self, db):
        """Should raise KeyError when the IMDb ID is not in the database."""
        db.insert(make_movie('tt5697572', 'Cats'))
        with pytest.raises(KeyError):
            db.get('media', 'imdb-tt9999999', with_doc=True)

    def test_lookup_correct_movie_among_many(self, db):
        """
        BUG REPRODUCTION — Bug 1.

        With multiple movies in the database, db.get('media', 'imdb-XXXX')
        must return the movie matching XXXX, NOT the first movie inserted.

        Before the fix, the SQL is overwritten to return ALL media docs and
        limit=1 silently returns the first one inserted — here 'Cats'.
        """
        # Insert in an order where the target is NOT first.
        for movie in [
            make_movie('tt5697572', 'Cats'),
            make_movie('tt3105662', 'Breaking the Bank'),
            make_movie('tt13320622', 'The Lost City'),
        ]:
            db.insert(movie)

        result = db.get('media', 'imdb-tt13320622', with_doc=True)
        doc = result['doc']

        assert doc['identifiers']['imdb'] == 'tt13320622', (
            f"Expected tt13320622 (The Lost City) but got "
            f"{doc['identifiers']['imdb']} ({doc['title']})"
        )
        assert doc['title'] == 'The Lost City'

    def test_each_imdb_id_returns_its_own_movie(self, db):
        """Looking up different IMDb IDs must return different movies."""
        db.insert(make_movie('tt5697572', 'Cats'))
        db.insert(make_movie('tt13320622', 'The Lost City'))

        cats = db.get('media', 'imdb-tt5697572', with_doc=True)['doc']
        lost = db.get('media', 'imdb-tt13320622', with_doc=True)['doc']

        assert cats['title'] == 'Cats'
        assert lost['title'] == 'The Lost City'
        assert cats['_id'] != lost['_id']


# ---------------------------------------------------------------------------
# Bug 2: 'release_identifier' index lookup
# ---------------------------------------------------------------------------

class TestReleaseIdentifierLookup:
    """db.get('release_identifier', ...) must find the right release."""

    def test_lookup_existing_release(self, db):
        """Basic lookup by release identifier returns the matching release."""
        movie = db.insert(make_movie('tt13320622', 'The Lost City'))
        db.insert(make_release(movie['_id'], 'tt13320622'))

        result = db.get('release_identifier', 'tt13320622.DTS.720p', with_doc=True)
        doc = result['doc']
        assert doc['_t'] == 'release'
        assert doc['identifier'] == 'tt13320622.DTS.720p'

    def test_lookup_raises_for_missing_identifier(self, db):
        """Should raise KeyError when no release has that identifier."""
        with pytest.raises(KeyError):
            db.get('release_identifier', 'tt9999999.AC3.1080p', with_doc=True)

    def test_lookup_does_not_return_media_doc(self, db):
        """
        BUG REPRODUCTION — Bug 2.

        When a media doc exists but NO matching release exists,
        db.get('release_identifier', ...) must raise KeyError — not return
        the media doc as if it were a release.

        Before the fix, the generic fallback returns the first document
        (the media doc), so the caller thinks a release was found and
        overwrites that media doc with release data.
        """
        db.insert(make_movie('tt13320622', 'The Lost City'))

        with pytest.raises(KeyError):
            db.get('release_identifier', 'tt13320622.DTS.720p', with_doc=True)

    def test_lookup_returns_correct_release_among_many(self, db):
        """With multiple releases, returns the one matching the identifier."""
        m1 = db.insert(make_movie('tt13320622', 'The Lost City'))
        m2 = db.insert(make_movie('tt5697572', 'Cats'))
        db.insert(make_release(m1['_id'], 'tt13320622', audio='DTS', quality='720p'))
        db.insert(make_release(m2['_id'], 'tt5697572', audio='AC3', quality='1080p'))

        r = db.get('release_identifier', 'tt5697572.AC3.1080p', with_doc=True)['doc']
        assert r['identifier'] == 'tt5697572.AC3.1080p'
        assert r['media_id'] == m2['_id']


# ---------------------------------------------------------------------------
# Integration: simulate release.add() logic
# ---------------------------------------------------------------------------

class TestDuplicateDetectionAfterLibraryScan:
    """
    Simulate the library-scan code path from release/main.py:add() without
    loading the full CouchPotato event system.

    This is the code path that triggers both bugs in production.
    """

    # ------------------------------------------------------------------
    # Helpers that mirror release.add() and movie.add() core logic
    # ------------------------------------------------------------------

    def _simulate_release_add(self, db, imdb_id, title, audio, quality, file_path):
        """
        Mirror the critical duplicate-prevention logic of release/main.py:add().

        Step 1 (media lookup) — uses db.get('media', 'imdb-{id}') [Bug 1 site]
        Step 2 (release lookup) — uses db.get('release_identifier', ...) [Bug 2 site]
        """
        release_identifier = f'{imdb_id}.{audio}.{quality}'

        # --- Step 1: find or create media ---
        try:
            media = db.get('media', f'imdb-{imdb_id}', with_doc=True)['doc']
        except KeyError:
            ref = db.insert(make_movie(imdb_id, title))
            media = db.get('id', ref['_id'])

        media_id = media['_id']

        # --- Step 2: find or create release ---
        release_doc = {
            '_t': 'release',
            'media_id': media_id,
            'identifier': release_identifier,
            'quality': quality,
            'is_3d': 0,
            'last_edit': int(time.time()),
            'status': 'done',
            'files': {'movie': [file_path]},
        }

        try:
            existing = db.get('release_identifier', release_identifier, with_doc=True)['doc']
            existing['media_id'] = media_id
            existing['files'] = {'movie': [file_path]}
            db.update(existing)
        except KeyError:
            db.insert(release_doc)

        return media_id

    def _movie_count_for_imdb(self, db, imdb_id):
        conn = db._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM media_identifiers WHERE provider='imdb' AND identifier=?",
            (imdb_id,)
        ).fetchone()
        return row[0]

    def _release_count_for_identifier(self, db, identifier):
        conn = db._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM documents "
            "WHERE _t='release' AND json_extract(data,'$.identifier')=?",
            (identifier,)
        ).fetchone()
        return row[0]

    def _all_movies(self, db):
        conn = db._get_conn()
        rows = conn.execute(
            "SELECT _id, data FROM documents WHERE _t='media'"
        ).fetchall()
        return [(r['_id'], json.loads(r['data'])) for r in rows]

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_single_scan_creates_one_movie_one_release(self, db):
        """First-time scan of a movie creates exactly 1 media + 1 release."""
        self._simulate_release_add(
            db, 'tt13320622', 'The Lost City', 'DTS', '720p',
            '/media/TheLostCity.mkv'
        )
        assert self._movie_count_for_imdb(db, 'tt13320622') == 1
        assert self._release_count_for_identifier(db, 'tt13320622.DTS.720p') == 1

    def test_second_scan_no_duplicate_movie(self, db):
        """
        BUG REPRODUCTION.

        Running the library scan twice (as happens after a migration) must
        NOT create a second media entry for the same IMDb ID.

        Without the fix: the 'media' lookup returns the first doc (or wrong
        doc), causing movie.add() to create a brand-new record — duplicating
        the movie.
        """
        for _ in range(2):
            self._simulate_release_add(
                db, 'tt13320622', 'The Lost City', 'DTS', '720p',
                '/media/TheLostCity.mkv'
            )

        count = self._movie_count_for_imdb(db, 'tt13320622')
        assert count == 1, (
            f"DUPLICATE DETECTED: {count} entries for tt13320622 after second scan. "
            "Bug 1 in SQLiteAdapter._query_index('media') is active."
        )

    def test_second_scan_no_duplicate_release(self, db):
        """
        BUG REPRODUCTION.

        Running the library scan twice must NOT create a second release with
        the same identifier.  This reproduces the 'Entry A: same file path
        listed twice' pattern from the production bug report.
        """
        for _ in range(2):
            self._simulate_release_add(
                db, 'tt13320622', 'The Lost City', 'DTS', '720p',
                '/media/TheLostCity.mkv'
            )

        count = self._release_count_for_identifier(db, 'tt13320622.DTS.720p')
        assert count == 1, (
            f"DUPLICATE RELEASE: {count} releases for tt13320622.DTS.720p after second scan. "
            "Bug 2 in SQLiteAdapter._query_index('release_identifier') is active."
        )

    def test_multiple_movies_no_cross_contamination(self, db):
        """
        BUG REPRODUCTION.

        With multiple existing movies, scanning a new movie must NOT link its
        release to a different (first-in-DB) movie.

        Before the fix, 'Cats' (inserted first) would receive the release
        that belongs to 'The Lost City' because the 'media' lookup always
        returns the first media doc.
        """
        cats_ref = db.insert(make_movie('tt5697572', 'Cats'))
        cats_id = cats_ref['_id']

        lost_city_media_id = self._simulate_release_add(
            db, 'tt13320622', 'The Lost City', 'DTS', '720p',
            '/media/TheLostCity.mkv'
        )

        # The Lost City must have its own entry
        assert self._movie_count_for_imdb(db, 'tt13320622') == 1
        # Cats must be untouched
        assert self._movie_count_for_imdb(db, 'tt5697572') == 1

        # The release must be linked to The Lost City, NOT Cats
        conn = db._get_conn()
        row = conn.execute(
            "SELECT data FROM documents WHERE _t='release' "
            "AND json_extract(data,'$.identifier')='tt13320622.DTS.720p'"
        ).fetchone()
        assert row is not None, "Release for The Lost City should exist"
        release_data = json.loads(row['data'])
        assert release_data['media_id'] != cats_id, (
            "Release is wrongly linked to Cats — Bug 1 is active"
        )
        assert release_data['media_id'] == lost_city_media_id, (
            "Release must be linked to The Lost City"
        )

    def test_post_migration_77_movie_scenario(self, db):
        """
        Regression: simulate the production N-movie post-migration scenario.

        Scanning N distinct movies twice must produce exactly N unique
        movie entries and N unique release entries — zero duplicates.
        """
        CATALOG = [
            ('tt13320622', 'The Lost City',      '/media/TheLostCity.mkv'),
            ('tt5697572',  'Cats',               '/media/Cats.mkv'),
            ('tt3105662',  'Breaking the Bank',  '/media/BreakingTheBank.mkv'),
            ('tt4154796',  'Avengers: Endgame',  '/media/AvengersEndgame.mkv'),
            ('tt0468569',  'The Dark Knight',    '/media/DarkKnight.mkv'),
        ]

        # Scan 1: initial library scan (or post-migration state)
        for imdb_id, title, path in CATALOG:
            self._simulate_release_add(db, imdb_id, title, 'DTS', '720p', path)

        # Scan 2: post-migration library refresh
        for imdb_id, title, path in CATALOG:
            self._simulate_release_add(db, imdb_id, title, 'DTS', '720p', path)

        for imdb_id, title, _ in CATALOG:
            movie_count = self._movie_count_for_imdb(db, imdb_id)
            release_count = self._release_count_for_identifier(
                db, f'{imdb_id}.DTS.720p'
            )
            assert movie_count == 1, (
                f"DUPLICATE MOVIE: '{title}' ({imdb_id}) has {movie_count} entries"
            )
            assert release_count == 1, (
                f"DUPLICATE RELEASE: '{title}' ({imdb_id}) has {release_count} releases"
            )

    def test_existing_db_movies_plus_new_scan(self, db):
        """
        Simulate the exact production migration scenario:
        movies already exist in DB (from migration), then library refresh runs.
        """
        # Pre-populate DB (this represents the migrated data)
        for movie in [
            make_movie('tt5697572', 'Cats'),
            make_movie('tt3105662', 'Breaking the Bank'),
            make_movie('tt13320622', 'The Lost City'),
        ]:
            db.insert(movie)

        # Library refresh runs — scanner finds all three on disk
        for imdb_id, title, path in [
            ('tt5697572',  'Cats',              '/media/Cats.mkv'),
            ('tt3105662',  'Breaking the Bank', '/media/BTB.mkv'),
            ('tt13320622', 'The Lost City',     '/media/TLC.mkv'),
        ]:
            self._simulate_release_add(db, imdb_id, title, 'DTS', '720p', path)

        # No duplicates anywhere
        all_movies = self._all_movies(db)
        imdb_ids_seen = [
            json.loads(
                db._get_conn().execute(
                    "SELECT mi.identifier FROM media_identifiers mi WHERE mi.media_id=?",
                    (mid,)
                ).fetchone()[0]  # type: ignore[index]
            )
            if False else
            db._get_conn().execute(
                "SELECT mi.identifier FROM media_identifiers mi "
                "WHERE mi.media_id=? AND mi.provider='imdb'",
                (mid,)
            ).fetchone()[0]
            for mid, _ in all_movies
        ]

        # Each IMDb ID must appear exactly once
        from collections import Counter
        counts = Counter(imdb_ids_seen)
        for imdb_id, count in counts.items():
            assert count == 1, (
                f"IMDb ID {imdb_id} appears {count} times — DUPLICATE"
            )
