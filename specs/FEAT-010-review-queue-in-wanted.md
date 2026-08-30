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

*(To be written by the planning lenses. Each must be testable: a thing that can
be shown true or false.)*

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

| Path | Change |
|---|---|
| `couchpotato/ui/templates/wanted.html` | Wanted requests `status=active,downloaded`; add the Review chip |
| `couchpotato/static/scripts/ui/movie-filter.js` | Ensure Review takes precedence over the has-releases chips |
| `couchpotato/ui/templates/partials/movie_cards.html` | Mark Done / Mark Failed on a card awaiting review |
| `tests/unit/movie-filter.test.ts` | Filter precedence, both directions |
| `tests/e2e/filters.spec.ts` | A `downloaded` film appears in Wanted and under Review |

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
