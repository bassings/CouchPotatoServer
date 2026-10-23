"""Contracts for the TMDB provider paths targeted by complexity refactoring."""

from unittest.mock import call, patch

import pytest

from couchpotato.core.media.movie.providers.info.themoviedb import TheMovieDb


@pytest.fixture
def provider():
    instance = TheMovieDb.__new__(TheMovieDb)
    instance.configuration = {
        "images": {"secure_base_url": "https://image.tmdb.org/t/p/"}
    }
    instance.languages = []
    instance.default_language = "en"
    return instance


def test_trailer_resolves_imdb_and_prefers_youtube_trailer(provider):
    videos = [
        {"site": "YouTube", "type": "Teaser", "key": "teaser"},
        {"site": "Vimeo", "type": "Trailer", "key": "vimeo"},
        {"site": "YouTube", "type": "Trailer", "key": "trailer", "name": "Official"},
    ]
    with patch.object(
        provider,
        "request",
        side_effect=[{"movie_results": [{"id": 700}]}, videos],
    ) as request:
        result = provider.getTrailer(identifier="tt0000700")

    assert result == {
        "success": True,
        "video_id": "trailer",
        "title": "Official",
        "thumbnail": "https://img.youtube.com/vi/trailer/hqdefault.jpg",
        "url": "https://www.youtube.com/watch?v=trailer",
    }
    assert request.call_args_list == [
        call("find/tt0000700", params={"external_source": "imdb_id"}),
        call("movie/700/videos", return_key="results"),
    ]


@pytest.mark.parametrize(
    ("videos", "selected"),
    [
        (
            [
                {"site": "YouTube", "type": "Featurette", "key": "feature"},
                {"site": "YouTube", "type": "Teaser", "key": "teaser"},
            ],
            "teaser",
        ),
        ([{"site": "YouTube", "type": "Featurette", "key": "feature"}], "feature"),
    ],
)
def test_trailer_falls_back_to_teaser_then_other_youtube_video(
    provider, videos, selected
):
    with patch.object(provider, "request", return_value=videos) as request:
        result = provider.getTrailer(id="700")

    assert result["video_id"] == selected
    assert result["title"] == ""
    request.assert_called_once_with("movie/700/videos", return_key="results")


def test_trailer_missing_identifier_mapping_and_videos_return_failure(provider):
    with patch.object(provider, "request") as request:
        assert provider.getTrailer() == {"success": False}
    request.assert_not_called()

    with patch.object(provider, "request", return_value={"movie_results": []}) as request:
        assert provider.getTrailer(identifier="tt0000700") == {"success": False}
    request.assert_called_once_with(
        "find/tt0000700", params={"external_source": "imdb_id"}
    )

    with patch.object(provider, "request", return_value=[]) as request:
        assert provider.getTrailer(identifier="700") == {"success": False}
    request.assert_called_once_with("movie/700/videos", return_key="results")


def test_search_parse_error_keeps_false_result_and_request_parameters(provider):
    with patch.object(provider, "isDisabled", return_value=False), patch(
        "couchpotato.core.media.movie.providers.info.themoviedb.fireEvent",
        return_value={"name": "Film", "year": 2001},
    ), patch.object(provider, "request", return_value=[{"id": 700}]) as request, patch.object(
        provider, "parseMovie", side_effect=SyntaxError("invalid metadata")
    ):
        result = provider.search("Film", limit=1)

    assert result is False
    request.assert_called_once_with(
        "search/movie",
        {"query": "Film", "year": 2001, "search_type": "phrase"},
        return_key="results",
    )


def test_parse_movie_keeps_missing_year_and_skips_bad_cast_item(provider):
    movie = {
        "id": 700,
        "title": "Sample",
        "original_title": "Original",
        "release_date": "1900-01-01",
        "alternative_titles": {"titles": [{"title": "Alias"}]},
        "casts": {
            "cast": [
                None,
                {
                    "name": "Actor",
                    "character": "Role",
                    "profile_path": "/actor.jpg",
                },
            ]
        },
    }
    with patch.object(provider, "request", return_value=movie) as request:
        result = provider.parseMovie({"id": 700}, extended=True)

    assert result["released"] == "1900-01-01"
    assert "year" not in result
    assert result["titles"] == ["Sample", "Alias", "Original"]
    assert result["actor_roles"] == {"Actor": "Role"}
    assert result["images"]["actors"] == {
        "Actor": "https://image.tmdb.org/t/p/original/actor.jpg"
    }
    request.assert_called_once_with(
        "movie/700",
        {"append_to_response": "alternative_titles,images,casts", "language": "en"},
    )
