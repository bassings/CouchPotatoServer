# FEAT-010: a film awaiting review stays visible in Wanted, and can be actioned there

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** draft
**Lenses run:** <plan-cycle to fill> · **Skipped:** <plan-cycle to fill>

## Problem

A film that finishes downloading disappears from the application entirely.

The `downloaded` review gate (`DOWNLOADED-REVIEW-WORKFLOW.md`) routes a
completed download to `status = 'downloaded'` and holds it for the owner to
confirm the right film landed. The backend half works: the searcher gates on it
(`couchpotato/core/media/movie/searcher.py:185`), `restatus` preserves it
(`couchpotato/core/media/_base/media/main.py:791-799`), the card and detail
templates render a "downloaded / review" badge, and the Mark Done and Mark
Failed actions exist and work (`partials/movie_detail.html:269-284`).

Nothing lists them. `wanted.html:119` asks the server for exactly one status:
`done` when the page is Library, `active` otherwise. No page, filter chip or
nav entry has ever requested `downloaded`. That two-way switch has been
unchanged since 2026-02-17 (`87a5a59f`), so this is not a regression: the
backend gained a third state and the list view was never taught about it.

The spec that introduced the state required it be *"filterable in the
wanted/manage lists"* (`DOWNLOADED-REVIEW-WORKFLOW.md:63`). That half was never
built.

**Measured on production, 2026-08-30**, via `media.list`:

| status | films |
|---|---|
| `active` (Wanted shows these) | 10 |
| `done` (Library shows these) | 1084 |
| `downloaded` (nothing shows these) | **5** |

The five are Spider-Man: Brand New Day, Minions & Monsters, Bride Hard, Tinsel
Town and Stop! That! Train!. All 18 production profiles have
`manual_confirmation = 1`, so every future completed download joins them.

Cost to the owner: a downloaded film is indistinguishable from a lost one. The
only way to reach it is to already know its id and type the URL by hand.

**Owner's statement of the intended design (2026-08-30):** "once something is
downloaded, it stays in wanted status for me to verify that the correct film has
downloaded, then I can mark it as done, or mark it as failed and select a
different file to download. Films should stay in the wanted section until they
are manually marked as done."

So the destination is Wanted, not a new section.

## Not in scope

- **Changing the review gate default or the `manual_confirmation` setting.**
  The gate is behaving as designed; only its visibility is broken. Note the
  planning gap recorded below.
- **Exposing `manual_confirmation` in the profile editor UI.** Still deferred
  from Phase 2 (`DOWNLOADED-REVIEW-WORKFLOW.md:170-177`); settable via the
  `profile.save` API. Would change only who can turn the gate on, not whether a
  gated film is visible.
- **Replacing a library file with one the owner placed by hand.** Separate
  problem, separate blast radius, specced as FEAT-011.
- **Bulk review actions and a nav count badge.** Considered and declined by the
  owner as disproportionate for a five-film queue. Revisit if a backlog builds.
- **The renamer retry loop** observed on production (31 identical cycles in 65
  minutes for one film). Unrelated to visibility; belongs with FEAT-011.

---

## Acceptance criteria

Synthesised from six planning lenses (security, qa, simplicity, product, design,
accessibility). Each line is a thing that can be shown true or false, and is what
the review cycle verifies. Where two lenses wrote the same criterion, the more
testable wording was kept and the merged IDs are named on the line.

**Decisions taken at synthesis, because more than one lens flagged them as
undecided** (these are the contract, not suggestions):

1. **Chip semantics.** A film awaiting review is claimed by the Review chip and
   by no other chip. `available` becomes "has a release AND is not awaiting
   review"; `wanted` stays "has no release" and also excludes a film awaiting
   review. The spec's Risks section named this collision; product and design
   both supplied the criterion, so simplicity's "leave `movie-filter.js`
   untouched" veto does not stand.
2. **Card actions.** **Mark Done and Mark Failed both go on the card**, and Mark
   Failed carries the same `confirm()` the detail page already uses
   (`movie_detail.html:281`), with the same wording. *(Owner decision
   2026-08-30, overruling `lens-simplicity`'s veto: rejecting a film is half
   the stated workflow, so making the reject half the only action that needs a
   detail page adds friction to exactly the case the review gate exists for.
   The veto's concern is real and is answered by the confirmation rather than
   by removing the control; see "Vetoed at planning".)*
3. **Bulk Delete.** A film awaiting review is never deleted by the Wanted page's
   bulk Delete, and the confirmation says how many of the selection are being
   skipped for that reason. This matches what the server already does
   (`main.py:567`); today the UI would claim otherwise.
4. **Success behaviour.** A card action re-fetches the grid rather than calling
   `location.reload()`, because a reload destroys the live-region announcers in
   `base.html` before the outcome can be spoken.

### Security

- **AC-SEC-1:** No film title reaches an Alpine or JS expression by string interpolation. Rendering the real `partials/movie_cards.html` for a `downloaded` movie titled `Ocean's Eleven'+(window.pwn=1)+'`, every attribute on the card whose name begins with `@`, `:` or `x-` yields, after HTML-entity decoding, a value that does not contain `+(window.pwn=1)+` outside a quoted JS literal. Titles reaching a handler come from `| tojson` (filter registered at `couchpotato/ui/__init__.py:33`) or from a `data-` attribute read at runtime. The pre-existing `:aria-label` at `movie_cards.html:108` fails this today and is fixed in the same change; the test is proven load-bearing by reverting that line and watching it go red.
- **AC-SEC-2:** A review-gated film survives the Wanted page's bulk Delete. With a `downloaded` film in the grid, Select All then Delete leaves that film present with `status == 'downloaded'`, its releases undeleted and its `profile_id` non-null. Proven end-to-end through the newly reachable path, not only at the `MediaPlugin.delete` unit level where `main.py:567` already has coverage.
- **AC-SEC-3:** *(Reinstated by owner decision 2026-08-30, when card-level Mark Failed was restored. Written fresh rather than restored verbatim: the original text lived only in the lens report, and claiming it is the original would be a citation that cannot be checked.)* The card's Mark Failed cannot act on a film that is not awaiting review, and cannot act at all without a session. `movie.searcher.mark_failed` called for a movie whose stored status is `active` or `done` performs no write and returns failure, leaving the stored status and the owning release untouched; called without a session cookie it is refused before reaching the handler. Proven in both directions, including that a genuinely `downloaded` movie still succeeds, so the guard cannot pass by refusing everything.
- **AC-SEC-4:** The changed grid request is still refused without a session. With authentication enabled and no session cookie, `GET /partial/movies?status=active,downloaded` returns a refusal (302 to login, or 204 with `HX-Redirect` when the request carries `HX-Request`, per `couchpotato/__init__.py:951-954`) and its body contains no `poster-card` markup. No route or query parameter added or altered by this change is reachable without `Depends(require_auth)`.
- **AC-SEC-5:** The review card leaks no secret and no filesystem path. Rendering `partials/movie_cards.html` for a `downloaded` movie whose release carries `files: {'movie': ['/Volumes/Media/Movies/X (2001)/x.mkv']}` with `api_key='SECRETKEY123'`, the output contains the api key zero times and the absolute path zero times; anything shown about the landed file is the basename only, matching `partials/movie_releases.html:201`. The log records captured while serving that request contain no absolute path outside the configured library root and no api key. Both halves hold on the current template, so this is a regression pin.
- **AC-SEC-6:** The Review chip value round-trips through the URL as data, never as markup. Loading `/?filter=<img src=x onerror="window.pwn=1">` renders the value as visible text in the filtered-to-empty panel (`wanted.html:176`), leaves `window.pwn` undefined, and produces no element whose attribute value was built from the URL parameter. The chip value is only ever compared or written with `x-text`, never with `x-html` or into an attribute expression.
- **AC-SEC-7:** Mark Done refuses a stale card. `media.done` gains a status precondition (mirroring the atomic `_reset_if_downloaded` guard at `searcher.py:817-824`) so a card whose displayed status no longer matches the stored one performs no write: calling the route for a movie whose status is `active` returns failure and leaves the stored status `active`. Proven in both directions, including that a genuinely `downloaded` movie still succeeds. *(Orchestrator-added from lens-security's third finding, which asked for this to be written as an AC rather than inferred; `markDone` at `main.py:646-647` currently sets `status = 'done'` unconditionally.)*

### QA

- **AC-QA-1:** `GET /wanted` renders the movie grid with exactly one `hx-get` whose query string is `status=active,downloaded`, and `GET /library` still renders exactly `status=done`. Both directions are asserted so neither page can inherit the other's status set. Retarget `tests/unit/test_fastapi_web.py::test_wanted_grid_always_loads_active_movies`, which today asserts the literal `hx-get="/partial/movies?status=active"` and passes; it must assert the new literal, never be loosened to a substring or regex that both strings satisfy. *(Merged: AC-SIMP-8.)*
- **AC-QA-2:** A single request to `/partial/movies?status=active,downloaded` produces exactly ONE call to the `media.list` handler, with `status == 'active,downloaded'` and no `has_releases` key in the kwargs. Asserted with a capturing handler in the style of `test_partial_movies_without_with_releases_does_not_filter_at_all`, with call count `== 1`, not `>= 1`. This kills a two-fetch implementation and stops the `has_releases` default being reintroduced.
- **AC-QA-3:** When the `media.list` handler raises, `/partial/movies?status=active,downloaded` still returns HTTP 200 rendering the "No movies found" empty state, and the response body contains no traceback text and no exception class name.
- **AC-QA-4:** Rendering `partials/movie_cards.html` with a movie whose status is `downloaded` produces a card carrying `data-status="downloaded"`, the "downloaded / review" badge, and a card-level Mark Done control addressable by a stable `data-testid` rather than by visible text. Uses the real-Jinja render pattern of `tests/unit/test_review_actions_ui_template.py`, not a copy of the template.
- **AC-QA-5:** The same render with each of `active`, `done`, `snatched` and an unrecognised value (`suspended`) produces NO card-level review control: the gate is proven in both directions, and a mutation that renders the control unconditionally fails at least one of the four cases.
- **AC-QA-8:** `make mutation-changed` over `couchpotato/static/scripts/ui/movie-filter.js` reports zero surviving mutants in the branches added or altered for the Review chip and the chip exclusions, and the measured score is quoted in the PR body. The file is already in Stryker's mutate glob, so this needs no new tooling.
- **AC-QA-9:** `scripts/seed_e2e_data.py` seeds TWO dedicated review-gate movies: one reserved for read-only assertions and one reserved for the state-changing Mark Done spec, mirroring the existing `MOVIE_ID` / `DESTRUCTIVE_MOVIE_ID` split. Each is media status `downloaded` with a landed release and a profile carrying `manual_confirmation`, and neither id is referenced by any other seeded constant. Two are required, not one, so AC-A11Y-5's uniqueness assertion is non-vacuous.
- **AC-QA-10:** `seed_e2e_data.verify()` fails, naming the movie id, when either new review movie is left in a status other than `downloaded` (proven by mutating the seeded doc and asserting `verify()` returns a problem mentioning that id, the pattern at `tests/unit/test_seed_e2e_data_guard.py:417`), and `test_seed_e2e_data_guard.py` additionally pins that neither new title is a substring of any other seeded title, because `tests/e2e/filters.spec.ts:68` asserts `toHaveCount(1)` after filtering on a full title and breaks silently otherwise.
- **AC-QA-12:** *(Reinstated by owner decision 2026-08-30, written fresh; see AC-SEC-3's note.)* The card's Mark Failed asks before it discards, and cancelling does nothing at all. Activating it opens a confirmation whose text is the same one the detail page uses (`movie_detail.html:281`), and dismissing that confirmation issues ZERO requests to `movie.searcher.mark_failed`, leaves the card present with `data-status="downloaded"`, and leaves the control in its idle state. Asserted with a request counter at an intercepted route, `== 0`, not merely "the card is still there", because the card would still be there during an in-flight request too.
- **AC-QA-13:** *(Reinstated by owner decision 2026-08-30, written fresh; see AC-SEC-3's note.)* Confirming Mark Failed from a card has the same effect as confirming it from the detail page, and no other. Exactly one `movie.searcher.mark_failed` request is issued for the card's own media id, no `media.done` request is issued, and no other card in the grid changes its `data-status`. The two-card seeding required by AC-QA-9 makes the "no other card" half non-vacuous; with a single seeded film it could not fail.
- **AC-QA-15:** A rejected Mark Done is visibly rejected and recoverable, in both failure shapes: (a) the route returns `{'success': false}` and (b) the route is aborted (transport failure). In each case the card stays visible and unchanged, the control returns from its pending label to its idle label and re-enables, and an error message is surfaced. Neither case leaves the control stuck on "Marking…" nor claims success. AC-SEC-7 makes shape (a) reachable without a fault injector. *(Merged: AC-DESIGN-10, which also requires the in-flight state to be visible and the control disabled while the request is outstanding.)*
- **AC-QA-16:** Double activation is bounded: two rapid clicks, and two rapid Enter presses, on a card's Mark Done produce exactly one `media.done` request counted at an intercepted route.
- **AC-QA-18:** Zero-and-unknown cases do not produce a blank grid: with a stubbed grid containing no downloaded films, clicking Review shows the filter-empty-state panel and writes into the `filter-empty-announcer` live region; and loading `/wanted?filter=zzz-not-a-status` does the same rather than rendering an unexplained empty list. Reuses the `stubMovieGrid` helper at `tests/e2e/filters.spec.ts:209`.
- **AC-QA-19:** The deep link `/wanted?filter=downloaded` loads with the Review chip in its selected state (the same accent class the other chips use) and only downloaded cards visible, and the URL is preserved rather than rewritten by `updateUrl()` on first paint.
- **AC-QA-20:** Select All followed by bulk Delete on a Wanted grid containing a review-gated film never deletes that film, and says so before acting: the confirmation states how many of the selection have a completed download awaiting review and are being skipped, the request is not issued for those ids, and the review-gated card is still present with `data-status="downloaded"` afterwards. When the selection contains none, the existing wording is unchanged. *(Merged: AC-DESIGN-12. This is the decided resolution of the mismatch between `wanted.html:393`'s "This cannot be undone" and `main.py:567`'s silent no-op.)*
- **AC-QA-21:** Loading `/wanted` issues exactly one `/partial/movies` request regardless of how many statuses it asks for, and the review control adds no per-card HTTP request: the count of requests to `CP.apiBase` during grid load is unchanged from before the change. This is the only performance statement currently enforceable: no lab budget covers this page (`lighthouserc.js` collects `/`, `/available/`, `/add/` and `/settings/` and is referenced by neither `scripts/verify.sh` nor any CI workflow) and no wall-clock baseline for `/partial/movies` against a production-sized library has been measured. **A latency threshold must not be added until that baseline is taken.**

### Simplicity

*Verified by the orchestrator directly against the diff at review; no agent needed.*

- **AC-SIMP-1:** The only Python file changed under `couchpotato/` is the one carrying AC-SEC-7's status precondition on `media.done`. No new Python module, no new route, no new API endpoint and no new setting is added; the status widening itself is a template edit at `wanted.html:119`, because `/partial/movies` already forwards `status` verbatim to `media.list` (`couchpotato/ui/__init__.py:304`).
- **AC-SIMP-4:** *(Rewritten 2026-08-30 after the owner overruled the Mark Failed veto. The original forbade `mark_failed` and `confirm(` in `movie_cards.html` outright; that is now the opposite of the requirement, so the criterion keeps the half that still holds.)* The only destructive route added to `couchpotato/ui/templates/partials/movie_cards.html` is `movie.searcher.mark_failed`, and it is guarded: the diff of that file contains no reference to `media.delete`, and every occurrence of `mark_failed` in it is lexically inside a `confirm(` branch, so no code path reaches the request without the dialogue. Proven load-bearing by deleting the `confirm(` wrapper and watching AC-QA-12 go red.
- **AC-SIMP-5:** The Review chip is a single `<button>` inside the existing chip group at `wanted.html:57-67` whose handler is exactly `setFilter('downloaded')`. It introduces no new function on the `movieList()` component, no new URL query parameter (the existing `?filter=` round-trip at `wanted.html:213` and `:327` already carries it) and no label or status lookup table.
- **AC-SIMP-6:** No new runtime or test dependency: `package.json`, `package-lock.json`, `requirements.txt` and any `pyproject`/constraints file are unchanged.
- **AC-SIMP-7:** No new configuration setting, profile field or feature flag gates this behaviour. The Wanted page requests the widened status unconditionally for every user, and the rendered `hx-get` contains no Jinja branch other than the pre-existing library/wanted one.
- **AC-SIMP-9:** No nav count badge, no bulk review action and no new nav or sidebar entry is added, both having been declined by the owner (Vetoes and trade-offs, above). The diff adds no element to `base.html`'s navigation (still exactly the six entries at `base.html:326-333`), no new page or route serving a review queue, and no bulk-action button inside `wanted.html`'s `selectedCount` block. A film awaiting review appears in Wanted and nowhere else; the Library page continues to list only `done`. *(Merged: AC-PROD-9.)*
- **AC-SIMP-10:** The change creates no new source file: `git diff --diff-filter=A --name-only master...` returns no new template, Jinja macro, JS module or Python module. New test cases live in the existing files named in the Affected files table plus `scripts/seed_e2e_data.py`, `tests/unit/test_seed_e2e_data_guard.py`, `tests/unit/test_fastapi_web.py`, `tests/e2e/accessibility.a11y.spec.ts` and a `*.mobile.spec.ts` target; a new `*.mobile.spec.ts` is permitted only if no existing one can host the assertions. *(Replaces lens-simplicity's original five-file budget, which the accessibility floor's fixture and project requirements make unattainable; see the note below.)*

### Product

- **AC-PROD-1:** A film with media status `downloaded` is listed on the Wanted page in its default view (no chip selected), reached by loading `/wanted/` alone: no id, no hand-typed URL and no chip click is required to see that the film still exists.
- **AC-PROD-2:** In the Wanted grid a film awaiting review is distinguishable from a film still being sought without opening it: its card shows the "downloaded / review" badge, and a film with status `active` in the same grid does not.
- **AC-PROD-3:** The Wanted page offers a chip that shows the review queue and only the review queue: with it active, the set of `data-status` values on visible cards is exactly `{"downloaded"}` AND the visible count equals the number of seeded downloaded films, so the chip cannot pass by hiding everything. Deactivating it (All) restores all cards. *(Merged: AC-QA-11, AC-DESIGN-2.)*
- **AC-PROD-4:** Each film in the Wanted grid is claimed by exactly one of the four chips: a film awaiting review is shown under Review and is NOT shown under Available or Wanted, and the visible counts of Wanted, Available and Review sum to the count shown with no chip active.
- **AC-PROD-5:** A film awaiting review can be confirmed from its card in the Wanted grid without opening the detail page: the card offers a Mark Done control, and using it sets the film's media status to `done`, verified by re-reading the film via `media.get`. *(This criterion is what lifts lens-simplicity's veto on the non-destructive half of the card actions.)*
- **AC-PROD-6:** After Mark Done is used on a card, the film stops being listed in Wanted and starts being listed in Library, with no manual page reload by the user: the card is gone from `#movie-grid` without `page.reload()`, and the film is present on `/library`. Exactly one `media.done` request is made, carrying that card's id. *(Merged: AC-QA-14.)*
- **AC-PROD-7:** After Mark Failed is used from the detail page and confirmed, the film remains listed on the Wanted page as an active film being re-searched, with `data-status="active"`, rather than disappearing from the application, which is the failure this change exists to remove. Asserted on the Wanted grid, not on the detail page.
- **AC-PROD-8:** The user never sees an internal status token they did not choose. One user-facing term names this state on the Review chip, on the card badge (`movie_cards.html:79`), in the card link's accessible name (`movie_cards.html:49`, which currently interpolates the bare status) and in the filtered-to-empty message (`wanted.html:175-177`, which prints `filterStatus` verbatim). Asserted by activating the review chip with no matching films seeded and checking the empty-state prose contains the chip's own label. *(Merged: AC-DESIGN-16.)*

### Design

- **AC-DESIGN-1:** The Wanted page renders exactly four filter chips, in the order All, Wanted, Available, Review. The Review chip reuses the existing chip markup verbatim (`px-2.5 py-1 rounded-md transition-colors` inside the `text-[10px]` group, with the same selected/unselected class binding), and introduces no new colour token, no new class pattern and no new component. It renders unconditionally, including when zero films are awaiting review, so its position never moves. `python scripts/check_conformance.py` stays green.
- **AC-DESIGN-3:** In `couchpotato/static/scripts/ui/movie-filter.js`, `matchesFilter` returns false for a card with `status === 'downloaded'` under both `filterStatus: 'available'` and `filterStatus: 'wanted'`, true under the Review chip's value, true for a non-downloaded card with releases under `available`, true for a non-downloaded card without releases under `wanted`, and false for a downloaded card whose title does not contain the search query (search AND chip must both match). All six cases are asserted in `tests/unit/ui/movie-filter.spec.ts`, so the guard fails in both directions. *(Merged: AC-QA-6, AC-QA-7.)*
- **AC-DESIGN-4:** When the Review chip matches nothing while the list is non-empty, the filtered-to-empty panel (`[data-testid="filter-empty-state"]`, `wanted.html:163-188`) is shown, its "Clear filters" button is present, and clicking it returns the grid to All with all cards visible.
- **AC-DESIGN-7:** The card's action label is character-identical to the detail page's, "Mark Done" (`partials/movie_detail.html:277`), so the same action is named the same way on both surfaces and nothing new is introduced for a user to learn. Pinned by `getByRole('button', { name: 'Mark Done', exact: true })` resolving on a review card, plus a grep pinning the string in both templates.
- **AC-DESIGN-8:** *(Reinstated by owner decision 2026-08-30, written fresh; see AC-SEC-3's note.)* The two card controls cannot be confused for one another, and the destructive one is not the easy target. Mark Failed uses the danger token already used for the same action on the detail page (`bg-cp-danger/10 text-cp-danger`, `movie_detail.html:283`) and Mark Done the success token, so they differ by more than position; they are separated by at least the standard control gap so neither sits under the pointer after the other is dismissed; and Mark Done is first in DOM order, so the destructive control is never the first thing reached by Tab or by a screen reader moving through the card. `python scripts/check_conformance.py` stays green, and no new colour token is introduced.
- **AC-DESIGN-11:** After a successful card action the grid reloads and the user's context survives it: the previously active chip stays active, the text in the title filter is unchanged, and `#movie-count` updates to the new totals. If the action emptied the current filter while the list still holds other films, the filtered-to-empty panel appears rather than a blank area.
- **AC-DESIGN-13:** The bulk Delete button at `wanted.html:33` uses `cp-danger`, a token defined at `base.html:73`, instead of `cp-error`, which no token defines, so the page's most destructive control renders with the danger tint in both themes rather than as untinted text. `grep -rn cp-error couchpotato/` returns nothing. This is one line, and it is kept in scope because it is load-bearing for AC-QA-20: better copy on a control that does not look destructive is half a fix.
- **AC-DESIGN-14:** The card action respects the documented on-dark rule (`base.html:122-141`): because it sits on the card surface rather than over poster artwork, its status-token colour class does NOT carry `on-dark`, so the light theme's darker equivalent applies. The existing over-poster badge at `movie_cards.html:79` keeps its `on-dark`. Both themes are exercised.
- **AC-DESIGN-15:** At 393px (the `mobile-chrome` project, `playwright.config.ts:124-127`), a Wanted page carrying at least one review card has the four-chip group wrapping rather than scrolling off, and each card's action row fully inside its card's bounding box with no clipped label. Asserted from a spec matching `*.mobile.spec.ts`, because the mobile project runs nothing else; a desktop-project assertion would never execute.

### Accessibility

*WCAG 2.2 AA is a floor, not a trade-off (`AGENT-HARNESS.md`, precedence rule 3). None of these may be dropped for scope.*

- **AC-A11Y-1:** The Review chip is reachable and operable by keyboard alone (Tab to it, activate with both Enter and Space), and while focused shows a focus indicator meeting 3:1 non-text contrast against its own background in BOTH themes. Proven by a Playwright test that focuses via keyboard only, asserts `document.activeElement` is the chip, activates with each key, and runs in the light-pinned accessibility project plus a dark-theme run that first asserts `document.documentElement.classList.contains('light')` is false.
- **AC-A11Y-2:** All four Wanted filter chips expose their selected state programmatically, not by colour alone: after each click exactly one chip resolves under `page.getByRole('button', { pressed: true })` and the other three under `{ pressed: false }`, and that state matches the component's `filterStatus`. Selection is currently signalled only by a class swap (`wanted.html:59-65`), which assistive technology cannot report.
- **AC-A11Y-3:** The Review chip's accessible name contains its visible label (SC 2.5.3), and the filtered-to-empty panel and its sr-only announcement name that label rather than the internal status token: with the Review chip active and no film awaiting review, the text of `[data-testid="filter-empty-announcer"]` and `[data-testid="filter-empty-state"]` contain the chip's label and do not contain the raw word `downloaded` rendered by `wanted.html:176`'s `x-text="filterStatus"`.
- **AC-A11Y-4:** Activating the Review chip announces the result exactly once, not once per card and not per keystroke: a MutationObserver on `[data-testid="filter-empty-announcer"]` records exactly one text change across a single chip activation, and zero text changes when the chip is activated while films awaiting review are present.
- **AC-A11Y-5:** The card review control has an accessible name that includes the film's title, and those names are unique across the grid: on a Wanted grid containing at least two films awaiting review, `page.getByRole('button', { name: /mark .* as done/i })` resolves to exactly one element per film and no two cards produce the same accessible name. AC-QA-9's two seeded films make this non-vacuous.
- **AC-A11Y-6:** The card review control is keyboard reachable and visible while focused: tabbing forward from a review card's poster link reaches it without any pointer interaction, `getComputedStyle(el).opacity` is `'1'` and its bounding box lies within the viewport while it holds focus. It is not a descendant of the card's `<a>` (`document.querySelectorAll('#movie-grid a button').length` is 0), so no interactive control is nested inside a link, and activating it does not navigate: after the click the page URL is still the Wanted page. *(Merged: AC-QA-17, AC-DESIGN-5.)*
- **AC-A11Y-7:** No review control is operable while invisible. Its markup carries none of `opacity-0`, `group-hover:opacity-100` or `focus:opacity-100` (the pattern used by the hover-only refresh button at `movie_cards.html:105`), and under the `mobile-chrome` project (Pixel 5, 393px) with no pointer hover applied it is reported visible on first paint. Asserted in both the default and the mobile project, because hover does not exist on touch. *(Merged: AC-DESIGN-6.)*
- **AC-A11Y-8:** Target size (SC 2.5.8): the Review chip and the card review control each have a hit area of at least 24x24 CSS px, measured by `getBoundingClientRect()` at both 1280px and 393px viewport widths, without relying on the spacing exception: each measures >= 24 in both dimensions on its own. Axe's `target-size` rule reports zero violations on a Wanted page carrying at least one review card at both widths.
- **AC-A11Y-9:** Focus has a defined destination after the card review action. Once the acted-on card has been removed or replaced, `document.activeElement` is neither `document.body` nor `documentElement`, and is a named, still-present element (the next card's link, or the movie-count region). Asserted both where the acted-on card is the last remaining card in the grid and where others remain. The identical bug is already documented and fixed for the Clear filters button at `wanted.html:282-287`.
- **AC-A11Y-10:** The outcome of the card review action is announced through a live region that survives the update, and says what happened and where the film went rather than a bare "Done": within 2s of completion one of `base.html`'s persistent announcers (`[data-testid="toast-announcer-polite"]` or `[data-testid="toast-announcer-assertive"]`) contains outcome text naming the Library as the destination, that region is still attached to the document 1s later, and the action performs no full page reload that would destroy it before it can be spoken. *(Merged: AC-DESIGN-9.)*
- **AC-A11Y-11:** A card review action does not cause the whole movie list to be re-announced. Either `#movie-grid` carries no `aria-live` attribute after this change (with the loading state's own `role="status"` region retained for the initial load), or the action's DOM update is confined to the acted-on card and leaves the other cards' nodes identical. One of the two is asserted mechanically, and the implementation states which, because `wanted.html:122` currently makes the entire grid a polite live region.
- **AC-A11Y-12:** Colour contrast in both themes for every element this change makes newly reachable: the "downloaded / review" badge (`movie_cards.html:78-79`, a branch no list has ever rendered), the Review chip in its selected and unselected states, and the card review control meet 4.5:1 for text and 3:1 for icon strokes and control boundaries. Each carries a background opaque enough that the measured ratio does not depend on the poster artwork behind it, verified against both a white and a black poster fixture in light and dark themes. Axe cannot settle this, because contrast over an image is reported as incomplete rather than as a violation, so it is measured from computed colours.
- **AC-A11Y-13:** Axe reports zero violations under tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` on a Wanted page containing at least one film awaiting review, in the light theme and in the dark theme. The test FAILS, rather than skipping or passing, when no review card is present in the grid, so a missing fixture cannot produce a green run.
- **AC-A11Y-14:** Reflow (SC 1.4.10): with review cards present, `document.documentElement.scrollWidth <= clientWidth` on the Wanted page at 393px and at a 640px CSS width (the 200% zoom equivalent of 1280px), and at both sizes the card review control remains reachable: its bounding box is inside the viewport once focused.

### Vetoed at planning

`lens-simplicity` may reject any requirement not traceable to the spec's stated
goal, and that rejection stands unless the owning lens supplies the criterion. It
cannot override security, irrecoverable data loss or the accessibility floor.

| Dropped | Raised by | Reason |
|---|---|---|
| **Mark Failed on a Wanted card**, and with it AC-SEC-3, AC-QA-12, AC-QA-13, AC-DESIGN-8 | vetoed by `lens-simplicity`; **OVERRULED BY THE OWNER 2026-08-30, criteria reinstated** | The veto's reasoning stands on its own terms and is kept here rather than deleted: Mark Failed already works from the detail page, and putting the one action that discards a completed download onto a hover target on a dense grid makes the spec's own highest-harm risk cheaper to trigger. The owner overruled it because rejecting a film is half the stated workflow ("I can mark it as done, or mark it as failed and select a different file"), so leaving reject as the only action needing a detail page adds friction to exactly the case the review gate exists for. **The concern is answered rather than dismissed:** the detail page's existing `confirm()` moves onto the card with the control (AC-QA-12 proves cancelling issues zero requests), and AC-DESIGN-8 keeps the destructive control off the first tab stop and in the danger token. AC-SIMP-4 was rewritten rather than deleted, since its `media.delete` half still holds. The four criteria are written FRESH, not restored verbatim: the originals existed only in the lens reports, and presenting new text as the original would be a citation nobody can check. |
| **AC-SIMP-2 and AC-SIMP-3** (`movie-filter.js` byte-identical; `available`/`wanted` predicates unchanged) | `lens-simplicity`; **overruled** | Both product (AC-PROD-4) and design (AC-DESIGN-3) supplied the criterion, so the veto does not stand. The requirement is also traceable to the spec's own Risks section: "the same film appears under two chips meaning different things." Simplicity's argument was cost (one branch, test churn), not correctness. |
| **AC-SIMP-2's premise that the chip needs no logic at all** | `lens-simplicity`, quoting the spec | Correct for the Review chip itself (`matchesFilter` falls through to an exact status comparison at `movie-filter.js:25`) and wrong for the other two chips, which read only `hasReleases` and never `status`. The spec's Affected-files wording "Review takes precedence" misnames the mechanism: only one `filterStatus` is ever active, so there is no precedence, only an exclusion. |
| **AC-SIMP-10's five-file budget** | `lens-simplicity`; **relaxed** | Unattainable alongside the accessibility floor, which simplicity cannot override: AC-A11Y-13 and AC-A11Y-8 require a seeded `downloaded` film (`scripts/seed_e2e_data.py` plus its guard test) and assertions in projects scoped by filename (`*.a11y.spec.ts`, `*.mobile.spec.ts`). Replaced by the narrower AC-SIMP-10 above, which keeps the useful half: no new source file. |
| **A distinct error state for a failed grid fetch** (raised by `lens-design`; `/partial/movies` swallows the exception and renders "No movies found", indistinguishable from an empty library) | dropped as scope | Pre-existing behaviour of a route this change does not otherwise alter, and `lens-design` itself flagged it as contestable scope for adjudication. AC-QA-3 keeps the half that is this change's business (200, empty state, no traceback). **This is a real defect and it deserves its own spec**: it reproduces this feature's own "my films have vanished" failure on a different code path, and `partial_movie_detail` has the same shape. |
| **A latency budget for the Wanted page** | not adopted | No baseline exists: Lighthouse gates nothing here (`lighthouserc.js` is referenced by neither `scripts/verify.sh` nor any CI workflow) and no wall-clock number for `/partial/movies` against a production-sized library has been measured. AC-QA-21 pins the request count instead. A threshold invented before the measurement would be theatre. |

**Proportionality note.** `lens-simplicity` argued the full nine-lens harness is
disproportionate to what remains. With Mark Failed vetoed the production change
is roughly: one query string, one chip button, one exclusion in `matchesFilter`,
one card button, one `media.done` precondition and one token fix. The criteria
count is nonetheless high because the accessibility floor was genuinely
unexercised on this surface (`movie_cards.html:78-79`'s review badge is a branch
no list has ever rendered) and because no fixture in the repo could produce a
`downloaded` film. Both are one-off costs. Design, accessibility, product, qa and
security all earned their run here; `lens-architecture`, `lens-data` and
`lens-operability` were not triggered and were skipped: no schema, no new
boundary, no production behaviour beyond one query string and one precondition.

---

## Vetoes and trade-offs

| Item | Raised by | Decision | Rationale |
|---|---|---|---|
| Separate "Review" nav section instead of Wanted | orchestrator | vetoed by owner | The owner's design is that films stay in Wanted until marked done. A separate section splits the queue the owner wants in one place. |
| Bulk review actions + nav count badge | orchestrator | declined by owner | Disproportionate for five films. Not a rejection on merit; revisit on evidence of a backlog. |

## Risks

Ranked by recoverability.

- **Irreplaceable: none.** This change adds no destructive path. Mark Failed is
  already reachable today via the detail page and its behaviour is unchanged;
  putting it on the card changes only how many clicks reach it, which is
  precisely why the confirm dialogue on it is load-bearing and must be
  preserved.
- **Expensive: a mis-click on Mark Failed discards a completed download** and
  triggers a re-search. Today that action costs a deliberate navigation to a
  detail page; on a card it costs one click on a dense grid. The existing
  `confirm()` guard (`partials/movie_detail.html:281`) must survive the move,
  and this is the single most likely place for the change to do harm.
- **Cheap: the Wanted count changes** from 10 to 15 on production, and the
  "Available" chip currently keys on "has releases", which a `downloaded` film
  satisfies. Without care the same film appears under two chips meaning
  different things.

## Affected files

**Corrected 2026-08-30 after planning.** Four lenses independently found this
table wrong, and an implementer working from the original would have created a
duplicate test file, been blocked by a red test with a tempting cheap repair,
and had no way to produce the state the feature is about. The errors are
recorded rather than quietly overwritten, because a wrong Affected-files table
reads as precision and is worse than an absent one.

| Path | Change |
|---|---|
| `couchpotato/ui/templates/wanted.html` | Wanted requests `status=active,downloaded`; add the Review chip |
| `couchpotato/static/scripts/ui/movie-filter.js` | Review claims a review-gated film; `available` and `wanted` both exclude it |
| `couchpotato/ui/templates/partials/movie_cards.html` | Mark Done on a card awaiting review. NOT Mark Failed, see "Vetoed at planning" |
| `tests/unit/ui/movie-filter.spec.ts` | Chip precedence, all three chips, both directions |
| `scripts/seed_e2e_data.py` | **Must gain the ability to seed a `downloaded` film.** Today it deliberately refuses to (`:227-231`) |
| `tests/unit/test_fastapi_web.py` | `test_wanted_grid_always_loads_active_movies` (`:568`) WILL go red. Its name and its assertion both encode the old contract |
| `tests/e2e/filters.spec.ts` | A `downloaded` film appears in Wanted and under Review |
| `tests/e2e/accessibility.a11y.spec.ts` + a `*.mobile.spec.ts` | The a11y and target-size criteria run in filename-scoped Playwright projects, so they cannot live in `filters.spec.ts` |

**Three corrections, and why each mattered:**

- `tests/unit/movie-filter.test.ts` does not exist. The real path is
  `tests/unit/ui/movie-filter.spec.ts`. Left uncorrected, an implementer
  creates a second parallel test file and the two sets of assertions drift.
- **Nothing in this repository can currently produce a `downloaded` film**, and
  `scripts/seed_e2e_data.py:227-231` records the avoidance as deliberate. This
  is the most consequential omission: without seeding, every criterion that
  matters is unprovable, and all three cheap responses (skip the test, wrap it
  in `if (count > 0)`, stub the grid) ship green while proving nothing. That is
  precisely the failure this spec exists to end, reproduced inside its own
  tests.
- `test_fastapi_web.py:568` asserts the literal
  `hx-get="/partial/movies?status=active"` and passes today. It must go red and
  be updated deliberately. **The cheap repair is to weaken it to a substring
  both the old and new strings satisfy, which destroys the guard** rather than
  updating it. The test's name encodes the old contract too and should change
  with it.

**Verified available, no backend change needed:** `media.list` already documents
`status` as "array or csv" (`couchpotato/core/media/_base/media/main.py:50`) and
`status=active,downloaded` returns 15 against the live production server, versus
10 and 5 for the parts. The card already carries `data-status`
(`movie_cards.html:22`) and `matchesFilter` already falls through to an exact
status comparison (`movie-filter.js:25`), so the chip needs no new logic.

---

## Review cycle

*(To be filled by the review cycle.)*

### Spec gaps found at review

**Recorded at planning, from the incident that prompted this spec.** The
`downloaded` state shipped across four phases with a badge, two actions, a
notification and searcher gating, and no phase owned the one thing that made any
of it reachable. The spec named the requirement in a design bullet
(*"filterable in the wanted/manage lists"*) rather than as a phase with its own
PR, so every phase could close as DONE while the feature was unusable. A
requirement that is not somebody's phase is nobody's.
