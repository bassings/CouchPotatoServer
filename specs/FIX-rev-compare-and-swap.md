# FIX — Compare-and-swap on `_rev` in SQLiteAdapter.update()

## Problem

`couchpotato/core/db/sqlite_adapter.py`'s `update(data)` read the existing
`_rev` only to check that the document exists, then ran:

```sql
UPDATE documents SET _rev=?, _t=?, data=?, updated_at=? WHERE _id=?
```

The `WHERE` clause has **no `AND _rev = ?` guard**. Two concurrent
read-modify-write cycles on the same document race like this:

1. Thread A `get()`s the doc at rev `X`.
2. Thread B `get()`s the same doc, also at rev `X`.
3. Thread A mutates its copy and `update()`s -> doc is now at rev `Y`.
4. Thread B mutates *its* (stale) copy -- which never saw A's change -- and
   `update()`s. The unconditional `WHERE _id=?` matches regardless of rev,
   so B's write silently **overwrites A's change** with no error and no
   trace (a classic lost update).

REG-004's `UNIQUE(provider, identifier)` index on `media_identifiers`
prevents *duplicate media rows*, but does nothing for this: it's a
different failure mode -- an existing doc's JSON body (status flips,
tag/quality edits, release status transitions, watch metadata) silently
regressing to a stale value. REG-002's threadpool made concurrent writes to
the FastAPI app routine (previously mostly serialized by Tornado's
single-threaded model), so this is no longer a theoretical race.

## Fix

### 1. `update()` — compare-and-swap when `_rev` is present

If the caller's `data` dict carries a `_rev` (true for every doc obtained
via `get()`/`query()`/`update_with_retry()` -- i.e. essentially all
real-world callers), the UPDATE is now conditioned on that exact `_rev`
still being current:

```sql
UPDATE documents SET _rev=?, _t=?, data=?, updated_at=? WHERE _id=? AND _rev=?
```

binding the caller's *expected* `_rev` as the last parameter (the new,
freshly-generated rev is still what gets written).

If `cursor.rowcount == 0`, the adapter distinguishes the two possible
causes with a follow-up `SELECT _rev FROM documents WHERE _id = ?`:

- **Row doesn't exist at all** -> `KeyError` (unchanged from before).
- **Row exists but with a different `_rev`** -> a new `ConflictError`
  (defined in `sqlite_adapter.py`, subclasses `Exception`, carries `._id`
  and a descriptive message). This is the lost-update signal: the caller's
  in-memory copy is stale.

In both branches, the (empty) write is rolled back before raising, same
rollback discipline as the existing `sqlite3.IntegrityError` handler right
below it.

### 2. Backward-compat: no `_rev` -> unconditional update (documented trade-off)

Some call sites build a *fresh* dict rather than mutating a `get()` result
(no `_rev` in scope at all). Forcing CAS on them would break them outright
with no way to supply a rev. If `data` has **no `_rev` key**, `update()`
falls back to the previous unconditional last-writer-wins UPDATE, logging
at `debug` that CAS was skipped. This is deliberately permissive: it keeps
existing untouched callers working exactly as before (no behavior change
for them), at the cost of leaving them exposed to the original race. Tests
`test_update_without_rev_falls_back_to_unconditional_update` and
`test_update_without_rev_overwrites_concurrent_change_last_writer_wins`
document both the compatibility guarantee and the trade-off explicitly, so
this isn't a silent gap.

The return shape `{'_id': ..., '_rev': <new rev>}` is unchanged in all
paths.

### 3. `update_with_retry(mutator, doc_id, retries=3)` — safe RMW primitive

New adapter method: re-`get()`s the doc, calls `mutator(doc)` (mutate in
place), then `update()`s. On `ConflictError` it re-reads and re-applies the
mutator, up to `retries` attempts, then re-raises the last `ConflictError`.
`mutator` may return `False` to mean "no change needed" -- `update_with_retry`
then skips the write entirely, with no retry. Any other return value means
"write it". This lets callers express "only write if something actually
changed" (e.g. a status that's already at the target value) without a
spurious rev bump.

**Return contract:** `update_with_retry` returns the *updated* document
dict (carrying its freshly-bumped `_rev`) when a write actually happened,
or **`None`** when the mutator returned `False` on any attempt -- including
a retry attempt after this call lost the CAS race and re-read a document
that turned out to already be at the desired state. Callers must key
side effects (e.g. firing a notification) off this `None` vs. non-`None`
distinction, not off whatever the mutator closure did on its *first*
attempt: if attempt 1 mutates the in-memory doc but then loses the write
race, and the retry's re-read finds the doc already at the target state
(because the winning concurrent writer got there first), the mutator
returns `False` on the retry and no write happens on this call at all --
yet a flag captured only from attempt 1 would still say "changed",
producing a spurious duplicate notification for a write this call never
made. (This exact bug existed in `Release.updateStatus` before it was
fixed to gate on the return value instead of an accumulating closure
flag -- see "Callers converted" below.)

`KeyError` (missing doc) propagates immediately, un-retried, since retrying
a nonexistent document can never converge.

### 4. Callers converted

Two clear, unlocked read-modify-write hotspots were converted to
`update_with_retry`:

- **`couchpotato/core/media/_base/media/main.py`: `markWatched` /
  `markUnwatched`.** User-triggered (API call, e.g. double-click / two
  browser tabs / two devices marking the same movie watched), a plain
  `get()` + field-set + `update()` with **no lock at all**. A lost update
  here silently drops watch metadata. The mutator only sets/clears watch
  fields; the not-found path (`KeyError` from the doc no longer existing)
  is caught identically to the prior `RecordNotFound`/`KeyError` handling
  around the old `db.get()` call, preserving the `{'success': False,
  'error': 'Media not found'}` contract.
- **`couchpotato/core/plugins/release/main.py`: `updateStatus`.** The
  single most-repeated release status-transition function -- called from
  search, snatch, download, ignore, and clean paths -- with **no lock**
  protecting it. A lost update here can regress a release's status (e.g.
  `downloaded` silently reverting to `available`), which is exactly the
  audit's concern. The mutator returns `False` (skip write) when the
  release is already at the target status, matching the original "only
  touch the doc if status changed" short-circuit -- so `updateStatus`'s
  `fireEvent('notify.frontend', ...)` fires strictly on `update_with_retry`
  returning non-`None` (i.e. this call actually wrote), not on every no-op
  call. (An earlier revision of this conversion instead tracked "did the
  mutator run its write branch" via a closure flag set on the *first*
  attempt; that flag stayed `True` even when a later retry attempt's
  mutator short-circuited after losing the CAS race, causing a spurious
  duplicate `notify.frontend` for a write this call never made. Fixed by
  gating on `update_with_retry`'s return value instead -- see its return
  contract above.)

### 5. Callers deliberately left for follow-up (not converted)

These have unambiguous read-then-write shapes but were judged too risky to
mechanically refactor into the `mutator(doc)` shape in this change, because
business logic and side effects (network calls, nested `fireEvent`s,
early-return branches) are interleaved with the read and the write in ways
that don't cleanly separate into "read, mutate in memory, write":

- `couchpotato/core/media/movie/_base/main.py`: `update()` (fetches info
  from providers mid-flight, has its own `acquireLock`/`releaseLock`
  pairing keyed by media id/identifier -- re-entrant refactor risk),
  `edit()` (mutates multiple fields conditionally, deletes releases, fires
  `media.restatus` and re-reads the doc afterwards -- **not currently
  locked**, a real follow-up candidate but the multi-step flow needs more
  careful redesign than a drop-in mutator), `updateReleaseDate()` (network
  call to `movie.info.release_date` between read and write, **not
  currently locked**), and the tail `db.update(m)` inside `add()` (already
  serialized by `media_lock(identifier_key)`, so the immediate risk is
  lower, but the surrounding function has several conditional early paths
  that made a safe mutator boundary non-obvious in the time available).
- `couchpotato/core/media/_base/media/main.py`: `restatus`, `tag`, `unTag`
  -- already wrapped in `with media_lock(media_id):`, an in-process
  per-key `RLock` that already serializes read-modify-write on the same
  key within one process. Since this app runs single-process, these are
  not currently racy in practice; converting them is lower-value
  defense-in-depth rather than a fix for a live bug, and `restatus`
  interleaves a second `db.get('id', profile_id)` and a `fireEvent`
  between read and write, complicating a clean mutator boundary. Left as
  a genuine follow-up (multi-process deployment would need it), not
  converted here.
- `couchpotato/core/media/_base/media/main.py`: `cleanupFaults()` --
  read-modify-write with no lock, but runs once at `app.load` (startup),
  effectively single-threaded at that point; low real-world risk.
- `couchpotato/core/plugins/release/main.py`: `add()` (already under
  `media_lock`), `clean()` and `ignore()` (file-list cleanup / toggle via
  `updateStatus`, which itself is now CAS-protected transitively; `clean()`
  itself is a straightforward `get()`+mutate+`update()` with no lock and
  would be a reasonable, low-risk future conversion -- left out here to keep
  this change's caller-conversion surface small and reviewable), and
  `cleanDone()`'s inline `doc['status'] = 'ignored'; db.update(doc)` fixup
  (runs during a periodic maintenance sweep, low concurrency risk, and the
  surrounding loop already has its own try/except/reindex bookkeeping that
  would need care to preserve if refactored).

None of the above were modified in this change; `db.update()`'s CAS
contract still protects them at the storage layer (a concurrent write will
now raise instead of being silently lost) -- they just don't yet retry
automatically on conflict.

### 5a. `couchpotato/core/migration/fix_release_quality.py` — gap closed

This migration's per-release loop does a plain `db.update(doc)` (not
`update_with_retry`) under a per-release `except (RecordNotFound, KeyError,
TypeError)`. Since `db.update()` can now raise `ConflictError` for any doc
carrying a `_rev` (which every doc loaded via `get_many(..., with_doc=True)`
does), a real CAS conflict on one release used to fall through that narrow
except tuple, propagate out of the whole scan loop, get caught by the
migration's outer catch-all, and abort processing of *every remaining*
release in the batch -- not just the one that conflicted. Fixed by adding
`ConflictError` to the per-release except tuple, so a conflict now just
skips that one release (logged at debug, same as the other skip reasons)
and the loop continues with the rest of the batch.

### 5b. `couchpotato/core/plugins/release/main.py` `createFromSearch()` — gap closed (review)

`createFromSearch()` loops over `search_results` and calls a plain `db.update(rls)`
per release (line ~505) to persist each upserted release doc, with the entire
function body wrapped in one function-level `try/except Exception: ... return
[]`. Since `db.update()` can now raise `ConflictError` for any doc carrying a
`_rev`, a real CAS conflict on just one release -- plausible because
`updateStatus()` elsewhere in this same file can concurrently mutate that same
release doc via its own CAS retry path -- used to propagate out of the whole
loop, get caught by the function-level catch-all, and discard every
`found_releases` entry already accumulated for the *other* releases in the
batch, not just the one that conflicted. Fixed the same way as 5a: the
`db.update(rls)` call is now wrapped in its own per-iteration
`try/except ConflictError`, which logs a warning (`'Skipped release %s due to
a concurrent update: %s'`) and `continue`s to the next release, so the
function still returns the partial `found_releases` list for the releases
that updated successfully. The happy-path return contract (no conflicts ->
same list as before) is unchanged.

### 6. Explicitly out of scope

- `insert()`, `delete()`, `get()` semantics: unchanged.
- `_generate_rev()`: unchanged.
- `couchpotato/lib/` / `libs/` (CodernityDB): untouched.

## Tests

`tests/unit/test_sqlite_adapter.py`:

- `TestSQLiteAdapterCompareAndSwap`:
  - `test_update_with_correct_rev_succeeds_and_bumps_rev` -- normal path.
  - `test_stale_rev_raises_conflict_and_does_not_clobber` -- **the
    no-clobber proof**: two readers fetch the same doc at rev A; reader B
    writes first (advancing to rev B); reader A then tries to write its
    stale rev-A copy and gets `ConflictError` (asserted to carry the doc's
    `_id`); a final `get()` confirms the document still holds reader B's
    `status` and rev -- i.e. reader A's write never landed, proving the
    race is closed rather than merely erroring cosmetically while still
    clobbering.
  - `test_update_missing_id_still_raises_keyerror` -- KeyError semantics
    preserved even when a (meaningless) `_rev` is supplied for a
    nonexistent id.
  - `test_update_without_rev_falls_back_to_unconditional_update` /
    `test_update_without_rev_overwrites_concurrent_change_last_writer_wins`
    -- backward-compat contract and its trade-off, both made explicit.
- `TestSQLiteAdapterUpdateWithRetry`:
  - `test_converges_when_no_conflict`.
  - `test_converges_after_a_single_conflict` -- monkeypatches `db.update`
    to inject one concurrent write on the first attempt only, and asserts
    `update_with_retry` transparently retries and converges (exactly 2
    internal attempts).
  - `test_raises_conflict_after_exhausting_retries` -- a `db.update` stub
    that injects a fresh conflicting write on *every* attempt; asserts
    `ConflictError` propagates once `retries` is exhausted rather than
    looping forever.
  - `test_missing_document_raises_keyerror`.

`tests/unit/test_watch_history.py` -- extended for the `update_with_retry`
call site: `test_mark_watched_records_watch_metadata_without_changing_media_status`
and `test_mark_unwatched_clears_watch_metadata_without_changing_media_status`
were updated to mock `db.update_with_retry` (applying the mutator to the
test fixture, mirroring the real adapter's contract) instead of
`db.get`/`db.update`, preserving the same field-level and
`fireEvent`-call assertions as before the conversion. Added
`test_mark_watched_returns_not_found_when_media_missing` for the
not-found path through the new call site.

`tests/unit/test_release_update_status_cas.py` (new) -- covers the
converted `Release.updateStatus()`:
`test_update_status_changes_status_and_notifies`,
`test_update_status_no_op_when_already_at_target_status_does_not_notify`
(proves the mutator's `False`-return short-circuit preserves the
"only write and notify on genuine change" behaviour),
`test_update_status_without_status_arg_is_a_noop`,
`test_update_status_missing_release_returns_false`, and
`test_update_status_survives_a_transient_conflict_via_retry_helper` (an
end-to-end check against a real `SQLiteAdapter`, not a mock, confirming the
call site is wired correctly).

## Acceptance criteria

- [x] `update(data)` performs a CAS UPDATE (`WHERE _id=? AND _rev=?`) when
      `data` contains a `_rev`.
- [x] A lost CAS race raises `ConflictError` (carrying `_id`) rather than
      silently overwriting; the document's stored value is unaffected by
      the losing write (proven by test).
- [x] A genuinely missing document still raises `KeyError` (both with and
      without a `_rev` present in the caller's dict).
- [x] `data` without a `_rev` still updates successfully (documented
      last-writer-wins fallback, unchanged from pre-CAS behavior).
- [x] `update_with_retry(mutator, doc_id, retries=3)` exists, retries on
      `ConflictError`, supports a mutator-signalled no-op skip, and raises
      after exhausting retries.
- [x] `markWatched`/`markUnwatched` (media) and `updateStatus` (release)
      converted to `update_with_retry`; their existing observable
      behavior/tests preserved (extended, not weakened).
- [x] `insert`/`delete`/`get`/`_generate_rev` unchanged; `couchpotato/lib/`
      and `libs/` (CodernityDB) untouched.
- [x] Full suite green: `pytest tests/unit/ -q` -- 1032 passed (was 1026
      before this change; +6 net from the new/extended test files).
- [x] `ruff check .` clean.

## Follow-up (not done here)

See "Callers deliberately left for follow-up" above for the specific list
and reasoning per call site. In priority order for a future pass:

1. `movie/_base/main.py::edit()` and `updateReleaseDate()` -- currently
   **unlocked** read-modify-write; genuine follow-up candidates, but need a
   deliberate mutator-boundary redesign (network calls / multi-field
   conditionals interleaved with the write) rather than a mechanical swap.
2. `release/main.py::clean()` -- straightforward unlocked RMW, low risk to
   convert, left out here purely to keep this PR's surface small.
3. `media/_base/media/main.py::restatus/tag/unTag` -- already
   `media_lock`-protected (safe under the current single-process
   deployment model); would matter if CouchPotato ever runs multi-process.
