from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.media.movie.providers.userscript.appletrailers import (
    AppleTrailers,
)


class TestAppleTrailersFilmId:

    def test_get_movie_does_not_shadow_python_builtins(self):
        assert 'id' not in AppleTrailers.getMovie.__code__.co_varnames

    def _provider(self, page):
        provider = object.__new__(AppleTrailers)
        provider.getUrl = MagicMock(return_value=page)
        provider.getJsonData = MagicMock(return_value={
            'page': {
                'movie_title': 'Example Movie',
                'release_date': '2026-07-12',
            },
        })
        provider.search = MagicMock(return_value='movie-result')
        return provider

    def test_valid_film_id_fetches_metadata_and_searches(self):
        provider = self._provider("prefix FilmId = '12345'; suffix")

        assert provider.getMovie('http://trailers.apple.test/example') == 'movie-result'
        provider.getJsonData.assert_called_once_with(
            'https://trailers.apple.com/trailers/feeds/data/12345.json',
        )
        provider.search.assert_called_once_with('Example Movie', 2026)

    def test_valid_film_id_from_http_response_bytes_fetches_metadata(self):
        provider = self._provider(b"prefix FilmId = '12345'; suffix")

        assert provider.getMovie('http://trailers.apple.test/example') == 'movie-result'
        provider.getJsonData.assert_called_once_with(
            'https://trailers.apple.com/trailers/feeds/data/12345.json',
        )

    def test_invalid_bytes_outside_film_id_do_not_hide_a_valid_id(self):
        provider = self._provider(b"\xff prefix FilmId = '12345'; suffix")

        assert provider.getMovie('http://trailers.apple.test/example') == 'movie-result'
        provider.getJsonData.assert_called_once_with(
            'https://trailers.apple.com/trailers/feeds/data/12345.json',
        )

    def test_parser_preserves_the_legacy_greedy_id_boundary(self):
        provider = self._provider("FilmId = 'first'; noise = 'second'; tail")

        provider.getMovie('http://trailers.apple.test/example')

        provider.getJsonData.assert_called_once_with(
            'https://trailers.apple.com/trailers/feeds/data/second.json',
        )

    @pytest.mark.parametrize(
        'page',
        [
            'FilmId without assignment',
            "FilmId = 'missing terminator'",
            "FilmId = '';",
            "FilmId =\n'cross-line';",
            b"FilmId = '\xff';",
            ('FilmId' + ('=' * 20_000) + ("'" * 20_000)),
        ],
    )
    def test_malformed_film_id_makes_no_metadata_request(self, page):
        provider = self._provider(page)

        with patch(
            'couchpotato.core.media.movie.providers.userscript.appletrailers.log.error',
        ) as error_log:
            assert provider.getMovie('http://trailers.apple.test/example') is None

        provider.getJsonData.assert_not_called()
        provider.search.assert_not_called()
        error_log.assert_not_called()

    def test_film_id_parsing_does_not_use_a_regular_expression(self):
        provider = self._provider("FilmId = '12345';")

        with patch(
            're.search',
            side_effect=AssertionError('FilmId parser used a regex'),
        ):
            assert provider.getMovie('http://trailers.apple.test/example') == 'movie-result'
