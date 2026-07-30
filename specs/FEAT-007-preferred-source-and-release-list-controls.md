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
   that says "this decides which source wins". The production instance has
   sat at the `both` default since install — confirmed via the settings API
   (`preferred_method` reported as `both`), not by grepping the config file:
   an earlier draft of this section cited a `grep` against `settings.conf`
   turning up no `[searcher]` section, but production's actual settings file
   is `config.ini` (`/var/lib/plexmediaserver/CouchPotato/config/config.ini`),
   so that grep was a false negative against the wrong filename, not
   evidence. The `both`-default conclusion is unaffected — the settings API
   check is independent of the file lookup — but the file-based citation was
   wrong and is corrected here rather than left to imply the grep was
   meaningful.
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
  direction-dependent behaviour. **Accepted consequence:** `Release.add()`
  (`couchpotato/core/plugins/release/main.py`, around lines 180-188) creates
  release documents with no `info` key at all -- these represent movies the
  library scanner found, i.e. copies the user already owns. Under a non-`both`
  `preferred_method`, these scanner-created releases now rank as unknown and
  sort LAST, where under the old direction-dependent behaviour they sorted
  FIRST for one preference direction. Verified side by side: master orders
  `['done-no-info', 'nzb', 'torrent', 'magnet']` under an nzb preference,
  this change orders `['nzb', 'torrent', 'magnet', 'done-no-info']`. The point
  is that the unknown release now sorts LAST under both preference
  directions, rather than first under one of them. This has a knock-on: BOTH
  `couchpotato/ui/templates/partials/movie_detail.html:20-23` and
  `couchpotato/ui/templates/partials/movie_cards.html:12-16` pick
  `completed_releases[0]` for the downloaded quality/status they display (the
  detail header and the poster-grid badge respectively), so for a movie with
  both a scanner-created `done` release and another completed release carrying
  protocol info, which one they show can flip. Those two templates are the
  only order-sensitive consumers of `release.for_media`; every other caller
  iterates the whole list. This is accepted as a correct consequence of fixing
  the direction-dependent bug, not a new defect, and is pinned by a test (see
  Acceptance criteria A10 note and `tests/unit/test_protocol_preference.py`).
- **Server-side sort/filter over htmx**, not client-side Alpine. It keeps a
  single Jinja rendering path and fits the htmx-first architecture; the cost is
  a round-trip per interaction, which is acceptable for a LAN app.
- **Controls are real links and a GET form, htmx-enhanced — bookmarkable, not
  no-JS.** Sortable column headers render as
  `<a href="/movie/{id}?source=nzb&sort=size&dir=desc">` with an `hx-get`
  alongside; the source/quality/status filters are a GET `<form>`. **Design
  correction (made while implementing this plan, see
  `docs/plans/2026-07-30-release-list-sort-filter.md`):** an earlier version
  of this bullet claimed these "work with JavaScript disabled" — that is not
  achievable and was dropped. `couchpotato/ui/templates/detail.html` is a
  five-line htmx shell: the entire movie detail body, releases table
  included, is fetched by `hx-get` on `load`, so with JS off the page is a
  spinner and there is no table to enhance in the first place. What the
  anchor/form markup actually buys, and the real reason for the decision, is
  **bookmarkable and shareable URLs**: the full-page route
  (`ui/__init__.py`, which registers both the trailing-slash and bare
  `/movie/{id}` forms — both must accept the params) forwards the same query
  params into that initial `hx-get`, so `/movie/{id}?source=nzb&sort=size`
  restores that exact filtered/sorted view on first paint. htmx intercepts
  clicks/changes afterwards to swap only `#movie-releases`.
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

- [x] A1: with `preferred_method = 'nzb'`, every NZB release precedes every
      torrent release in both `Searcher.search()` and `Release.forMedia()`,
      regardless of score. (`test_nzb_preference_puts_every_nzb_before_every_torrent`,
      `test_nzb_preference_orders_nzb_first_regardless_of_score`,
      `test_nzb_preference_lists_nzb_first`)
- [x] A2: with `preferred_method = 'torrent'`, the reverse holds.
      (`test_torrent_preference_puts_every_torrent_before_every_nzb`,
      `test_torrent_preference_orders_torrents_first`,
      `test_torrent_preference_lists_torrents_first`)
- [x] A3: with `preferred_method = 'both'`, order is score-descending only —
      the helper returns the list unchanged. (`test_both_leaves_the_incoming_order_untouched`,
      `test_both_preserves_pure_score_order`, `test_both_lists_in_score_order`)
- [x] A4: within a protocol group, score-descending order is preserved (sort
      stability) for all three preference values.
      (`test_score_order_is_preserved_within_each_protocol_group`,
      `test_score_order_is_preserved_within_the_group_under_a_torrent_preference`,
      `test_score_order_survives_inside_the_preferred_group`,
      `test_both_leaves_the_incoming_order_untouched`)
- [x] A5: `torrent_magnet` is ranked with `torrent`, not as unknown.
      (`test_torrent_magnet_ranks_with_torrent`)
- [x] A6: a release with a missing, empty or unrecognised protocol sorts
      **last** under `'nzb'` *and* under `'torrent'`.
      (`test_unknown_protocol_sorts_last_when_preferring_nzb`,
      `test_unknown_protocol_sorts_last_when_preferring_torrent_too`,
      `test_missing_or_unrecognised_protocols_are_treated_as_unknown`,
      `test_a_release_with_no_protocol_is_listed_last_not_first`)
- [x] A7: both call sites use the shared helper — no remaining hand-rolled
      protocol sort, verified by test, not by eye. (`test_search_uses_the_shared_helper`,
      `test_for_media_uses_the_shared_helper` — strengthened to assert on
      `call_args`, not just `.called`)
- [x] A8: an empty list, and a list with a single item, are handled without
      error for every preference value. (`test_empty_and_single_item_lists_are_safe`)
- [x] A9: the config option is defined with the new label and value labels, and
      an existing `settings.conf` containing `preferred_method = nzb` is still
      read correctly (stored values unchanged).
      (`TestPreferredMethodConfigOption` asserts on the config data structure —
      it does NOT assert rendering; that the settings page renders the option
      was verified manually against a running instance via the settings API,
      not by an automated test. The real config-file read is covered by
      `TestPreferredMethodRealSettingsPlumbing::test_preferred_method_is_read_through_the_real_settings_and_env_plumbing`,
      which goes through `Settings` → `Env.setting` → `Plugin.conf`.)
- [x] A10: fallback is explicit — when the preferred protocol has no release
      passing `tryDownloadResult`'s filters, a release of the other protocol is
      still downloaded. **Verification, not implementation** — this was
      confirmed working for filter rejections
      (`test_a_torrent_is_downloaded_when_no_nzb_was_found`,
      `test_a_torrent_is_downloaded_when_the_preferred_nzb_fails_the_filters`,
      `test_the_preferred_release_still_wins_when_it_passes`), with the
      download-failure limitation called out and pinned separately
      (`test_a_download_failure_does_not_fall_through_to_the_other_protocol`
      — see "Fallback, not exclusion" above).

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

**Accessibility.** Sortable headers are **links** (`<a>`, not buttons) inside
`<th>` carrying `aria-sort="ascending|descending|none"`, updated to match
current state — a link is the correct role here since each one navigates to
a different bookmarkable URL (see the "Controls are real links" decision
above); `tests/e2e/release_controls.spec.ts` asserts on
`getByRole('link', ...)` accordingly. **Correction:** an earlier version of
this bullet said "buttons"; that was wrong even at the design stage, since
the sort links carry `href`s that must work with `hx-push-url` for B8's
bookmarkability, which a `<button>` cannot do without extra JS. The filter
controls are a labelled `<form>` group. A result count lives in an
`aria-live="polite"` region, hosted in `detail.html`'s static shell (not
inside the swapped `#movie-releases`, and updated via
`hx-swap-oob="innerHTML"` -- see the B10 correction below),
so a filter change is announced. **Correction (found during the pre-push
review that also fixed B13/B14 below):** "touch targets meet the 44px
floor from the global standards" overstated it for the sort links. Measured
(Playwright `boundingBox()` against the seeded fixture): every sort link is
44px tall (`min-h-[44px]` holds), but width varies by column label length --
from about 20px (`Age`) up to 44px (`Seeders`), several columns (`Age`,
`Size`, `Name`, `Score`) well under a 44×44 square. They meet WCAG 2.5.8
(Target Size, Level AA -- 24×24px minimum) only via that criterion's
spacing exception (adjacent targets are far enough apart), not on raw
target size; they do not meet the stricter 44×44 floor CLAUDE.md's global
standards ask for on their own. The filter `<select>`s (`min-h-[44px]`,
full-width-ish column) are not affected by this.

**Error handling.** Unrecognised `sort`, `dir`, `source`, `quality` or `status`
values fall back to their defaults rather than raising — these values arrive
from URLs that can be bookmarked, shared or hand-edited. Releases missing
`size`/`seeders` sort last rather than crashing the comparison. A failed
`media.get` renders the existing empty state.

### Acceptance criteria — Part B

- [x] B1: `filter_and_sort_releases` with all defaults returns the input list
      in its original order, unmodified.
      (`test_defaults_return_everything_in_the_given_order`,
      `test_sort_default_preserves_the_incoming_order`,
      `test_no_input_yields_the_documented_defaults`,
      `test_defaults_are_the_no_op_view` — all in `tests/unit/test_releases_view.py`)
- [x] B2: `source='nzb'` returns only NZB releases; `source='torrent'` returns
      both `torrent` and `torrent_magnet`.
      (`test_source_nzb_returns_only_nzb`, `test_source_torrent_includes_magnets`,
      `test_a_release_with_an_unknown_protocol_is_excluded_by_either_source_filter`)
- [x] B3: `quality` and `status` filters each return only matching releases,
      and compose with `source` (all three applied together).
      (`test_quality_filter_matches_the_identifier`,
      `test_quality_filter_tolerates_a_dict_shaped_quality`, `test_status_filter`,
      `test_all_three_filters_compose`)
- [x] B4: every `sort` key orders correctly in both directions, including
      `size` and `seeders`.
      (`test_numeric_sorts_in_both_directions` (parametrised over score/size/
      seeders/age), `test_fractional_sizes_and_scores_are_not_truncated`,
      `test_name_sorts_case_insensitively`,
      `test_source_and_status_sort_alphabetically_by_their_displayed_value`,
      `test_quality_sorts_by_profile_order_not_alphabetically`,
      `test_quality_sort_without_a_profile_falls_back_to_the_identifier`,
      `test_sorting_is_stable_for_equal_values`). **Correction:**
      `test_quality_sorts_by_profile_order_not_alphabetically` originally used
      a profile of `['1080p', '720p']`, whose order already IS alphabetical,
      so it passed even with `_quality_key`'s profile-index lookup replaced
      outright by `return identifier.lower()` (confirmed with that exact
      substitution). It now uses `['720p', '1080p']`, where profile order and
      alphabetical order disagree, so only a genuine profile-index lookup
      passes.
- [x] B5: releases missing the sorted-on field sort last in both directions and
      never raise.
      (`test_releases_missing_the_sorted_field_go_last_in_both_directions`
      (parametrised over every sort key × both directions),
      `test_an_nzb_has_no_seeders_so_it_sorts_last_by_seeders`,
      `test_a_none_valued_field_counts_as_missing_rather_than_raising`)
- [x] B6: unrecognised values for any param fall back to the default and return
      a 200, not a 500.
      (`test_unrecognised_values_fall_back_to_the_default` in
      `test_releases_view.py`; `test_garbage_params_return_200_not_500`
      (parametrised over `sort`/`dir`/`source`/`status`/`quality` garbage) in
      `tests/unit/test_releases_partial_route.py`)
- [x] B7: `GET /partial/movie/{id}/releases` requires auth, returns the table
      HTML, and honours all five params.
      (`test_returns_the_table_with_every_release_by_default`,
      `test_source_filter_is_honoured`, `test_status_and_quality_filters_are_honoured`,
      `test_sort_is_honoured`, `test_requires_auth_when_a_password_is_set` — the
      last asserts the route is wired through the same `require_auth` dependency
      as its siblings, not that a password-gated request is rejected end to end;
      see the note on B7/B8 test depth below)
- [x] B8 (redefined — see the corrected decision bullet above): the full-page
      movie route accepts the same params and forwards them into the initial
      partial load, so `/movie/{id}?source=nzb&sort=size` is bookmarkable and
      shareable. (No-JS support is explicitly NOT a goal — see the correction
      above.) Covered by `tests/e2e/release_controls.spec.ts`'s
      `'a bookmarked filtered URL renders filtered on first paint (B8)'`
      (skips explicitly if the local test library has no movie with releases
      — see the E2E coverage-gap note below). The query-forwarding logic
      itself (`request.url.query` → `detail_query` → `detail.html`'s
      `hx-get`) has no dedicated unit test as of this writing — it is a thin
      three-line pass-through in `couchpotato/ui/__init__.py`'s `movie_detail`
      route, and is exercised only by the E2E test above.
- [x] B9: Size and Seeders columns render; Seeders is blank (not `0`) for NZB
      releases.
      (`test_an_nzb_has_no_seeders_so_it_sorts_last_by_seeders` in
      `test_releases_view.py`; `test_size_and_seeders_are_rendered` in
      `test_releases_partial_route.py`)
- [x] B10: sortable headers expose `aria-sort` reflecting the active sort, and
      the result count is in an `aria-live` region.
      (`test_aria_sort_marks_only_the_active_column`,
      `test_no_column_is_marked_under_the_default_sort` in `test_releases_view.py`;
      `test_aria_sort_reflects_the_active_column`,
      `test_the_result_count_live_region_lives_in_the_static_shell`,
      `test_the_live_region_survives_a_swap_via_hx_swap_oob` in
      `test_releases_partial_route.py`). **Correction (found in pre-push
      review, then a second bug caught while verifying the fix live in a
      browser):** the `aria-live` region originally lived INSIDE
      `#movie-releases`, which `hx-swap="outerHTML"` destroys and recreates
      on every filter/sort change — screen readers announce mutations to a
      region already registered in the accessibility tree, not a brand-new
      node, so the count was never actually announced. The first fix moved
      a screen-reader-only copy to a sibling of `#movie-releases`, updated
      via `hx-swap-oob="innerHTML"` (deliberately not the bare
      `hx-swap-oob="true"` outerHTML shorthand, which would recreate the
      node's identity and reproduce the exact same bug) — but defined only
      inside `partials/movie_releases.html`. That still didn't work: htmx's
      OOB swap only updates a target id that ALREADY EXISTS in the
      document, and even the very FIRST render of the detail body arrives
      via an htmx swap (`detail.html`'s own `hx-trigger="load"`), so on that
      first render there was no pre-existing node for the OOB fragment to
      match — htmx fires `htmx:oobErrorNoTarget` and silently drops it
      (confirmed: `curl` saw the announcer in the raw response; the
      browser's rendered DOM did not). The announcer now lives in
      `detail.html`'s STATIC shell instead, so it exists before any swap
      ever happens. Verified live in a browser: a JS marker property set on
      the node survives a subsequent filter/sort swap (proving it is the
      SAME DOM node throughout, not recreated), and its text updates
      correctly (e.g. "6 of 6 releases" → "2 of 6 releases" after filtering
      to NZB).
- [x] B11: E2E — filter to NZB, confirm only NZB rows remain; sort by size,
      confirm row order and that `aria-sort` updated (CLAUDE.md rule 5).
      (`tests/e2e/release_controls.spec.ts`: `'filtering by source shows only
      that source'`, `'sorting by size marks that column and reorders the
      rows'`, `'the release table exposes sortable headers with aria-sort'` —
      each `test.skip()`s explicitly, with a stated reason, when the local test
      library has no movie, no releases, or only one source/fewer than two
      releases; see the coverage-gap note below)
- [x] B12: E2E/axe — no new accessibility violations on the detail page with
      filters applied.
      (`tests/e2e/accessibility.a11y.spec.ts`: `'Movie Detail page with a
      release filter applied should be accessible'`; skips explicitly if the
      local test library has no movie with releases)
- [x] B13: Download and Skip still work on a row after an htmx swap (the Alpine
      component rebinds).
      (`tests/e2e/release_controls.spec.ts`: `'Download and Skip still work
      after a swap (B13)'`; skips explicitly, with a stated reason, if the
      library has no movie with releases). **Correction:** the original
      version asserted `toBeEnabled()` on the action button, but `:disabled`
      is an Alpine binding, not an HTML attribute, so that assertion passed
      whether or not Alpine ever rebound the component after the swap — it
      was also wrapped in `if (count > 0)`, so a missing button silently
      no-opped instead of failing or skipping with a reason. It now asserts
      `Alpine.$data(document.querySelector('#movie-releases'))` is the
      rebound `releaseDownloader()` scope (has `downloading`/`ignoring` as
      objects) after the swap, which is `undefined`/wrong-shaped if the
      component failed to rebind; the button-count guard is an explicit
      `test.skip()` with a reason rather than a silent no-op. Still does NOT
      click Download/Skip themselves.
- [x] B14: a movie with no releases still renders the existing empty state,
      with controls either hidden or inert.
      (`test_a_movie_with_no_releases_renders_the_empty_state` in
      `test_releases_partial_route.py`). **Correction:** the original version
      asserted only `status_code == 200`, which also passes for an unrelated
      error page, and so named nothing about what the empty state actually
      looks like. It now also asserts there is no `<table>`, no "Releases"
      heading, and no profile-hidden message — i.e. the container is truly
      empty, not just any 200 response. A second regression test
      (`test_releases_hidden_by_the_profile_are_distinguished_from_no_releases`)
      pins the DIFFERENT case this one must not be confused with: releases
      exist but all are hidden by the movie's quality profile, which renders
      a heading + explanatory message rather than nothing (see the
      `raw_release_count` fix in `couchpotato/ui/__init__.py`'s
      `_releases_ctx`, added after `total_releases` became the
      profile-matching count and silently swallowed this distinction).

**E2E coverage-gap note (B11-B13):** CI and local e2e always start from a
fresh, empty `.e2e-data`/`.config` (see the same gap documented in
`tests/e2e/movie-detail.spec.ts` for the downloaded-review-workflow buttons),
so there is no fixture guaranteed to produce a movie with releases at all,
let alone releases from more than one source or with more than one row. Every
assertion above that depends on such data uses `test.skip()` with an explicit
reason rather than faking data into the app or passing vacuously when the
precondition isn't met — see `docs/plans/2026-07-30-release-list-sort-filter.md`'s
Task 8 notes for the same reasoning applied to this suite specifically.

**B7/B8 auth-test depth note:** `test_requires_auth_when_a_password_is_set`
(and the B7 criterion's "requires auth" clause generally) asserts that the
route is wired through the same `Depends(require_auth)` dependency as its
siblings — it does not spin up a password-protected instance and assert a 302
for an unauthenticated request end to end. No test in this suite does that for
ANY `/partial/*` route; it would be a pre-existing gap to close separately,
not one introduced by this plan.

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
  same params, and (post-review) branches on the `HX-Request` header so the
  filter form can target its own bookmarkable path instead of the standalone
  partial route (see the B8/hx-push-url correction above)
- new: `couchpotato/ui/templates/partials/movie_releases.html` — extracted from
  `movie_detail.html`
- `couchpotato/ui/templates/partials/movie_detail.html` — include the partial;
  Size/Seeders columns; controls
- `couchpotato/ui/templates/detail.html` — (post-review) hosts the persistent
  `#release-count-announcer` live region in the static shell (see the B10
  correction above)
- new: `tests/unit/` — helper tests (Part A), `filter_and_sort_releases` tests
  and route tests (Part B)
- `tests/e2e/` — filter/sort coverage per CLAUDE.md rule 5
- `docs/design-system/CONFORMANCE.md` — if the new controls introduce patterns
  the conformance gate checks
