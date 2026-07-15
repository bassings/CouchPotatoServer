"""Tests for MovieSearcher.couldBeReleased() pre-release ETA guard.

BUG-014: when a release is flagged as a pre-release (`is_pre_release=True`)
but the movie's theater date is unknown (`dates['theater'] == 0`), the
pre-release branch computed `0 - 604800 < now`, which is always true for any
real-world unix timestamp. This meant couldBeReleased() would incorrectly
report that a pre-release could already be released, purely because the
theater date hadn't been scraped yet, rather than because it was actually
within a week of release.

The fix adds a `dates.get('theater') > 0` guard to the is_pre_release branch
only, mirroring the guard already present in the sibling non-pre-release
branch a few lines below. See specs/BUG-014-prerelease-eta-guard.md.
"""

import time

import pytest

from couchpotato.core.media.movie.searcher import MovieSearcher


@pytest.fixture
def searcher():
    """couldBeReleased() reads no instance state; bypass __init__ so we
    don't pull in addEvent/addApiView plugin registration machinery."""
    return object.__new__(MovieSearcher)


class TestCouldBeReleasedPreReleaseGuard:

    def test_pre_release_with_unknown_theater_date_returns_false(self, searcher):
        """AC1 (bug repro): theater date unknown (0) must NOT be treated as
        'within a week of release'. This is the criterion that fails against
        the unfixed code (0 - 604800 < now is always True)."""
        result = searcher.couldBeReleased(
            True,
            {'theater': 0, 'dvd': 0},
            year=time.gmtime().tm_year,
        )
        assert result is False, (
            "Unknown theater date must not make a pre-release look releasable"
        )

    def test_pre_release_with_unknown_theater_and_known_dvd_returns_false(self, searcher):
        """AC2: a known dvd date must not leak into the pre-release branch
        either — that branch only ever consults 'theater', so with theater
        unknown the whole pre-release check should stay closed."""
        now = int(time.time())
        result = searcher.couldBeReleased(
            True,
            {'theater': 0, 'dvd': now - 1},
            year=time.gmtime().tm_year,
        )
        assert result is False

    def test_pre_release_within_week_of_theater_returns_true(self, searcher):
        """AC3 (regression guard): a known theater date within the next week
        is the legitimate pre-release case and must still return True after
        the fix."""
        now = int(time.time())
        theater = now + 3 * 86400  # 3 days from now, inside the 1-week window
        result = searcher.couldBeReleased(
            True,
            {'theater': theater, 'dvd': 0},
            year=time.gmtime().tm_year,
        )
        assert result is True

    def test_pre_release_far_before_theater_returns_false(self, searcher):
        """AC4 (regression guard): a known theater date far in the future
        (outside the 1-week pre-release window) must still return False,
        unaffected by the fix."""
        now = int(time.time())
        theater = now + 30 * 86400  # 30 days out, well outside the window
        result = searcher.couldBeReleased(
            True,
            {'theater': theater, 'dvd': 0},
            year=time.gmtime().tm_year,
        )
        assert result is False

    def test_non_pre_release_with_unknown_dates_returns_false(self, searcher):
        """AC5 (sibling branch untouched): the non-pre-release branch already
        guards on `dates.get('theater') > 0` / `dates.get('dvd') > 0`, so
        fully unknown dates must keep returning False both before and after
        the fix (the fix touches only the is_pre_release branch)."""
        result = searcher.couldBeReleased(
            False,
            {'theater': 0, 'dvd': 0},
            year=time.gmtime().tm_year,
        )
        assert result is False

    def test_pre_1972_sentinel_still_returns_true_regardless_of_pre_release(self, searcher):
        """AC6 (boundary untouched): a negative theater date is the
        pre-1972/no-data sentinel handled earlier in the method and must
        keep short-circuiting to True before the is_pre_release branch is
        ever reached."""
        result = searcher.couldBeReleased(
            True,
            {'theater': -1, 'dvd': 0},
            year=None,
        )
        assert result is True

    def test_pre_release_exactly_one_week_boundary(self, searcher, monkeypatch):
        """Pin the strict-inequality edge of the 1-week window
        (`theater - 604800 < now`). Exactly one week out is OUTSIDE the
        window and must return False; one second inside must return True.
        Time is frozen so the sub-second gap between the test clock and the
        method's own `time.time()` can't make this flaky. `theater` is
        non-zero, so the top-of-method 'no dates' heuristic never applies
        regardless of `year`."""
        frozen_now = 1_800_000_000  # fixed reference timestamp
        monkeypatch.setattr(
            'couchpotato.core.media.movie.searcher.time.time',
            lambda: frozen_now,
        )
        one_week = 604800
        year = time.gmtime(frozen_now).tm_year

        on_boundary = searcher.couldBeReleased(
            True, {'theater': frozen_now + one_week, 'dvd': 0}, year=year,
        )
        assert on_boundary is False, "exactly one week out is outside the window"

        just_inside = searcher.couldBeReleased(
            True, {'theater': frozen_now + one_week - 1, 'dvd': 0}, year=year,
        )
        assert just_inside is True, "one second inside the window is releasable"
