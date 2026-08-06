"""Integration tests for CodernityDB → SQLite migration.

Uses a temporary CodernityDB database populated from sample_data.json,
then migrates to SQLite and verifies.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import textwrap

import pytest
from pathlib import Path

# Ensure libs are importable
libs_path = os.path.join(os.path.dirname(__file__), '..', '..', 'libs')
if libs_path not in sys.path:
    sys.path.insert(0, os.path.abspath(libs_path))

from CodernityDB.database import Database

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.db.migrate import read_codernity_docs, clean_doc_for_sqlite, migrate, verify


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_PATH = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'sample_data.json')


def _identifier_rows(dest_path: str) -> list:
    """Every row of the denormalised media_identifiers table, sorted."""
    conn = sqlite3.connect(os.path.join(dest_path, 'couchpotato.db'))
    try:
        return sorted(conn.execute(
            "SELECT media_id, provider, identifier FROM media_identifiers"
        ).fetchall())
    finally:
        conn.close()


def digest_tree(root: str) -> dict:
    """Map every file under `root` to the SHA-256 of its contents.

    Used to assert a directory is byte-identical before and after an
    operation. Compares contents rather than mtimes: a rewrite that happens
    to reproduce the same bytes is not damage, and a filesystem's mtime
    granularity is too coarse to trust for a fast test.
    """
    digests = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            with open(full, 'rb') as handle:
                digests[os.path.relpath(full, root)] = hashlib.sha256(handle.read()).hexdigest()
    return digests


@pytest.fixture
def sample_data():
    with open(FIXTURES_PATH) as f:
        return json.load(f)


@pytest.fixture
def codernity_db(tmp_path, sample_data):
    """Create a temporary CodernityDB populated with sample data."""
    db_path = str(tmp_path / "source_db")
    db = Database(db_path)
    db.create()

    # Insert all sample documents
    all_docs = []
    for doc_type in ['media', 'release', 'quality', 'profile', 'notification', 'property']:
        for doc in sample_data.get(doc_type, []):
            inserted = db.insert(doc)
            all_docs.append(inserted)

    db.close()
    return db_path, len(all_docs)


class TestReadCodernitydocs:
    def test_read_all_docs(self, codernity_db):
        db_path, expected_count = codernity_db
        docs = read_codernity_docs(db_path)
        assert len(docs) == expected_count

    def test_docs_have_required_fields(self, codernity_db):
        db_path, _ = codernity_db
        docs = read_codernity_docs(db_path)
        for doc in docs:
            assert '_id' in doc
            assert '_t' in doc or '_rev' in doc  # All docs should have type or at least rev


class TestCleanDocForSqlite:
    def test_removes_rev(self):
        doc = {'_id': 'abc', '_rev': '123', '_t': 'media', 'title': 'Test'}
        cleaned = clean_doc_for_sqlite(doc)
        assert '_rev' not in cleaned
        assert '_id' in cleaned
        assert cleaned['title'] == 'Test'

    def test_removes_key(self):
        doc = {'_id': 'abc', '_t': 'media', 'key': 'indexkey', 'title': 'Test'}
        cleaned = clean_doc_for_sqlite(doc)
        assert 'key' not in cleaned


class TestMigrate:
    def test_full_migration(self, codernity_db, tmp_path):
        source_path, expected_count = codernity_db
        dest_path = str(tmp_path / "dest_db")

        count, types = migrate(source_path, dest_path, verbose=False)
        assert count == expected_count

        # Verify we can read from SQLite
        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        all_docs = list(adapter.all('id'))
        assert len(all_docs) == expected_count
        adapter.close()

    def test_type_counts_correct(self, codernity_db, tmp_path, sample_data):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")

        count, types = migrate(source_path, dest_path, verbose=False)

        for doc_type in ['media', 'release', 'quality', 'profile', 'notification', 'property']:
            expected = len(sample_data.get(doc_type, []))
            assert types.get(doc_type, 0) == expected, f"Type {doc_type}: expected {expected}, got {types.get(doc_type, 0)}"

    def test_media_identifiers_migrated(self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)

        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        # The sample data has imdb identifiers
        # query with_doc=True yields {'doc': {...}, '_id': '...'} (CodernityDB compat)
        media_docs = list(adapter.query('media_status', with_doc=True))
        has_identifiers = any(d.get('doc', d).get('identifiers') for d in media_docs)
        assert has_identifiers
        adapter.close()


class TestVerify:
    def test_verify_passes(self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)
        assert verify(source_path, dest_path, verbose=False)

    def test_verify_fails_with_missing_docs(self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)

        # Delete a document from SQLite
        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        docs = list(adapter.all('id', limit=1))
        adapter.delete({'_id': docs[0]['_id']})
        adapter.close()

        assert not verify(source_path, dest_path, verbose=False)


class TestMigrationDataIntegrity:
    def test_json_fields_preserved(self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)

        adapter = SQLiteAdapter()
        adapter.open(dest_path)

        # Check media info blobs
        media = list(adapter.query('media_by_type', key='movie', with_doc=True))
        for m in media:
            if m.get('info'):
                assert isinstance(m['info'], dict)

        # Check release files
        releases = list(adapter.query('release_status', key='done', with_doc=True))
        for r in releases:
            if r.get('files'):
                assert isinstance(r['files'], dict)

        adapter.close()

    def test_all_doc_types_present(self, codernity_db, tmp_path, sample_data):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")
        migrate(source_path, dest_path, verbose=False)

        adapter = SQLiteAdapter()
        adapter.open(dest_path)

        for doc_type in ['media', 'release', 'quality', 'profile', 'notification', 'property']:
            docs = list(adapter.query(doc_type if doc_type != 'media' else 'media_by_type', with_doc=True))
            expected = len(sample_data.get(doc_type, []))
            assert len(docs) == expected, f"Type {doc_type}: expected {expected}, got {len(docs)}"

        adapter.close()


class TestMigrationIsRepeatable:
    """AC-DATA-23: the migration survives being run a second time.

    An operator whose first run was interrupted -- a full disk, a Ctrl-C, a
    container restart part-way through 849 documents -- will simply run it
    again. Two things must hold for that to be safe, and neither is obvious
    from reading migrate():

    1. The second run must not double the library. That rests entirely on
       insert_bulk using INSERT OR REPLACE; a future change to plain INSERT,
       or a denormalised side table that appends rather than replaces, breaks
       it silently and the operator finds out by scrolling a library with
       every film in it twice.
    2. The CodernityDB source must come back untouched. Until the operator
       trusts the SQLite copy, that directory is their only rollback, and
       migrate() opens it with a library written for Python 2. A read path
       that quietly rewrites index or storage files would be destroying the
       escape hatch at the exact moment it is most likely to be needed.
    """

    def test_running_the_migration_twice_does_not_duplicate_documents(self, codernity_db, tmp_path):
        source_path, expected_count = codernity_db
        dest_path = str(tmp_path / "dest_db")

        first_count, first_types = migrate(source_path, dest_path, verbose=False)
        first_rows = _identifier_rows(dest_path)
        second_count, second_types = migrate(source_path, dest_path, verbose=False)
        second_rows = _identifier_rows(dest_path)

        assert first_count == expected_count
        assert second_count == expected_count
        assert second_types == first_types

        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        try:
            ids = [doc['_id'] for doc in adapter.all('id')]
        finally:
            adapter.close()

        assert len(ids) == expected_count, (
            'the second migration run changed the document count from '
            f'{expected_count} to {len(ids)}'
        )
        assert len(set(ids)) == len(ids), 'the second migration run duplicated document ids'
        assert verify(source_path, dest_path, verbose=False)

        # verify() only compares the `documents` table. media_identifiers is
        # the denormalised side table, and rows going wrong there are exactly
        # what produced this project's live "same film added twice" defects --
        # so check it directly rather than inferring it from a passing verify.
        #
        # NOT "no duplicate three-tuples": a UNIQUE index on
        # (provider, identifier) makes that state unreachable, so asserting it
        # is a guard that cannot fail sitting inside one that can. Measured:
        # inserting a duplicate raises IntegrityError.
        #
        # What the equality below IS: a drift detector, and `assert first_rows`
        # is what carries most of the weight (disabling the identifier INSERT
        # reds it). Note what makes the bulk path idempotent is the FOREIGN KEY
        # cascade, not `_update_denormalized`'s explicit DELETE: schema.sql
        # enables `PRAGMA foreign_keys` and media_identifiers.media_id is
        # `ON DELETE CASCADE`, so `INSERT OR REPLACE INTO documents` clears the
        # old rows before they are re-inserted. Review measured that: removing
        # that DELETE changes nothing on this path. An earlier version of this
        # comment claimed the DELETE was what held, which was not true.
        assert second_rows == first_rows, (
            'the second migration run changed media_identifiers from '
            f'{len(first_rows)} rows to {len(second_rows)}'
        )
        assert first_rows, 'no identifier rows were written, so this proves nothing'

    def test_the_codernitydb_source_is_byte_identical_after_migrating_and_verifying(
            self, codernity_db, tmp_path):
        source_path, _ = codernity_db
        dest_path = str(tmp_path / "dest_db")

        before = digest_tree(source_path)
        # Guards the guard: an empty mapping would make the comparison below
        # hold no matter what migrate() did to the source.
        assert before, 'the fixture produced no source files to hash'
        # Known limit of this fixture, stated rather than implied: the source
        # here is three files and a single index, written seconds earlier by
        # the same Python 3 library that then reads it. A real operator's
        # database carries a dozen indexes written by Python 2, and THAT is
        # the shape whose read path could plausibly rewrite index storage on
        # open. This test pins that we do not damage the source we can build;
        # it does not clear the one we cannot. The real-backup equivalent
        # lives in tests/local/, outside pytest.ini's testpaths by design.
        assert len(before) < 10, (
            'fixture grew unexpectedly (%d files) -- if it now resembles a real '
            'multi-index database, update this note rather than deleting it'
            % len(before)
        )

        # The whole documented operator flow, not just one call: `migrate
        # --verify` reads the source twice, and the second read is the one a
        # naive "just reopen it" implementation is most likely to dirty.
        migrate(source_path, dest_path, verbose=False)
        migrate(source_path, dest_path, verbose=False)
        verify(source_path, dest_path, verbose=False)

        after = digest_tree(source_path)
        changed = sorted(
            name for name in set(before) | set(after)
            if before.get(name) != after.get(name)
        )
        assert not changed, (
            'migrating mutated the CodernityDB source, which is the operator\'s '
            f'only rollback until they trust the SQLite copy: {changed}'
        )


class TestMigrationFailureModes:
    """What the operator sees when the source cannot be migrated as-is."""

    def test_a_duplicate_media_identifier_names_the_films_that_collide(self, tmp_path, sample_data):
        """A stopped migration must say WHICH film to fix.

        `media_identifiers` carries a UNIQUE index on (provider, identifier)
        -- the REG-004 backstop -- and it exists because this project shipped
        duplicate media rows. A source written before that can hold a pair,
        and SQLite's own message names the constraint and nothing else. The
        operator is left with a migration that stops dead, an empty
        destination, and no idea which of 849 films is the problem.

        Nothing is lost either way; this is purely about being able to act.
        """
        db_path = str(tmp_path / "dup_source")
        db = Database(db_path)
        db.create()
        # CodernityDB assigns the _id itself (it must be a 32-char hex string),
        # so capture what it returns rather than inventing one.
        inserted_ids = [
            db.insert({
                '_t': 'media', 'type': 'movie', 'status': 'active',
                'title': 'Duplicate %d' % i,
                'identifiers': {'imdb': 'tt0000001'},
            })['_id']
            for i in (1, 2)
        ]
        db.close()

        dest_path = str(tmp_path / "dup_dest")
        with pytest.raises(RuntimeError) as excinfo:
            migrate(db_path, dest_path, verbose=False)

        message = str(excinfo.value)
        assert 'imdb=tt0000001' in message, message
        for doc_id in inserted_ids:
            assert doc_id in message, 'the message must name both colliding docs: %s' % message

        # The message makes a promise about the destination. Pin it, or the
        # same one-line change to insert_bulk that the interrupted-run test
        # guards would quietly make this message a lie -- and the operator
        # acts on it.
        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        try:
            written = list(adapter.all('id'))
        finally:
            adapter.close()
        assert written == [], (
            'the abort message promises no documents were written, but %d were'
            % len(written)
        )
        # The reassurance is load-bearing: an operator who thinks the source
        # was damaged may go looking for a backup they do not need.
        assert 'source is' in message and 'untouched' in message, message

    def test_the_remedy_differs_by_where_the_clash_actually_is(self, tmp_path):
        """Three states, and each issues a DIFFERENT destructive instruction.

        The branch used to key on the message starting with 'Duplicate'.
        Measured at review: renaming the describer's heading -- an ordinary
        copy edit -- routed a genuine source-side duplicate to the
        destination-side advice, with every migration test still green.
        Neither branch had a test at all.

        The stakes are why this is pinned rather than reasoned about: the
        source-side remedy tells the operator to delete a document from the
        CodernityDB source, which is their only rollback copy until they trust
        the SQLite one. Getting that branch wrong points them at it on a false
        premise.
        """
        from couchpotato.core.db.migrate import _describe_identifier_collision

        source_clash = [
            {'_id': 'a', '_t': 'media', 'identifiers': {'imdb': 'tt1'}},
            {'_id': 'b', '_t': 'media', 'identifiers': {'imdb': 'tt1'}},
        ]
        no_clash = [
            {'_id': 'a', '_t': 'media', 'identifiers': {'imdb': 'tt1'}},
            {'_id': 'b', '_t': 'media', 'identifiers': {'imdb': 'tt2'}},
        ]

        found, text = _describe_identifier_collision(source_clash)
        assert found is True
        assert 'imdb=tt1' in text and 'a' in text and 'b' in text

        found, _text = _describe_identifier_collision(no_clash)
        assert found is False

        # A hostile input the describer cannot read: it must say so rather
        # than report "no duplicate", because the caller turns False into
        # "the clash is in your destination, go delete a row there".
        class _Hostile(dict):
            def get(self, *a, **kw):
                raise RuntimeError('simulated: unreadable document')

        found, text = _describe_identifier_collision([_Hostile()])
        assert found is None, 'a failed diagnostic must not masquerade as "no duplicate"'
        assert 'could not determine' in text

    def test_a_source_side_duplicate_advises_the_source_and_nothing_else(self, tmp_path):
        """End to end: the message an operator actually reads."""
        db_path = str(tmp_path / "dup_source")
        db = Database(db_path)
        db.create()
        for i in (1, 2):
            db.insert({'_t': 'media', 'type': 'movie', 'status': 'active',
                       'title': 'Duplicate %d' % i,
                       'identifiers': {'imdb': 'tt0000001'}})
        db.close()

        with pytest.raises(RuntimeError) as excinfo:
            migrate(db_path, str(tmp_path / "dup_dest"), verbose=False)

        message = str(excinfo.value)
        assert 'Resolve the duplicate in the source' in message
        assert 'DESTINATION' not in message, (
            'a source-side clash must not send the operator to the destination'
        )

    @pytest.mark.parametrize('state,must_contain,must_not_contain', [
        (True, 'Resolve the duplicate in the source', 'DESTINATION'),
        (False, 'already in the destination', 'delete one of the two documents'),
        (None, 'could not determine', 'delete one of the two documents'),
    ])
    def test_each_collision_state_maps_to_its_own_remedy(
            self, tmp_path, monkeypatch, state, must_contain, must_not_contain):
        """The state-to-remedy mapping, pinned AT THE CALLER.

        Three tests already cover what `_describe_identifier_collision`
        returns. None covered what `migrate()` does with it, and review
        measured the cost: changing `is True` to `is not False` gives the
        "could not determine" state the SOURCE-side advice, and `is not None`
        gives it to a destination-side clash -- the exact defect an earlier
        round fixed. All 17 migration tests stayed green under both.

        This matters more than a normal mapping test because the source-side
        remedy tells the operator to delete a document from the CodernityDB
        source, which is their only rollback copy until they trust the SQLite
        one. Issuing it on the wrong premise is the failure mode.
        """
        import couchpotato.core.db.migrate as migrate_mod

        db_path = str(tmp_path / "src")
        db = Database(db_path)
        db.create()
        for i in (1, 2):
            db.insert({'_t': 'media', 'type': 'movie', 'status': 'active',
                       'title': 'Dup %d' % i,
                       'identifiers': {'imdb': 'tt0000009'}})
        db.close()

        monkeypatch.setattr(
            migrate_mod, '_describe_identifier_collision',
            lambda docs: (state, '  (stubbed diagnostic)'),
        )

        with pytest.raises(RuntimeError) as excinfo:
            migrate(db_path, str(tmp_path / "dest"), verbose=False)

        message = str(excinfo.value)
        assert must_contain in message, message
        assert must_not_contain not in message, message
        # Every state must protect the source.
        assert 'Do NOT edit the source' in message or state is True, message

    def test_an_interrupted_migration_leaves_no_partial_destination(self, codernity_db, tmp_path):
        """The case the repeatability tests name but do not exercise.

        `TestMigrationIsRepeatable` runs two SUCCESSFUL migrations. The
        motivating story is an interrupted one -- a full disk, a Ctrl-C, a
        container restart part-way through 849 documents -- and the property
        that makes re-running safe is that a killed run commits nothing.
        `insert_bulk` commits once at the end, so it holds today; if that
        ever became a per-document commit, the repeatability tests would stay
        green while the guarantee was gone.

        Killed with SIGKILL in a separate process, because that is the only
        way to reproduce "the process stopped mid-write" without cooperation
        from the code under test.
        """
        source_path, expected_count = codernity_db
        dest_path = str(tmp_path / "interrupted_dest")

        # Kill INSIDE the real insert_bulk loop, not by replacing it. A probe
        # that substitutes its own insert_bulk exercises nothing: measured,
        # such a version stayed green when insert_bulk was mutated to commit
        # per document, which is the single change this test exists to catch.
        # Hooking _update_denormalized leaves the real loop, the real inserts
        # and the real commit placement in charge.
        script = textwrap.dedent(
            '''
            import os, sys
            sys.path.insert(0, %r)
            sys.path.insert(0, %r)
            from couchpotato.core.db import migrate as m
            from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

            real_denorm = SQLiteAdapter._update_denormalized
            seen = []
            def dying_denorm(self, doc_id, data):
                real_denorm(self, doc_id, data)
                seen.append(doc_id)
                if len(seen) >= 3:
                    # Die the way a container restart dies: no unwinding, no
                    # atexit, no commit that Python would otherwise perform.
                    os._exit(9)
            SQLiteAdapter._update_denormalized = dying_denorm
            m.migrate(%r, %r, verbose=False)
            '''
        ) % (str(REPO_ROOT), str(REPO_ROOT / 'libs'), source_path, dest_path)

        proc = subprocess.run([sys.executable, '-c', script], capture_output=True)
        assert proc.returncode == 9, (
            'the probe did not die where it was meant to: rc=%s stderr=%s'
            % (proc.returncode, proc.stderr.decode()[-2000:])
        )

        adapter = SQLiteAdapter()
        adapter.open(dest_path)
        try:
            survived = len(list(adapter.all('id')))
        finally:
            adapter.close()
        assert survived == 0, (
            'a killed migration committed %d documents; re-running would then '
            'have to reconcile a partial destination rather than simply '
            'overwrite it' % survived
        )

        # And the whole point: running it again just works.
        count, _types = migrate(source_path, dest_path, verbose=False)
        assert count == expected_count
        assert verify(source_path, dest_path, verbose=False)
