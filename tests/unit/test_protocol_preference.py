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

    def test_a_non_string_protocol_does_not_crash_and_ranks_as_unknown(self):
        """A corrupt document can carry a non-None non-string 'protocol'
        (e.g. a list). `(protocol or '').strip().lower()` raises
        AttributeError for that; master's `[:3]` slice tolerated sequences.
        Since this feeds forMedia and therefore the movie-detail page, a
        non-string protocol must rank as unknown rather than raising.
        """
        items = _items(['not', 'a', 'string'], 'torrent', 'nzb')
        result = sort_by_protocol_preference(items, 'nzb', _get)
        assert _protocols(result) == ['nzb', 'torrent', ['not', 'a', 'string']]

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


class TestReleaseForMediaOrdering:
    """`Release.forMedia()` — the order the movie detail page renders."""

    @pytest.fixture
    def plugin(self):
        from couchpotato.core.plugins.release.main import Release
        return object.__new__(Release)

    def _for_media(self, plugin, preference, docs):
        from unittest.mock import MagicMock, patch

        db = MagicMock()
        db.get_many.return_value = [{'_id': d['_id']} for d in docs]
        db.get.side_effect = lambda _index, _id: next(d for d in docs if d['_id'] == _id)

        with patch('couchpotato.core.plugins.release.main.get_db', return_value = db), \
                patch.object(plugin, 'conf', return_value = preference):
            return plugin.forMedia('movie-1')

    @staticmethod
    def _doc(_id, protocol, score):
        return {'_id': _id, 'info': {'protocol': protocol, 'score': score}}

    def test_nzb_preference_lists_nzb_first(self, plugin):
        """A1 on the display path."""
        docs = [self._doc('t1', 'torrent', 3400), self._doc('n1', 'nzb', 210)]
        assert [r['_id'] for r in self._for_media(plugin, 'nzb', docs)] == ['n1', 't1']

    def test_torrent_preference_lists_torrents_first(self, plugin):
        """A2 on the display path."""
        docs = [self._doc('n1', 'nzb', 3400), self._doc('t1', 'torrent', 210)]
        assert [r['_id'] for r in self._for_media(plugin, 'torrent', docs)] == ['t1', 'n1']

    def test_both_lists_in_score_order(self, plugin):
        """A3 on the display path."""
        docs = [self._doc('n1', 'nzb', 500), self._doc('t1', 'torrent', 3400)]
        assert [r['_id'] for r in self._for_media(plugin, 'both', docs)] == ['t1', 'n1']

    def test_a_release_with_no_protocol_is_listed_last_not_first(self, plugin):
        """A6: THE BUG. `''[:3]` sorted ascending put this at the TOP under 'nzb'."""
        docs = [
            self._doc('unknown', '', 999),
            self._doc('t1', 'torrent', 500),
            self._doc('n1', 'nzb', 100),
        ]
        assert [r['_id'] for r in self._for_media(plugin, 'nzb', docs)] == ['n1', 't1', 'unknown']

    def test_a_release_with_no_info_block_does_not_crash_the_list(self, plugin):
        """Defensive: a partially-written document must not break the page.

        `k.get('info', {})` (the old, unguarded expression) already returns
        `{}` for a MISSING 'info' key, so a doc that simply omits 'info'
        does not exercise the `(k.get('info') or {})` hardening at all --
        it would pass against either expression. The only case the `or {}`
        guard changes is an explicit `'info': None`, which is what this test
        must include to actually cover the hardening.
        """
        docs = [
            {'_id': 'broken', 'info': None},
            {'_id': 'missing_key'},
            self._doc('n1', 'nzb', 100),
        ]
        assert [r['_id'] for r in self._for_media(plugin, 'nzb', docs)] == ['n1', 'broken', 'missing_key']

    def test_a_score_of_none_does_not_crash_the_list(self, plugin):
        """The `or {}` guard is only half a guard: a doc with an explicit
        'info': {'score': None} still has a truthy info dict, so `or {}`
        does not fire, and `.get('score', 0)` returns None (the key IS
        present) rather than the 0 default. Comparing None to an int during
        sort raises TypeError. The score coercion must use `tryInt` (already
        imported in release/main.py) so None/garbage sorts as 0, consistent
        with the rest of the hardening.
        """
        docs = [
            {'_id': 'nullscore', 'info': {'protocol': 'nzb', 'score': None}},
            self._doc('t1', 'torrent', 500),
        ]
        assert [r['_id'] for r in self._for_media(plugin, 'both', docs)] == ['t1', 'nullscore']

    def test_for_media_uses_the_shared_helper(self, plugin):
        """A7: the second copy of the logic must be gone."""
        from unittest.mock import MagicMock, patch

        docs = [self._doc('n1', 'nzb', 100)]
        db = MagicMock()
        db.get_many.return_value = [{'_id': 'n1'}]
        db.get.side_effect = lambda _index, _id: docs[0]

        with patch('couchpotato.core.plugins.release.main.sort_by_protocol_preference',
                   return_value = docs) as helper, \
                patch('couchpotato.core.plugins.release.main.get_db', return_value = db), \
                patch.object(plugin, 'conf', return_value = 'nzb'):
            plugin.forMedia('movie-1')

        assert helper.called, 'Release.forMedia must delegate to sort_by_protocol_preference'


class TestFallbackToTheOtherProtocol:
    """A10: the preference orders candidates; it never excludes them.

    `tryDownloadResult` walks the preference-ordered list and takes the first
    release that passes the FILTERS (status / minimum_score / size / seeders)
    -- so when the preferred protocol has nothing that passes those filters,
    the other one is still downloaded. That is the designed behaviour
    ("fall back to torrent"), and it is covered below.

    That is NOT the same as "any failure of the preferred release falls
    back". If the preferred release passes every filter but the DOWNLOAD
    ITSELF then fails (downloader disabled/unreachable, provider error --
    `release.download` returning something other than True or the sentinel
    'try_next'), `tryDownloadResult` hits `break` and the non-preferred
    release is never tried. This is pre-existing behaviour, not a
    regression introduced here, and it is a known limitation, not something
    this test suite claims is "safe" -- see
    test_a_download_failure_does_not_fall_through_to_the_other_protocol
    below, which pins it explicitly.
    """

    @pytest.fixture
    def plugin(self):
        from couchpotato.core.plugins.release.main import Release
        return object.__new__(Release)

    def _try(self, plugin, results, minimum_score = 1):
        from unittest.mock import MagicMock, patch

        downloaded = []

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.download':
                downloaded.append(kwargs.get('data', {}).get('name'))
                return True
            return None

        env = MagicMock()
        env.setting.return_value = 1  # torrent.minimum_seeders

        with patch('couchpotato.core.plugins.release.main.fireEvent', side_effect = fake_fire_event), \
                patch('couchpotato.core.plugins.release.main.Env', env):
            plugin.tryDownloadResult(results, {'_id': 'movie-1'}, {'minimum_score': minimum_score, 'index': 0})

        return downloaded

    def _try_with_download_outcomes(self, plugin, results, outcomes, minimum_score = 1):
        """Like `_try`, but `release.download`'s return value is controlled
        per release name via `outcomes` (defaulting to True), so a
        download-failure scenario can be driven without touching the
        filters.
        """
        from unittest.mock import MagicMock, patch

        attempted = []

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.download':
                name = kwargs.get('data', {}).get('name')
                attempted.append(name)
                return outcomes.get(name, True)
            return None

        env = MagicMock()
        env.setting.return_value = 1  # torrent.minimum_seeders

        with patch('couchpotato.core.plugins.release.main.fireEvent', side_effect = fake_fire_event), \
                patch('couchpotato.core.plugins.release.main.Env', env):
            plugin.tryDownloadResult(results, {'_id': 'movie-1'}, {'minimum_score': minimum_score, 'index': 0})

        return attempted

    def test_a_torrent_is_downloaded_when_no_nzb_was_found(self, plugin):
        """Preference nzb, but the search returned torrents only."""
        results = [
            {'name': 'only.torrent', 'protocol': 'torrent', 'score': 100, 'size': 4000, 'seeders': 20, 'age': 5},
        ]
        assert self._try(plugin, results) == ['only.torrent']

    def test_a_torrent_is_downloaded_when_the_preferred_nzb_fails_the_filters(self, plugin):
        """The real fallback path: an nzb ranked first but rejected on score.

        The list arrives nzb-first (the preference already applied); the nzb is
        filtered out for scoring below `minimum_score`, and the torrent behind
        it is taken.
        """
        results = [
            {'name': 'weak.nzb', 'protocol': 'nzb', 'score': 2, 'size': 4000, 'age': 5},
            {'name': 'fine.torrent', 'protocol': 'torrent', 'score': 800, 'size': 4000, 'seeders': 20, 'age': 5},
        ]
        assert self._try(plugin, results, minimum_score = 500) == ['fine.torrent']

    def test_the_preferred_release_still_wins_when_it_passes(self, plugin):
        """The complement — fallback must not fire when it should not."""
        results = [
            {'name': 'good.nzb', 'protocol': 'nzb', 'score': 800, 'size': 4000, 'age': 5},
            {'name': 'big.torrent', 'protocol': 'torrent', 'score': 5000, 'size': 4000, 'seeders': 900, 'age': 5},
        ]
        assert self._try(plugin, results) == ['good.nzb']

    def test_a_download_failure_does_not_fall_through_to_the_other_protocol(self, plugin):
        """KNOWN LIMITATION, pinned deliberately, not a regression.

        The preferred nzb passes every filter (score, size, age) and is
        tried first. `release.download` then returns False for it --
        simulating a disabled/unreachable downloader or a provider error,
        as opposed to a filter rejection. `tryDownloadResult` only advances
        to the next candidate when a release is rejected by the filters or
        when `release.download` returns the sentinel 'try_next'; any other
        return value (including False) hits `break`, so the torrent behind
        it is never attempted. This contradicts a plain reading of the
        setting's "falls back" description for this one case -- the
        description has been narrowed to say the fallback covers "no
        acceptable release of this type is found", which this scenario
        satisfies (an nzb was found and was acceptable) but which still
        doesn't get downloaded.
        """
        results = [
            {'name': 'good.nzb', 'protocol': 'nzb', 'score': 800, 'size': 4000, 'age': 5},
            {'name': 'big.torrent', 'protocol': 'torrent', 'score': 5000, 'size': 4000, 'seeders': 900, 'age': 5},
        ]
        attempted = self._try_with_download_outcomes(plugin, results, outcomes = {'good.nzb': False})
        assert attempted == ['good.nzb']


class TestPreferredMethodConfigOption:
    """A9: named for what it does, without changing what it stores."""

    @staticmethod
    def _option():
        from couchpotato.core.media._base.searcher import config
        for section in config:
            if section['name'] != 'searcher':
                continue
            for group in section['groups']:
                for option in group['options']:
                    if option['name'] == 'preferred_method':
                        return option
        raise AssertionError('preferred_method option not found in searcher config')

    def test_the_label_says_what_the_setting_does(self):
        option = self._option()
        assert option['label'] == 'Preferred download source'

    def test_the_description_explains_the_hard_preference_and_the_fallback(self):
        description = self._option()['description'].lower()
        assert 'prefer' in description
        assert 'falls back' in description

    def test_the_value_labels_are_plain_english(self):
        labels = [label for label, _stored in self._option()['values']]
        assert labels == ['No preference', 'Usenet (NZB)', 'Torrents']

    def test_the_stored_values_are_unchanged(self):
        """Backwards compatibility: existing settings.conf files must keep working.

        Only the display strings change. `preferred_method = nzb` written by an
        older build must still be read as 'nzb'.
        """
        stored = [value for _label, value in self._option()['values']]
        assert stored == ['both', 'nzb', 'torrent']
        assert self._option()['default'] == 'both'
        assert self._option()['type'] == 'dropdown'
