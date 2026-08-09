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
