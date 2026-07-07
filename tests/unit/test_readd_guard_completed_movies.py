"""Tests for the force_readd re-add guard (specs/DOWNLOADED-REVIEW-WORKFLOW.md
Phase 3a, "the re-add guard" item).

Problem: `MovieBase.add()` (couchpotato/core/media/movie/_base/main.py)
defaults `force_readd=True`. The live "Add" buttons
(ui/templates/partials/search_results.html, movie_info_modal.html) call
`movie.add` with NO `force_readd`, so a single stray click on a movie that is
already `done` or `downloaded` (review-gated) used to hit the destructive
`elif force_readd:` branch: it deletes the movie's completed release(s),
resets profile_id/category_id/tags, resets status to 'active', and
re-searches -- silently destroying a confirmed copy. This is pre-existing and
app-wide (it already harmed `done` movies before the `downloaded` status
existed).

Fix: an IMPLICIT force_readd (the caller never passed `force_readd` in
params at all -- the default) against an already-completed movie (`done` or
`downloaded`) is now a no-op, identical to the pre-existing non-force_readd
branch: no release wipe, no profile/category/tags reset, no persisted status
change, no re-search. An EXPLICIT force_readd (e.g. the API's
`force_readd=1`) still falls through to the destructive branch and is
honored -- this guard only protects the default.

Re-search plumbing these tests exercise (main.py ~198-264): a genuine
force_readd sets `do_search = True`; after the release cleanup, the block
`if do_search and search_after: onComplete = self.createOnComplete(...); onComplete()`
fires. `createOnComplete().onComplete()` (couchpotato/core/media/__init__.py)
does `fireEvent('media.get', ...)` then
`fireEventAsync('%s.searcher.single' % media['type'], ...)`. So a real
re-search surfaces as a `movie.searcher.single` fireEventAsync call -- but
ONLY when `search_after` is truthy, which requires
`conf('search_on_add', ...)` to be True (main.py:198). The harness below
therefore stubs conf -> True so the "no re-search" assertions are
discriminating rather than vacuously satisfied by search_after=False.
"""
from unittest.mock import patch

from couchpotato.core.media.movie._base.main import MovieBase


def _base_params(imdb_id='tt0133093', profile_id='profile-1', force_readd=None):
    params = {
        'identifier': imdb_id,
        'info': {'titles': ['The Matrix'], 'title': 'The Matrix'},
        'profile_id': profile_id,
    }
    if force_readd is not None:
        params['force_readd'] = force_readd
    return params


class _FakeExistingMovieDB:
    """A db double for an *existing* media doc (the "found" branch)."""

    def __init__(self, existing):
        self.existing = existing
        self.deleted = []
        self.updated = []

    def get(self, index, key, with_doc=False):
        if index == 'media':
            return {'doc': dict(self.existing), '_id': self.existing['_id']}
        raise KeyError('not found: %s/%s' % (index, key))

    def update(self, data):
        self.updated.append(dict(data))
        return {'_id': data['_id'], '_rev': 'rev2'}

    def delete(self, data):
        self.deleted.append(data)
        return True


class _FakeNewMovieDB:
    """A db double for a brand-new movie (the "not found" -> insert branch)."""

    def __init__(self):
        self.inserted = None
        self.updated = []
        self.deleted = []

    def get(self, index, key, with_doc=False):
        raise KeyError('not found: %s/%s' % (index, key))

    def insert(self, data):
        doc = dict(data)
        doc['_id'] = 'new-media-id'
        self.inserted = doc
        return doc

    def update(self, data):
        self.updated.append(dict(data))
        return {'_id': data['_id'], '_rev': 'rev2'}

    def delete(self, data):
        self.deleted.append(data)
        return True


def _run_add(fake_db, params, releases, media_dict, event_calls,
             search_after=True, update_after=False, notify_after=False,
             search_on_add=True):
    """Runs MovieBase.add() with get_db/fireEvent/fireEventAsync patched, and
    self.conf stubbed to return `search_on_add` for the
    conf('search_on_add', ...) lookup at main.py:198.

    CRUCIAL: search_on_add defaults True here (unlike a False stub that would
    force search_after=False in every branch and make "no re-search"
    assertions vacuous). With it True, a genuine force_readd re-add actually
    calls onComplete() -> fireEventAsync('movie.searcher.single', ...), so a
    guarded no-op's ABSENCE of that call is a real, discriminating signal --
    proven by the active-movie positive-control test below, which fires it.

    `event_calls` records every fireEvent/fireEventAsync call as
    (event_name, args, kwargs).
    """
    plugin = MovieBase.__new__(MovieBase)
    plugin.conf = lambda *a, **k: search_on_add

    def fake_fire_event(event, *args, **kwargs):
        event_calls.append((event, args, kwargs))
        if event == 'release.for_media':
            return releases
        if event == 'media.get':
            return media_dict
        if event in ('release.delete', 'release.update_status', 'notify.frontend'):
            return True
        raise AssertionError('Unexpected fireEvent: %r %r %r' % (event, args, kwargs))

    def fake_fire_event_async(event, *args, **kwargs):
        event_calls.append((event, args, kwargs))
        return True

    # The re-search path routes through createOnComplete() ->
    # onComplete(), which lives in couchpotato.core.media (MediaBase) and
    # binds fireEvent/fireEventAsync in THAT module's namespace -- so those
    # must be patched too, or the movie.searcher.single dispatch would run
    # the real (unhandled) event and be swallowed, silently defeating the
    # positive-control assertion.
    with (
        patch('couchpotato.core.media.movie._base.main.get_db', return_value=fake_db),
        patch('couchpotato.core.media.movie._base.main.fireEvent', side_effect=fake_fire_event),
        patch('couchpotato.core.media.movie._base.main.fireEventAsync', side_effect=fake_fire_event_async),
        patch('couchpotato.core.media.fireEvent', side_effect=fake_fire_event),
        patch('couchpotato.core.media.fireEventAsync', side_effect=fake_fire_event_async),
    ):
        result = plugin.add(
            params=params,
            search_after=search_after,
            update_after=update_after,
            notify_after=notify_after,
        )

    return result


def _completed_movie(status, media_id='media-1', profile_id='existing-profile'):
    return {
        '_id': media_id,
        '_t': 'media',
        'type': 'movie',
        'status': status,
        'profile_id': profile_id,
        'category_id': 'cat-existing',
        'identifiers': {'imdb': 'tt0133093'},
        'info': {'titles': ['The Matrix']},
        'tags': ['keep-me'],
    }


def _searcher_single_calls(event_calls):
    return [(args, kwargs) for name, args, kwargs in event_calls
            if name == 'movie.searcher.single']


def _release_delete_calls(event_calls):
    return [(args, kwargs) for name, args, kwargs in event_calls
            if name == 'release.delete']


class TestImplicitReaddOfCompletedMovieIsNoOp:
    """Add-button style calls (no force_readd in params) against a movie
    that is already 'done' or 'downloaded' must be a no-op -- with
    search_on_add=True, so the "no re-search" assertion is real."""

    def test_readd_done_movie_without_force_readd_does_not_wipe_or_research(self):
        existing = _completed_movie('done')
        completed_release = {'_id': 'rel-1', 'status': 'done'}
        fake_db = _FakeExistingMovieDB(existing)
        event_calls = []

        result = _run_add(
            fake_db,
            params=_base_params(),  # no 'force_readd' key -> implicit default
            releases=[completed_release],
            media_dict={'_id': 'media-1', 'type': 'movie', 'status': 'done', 'title': 'The Matrix'},
            event_calls=event_calls,
        )

        assert result is not False
        # DB state untouched.
        assert fake_db.deleted == [], (
            "implicit re-add of a 'done' movie must not delete its completed release"
        )
        assert fake_db.updated == [], (
            "implicit re-add of a 'done' movie must not persist any change "
            "(status/profile/category/tags reset)"
        )
        # No destructive-branch side effects.
        assert _release_delete_calls(event_calls) == []
        assert [n for n, _a, _k in event_calls if n == 'release.update_status'] == []
        # The KEY assertion, now discriminating (search_on_add=True): the
        # re-search path (do_search -> onComplete() -> movie.searcher.single)
        # is NOT taken for the guarded no-op.
        assert _searcher_single_calls(event_calls) == [], (
            "implicit re-add of a completed movie must not trigger a re-search "
            "(no movie.searcher.single) even with search_on_add=True"
        )

    def test_readd_downloaded_movie_without_force_readd_does_not_wipe_or_research(self):
        existing = _completed_movie('downloaded')
        review_release = {'_id': 'rel-1', 'status': 'downloaded'}
        fake_db = _FakeExistingMovieDB(existing)
        event_calls = []

        result = _run_add(
            fake_db,
            params=_base_params(),
            releases=[review_release],
            media_dict={'_id': 'media-1', 'type': 'movie', 'status': 'downloaded', 'title': 'The Matrix'},
            event_calls=event_calls,
        )

        assert result is not False
        assert fake_db.deleted == [], (
            "implicit re-add of a 'downloaded' (review-gated) movie must not "
            "delete its release"
        )
        assert fake_db.updated == [], (
            "implicit re-add of a 'downloaded' movie must not persist any "
            "change -- the review gate must stay intact"
        )
        assert _release_delete_calls(event_calls) == []
        assert [n for n, _a, _k in event_calls if n == 'release.update_status'] == []
        assert _searcher_single_calls(event_calls) == [], (
            "implicit re-add of a 'downloaded' movie must not trigger a re-search"
        )


class TestExplicitForceReaddStillHonored:
    """Regression lock: an EXPLICIT force_readd must still perform the full
    destructive re-add, proving the guard only blocks the implicit default
    and doesn't over-block deliberate requests."""

    def test_readd_done_movie_with_explicit_force_readd_wipes_and_researches(self):
        existing = _completed_movie('done')
        completed_release = {'_id': 'rel-1', 'status': 'done'}
        fake_db = _FakeExistingMovieDB(existing)
        event_calls = []

        result = _run_add(
            fake_db,
            params=_base_params(force_readd='1'),  # explicit, e.g. API force_readd=1
            releases=[completed_release],
            media_dict={'_id': 'media-1', 'type': 'movie', 'status': 'active', 'title': 'The Matrix'},
            event_calls=event_calls,
        )

        assert result is not False
        assert _release_delete_calls(event_calls) == [(('rel-1',), {'single': True})], (
            "an EXPLICIT force_readd against a 'done' movie must still fire "
            "release.delete for its completed release (regression lock -- "
            "guard must not over-block a deliberate re-add)"
        )
        assert len(fake_db.updated) == 1
        updated = fake_db.updated[0]
        assert updated['tags'] == [], "explicit force_readd must still reset tags"
        assert updated['status'] == 'active', (
            "explicit force_readd must still reset status to active "
            "(media['status'] default from m.update(media))"
        )
        # Deliberate re-add DOES re-search.
        assert len(_searcher_single_calls(event_calls)) == 1, (
            "explicit force_readd must still trigger the re-search"
        )

    def test_readd_done_movie_with_explicit_force_readd_zero_is_noop(self):
        """Explicit force_readd=0 resolves force_readd to False, so add()
        falls through to the pre-existing non-force_readd `else` no-op branch:
        the completed copy must survive untouched (closes the reviewer's noted
        gap that only force_readd=1 was covered on the explicit path)."""
        existing = _completed_movie('done')
        completed_release = {'_id': 'rel-1', 'status': 'done'}
        fake_db = _FakeExistingMovieDB(existing)
        event_calls = []

        result = _run_add(
            fake_db,
            params=_base_params(force_readd='0'),  # explicit disable
            releases=[completed_release],
            media_dict={'_id': 'media-1', 'type': 'movie', 'status': 'done', 'title': 'The Matrix'},
            event_calls=event_calls,
        )

        assert result is not False
        assert fake_db.deleted == []
        assert fake_db.updated == []
        assert _release_delete_calls(event_calls) == []
        assert _searcher_single_calls(event_calls) == [], (
            "explicit force_readd=0 must not re-search a 'done' movie"
        )


class TestNonCompletedMovieUnaffectedByGuard:
    """The guard only protects 'done'/'downloaded'. A non-completed existing
    movie must still force-readd by default exactly as before. This is ALSO
    the positive control proving the guarded tests' "no movie.searcher.single"
    assertion is discriminating (this one DOES fire it under the same
    search_on_add=True harness)."""

    def test_readd_active_movie_without_force_readd_still_destructive_and_researches(self):
        existing = _completed_movie('active')
        snatched_release = {'_id': 'rel-1', 'status': 'snatched'}
        fake_db = _FakeExistingMovieDB(existing)
        event_calls = []

        result = _run_add(
            fake_db,
            params=_base_params(),  # implicit default force_readd=True
            releases=[snatched_release],
            media_dict={'_id': 'media-1', 'type': 'movie', 'status': 'active', 'title': 'The Matrix'},
            event_calls=event_calls,
        )

        assert result is not False
        assert _release_delete_calls(event_calls) == [(('rel-1',), {'single': True})], (
            "the guard must not broaden to non-completed movies -- an "
            "'active' movie must still force-readd (wipe) by default, "
            "unchanged from before this fix"
        )
        assert len(fake_db.updated) == 1
        assert fake_db.updated[0]['tags'] == []
        # POSITIVE CONTROL: under the identical search_on_add=True harness, an
        # 'active' implicit re-add DOES fire movie.searcher.single. This proves
        # the guarded no-op tests' `_searcher_single_calls == []` assertion is
        # discriminating (it can fail), not vacuously true.
        assert len(_searcher_single_calls(event_calls)) == 1, (
            "positive control: a destructive re-add MUST fire movie.searcher.single "
            "so the guarded tests' 'no re-search' assertion is meaningful"
        )


class TestBrandNewMovieUnaffectedByGuard:
    """A movie that doesn't exist yet must be unaffected: no previous_status
    exists, so the guard branch can never apply."""

    def test_add_brand_new_movie_is_unchanged(self):
        fake_db = _FakeNewMovieDB()
        event_calls = []

        result = _run_add(
            fake_db,
            params=_base_params(),
            releases=[],
            media_dict={'_id': 'new-media-id', 'type': 'movie', 'status': 'active', 'title': 'The Matrix'},
            event_calls=event_calls,
        )

        assert result is not False
        assert fake_db.inserted is not None
        assert fake_db.inserted['status'] == 'active'
        # New-movie path never touches db.update/db.delete in add() itself.
        assert fake_db.updated == []
        assert fake_db.deleted == []
