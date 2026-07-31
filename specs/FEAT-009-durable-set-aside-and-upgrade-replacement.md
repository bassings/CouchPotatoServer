# FEAT-009 — A set-aside release must survive a rescan, and an upgrade must be able to land

Prerequisite for FEAT-008's "Move back to wanted". Six review rounds established
that the restore action cannot be made durable inside FEAT-008, because two
platform-level facts defeat every attempt. This spec fixes those two facts.

Everything below was measured, not inferred; the measurements are cited.

---

## Background: why four designs failed

Restoring a movie to wanted has to stop the copy it already holds from counting
as satisfying the profile — in `MediaPlugin.restatus` (counts `done` releases)
and in `MovieSearcher.single`'s `has_better_quality` loop (counts anything not
`available`/`ignored`/`failed`). Marking the held release `ignored` does both.

The problem is durability: `Release.add` — the library scanner's entry point —
rebuilds the release doc with a hardcoded `'status': 'done'` and never reads the
current status. Every full scan ("Update Library", or the
`library_refresh_interval` cron) therefore resurrects it.

| # | Design | Why it failed |
|---|---|---|
| 1 | Timestamp on the media doc; `restatus` discounts older releases | Covered `restatus` but not `has_better_quality`, so the movie sat in Wanted contacting zero providers. `release.add` also rewrites `last_edit`, re-arming the bug. |
| 2 | `release.add` preserves `ignored`/`failed`, keyed on `release_identifier` | That identifier is `<imdb>.<audio>.<quality>` — a quality **rung**. Meant "never record any copy at this quality again": a re-downloaded 1080p was filed `ignored`, the movie never completed, and the searcher re-grabbed it weekly. Broke `tryNextRelease` too. |
| 3 | Require a profile that leaves room above what is held | Correct in principle (measured: `[2160p, 1080p]` holding 1080p → `isFinish` False, 1 search) but `build_profile_doc` sets `finish=True` on every rung of every seeded profile, so it would refuse essentially every real restore. |
| 4 | As #2, but keyed on the scanned **file set** | Unsound in both directions. `folder_scanner.py:270` builds the list from a `set`, so ordering is hash-randomised — 3 distinct orderings of one unchanged folder across 6 seeds locally, 9 across 14 processes in review. And the default renamer naming (`<namethe> (<year>)` / `<thename><cd>.<ext>`) carries no quality/group/source token, so every copy renames to the **same path** and a new copy looks identical. |

The common cause: **the data model has no per-copy identity.** One release doc
exists per quality rung, updated in place, and its paths are neither stable nor
distinguishing. That is what Part A adds.

## Background: the upgrade cannot land anyway

`renamer/main.py:220` — `if os.path.exists(dst): continue`. A replacement copy
is never moved into the library while the old file is there. Worse, `cleanup`
then deletes the source folder, so **the download the user just made is
discarded**. This affects every upgrade path, not only FEAT-008.

`remove_lower_quality_copies` ("Delete Others — Remove lower/equal quality
copies of a release after downloading", default **True**) is declared in
`renamer/api.py:135` and read **nowhere** in the codebase. The behaviour users
are already promised is unimplemented. That is Part B.

---

## Part A — per-copy release identity

### Acceptance criteria

1. A release doc records a `copy_id`: a stable digest derived from the **sizes**
   of the release's movie files, sorted.
   - Size, because the scanner already stats files, two different encodes
     essentially never share a byte size, and size is immune to both defects
     that killed design #4 (path collisions and set ordering).
   - Sorted, so scanner ordering cannot affect it.
2. `Release.add` preserves a deliberate `ignored`/`failed` status **only** when
   the scanned `copy_id` equals the stored one. Any difference means a different
   copy, which completes normally (`done`).
3. When `copy_id` cannot be computed on either side (missing files, an unreadable
   path, or a doc created by `createFromSearch`, which stores no files), the
   status is `done` — i.e. it degrades to today's master behaviour rather than
   guessing.
4. No behaviour change for any release whose status is not `ignored`/`failed`.
5. `tryNextRelease` and `markFailedAndResearch` must not regress. Both mark by
   status; a replacement copy must still complete the movie.

### Risks

- **Do not let the rule wrongly preserve.** That is the failure that produced an
  unbounded weekly re-download loop in design #2/#4. Pin the "a different copy
  still completes" direction explicitly, with a fixture whose only difference is
  file size (identical paths — the default-renamer case).
- **Do not stat on every scan if it is expensive.** Sizes come from the scan
  itself where available; a missing size degrades per AC3, it does not raise.

---

## Part B — an upgrade must be able to replace what is there

> **STATUS: the replacement half is NOT IMPLEMENTED and is deferred.** Only the
> safety half shipped: a skipped move no longer lets `cleanup` destroy the
> download. Replacement was attempted twice and withdrawn both times, because
> each attempt put the user's irreplaceable library at risk —
>
> 1. No quality comparison at all. Measured: a 720p download overwrote a 2160p
>    remux. This moved the loss from the replaceable side (the download) to the
>    irreplaceable side, which is worse than the bug it fixed.
> 2. Comparison via `quality.ishigher`. That is a SEARCH heuristic — it returns
>    `'higher'` when the existing quality is not a rung of the profile
>    ("anything beats a rung I do not want", `quality/main.py`). The default
>    `Best` profile excludes 2160p, so it still authorised destroying a remux.
>    It was also inert: the scanner-supplied `group['media']` has no `releases`
>    key (`media.get` attaches that, and the scanner never calls it), so the
>    gate always refused. Fixing the inertness would have ACTIVATED the
>    destruction, on the default profile.
>
> **What a third attempt needs, and does not currently have:** a total ordering
> over qualities that is independent of any profile. `QualityPlugin.qualities`
> is such a list, and ranking by index in it is probably the right primitive —
> "is this file better than what is on disk" is a global question, not a profile
> question. It also needs the media's releases attached at the call site, and a
> rule for which release owns a given path when two legitimately claim it.
>
> None of that is a detail of `_moveRenamedFiles`. It is its own change, on the
> one code path that deletes files from the user's library, and it must be
> reviewed as such. **FEAT-008 does not require it:** without replacement the
> app behaves as it always has (skip and warn), and the download now survives.


### Acceptance criteria

1. When the destination exists and `remove_lower_quality_copies` is on (its
   declared default), the renamer replaces it with the incoming file.
2. When it is off, the existing file is left alone and the incoming file is
   **not** silently destroyed — see AC3.
3. `cleanup` must not delete the source folder when any file was skipped or
   failed to move. Today a skipped move followed by cleanup discards the
   download entirely; that is data loss and must not survive this change.
4. Replacing is not merely `os.remove` + move: the destination must not be
   destroyed before the incoming file is known to be in place, or a failure
   mid-way leaves the user with neither copy.

### Risks

- **This is shared code on the path that writes to the user's library.** Two
  changes on the parent branch have already reached outside their feature. Every
  AC above needs the destructive direction pinned: a test that fails if the old
  file is removed when the new one did not land.

---

## Affected files

| Path | Change |
|---|---|
| `couchpotato/core/plugins/release/main.py` | compute/store `copy_id`; preserve deliberate status on match |
| `couchpotato/core/plugins/renamer/main.py` | implement replacement; never cleanup after a skipped move |
| `tests/unit/test_release_copy_identity.py` | new |
| `tests/unit/test_renamer_replacement.py` | new |

## Out of scope

The renamer's default naming template. Adding a quality token would give paths
per-copy meaning, but it changes every user's library layout and is not
necessary once `copy_id` exists.
