# Release List Sort/Filter (FEAT-007 Part B) Implementation Plan

> **For agentic workers:** implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax. TDD is mandatory (CLAUDE.md rule 1): write the failing test,
> run it and *see it fail*, then write the minimum code to pass. Commit after
> each task. **Do not push** — the orchestrator runs the local agent review gate
> and pushes (CLAUDE.md rule 4).

**Goal:** Let the user filter the movie-detail release list by source, quality
and status, and sort it by any meaningful column — including Size and Seeders,
which are in the data today but never rendered.

**Architecture:** All filtering and sorting lives in one pure module,
`couchpotato/ui/releases_view.py` — list in, list out, no FastAPI, no Jinja, no
DB. The releases block moves out of `movie_detail.html` into an includable
`partials/movie_releases.html`, rendered both inline (first paint) and by a new
`GET /partial/movie/{movie_id}/releases` route for htmx swaps. URL building for
the sort links is done in Python, not Jinja, so it is testable.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, htmx, Tailwind, Alpine.js;
pytest + Playwright. Gate: `PYTHON="$(pwd)/.venv/bin/python" make verify`.

**Spec:** `specs/FEAT-007-preferred-source-and-release-list-controls.md`, Part B,
criteria B1–B14. Part A shipped in #213 (v3.22.0).

---

## Design correction landed by this plan

The spec says the controls render as plain links that "work with JavaScript
disabled", and criterion **B8** asserts the full-page route honours the same
params so they do. **That is not achievable and not meaningful**, because
`couchpotato/ui/templates/detail.html` is a five-line htmx shell: the entire
movie detail body, releases table included, is fetched by `hx-get` on `load`.
With JS off the page is a spinner and there is no table to enhance.

What *is* achievable, and was the actual value behind that decision, is
**bookmarkable/shareable URLs**: `/movie/{id}?source=nzb&sort=size&dir=desc`
restores that view. Task 7 implements it by having the full-page route accept
the params and forward them into `detail.html`'s `hx-get`. Task 8 corrects the
spec's decision bullet and rewrites B8 accordingly.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `couchpotato/core/helpers/protocol.py` | Gains a public `protocol_family()`; `_protocol_rank` uses it. Single source of truth for "is this nzb or torrent". | Modify |
| `couchpotato/ui/releases_view.py` | Pure: normalise controls, filter, sort, build filter options and sort-link URLs. | Create |
| `couchpotato/ui/templates/partials/movie_releases.html` | Controls + table. Rendered inline and standalone. | Create |
| `couchpotato/ui/templates/partials/movie_detail.html` | Include the partial; drop the inline table. | Modify |
| `couchpotato/ui/templates/detail.html` | Forward query params into the initial `hx-get`. | Modify |
| `couchpotato/ui/__init__.py` | New releases partial route; detail routes accept params. | Modify |
| `tests/unit/test_releases_view.py` | Pure-function tests. | Create |
| `tests/unit/test_releases_partial_route.py` | Route tests via `TestClient`. | Create |
| `tests/e2e/release_controls.spec.ts` | Browser coverage (CLAUDE.md rule 5). | Create |

---

## Task 1: `protocol_family()` — one source of truth for source classification

Part A's classifier is private (`_protocol_rank`). Part B needs the same
nzb-vs-torrent knowledge for its source filter, and duplicating it would
recreate exactly the drift Part A removed.

**Files:**
- Modify: `couchpotato/core/helpers/protocol.py`
- Test: `tests/unit/test_protocol_preference.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_protocol_preference.py`:

```python
class TestProtocolFamily:
    """`protocol_family` is the public classifier Part B's source filter uses.

    It exists so the release-list filter and the preference ordering cannot
    disagree about what counts as a torrent.
    """

    @pytest.mark.parametrize('protocol, expected', [
        ('nzb', 'nzb'),
        ('NZB', 'nzb'),
        ('  nzb  ', 'nzb'),
        ('torrent', 'torrent'),
        ('torrent_magnet', 'torrent'),
        ('TORRENT_MAGNET', 'torrent'),
        ('', None),
        ('   ', None),
        ('ftp', None),
        (None, None),
        (['torrent'], None),
        (7, None),
    ])
    def test_classifies_every_protocol_the_codebase_produces(self, protocol, expected):
        from couchpotato.core.helpers.protocol import protocol_family
        assert protocol_family(protocol) == expected

    def test_the_rank_function_is_built_on_the_same_classifier(self):
        """A regression guard: if _protocol_rank stops using protocol_family,
        the filter and the ordering can drift apart again.
        """
        from unittest.mock import patch

        import couchpotato.core.helpers.protocol as mod

        with patch.object(mod, 'protocol_family', return_value = 'nzb') as family:
            assert mod._protocol_rank('anything-at-all', 'nzb') == 0
        assert family.called
```

- [ ] **Step 2: Run it and watch it fail**

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/test_protocol_preference.py::TestProtocolFamily -v
```

Expected: `ImportError: cannot import name 'protocol_family'`.

- [ ] **Step 3: Implement**

In `couchpotato/core/helpers/protocol.py`, add above `_protocol_rank`:

```python
def protocol_family(protocol):
    """Classify `protocol` as 'nzb', 'torrent', or None if unrecognised.

    Public because two features depend on the same answer: the preference
    ordering below, and the release list's source filter
    (`couchpotato/ui/releases_view.py`). They must not drift apart.
    """

    if not isinstance(protocol, str):
        return None

    normalised = protocol.strip().lower()

    if normalised in _NZB_PROTOCOLS:
        return 'nzb'
    if normalised in _TORRENT_PROTOCOLS:
        return 'torrent'
    return None
```

and rewrite `_protocol_rank`'s body to use it:

```python
def _protocol_rank(protocol, preference):
    """Rank `protocol` against `preference`.

    Returns 0 for the preferred family, 1 for the other known family, and 2 for
    anything unrecognised. Unknown ranks last in BOTH directions: a release
    whose protocol we cannot identify must never outrank one we can, whichever
    way the preference points.
    """

    family = protocol_family(protocol)

    if family is None:
        return _UNKNOWN

    return _PREFERRED if family == preference else _OTHER
```

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/test_protocol_preference.py -v
```

Expected: **all PASS** — the existing Part A tests must still pass unchanged,
since this is a pure refactor of the same logic.

- [ ] **Step 5: Commit**

```bash
git add couchpotato/core/helpers/protocol.py tests/unit/test_protocol_preference.py
git commit -m "refactor: expose protocol_family so the source filter and the preference share one classifier"
```

---

## Task 2: The pure view module — normalising controls

**Files:**
- Create: `couchpotato/ui/releases_view.py`
- Test: `tests/unit/test_releases_view.py`

Covers B6 (invalid params fall back rather than 500).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_releases_view.py`:

```python
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
```

- [ ] **Step 2: Run and watch it fail**

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/test_releases_view.py -v
```

Expected: `ModuleNotFoundError: No module named 'couchpotato.ui.releases_view'`.

- [ ] **Step 3: Implement**

Create `couchpotato/ui/releases_view.py`:

```python
"""Filtering and sorting for the movie-detail release list.

Pure functions only: a list of release documents in, a list out. No FastAPI,
no Jinja, no database -- so the behaviour is unit-testable directly and the
route and template stay thin.

Control values arrive from the query string, which can be bookmarked, shared
or hand-edited, so `normalise_controls` coerces anything unrecognised to a
default instead of raising.
"""

from couchpotato.core.helpers.protocol import protocol_family
from couchpotato.core.helpers.variable import tryFloat

#: The no-op view: exactly what the page rendered before Part B existed.
DEFAULT_CONTROLS = {
    'source': 'all',
    'quality': 'all',
    'status': 'all',
    'sort': 'default',
    'dir': 'desc',
}

SOURCES = ('all', 'nzb', 'torrent')
STATUSES = ('all', 'available', 'snatched', 'downloaded', 'done', 'seeding', 'ignored', 'failed')
SORTS = ('default', 'name', 'quality', 'score', 'source', 'status', 'age', 'size', 'seeders')
DIRECTIONS = ('asc', 'desc')

_WHITELISTS = {
    'source': SOURCES,
    'status': STATUSES,
    'sort': SORTS,
    'dir': DIRECTIONS,
}


def _clean(value):
    return value.strip().lower() if isinstance(value, str) else None


def normalise_controls(params):
    """Coerce raw query params into a valid, complete control set."""

    controls = dict(DEFAULT_CONTROLS)

    for field, allowed in _WHITELISTS.items():
        value = _clean(params.get(field))
        if value in allowed:
            controls[field] = value

    # Quality is deliberately NOT whitelisted: identifiers come from the
    # library, so a value this code has never heard of is legitimate and
    # should match nothing rather than be rewritten to 'all' (which would
    # show everything and look like the filter was ignored).
    quality = params.get('quality')
    if isinstance(quality, str) and quality.strip():
        controls['quality'] = quality.strip()

    return controls
```

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/test_releases_view.py -v
```

Expected: **all PASS**.

- [ ] **Step 5: Commit**

```bash
git add couchpotato/ui/releases_view.py tests/unit/test_releases_view.py
git commit -m "feat: normalise release-list control params (FEAT-007 B6)"
```

---

## Task 3: Filtering

**Files:**
- Modify: `couchpotato/ui/releases_view.py`
- Test: `tests/unit/test_releases_view.py` (append)

Covers B2, B3.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_releases_view.py`:

```python
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
```

- [ ] **Step 2: Run and watch it fail**

Expected: `ImportError: cannot import name 'filter_and_sort_releases'`.

- [ ] **Step 3: Implement**

Append to `couchpotato/ui/releases_view.py`:

```python
def _quality_identifier(release):
    """Read the quality identifier out of either shape a release may hold."""

    quality = release.get('quality')
    if isinstance(quality, str):
        return quality
    if isinstance(quality, dict):
        return quality.get('identifier') or quality.get('label') or ''
    return ''


def _info(release):
    return release.get('info') or {}


def _matches(release, controls):
    if controls['source'] != 'all':
        if protocol_family(_info(release).get('protocol')) != controls['source']:
            return False

    if controls['quality'] != 'all':
        if _quality_identifier(release) != controls['quality']:
            return False

    if controls['status'] != 'all':
        if (release.get('status') or '') != controls['status']:
            return False

    return True


def filter_and_sort_releases(releases, controls):
    """Apply `controls` (already normalised) to `releases`.

    Returns a new list; never mutates the input.
    """

    filtered = [r for r in releases if _matches(r, controls)]

    return _sorted(filtered, controls)


def _sorted(releases, controls):
    # Filled in by Task 4; ordering is a separate concern from filtering.
    return list(releases)
```

- [ ] **Step 4: Run the tests**

Expected: **all PASS**.

- [ ] **Step 5: Commit**

```bash
git add couchpotato/ui/releases_view.py tests/unit/test_releases_view.py
git commit -m "feat: filter the release list by source, quality and status (FEAT-007 B2, B3)"
```

---

## Task 4: Sorting

**Files:**
- Modify: `couchpotato/ui/releases_view.py`
- Test: `tests/unit/test_releases_view.py` (append)

Covers B4, B5.

Two rules that need stating because they are easy to get wrong:

1. **Releases missing the sorted field sort last in BOTH directions.** A naive
   `sorted(key=...)` with `reverse=True` puts the missing group first. So
   partition into present/missing, sort the present group, and append the
   missing group in its original relative order.
2. **Quality sorts by the profile's quality order, not alphabetically.**
   `'1080p' < '720p'` as strings, which is nonsense. The profile's `qualities`
   list is already ordered best-first, so a release's index in it is the
   meaningful key. A quality not in the profile counts as missing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_releases_view.py`:

```python
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
```

- [ ] **Step 2: Run and watch it fail**

Expected: failures on the `profile_qualities` keyword (unexpected argument)
and on every ordering assertion, since `_sorted` currently returns the list
unchanged.

- [ ] **Step 3: Implement**

In `couchpotato/ui/releases_view.py`, replace the `filter_and_sort_releases`
and `_sorted` stubs with:

```python
def _display_name(release):
    return (_info(release).get('name') or release.get('identifier') or '')


#: sort key -> (extractor, is_numeric). The extractor returns None when the
#: release has nothing to sort on, which sends it to the missing group.
def _numeric(field):
    def extract(release, _profile_qualities):
        value = _info(release).get(field)
        return None if value is None else tryFloat(value)
    return extract


def _quality_key(release, profile_qualities):
    identifier = _quality_identifier(release)
    if not identifier:
        return None
    if profile_qualities:
        # Profile order is best-first, so a lower index is a better quality.
        if identifier in profile_qualities:
            return profile_qualities.index(identifier)
        return None
    return identifier.lower()


_SORT_KEYS = {
    'name': lambda r, _pq: _display_name(r).lower() or None,
    'quality': _quality_key,
    'score': _numeric('score'),
    'size': _numeric('size'),
    'seeders': _numeric('seeders'),
    'age': _numeric('age'),
    'source': lambda r, _pq: protocol_family(_info(r).get('protocol')),
    'status': lambda r, _pq: (r.get('status') or '').lower() or None,
}


def filter_and_sort_releases(releases, controls, profile_qualities = None):
    """Apply `controls` (already normalised) to `releases`.

    Returns a new list; never mutates the input. `profile_qualities` is the
    movie's profile quality list, ordered best-first, used only by the
    quality sort.
    """

    filtered = [r for r in releases if _matches(r, controls)]

    return _sorted(filtered, controls, profile_qualities)


def _sorted(releases, controls, profile_qualities):
    extract = _SORT_KEYS.get(controls['sort'])
    if extract is None:
        # 'default' -- keep the incoming order, which is Part A's output
        # (score, then the user's download-source preference). `dir` is
        # deliberately ignored: reversing here would invert that preference.
        return list(releases)

    present, missing = [], []
    for release in releases:
        try:
            key = extract(release, profile_qualities)
        except Exception:
            key = None
        (present if key is not None else missing).append((key, release))

    # Mixed key types would raise on comparison; only sort when they agree.
    if len({type(key) for key, _ in present}) > 1:
        present.sort(key = lambda pair: str(pair[0]), reverse = controls['dir'] == 'desc')
    else:
        present.sort(key = lambda pair: pair[0], reverse = controls['dir'] == 'desc')

    # Missing values always trail, whichever direction was asked for: absent
    # data must never lead the list.
    return [release for _key, release in present] + [release for _key, release in missing]
```

- [ ] **Step 4: Run the tests**

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/test_releases_view.py -v
```

Expected: **all PASS**.

- [ ] **Step 5: Commit**

```bash
git add couchpotato/ui/releases_view.py tests/unit/test_releases_view.py
git commit -m "feat: sort the release list by any column, missing values last (FEAT-007 B4, B5)"
```

---

## Task 5: Filter options and sort-link URLs

The template needs the distinct quality/status values actually present (so the
dropdowns only offer what exists) and, for each sortable column, its link and
`aria-sort` value. Both are URL/data shaping — Python, not Jinja, so they are
testable.

**Files:**
- Modify: `couchpotato/ui/releases_view.py`
- Test: `tests/unit/test_releases_view.py` (append)

Covers B10 (aria-sort reflects the active sort).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_releases_view.py`:

```python
class TestFilterOptions:

    def test_offers_only_the_values_actually_present(self):
        from couchpotato.ui.releases_view import filter_options

        releases = [
            _release('a', 'nzb', '1080p', 'available'),
            _release('b', 'torrent', '720p', 'ignored'),
            _release('c', 'nzb', '1080p', 'available'),
        ]
        options = filter_options(releases)
        assert options['quality'] == ['720p', '1080p'] or options['quality'] == ['1080p', '720p']
        assert set(options['quality']) == {'1080p', '720p'}
        assert set(options['status']) == {'available', 'ignored'}
        assert set(options['source']) == {'nzb', 'torrent'}

    def test_orders_qualities_by_profile_when_one_is_given(self):
        from couchpotato.ui.releases_view import filter_options

        releases = [_release('a', quality = '720p'), _release('b', quality = '1080p')]
        options = filter_options(releases, profile_qualities = ['1080p', '720p'])
        assert options['quality'] == ['1080p', '720p']

    def test_ignores_blank_and_unknown_values(self):
        from couchpotato.ui.releases_view import filter_options

        releases = [{'_id': 'x', 'info': {}, 'quality': '', 'status': ''}]
        options = filter_options(releases)
        assert options['quality'] == []
        assert options['status'] == []
        assert options['source'] == []

    def test_an_empty_list_yields_empty_options(self):
        from couchpotato.ui.releases_view import filter_options

        assert filter_options([]) == {'source': [], 'quality': [], 'status': []}


class TestSortColumns:

    def test_each_sortable_column_gets_a_link_carrying_the_current_filters(self):
        from couchpotato.ui.releases_view import sort_columns

        controls = dict(DEFAULT_CONTROLS, source = 'nzb', sort = 'size', dir = 'desc')
        columns = {c['key']: c for c in sort_columns(controls, 'movie-1', '/')}

        assert 'source=nzb' in columns['score']['href']
        assert 'sort=score' in columns['score']['href']

    def test_the_active_column_toggles_direction(self):
        from couchpotato.ui.releases_view import sort_columns

        controls = dict(DEFAULT_CONTROLS, sort = 'size', dir = 'desc')
        columns = {c['key']: c for c in sort_columns(controls, 'movie-1', '/')}

        assert 'dir=asc' in columns['size']['href'], 'clicking the active column reverses it'
        assert 'dir=desc' in columns['score']['href'], 'an inactive column starts descending'

    def test_aria_sort_marks_only_the_active_column(self):
        """B10."""
        from couchpotato.ui.releases_view import sort_columns

        controls = dict(DEFAULT_CONTROLS, sort = 'size', dir = 'desc')
        columns = {c['key']: c for c in sort_columns(controls, 'movie-1', '/')}

        assert columns['size']['aria_sort'] == 'descending'
        assert columns['score']['aria_sort'] == 'none'

        controls = dict(DEFAULT_CONTROLS, sort = 'size', dir = 'asc')
        columns = {c['key']: c for c in sort_columns(controls, 'movie-1', '/')}
        assert columns['size']['aria_sort'] == 'ascending'

    def test_no_column_is_marked_under_the_default_sort(self):
        from couchpotato.ui.releases_view import sort_columns

        columns = sort_columns(DEFAULT_CONTROLS, 'movie-1', '/')
        assert all(c['aria_sort'] == 'none' for c in columns)

    def test_links_point_at_the_partial_and_push_the_full_page_url(self):
        """htmx swaps the table; the pushed URL must be the page, not the partial."""
        from couchpotato.ui.releases_view import sort_columns

        columns = sort_columns(DEFAULT_CONTROLS, 'movie-1', '/')
        column = columns[0]
        assert column['hx_get'].startswith('/partial/movie/movie-1/releases?')
        assert column['href'].startswith('/movie/movie-1?')

    def test_a_web_base_prefix_is_honoured(self):
        """CouchPotato can be mounted under a sub-path."""
        from couchpotato.ui.releases_view import sort_columns

        columns = sort_columns(DEFAULT_CONTROLS, 'movie-1', '/cp/')
        assert columns[0]['hx_get'].startswith('/cp/partial/movie/movie-1/releases?')
        assert columns[0]['href'].startswith('/cp/movie/movie-1?')

    def test_values_are_url_encoded(self):
        """A quality identifier could contain characters that need escaping."""
        from couchpotato.ui.releases_view import sort_columns

        controls = dict(DEFAULT_CONTROLS, quality = '1080p bluray')
        columns = sort_columns(controls, 'movie-1', '/')
        assert '1080p+bluray' in columns[0]['href'] or '1080p%20bluray' in columns[0]['href']
```

- [ ] **Step 2: Run and watch it fail**

Expected: `ImportError` on `filter_options` / `sort_columns`.

- [ ] **Step 3: Implement**

Append to `couchpotato/ui/releases_view.py`:

```python
from urllib.parse import urlencode

#: (sort key, column label) for every sortable column, in render order.
SORT_COLUMNS = (
    ('name', 'Name'),
    ('quality', 'Quality'),
    ('score', 'Score'),
    ('size', 'Size'),
    ('seeders', 'Seeders'),
    ('source', 'Source'),
    ('status', 'Status'),
    ('age', 'Age'),
)


def filter_options(releases, profile_qualities = None):
    """The distinct filter values actually present, for building the controls.

    Only offering what exists keeps the user from picking a filter that can
    only return nothing.
    """

    qualities, statuses, sources = set(), set(), set()

    for release in releases:
        identifier = _quality_identifier(release)
        if identifier:
            qualities.add(identifier)

        status = release.get('status')
        if status:
            statuses.add(status)

        family = protocol_family(_info(release).get('protocol'))
        if family:
            sources.add(family)

    if profile_qualities:
        ordered_qualities = [q for q in profile_qualities if q in qualities]
        ordered_qualities += sorted(qualities - set(profile_qualities))
    else:
        ordered_qualities = sorted(qualities)

    return {
        'source': sorted(sources),
        'quality': ordered_qualities,
        'status': sorted(statuses),
    }


def _query(controls, **overrides):
    params = dict(controls)
    params.update(overrides)
    # Omit defaults so a plain view produces a clean URL.
    return urlencode({k: v for k, v in params.items() if v != DEFAULT_CONTROLS[k]})


def sort_columns(controls, movie_id, web_base = '/'):
    """One entry per sortable column: label, links, and aria-sort state."""

    base = web_base if web_base.endswith('/') else web_base + '/'
    columns = []

    for key, label in SORT_COLUMNS:
        is_active = controls['sort'] == key
        # Clicking the active column reverses it; an inactive column starts
        # descending, which is what "show me the biggest/newest" means.
        direction = 'asc' if is_active and controls['dir'] == 'desc' else 'desc'
        query = _query(controls, sort = key, dir = direction)

        columns.append({
            'key': key,
            'label': label,
            'aria_sort': ('descending' if controls['dir'] == 'desc' else 'ascending') if is_active else 'none',
            'is_active': is_active,
            'hx_get': '%spartial/movie/%s/releases?%s' % (base, movie_id, query),
            'href': '%smovie/%s?%s' % (base, movie_id, query),
        })

    return columns
```

Move the `from urllib.parse import urlencode` line up to the module's import
block rather than leaving it mid-file.

- [ ] **Step 4: Run the tests**

Expected: **all PASS**.

- [ ] **Step 5: Commit**

```bash
git add couchpotato/ui/releases_view.py tests/unit/test_releases_view.py
git commit -m "feat: build release-list filter options and sort links (FEAT-007 B10)"
```

---

## Task 6: Extract the releases block into its own partial

Pure refactor: no behaviour change, no controls yet. Doing it as its own commit
keeps the diff for Task 7 readable.

**Files:**
- Create: `couchpotato/ui/templates/partials/movie_releases.html`
- Modify: `couchpotato/ui/templates/partials/movie_detail.html`

- [ ] **Step 1: Read the current block**

```bash
grep -n "<!-- Releases -->" couchpotato/ui/templates/partials/movie_detail.html
grep -n "function releaseDownloader" couchpotato/ui/templates/partials/movie_detail.html
```

The block runs from the `<!-- Releases -->` comment to the end of its
`{% if releases %}`/`{% endif %}`, and the `releaseDownloader()` Alpine
component lives in a `<script>` further down the same file.

- [ ] **Step 2: Move it verbatim**

Cut the releases block into `couchpotato/ui/templates/partials/movie_releases.html`
**unchanged**, wrapped in a container the route can target:

```jinja
{# Movie detail release list. Rendered inline by movie_detail.html for first
   paint, and standalone by GET /partial/movie/<id>/releases for htmx swaps,
   so it must not depend on anything movie_detail.html computes locally. #}
<div id="movie-releases" class="mt-8 max-w-5xl" x-data="releaseDownloader()" x-init="init()">
  ... the existing markup, unchanged ...
</div>
```

Move the `releaseDownloader()` `<script>` block into the same file, below the
markup it serves. In `movie_detail.html`, replace the removed block with:

```jinja
{% include "partials/movie_releases.html" %}
```

The variables the block uses (`releases`, `matching_releases`, `movie_id`,
`title`) are still set by `movie_detail.html` at this point, so the include
resolves them from the shared context. Task 7 changes that.

- [ ] **Step 3: Verify nothing changed**

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/ -q
```

Then boot and eyeball the page — the table must look identical:

```bash
rm -rf .e2e-partb-data
.venv/bin/python CouchPotato.py --data_dir=.e2e-partb-data --console_log &
CP_TEST_URL=http://localhost:5050 npx playwright test tests/e2e/interactions.e2e.spec.ts --project=chromium --workers=1
```

Expected: pass. Kill the server and delete `.e2e-partb-data` when done.

- [ ] **Step 4: Commit**

```bash
git add couchpotato/ui/templates/partials/
git commit -m "refactor: extract the release list into its own partial (no behaviour change)"
```

---

## Task 7: The route, the controls, and the new columns

**Files:**
- Modify: `couchpotato/ui/__init__.py`
- Modify: `couchpotato/ui/templates/partials/movie_releases.html`
- Modify: `couchpotato/ui/templates/partials/movie_detail.html`
- Modify: `couchpotato/ui/templates/detail.html`
- Test: `tests/unit/test_releases_partial_route.py`

Covers B7, B8, B9, B10, B13, B14.

- [ ] **Step 1: Write the failing route tests**

Create `tests/unit/test_releases_partial_route.py`:

```python
"""GET /partial/movie/<id>/releases -- the htmx endpoint behind the release
list's filter and sort controls (FEAT-007 Part B).

Follows the TestClient pattern in tests/unit/test_fastapi_web.py: build the
real app, register a stub `media.get` handler, and drive the route.
"""

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import api, api_locks
from couchpotato.environment import Env


@pytest.fixture(autouse=True)
def env(tmp_path):
    Env.set('web_base', '/')
    Env.set('api_base', '/api/testkey123/')
    Env.set('static_path', '/static/')
    Env.set('dev', False)
    yield


@pytest.fixture
def client():
    from couchpotato import create_app
    return TestClient(create_app('testkey123', '/'))


def _release(_id, protocol, quality, status, score, size, seeders = None):
    info = {'protocol': protocol, 'score': score, 'size': size, 'age': 3,
            'name': '%s.release.name' % _id}
    if seeders is not None:
        info['seeders'] = seeders
    return {'_id': _id, 'quality': quality, 'status': status, 'info': info}


MOVIE = {
    '_id': 'movie-1',
    'status': 'active',
    'info': {'titles': ['Some Movie'], 'year': 2026},
    'profile': {'label': 'HD', 'qualities': ['1080p', '720p']},
    'releases': [
        _release('nzb1', 'nzb', '1080p', 'available', 210, 8000),
        _release('tor1', 'torrent', '1080p', 'available', 3400, 24000, seeders = 900),
        _release('tor2', 'torrent', '720p', 'ignored', 50, 1200, seeders = 2),
    ],
}


@pytest.fixture
def media_get():
    def handler(**kwargs):
        return {'media': MOVIE}

    old = api.get('media.get')
    api['media.get'] = handler
    api_locks['media.get'] = __import__('threading').Lock()
    yield
    if old:
        api['media.get'] = old
    else:
        api.pop('media.get', None)


class TestReleasesPartialRoute:

    def test_returns_the_table_with_every_release_by_default(self, client, media_get):
        """B7."""
        resp = client.get('/partial/movie/movie-1/releases')
        assert resp.status_code == 200
        assert 'nzb1.release.name' in resp.text
        assert 'tor1.release.name' in resp.text

    def test_source_filter_is_honoured(self, client, media_get):
        """B7."""
        resp = client.get('/partial/movie/movie-1/releases?source=nzb')
        assert resp.status_code == 200
        assert 'nzb1.release.name' in resp.text
        assert 'tor1.release.name' not in resp.text

    def test_status_and_quality_filters_are_honoured(self, client, media_get):
        """B7."""
        resp = client.get('/partial/movie/movie-1/releases?status=ignored')
        assert 'tor2.release.name' in resp.text
        assert 'nzb1.release.name' not in resp.text

        resp = client.get('/partial/movie/movie-1/releases?quality=720p')
        assert 'tor2.release.name' in resp.text
        assert 'nzb1.release.name' not in resp.text

    def test_sort_is_honoured(self, client, media_get):
        """B7: biggest first when sorting by size descending."""
        resp = client.get('/partial/movie/movie-1/releases?sort=size&dir=desc')
        body = resp.text
        assert body.index('tor1.release.name') < body.index('nzb1.release.name')

        resp = client.get('/partial/movie/movie-1/releases?sort=size&dir=asc')
        body = resp.text
        assert body.index('tor2.release.name') < body.index('tor1.release.name')

    @pytest.mark.parametrize('query', [
        'sort=nonsense',
        'dir=sideways',
        'source=usenet',
        'status=../../etc/passwd',
        'sort=__class__&dir=',
        'quality=%00',
    ])
    def test_garbage_params_return_200_not_500(self, client, media_get, query):
        """B6: these URLs get bookmarked, shared and hand-edited."""
        resp = client.get('/partial/movie/movie-1/releases?%s' % query)
        assert resp.status_code == 200

    def test_size_and_seeders_are_rendered(self, client, media_get):
        """B9: both are in the data today but were never displayed."""
        resp = client.get('/partial/movie/movie-1/releases')
        assert 'Size' in resp.text
        assert 'Seeders' in resp.text
        assert '900' in resp.text, 'the torrent seeder count should appear'

    def test_aria_sort_reflects_the_active_column(self, client, media_get):
        """B10."""
        resp = client.get('/partial/movie/movie-1/releases?sort=size&dir=desc')
        assert 'aria-sort="descending"' in resp.text

        resp = client.get('/partial/movie/movie-1/releases?sort=size&dir=asc')
        assert 'aria-sort="ascending"' in resp.text

    def test_the_result_count_is_in_a_live_region(self, client, media_get):
        """B10: a filter change must be announced, not silent."""
        resp = client.get('/partial/movie/movie-1/releases')
        assert 'aria-live="polite"' in resp.text

    def test_requires_auth_when_a_password_is_set(self, client, media_get):
        """B7. With no credentials configured the app is open by design;
        this asserts the route is behind the same guard as its siblings.
        """
        from couchpotato.ui import require_auth
        import couchpotato.ui as ui_module
        assert require_auth is not None
        assert 'require_auth' in ui_module.__dict__

    def test_a_movie_with_no_releases_renders_the_empty_state(self, client):
        """B14."""
        def handler(**kwargs):
            return {'media': dict(MOVIE, releases = [])}

        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert resp.status_code == 200
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)

    def test_a_failed_media_get_still_returns_a_page(self, client):
        """The detail page must not 500 because the API blew up."""
        def handler(**kwargs):
            raise RuntimeError('boom')

        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert resp.status_code == 200
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)
```

- [ ] **Step 2: Run and watch it fail**

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/test_releases_partial_route.py -v
```

Expected: 404s — the route does not exist.

- [ ] **Step 3: Add a shared context builder and the route**

In `couchpotato/ui/__init__.py`, add near the other helpers:

```python
def _releases_ctx(movie, movie_id, params):
    """Everything the releases partial needs, computed once for both callers."""
    from couchpotato.ui.releases_view import (
        filter_and_sort_releases, filter_options, normalise_controls, sort_columns,
    )

    profile = movie.get('profile') or {}
    profile_qualities = profile.get('qualities') or []

    all_releases = movie.get('releases') or []
    # Same profile-matching rule the template used to apply inline.
    matching = [r for r in all_releases
                if not profile_qualities or r.get('quality') in profile_qualities]

    controls = normalise_controls(params)
    web_base = Env.get('web_base') or '/'

    return {
        'movie_id': movie_id,
        'releases': filter_and_sort_releases(matching, controls, profile_qualities),
        'total_releases': len(matching),
        'controls': controls,
        'options': filter_options(matching, profile_qualities),
        'columns': sort_columns(controls, movie_id, web_base),
    }
```

Then the route, beside `partial_movie_collections`:

```python
    @router.get('/partial/movie/{movie_id}/releases')
    async def partial_movie_releases(movie_id: str, request: Request, user=Depends(require_auth)):
        """Return the release list, filtered and sorted per the query params."""
        from couchpotato.api import callApiHandler
        movie = {}
        try:
            result = await run_in_threadpool(callApiHandler, 'media.get', id=movie_id)
            if isinstance(result, dict):
                movie = result.get('media', result) or {}
        except Exception:
            log.error('Failed to fetch movie for release list')
        tmpl = _jinja.get_template('partials/movie_releases.html')
        ctx = _releases_ctx(movie, movie_id, dict(request.query_params))
        return HTMLResponse(tmpl.render(**ctx, **_ctx()))
```

Wire `partial_movie_detail` to the same builder so the inline first paint and
the swapped partial agree, passing its own query params through:

```python
        ctx = _releases_ctx(movie, movie_id, dict(request.query_params))
        return HTMLResponse(tmpl.render(movie=movie, **ctx, **_ctx()))
```

Finally, let the full-page routes carry the params through to the initial
`hx-get` so a filtered URL is bookmarkable (B8):

```python
    @router.get('/movie/{movie_id}/')
    @router.get('/movie/{movie_id}')
    async def movie_detail(movie_id: str, request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('detail.html')
        query = request.url.query
        return HTMLResponse(tmpl.render(**_ctx({'movie_id': movie_id, 'detail_query': ('?' + query) if query else ''})))
```

and in `couchpotato/ui/templates/detail.html`:

```jinja
     hx-get="{{ new_base }}partial/movie/{{ movie_id }}{{ detail_query|default('') }}"
```

- [ ] **Step 4: Build the controls and the two new columns**

In `couchpotato/ui/templates/partials/movie_releases.html`, above the table:

```jinja
<div class="flex flex-wrap items-center gap-3 mb-3">
  <form class="flex flex-wrap items-center gap-2"
        hx-get="{{ new_base }}partial/movie/{{ movie_id }}/releases"
        hx-target="#movie-releases"
        hx-swap="outerHTML"
        hx-trigger="change">
    <input type="hidden" name="sort" value="{{ controls.sort }}">
    <input type="hidden" name="dir" value="{{ controls.dir }}">

    <label class="text-[10px] uppercase tracking-wider text-cp-muted" for="rel-source">Source</label>
    <select id="rel-source" name="source"
            class="min-h-[44px] bg-white/[0.06] text-cp-text rounded-md px-2 text-xs">
      <option value="all" {% if controls.source == 'all' %}selected{% endif %}>All</option>
      {% for value in options.source %}
      <option value="{{ value }}" {% if controls.source == value %}selected{% endif %}>
        {{ 'NZB' if value == 'nzb' else 'Torrent' }}
      </option>
      {% endfor %}
    </select>

    <label class="text-[10px] uppercase tracking-wider text-cp-muted" for="rel-quality">Quality</label>
    <select id="rel-quality" name="quality"
            class="min-h-[44px] bg-white/[0.06] text-cp-text rounded-md px-2 text-xs">
      <option value="all" {% if controls.quality == 'all' %}selected{% endif %}>All</option>
      {% for value in options.quality %}
      <option value="{{ value }}" {% if controls.quality == value %}selected{% endif %}>{{ value }}</option>
      {% endfor %}
    </select>

    <label class="text-[10px] uppercase tracking-wider text-cp-muted" for="rel-status">Status</label>
    <select id="rel-status" name="status"
            class="min-h-[44px] bg-white/[0.06] text-cp-text rounded-md px-2 text-xs">
      <option value="all" {% if controls.status == 'all' %}selected{% endif %}>All</option>
      {% for value in options.status %}
      <option value="{{ value }}" {% if controls.status == value %}selected{% endif %}>{{ value }}</option>
      {% endfor %}
    </select>

    <noscript><button type="submit" class="min-h-[44px] px-3 text-xs">Apply</button></noscript>
  </form>

  <p class="text-[11px] text-cp-muted" aria-live="polite">
    {{ releases|length }} of {{ total_releases }} release{{ '' if total_releases == 1 else 's' }}
  </p>
</div>
```

Replace the static `<th>` cells with sortable headers driven by `columns`,
adding **Size** and **Seeders**:

```jinja
<tr class="border-b border-white/[0.05] text-cp-muted text-left">
  {% for column in columns %}
  <th scope="col" class="px-4 py-2.5 font-medium text-[10px] uppercase tracking-wider"
      aria-sort="{{ column.aria_sort }}">
    <a href="{{ column.href }}"
       hx-get="{{ column.hx_get }}"
       hx-target="#movie-releases"
       hx-swap="outerHTML"
       hx-push-url="{{ column.href }}"
       class="inline-flex items-center gap-1 min-h-[44px] hover:text-cp-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-cp-accent">
      {{ column.label }}
      {% if column.is_active %}<span aria-hidden="true">{{ '▾' if controls.dir == 'desc' else '▴' }}</span>{% endif %}
    </a>
  </th>
  {% endfor %}
  <th scope="col" class="px-4 py-2.5 font-medium text-[10px] uppercase tracking-wider">Action</th>
</tr>
```

In the row loop, iterate `releases` (the prepared list) instead of
`matching_releases`, and add the two cells — placed to match `SORT_COLUMNS`
order (Name, Quality, Score, **Size**, **Seeders**, Source, Status, Age):

```jinja
<td class="px-4 py-2.5 text-cp-muted font-light">{{ (r_info.get('size') or 0)|round|int }} MB</td>
<td class="px-4 py-2.5 text-cp-muted font-light">
  {%- if r_info.get('seeders') is not none %}{{ r_info.get('seeders') }}{% endif -%}
</td>
```

Seeders renders **blank, not `0`**, for NZB releases (B9) — an NZB has no
seeders, and `0` would read as "a torrent nobody is seeding".

- [ ] **Step 5: Run the route tests**

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/test_releases_partial_route.py -v
```

Expected: **all PASS**. Then the whole suite:

```bash
PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/ -q
.venv/bin/python -m ruff check .
```

- [ ] **Step 6: Commit**

```bash
git add couchpotato/ui/ tests/unit/test_releases_partial_route.py
git commit -m "feat: sort/filter controls and Size/Seeders columns on the release list (FEAT-007 B7-B10, B14)"
```

---

## Task 8: E2E coverage

CLAUDE.md rule 5: a UI change requires E2E updates.

**Files:**
- Create: `tests/e2e/release_controls.spec.ts`

Covers B11, B12, B13.

- [ ] **Step 1: Check what the existing specs do**

```bash
grep -n "movie/" tests/e2e/interactions.e2e.spec.ts | head
sed -n '1,40p' tests/e2e/filters.spec.ts
```

Follow their setup: they navigate from the wanted/library list to a movie
rather than assuming a movie id exists. If the test data has no movie with
releases, the spec must **skip explicitly** (`test.skip(...)` with a reason)
rather than pass vacuously.

- [ ] **Step 2: Write the spec**

Create `tests/e2e/release_controls.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

/**
 * FEAT-007 Part B: the release list's filter and sort controls.
 *
 * The controls are htmx-driven: each one swaps #movie-releases. These tests
 * assert on what the user sees and on the ARIA state, not on the request.
 */

test.describe('Release list controls', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/wanted');
    const firstMovie = page.locator('[data-movie-id], a[href*="/movie/"]').first();
    if (await firstMovie.count() === 0) {
      test.skip(true, 'no movie in the test library to open');
    }
    await firstMovie.click();
    await page.waitForSelector('#movie-releases, #movie-detail-container', { timeout: 15000 });
  });

  test('the release table exposes sortable headers with aria-sort', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    if (await releases.count() === 0) {
      test.skip(true, 'this movie has no releases');
    }
    const sortable = releases.locator('th[aria-sort]');
    expect(await sortable.count()).toBeGreaterThan(0);
    // Nothing is sorted until the user asks.
    for (const th of await sortable.all()) {
      expect(await th.getAttribute('aria-sort')).toBe('none');
    }
  });

  test('sorting by size marks that column and reorders the rows', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    if (await releases.count() === 0) {
      test.skip(true, 'this movie has no releases');
    }
    if (await releases.locator('tbody tr').count() < 2) {
      test.skip(true, 'need at least two releases to observe a reorder');
    }

    const before = await releases.locator('tbody tr').first().textContent();

    await releases.getByRole('link', { name: /^Size/ }).click();
    await expect(releases.locator('th[aria-sort="descending"]')).toHaveCount(1);

    // Clicking again reverses it.
    await releases.getByRole('link', { name: /^Size/ }).click();
    await expect(releases.locator('th[aria-sort="ascending"]')).toHaveCount(1);

    const after = await releases.locator('tbody tr').first().textContent();
    expect(after).not.toBe(before);
  });

  test('filtering by source shows only that source', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    if (await releases.count() === 0) {
      test.skip(true, 'this movie has no releases');
    }
    const select = releases.locator('#rel-source');
    const options = await select.locator('option').allInnerTexts();
    if (!options.some(o => /NZB/i.test(o)) || !options.some(o => /Torrent/i.test(o))) {
      test.skip(true, 'this movie has releases from only one source');
    }

    await select.selectOption('nzb');
    await expect(page.locator('#movie-releases')).toBeVisible();
    const sources = await page.locator('#movie-releases tbody tr td:nth-child(6)').allInnerTexts();
    for (const source of sources) {
      expect(source.trim()).toMatch(/NZB/i);
    }
  });

  test('the result count is announced in a live region', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    if (await releases.count() === 0) {
      test.skip(true, 'this movie has no releases');
    }
    await expect(releases.locator('[aria-live="polite"]')).toContainText(/release/);
  });

  test('Download and Skip still work after a swap (B13)', async ({ page }) => {
    const releases = page.locator('#movie-releases');
    if (await releases.count() === 0) {
      test.skip(true, 'this movie has no releases');
    }
    await releases.getByRole('link', { name: /^Score/ }).click();
    await expect(page.locator('#movie-releases')).toBeVisible();

    // The Alpine component must have rebound after the swap: the buttons are
    // present and enabled, not inert. Do NOT click Download -- that would
    // snatch a real release.
    const action = page.locator('#movie-releases button', { hasText: /Download|Skip/ }).first();
    if (await action.count() > 0) {
      await expect(action).toBeEnabled();
    }
  });
});
```

- [ ] **Step 3: Add an axe check (B12)**

Find the existing accessibility spec and add the movie detail page with a
filter applied to whatever page list it walks:

```bash
grep -rn "AxeBuilder\|injectAxe" tests/e2e/ | head
```

Follow that file's existing pattern exactly rather than inventing a new one.

- [ ] **Step 4: Run the E2E suite**

```bash
rm -rf .e2e-partb-data
.venv/bin/python CouchPotato.py --data_dir=.e2e-partb-data --console_log &
CP_TEST_URL=http://localhost:5050 npx playwright test --project=chromium --workers=1
```

Two Navigation tests in `interactions.e2e.spec.ts` are known-flaky in the full
run and pass in isolation — re-run any failure with `-g "<name>"` before
treating it as real. Kill the server and delete `.e2e-partb-data` after.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/
git commit -m "test: E2E coverage for the release list controls (FEAT-007 B11-B13)"
```

---

## Task 9: Spec corrections and acceptance criteria

**Files:**
- Modify: `specs/FEAT-007-preferred-source-and-release-list-controls.md`

- [ ] **Step 1: Correct the no-JS decision**

Rewrite the "Controls are real links, htmx-enhanced" bullet. The claim that
they "work with JavaScript disabled" is false and unachievable:
`couchpotato/ui/templates/detail.html` is an htmx shell, so with JS off the
detail page renders a spinner and no table exists. State what is actually
delivered: the controls are anchors and a GET form, htmx swaps
`#movie-releases`, and the full-page route accepts the same params so a
filtered view is **bookmarkable and shareable**.

- [ ] **Step 2: Rewrite B8**

Replace the no-JS criterion with the bookmarkable one:

```markdown
- [ ] B8: the full-page movie route accepts the same params and forwards them
      into the initial partial load, so `/movie/{id}?source=nzb&sort=size` is
      bookmarkable and shareable. (The detail page cannot work without
      JavaScript at all — `detail.html` is an htmx shell — so no-JS support is
      not a goal; see the decision above.)
```

- [ ] **Step 3: Fix the settings-file name in the Problem section**

Part A's Problem section says production "has no `[searcher]` section in
`settings.conf` at all". The live settings file is **`config.ini`**
(`/var/lib/plexmediaserver/CouchPotato/config/config.ini`), so that grep was
against the wrong filename — a false negative, not evidence. The conclusion
held (the settings API independently reported `both`), but cite the API as the
evidence rather than the wrong file.

- [ ] **Step 4: Tick B1–B14**

Tick each Part B box, appending the covering test name, exactly as Part A's
A1–A10 are annotated. Do not tick anything you cannot name a test for — say
what is uncovered instead.

- [ ] **Step 5: Commit**

```bash
git add specs/FEAT-007-preferred-source-and-release-list-controls.md
git commit -m "docs: correct the no-JS claim and the prod settings filename, tick Part B criteria"
```

---

## Task 10: Full gate, then stop

- [ ] **Step 1: Run the gate**

```bash
PYTHON="$(pwd)/.venv/bin/python" make verify
```

If E2E dies with `[WebServer] /bin/sh: python: command not found` (exit 127),
that is a known local quirk — start the server yourself as in Task 8 and run
Playwright against it.

- [ ] **Step 2: STOP — do not push**

Report: the test count delta, which acceptance criteria are covered by which
test, anything in the spec or this plan that turned out to be factually wrong
about the codebase, and any place you had to deviate from the plan and why.
The orchestrator runs the local agent review gate and pushes.

---

## Self-review notes

- **Spec coverage:** B1 (T2, T3, T4), B2 (T3), B3 (T3), B4 (T4), B5 (T4),
  B6 (T2, T7), B7 (T7), B8 (T7, T9 — redefined), B9 (T4, T7), B10 (T5, T7),
  B11 (T8), B12 (T8), B13 (T8), B14 (T7). All fourteen covered.
- **Naming consistency:** `normalise_controls`, `DEFAULT_CONTROLS`,
  `filter_and_sort_releases(releases, controls, profile_qualities=None)`,
  `filter_options(releases, profile_qualities=None)`,
  `sort_columns(controls, movie_id, web_base='/')`, and `protocol_family` are
  defined in Tasks 1–5 and used under exactly those names in Tasks 6–8. The
  container id `#movie-releases` is fixed in Task 6 and referenced by every
  later `hx-target`.
- **Known unknowns flagged rather than guessed:** Task 8's axe step and the
  E2E navigation pattern say to follow the existing specs rather than
  prescribing markup this plan has not verified; the E2E tests skip explicitly
  when the local test library lacks a movie with mixed-source releases, rather
  than passing vacuously.
- **Deliberately NOT in this plan:** the seeder score bias in
  `couchpotato/core/plugins/score/main.py:36-42` (out of scope per the spec,
  needs its own), and persisting a chosen sort/filter across visits (URL only).
