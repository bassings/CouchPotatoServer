"""Filtering and sorting for the movie-detail release list (FEAT-007 Part B).

Everything here is pure: a list of release documents in, a list out. The
route and the template are thin wrappers, so this is where the behaviour is
pinned.

Control values arrive from a URL that can be bookmarked, shared, or
hand-edited, so every one of them must degrade to a default rather than
raise -- a 500 on the movie detail page is not an acceptable response to a
stale bookmark.
"""

import pytest

from couchpotato.ui.releases_view import DEFAULT_CONTROLS, normalise_controls


class TestNormaliseControls:

    def test_no_input_yields_the_documented_defaults(self):
        assert normalise_controls({}) == DEFAULT_CONTROLS

    def test_defaults_are_the_no_op_view(self):
        """B1: defaults must reproduce today's page exactly."""
        assert DEFAULT_CONTROLS == {
            'source': 'all',
            'quality': 'all',
            'status': 'all',
            'sort': 'default',
            'dir': 'desc',
        }

    @pytest.mark.parametrize('field, value', [
        ('source', 'nzb'),
        ('source', 'torrent'),
        ('quality', '1080p'),
        ('status', 'available'),
        ('sort', 'size'),
        ('sort', 'seeders'),
        ('dir', 'asc'),
    ])
    def test_valid_values_are_kept(self, field, value):
        assert normalise_controls({field: value})[field] == value

    @pytest.mark.parametrize('field, bad', [
        ('source', 'usenet'),
        ('source', ''),
        ('source', None),
        ('sort', 'name; DROP TABLE'),
        ('sort', '__class__'),
        ('sort', ''),
        ('dir', 'sideways'),
        ('dir', ''),
        ('status', 'nonsense'),
    ])
    def test_unrecognised_values_fall_back_to_the_default(self, field, bad):
        """B6: a hand-edited or stale URL must not break the page."""
        assert normalise_controls({field: bad})[field] == DEFAULT_CONTROLS[field]

    def test_quality_is_not_whitelisted_because_it_is_data_driven(self):
        """Quality identifiers come from the library, not a fixed list.

        An unknown quality is therefore kept and simply matches nothing,
        rather than being silently rewritten to 'all' -- which would show
        the user everything and look like the filter was ignored.
        """
        assert normalise_controls({'quality': 'some-future-quality'})['quality'] == 'some-future-quality'

    def test_a_non_string_quality_falls_back(self):
        assert normalise_controls({'quality': ['1080p']})['quality'] == 'all'

    def test_values_are_stripped_and_lowercased_where_that_is_safe(self):
        got = normalise_controls({'source': ' NZB ', 'dir': ' ASC '})
        assert got['source'] == 'nzb'
        assert got['dir'] == 'asc'

    def test_extra_unknown_keys_are_ignored(self):
        got = normalise_controls({'source': 'nzb', 'evil': 'x'})
        assert 'evil' not in got
        assert got['source'] == 'nzb'
