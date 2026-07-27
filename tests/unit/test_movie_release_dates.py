"""Tests for release-date population (BUG-017).

`MovieBase.updateReleaseDate()` fires `movie.info.release_date` to obtain the
`{theater, dvd}` epoch mapping the ETA gate reads. **Nothing in the codebase
registers a handler for that event**, and `fireEvent` returns `[]` for an
unhandled name, so the mapping was empty for every movie on every search —
which made `couldBeReleased()` a no-op that authorised every download.

The date itself was always there: the info provider stores TMDB's
`release_date` as `info['released']` ('YYYY-MM-DD', or the literal string
'None' when TMDB has no date, because it is written via `str()`). These tests
cover deriving the mapping from it.

See specs/BUG-017-eta-unknown-release-dates.md.
"""

import calendar
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.media.movie._base.main import releaseDatesFromInfo


def _epoch(year, month, day):
    return calendar.timegm((year, month, day, 0, 0, 0, 0, 0, 0))


class TestReleaseDatesFromInfo:

    def test_parses_an_iso_date_to_utc_midnight(self):
        """AC8: the happy path — TMDB's 'YYYY-MM-DD'."""
        dates = releaseDatesFromInfo({'released': '2026-08-14'})

        assert dates['theater'] == _epoch(2026, 8, 14)

    def test_leaves_dvd_unknown(self):
        """The info provider gives one date. Claiming a dvd date we don't
        have would unlock the '4 weeks before dvd' early-download path on a
        fabricated value."""
        dates = releaseDatesFromInfo({'released': '2026-08-14'})

        assert dates['dvd'] == 0

    def test_is_timezone_independent(self):
        """The gate compares against `int(time.time())`, which is UTC. Using
        a local-time parse would shift the unlock by up to a day and make
        behaviour depend on the server's TZ."""
        dates = releaseDatesFromInfo({'released': '1970-01-02'})

        assert dates['theater'] == 86400

    @pytest.mark.parametrize('info', [
        {},
        {'released': ''},
        {'released': None},
        {'released': 'None'},          # str(None) from the TMDB provider
        {'released': 'none'},
        {'released': 'not-a-date'},
        {'released': '2026-13-45'},    # well-formed shape, impossible date
        {'released': '2026'},
        {'released': 12345},           # not a string at all
        {'released': ['2026-08-14']},
    ], ids=lambda i: repr(i.get('released', '<missing>')))
    def test_unparseable_input_yields_empty_without_raising(self, info):
        """AC9: anything we cannot read must degrade to "unknown", never
        raise into a search cycle and never invent a date.

        'None' matters most: `str(movie.get('release_date'))` in the TMDB
        provider turns a missing date into that literal string, and it is
        truthy, so a naive check would treat it as a real value.
        """
        assert releaseDatesFromInfo(info) == {}

    def test_tolerates_a_non_dict(self):
        assert releaseDatesFromInfo(None) == {}

    def test_rejects_the_tmdb_1900_placeholder(self):
        """TMDB uses 1900-01-01 to mean "no release date". The provider
        already knows this -- themoviedb.py has `# 1900 is the same as None`
        and nulls `year` for it -- but it still writes the placeholder to
        `released`.

        Taking it literally is not merely wrong, it reopens this very bug:
        1900 is a NEGATIVE epoch, and couldBeReleased() treats a negative
        date as the pre-1972 "definitely already out" sentinel and returns
        True before any wait is applied. So an unknown release date would
        once again authorise an immediate download.
        """
        assert releaseDatesFromInfo({'released': '1900-01-01'}) == {}

    @pytest.mark.parametrize('released', [
        '1900-01-01', '1899-12-31', '1965-06-01', '1969-12-31',
    ])
    def test_rejects_pre_epoch_dates(self, released):
        """More generally: never derive a negative epoch, because it collides
        with the pre-1972 sentinel. Genuinely old films are not harmed -- an
        old `year` routes them to couldBeReleased()'s "old movie, no dates"
        heuristic, which assumes released. Being unknown is the right answer
        here; being negative is an assertion we don't want to make."""
        assert releaseDatesFromInfo({'released': released}) == {}

    def test_accepts_the_first_representable_date(self):
        """The boundary: 1970-01-01 is epoch 0, which is not negative and so
        does not trip the sentinel."""
        assert releaseDatesFromInfo({'released': '1970-01-01'}) == {
            'theater': 0, 'dvd': 0,
        }

    @pytest.mark.parametrize('released', [
        '2026-02-30',   # February never has 30 days
        '2026-04-31',   # April has 30
        '2023-02-29',   # not a leap year
    ], ids=['feb-30', 'apr-31', 'non-leap-feb-29'])
    def test_rejects_impossible_days_for_the_month(self, released):
        """`timegm` silently NORMALISES an impossible day rather than
        raising -- 2026-02-30 becomes 2026-03-02 -- so a day <= 31 check is
        not enough. A quietly shifted unlock date is worse than a rejected
        one, because nothing surfaces it."""
        assert releaseDatesFromInfo({'released': released}) == {}

    @pytest.mark.parametrize('released', [
        '10000-01-01',      # one past datetime's ceiling
        '99999999-06-15',
    ])
    def test_rejects_years_outside_the_representable_range(self, released):
        """calendar.monthrange/timegm raise ValueError above year 9999
        (`year must be in 1..9999`). This function promises never to raise --
        a provider returning a nonsense year must degrade to "unknown", not
        throw an exception up into the search loop once per movie."""
        assert releaseDatesFromInfo({'released': released}) == {}

    def test_accepts_the_last_representable_year(self):
        """The boundary on the other side stays usable."""
        dates = releaseDatesFromInfo({'released': '9999-12-31'})

        assert dates['theater'] == _epoch(9999, 12, 31)

    def test_accepts_a_real_leap_day(self):
        """The mirror of the above: 2024 IS a leap year, so this is valid and
        must not be rejected by an over-eager guard."""
        dates = releaseDatesFromInfo({'released': '2024-02-29'})

        assert dates['theater'] == _epoch(2024, 2, 29)

    def test_accepts_a_datetime_style_string(self):
        """Some providers append a time component; take the date part."""
        dates = releaseDatesFromInfo({'released': '2026-08-14 00:00:00'})

        assert dates['theater'] == _epoch(2026, 8, 14)


class TestUpdateReleaseDateFallback:
    """AC10/AC11 — the wiring in MovieBase.updateReleaseDate()."""

    def _media(self, released='2026-08-14', cached=None):
        info = {'released': released, 'year': 2026}
        if cached is not None:
            info['release_date'] = cached
        return {
            '_t': 'movie',
            '_id': 'movie-1',
            '_rev': '001',
            'identifiers': {'imdb': 'tt1234567'},
            'info': info,
        }

    def _run(self, media, event_result):
        """Drive updateReleaseDate with a mocked db and event bus."""
        from couchpotato.core.media.movie._base.main import MovieBase

        plugin = object.__new__(MovieBase)
        db = MagicMock()
        db.get.return_value = media

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent',
                      return_value=event_result) as fire:
            result = plugin.updateReleaseDate('movie-1')

        return result, db, fire

    def test_falls_back_to_derived_dates_when_event_is_unhandled(self):
        """AC10 (bug repro): `[]` is what an unhandled fireEvent returns, and
        it is what this event returns in production. The derived date must be
        used instead of surfacing the empty list."""
        result, _, _ = self._run(self._media(), event_result=[])

        assert result['theater'] == _epoch(2026, 8, 14)

    def test_does_not_write_derived_dates_back_to_the_document(self):
        """AC10: deriving is free, so persisting it would just be a db write
        per movie per search cycle -- which is what the old code did with the
        useless empty result."""
        _, db, _ = self._run(self._media(), event_result=[])

        db.update.assert_not_called()

    def test_a_real_provider_result_wins_over_the_fallback(self):
        """AC11: if a provider ever implements the event, its answer is
        authoritative -- it may know a dvd date, which we never derive."""
        provided = {'theater': 111, 'dvd': 222, 'expires': 999}

        result, db, _ = self._run(self._media(), event_result=provided)

        assert result == provided
        db.update.assert_called_once()

    def test_returns_empty_when_nothing_is_derivable(self):
        """No usable date anywhere -> unknown. couldBeReleased() then treats
        the movie as not-yet-released unless it is old enough to hit the
        'old movie' heuristic."""
        result, _, _ = self._run(self._media(released='None'), event_result=[])

        assert result == {}

    def test_ignores_a_stale_empty_list_cached_by_previous_versions(self):
        """Existing databases have `release_date: []` written by the old code
        on every search. That must not be mistaken for a valid cached value."""
        result, _, _ = self._run(
            self._media(cached=[]), event_result=[],
        )

        assert result['theater'] == _epoch(2026, 8, 14)
