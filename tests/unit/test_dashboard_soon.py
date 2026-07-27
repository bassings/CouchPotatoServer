"""Tests for the dashboard 'Coming soon' / 'Late' views (BUG-017 follow-up).

`Dashboard.getSoonView()` decides whether a movie is coming soon by firing
`movie.searcher.could_be_released` with `media['info']['release_date']` read
straight off the document. Nothing ever populates that field -- the same
BUG-017 root cause -- so it always passed an empty mapping.

That was survivable only because `couldBeReleased()` used to return True for
an empty mapping, which made the view list *every* active movie. Closing that
hole for the searcher flips this caller from "lists everything" to "lists
nothing", so the dashboard has to derive dates the same way the searcher now
does.

These tests drive the real `couldBeReleased` rather than stubbing it, so they
exercise the actual gate.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.media.movie.searcher import MovieSearcher
from couchpotato.core.plugins.dashboard import Dashboard

DAY = 86400


@pytest.fixture
def gate():
    """The real ETA gate, as the event would dispatch to it."""
    searcher = object.__new__(MovieSearcher)
    return searcher.couldBeReleased


def _media(released, media_id='m1'):
    return {
        '_id': media_id,
        '_t': 'movie',
        'title': 'Test Movie',
        'profile_id': 'p1',
        'status': 'active',
        'info': {'year': time.gmtime().tm_year, 'released': released},
    }


def _run(media, gate, late=False, profile=None, wait_days=0):
    """Drive getSoonView with the surrounding plumbing mocked.

    `gate` is the real couldBeReleased, called with whatever positional and
    keyword arguments the view passes -- so a missing `wait_days` shows up as
    a wrong answer rather than being silently absorbed by a stub.
    """
    dashboard = object.__new__(Dashboard)
    profile = profile or {'_id': 'p1', 'qualities': ['1080p', '720p']}

    def fake_fire_event(name, *args, **kwargs):
        if name == 'profile.all':
            return [profile]
        if name == 'quality.pre_releases':
            return ['cam', 'ts', 'tc', 'r5', 'scr']
        if name == 'media.with_status':
            return [{'_id': media['_id']}]
        if name == 'movie.searcher.could_be_released':
            # fireEvent consumes its own dispatch options before invoking a
            # handler; forward only what the handler would really receive.
            passthrough = {
                k: v for k, v in kwargs.items()
                if k not in ('single', 'merge', 'in_order', 'on_complete', 'is_after_event')
            }
            return gate(*args, **passthrough)
        if name == 'release.for_media':
            return []
        return None

    db = MagicMock()
    db.all.return_value = [{'_id': media['_id']}]
    db.get.return_value = media

    with patch('couchpotato.core.plugins.dashboard.get_db', return_value=db), \
            patch('couchpotato.core.plugins.dashboard.fireEvent', side_effect=fake_fire_event), \
            patch('couchpotato.core.plugins.dashboard.Env.setting', return_value=wait_days):
        return dashboard.getSoonView(late=late)


class TestComingSoonUsesDerivedDates:

    def test_lists_a_recently_released_movie(self, gate):
        """Bug repro: with the ETA gate closed for unknown dates, a dashboard
        that reads the never-populated `release_date` field lists nothing at
        all. It must derive from `info['released']` like the searcher does.

        'Soon' means within the view's 3-month window -- a film released
        years ago belongs to the 'late' view, not this one.
        """
        recent = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 10 * DAY))

        result = _run(_media(released=recent), gate)

        assert result['empty'] is False
        assert [m['_id'] for m in result['movies']] == ['m1']

    def test_excludes_an_unreleased_movie(self, gate):
        """The flip side, and a genuine improvement: before this work the
        view listed every active movie regardless of date, because the gate
        always said yes. A film that is not out yet is not 'coming soon' in
        the downloadable sense the view is reporting."""
        future = time.strftime('%Y-%m-%d', time.gmtime(time.time() + 90 * DAY))

        result = _run(_media(released=future), gate)

        assert result['empty'] is True

    def test_a_cached_provider_date_still_wins(self, gate):
        """If a provider ever populates release_date, that value is
        authoritative -- the derivation is only a fallback."""
        media = _media(released='2020-05-01')
        media['info']['release_date'] = {
            'theater': int(time.time()) + 90 * DAY, 'dvd': 0,
        }

        result = _run(media, gate)

        assert result['empty'] is True, (
            'the cached future date must override the derived past one'
        )

    def test_ignores_a_stale_empty_list_cached_by_previous_versions(self, gate):
        """Existing databases hold `release_date: []` written by the old
        updateReleaseDate() on every search."""
        recent = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 10 * DAY))
        media = _media(released=recent)
        media['info']['release_date'] = []

        result = _run(media, gate)

        assert result['empty'] is False

    def test_movie_with_no_derivable_date_is_not_listed(self, gate):
        """Unknown stays unknown -- no guessing."""
        result = _run(_media(released='None'), gate)

        assert result['empty'] is True


class TestHonoursTheConfiguredWait:
    """The view answers "is this coming soon" by calling the same gate the
    searcher uses. If it does not pass the configured `wait_for_release`, it
    reports a movie as available while the searcher is still holding it back
    -- the dashboard and the downloader disagree about the same movie.
    """

    def test_a_movie_inside_the_wait_window_is_not_listed(self, gate):
        recent = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 3 * DAY))

        result = _run(_media(released=recent), gate, wait_days=21)

        assert result['empty'] is True, (
            'released 3 days ago with a 21-day wait: the searcher will not '
            'download it, so the dashboard must not advertise it'
        )

    def test_a_movie_past_the_wait_window_is_listed(self, gate):
        older = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 30 * DAY))

        result = _run(_media(released=older), gate, wait_days=21)

        assert result['empty'] is False

    def test_default_zero_wait_is_unchanged(self, gate):
        recent = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 3 * DAY))

        result = _run(_media(released=recent), gate, wait_days=0)

        assert result['empty'] is False


class TestLateView:

    def test_lists_a_movie_released_more_than_three_months_ago(self, gate):
        """The 'late' cutoff reads `eta[coming_soon]`, but a derived mapping
        only knows `theater` -- `dvd` is deliberately left 0 rather than
        guessed. Without a fallback to `theater`, the late view can never
        match anything for derived dates."""
        old = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 120 * DAY))

        result = _run(_media(released=old), gate, late=True)

        assert result['empty'] is False

    def test_does_not_list_a_recent_release_as_late(self, gate):
        recent = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 10 * DAY))

        result = _run(_media(released=recent), gate, late=True)

        assert result['empty'] is True
