"""The download-source preference (`searcher.preferred_method`) ordering.

FEAT-007 Part A. The preference is a HARD preference that FALLS BACK: every
release of the preferred protocol outranks every release of the other one,
but when the preferred protocol has nothing usable the other is still used.

Before this change the ordering was hand-rolled twice — in `Searcher.search()`
and in `Release.forMedia()` — using a `protocol[:3]` string trick against two
different key paths, with no test coverage at all. The two copies disagreed on
unknown protocols: sorting `''` ascending floated unknown-protocol releases
ABOVE nzb when preferring usenet, and buried them when preferring torrents.
"""

import pytest

from couchpotato.core.helpers.protocol import sort_by_protocol_preference


def _items(*protocols):
    """Items in descending-score order, as both call sites hand them over.

    `pos` records the incoming order so stability can be asserted.
    """
    return [{'pos': i, 'protocol': p} for i, p in enumerate(protocols)]


def _get(item):
    return item.get('protocol')


def _protocols(items):
    return [item['protocol'] for item in items]


class TestSortByProtocolPreference:

    def test_nzb_preference_puts_every_nzb_before_every_torrent(self):
        """A1: hard preference — even a last-place nzb beats a first-place torrent."""
        items = _items('torrent', 'torrent', 'nzb', 'torrent')
        result = sort_by_protocol_preference(items, 'nzb', _get)
        assert _protocols(result) == ['nzb', 'torrent', 'torrent', 'torrent']

    def test_torrent_preference_puts_every_torrent_before_every_nzb(self):
        """A2: the mirror image."""
        items = _items('nzb', 'nzb', 'torrent', 'nzb')
        result = sort_by_protocol_preference(items, 'torrent', _get)
        assert _protocols(result) == ['torrent', 'nzb', 'nzb', 'nzb']

    def test_both_leaves_the_incoming_order_untouched(self):
        """A3: 'both' means score order only — the caller already sorted by score."""
        items = _items('torrent', 'nzb', 'torrent', 'nzb')
        result = sort_by_protocol_preference(items, 'both', _get)
        assert _protocols(result) == ['torrent', 'nzb', 'torrent', 'nzb']
        assert [i['pos'] for i in result] == [0, 1, 2, 3]

    def test_score_order_is_preserved_within_each_protocol_group(self):
        """A4: the sort must be stable — callers sort by score first, then by protocol.

        An unstable sort here would silently scramble score ranking within a
        group, which is the whole basis for picking a release.
        """
        items = _items('torrent', 'nzb', 'torrent', 'nzb', 'torrent')
        result = sort_by_protocol_preference(items, 'nzb', _get)
        assert [i['pos'] for i in result] == [1, 3, 0, 2, 4]

    def test_torrent_magnet_ranks_with_torrent(self):
        """A5: a magnet link is a torrent as far as the preference is concerned."""
        items = _items('torrent_magnet', 'nzb')
        assert _protocols(sort_by_protocol_preference(items, 'nzb', _get)) == ['nzb', 'torrent_magnet']
        assert _protocols(sort_by_protocol_preference(items, 'torrent', _get)) == ['torrent_magnet', 'nzb']

    def test_unknown_protocol_sorts_last_when_preferring_nzb(self):
        """A6: the bug being fixed — `''` used to sort BEFORE 'nzb' ascending."""
        items = _items('mystery', 'torrent', 'nzb')
        result = sort_by_protocol_preference(items, 'nzb', _get)
        assert _protocols(result) == ['nzb', 'torrent', 'mystery']

    def test_unknown_protocol_sorts_last_when_preferring_torrent_too(self):
        """A6: unknown is last in BOTH directions, not direction-dependent."""
        items = _items('mystery', 'torrent', 'nzb')
        result = sort_by_protocol_preference(items, 'torrent', _get)
        assert _protocols(result) == ['torrent', 'nzb', 'mystery']

    @pytest.mark.parametrize('bad', [None, '', '   ', 'ftp'])
    def test_missing_or_unrecognised_protocols_are_treated_as_unknown(self, bad):
        """A6: absent data must not outrank real data."""
        items = _items(bad, 'nzb')
        result = sort_by_protocol_preference(items, 'nzb', _get)
        assert _protocols(result) == ['nzb', bad]

    def test_protocol_matching_is_case_and_whitespace_insensitive(self):
        """Provider data is not guaranteed to be normalised."""
        items = _items('torrent', ' NZB ')
        result = sort_by_protocol_preference(items, 'nzb', _get)
        assert _protocols(result) == [' NZB ', 'torrent']

    @pytest.mark.parametrize('preference', ['both', 'nzb', 'torrent', None, '', 'nonsense'])
    def test_empty_and_single_item_lists_are_safe(self, preference):
        """A8: no crash on the degenerate cases, for any preference value."""
        assert sort_by_protocol_preference([], preference, _get) == []
        single = _items('nzb')
        assert _protocols(sort_by_protocol_preference(single, preference, _get)) == ['nzb']

    @pytest.mark.parametrize('preference', [None, '', 'nonsense'])
    def test_an_unrecognised_preference_behaves_as_no_preference(self, preference):
        """A config read can return None/'' before defaults are applied.

        The safe reading of "I don't understand this setting" is "don't
        reorder", never "reorder arbitrarily".
        """
        items = _items('torrent', 'nzb', 'torrent')
        result = sort_by_protocol_preference(items, preference, _get)
        assert _protocols(result) == ['torrent', 'nzb', 'torrent']

    def test_the_input_list_is_not_mutated(self):
        """Callers reuse their list; sorting must return a new one."""
        items = _items('torrent', 'nzb')
        sort_by_protocol_preference(items, 'nzb', _get)
        assert _protocols(items) == ['torrent', 'nzb']


class TestSearcherSearchOrdering:
    """`Searcher.search()` — the order here decides what gets downloaded."""

    @pytest.fixture
    def searcher(self):
        # __init__ registers events and API views; bypass it.
        from couchpotato.core.media._base.searcher.main import Searcher
        return object.__new__(Searcher)

    def _search(self, searcher, preference, results):
        """Drive search() with one provider event per protocol, as in production."""
        from unittest.mock import patch

        def fake_fire_event(event, *args, **kwargs):
            if event == 'provider.search.nzb.movie':
                return [r for r in results if r['protocol'] == 'nzb']
            if event == 'provider.search.torrent.movie':
                return [r for r in results if r['protocol'] != 'nzb']
            return []

        with patch('couchpotato.core.media._base.searcher.main.fireEvent',
                   side_effect = fake_fire_event), \
                patch.object(searcher, 'conf', return_value = preference):
            return searcher.search(['nzb', 'torrent'], {'type': 'movie'}, {'identifier': '1080p'})

    def test_nzb_preference_orders_nzb_first_regardless_of_score(self, searcher):
        """A1: a 900-seeder torrent scoring 3400 still loses to a 210-score nzb."""
        results = [
            {'name': 'big.torrent', 'protocol': 'torrent', 'score': 3400},
            {'name': 'good.nzb', 'protocol': 'nzb', 'score': 210},
        ]
        ordered = self._search(searcher, 'nzb', results)
        assert [r['name'] for r in ordered] == ['good.nzb', 'big.torrent']

    def test_torrent_preference_orders_torrents_first(self, searcher):
        """A2."""
        results = [
            {'name': 'big.nzb', 'protocol': 'nzb', 'score': 3400},
            {'name': 'ok.torrent', 'protocol': 'torrent', 'score': 210},
        ]
        ordered = self._search(searcher, 'torrent', results)
        assert [r['name'] for r in ordered] == ['ok.torrent', 'big.nzb']

    def test_both_preserves_pure_score_order(self, searcher):
        """A3."""
        results = [
            {'name': 'mid.nzb', 'protocol': 'nzb', 'score': 500},
            {'name': 'big.torrent', 'protocol': 'torrent', 'score': 3400},
            {'name': 'small.torrent', 'protocol': 'torrent', 'score': 10},
        ]
        ordered = self._search(searcher, 'both', results)
        assert [r['name'] for r in ordered] == ['big.torrent', 'mid.nzb', 'small.torrent']

    def test_score_order_survives_inside_the_preferred_group(self, searcher):
        """A4 at the call site, not just in the helper."""
        results = [
            {'name': 'best.nzb', 'protocol': 'nzb', 'score': 900},
            {'name': 'worst.nzb', 'protocol': 'nzb', 'score': 5},
            {'name': 'mid.nzb', 'protocol': 'nzb', 'score': 400},
            {'name': 'a.torrent', 'protocol': 'torrent', 'score': 5000},
        ]
        ordered = self._search(searcher, 'nzb', results)
        assert [r['name'] for r in ordered] == ['best.nzb', 'mid.nzb', 'worst.nzb', 'a.torrent']

    def test_search_uses_the_shared_helper(self, searcher):
        """A7: no second hand-rolled copy of this logic may survive."""
        from unittest.mock import patch

        results = [{'name': 'x.nzb', 'protocol': 'nzb', 'score': 1}]
        with patch('couchpotato.core.media._base.searcher.main.sort_by_protocol_preference',
                   return_value = results) as helper, \
                patch('couchpotato.core.media._base.searcher.main.fireEvent',
                      side_effect = lambda event, *a, **k: results if event.endswith('.nzb.movie') else []), \
                patch.object(searcher, 'conf', return_value = 'nzb'):
            searcher.search(['nzb'], {'type': 'movie'}, {'identifier': '1080p'})

        assert helper.called, 'Searcher.search must delegate to sort_by_protocol_preference'
