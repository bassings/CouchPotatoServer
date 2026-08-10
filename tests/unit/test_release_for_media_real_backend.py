"""`forMedia(require_complete=True)` against a REAL SQLiteAdapter.

The other tests for this function use a hand-rolled fake `_DB`, and a fake
cannot model the thing that was actually wrong: `get_many`'s own `with_doc`
default.

With `with_doc=True` -- the default the caller inherited by not passing one --
`query()` resolves each document INSIDE the generator via `self.get('id', ...)`
and catches only `KeyError` (sqlite_adapter.py:646-653). A corrupt document
raises `JSONDecodeError`, a `ValueError`, which escapes. So the per-document
loop in `forMedia`, including the branch that increments `unreadable` and
fires `database.delete_corrupted`, never ran for the one failure mode it
names: a single bad document made the ENTIRE release set unreadable and the
self-healing event never fired.

The fake said everything was fine. This file exists because that is the
category of defect a fake is structurally unable to report, and because
`require_complete` is the safety linchpin the actual delete depends on.
"""
import json

import pytest

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def db(tmp_path):
    adapter = SQLiteAdapter()
    adapter.create(str(tmp_path / 'releasedb'))
    yield adapter
    adapter.close()


@pytest.fixture
def plugin(db, monkeypatch):
    import couchpotato.core.plugins.release.main as release_main
    from couchpotato.core.plugins.release.main import Release

    monkeypatch.setattr(release_main, 'get_db', lambda: db)
    fired = []
    monkeypatch.setattr(release_main, 'fireEvent',
                        lambda name, *a, **k: fired.append((name, a, k)))
    obj = Release.__new__(Release)
    return obj, db, fired


def _add_release(db, media_id, name):
    return db.insert({'_t': 'release', 'media_id': media_id, 'status': 'done',
                      'identifier': name})


class TestTheSchemaItselfRefusesToStoreMalformedJson:
    """Found while trying to write the corrupt-document test, and it changes
    what that test should be.

    The review that prompted this work reasoned that a corrupt document raises
    `JSONDecodeError` out of the generator. On THIS backend it cannot get that
    far: the schema carries expression indexes over `json_extract(data, ...)`
    and denormalisation on write, so SQLite rejects malformed JSON at the
    point of writing with "malformed JSON". Dropping the expression indexes is
    not enough -- something else in the write path still refuses it.

    So the `ValueError`/`EOFError` branch in `forMedia` is inherited from the
    CodernityDB era, where documents were pickled files that really could rot
    on disk. Keeping it costs nothing and it is the correct handling if a
    torn page ever produces one, but it is not the reachable failure mode
    here, and a test pretending otherwise would be modelling fiction.

    Pinned because it is a genuine integrity guarantee nobody had written
    down: on this schema, a release document cannot be stored unparseable.
    """

    def test_a_write_of_malformed_json_is_rejected(self, plugin):
        import sqlite3

        obj, db, _fired = plugin
        rel = _add_release(db, 'm-1', 'one')
        conn = db._get_conn()

        with pytest.raises(sqlite3.Error, match='(?i)malformed|json'):
            conn.execute("UPDATE documents SET data = ? WHERE _id = ?",
                         ('{not json', rel['_id']))
            conn.commit()


class TestOneUnreadableDocumentIsIsolatedNotFatalToTheWholeSet:
    """The behaviour the fake could not check: `get_many` is called with
    `with_doc=False`, so documents are read ONE AT A TIME inside the loop's
    try, and a single failure is isolated.

    With the inherited default (`with_doc=True`) the generator resolves every
    document itself, so one failing read took down the entire set and the
    per-document accounting below it never ran.

    The failure is injected at `db.get` rather than by storing bad bytes,
    because this schema will not store bad bytes -- see the class above.
    """

    @staticmethod
    def _make_one_unreadable(db, doc_id):
        real_get = db.get

        def _get(index_name, key, *a, **k):
            if key == doc_id:
                raise ValueError('simulated unreadable document')
            return real_get(index_name, key, *a, **k)

        db.get = _get

    def test_the_healthy_releases_still_come_back(self, plugin):
        obj, db, _fired = plugin
        good = _add_release(db, 'm-1', 'good-one')
        bad = _add_release(db, 'm-1', 'bad-one')
        self._make_one_unreadable(db, bad['_id'])

        result = obj.forMedia('m-1')

        assert isinstance(result, list), (
            'one unreadable document made the whole set unreadable: %r'
            % (result,)
        )
        assert [r['_id'] for r in result] == [good['_id']], (
            'the per-document loop did not run: with_doc has reverted to the '
            'default and the generator is resolving documents itself'
        )

    def test_the_self_healing_event_fires_for_that_one_document(self, plugin):
        obj, db, fired = plugin
        _add_release(db, 'm-1', 'good-one')
        bad = _add_release(db, 'm-1', 'bad-one')
        self._make_one_unreadable(db, bad['_id'])

        obj.forMedia('m-1')

        deletes = [f for f in fired if f[0] == 'database.delete_corrupted']
        assert deletes, (
            'the unreadable document was never reported for cleanup, so it '
            'stays broken and this repeats on every scan: %r' % (fired,)
        )
        assert deletes[0][1][0] == bad['_id']

    def test_strict_mode_refuses_because_ONE_document_was_unreadable(self, plugin):
        obj, db, _fired = plugin
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET

        _add_release(db, 'm-1', 'good-one')
        bad = _add_release(db, 'm-1', 'bad-one')
        self._make_one_unreadable(db, bad['_id'])

        assert obj.forMedia('m-1', require_complete=True) is INCOMPLETE_RELEASE_SET

    def test_a_healthy_set_is_complete_under_strict_mode(self, plugin):
        """The control. Without it, a guard that refused every real database
        would look identical to one that works."""
        obj, db, _fired = plugin
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET

        _add_release(db, 'm-1', 'one')
        _add_release(db, 'm-1', 'two')

        result = obj.forMedia('m-1', require_complete=True)
        assert result is not INCOMPLETE_RELEASE_SET
        assert len(result) == 2

    def test_a_media_with_no_releases_is_complete_and_empty(self, plugin):
        obj, db, _fired = plugin
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET

        result = obj.forMedia('m-nothing', require_complete=True)
        assert result is not INCOMPLETE_RELEASE_SET
        assert result == []


class TestARepeatedlyUnreadableSetDoesNotEraseTheLog:
    """`forMedia` has sixteen callers and runs on ordinary page loads, not
    just on a rename collision -- so this path is HOTTER than the renamer
    decision whose traceback was bounded two commits earlier.

    Sustained lock contention would therefore repeat on every scan AND every
    dashboard render, and an unbounded traceback each time evicts the rotating
    log that is the only diagnostic a self-hosted install has: the failure
    erases the evidence of itself.
    """

    @pytest.fixture(autouse=True)
    def _fresh_windows(self):
        from couchpotato.core.logger import reset_log_suppression
        reset_log_suppression()
        yield
        reset_log_suppression()

    @staticmethod
    def _always_fails(db):
        def _boom(*a, **k):
            raise RuntimeError('database is locked')
        db.get_many = _boom

    def test_the_first_failure_is_reported_in_full(self, plugin, caplog):
        import logging
        obj, db, _fired = plugin
        self._always_fails(db)

        with caplog.at_level(logging.ERROR):
            obj.forMedia('m-1', require_complete=True)

        assert any('database is locked' in r.getMessage() for r in caplog.records), (
            'the first failure was suppressed, so the bound cost the diagnosis'
        )

    def test_twenty_reads_do_not_write_twenty_tracebacks(self, plugin, caplog):
        import logging
        obj, db, _fired = plugin
        self._always_fails(db)

        with caplog.at_level(logging.ERROR):
            for _ in range(20):
                obj.forMedia('m-1', require_complete=True)

        tracebacks = [
            r for r in caplog.records if 'database is locked' in r.getMessage()
        ]
        assert tracebacks, 'nothing was recorded at all'
        assert len(tracebacks) < 20, (
            'every read wrote a full traceback (%d of 20); the rotating log '
            'is being evicted by the failure it exists to record'
            % len(tracebacks)
        )

    def test_a_different_media_is_not_silenced_by_the_first(self, plugin, caplog):
        import logging
        obj, db, _fired = plugin
        self._always_fails(db)

        with caplog.at_level(logging.ERROR):
            for _ in range(6):
                obj.forMedia('m-1', require_complete=True)
            caplog.clear()
            obj.forMedia('m-2', require_complete=True)

        assert any('database is locked' in r.getMessage() for r in caplog.records), (
            'a second, unrelated media was silenced by the first'
        )


class TestDetachFileDoesNotLogTheLibraryPath:
    """`detachFile` receives a real destination path, and an OSError's
    `__str__` appends `filename` -- so `traceback.format_exc()` here would put
    the library path in the log. That is what D8 forbids and what
    `_withoutPaths` was added for on the renamer side; this call site was the
    one that had not caught up.
    """

    def test_a_failure_reports_the_cause_without_the_path(self, plugin, caplog):
        import logging

        obj, db, _fired = plugin
        rel = _add_release(db, 'm-1', 'one')
        secret = '/mnt/nas/Films/Some Movie (1999)/Some Movie.mkv'

        def _boom(*a, **k):
            raise PermissionError(13, 'Permission denied', secret)

        db.update_with_retry = _boom

        with caplog.at_level(logging.ERROR):
            assert obj.detachFile(rel['_id'], secret) is False

        messages = ' '.join(r.getMessage() for r in caplog.records)
        assert secret not in messages, (
            'the library path reached the log through the exception: %s' % messages
        )
        assert '/mnt/nas' not in messages and 'Some Movie' not in messages
        # The bound must not cost the diagnosis.
        assert 'Permission denied' in messages and '13' in messages
        assert rel['_id'] in messages


class TestDetachFileActuallyDetaches:
    """`detachFile`'s read-modify-write was only ever exercised through the
    renamer's stubbed `fireEvent`, which returns True without doing anything,
    plus one direct test that patches `update_with_retry` to raise. So the
    mutation itself -- removing the path, recomputing copy_id -- had no
    coverage at all.

    It is on the path that stops the NEXT upgrade resolving as ambiguous, and
    it is the CAS pattern this project treats as a known race risk. Driven
    against a real SQLiteAdapter here.
    """

    @staticmethod
    def _with_files(db, media_id, files):
        from couchpotato.core.plugins.release.main import copyIdentity
        doc = db.insert({'_t': 'release', 'media_id': media_id, 'status': 'done',
                         'files': files, 'copy_id': copyIdentity(files)})
        return doc

    def test_the_path_is_removed_from_the_document(self, plugin, tmp_path):
        obj, db, _fired = plugin
        a = tmp_path / 'kept.mkv'; a.write_bytes(b'x' * 10)
        b = tmp_path / 'gone.mkv'; b.write_bytes(b'y' * 20)
        rel = self._with_files(db, 'm-1', {'movie': [str(a), str(b)]})

        assert obj.detachFile(rel['_id'], str(b)) is True

        after = db.get('id', rel['_id'])
        assert after['files']['movie'] == [str(a)], (
            'the replaced path is still claimed: %r' % after['files']
        )

    def test_copy_id_is_recomputed_not_left_stale(self, plugin, tmp_path):
        """A copy_id beside a removed path describes a set the document no
        longer claims, which is worse than having none."""
        obj, db, _fired = plugin
        a = tmp_path / 'kept.mkv'; a.write_bytes(b'x' * 10)
        b = tmp_path / 'gone.mkv'; b.write_bytes(b'y' * 20)
        rel = self._with_files(db, 'm-1', {'movie': [str(a), str(b)]})
        # Read it back rather than trusting insert()'s return value.
        before = db.get('id', rel['_id']).get('copy_id')
        assert before and ',' in before, (
            'the fixture did not store a two-file identity: %r' % before
        )

        obj.detachFile(rel['_id'], str(b))

        after = db.get('id', rel['_id'])
        assert after['copy_id'] != before
        assert after['copy_id'] == '10', (
            'copy_id was not recomputed from what remains: %r' % after['copy_id']
        )

    def test_detaching_the_only_file_leaves_no_identity(self, plugin, tmp_path):
        obj, db, _fired = plugin
        only = tmp_path / 'only.mkv'; only.write_bytes(b'z' * 30)
        rel = self._with_files(db, 'm-1', {'movie': [str(only)]})

        obj.detachFile(rel['_id'], str(only))

        after = db.get('id', rel['_id'])
        assert not after.get('files'), 'an empty file type was left behind'
        assert after.get('copy_id') is None, (
            'an identity survived a document that claims nothing: %r'
            % after.get('copy_id')
        )

    def test_other_file_types_are_untouched(self, plugin, tmp_path):
        obj, db, _fired = plugin
        movie = tmp_path / 'm.mkv'; movie.write_bytes(b'x' * 10)
        nfo = tmp_path / 'm.nfo'; nfo.write_bytes(b'n')
        rel = self._with_files(db, 'm-1', {'movie': [str(movie)], 'nfo': [str(nfo)]})

        obj.detachFile(rel['_id'], str(movie))

        after = db.get('id', rel['_id'])
        assert after['files'].get('nfo') == [str(nfo)], (
            'detaching a movie file removed unrelated file types: %r' % after['files']
        )

    def test_a_path_the_release_never_claimed_changes_nothing(self, plugin, tmp_path):
        """Short-circuits rather than rewriting an identical document, and
        still answers True -- "not claimed" is the state the caller wanted."""
        obj, db, _fired = plugin
        movie = tmp_path / 'm.mkv'; movie.write_bytes(b'x' * 10)
        rel = self._with_files(db, 'm-1', {'movie': [str(movie)]})
        before = db.get('id', rel['_id'])

        assert obj.detachFile(rel['_id'], str(tmp_path / 'never-claimed.mkv')) is True

        after = db.get('id', rel['_id'])
        assert after['files'] == before['files']
        assert after['_rev'] == before['_rev'], 'it rewrote an unchanged document'
