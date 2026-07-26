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
