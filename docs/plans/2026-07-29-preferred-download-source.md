# Preferred Download Source (FEAT-007 Part A) Implementation Plan

> **For agentic workers:** implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking. TDD is mandatory (CLAUDE.md rule 1): write the
> failing test, run it and *see it fail*, then write the minimum code to pass.
> Commit after each task. **Do not push** — the orchestrator runs the local
> agent review gate and pushes (CLAUDE.md rule 4).

**Goal:** Make the existing `searcher.preferred_method` setting discoverable,
consistent across its two call sites, and covered by tests — without changing
the behaviour the owner chose (hard preference, falls back to the other source).

**Architecture:** One shared pure function,
`couchpotato/core/helpers/protocol.py::sort_by_protocol_preference`, replaces
the two hand-rolled `protocol[:3]` sorts in `Searcher.search()` and
`Release.forMedia()`. Ranking is explicit (preferred = 0, other known = 1,
unknown = 2), which also fixes today's direction-dependent placement of
unknown protocols. The config option is relabelled; its **stored values are
unchanged**, so existing `settings.conf` files keep working.

**Tech Stack:** Python 3.10+, pytest, ruff (line-length 160), FastAPI/Jinja UI.
Gate: `make verify` (or `PYTHON="$(pwd)/.venv/bin/python" make verify` locally
— system `python3` lacks the deps).

**Spec:** `specs/FEAT-007-preferred-source-and-release-list-controls.md` (Part A
and acceptance criteria A1–A10). Part B (release list sort/filter) is a
separate plan, written after this lands.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `couchpotato/core/helpers/protocol.py` | Rank a protocol against a preference; stable-sort a list by that rank. No imports from the plugin tree. | Create |
| `couchpotato/core/media/_base/searcher/main.py:59-65` | Call the helper instead of its own sort (decides what gets downloaded). | Modify |
| `couchpotato/core/plugins/release/main.py:674-681` | Call the helper instead of its own sort (orders the list the UI shows). | Modify |
| `couchpotato/core/media/_base/searcher/__init__.py:16-25` | Config option label, description, value labels. | Modify |
| `tests/unit/test_protocol_preference.py` | Helper unit tests + both call sites + fallback + config. | Create |

`couchpotato/core/helpers/` is the right home: both call sites already import
from `couchpotato.core.helpers.variable`, so it adds no import cycle. Putting
it under the `searcher` package would make `release/main.py` import a package
whose `__init__.py` pulls in `Searcher` and the plugin base.

---

## Task 1: The shared ranking helper

**Files:**
- Create: `couchpotato/core/helpers/protocol.py`
- Test: `tests/unit/test_protocol_preference.py`

Covers A1–A6, A8.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_protocol_preference.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py -v
```

Expected: **collection error** —
`ModuleNotFoundError: No module named 'couchpotato.core.helpers.protocol'`.
That is the correct failure: the module does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `couchpotato/core/helpers/protocol.py`:

```python
"""Ordering releases by the user's preferred download source.

`searcher.preferred_method` ('both' | 'nzb' | 'torrent') is a HARD preference
that FALLS BACK: every release of the preferred protocol outranks every release
of the other one, but nothing is excluded, so when the preferred protocol has
no usable release the other one is still downloaded.

Both call sites — `Searcher.search()` (what gets downloaded) and
`Release.forMedia()` (what the UI lists) — sort by score first and then apply
this, relying on a stable sort to keep score order inside each protocol group.
"""

NO_PREFERENCE = 'both'

_NZB_PROTOCOLS = ('nzb',)
_TORRENT_PROTOCOLS = ('torrent', 'torrent_magnet')

#: Ranks, low sorts first.
_PREFERRED = 0
_OTHER = 1
_UNKNOWN = 2


def protocol_rank(protocol, preference):
    """Rank `protocol` against `preference`.

    Returns 0 for the preferred family, 1 for the other known family, and 2 for
    anything unrecognised. Unknown ranks last in BOTH directions: a release
    whose protocol we cannot identify must never outrank one we can, whichever
    way the preference points.
    """

    normalised = (protocol or '').strip().lower()

    if normalised in _NZB_PROTOCOLS:
        family = 'nzb'
    elif normalised in _TORRENT_PROTOCOLS:
        family = 'torrent'
    else:
        return _UNKNOWN

    return _PREFERRED if family == preference else _OTHER


def sort_by_protocol_preference(items, preference, get_protocol):
    """Stable-sort `items` so the preferred protocol comes first.

    `preference` is 'both' | 'nzb' | 'torrent'; anything else (including None,
    as a config read can yield before defaults are applied) is treated as no
    preference and the incoming order is returned unchanged.

    `get_protocol` maps an item to its protocol string — the two call sites
    hold it at different key paths.
    """

    if preference not in ('nzb', 'torrent'):
        return list(items)

    return sorted(items, key = lambda item: protocol_rank(get_protocol(item), preference))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py -v
```

Expected: **all PASS** (23 tests, counting parametrised cases).

- [ ] **Step 5: Lint**

```bash
.venv/bin/python -m ruff check couchpotato/core/helpers/protocol.py tests/unit/test_protocol_preference.py
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add couchpotato/core/helpers/protocol.py tests/unit/test_protocol_preference.py
git commit -m "feat: shared protocol-preference ordering helper (FEAT-007 A1-A6, A8)"
```

---

## Task 2: Wire `Searcher.search()` to the helper

This is the call site that decides **what gets downloaded** —
`release.try_download_result` walks the list it returns in order.

**Files:**
- Modify: `couchpotato/core/media/_base/searcher/main.py:59-65`
- Test: `tests/unit/test_protocol_preference.py` (append)

Covers A1, A2, A7.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_protocol_preference.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py::TestSearcherSearchOrdering -v
```

Expected: `test_search_uses_the_shared_helper` FAILS with
`AttributeError: <module 'couchpotato.core.media._base.searcher.main'> does not have the attribute 'sort_by_protocol_preference'`.
The ordering tests may already pass — the existing `[:3]` sort happens to be
correct for these inputs. That is expected and fine: they are being added as
regression cover for behaviour the refactor must not change.

- [ ] **Step 3: Make the change**

In `couchpotato/core/media/_base/searcher/main.py`, add to the imports (after
the existing `couchpotato.core.helpers.variable` import on line 7):

```python
from couchpotato.core.helpers.protocol import sort_by_protocol_preference
```

Then replace lines 59-65 — currently:

```python
        sorted_results = sorted(results, key = lambda k: k['score'], reverse = True)

        download_preference = self.conf('preferred_method', section = 'searcher')
        if download_preference != 'both':
            sorted_results = sorted(sorted_results, key = lambda k: k['protocol'][:3], reverse = (download_preference == 'torrent'))

        return sorted_results
```

with:

```python
        sorted_results = sorted(results, key = lambda k: k['score'], reverse = True)

        # Hard preference, applied after the score sort and relying on its
        # stability: every release of the preferred protocol outranks the
        # other, but nothing is excluded, so an unmatched preference falls back.
        download_preference = self.conf('preferred_method', section = 'searcher')
        sorted_results = sort_by_protocol_preference(sorted_results, download_preference, lambda k: k.get('protocol'))

        return sorted_results
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py -v
```

Expected: **all PASS**.

- [ ] **Step 5: Run the searcher's existing tests for regressions**

```bash
.venv/bin/python -m pytest tests/unit/test_searcher_matching.py tests/unit/test_movie_searcher_eta.py tests/unit/test_search_releases_list_only.py -q
```

Expected: all pass, no change in counts.

- [ ] **Step 6: Commit**

```bash
git add couchpotato/core/media/_base/searcher/main.py tests/unit/test_protocol_preference.py
git commit -m "refactor: Searcher.search uses the shared preference helper (FEAT-007 A7)"
```

---

## Task 3: Wire `Release.forMedia()` to the helper

This is the call site that orders **what the UI shows**, and the one carrying
the unknown-protocol bug.

**Files:**
- Modify: `couchpotato/core/plugins/release/main.py:674-681`
- Test: `tests/unit/test_protocol_preference.py` (append)

Covers A1, A2, A6, A7.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_protocol_preference.py`:

```python
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
        """Defensive: a partially-written document must not break the page."""
        docs = [{'_id': 'broken'}, self._doc('n1', 'nzb', 100)]
        assert [r['_id'] for r in self._for_media(plugin, 'nzb', docs)] == ['n1', 'broken']

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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py::TestReleaseForMediaOrdering -v
```

Expected: **two failures** —
`test_a_release_with_no_protocol_is_listed_last_not_first` fails with
`['unknown', 'n1', 't1'] != ['n1', 't1', 'unknown']` (the bug, now pinned), and
`test_for_media_uses_the_shared_helper` fails with `AttributeError` on the
patch target.

- [ ] **Step 3: Make the change**

In `couchpotato/core/plugins/release/main.py`, add to the imports:

```python
from couchpotato.core.helpers.protocol import sort_by_protocol_preference
```

Then replace lines 674-681 — currently:

```python
        releases = sorted(releases, key = lambda k: k.get('info', {}).get('score', 0), reverse = True)

        # Sort based on preferred search method
        download_preference = self.conf('preferred_method', section = 'searcher')
        if download_preference != 'both':
            releases = sorted(releases, key = lambda k: k.get('info', {}).get('protocol', '')[:3], reverse = (download_preference == 'torrent'))

        return releases or []
```

with:

```python
        releases = sorted(releases, key = lambda k: (k.get('info') or {}).get('score', 0), reverse = True)

        # Sort based on the preferred download source. Same helper as
        # Searcher.search(), so the list the user sees is ordered the same way
        # the automatic picker orders its candidates.
        download_preference = self.conf('preferred_method', section = 'searcher')
        releases = sort_by_protocol_preference(releases, download_preference, lambda k: (k.get('info') or {}).get('protocol'))

        return releases or []
```

Note `(k.get('info') or {})` rather than `k.get('info', {})`: a document with
an explicit `'info': None` would make the original raise `AttributeError`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py -v
```

Expected: **all PASS**.

- [ ] **Step 5: Run the release plugin's existing tests for regressions**

```bash
.venv/bin/python -m pytest tests/unit/test_release_info_population.py tests/unit/test_release_add_lookup_narrowing.py tests/unit/test_release_create_from_search_cas.py tests/unit/test_release_update_status_cas.py -q
```

Expected: all pass, no change in counts.

- [ ] **Step 6: Commit**

```bash
git add couchpotato/core/plugins/release/main.py tests/unit/test_protocol_preference.py
git commit -m "fix: unknown-protocol releases sort last in both directions (FEAT-007 A6, A7)"
```

---

## Task 4: Prove the fallback (A10)

The spec asserts fallback works today, from reading `tryDownloadResult`. It is
untested, so **verify it rather than assume it**. If these tests fail, the
fallback is broken and that is a bug fix belonging to this PR — report it
before changing production code.

**Files:**
- Test: `tests/unit/test_protocol_preference.py` (append)
- Modify (only if the tests fail): `couchpotato/core/plugins/release/main.py:418-468`

Covers A10.

- [ ] **Step 1: Write the test**

Append to `tests/unit/test_protocol_preference.py`:

```python
class TestFallbackToTheOtherProtocol:
    """A10: the preference orders candidates; it never excludes them.

    `tryDownloadResult` walks the preference-ordered list and takes the first
    release that passes the filters — so when the preferred protocol has
    nothing usable, the other one is still downloaded. That is the designed
    behaviour ("fall back to torrent"), and it is what makes the preference
    safe to turn on.
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
```

- [ ] **Step 2: Run the tests**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py::TestFallbackToTheOtherProtocol -v
```

Expected: **all PASS** with no production change — these pin existing
behaviour. **If any fail, stop and report it**: the spec's A10 assumption is
wrong, fallback is broken, and the fix needs deciding before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_protocol_preference.py
git commit -m "test: pin fallback to the non-preferred protocol (FEAT-007 A10)"
```

---

## Task 5: Relabel the setting

**Files:**
- Modify: `couchpotato/core/media/_base/searcher/__init__.py:16-25`
- Test: `tests/unit/test_protocol_preference.py` (append)

Covers A9.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_protocol_preference.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py::TestPreferredMethodConfigOption -v
```

Expected: three FAIL (`'First search' != 'Preferred download source'`, the
description assertion, and the value labels);
`test_the_stored_values_are_unchanged` PASSES already — that is the point of
it, it is the guard against the refactor breaking existing configs.

- [ ] **Step 3: Make the change**

In `couchpotato/core/media/_base/searcher/__init__.py`, replace lines 17-24:

```python
                {
                    'name': 'preferred_method',
                    'label': 'First search',
                    'description': 'Which of the methods do you prefer',
                    'default': 'both',
                    'type': 'dropdown',
                    'values': [('usenet & torrents', 'both'), ('usenet', 'nzb'), ('torrents', 'torrent')],
                },
```

with:

```python
                {
                    'name': 'preferred_method',
                    'label': 'Preferred download source',
                    'description': 'Prefer this source when both have acceptable releases. Falls back to the other if nothing suitable is found.',
                    'default': 'both',
                    'type': 'dropdown',
                    'values': [('No preference', 'both'), ('Usenet (NZB)', 'nzb'), ('Torrents', 'torrent')],
                },
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/unit/test_protocol_preference.py -v
```

Expected: **all PASS**.

- [ ] **Step 5: Check no test or template hard-codes the old label**

```bash
grep -rn "First search" tests/ couchpotato/ specs/ docs/ 2>/dev/null
```

Expected: **no hits in `tests/` or `couchpotato/`**. The only known reference is
`QA/QA_SESSION_2026-02-16.md`, a point-in-time session log — leave it alone. If
anything in `tests/e2e/settings.spec.ts` asserts on the old label, update it
here (CLAUDE.md rule 5).

- [ ] **Step 6: Commit**

```bash
git add couchpotato/core/media/_base/searcher/__init__.py tests/unit/test_protocol_preference.py
git commit -m "feat: name the download-source setting for what it does (FEAT-007 A9)"
```

---

## Task 6: Full gate and hand-off

- [ ] **Step 1: Run the full local gate**

```bash
PYTHON="$(pwd)/.venv/bin/python" make verify
```

Expected: ruff clean, Python unit suite green (previous baseline **1465
passed**, plus the new tests), UI unit tests green.

If the E2E stage dies with `[WebServer] /bin/sh: python: command not found`
(exit 127), that is a known local-environment quirk, not a failure. Start the
server yourself with a **fresh** data dir and run Playwright against it:

```bash
rm -rf .e2e-feat007-data
.venv/bin/python CouchPotato.py --data_dir=.e2e-feat007-data --console_log &
CP_TEST_URL=http://localhost:5050 npx playwright test --project=chromium --workers=1
```

Two Navigation tests in `tests/e2e/interactions.e2e.spec.ts` are known-flaky in
the full single-worker run and pass in isolation; re-run any failure with
`-g "<test name>"` before treating it as real.

- [ ] **Step 2: Confirm the acceptance criteria**

Walk `specs/FEAT-007-preferred-source-and-release-list-controls.md` A1–A10 and
tick each box in the spec, citing the test that covers it. A10 is a
verification, not an implementation — record what you found.

- [ ] **Step 3: Commit the ticked spec**

```bash
git add specs/FEAT-007-preferred-source-and-release-list-controls.md
git commit -m "docs: tick FEAT-007 Part A acceptance criteria"
```

- [ ] **Step 4: STOP**

Do **not** push. Report back with: the test count delta, the A10 finding
(fallback confirmed or broken), and anything in the spec that turned out to be
wrong. The orchestrator runs the local agent review gate (≥2 independent
`general-purpose` reviewers on the branch diff) and pushes only once it is
clean.

---

## Self-review notes

- **Spec coverage:** A1 (T1, T2, T3), A2 (T1, T2, T3), A3 (T1, T2, T3),
  A4 (T1, T2), A5 (T1), A6 (T1, T3), A7 (T2, T3), A8 (T1), A9 (T5),
  A10 (T4). All ten covered.
- **Not in this plan, by design:** every Part B criterion (B1–B14) — separate
  plan once this lands. The seeder score bias is out of scope per the spec.
- **Naming is consistent** across tasks: `sort_by_protocol_preference` and
  `protocol_rank` are defined in Task 1 and used under those exact names in
  Tasks 2 and 3, patched at
  `couchpotato.core.media._base.searcher.main.sort_by_protocol_preference` and
  `couchpotato.core.plugins.release.main.sort_by_protocol_preference` — the
  module-level names created by the `from ... import ...` lines those tasks add.
- **Expected-failure honesty:** Tasks 2 and 4 note upfront that some tests pass
  before the change. They are regression cover, and the plan says so rather
  than pretending to a red-green cycle that will not happen.
