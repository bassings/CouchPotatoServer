# REG-004 — P0 data-integrity fixes (duplicate media / stale releases)

## Background

Production already suffered one duplicate-media corruption incident: a bug
in `SQLiteAdapter._query_index` (fixed separately — see
`tests/integration/test_duplicate_detection.py`) let a `'media'` index
lookup ignore its key and return the wrong (or first) document, causing
`movie.add()` and `release.add()` to create 77 duplicate movie entries after
a migration + library refresh.

That specific bug is fixed, but nothing stops the *class* of bug from
recurring: there is no uniqueness backstop at the storage layer, and the
app-layer get-or-insert path in `movie.add()` treats **any** exception from
the lookup as "not found", then inserts unconditionally with no lock. This
spec closes both gaps and fixes one related, independently-discovered
correctness bug (`is` vs `==` on a JSON-deserialized string).

## Item 1 — No uniqueness backstop + `movie.add` insert race (HIGH)

### Problem

- `couchpotato/core/db/schema.sql`: `media_identifiers(media_id, provider,
  identifier)` has `PRIMARY KEY (media_id, provider)` and a plain (non-unique)
  index on `(provider, identifier)`. Two different `media_id`s can each own a
  row for the same `(provider, identifier)` — e.g. two media docs both
  claiming `imdb`/`tt1234567`. Nothing in the schema prevents this.
- `couchpotato/core/media/movie/_base/main.py` `add()`: the get-or-insert
  block wrapped the lookup in a bare `except Exception:` — any error from
  `db.get('media', ...)` (including a transient DB error, not just "not
  found") was treated as "doesn't exist yet" and triggered an unconditional
  `db.insert(media)`. There was also no lock around the check-then-insert, so
  two concurrent `add()` calls for the same imdb id could both observe "not
  found" and both insert.
- `couchpotato/core/db/sqlite_adapter.py` `_update_denormalized()`: the
  `media_identifiers` row was written with `INSERT OR REPLACE`. Adding a
  UNIQUE index on `(provider, identifier)` without changing this would make
  SQLite's conflict resolution **silently delete the other media doc's row**
  instead of raising — defeating the whole point of the constraint.

### Fix

- `schema.sql`: `idx_media_identifiers_lookup` becomes a `CREATE UNIQUE INDEX`
  on `media_identifiers(provider, identifier)`. **Fresh installs only** — no
  migration runs against existing databases (there is no migration runner
  yet, and historical prod DBs may still contain duplicate rows from the
  incident above, which would make creating a unique index fail outright).
  Applying this to existing DBs via a future schema-migration runner is a
  tracked follow-up, not part of this change.
- `sqlite_adapter.py`:
  - `_update_denormalized()`: `media_identifiers` rows are now written with a
    plain `INSERT` instead of `INSERT OR REPLACE`. The preceding
    `DELETE FROM media_identifiers WHERE media_id = ?` already clears any row
    this same document owned, so a plain insert only conflicts when a
    *different* doc already owns the identifier — which is exactly the case
    that must raise, not silently replace.
  - `insert()` and `update()`: the document write + denormalized-table write
    now run in a `try/except sqlite3.IntegrityError`, which rolls back the
    connection (when not already inside an explicit `transaction()`) before
    re-raising. Without this, a failed insert would leave an uncommitted
    `documents` row on the connection that a later, unrelated write could
    accidentally commit alongside.
- `couchpotato/core/media/movie/_base/main.py` `add()`:
  - The lookup's `except Exception:` narrows to `except (RecordNotFound,
    KeyError):` — the two "not found" signals from the codernity and sqlite
    backends respectively.
  - The whole get-or-insert block is wrapped in
    `with media_lock('imdb-%s' % identifier):` (`couchpotato/core/media_lock.py`,
    already used by `release.add()`), serializing concurrent `add()` calls
    for the same imdb id within one process.
  - The insert itself is wrapped in `except sqlite3.IntegrityError:` — if a
    concurrent insert still wins the race (e.g. across processes, which the
    in-process lock can't cover), the loser re-fetches the winner's doc via
    `db.get('media', ...)` instead of failing or duplicating.
- `couchpotato/core/plugins/release/main.py` `add()`: this method already
  runs its whole body under `media_lock(group['identifier'])`, so the
  insert-race scenario doesn't apply here the same way. Its two get-or-insert
  sites (media lookup at ~145, release lookup at ~178) still had the same
  "bare except swallows real errors" anti-pattern, so both narrow to
  `except (RecordNotFound, KeyError):` for consistency. No unique index was
  added for `release_identifier` (out of scope here), so there's no new
  `IntegrityError` to catch at these two sites.

### Acceptance

- Inserting two media docs with the same `(provider, identifier)` on a
  fresh-schema DB raises `sqlite3.IntegrityError`.
- A failed duplicate insert leaves no orphaned `documents` row, and the
  connection remains usable for subsequent writes.
- A simulated concurrent double `movie.add()` (real threads racing
  `SQLiteAdapter.insert()`, and — at the app layer — the `IntegrityError`
  catch-and-refetch path in `movie.add()`) results in **one** media doc, not
  two.

## Item 2 — `is 'available'` identity-comparison bug (MED correctness) — VERIFIED

### Problem

`couchpotato/core/media/movie/_base/main.py:194` (in `add()`) and `:248` (in
`edit()`) — line numbers as fixed; originally 175/229 — compared
`rel['status'] is 'available'`. `rel['status']` is a string produced by
`json.loads()` when the release document is read back out of SQLite, which
is **never** the same object as the `'available'` string literal compiled
into this module, so the comparison is effectively always `False`. Stale
`available` releases were therefore never deleted when a movie was
re-added or edited. Confirmed independently: CPython itself emits
`SyntaxWarning: "is" with 'str' literal. Did you mean "=="?` for both lines
(visible in the `ruff`/`pytest` warning output on current code).

Grepped the whole `couchpotato/` tree (excluding `couchpotato/lib/`, out of
scope per this task's constraints) for the same `is '<literal>'` /
`is "<literal>"` pattern: no other occurrences. (One additional hit exists at
`couchpotato/lib/subliminal/services/__init__.py:132`, inside `libs/`-adjacent
vendored code that is explicitly out of scope for this change — reported,
not fixed.)

### Fix

Both comparisons changed from `is` to `==`.

### Acceptance

- New test inserts/mocks a media doc with an `available` release whose
  `status` string is produced via `json.loads(...)` (not a literal, so it
  isn't accidentally string-interned the same way CPython interns
  compile-time literals) and drives the `add()` re-add path with
  `force_readd=True`. Before the fix, the release is never deleted; after,
  it is.

## Item 3 — Duplicate-corruption regression tests don't run per-PR (MED testability)

### Problem

`tests/integration/test_duplicate_detection.py` guards the exact
`_query_index` corruption branches (the `'media'` index-join lookup and the
`'release_identifier'` lookup) that caused the 77-duplicate-movie incident.
CI and `make verify` only run `tests/unit/`, so this coverage doesn't run on
every PR — a regression in these branches could land unnoticed.

### Fix

Copied (not moved — originals stay in place) the following into
`tests/unit/test_sqlite_adapter.py` under
`TestSQLiteAdapterDuplicateDetectionRegression`, since they're pure
`tmp_path`-backed SQLite tests with nothing integration about them:

- `test_media_lookup_returns_correct_movie_among_many` — the `'media'`
  index-join branch (`sqlite_adapter.py` `_query_index`, `'media'` case),
  confirmed **not** covered by pre-existing unit tests (all existing
  `'media'`-adjacent unit tests used a single-movie DB, which can't
  distinguish "returns the right doc" from "returns the only doc").
- `test_release_identifier_lookup_finds_matching_release` — a
  `release_identifier` hit.
- `test_release_identifier_lookup_raises_keyerror_when_absent` — the
  `release_identifier`-absent-but-media-exists `KeyError` case (Bug 2's
  exact reproduction).

### Acceptance

- All three copied tests pass under `tests/unit/`.
- Originals in `tests/integration/test_duplicate_detection.py` untouched and
  still pass.

## Constraints

- No changes to CodernityDB or anything under `libs/` / `couchpotato/lib/`.
  The `codernity` backend keeps working unchanged; only the `sqlite`
  schema/adapter/call-sites changed.
- `schema.sql` change is additive/fresh-install only — no ALTER migration
  against existing databases.

## Files

- `couchpotato/core/db/schema.sql`
- `couchpotato/core/db/sqlite_adapter.py`
- `couchpotato/core/media/movie/_base/main.py`
- `couchpotato/core/plugins/release/main.py`
- `tests/unit/test_sqlite_adapter.py`
- `tests/unit/test_movie_add_integrity.py` (new)

## Gate

- `.venv/bin/python -m pytest tests/unit/ -q` fully green.
- `.venv/bin/ruff check .` clean.
- Commit locally on `fix/reg-004-p0-data-integrity`. **STOP after
  committing — do NOT push.**
