# FEAT-007: Preferred download source, and sort/filter for the release list

> Owner-approved design, 2026-07-29. Two parts. Part A makes an existing but
> undiscoverable and untested behaviour explicit and safe; Part B adds the
> controls that let you see and act on what each source actually offers.
> They may ship as two PRs, but A lands first: B's default ordering is
> A's output.

## Problem

Two separate problems, reported together as "I want to prefer NZB, and most
results are torrents".

**A. The preference already exists but is unfindable, unsafe to rely on, and
undermined by scoring.**

A tri-state `preferred_method` setting is already defined
(`couchpotato/core/media/_base/searcher/__init__.py:18-24`) with values
`both` / `nzb` / `torrent`, and it is honoured in two places:

- `couchpotato/core/media/_base/searcher/main.py:61-63` — orders the candidate
  list that `release.try_download_result` walks, so it decides what gets
  downloaded automatically.
- `couchpotato/core/plugins/release/main.py:677-679` — orders the release list
  the UI shows (via `release.for_media`, reached from
  `couchpotato/core/media/_base/library/main.py:122`).

Three things are wrong with it:

1. **It is labelled "First search"**, described as "Which of the methods do you
   prefer", with values "usenet & torrents / usenet / torrents". Nothing about
   that says "this decides which source wins". The production instance has no
   `[searcher]` section in `settings.conf` at all, i.e. it has sat at the
   `both` default since install.
2. **It has zero test coverage.** `grep -rn preferred_method tests/` returns
   nothing. The behaviour is implemented twice, by hand, with a
   `protocol[:3]` string trick, against two different key paths
   (`rel['protocol']` vs `rel['info']['protocol']`). Nothing stops the two
   copies drifting, and nothing catches it if they do.
3. **The two copies already differ in a way that is a latent bug.** In
   `forMedia`, a release with a missing or unknown protocol yields `''`, which
   sorts *before* `'nzb'` ascending — so unknown-protocol releases float to the
   **top** of the list when you prefer usenet, and sink when you prefer
   torrents. Direction-dependent placement of unknown data is not intended
   behaviour in either direction.

Separately, and the actual reason torrents dominate today:
`couchpotato/core/plugins/score/main.py:36-42` adds
`seeders * 100/15 + leechers * 100/30` to a torrent's score. A torrent with 50
seeders gains **+333**. The entire name/quality scoring vocabulary in
`couchpotato/core/plugins/score/scores.py:14-28` spans roughly -40 to +15, with
preferred-word matches at +100 each. So under `both`, torrents do not compete
with NZBs on merit — they outrank them by an order of magnitude regardless of
quality. See *Out of scope* below.

**B. The release list cannot be sorted or filtered.**

The releases table (`couchpotato/ui/templates/partials/movie_detail.html:244`
onward) is a static server-rendered table: Name, Quality, Score, Source,
Status, Age, Action. There are no controls. `info.size` and `info.seeders` are
carried in the data but never rendered, so the two fields most useful for
choosing between releases by hand are invisible.

## Goal

- **A:** the preference is named for what it does, behaves identically in both
  call sites, is covered by tests, and treats unknown protocols consistently.
  No change to the *semantics* the owner already chose: a hard preference that
  falls back.
- **B:** the release list can be filtered by source, quality and status, and
  sorted by any meaningful column including size and seeders — without changing
  what the page shows when no control has been touched.

## Decisions (owner-approved 2026-07-29)

- **Hard preference, not a score bonus.** Any release of the preferred protocol
  that passes the existing filters (`minimum_score`, `minimum_seeders`, size,
  ignored/failed status) is taken over any release of the other protocol, even
  a substantially better one. This is what the code already does; it is now the
  documented, tested contract.
- **Fallback, not exclusion.** When no acceptable release of the preferred
  protocol exists, the other protocol is used. There is no "usenet only" mode
  and no "wait for an NZB" mode; a fourth strict state was considered and
  rejected. **Known limitation, carried forward unchanged from before this
  change:** "acceptable" means the release passes `tryDownloadResult`'s
  FILTERS (status / minimum_score / size / seeders). Fallback happens when
  the preferred release is filtered out, NOT when its download fails --
  if a preferred-protocol release passes every filter but the download
  itself then fails (downloader disabled/unreachable, provider error),
  `tryDownloadResult` does not advance to the next candidate and the other
  protocol is never tried for that search. This is pre-existing behaviour,
  not introduced by this PR; it is pinned by
  `tests/unit/test_protocol_preference.py::TestFallbackToTheOtherProtocol::test_a_download_failure_does_not_fall_through_to_the_other_protocol`
  so the gap stays visible rather than contradicted by the setting's
  description.
- **`torrent_magnet` groups with `torrent`.** It is a torrent as far as the
  preference is concerned.
- **Unknown protocol sorts last** in both directions, replacing the current
  direction-dependent behaviour.
- **Server-side sort/filter over htmx**, not client-side Alpine. It keeps a
  single Jinja rendering path and fits the htmx-first architecture; the cost is
  a round-trip per interaction, which is acceptable for a LAN app.
- **Controls are real links, htmx-enhanced.** They render as
  `<a href="/movie/{id}?source=nzb&sort=size&dir=desc">` and the full-page
  route (`ui/__init__.py:106-107`, which registers both the trailing-slash and
  bare forms — both must accept the params) honours the same query params, so
  they work with JavaScript disabled. htmx intercepts to swap only the table.
- **Defaults preserve today's output.** With no query params the list renders
  exactly as it does now: score order, then Part A's protocol preference.

## Part A — Preferred download source

### Design

**Relabel** in `couchpotato/core/media/_base/searcher/__init__.py`:

| Field | From | To |
|---|---|---|
| `label` | `First search` | `Preferred download source` |
| `description` | `Which of the methods do you prefer` | `Prefer this source when both have acceptable releases. Falls back to the other if nothing suitable is found.` |
| `values` | `usenet & torrents` / `usenet` / `torrents` | `No preference` / `Usenet (NZB)` / `Torrents` |

The stored values (`both`, `nzb`, `torrent`) are **unchanged** — only display
strings change, so existing `settings.conf` files keep working untouched.

**Extract one helper.** A new module `couchpotato/core/helpers/protocol.py`
exposing:

```python
def sort_by_protocol_preference(items, preference, get_protocol):
    """Stable-sort `items` so the preferred protocol comes first.

    preference: 'both' | 'nzb' | 'torrent'. 'both' returns items unchanged.
    get_protocol: callable mapping an item to its protocol string.
    Rank: preferred = 0, other known = 1, unknown/missing = 2.
    """
```

Ranking is explicit rather than the `[:3]` string trick. Both call sites
(`searcher/main.py:61-63` and `release/main.py:677-679`) delegate to it,
passing the getter appropriate to their data shape.

`couchpotato/core/helpers/` is the right home: both call sites already import
from `couchpotato.core.helpers.variable`, so the import path is established and
adds no cycle. Putting the helper under the `searcher` package instead would
make `release/main.py` import a package whose `__init__.py` pulls in
`Searcher` and the plugin base — a cycle risk for no benefit.

Stability matters and is load-bearing: both callers sort by score *first*, then
by protocol, and rely on Python's stable sort to preserve score order within
each protocol group.

### Acceptance criteria — Part A

- [ ] A1: with `preferred_method = 'nzb'`, every NZB release precedes every
      torrent release in both `Searcher.search()` and `Release.forMedia()`,
      regardless of score.
- [ ] A2: with `preferred_method = 'torrent'`, the reverse holds.
- [ ] A3: with `preferred_method = 'both'`, order is score-descending only —
      the helper returns the list unchanged.
- [ ] A4: within a protocol group, score-descending order is preserved (sort
      stability) for all three preference values.
- [ ] A5: `torrent_magnet` is ranked with `torrent`, not as unknown.
- [ ] A6: a release with a missing, empty or unrecognised protocol sorts
      **last** under `'nzb'` *and* under `'torrent'`.
- [ ] A7: both call sites use the shared helper — no remaining hand-rolled
      protocol sort, verified by test, not by eye.
- [ ] A8: an empty list, and a list with a single item, are handled without
      error for every preference value.
- [ ] A9: the config option renders in Settings → Searcher → Basics with the
      new label and value labels, and an existing `settings.conf` containing
      `preferred_method = nzb` is still read correctly (stored values unchanged).
- [ ] A10: fallback is explicit — when the preferred protocol has no release
      passing `tryDownloadResult`'s filters, a release of the other protocol is
      still downloaded.

## Part B — Sort/filter for the release list

### Design

**Route.** `GET /partial/movie/{movie_id}/releases`, registered in
`couchpotato/ui/__init__.py` beside the existing
`/partial/movie/{movie_id}/collections` (line 311), with the same
`Depends(require_auth)` guard. Query params: `source`, `quality`, `status`,
`sort`, `dir`.

**One pure function.** `couchpotato/ui/releases_view.py`:

```python
def filter_and_sort_releases(releases, *, source='all', quality='all',
                             status='all', sort='default', dir='desc'):
```

No FastAPI, no Jinja, no database — a list in, a list out, so it is unit
testable directly. It is the only place release ordering logic lives.

- `source`: `all` | `nzb` | `torrent` (the latter matches `torrent_magnet` too)
- `quality`: `all` | any quality identifier present in the supplied list.
  Release documents store `quality` as an identifier **string**
  (`release/main.py:183`, `:501`), but the template already defends against a
  dict (`movie_detail.html:279`), so the filter reads the identifier from
  either shape and treats anything else as no-match.
- `status`: `all` | `available` | `snatched` | `done` | `ignored` | `failed`
- `sort`: `default` | `name` | `quality` | `score` | `source` | `status` |
  `age` | `size` | `seeders`
- `dir`: `asc` | `desc`
- `sort='default'` returns the input order untouched — i.e. whatever
  `release.for_media` already produced, which is Part A's output. `dir` is
  ignored in this case rather than reversing the default order.

**Templates.** The releases block moves out of `movie_detail.html` into
`partials/movie_releases.html`, which `movie_detail.html` `{% include %}`s.
First paint stays server-rendered with no extra round-trip; the partial route
renders the same template for htmx swaps. The `releaseDownloader()` Alpine
component (`movie_detail.html:412`) moves with the block it serves, and the
existing Download / Skip actions must keep working after a swap.

**Columns.** Add **Size** (from `info.size`, MB) and **Seeders** (from
`info.seeders`, blank for NZB). Existing columns are unchanged.

**Accessibility.** Sortable headers are buttons inside `<th>` carrying
`aria-sort="ascending|descending|none"`, updated to match current state. The
filter controls are a labelled group. A result count lives in an
`aria-live="polite"` region so a filter change is announced. Touch targets on
the controls meet the 44px floor from the global standards.

**Error handling.** Unrecognised `sort`, `dir`, `source`, `quality` or `status`
values fall back to their defaults rather than raising — these values arrive
from URLs that can be bookmarked, shared or hand-edited. Releases missing
`size`/`seeders` sort last rather than crashing the comparison. A failed
`media.get` renders the existing empty state.

### Acceptance criteria — Part B

- [ ] B1: `filter_and_sort_releases` with all defaults returns the input list
      in its original order, unmodified.
- [ ] B2: `source='nzb'` returns only NZB releases; `source='torrent'` returns
      both `torrent` and `torrent_magnet`.
- [ ] B3: `quality` and `status` filters each return only matching releases,
      and compose with `source` (all three applied together).
- [ ] B4: every `sort` key orders correctly in both directions, including
      `size` and `seeders`.
- [ ] B5: releases missing the sorted-on field sort last in both directions and
      never raise.
- [ ] B6: unrecognised values for any param fall back to the default and return
      a 200, not a 500.
- [ ] B7: `GET /partial/movie/{id}/releases` requires auth, returns the table
      HTML, and honours all five params.
- [ ] B8: the full-page movie route honours the same params, so the controls
      work as plain links with JavaScript disabled.
- [ ] B9: Size and Seeders columns render; Seeders is blank (not `0`) for NZB
      releases.
- [ ] B10: sortable headers expose `aria-sort` reflecting the active sort, and
      the result count is in an `aria-live` region.
- [ ] B11: E2E — filter to NZB, confirm only NZB rows remain; sort by size,
      confirm row order and that `aria-sort` updated (CLAUDE.md rule 5).
- [ ] B12: E2E/axe — no new accessibility violations on the detail page with
      filters applied.
- [ ] B13: Download and Skip still work on a row after an htmx swap (the Alpine
      component rebinds).
- [ ] B14: a movie with no releases still renders the existing empty state,
      with controls either hidden or inert.

## Out of scope

- **The seeder score bias** (`couchpotato/core/plugins/score/main.py:36-42`).
  The hard preference routes around it, but it still means "No preference" is
  not neutral, and it distorts score ordering *within* the torrent group. Worth
  its own spec; deliberately not smuggled into this change.
- **Per-profile or per-movie source preference.** The setting stays global.
- **A strict "usenet only, never torrent" mode.** Considered and rejected.
- **Persisting the user's chosen sort/filter** across visits. The params live
  in the URL only.

## Affected files

- `couchpotato/core/media/_base/searcher/__init__.py` — config label,
  description, value labels
- `couchpotato/core/media/_base/searcher/main.py` — call the shared helper
- `couchpotato/core/plugins/release/main.py` — call the shared helper
- new: `couchpotato/core/helpers/protocol.py` —
  `sort_by_protocol_preference()`
- new: `couchpotato/ui/releases_view.py` — `filter_and_sort_releases`
- `couchpotato/ui/__init__.py` — new partial route; full-page route accepts the
  same params
- new: `couchpotato/ui/templates/partials/movie_releases.html` — extracted from
  `movie_detail.html`
- `couchpotato/ui/templates/partials/movie_detail.html` — include the partial;
  Size/Seeders columns; controls
- new: `tests/unit/` — helper tests (Part A), `filter_and_sort_releases` tests
  and route tests (Part B)
- `tests/e2e/` — filter/sort coverage per CLAUDE.md rule 5
- `docs/design-system/CONFORMANCE.md` — if the new controls introduce patterns
  the conformance gate checks
