"""Tests for MovieSearcher.couldBeReleased() pre-release ETA guard.

BUG-014: when a release is flagged as a pre-release (`is_pre_release=True`)
but the movie's theater date is unknown (`dates['theater'] == 0`), the
pre-release branch computed `0 - 604800 < now`, which is always true for any
real-world unix timestamp. This meant couldBeReleased() would incorrectly
report that a pre-release could already be released, purely because the
theater date hadn't been scraped yet, rather than because it was actually
within a week of release.

The fix adds a `dates.get('theater') > 0` guard to the is_pre_release branch,
mirroring the guard already present in the sibling non-pre-release branch a
few lines below, and additionally hardens all `dates.get()` calls in both
branches with explicit `0` defaults so partial dicts missing a key return
False instead of raising TypeError. See specs/BUG-014-prerelease-eta-guard.md.
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
        """Regression guard, not a numbered AC: a known dvd date must not
        leak into the pre-release branch either — that branch only ever
        consults 'theater', so with theater unknown the whole pre-release
        check should stay closed."""
        now = int(time.time())
        result = searcher.couldBeReleased(
            True,
            {'theater': 0, 'dvd': now - 1},
            year=time.gmtime().tm_year,
        )
        assert result is False

    def test_pre_release_within_week_of_theater_returns_true(self, searcher):
        """AC2 (regression guard): a known theater date within the next week
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
        """AC3 (regression guard): a known theater date far in the future
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
        """AC4 (sibling branch untouched): the non-pre-release branch already
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
        """Regression guard, not a numbered AC: a negative theater date is
        the pre-1972/no-data sentinel handled earlier in the method and must
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
        regardless of `year`.

        Note for reviewers: the monkeypatch target `searcher.time.time`
        resolves to the shared `time` MODULE's `time` attribute (searcher
        imports the module, not the function), and CPython's
        `datetime.date.today()` calls `time.time()` internally — so the
        method's `date.today()` future-year guard is frozen to 2027 along
        with the clock, and `year=2027` never trips it. Verified
        empirically: with this patch active, `date.today()` returns
        2027-01-15 regardless of the real system date."""
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

    @pytest.mark.parametrize('is_pre_release', [True, False])
    def test_old_movie_with_unknown_dates_assumed_released(self, searcher, is_pre_release):
        """AC5: an old movie (year two years in the past) with fully unknown
        dates must hit the top-of-method 'no dates known, old movie' heuristic
        and return True regardless of is_pre_release — that early-return path
        is intentional and must not be affected by the is_pre_release guard
        fix (see spec 'Fix Required' notes)."""
        old_year = time.gmtime().tm_year - 2
        result = searcher.couldBeReleased(
            is_pre_release,
            {'theater': 0, 'dvd': 0},
            year=old_year,
        )
        assert result is True


class TestCouldBeReleasedUnknownDates:
    """BUG-017: an EMPTY or absent `dates` mapping meant 'already released'.

    The pre-1972 branch read `if not dates or dates.get('theater', 0) < 0
    or dates.get('dvd', 0) < 0: return True`. The comment shows the intent —
    a *negative* epoch is the pre-1970 sentinel — but `not dates` rode along,
    so an unknown release date returned True and the searcher downloaded.

    Empty is exactly what the caller passes when the lookup fails:
    `MovieBase.updateReleaseDate()` returns `{}` from its exception handler
    and whenever the info provider has no release_date yet. Bulk-adding
    movies (each triggering a search via `search_on_add`) is when provider
    calls are most likely to come back empty.

    Note the asymmetry that hid this: `{'theater': 0, 'dvd': 0}` already
    behaved correctly (see TestCouldBeReleasedPreReleaseGuard), so only the
    falsy-mapping shapes were wrong. See specs/BUG-017-eta-unknown-release-dates.md.
    """

    @pytest.mark.parametrize('dates', [{}, None], ids=['empty-dict', 'none'])
    def test_unknown_dates_are_not_releasable(self, searcher, dates):
        """AC1/AC2 (bug repro): a current-year movie whose release dates
        could not be resolved must NOT be considered released. Fails against
        the unfixed code, which returns True for both shapes."""
        result = searcher.couldBeReleased(
            False, dates, year=time.gmtime().tm_year,
        )
        assert result is False, (
            "Unknown release dates must not authorise a download"
        )

    @pytest.mark.parametrize('dates', [{}, None], ids=['empty-dict', 'none'])
    def test_unknown_dates_are_not_releasable_for_pre_releases(self, searcher, dates):
        """AC3: same for the pre-release branch — unknown is unknown
        regardless of which branch asks."""
        result = searcher.couldBeReleased(
            True, dates, year=time.gmtime().tm_year,
        )
        assert result is False

    @pytest.mark.parametrize('dates', [
        {'theater': -1},
        {'dvd': -1},
        {'theater': -1, 'dvd': 0},
    ], ids=['theater', 'dvd', 'theater-with-zero-dvd'])
    def test_negative_epoch_sentinel_still_releasable(self, searcher, dates):
        """AC4 (regression): the pre-1972 sentinel is the branch's real
        purpose and must survive removal of the `not dates` clause. Note
        these dicts are missing a key each — the fix must not reintroduce a
        TypeError on partial mappings."""
        result = searcher.couldBeReleased(
            False, dates, year=time.gmtime().tm_year,
        )
        assert result is True

    @pytest.mark.parametrize('dates', [
        {}, None, {'theater': 0, 'dvd': 0},
    ], ids=['empty-dict', 'none', 'explicit-zeros'])
    def test_old_movie_with_unknown_dates_is_still_releasable(self, searcher, dates):
        """AC5 (regression): the *other* `not dates` test — the top-of-method
        'old movie and no dates' heuristic at line 381 — is deliberate and
        must be left intact. A film two years old cannot be unreleased, so
        assuming released is right there. Only the pre-1972 branch changes."""
        old_year = time.gmtime().tm_year - 2
        result = searcher.couldBeReleased(False, dates, year=old_year)
        assert result is True

    def test_unknown_year_with_unknown_dates_is_still_releasable(self, searcher):
        """Regression: `year=None` also routes to the line-381 heuristic
        (catalogue entries with no year at all)."""
        assert searcher.couldBeReleased(False, {}, year=None) is True


class TestConfigurableWaitAfterRelease:
    """BUG-017: the theatrical unlock was hardcoded at 12 weeks
    (`theater + 7257600 < now`), written when physical media was the target.

    Now that release dates are actually populated, that constant decides when
    every movie in a library becomes downloadable, so it is a setting rather
    than a magic number. Default 0 -- a film unlocks once its release date has
    passed; set 84 for the old behaviour.
    """

    def _released_days_ago(self, days):
        return {'theater': int(time.time()) - days * 86400, 'dvd': 0}

    def test_default_unlocks_once_the_release_date_has_passed(self):
        """AC12: yesterday's release is downloadable at the default."""
        searcher = object.__new__(MovieSearcher)

        result = searcher.couldBeReleased(
            False, self._released_days_ago(1), year=time.gmtime().tm_year,
        )
        assert result is True

    def test_future_release_is_not_downloadable_at_the_default(self):
        """AC14: the reported bug, end to end. An unreleased film must not be
        grabbed even though the default wait is zero."""
        searcher = object.__new__(MovieSearcher)
        future = {'theater': int(time.time()) + 30 * 86400, 'dvd': 0}

        result = searcher.couldBeReleased(
            False, future, year=time.gmtime().tm_year,
        )
        assert result is False

    def test_wait_days_holds_back_a_recent_release(self):
        """AC12: with a 7-day wait, yesterday's release is still too early."""
        searcher = object.__new__(MovieSearcher)

        result = searcher.couldBeReleased(
            False, self._released_days_ago(1),
            year=time.gmtime().tm_year, wait_days=7,
        )
        assert result is False

    def test_wait_days_elapses(self):
        """AC12: ...and is downloadable once the wait has elapsed."""
        searcher = object.__new__(MovieSearcher)

        result = searcher.couldBeReleased(
            False, self._released_days_ago(10),
            year=time.gmtime().tm_year, wait_days=7,
        )
        assert result is True

    def test_legacy_twelve_week_behaviour_is_reproducible(self):
        """The old hardcoded constant was 7257600s = 84 days. A user who
        wants it back must be able to get exactly it."""
        searcher = object.__new__(MovieSearcher)

        assert searcher.couldBeReleased(
            False, self._released_days_ago(83),
            year=time.gmtime().tm_year, wait_days=84,
        ) is False
        assert searcher.couldBeReleased(
            False, self._released_days_ago(85),
            year=time.gmtime().tm_year, wait_days=84,
        ) is True

    def test_wait_days_does_not_affect_the_pre_release_window(self):
        """The pre-release branch (cam/ts/scr, 1 week before theatres) is a
        separate rule about pre-release *qualities* and must not be shifted
        by a setting about waiting after release."""
        searcher = object.__new__(MovieSearcher)
        soon = {'theater': int(time.time()) + 3 * 86400, 'dvd': 0}

        assert searcher.couldBeReleased(
            True, soon, year=time.gmtime().tm_year, wait_days=30,
        ) is True

    @pytest.mark.parametrize('wait_days', [None, 0, '', 'abc'])
    def test_unusable_wait_values_fall_back_to_no_wait(self, searcher, wait_days):
        """The setting arrives from config as a string and may be blank.
        A junk value must mean 'no wait', never a crash or an infinite hold."""
        result = searcher.couldBeReleased(
            False, self._released_days_ago(1),
            year=time.gmtime().tm_year, wait_days=wait_days,
        )
        assert result is True


class TestWaitForReleaseSetting:
    """AC13 — the setting exists, is sane, and is actually wired up."""

    def _option(self, name):
        from couchpotato.core.media.movie.searcher import config

        for plugin in config:
            for group in plugin.get('groups', []):
                for option in group.get('options', []):
                    if option.get('name') == name:
                        return option
        raise AssertionError('%s option not found in config' % name)

    def test_setting_exists_and_defaults_to_no_wait(self):
        option = self._option('wait_for_release')

        assert option['default'] == 0
        assert option['type'] == 'int'

    def test_single_passes_the_setting_to_could_be_released(self):
        """A setting nothing reads is worse than no setting.

        This drives single() for real and asserts on the call, rather than
        grepping its source: a source check stays green if the value is read
        into a variable and then silently dropped before the call, which is
        exactly the regression worth guarding against.
        """
        from unittest.mock import MagicMock, patch

        from couchpotato.core.media.movie.searcher import MovieSearcher

        searcher = MovieSearcher.__new__(MovieSearcher)
        movie = {
            '_id': 'movie-1', 'title': 'Test', 'profile_id': 'profile-1',
            'status': 'active', 'releases': [],
            'info': {'year': 2026, 'titles': ['Test']},
            'identifiers': {'imdb': 'tt1234567'},
        }
        profile = {
            '_id': 'profile-1', 'qualities': ['1080p'], 'finish': [True],
            'wait_for': [0], 'stop_after': [0], '3d': [False],
            'minimum_score': 1,
        }

        def fake_fire_event(name, *args, **kwargs):
            return {
                'quality.pre_releases': [],
                'movie.update_release_dates': {'theater': 1, 'dvd': 0},
                'quality.single': {'identifier': '1080p', 'label': '1080p'},
                'searcher.search': [],
                'media.get': movie,
                'release.create_from_search': [],
                'release.try_download_result': False,
                'media.restatus': 'active',
            }.get(name)

        db = MagicMock()
        db.get.return_value = profile

        # 'always_search' must stay falsy or the ETA branch is skipped.
        conf = MagicMock(side_effect=lambda name, **kw: {
            'always_search': False, 'wait_for_release': 21,
        }.get(name))

        # With always_search falsy, single() takes the "ignore eta once every
        # 7 days" path, which reads Env.prop; float() needs a real number.
        env = MagicMock()
        env.prop.return_value = 0

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event), \
                patch('couchpotato.core.media.movie.searcher.get_db', return_value=db), \
                patch('couchpotato.core.media.movie.searcher.Env', env), \
                patch.object(searcher, 'conf', conf), \
                patch.object(searcher, 'couldBeReleased', return_value=True) as could:
            searcher.single(movie, search_protocols=['nzb'])

        assert could.called, 'single() must consult couldBeReleased'
        assert could.call_args.kwargs.get('wait_days') == 21, (
            'single() must pass the configured wait through, got %r'
            % (could.call_args,)
        )


class TestAlwaysSearchDescription:
    """AC7: `always_search` does not merely widen searching — at
    `MovieSearcher.single()` it is also one of the three conditions that
    authorise the download (`force_download or not could_not_be_released or
    always_search`). The description said only 'Search for movies even
    before there is a ETA', so a user could enable it expecting to review
    results manually and instead get automatic pre-ETA grabs.

    Behaviour is deliberately unchanged (people have configured around it);
    only the description is corrected. See specs/BUG-017.
    """

    def _always_search_option(self):
        from couchpotato.core.media.movie.searcher import config

        for plugin in config:
            for group in plugin.get('groups', []):
                for option in group.get('options', []):
                    if option.get('name') == 'always_search':
                        return option
        raise AssertionError('always_search option not found in config')

    def test_description_mentions_downloading_not_just_searching(self):
        description = self._always_search_option()['description'].lower()

        assert 'download' in description, (
            "always_search also bypasses the ETA gate for downloads; the "
            "description must say so, got: %r" % description
        )

    def test_default_is_still_off(self):
        """Regression guard: the honest description must not come with a
        quiet default flip."""
        assert self._always_search_option()['default'] is False


class TestCouldBeReleasedMissingDateKeys:
    """Latent TypeError hardening: `dates.get('theater')` / `dates.get('dvd')`
    without an explicit default return None for a dict that has other keys
    but is missing that particular one, and `None > 0` raises TypeError in
    Python 3. couldBeReleased() must tolerate partial `dates` dicts and
    return False rather than raising."""

    def test_pre_release_with_missing_theater_key_returns_false(self, searcher):
        """is_pre_release branch: 'theater' key absent (only 'dvd' present)
        must not raise and must return False, since an unknown theater date
        can never satisfy the 1-week-before-theater window."""
        result = searcher.couldBeReleased(
            True,
            {'dvd': 0},
            year=time.gmtime().tm_year,
        )
        assert result is False

    def test_non_pre_release_with_missing_dvd_key_returns_false(self, searcher):
        """Non-pre-release branch: 'dvd' key absent (only 'theater' present,
        and known-zero) must not raise and must return False."""
        result = searcher.couldBeReleased(
            False,
            {'theater': 0},
            year=time.gmtime().tm_year,
        )
        assert result is False
