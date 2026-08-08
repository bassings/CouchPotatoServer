# FEAT-009B: upgrade replacement — let a better copy land without ever risking the library

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** draft
**Lenses run:** *(to be filled by `/plan-cycle`)* · **Skipped:** *(with why)*

Task **T5** of `specs/REMEDIATION-2026-08.md`; completes Part B of
`specs/FEAT-009-durable-set-aside-and-upgrade-replacement.md`, whose
`STATUS: NOT IMPLEMENTED` block this change retires.

**This is the one code path in the project that deletes files from the user's
library.** It is specified and reviewed on its own, and it is deliberately not
folded into the performance PR.

## Problem

`remove_lower_quality_copies` is offered in the settings UI
(`renamer/api.py:135`) and read by nothing. The renamer's
`_moveRenamedFiles` currently skips unconditionally when the destination exists
(`renamer/main.py:154-157`), so an upgrade the user asked for can never land:
the better copy is downloaded, the setting is on, and the file sits in the
download folder forever.

The safety half of FEAT-009 already shipped: a skip now suppresses `cleanup`, so
the download the user just made is no longer destroyed after being skipped
(`renamer/main.py:167-172`). What is missing is the half that lets the upgrade
actually replace the old file.

### Two attempts were made and both withdrawn. Do not repeat either.

Recorded because CLAUDE.md rule 11 applies: a fix has introduced a defect here
twice, so this third attempt is reviewed as **new work, not a correction**.

1. **No quality comparison at all.** Measured: a 720p download overwrote a 2160p
   remux.
2. **Comparison via `quality.isHigher`.** Re-verified against
   `quality/main.py:530-548`: that function looks the quality up in a *profile*
   and returns `'lower'`/`'higher'` by profile position, falling through to
   "anything beats a quality I do not want" when a rung is absent. It is a
   **search** heuristic — "should I keep looking for a better release for this
   profile" — not a statement about which file is objectively better. The
   default `Best` profile excludes 2160p, so this still authorised destroying a
   remux.

   It was also **inert**: the scanner-supplied `group['media']` carries no
   `releases` key (`media.get` attaches it, and the scanner never calls it), so
   the gate always refused.

**That last point sets the sequencing and it is the single most important
constraint in this spec: the ordering must be correct and proven before the gate
is made live.** Fixing the missing `releases` attachment first would have
activated the destruction on the default profile. Do T5.1 before T5.2.

## Not in scope

- Changing `quality.isHigher` or any search/decision path that consumes it. The
  new ranking is additive; search behaviour must be untouched.
- Any change to the shipped safety half (skip suppresses `cleanup`). This spec
  regression-pins it rather than revisiting it.
- Retrospective replacement of files already in the library (no backfill, no
  rescan-and-upgrade sweep).
- The `renamer.before` / `renamer.after` event chain, which is separately known
  to be unported.

---

## Acceptance criteria

*(To be written by `/plan-cycle`. Per the M15 rule recorded in
`specs/REMEDIATION-2026-08.md`, implementation does not start before this
section exists. The sub-task acceptance notes below are the input to that
cycle, not a substitute for it.)*

---

## Proposed shape, in the order it must be built

### T5.1: Profile-independent quality ranking · S · risk: low

A ranking primitive over `QualityPlugin.qualities` (`quality/main.py:26-38`):
rank by list index, lower index = better. **"Is this file better than what is on
disk" is a global question, not a profile question** — that confusion is what
made attempt #2 dangerous.

The list order, verified 2026-08-08:

    2160p · bd50 · 1080p · 720p · brrip · dvdr · dvdrip · scr · r5 · tc · ts · cam

- New event/method, e.g. `quality.rank`, returning the index, or `None` when the
  quality is unknown.
- **Unknown quality on either side ⇒ refuse to replace.** Degrade to today's
  skip-and-warn rather than guessing, matching Part A's AC3 philosophy.
- **Pin the 3D rule.** `is_3d` is not part of the global list ordering, so a 3D
  and a non-3D copy at the same rung are not comparable: treat as "not better"
  and refuse.

**Acceptance input:** a test table over the full list pins the ordering,
including `bd50` above `1080p` and `brrip` below `720p`. Explicitly pin **720p
vs 2160p → not better** (the case measured to fail in attempt #1) and the
default-`Best`-profile case from attempt #2 — the ranking must not consult a
profile at all, so a test that passes a profile and asserts *no behaviour
change* is the guard against regressing to `isHigher`.

### T5.2: Attach releases at the call site · S · risk: medium

Attach the media's releases where the renamer needs them, so the gate is
reachable at all.

**Only after T5.1 is green.** This is the change that makes the gate live; on
the previous attempt it would have activated destruction.

**Acceptance input:** a test asserts the renamer sees the media's releases, and
that the replacement gate is *exercised* rather than silently refusing. An inert
gate is a vacuous guard (CLAUDE.md §11 / rule 10).

### T5.3: Atomic replacement · M · risk: **high**

Replace the unconditional skip with: replace when
`remove_lower_quality_copies` is on **and** the incoming copy ranks strictly
better; otherwise keep the existing file and preserve the download.

Replacement must never be `os.remove` then move. Sequence:

1. Move the incoming file into the **destination directory** under a temporary
   name.
2. Verify it landed: size matches the source.
3. `os.replace(tmp, dst)`.
4. Only then account for the old copy.

If any step fails, the destination is untouched and the download survives.

**Gotcha that decides the design:** `os.replace` is atomic only *within* a
filesystem, and on this project's target deployment the library and the download
directory are frequently different mounts. The temp file must therefore be
created in the destination directory, not the source. This interacts directly
with `moveFile`'s hardlink/symlink fallback branches, which PR 1 now covers —
reuse those tests as the foundation rather than building a parallel harness.

**Acceptance input — every one is a destructive-direction test:**

- The old file is **not** removed when the new one did not land (kill the move
  mid-way; assert both the original and the download survive).
- A strictly better copy replaces; an equal or worse copy does not.
- With `remove_lower_quality_copies` off, the existing file is untouched **and**
  the incoming file is not silently destroyed.
- `cleanup` does not delete the source folder when any file was skipped or
  failed — regression-pin the shipped safety half so this change cannot undo it.

### T5.4: Path ownership · S · risk: medium

FEAT-009 names an open design question: which release owns a given path when two
legitimately claim it. Resolve it explicitly (`copy_id` from Part A is the
natural discriminator) and **write the rule down**. An ambiguous answer here is
how the wrong file gets deleted.

---

## Constraints that already have teeth

1. **Rank data risk by what cannot be recovered** (CLAUDE.md): irreplaceable
   (media files) → expensive (a completed download) → cheap. A change that moves
   a possible loss *up* that list is worse than the bug it replaces, however
   correct it looks. Both withdrawn attempts failed exactly this test.
2. **Rule 11 is live on this function.** Two prior fixes introduced defects here.
   A third failed attempt is a signal to stop and re-open the approach, not to
   try a fourth.
3. **An inert gate passes every non-destructive test.** Attempt #2 was inert and
   looked safe. Any test that asserts "no replacement happened" must prove the
   gate was *reached and declined*, not that it was never called.

## Verification plan

- The replacement path exercised end-to-end against a real tmp filesystem, not a
  mocked one — including the cross-filesystem case the `os.replace` gotcha is
  about.
- Every destructive-direction test above run in both directions.
- A review lens specifically on "can this delete something irreplaceable", in
  addition to the standard set.
