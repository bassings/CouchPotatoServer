# FEAT-011: replace a library file with one the owner placed by hand

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** draft
**Lenses run:** <plan-cycle to fill> · **Skipped:** <plan-cycle to fill>

## Problem

The owner sometimes needs to replace a library file for a reason the system
cannot express: **the copy in the library is not playable**, and a different
copy of the same film at the same quality rung is.

The prompting case, measured on production 2026-08-30. `Minions & Monsters` was
filed as a 17.0 GB Dolby Vision **Profile 5** copy, which Plex cannot play back
on the owner's clients. The owner downloaded a 20.3 GB Profile 8 / HDR10+ copy
by hand into `/downloads` and expected the renamer to file it over the top. It
did not, and it will not, for three independent reasons:

1. **`upgrade_replace` is off** in production settings, which is the master
   switch for replacing a library file. It defaults off deliberately: two
   earlier attempts at replacement each destroyed an irreplaceable file
   (`renamer/replacement.py:9-20`).
2. **A hand-placed file cannot assert which film it is.** The scanner records
   `identity_source`, and only `download_id`, `cp_tag`, `nfo` and `filename`
   are trusted to authorise replacement (`renamer/main.py:490-509`). A file
   dropped into the watch folder is identified by a fuzzy title-and-year search
   (`folder_scanner.py:474`), which is refused, because a wrong guess here does
   not misfile a download, it destroys a **different film's** library copy.
3. **Even with both of those solved it would still refuse.** Both copies are
   2160p, so `is_better` answers no and the outcome is `declined_not_better`.
   Profile 5 versus Profile 8 is a *playability* difference; the system models
   quality rungs only and has no concept of "my player cannot decode this".

Each of those three is correct on its own terms. The gap is that there is no
way for the owner, who **knows** which film it is and **knows** the current copy
does not play, to say so.

**Observed cost while there is no such mechanism.** The refusal is not
terminal: the renamer rescans, re-decides, re-refuses, and leaves the download
in place, every two minutes, indefinitely. Measured on production: 31 identical
`declined_unverified_identity` cycles in 65 minutes, running since 2026-08-28,
each one costing a TMDB lookup and a full folder rescan. The owner's 20.3 GB
file stays in `/downloads` and the logs fill with a decision already made.

This will recur on every Dolby Vision Profile 5 release.

## Not in scope

- **Teaching the upgrade logic about HDR formats and Dolby Vision profiles.**
  Considered and declined by the owner as the largest option, touching the exact
  code path that has already destroyed files twice. This spec instead gives the
  owner an explicit, deliberate action and leaves automatic replacement alone.
- **Changing `upgrade_replace`, `is_better`, or any automatic replacement
  path.** The operator action specced here is a separate entry point. Automatic
  behaviour must be byte-for-byte unchanged, and that is an acceptance
  criterion, not an aspiration.
- **Making the review queue visible.** FEAT-010.

---

## Acceptance criteria

*(To be written by the planning lenses. Each must be testable.)*

**Design constraints the lenses must plan within**, from the incident history in
`renamer/replacement.py`:

- An **explicit operator choice of a specific film plus a specific file is
  itself the identity assertion**, and is stronger than any of the four
  automatic sources: it is a human naming both sides, not an inference. That is
  what makes bypassing `_identityIsAsserted` legitimate here and nowhere else.
- **Bypassing the quality comparison is the entire point** and must not leak
  into the automatic path.
- Everything that protects against *mechanical* failure stays: the atomic swap,
  the expected-source-size check, the destination-inside-the-library check, and
  single-video-file-per-group.
- The action is **destructive and irreversible**: it deletes an irreplaceable
  media file. It needs confirmation naming what is about to be destroyed, and
  per `CLAUDE.md` it may not move a possible loss *up* the recoverability
  ranking.

## Vetoes and trade-offs

| Item | Raised by | Decision | Rationale |
|---|---|---|---|
| Teach the upgrade path about DV profiles / HDR formats | orchestrator | declined by owner | Largest option, on the code path that destroyed files twice. An explicit operator action solves the owner's real workflow without touching automatic replacement. |
| Do nothing, handle by hand each time | orchestrator | declined by owner | Recurs on every DV Profile 5 release. |

## Risks

Ranked by recoverability. **This is the highest-risk change in the current
backlog** and should be reviewed as such.

- **Irreplaceable: it deletes a media file, by design.** A defect that picks
  the wrong destination destroys a film the owner did not choose. Two previous
  attempts at replacement did exactly this. The mitigation is that identity
  comes from an explicit operator choice rather than an inference, but a defect
  in *resolving* that choice to a path reintroduces the same failure.
- **Irreplaceable: bypassing `_identityIsAsserted` for the operator path could
  leak into the automatic path**, re-enabling the class of destruction the
  guard exists to prevent. A test must prove the automatic path still refuses a
  `search`-identified group after this change.
- **Expensive: the source file is consumed.** If the swap commits and the
  bookkeeping does not, the release record and the file on disk disagree.
  `replace_atomically` already orders this so the recoverable half loses
  (`renamer/main.py:271-291`); that ordering must be preserved.
- **Cheap: the retry loop.** Fixing it is a small, separate change with no
  destructive component and could ship first, independently.

## Affected files

| Path | Change |
|---|---|
| `couchpotato/core/plugins/renamer/replacement.py` | An operator-initiated outcome distinct from every automatic one |
| `couchpotato/core/plugins/renamer/main.py` | Entry point for the operator action; automatic path unchanged |
| `couchpotato/ui/templates/partials/movie_detail.html` | The action, its file picker, and its confirmation |
| `tests/unit/` | The automatic path still refuses; the operator path proceeds; the swap still verifies size and containment |

---

## Review cycle

*(To be filled by the review cycle.)*
