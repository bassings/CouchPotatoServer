"""Regression coverage for release-name quote extraction (GitHub #327)."""

from unittest.mock import patch

import pytest

from couchpotato.core.media._base.searcher.main import Searcher
from couchpotato.core.plugins.score.scores import namePositionScore, sceneScore


pytestmark = pytest.mark.unit


def test_searcher_uses_the_nearest_matching_quote_candidate():
    seen = []

    def scanner_result(event, value, single=False):
        assert event == 'scanner.name_year'
        seen.append(value)
        if value == '"Title"':
            return {'name': 'title', 'year': 2024}
        return {'name': 'movie title group', 'year': 2024}

    with patch('couchpotato.core.media._base.searcher.main.fireEvent', side_effect=scanner_result):
        assert Searcher().correctName('Movie "Title" 2024 "GROUP"', 'Title') is True

    assert '"Title"' in seen
    assert '"Title" 2024 "GROUP"' not in seen


@pytest.mark.parametrize(
    ('quoted_name', 'parsed_name', 'movie_name'),
    [
        ("'Ocean's Eleven 2001 1080p-GRP'", 'oceans eleven', 'Oceans Eleven'),
        (r"'Ocean\'s Eleven 2001 1080p-GRP'", 'oceans eleven', 'Oceans Eleven'),
        (r"'Girls\' Night Out 1998 1080p-GRP'", 'girls night out', 'Girls Night Out'),
    ],
)
def test_searcher_preserves_apostrophes_inside_single_quoted_candidates(quoted_name, parsed_name, movie_name):
    seen = []

    def scanner_result(event, value, single=False):
        assert event == 'scanner.name_year'
        seen.append(value)
        if value == quoted_name:
            return {'name': parsed_name, 'year': 2001}
        return {'name': 'unrelated release', 'year': 2001}

    with patch('couchpotato.core.media._base.searcher.main.fireEvent', side_effect=scanner_result):
        assert Searcher().correctName('Prefix ' + quoted_name, movie_name) is True

    assert quoted_name in seen


def test_scorer_uses_the_same_nearest_matching_quote_candidate():
    validated = []

    def score_result(event, value, single=False):
        assert event == 'release.validate'
        validated.append(value)
        if value == 'title 2024-group':
            return {'score': 12, 'reasons': ['test']}
        return {'score': 0, 'reasons': []}

    with patch('couchpotato.core.plugins.score.scores.fireEvent', side_effect=score_result):
        assert sceneScore('Other.Movie.2023-X "Title 2024-GROUP" "EXTRA"') == 12

    assert 'title 2024-group' in validated
    assert 'title 2024-group" "extra' not in validated


def test_name_position_score_uses_the_nearest_matching_quote_pair():
    scanner_inputs = []

    def score_inputs(event, value=None, single=False):
        if event == 'quality.all':
            return []
        assert event == 'scanner.name_year'
        scanner_inputs.append(value)
        return None

    with patch('couchpotato.core.plugins.score.scores.fireEvent', side_effect=score_inputs):
        namePositionScore('"Title" 2024 "GROUP"', 'Title')

    assert scanner_inputs == ['"Title"']
