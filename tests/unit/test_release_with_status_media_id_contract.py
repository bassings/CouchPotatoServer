"""Tests pinning the with_doc=False contract of Release.withStatus and the
has_releases filter in MediaPlugin.list that depends on it.

These drive a REAL SQLiteAdapter and REAL Release / MediaPlugin instances
end to end -- the existing test_media_has_releases_filter.py stubs
fireEvent('release.with_status', ...) to return already-flat dicts, which
means it never exercises Release.withStatus or SQLiteAdapter.get_many at
all, and so cannot catch a contract break between them. That mocked test
passed even while the real code was broken:

    Release.withStatus(status, with_doc=False) called
    db.get_many('release_status', s) -- with no with_doc argument, so
    SQLiteAdapter.get_many's own with_doc default (True) always won,
    regardless of what the caller of withStatus asked for. Every row
    withStatus yielded was actually {'doc': {...}, '_id': ...}, so callers
    reading row.get('media_id') or row['media_id'] directly always saw
    None/KeyError, no matter what with_doc they passed.

The consequence lived in media/main.py's has_releases block
(release/main.py:747-762 producing rows, media/main.py:328-338 consuming
them): media_with_releases stayed empty forever, so has_releases=False
matched *every* movie (Wanted page) and has_releases=True matched *none*
(Available page).
"""
import tempfile

import pytest


def _insert_movie(db, media_id, title, profile_id='prof1'):
    return db.insert({
        '_id': media_id,
        '_t': 'media',
        'type': 'movie',
        'status': 'active',
        'title': title,
        'profile_id': profile_id,
        'identifiers': {},
    })


def _insert_release(db, release_id, media_id, status):
    return db.insert({
        '_id': release_id,
        '_t': 'release',
        'media_id': media_id,
        'status': status,
        'identifier': '%s.ident' % release_id,
        'quality': '1080p',
    })


@pytest.fixture
def real_db():
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    with tempfile.TemporaryDirectory() as tmp_path:
        db = SQLiteAdapter()
        db.create(str(tmp_path))
        try:
            yield db
        finally:
            db.close()


def test_with_status_with_doc_false_yields_media_id_readable_at_top_level(real_db, monkeypatch):
    """Release.withStatus(status, with_doc=False) must yield rows where
    media_id is readable directly (row['media_id'] / row.get('media_id')),
    not buried under row['doc']['media_id']. This is the contract every
    with_doc=False caller in media/main.py relies on."""
    from couchpotato.core.plugins.release.main import Release
    import couchpotato.core.plugins.release.main as release_main

    _insert_movie(real_db, 'movie-1', 'Has A Release')
    _insert_release(real_db, 'release-1', 'movie-1', 'done')

    release_plugin = Release.__new__(Release)

    monkeypatch.setattr(release_main, 'get_db', lambda: real_db)
    rows = list(release_plugin.withStatus('done', with_doc=False))

    assert len(rows) == 1
    row = rows[0]
    # The failure mode being pinned: row used to be {'doc': {...}, '_id': ...}
    # with no top-level media_id at all.
    assert 'doc' not in row, (
        "with_doc=False must not wrap rows in {'doc': ...} -- that shape is "
        "the with_doc=True contract"
    )
    assert row.get('media_id') == 'movie-1'
    assert row.get('status') == 'done'


class _FakeEventBus:
    """Bridges fireEvent(event, *a, **kw) to real plugin methods for the
    handful of events MediaPlugin.list actually fires, so the test drives
    the real Release.withStatus / SQLiteAdapter boundary instead of
    stubbing it away. Raises on anything unexpected so a future change to
    list()'s event surface fails loudly here rather than silently no-op'ing."""

    def __init__(self, release_plugin, media_getter):
        self._release_plugin = release_plugin
        self._media_getter = media_getter

    def __call__(self, event, *args, **kwargs):
        kwargs.pop('single', None)
        if event == 'release.with_status':
            return list(self._release_plugin.withStatus(*args, **kwargs))
        if event == 'media.get':
            return self._media_getter(*args, **kwargs)
        raise AssertionError('Unexpected fireEvent call: %r' % (event,))


@pytest.fixture
def wired_media_plugin(real_db, monkeypatch):
    """A real MediaPlugin wired to a real Release plugin over a real
    SQLiteAdapter, with only the unrelated media.get -> release.for_media
    -> conf() chain stood in for by a direct db lookup (that boundary is
    not what this test is pinning)."""
    from couchpotato.core.media._base.media.main import MediaPlugin
    from couchpotato.core.plugins.release.main import Release
    import couchpotato.core.media._base.media.main as media_main
    import couchpotato.core.plugins.release.main as release_main

    media_plugin = MediaPlugin.__new__(MediaPlugin)
    release_plugin = Release.__new__(Release)

    def media_getter(media_id, **kwargs):
        try:
            return real_db.get('id', media_id)
        except KeyError:
            return None

    bus = _FakeEventBus(release_plugin, media_getter)

    monkeypatch.setattr(media_main, 'get_db', lambda: real_db)
    monkeypatch.setattr(release_main, 'get_db', lambda: real_db)
    monkeypatch.setattr(media_main, 'fireEvent', bus)

    return media_plugin


def test_has_releases_false_returns_only_the_movie_without_a_release(wired_media_plugin, real_db):
    _insert_movie(real_db, 'movie-with', 'Has A Release')
    _insert_movie(real_db, 'movie-without', 'No Release Yet')
    _insert_release(real_db, 'release-1', 'movie-with', 'done')

    total, movies = wired_media_plugin.list(types=['movie'], has_releases=False)

    assert total == 1
    assert [m['_id'] for m in movies] == ['movie-without']


def test_has_releases_true_returns_only_the_movie_with_a_release(wired_media_plugin, real_db):
    _insert_movie(real_db, 'movie-with', 'Has A Release')
    _insert_movie(real_db, 'movie-without', 'No Release Yet')
    _insert_release(real_db, 'release-1', 'movie-with', 'done')

    total, movies = wired_media_plugin.list(types=['movie'], has_releases=True)

    assert total == 1
    assert [m['_id'] for m in movies] == ['movie-with']
