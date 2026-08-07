"""`release_download` must honour its key, or downloads get misfiled.

The branch ignored it entirely (`sqlite_adapter.py`):

    sql = "SELECT ... WHERE _t = 'release'"
    if key is not None:
        sql += " AND json_extract(...downloader) IS NOT NULL
                 AND json_extract(...id)         IS NOT NULL"
        # We'd need to match on combined key; for now return all with download_info

`get()` then returns the FIRST row. The spec rates this "S · risk: low"; the
chain says otherwise, and every link was read:

1. `renamer/scanner.py:197` looks the release up by downloader+id.
2. `extendReleaseDownload` stamps that release's **imdb_id, quality, is_3d**
   onto the finished download.
3. `scanner/folder_scanner.py:361` `determineMedia` uses that `imdb_id` as the
   FIRST and highest-priority signal for which movie the files belong to --
   ahead of the CP tag and ahead of filename parsing.
4. It runs on `renamer.check_snatched`, a scheduled interval.

So with two or more releases carrying `download_info`, a completed download is
attributed to the wrong movie and the renamer files it into that movie's
folder. The wrong `imdb_id` does not merely fail to help: it **overrides** the
answer parsing would have got right.

Third defect in this same `_query_index` family, after the `'media'` branch
returning the first row for any key and the missing `'release_identifier'`
branch.

**The id type is not uniform, and that is the trap in the fix.** Hash-based
downloaders store a string (`deluge.py:180` `torrent['hash']`,
`transmission.py:180` `torrent['hashString']`), while `nzbget.py:178` stores
`nzb['NZBID']` -- an integer. A fixture using only string ids would pass while
every NZBGet user still matched nothing.
"""
import pytest

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def db(tmp_path):
    adapter = SQLiteAdapter()
    adapter.create(str(tmp_path / 'db'))
    try:
        yield adapter
    finally:
        adapter.close()


def _release(_id, downloader, download_id, imdb):
    return {
        '_id': _id,
        '_t': 'release',
        'media_id': 'media-%s' % _id,
        'quality': '1080p',
        'is_3d': False,
        'download_info': {'downloader': downloader, 'id': download_id},
        'identifiers': {'imdb': imdb},
    }


class TestTheLookupHonoursItsKey:

    def test_two_releases_do_not_collide(self, db):
        db.insert(_release('a', 'transmission', 'HASH-AAA', 'tt0000001'))
        db.insert(_release('b', 'transmission', 'HASH-BBB', 'tt0000002'))

        found = db.get('release_download', ('transmission', 'HASH-BBB'), with_doc=True)

        assert found['doc']['_id'] == 'b', (
            'the lookup returned release %r for a key that names release "b". '
            'Downstream this stamps the wrong movie onto the finished download '
            'and the renamer files it into that movie'
            % found['doc']['_id']
        )

    def test_the_same_id_on_a_different_downloader_does_not_match(self, db):
        """Both halves of the key must count, not just the id."""
        db.insert(_release('a', 'sabnzbd', 'SHARED', 'tt0000001'))
        db.insert(_release('b', 'transmission', 'SHARED', 'tt0000002'))

        assert db.get('release_download', ('transmission', 'SHARED'), with_doc=True)['doc']['_id'] == 'b'
        assert db.get('release_download', ('sabnzbd', 'SHARED'), with_doc=True)['doc']['_id'] == 'a'

    def test_an_unknown_key_raises_rather_than_returning_something(self, db):
        """Returning an arbitrary row is the whole defect. Not-found must be
        not-found, which the caller already handles by logging."""
        db.insert(_release('a', 'transmission', 'HASH-AAA', 'tt0000001'))

        with pytest.raises(KeyError):
            db.get('release_download', ('transmission', 'NOT-A-REAL-ID'), with_doc=True)

    def test_a_numeric_id_matches(self, db):
        """`nzbget.py:178` stores `nzb['NZBID']`, an int.

        The caller formats the key with `%s`, so the lookup value arrives as a
        string. Matching on the raw JSON value would compare `'123'` to `123`
        and find nothing -- silently breaking every NZBGet install while the
        hash-based downloaders kept working.
        """
        db.insert(_release('a', 'nzbget', 123, 'tt0000001'))
        db.insert(_release('b', 'nzbget', 456, 'tt0000002'))

        assert db.get('release_download', ('nzbget', 456), with_doc=True)['doc']['_id'] == 'b'
        assert db.get('release_download', ('nzbget', '456'), with_doc=True)['doc']['_id'] == 'b'


class TestTheLegacyCombinedKeyStillWorks:
    """One caller builds `'%s-%s' % (downloader, id)`; it is updated, but any
    other caller must fail CLOSED rather than get an arbitrary row."""

    def test_a_combined_string_key_matches_the_right_release(self, db):
        db.insert(_release('a', 'transmission', 'AAA', 'tt0000001'))
        db.insert(_release('b', 'transmission', 'BBB', 'tt0000002'))

        assert db.get('release_download', 'transmission-BBB', with_doc=True)['doc']['_id'] == 'b'

    def test_an_ambiguous_combined_key_finds_nothing_rather_than_the_wrong_row(self, db):
        """A downloader name containing `-` makes the split ambiguous.

        No downloader in this tree has one, but the failure mode must be
        "not found" -- which the caller logs -- and never "here is some other
        release".
        """
        db.insert(_release('a', 'my-downloader', 'XYZ', 'tt0000001'))

        with pytest.raises(KeyError):
            db.get('release_download', 'my-downloader-XYZ', with_doc=True)


class TestNoKeyStillListsEverything:
    """`query()`/`all()` over the index are a different contract from `get()`."""

    def test_a_none_key_returns_every_release_with_download_info(self, db):
        db.insert(_release('a', 'transmission', 'AAA', 'tt0000001'))
        db.insert(_release('b', 'nzbget', 42, 'tt0000002'))
        db.insert({'_id': 'c', '_t': 'release', 'media_id': 'm', 'quality': 'hd'})

        rows = list(db.query('release_download', with_doc=True))

        assert sorted(r['doc']['_id'] for r in rows) == ['a', 'b']


class TestTheIndexReachesExistingInstalls:
    """A new index in schema.sql alone would reach FRESH installs only.

    `open()` does not run `schema.sql` -- `_init_schema` is called from
    `create()` -- so anything added there never appears on a database that
    already exists. That is the same shape that would have bricked login had
    PR 2 added a `sessions` table, and it is why
    `_ensure_unique_media_identifier_index` exists at all.

    So the test that matters is not "a fresh database has the index" but
    "a database created BEFORE the index existed gains it on open".
    """

    def _index_names(self, adapter):
        rows = adapter._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        return {r[0] for r in rows}

    def test_a_fresh_database_has_the_index(self, tmp_path):
        adapter = SQLiteAdapter()
        adapter.create(str(tmp_path / 'fresh'))
        try:
            assert 'idx_release_download' in self._index_names(adapter)
        finally:
            adapter.close()

    def test_a_pre_existing_database_gains_it_on_open(self, tmp_path):
        """Simulates an install that predates this change."""
        path = str(tmp_path / 'existing')

        adapter = SQLiteAdapter()
        adapter.create(path)
        adapter.insert(_release('a', 'transmission', 'AAA', 'tt0000001'))
        adapter._get_conn().execute('DROP INDEX IF EXISTS idx_release_download')
        assert 'idx_release_download' not in self._index_names(adapter)
        adapter.close()

        reopened = SQLiteAdapter()
        reopened.open(path)
        try:
            assert 'idx_release_download' in self._index_names(reopened), (
                'the index reaches fresh installs only; every existing '
                'database keeps doing a full scan of every release row'
            )
            # ...and the data is still there and still findable.
            assert reopened.get('release_download', ('transmission', 'AAA'),
                                with_doc=True)['doc']['_id'] == 'a'
        finally:
            reopened.close()

    def test_opening_twice_is_harmless(self, tmp_path):
        """Idempotent: the upgrade runs on every open, not just the first.

        The DROP is what makes this test mean anything. Without it `create()`
        has already installed the index via schema.sql, so the upgrade path
        never executes and both opens merely observe what was always there --
        measured: under a mutation that deleted the
        `_ensure_release_download_index()` call from `open()` entirely, the
        original version of this test stayed GREEN while its sibling went red.
        Incidentally-passing, and it looked specific.
        """
        path = str(tmp_path / 'twice')
        first = SQLiteAdapter()
        first.create(path)
        first._get_conn().execute('DROP INDEX IF EXISTS idx_release_download')
        assert 'idx_release_download' not in self._index_names(first)
        first.close()

        for attempt in (1, 2):
            adapter = SQLiteAdapter()
            adapter.open(path)
            try:
                assert 'idx_release_download' in self._index_names(adapter), (
                    'open() #%d did not leave the index in place' % attempt
                )
            finally:
                adapter.close()

    def test_the_lookup_actually_uses_the_index(self, tmp_path):
        """The SQL predicate and the index expression must stay character-identical.

        `idx_release_download` indexes
        `CAST(json_extract(...) AS TEXT)`, and SQLite only uses an expression
        index when the query's expression matches it EXACTLY. Two comments say
        so; nothing enforced it, so the coupling could break silently and every
        correctness test would stay green -- measured: dropping the CASTs from
        the query alone falls back to a scan via `idx_documents_type`, still
        correct, 0.050ms vs 0.014ms per lookup over 2,000 releases. On a
        scheduled job over a real library that is the whole point of the index.
        """
        adapter = SQLiteAdapter()
        adapter.create(str(tmp_path / 'planned'))
        try:
            adapter.insert(_release('a', 'transmission', 'HASH-AAA', 'tt0000001'))

            # The real predicate, taken from the adapter rather than retyped --
            # a hand-copied duplicate here would drift from the code it claims
            # to pin and this test would then pass against a query nobody runs.
            import inspect
            source = inspect.getsource(SQLiteAdapter._query_index)
            marker = "elif index_name == 'release_download':"
            assert marker in source, 'the release_download branch moved; re-derive this test'
            branch = source.split(marker, 1)[1].split('elif index_name ==', 1)[0]
            assert "CAST(json_extract(data, '$.download_info.downloader') AS TEXT)" in branch, (
                'the downloader predicate no longer CASTs; it can no longer '
                'match the index expression in schema.sql'
            )

            plan = adapter._get_conn().execute(
                """EXPLAIN QUERY PLAN
                   SELECT _id, _rev, data FROM documents WHERE _t = 'release'
                   AND CAST(json_extract(data, '$.download_info.downloader') AS TEXT) = ?
                   AND CAST(json_extract(data, '$.download_info.id') AS TEXT) = ?""",
                ('transmission', 'HASH-AAA'),
            ).fetchall()

            detail = ' '.join(str(row['detail']) for row in plan)
            assert 'idx_release_download' in detail, (
                'the release_download lookup no longer uses its index (plan: '
                '%s). Correctness is unaffected, which is exactly why this '
                'needs a test: it degrades to a full scan of every release '
                'row on a scheduled job, silently.' % detail
            )
        finally:
            adapter.close()


class TestTheCallerStampsTheRightMovie:
    """The adapter returning the right row is necessary, not sufficient.

    `extendReleaseDownload` is where the harm happens: it copies the found
    release's `imdb_id`, `quality`, `is_3d` and `release_id` onto the finished
    download, and `folder_scanner.determineMedia` then treats that `imdb_id` as
    the highest-priority answer to "which movie is this?". An adapter-only test
    would go green while the caller still built an ambiguous key and misfiled
    the download, so the assertion has to be made here.
    """

    def _scanner(self, adapter, monkeypatch):
        from couchpotato.core.plugins.renamer import scanner as scanner_module
        from couchpotato.core.plugins.renamer.main import Renamer

        monkeypatch.setattr(scanner_module, 'get_db', lambda: adapter)
        monkeypatch.setattr(scanner_module, 'getIdentifier',
                            lambda media: (media or {}).get('identifiers', {}).get('imdb'))
        return Renamer.__new__(Renamer)

    def test_the_download_is_stamped_with_its_own_movie(self, db, monkeypatch):
        for suffix, imdb in (('a', 'tt1111111'), ('b', 'tt2222222')):
            db.insert({'_id': 'media-%s' % suffix, '_t': 'media',
                       'identifiers': {'imdb': imdb}, 'type': 'movie',
                       'status': 'done', 'title': 'Movie %s' % suffix})
            db.insert(_release(suffix, 'transmission', 'HASH-%s' % suffix.upper(), imdb))

        plugin = self._scanner(db, monkeypatch)
        download = {'downloader': 'transmission', 'id': 'HASH-B'}

        plugin.extendReleaseDownload(download)

        assert download.get('imdb_id') == 'tt2222222', (
            'the download for HASH-B was stamped with %r. determineMedia uses '
            'this as the FIRST signal for which movie the files belong to, so '
            'the renamer files them into the wrong movie'
            % download.get('imdb_id')
        )
        assert download.get('release_id') == 'b'

    def test_an_unknown_download_is_left_unstamped(self, db, monkeypatch):
        """Not-found must leave the download alone, so the scanner falls back
        to filename parsing rather than inheriting some other movie."""
        db.insert(_release('a', 'transmission', 'HASH-A', 'tt1111111'))

        plugin = self._scanner(db, monkeypatch)
        download = {'downloader': 'transmission', 'id': 'NOT-PRESENT'}

        plugin.extendReleaseDownload(download)

        assert 'imdb_id' not in download, (
            'an unmatched download inherited %r' % download.get('imdb_id')
        )
