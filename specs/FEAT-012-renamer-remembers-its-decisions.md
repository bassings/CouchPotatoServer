# FEAT-012: the renamer remembers it has already looked at a file

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** draft
**Lenses run:** <plan-cycle to fill> · **Skipped:** <plan-cycle to fill>

## Problem

The renamer re-makes a decision it has already made, about a file that has not
changed, every two minutes, forever.

Observed on production. `Minions & Monsters` finished downloading a second
time on 2026-08-28 at 21:30. The renamer scanned `/downloads`, resolved the
group's identity, decided it could not replace the library copy
(`declined_unverified_identity`), left the download in place, and then did the
whole thing again on the next scan. It did not stop until the owner moved the
file by hand on 2026-08-30 at 09:58.

**Roughly 36 hours and 1,100 cycles**, each one costing a full folder rescan
and a live TMDB search, to reach a conclusion that was already reached at
21:30 and could not change.

Measured directly: 31 identical `Destination already exists, keeping it`
cycles in a 65-minute window, one every two minutes, and after the file was
moved the renamer immediately reported `Renamer found 0 groups to process`.

The refusal itself is correct and should be kept. Two previous attempts at
upgrade replacement each destroyed an irreplaceable file, and this guard is
what stops the third. What is wrong is that **a refusal has no memory**: the
code path treats "I have decided not to act on this" and "I have not looked
at this yet" as the same state.

**Owner's framing, 2026-08-30:** "we don't need to cache the look up, we need
to remember that we've already looked at a file."

That is the right level. Caching the TMDB call would make the loop cheaper and
leave it running. Remembering the decision removes it.

### Costs, in order of what actually matters

- **The log becomes useless.** The same three lines repeated ~1,100 times bury
  everything else. An operator scrolling this log cannot see anything real
  that happened in those 36 hours, which is the failure mode that matters most:
  a noisy log is a log nobody reads.
- **Nothing said anything was stuck.** The condition needing a human ran for a
  day and a half and produced no signal distinguishable from normal operation.
- **A third-party API is polled for an unchanging answer.** ~1,100 TMDB
  searches for one film. Rate limiting is the owner's risk to carry, not
  TMDB's to absorb.
- **The download stays on disk.** 20.3 GB held in `/downloads`, correctly (the
  data must not be destroyed), but with no route to resolution.

### A SEPARATE defect found while measuring this, not the fix

The TMDB call should have been served from cache on all but the first of those
~1,100 polls, and never was. Proven by executing the real cache class:

| Value passed to `SQLiteCache.set` | Stored? |
|---|---|
| `bytes` | **No** |
| `str` | Yes |
| `dict` | Yes |

`HTTPClient.request` returns bytes by its own docstring, and every provider
body reaches the cache through `getJsonData` / `getRSSData` unchanged. So
`json.dumps(value)` raises `TypeError`, `SQLiteCache.set` catches it and
returns, and the write is dropped with a `log.debug` line nobody reads.

This is **not scoped into this spec** and must not be fixed as a side effect
of it, because the two fixes are independent and the cache one is far wider:
it silently disables HTTP response caching for every provider in the
application, not just this path. Production evidence is consistent with it:
122 cache entries, all written by call sites that pass a dict or a string, and
none live at the time of measurement. Raised separately as T67.

Fixing the cache alone would NOT fix this problem. It would make an endless
loop quieter, which is worse than an endless loop that is obvious.

## Not in scope

- **Changing any replacement decision.** Every outcome in
  `renamer/replacement.py` keeps its current meaning and its current answer.
  This spec changes only how often the question is asked.
- **Fixing the HTTP cache** (T67, above).
- **Making a hand-placed replacement land**, which is FEAT-011. That is the
  route by which this particular film would have resolved; this spec is about
  the loop, which would still be wrong even if FEAT-011 shipped.
- **Deleting or moving the download.** Leaving the file in place on a refusal
  is deliberate and stays: a skipped move followed by cleanup is exactly how
  this code destroyed a user's download once already.

---

## Acceptance criteria

*(To be written by the planning lenses.)*

**Design constraints the lenses must plan within:**

- **A remembered decision must expire on any input that could change it.**
  At minimum: the source file changing (size or mtime), the destination
  appearing or disappearing, and the settings that feed the decision changing.
  A refusal that outlives its cause is a bug report the owner cannot clear, and
  it is worse than the loop because it is silent.
- **A restart must re-decide.** Restarting is what an operator does after
  changing something, and it is the cheapest correct invalidation signal.
  Remembering across restarts buys little and risks a stuck state surviving the
  one action a human would expect to clear it.
- **Say it once, loudly enough.** The first refusal is news and should be
  visible. The 1,100th is noise. But going completely silent replaces a noisy
  failure with an invisible one, so a film parked in a refusal needs to be
  discoverable somewhere other than the log.
- **Never let "already decided" mean "already done".** These are different, and
  conflating them would let a file be treated as filed when it is still sitting
  in the download folder.

## Vetoes and trade-offs

| Item | Raised by | Decision | Rationale |
|---|---|---|---|
| Cache the TMDB lookup instead | owner, then withdrawn | rejected by owner | Makes the loop cheaper rather than removing it. The lookup being uncached is a real but separate defect (T67). |
| Persist decisions across restarts | orchestrator | to be decided at planning | Leans no: a stuck refusal surviving a restart removes the operator's most obvious remedy. |

## Risks

Ranked by recoverability.

- **Irreplaceable: none directly.** This spec removes work; it does not add a
  destructive path.
- **Irreplaceable, indirectly: a stale remembered refusal.** If invalidation is
  wrong, the renamer stops acting on a file it now COULD file correctly, and
  the download sits unfiled while the operator believes it is being handled.
  Nothing is destroyed, but a download can be lost to a disk clean-up nobody
  connects to this. This is the whole risk of the change and where review
  should concentrate.
- **Cheap: log volume and API calls**, which is what the change reclaims.

## Affected files

| Path | Change |
|---|---|
| `couchpotato/core/plugins/renamer/main.py` | Skip re-deciding an unchanged group; record the outcome |
| `couchpotato/core/plugins/scanner/folder_scanner.py` | Possibly the cheaper skip point, before identity resolution costs a lookup |
| `tests/unit/` | An unchanged group is decided once; each invalidation trigger forces a re-decide |

---

## Review cycle

*(To be filled by the review cycle.)*
