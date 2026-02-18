"""Tests for searcher release matching logic."""

import pytest
from unittest.mock import MagicMock, patch


class TestCorrectName:
    """Test correctName() function for title matching."""

    @pytest.fixture
    def searcher(self):
        """Create a Searcher instance with mocked dependencies."""
        from couchpotato.core.media._base.searcher.main import Searcher
        s = Searcher()
        return s

    def test_exact_match(self, searcher):
        """Exact title match should return True."""
        with patch('couchpotato.core.media._base.searcher.main.fireEvent') as mock_fire:
            # scanner.name_year returns lowercase names (via simplifyString)
            mock_fire.return_value = {'name': 'the matrix', 'year': 1999}
            result = searcher.correctName('The.Matrix.1999.1080p.BluRay', 'The Matrix')
            assert result is True

    def test_sequel_number_mismatch_should_fail(self, searcher):
        """Sister Act (1992) should NOT match Sister Act 3."""
        with patch('couchpotato.core.media._base.searcher.main.fireEvent') as mock_fire:
            # Release parsed as "sister act" (no number)
            mock_fire.return_value = {'name': 'sister act', 'year': 1992}
            result = searcher.correctName('Sister.Act.1992.1080p.BluRay', 'Sister Act 3')
            assert result is False, "Sister Act (1992) should not match Sister Act 3"

    def test_sequel_number_mismatch_2_vs_3(self, searcher):
        """Sister Act 2 should NOT match Sister Act 3."""
        with patch('couchpotato.core.media._base.searcher.main.fireEvent') as mock_fire:
            mock_fire.return_value = {'name': 'sister act 2', 'year': 1993}
            result = searcher.correctName('Sister.Act.2.1993.1080p.BluRay', 'Sister Act 3')
            assert result is False, "Sister Act 2 should not match Sister Act 3"

    def test_sequel_correct_number_matches(self, searcher):
        """Sister Act 3 release should match Sister Act 3 movie."""
        with patch('couchpotato.core.media._base.searcher.main.fireEvent') as mock_fire:
            mock_fire.return_value = {'name': 'sister act 3', 'year': 2025}
            result = searcher.correctName('Sister.Act.3.2025.1080p.BluRay', 'Sister Act 3')
            assert result is True

    def test_numbered_sequel_original_should_not_match_sequel(self, searcher):
        """Toy Story should NOT match Toy Story 4."""
        with patch('couchpotato.core.media._base.searcher.main.fireEvent') as mock_fire:
            mock_fire.return_value = {'name': 'toy story', 'year': 1995}
            result = searcher.correctName('Toy.Story.1995.1080p.BluRay', 'Toy Story 4')
            assert result is False, "Toy Story should not match Toy Story 4"

    def test_word_title_sequel_roman_numeral(self, searcher):
        """Frozen should NOT match Frozen II (roman numeral)."""
        with patch('couchpotato.core.media._base.searcher.main.fireEvent') as mock_fire:
            mock_fire.return_value = {'name': 'frozen', 'year': 2013}
            result = searcher.correctName('Frozen.2013.1080p.BluRay', 'Frozen II')
            # Roman numerals (II) are handled differently - may need separate logic
            # For now, this should fail because 'ii' is missing from release
            assert result is False, "Frozen should not match Frozen II"

    def test_extra_word_in_release_fails(self, searcher):
        """Release with extra words should fail."""
        with patch('couchpotato.core.media._base.searcher.main.fireEvent') as mock_fire:
            mock_fire.return_value = {'name': 'avatar extended', 'year': 2009}
            result = searcher.correctName('Avatar.Extended.2009.1080p', 'Avatar')
            assert result is False, "Avatar Extended should not match Avatar"

    def test_minor_word_difference_allowed(self, searcher):
        """One word difference (non-number) should be allowed for flexibility."""
        with patch('couchpotato.core.media._base.searcher.main.fireEvent') as mock_fire:
            # Release: "the avengers" movie: "avengers" (missing "the")
            mock_fire.return_value = {'name': 'avengers', 'year': 2012}
            result = searcher.correctName('Avengers.2012.1080p.BluRay', 'The Avengers')
            # Should match - "the" is a minor word difference
            assert result is True, "Minor word difference should be allowed"
