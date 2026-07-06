"""Tests for the SQLite database adapter."""
import json
import logging
import os
import sqlite3
import tempfile
import threading
import time

import pytest

from couchpotato.core.db.sqlite_adapter import ConflictError, SQLiteAdapter


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


class TestSQLiteAdapterCompareAndSwap:
    """Tests for optimistic-concurrency (CAS on `_rev`) in update().

    Closes the read-modify-write race flagged in the 2026-07 audit: two
    concurrent read-modify-write cycles on the same document must not
    silently clobber each other (lost update).
    """

    def test_update_with_correct_rev_succeeds_and_bumps_rev(self, db, sample_media):
        inserted = db.insert(sample_media)
        doc = db.get('id', inserted['_id'])
        assert doc['_rev'] == inserted['_rev']

        doc['status'] = 'done'
        update_result = db.update(doc)

        assert update_result['_rev'] != inserted['_rev']
        updated = db.get('id', inserted['_id'])
        assert updated['status'] == 'done'
        assert updated['_rev'] == update_result['_rev']

    def test_stale_rev_raises_conflict_and_does_not_clobber(self, db, sample_media):
        inserted = db.insert(sample_media)

        # Two readers both fetch the same doc at rev A.
        reader_a = db.get('id', inserted['_id'])
        reader_b = db.get('id', inserted['_id'])
        assert reader_a['_rev'] == reader_b['_rev'] == inserted['_rev']

        # Reader B writes first (concurrent write), advancing to rev B.
        reader_b['status'] = 'snatched'
        winner_result = db.update(reader_b)
        assert winner_result['_rev'] != inserted['_rev']

        # Reader A, still holding the stale rev-A copy, tries to write.
        reader_a['status'] = 'done'
        with pytest.raises(ConflictError) as excinfo:
            db.update(reader_a)
        assert inserted['_id'] in str(excinfo.value)
        assert excinfo.value._id == inserted['_id']

        # The doc must retain reader B's (winning) value -- no clobber.
        current = db.get('id', inserted['_id'])
        assert current['status'] == 'snatched'
        assert current['_rev'] == winner_result['_rev']

    def test_update_missing_id_still_raises_keyerror(self, db):
        with pytest.raises(KeyError):
            db.update({'_id': 'nonexistent', '_t': 'media', 'title': 'X', '_rev': 'deadbeef'})

    def test_update_without_rev_falls_back_to_unconditional_update(self, db, sample_media):
        """Backward-compat: callers that build a fresh dict without a _rev
        (no CAS context available) must still be able to update -- but the
        write is unconditional (last-writer-wins), matching pre-CAS
        behaviour, for compatibility with existing call sites."""
        inserted = db.insert(sample_media)

        # No `_rev` key at all -- simulates a caller-constructed dict.
        stale_free_update = {'_id': inserted['_id'], '_t': 'media', 'title': 'The Matrix Reloaded'}
        assert '_rev' not in stale_free_update

        result = db.update(stale_free_update)
        assert result['_rev'] != inserted['_rev']

        updated = db.get('id', inserted['_id'])
        assert updated['title'] == 'The Matrix Reloaded'

    def test_update_without_rev_overwrites_concurrent_change_last_writer_wins(self, db, sample_media):
        """Documents the deliberate trade-off: skipping `_rev` means no CAS
        protection at all, so a concurrent change IS clobbered. This is why
        callers should prefer passing `_rev` (via get()) or update_with_retry."""
        inserted = db.insert(sample_media)

        # Someone else updates the doc first.
        concurrent = db.get('id', inserted['_id'])
        concurrent['status'] = 'snatched'
        db.update(concurrent)

        # A caller without a _rev blindly overwrites.
        db.update({'_id': inserted['_id'], '_t': 'media', 'title': 'Overwritten'})

        final = db.get('id', inserted['_id'])
        assert final['title'] == 'Overwritten'
        assert final.get('status') is None  # clobbered -- no CAS guard without _rev


class TestSQLiteAdapterUpdateWithRetry:
    """Tests for the update_with_retry() safe read-modify-write helper."""

    def test_converges_when_no_conflict(self, db, sample_media):
        inserted = db.insert(sample_media)

        def mutator(doc):
            doc['status'] = 'done'

        result = db.update_with_retry(mutator, inserted['_id'])

        assert result['status'] == 'done'
        assert result['_rev'] != inserted['_rev']

    def test_converges_after_a_single_conflict(self, db, sample_media):
        inserted = db.insert(sample_media)
        attempts = {'count': 0}
        real_update = db.update

        def flaky_update(data):
            attempts['count'] += 1
            if attempts['count'] == 1:
                # Simulate a concurrent writer sneaking in between the
                # mutator's read and this update() call, on the first
                # attempt only.
                concurrent = db.get('id', inserted['_id'])
                concurrent['status'] = 'snatched'
                real_update(concurrent)
            return real_update(data)

        db.update = flaky_update
        try:
            def mutator(doc):
                doc['status'] = 'done'

            result = db.update_with_retry(mutator, inserted['_id'], retries=3)
        finally:
            db.update = real_update

        assert result['status'] == 'done'
        assert attempts['count'] == 2  # first attempt conflicted, second succeeded

        final = db.get('id', inserted['_id'])
        assert final['status'] == 'done'

    def test_raises_conflict_after_exhausting_retries(self, db, sample_media):
        inserted = db.insert(sample_media)
        real_update = db.update

        def always_conflicting_update(data):
            # Every attempt: a concurrent writer changes the doc first,
            # so the caller's rev is always stale by the time it writes.
            concurrent = db.get('id', inserted['_id'])
            concurrent['status'] = 'churning'
            real_update(concurrent)
            return real_update(data)

        db.update = always_conflicting_update
        try:
            def mutator(doc):
                doc['status'] = 'done'

            with pytest.raises(ConflictError):
                db.update_with_retry(mutator, inserted['_id'], retries=3)
        finally:
            db.update = real_update

    def test_missing_document_raises_keyerror(self, db):
        def mutator(doc):
            doc['status'] = 'done'

        with pytest.raises(KeyError):
            db.update_with_retry(mutator, 'nonexistent-id')


class TestSQLiteAdapterIndexQueries:
    def test_media_status_query(self, db, sample_media):
        db.insert(sample_media)
        # Distinct identifiers: two media docs can no longer share the same
        # (provider, identifier) pair (REG-004 unique index).
        sample2 = dict(sample_media, title='Inception', status='done',
                        identifiers={'imdb': 'tt1375666', 'tmdb': 27205})
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


class TestSQLiteAdapterUniqueMediaIdentifiers:
    """REG-004 (P0): (provider, identifier) must be unique across media docs.

    Regression coverage for the prod incident where a lookup race in
    movie.add() created 77 duplicate movie entries with the same IMDb id.
    """

    def test_duplicate_provider_identifier_raises_integrity_error(self, db, sample_media):
        db.insert(sample_media)

        duplicate = dict(sample_media)
        duplicate.pop('_id', None)
        with pytest.raises(sqlite3.IntegrityError):
            db.insert(duplicate)

    def test_failed_duplicate_insert_leaves_no_orphaned_document(self, db, sample_media):
        """An IntegrityError from the unique index must not leave a
        lingering, uncommitted 'documents' row behind -- otherwise a later,
        unrelated commit on the same connection could accidentally persist
        the half-inserted duplicate."""
        db.insert(sample_media)

        duplicate = dict(sample_media)
        duplicate.pop('_id', None)
        with pytest.raises(sqlite3.IntegrityError):
            db.insert(duplicate)

        assert len(list(db.all('id'))) == 1

        # A subsequent, unrelated insert must still work normally --
        # proves the connection wasn't left in a broken transaction state.
        other = {
            '_t': 'media',
            'status': 'active',
            'title': 'Unrelated Movie',
            'type': 'movie',
            'identifiers': {'imdb': 'tt9999999'},
            'info': {},
            'tags': [],
        }
        db.insert(other)
        assert len(list(db.all('id'))) == 2

    def test_concurrent_inserts_of_same_identifier_yield_one_media_doc(self, db, sample_media):
        """Simulated concurrent movie.add(): two threads race to insert a
        media doc for the same IMDb id. Exactly one must win; the loser
        must get IntegrityError (which movie.add() catches and re-fetches
        instead of duplicating -- see test_movie_add_integrity.py)."""
        results = {'ok': 0}
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            doc = dict(sample_media)
            try:
                db.insert(doc)
                results['ok'] += 1
            except sqlite3.IntegrityError as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert results['ok'] == 1
        assert len(errors) == 1

        media_docs = list(db.all('id'))
        assert len(media_docs) == 1

    def test_double_update_changing_identifiers_does_not_raise(self, db, sample_media):
        """REG-004 review: prove the double-update path is safe with the
        plain-INSERT denormalizer. update() DELETEs this doc's own
        media_identifiers rows before re-inserting, so updating the same doc
        repeatedly -- even changing its identifier on a later update -- must
        never trip the UNIQUE (provider, identifier) index on its own rows.
        """
        ref = db.insert(sample_media)

        # First update: identifiers unchanged (the self-collision candidate).
        doc = db.get('id', ref['_id'])
        doc['status'] = 'done'
        db.update(doc)

        # Second update: change the imdb identifier.
        doc = db.get('id', ref['_id'])
        doc['identifiers'] = {'imdb': 'tt7777777'}
        db.update(doc)

        updated = db.get('id', ref['_id'])
        assert updated['identifiers']['imdb'] == 'tt7777777'
        assert db.get_by_identifier('imdb', 'tt7777777')['_id'] == ref['_id']
        # The old identifier row must be gone (no orphan / no duplicate).
        with pytest.raises(KeyError):
            db.get_by_identifier('imdb', 'tt0133093')


def _make_legacy_sqlite_db(path, with_duplicate=False):
    """Build a *pre-REG-004*-shaped SQLite DB at ``path``: the media
    identifier index is the old NON-unique one. With ``with_duplicate`` the
    DB also contains two media docs claiming the same (imdb, tt1111111) pair
    -- exactly the corrupt state the prod incident left behind. The adapter
    is closed before returning so a fresh adapter can open() the path.
    """
    adapter = SQLiteAdapter()
    adapter.create(path)  # schema.sql builds the UNIQUE index...

    conn = adapter._get_conn()
    # ...downgrade it to the legacy non-unique index to mimic an old install.
    conn.execute("DROP INDEX idx_media_identifiers_lookup")
    conn.execute(
        "CREATE INDEX idx_media_identifiers_lookup "
        "ON media_identifiers(provider, identifier)"
    )
    conn.commit()
    assert not adapter._has_unique_identifier_index()

    adapter.insert({
        '_t': 'media', 'type': 'movie', 'status': 'active',
        'title': 'The Lost City', 'identifiers': {'imdb': 'tt1111111'},
        'info': {}, 'tags': [],
    })
    if with_duplicate:
        # A second, distinct media doc claiming the same identifier -- only
        # possible because the index is currently non-unique.
        adapter.insert({
            '_t': 'media', 'type': 'movie', 'status': 'active',
            'title': 'The Lost City (dup)', 'identifiers': {'imdb': 'tt1111111'},
            'info': {}, 'tags': [],
        })

    adapter.close()


class TestSQLiteAdapterExistingDbSelfUpgrade:
    """REG-004 review: open() must self-upgrade an existing install to the
    UNIQUE identifier index (open() never re-runs schema.sql), and must do so
    without ever bricking startup on a DB that still has duplicate rows."""

    def test_open_upgrades_clean_existing_db_to_unique_index(self, tmp_path):
        path = str(tmp_path / 'legacy_clean')
        _make_legacy_sqlite_db(path, with_duplicate=False)

        adapter = SQLiteAdapter()
        adapter.open(path)
        try:
            assert adapter._has_unique_identifier_index(), (
                "open() should have upgraded the non-unique index to UNIQUE"
            )
            # The backstop is now live: a duplicate media doc is rejected.
            with pytest.raises(sqlite3.IntegrityError):
                adapter.insert({
                    '_t': 'media', 'type': 'movie', 'status': 'active',
                    'title': 'The Lost City (dup)',
                    'identifiers': {'imdb': 'tt1111111'},
                    'info': {}, 'tags': [],
                })
        finally:
            adapter.close()

    def test_open_with_duplicate_rows_does_not_raise_and_warns(self, tmp_path, caplog):
        path = str(tmp_path / 'legacy_dirty')
        _make_legacy_sqlite_db(path, with_duplicate=True)

        adapter = SQLiteAdapter()
        with caplog.at_level(logging.WARNING, logger='couchpotato.core.db.sqlite_adapter'):
            adapter.open(path)  # must NOT raise despite the duplicate rows
        try:
            # Startup survived and the index stayed non-unique (lock-only mode).
            assert not adapter._has_unique_identifier_index()
            assert any(
                'duplicate' in r.getMessage().lower()
                for r in caplog.records if r.levelno >= logging.WARNING
            ), "expected a loud duplicate-identifier warning"

            # The (non-unique) index is still usable, and the DB still works.
            assert len(list(adapter.all('id'))) == 2
        finally:
            adapter.close()

    def test_non_integrity_create_failure_restores_non_unique_index(self, tmp_path, caplog):
        """If DROP succeeds but CREATE UNIQUE INDEX fails with an UNEXPECTED
        error (not IntegrityError/OperationalError), the non-unique index must
        still be restored -- otherwise media_identifiers is left with NO index
        at all (a lookup perf cliff on a large prod DB). open()/ensure must not
        raise either.
        """
        path = str(tmp_path / 'legacy_clean_flaky')
        _make_legacy_sqlite_db(path, with_duplicate=False)

        adapter = SQLiteAdapter()
        adapter.open(path)  # clean DB -> auto-upgrades to UNIQUE
        try:
            # Reset to the legacy non-unique state so we exercise the upgrade path.
            real_conn = adapter._get_conn()
            real_conn.execute("DROP INDEX idx_media_identifiers_lookup")
            real_conn.execute(
                "CREATE INDEX idx_media_identifiers_lookup "
                "ON media_identifiers(provider, identifier)"
            )
            real_conn.commit()
            assert not adapter._has_unique_identifier_index()

            class _FlakyConn:
                """Proxy that fails ONLY the CREATE UNIQUE INDEX with a
                non-Integrity/Operational error; everything else delegates."""
                def __init__(self, real):
                    self._real = real

                def execute(self, sql, *args, **kwargs):
                    if 'CREATE UNIQUE INDEX' in sql:
                        raise sqlite3.ProgrammingError('forced non-integrity failure')
                    return self._real.execute(sql, *args, **kwargs)

                def commit(self):
                    return self._real.commit()

                def rollback(self):
                    return self._real.rollback()

                def __getattr__(self, name):
                    return getattr(self._real, name)

            adapter._conn = _FlakyConn(real_conn)
            try:
                with caplog.at_level(logging.WARNING, logger='couchpotato.core.db.sqlite_adapter'):
                    # Must NOT raise despite the unexpected CREATE failure.
                    adapter._ensure_unique_media_identifier_index()
            finally:
                adapter._conn = real_conn

            # Fallback restored the non-unique index (no perf cliff).
            assert not adapter._has_unique_identifier_index()
            names = [r['name'] for r in
                     real_conn.execute("PRAGMA index_list('media_identifiers')").fetchall()]
            assert 'idx_media_identifiers_lookup' in names, (
                "the non-unique index must be restored after any CREATE failure"
            )
            assert any(
                'failed creating the unique' in r.getMessage().lower()
                for r in caplog.records if r.levelno >= logging.WARNING
            ), "expected the non-integrity create-failure warning"

            # Lookups via the restored index still work.
            assert adapter.get_by_identifier('imdb', 'tt1111111')['title'] == 'The Lost City'
        finally:
            adapter.close()

    def test_double_ddl_failure_never_bricks_startup(self, tmp_path, caplog):
        """Compounded failure: BOTH the CREATE UNIQUE INDEX and the fallback
        CREATE INDEX (recreate-non-unique) fail. Even with no index left at
        all, _ensure_unique_media_identifier_index() must NOT raise -- the
        never-brick guarantee has to hold in the worst case.
        """
        path = str(tmp_path / 'legacy_double_fail')
        _make_legacy_sqlite_db(path, with_duplicate=False)

        adapter = SQLiteAdapter()
        adapter.open(path)  # clean DB -> auto-upgrades to UNIQUE
        try:
            # Reset to the legacy non-unique state to exercise the upgrade path.
            real_conn = adapter._get_conn()
            real_conn.execute("DROP INDEX idx_media_identifiers_lookup")
            real_conn.execute(
                "CREATE INDEX idx_media_identifiers_lookup "
                "ON media_identifiers(provider, identifier)"
            )
            real_conn.commit()
            assert not adapter._has_unique_identifier_index()

            class _DoubleFlakyConn:
                """Proxy that fails BOTH CREATE statements (unique AND the
                non-unique recreate); DROP and PRAGMA still delegate."""
                def __init__(self, real):
                    self._real = real

                def execute(self, sql, *args, **kwargs):
                    if 'CREATE' in sql and 'INDEX' in sql:
                        raise sqlite3.OperationalError('forced index create failure')
                    return self._real.execute(sql, *args, **kwargs)

                def commit(self):
                    return self._real.commit()

                def rollback(self):
                    return self._real.rollback()

                def __getattr__(self, name):
                    return getattr(self._real, name)

            adapter._conn = _DoubleFlakyConn(real_conn)
            try:
                with caplog.at_level(logging.WARNING, logger='couchpotato.core.db.sqlite_adapter'):
                    # Must NOT raise even though we can't create ANY index.
                    adapter._ensure_unique_media_identifier_index()
            finally:
                adapter._conn = real_conn

            # Worst case: no index of that name remains, but startup survived.
            names = [r['name'] for r in
                     real_conn.execute("PRAGMA index_list('media_identifiers')").fetchall()]
            assert 'idx_media_identifiers_lookup' not in names
            assert not adapter._has_unique_identifier_index()
            assert any(
                r.levelno >= logging.WARNING and 'REG-004' in r.getMessage()
                for r in caplog.records
            ), "expected a warning even in the double-failure case"

            # The DB is still fully usable despite the missing index.
            assert adapter.get_by_identifier('imdb', 'tt1111111')['title'] == 'The Lost City'
        finally:
            adapter.close()


def _seed_raw_db_with_duplicate_identifiers_no_index(path):
    """Create a raw couchpotato.db at ``path`` that has the core tables and
    duplicate (provider, identifier) rows in media_identifiers, but NO
    idx_media_identifiers_lookup index of any kind. This is the state a
    retried/partial CodernityDB->SQLite migration can leave behind, where
    create()'s schema.sql then tries to build the UNIQUE index for the first
    time and hits the duplicate rows.

    (Contrast with _make_legacy_sqlite_db, which keeps a same-named NON-unique
    index -- there CREATE UNIQUE INDEX IF NOT EXISTS is a silent no-op and the
    fallback never fires.)
    """
    os.makedirs(path, exist_ok=True)
    db_file = os.path.join(path, 'couchpotato.db')
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                _id TEXT PRIMARY KEY, _rev TEXT NOT NULL, _t TEXT NOT NULL,
                data JSON NOT NULL, created_at REAL, updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS media_identifiers (
                media_id TEXT NOT NULL, provider TEXT NOT NULL, identifier TEXT NOT NULL,
                PRIMARY KEY (media_id, provider)
            );
            """
        )
        conn.execute("INSERT INTO documents VALUES ('m1', 'r1', 'media', '{}', 0, 0)")
        conn.execute("INSERT INTO documents VALUES ('m2', 'r2', 'media', '{}', 0, 0)")
        # Same (provider, identifier) owned by two different media docs.
        conn.execute("INSERT INTO media_identifiers VALUES ('m1', 'imdb', 'tt1111111')")
        conn.execute("INSERT INTO media_identifiers VALUES ('m2', 'imdb', 'tt1111111')")
        conn.commit()
    finally:
        conn.close()


class TestSQLiteAdapterInitSchemaFallback:
    """REG-004 review: _init_schema()'s fallback (create() against an already-
    populated path whose data has duplicate identifiers) must not crash startup
    -- it downgrades to the non-unique index and warns. Real trigger:
    codernity_to_sqlite.py's sqlite_db.create(sqlite_path) on a retried/partial
    migration."""

    def test_create_over_duplicate_rows_downgrades_and_warns(self, tmp_path, caplog):
        path = str(tmp_path / 'partial_migration')
        _seed_raw_db_with_duplicate_identifiers_no_index(path)

        adapter = SQLiteAdapter()
        with caplog.at_level(logging.WARNING, logger='couchpotato.core.db.sqlite_adapter'):
            adapter.create(path)  # must NOT raise despite the duplicate rows
        try:
            # The rest of the schema still initialized, and the index exists
            # but as the NON-unique fallback.
            assert not adapter._has_unique_identifier_index()
            names = [r['name'] for r in
                     adapter._get_conn().execute(
                         "PRAGMA index_list('media_identifiers')").fetchall()]
            assert 'idx_media_identifiers_lookup' in names, (
                "the non-unique fallback index must be created"
            )
            assert any(
                'duplicate' in r.getMessage().lower()
                for r in caplog.records if r.levelno >= logging.WARNING
            ), "expected the _init_schema duplicate-identifier fallback warning"

            # The DB is usable: the pre-seeded docs are readable.
            assert len(list(adapter.all('id'))) == 2
        finally:
            adapter.close()


class TestSQLiteAdapterDuplicateDetectionRegression:
    """Promoted from tests/integration/test_duplicate_detection.py (REG-004
    item 3): these are pure tmp_path SQLite tests with nothing integration
    about them, but only ran under tests/integration/, which isn't part of
    `make verify` / CI. Copied here (originals kept in place) so the exact
    corruption branches stay covered on every PR.
    """

    @staticmethod
    def _make_movie(imdb_id, title):
        return {
            '_t': 'media',
            'type': 'movie',
            'title': title,
            'status': 'done',
            'identifiers': {'imdb': imdb_id},
            'info': {'titles': [title], 'year': 2020},
            'files': {},
            'tags': [],
            'last_edit': int(time.time()),
        }

    @staticmethod
    def _make_release(media_id, imdb_id, audio='DTS', quality='720p'):
        return {
            '_t': 'release',
            'media_id': media_id,
            'identifier': f'{imdb_id}.{audio}.{quality}',
            'quality': quality,
            'is_3d': 0,
            'last_edit': int(time.time()),
            'status': 'done',
            'files': {},
        }

    def test_media_lookup_returns_correct_movie_among_many(self, db):
        """BUG REPRODUCTION (Bug 1, sqlite_adapter._query_index('media')).

        With multiple movies in the database, db.get('media', 'imdb-XXXX')
        must return the movie matching XXXX, not just the first one
        inserted. Before the fix, the SQL/params were overwritten and
        limit=1 silently returned the first media doc in the database.
        """
        for movie in [
            self._make_movie('tt5697572', 'Cats'),
            self._make_movie('tt3105662', 'Breaking the Bank'),
            self._make_movie('tt13320622', 'The Lost City'),
        ]:
            db.insert(movie)

        result = db.get('media', 'imdb-tt13320622', with_doc=True)
        doc = result['doc']

        assert doc['identifiers']['imdb'] == 'tt13320622', (
            f"Expected tt13320622 (The Lost City) but got "
            f"{doc['identifiers']['imdb']} ({doc['title']})"
        )
        assert doc['title'] == 'The Lost City'

    def test_release_identifier_lookup_finds_matching_release(self, db):
        """db.get('release_identifier', ...) must return the release with
        the matching identifier, not just any release/document."""
        movie = db.insert(self._make_movie('tt13320622', 'The Lost City'))
        db.insert(self._make_release(movie['_id'], 'tt13320622'))

        result = db.get('release_identifier', 'tt13320622.DTS.720p', with_doc=True)
        doc = result['doc']
        assert doc['_t'] == 'release'
        assert doc['identifier'] == 'tt13320622.DTS.720p'

    def test_release_identifier_lookup_raises_keyerror_when_absent(self, db):
        """BUG REPRODUCTION (Bug 2, sqlite_adapter._query_index('release_identifier')).

        When a media doc exists but no matching release exists, the lookup
        must raise KeyError -- not fall through to the generic "return all
        documents" branch and hand back the media doc as if it were a
        release (which caused release.add() to overwrite the media doc).
        """
        db.insert(self._make_movie('tt13320622', 'The Lost City'))

        with pytest.raises(KeyError):
            db.get('release_identifier', 'tt13320622.DTS.720p', with_doc=True)
