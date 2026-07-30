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


def _release(_id, protocol = 'nzb', quality = '1080p', status = 'available',
             score = 100, size = 4000, seeders = None, age = 3, name = None):
    """A release document in the shape `release.for_media` returns."""
    info = {'protocol': protocol, 'score': score, 'size': size, 'age': age,
            'name': name or '%s.release' % _id}
    if seeders is not None:
        info['seeders'] = seeders
    return {'_id': _id, 'quality': quality, 'status': status, 'info': info}


def _ids(releases):
    return [r['_id'] for r in releases]


class TestFilterReleases:

    def test_defaults_return_everything_in_the_given_order(self):
        """B1."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('a'), _release('b', protocol = 'torrent')]
        assert _ids(filter_and_sort_releases(releases, DEFAULT_CONTROLS)) == ['a', 'b']

    def test_source_nzb_returns_only_nzb(self):
        """B2."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('n', 'nzb'), _release('t', 'torrent'), _release('m', 'torrent_magnet')]
        controls = dict(DEFAULT_CONTROLS, source = 'nzb')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['n']

    def test_source_torrent_includes_magnets(self):
        """B2: torrent_magnet is a torrent."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('n', 'nzb'), _release('t', 'torrent'), _release('m', 'torrent_magnet')]
        controls = dict(DEFAULT_CONTROLS, source = 'torrent')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['t', 'm']

    def test_a_release_with_an_unknown_protocol_is_excluded_by_either_source_filter(self):
        """It is neither nzb nor torrent, so it matches neither."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('u', ''), _release('n', 'nzb')]
        assert _ids(filter_and_sort_releases(releases, dict(DEFAULT_CONTROLS, source = 'nzb'))) == ['n']
        assert _ids(filter_and_sort_releases(releases, dict(DEFAULT_CONTROLS, source = 'torrent'))) == []
        # ...but 'all' still shows it, so it is never invisible.
        assert _ids(filter_and_sort_releases(releases, DEFAULT_CONTROLS)) == ['u', 'n']

    def test_quality_filter_matches_the_identifier(self):
        """B3."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('hd', quality = '1080p'), _release('uhd', quality = '2160p')]
        controls = dict(DEFAULT_CONTROLS, quality = '2160p')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['uhd']

    def test_quality_filter_tolerates_a_dict_shaped_quality(self):
        """Release docs store a string (release/main.py:183,:501) but the
        template defends against a dict (movie_detail.html:279), so the
        filter reads the identifier out of either shape.
        """
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [{'_id': 'd', 'quality': {'identifier': '1080p'}, 'status': 'available', 'info': {}}]
        controls = dict(DEFAULT_CONTROLS, quality = '1080p')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['d']

    def test_status_filter(self):
        """B3."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('a', status = 'available'), _release('i', status = 'ignored')]
        controls = dict(DEFAULT_CONTROLS, status = 'ignored')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['i']

    def test_all_three_filters_compose(self):
        """B3: applied together, not last-one-wins."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [
            _release('want', 'nzb', '1080p', 'available'),
            _release('wrong_source', 'torrent', '1080p', 'available'),
            _release('wrong_quality', 'nzb', '720p', 'available'),
            _release('wrong_status', 'nzb', '1080p', 'ignored'),
        ]
        controls = dict(DEFAULT_CONTROLS, source = 'nzb', quality = '1080p', status = 'available')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['want']

    def test_filtering_never_mutates_the_input(self):
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('a'), _release('b', protocol = 'torrent')]
        filter_and_sort_releases(releases, dict(DEFAULT_CONTROLS, source = 'nzb'))
        assert _ids(releases) == ['a', 'b']

    def test_an_empty_list_is_safe(self):
        from couchpotato.ui.releases_view import filter_and_sort_releases

        assert filter_and_sort_releases([], DEFAULT_CONTROLS) == []


class TestSortReleases:

    def test_sort_default_preserves_the_incoming_order(self):
        """B1: 'default' is Part A's output -- score then protocol preference.

        `dir` is ignored here rather than reversing it: reversing would
        silently invert the user's configured download-source preference.
        """
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('a', score = 1), _release('b', score = 999)]
        assert _ids(filter_and_sort_releases(releases, DEFAULT_CONTROLS)) == ['a', 'b']
        controls = dict(DEFAULT_CONTROLS, dir = 'asc')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['a', 'b']

    @pytest.mark.parametrize('sort, expected_desc', [
        ('score', ['big', 'small']),
        ('size', ['big', 'small']),
        ('seeders', ['big', 'small']),
        ('age', ['big', 'small']),
    ])
    def test_numeric_sorts_in_both_directions(self, sort, expected_desc):
        """B4."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        big = _release('big', protocol = 'torrent', score = 900, size = 9000, seeders = 90, age = 90)
        small = _release('small', protocol = 'torrent', score = 1, size = 10, seeders = 1, age = 1)
        releases = [small, big]

        desc = filter_and_sort_releases(releases, dict(DEFAULT_CONTROLS, sort = sort, dir = 'desc'))
        assert _ids(desc) == expected_desc

        asc = filter_and_sort_releases(releases, dict(DEFAULT_CONTROLS, sort = sort, dir = 'asc'))
        assert _ids(asc) == list(reversed(expected_desc))

    def test_fractional_sizes_and_scores_are_not_truncated(self):
        """The same trap Part A hit with tryInt."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('lower', score = 300.2), _release('higher', score = 300.8)]
        controls = dict(DEFAULT_CONTROLS, sort = 'score', dir = 'desc')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['higher', 'lower']

    def test_name_sorts_case_insensitively(self):
        """B4."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('b', name = 'beta.release'), _release('A', name = 'Alpha.release')]
        controls = dict(DEFAULT_CONTROLS, sort = 'name', dir = 'asc')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['A', 'b']

    def test_source_and_status_sort_alphabetically_by_their_displayed_value(self):
        """B4."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('t', 'torrent'), _release('n', 'nzb')]
        controls = dict(DEFAULT_CONTROLS, sort = 'source', dir = 'asc')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['n', 't']

    def test_quality_sorts_by_profile_order_not_alphabetically(self):
        """B4: '1080p' < '720p' as strings, which would be wrong.

        The profile's qualities list is ordered best-first, so index in it is
        the meaningful key.
        """
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('hd', quality = '720p'), _release('fhd', quality = '1080p')]
        controls = dict(DEFAULT_CONTROLS, sort = 'quality', dir = 'asc')
        got = filter_and_sort_releases(releases, controls, profile_qualities = ['1080p', '720p'])
        assert _ids(got) == ['fhd', 'hd']

    def test_quality_sort_without_a_profile_falls_back_to_the_identifier(self):
        """A movie with no profile must still sort, not crash."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('b', quality = '720p'), _release('a', quality = '1080p')]
        controls = dict(DEFAULT_CONTROLS, sort = 'quality', dir = 'asc')
        got = filter_and_sort_releases(releases, controls)
        assert _ids(got) == ['a', 'b']

    @pytest.mark.parametrize('direction', ['asc', 'desc'])
    @pytest.mark.parametrize('sort', ['size', 'seeders', 'score', 'age', 'name'])
    def test_releases_missing_the_sorted_field_go_last_in_both_directions(self, sort, direction):
        """B5: absent data must never lead the list.

        A naive sorted(reverse=True) puts the missing group FIRST, which is
        the bug this pins.
        """
        from couchpotato.ui.releases_view import filter_and_sort_releases

        present = _release('present', protocol = 'torrent', score = 50, size = 50, seeders = 50, age = 50)
        missing = {'_id': 'missing', 'quality': '1080p', 'status': 'available', 'info': {}}
        releases = [missing, present]

        controls = dict(DEFAULT_CONTROLS, sort = sort, dir = direction)
        assert _ids(filter_and_sort_releases(releases, controls))[-1] == 'missing'

    def test_an_nzb_has_no_seeders_so_it_sorts_last_by_seeders(self):
        """B9's data reality: seeders is a torrent-only field."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('n', 'nzb'), _release('t', 'torrent', seeders = 5)]
        for direction in ('asc', 'desc'):
            controls = dict(DEFAULT_CONTROLS, sort = 'seeders', dir = direction)
            assert _ids(filter_and_sort_releases(releases, controls))[-1] == 'n'

    def test_a_none_valued_field_counts_as_missing_rather_than_raising(self):
        """B5."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [
            {'_id': 'null', 'quality': '1080p', 'status': 'available', 'info': {'size': None}},
            _release('ok', size = 10),
        ]
        controls = dict(DEFAULT_CONTROLS, sort = 'size', dir = 'desc')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['ok', 'null']

    def test_sorting_is_stable_for_equal_values(self):
        """Equal keys keep their incoming (Part A preference) order."""
        from couchpotato.ui.releases_view import filter_and_sort_releases

        releases = [_release('first', size = 100), _release('second', size = 100)]
        controls = dict(DEFAULT_CONTROLS, sort = 'size', dir = 'desc')
        assert _ids(filter_and_sort_releases(releases, controls)) == ['first', 'second']
