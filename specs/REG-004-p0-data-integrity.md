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
  on `media_identifiers(provider, identifier)`. This covers **fresh installs**
  via `create()` → `_init_schema()`.
- `sqlite_adapter.py` — **existing-DB self-upgrade** (added in the review
  follow-up): `open()` never re-runs `schema.sql`, so fresh-install-only
  coverage would leave every pre-REG-004 database (including prod's live DB —
  the one from the 77-duplicate incident) permanently unprotected. `open()`
  now calls `_ensure_unique_media_identifier_index()`, which:
  - Detects (via `PRAGMA index_list`/`index_info`) whether a UNIQUE index on
    `media_identifiers(provider, identifier)` already exists; if so, no-op.
  - Otherwise the install has the legacy **non-unique** index named
    `idx_media_identifiers_lookup`. Because `CREATE UNIQUE INDEX IF NOT EXISTS`
    with that same name is a silent no-op, it **`DROP`s** the old index and
    **`CREATE`s** it UNIQUE (SQLite auto-commits DDL, so a failed CREATE can't
    be rolled back — the drop+recreate is explicit and deliberate).
  - If the CREATE fails because **historical duplicate rows still exist**
    (`sqlite3.IntegrityError`/`OperationalError`), it does **not** auto-dedup
    (destructive). It recreates the original non-unique index and logs a LOUD
    `log.warning` (duplicate identifiers present → running with in-process-lock
    protection only → run the future dedup migration to enable the DB-level
    backstop), then continues startup. Startup **never bricks**.
  - Net: clean existing DBs self-upgrade to the backstop the first time they
    open; dirty DBs keep working in lock-only mode with a loud warning until a
    dedup migration runs.
- `sqlite_adapter.py` `_init_schema()` — defensive (review follow-up): the
  `executescript(schema.sql)` is wrapped so the "dups + a fresh `create()`
  against an already-populated path" edge can't crash startup uncaught. On
  `IntegrityError`/`OperationalError` it logs the same warning and retries the
  script with the UNIQUE index downgraded to a plain index (every schema
  statement is `IF NOT EXISTS`, so re-running is idempotent).
- **Future P2 dedup-migration runner (tracked follow-up, NOT in this change).**
  To enable the DB-level backstop on a DB that still has duplicate rows, that
  runner must: (1) **dedup** the `media_identifiers` rows (and reconcile the
  duplicate media documents they point at — merge releases, delete the losing
  media docs) so each `(provider, identifier)` maps to exactly one media_id;
  (2) **`DROP INDEX idx_media_identifiers_lookup`** (the surviving non-unique
  index); (3) **`CREATE UNIQUE INDEX idx_media_identifiers_lookup`**. Steps
  (2)+(3) are exactly what `_ensure_unique_media_identifier_index()` already
  does automatically once the data is clean — so in practice the runner only
  needs the destructive dedup step, then the next `open()` finishes the job.
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
- **Existing-DB self-upgrade (review follow-up):**
  - A pre-REG-004-shaped DB (non-unique index) with **no** duplicate rows:
    after `open()`, a UNIQUE index exists and a duplicate insert raises
    `IntegrityError`.
  - A pre-REG-004 DB **with** a duplicate `(provider, identifier)` pair:
    `open()` does not raise, logs the loud warning, and startup completes with
    the non-unique index still in place (lock-only mode).
- **Lock proven in isolation (review follow-up):** with an instantly-consistent
  in-memory DB that has **no** uniqueness backstop, N real threads racing
  `MovieBase.add()` for the same imdb id produce exactly **one** insert / one
  doc — demonstrating `media_lock` serializes the critical section rather than
  the DB backstop cleaning up after the fact. (Negative control: with the lock
  stubbed to a no-op, the same scenario yields N inserts.)

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

## Item 4 — CodernityDB→SQLite migration now silently DROPS duplicates (review follow-up)

### Problem

Once the UNIQUE `(provider, identifier)` index exists, migrating a legacy
CodernityDB that contains duplicate media (the exact prod state) makes
`sqlite_db.insert(doc)` raise `sqlite3.IntegrityError` for the second+ doc
sharing an identifier. `codernity_to_sqlite.py` previously caught **all**
exceptions in one bucket and reported them with a bare `print`, so this
**data-loss** on a disaster-recovery path was easy to miss.

### Fix

In the per-document migration loop (`couchpotato/core/migration/codernity_to_sqlite.py`):
- Catch `sqlite3.IntegrityError` **distinctly** from other errors, count it in
  a separate `duplicates` tally, and emit a LOUD `CPLog` (`log.warning`, not a
  bare `print`) naming it a duplicate-identifier skip, stating the row was
  **not** migrated (data loss), and that the original CodernityDB is preserved
  in `database.bak`.
- The end-of-migration summary reports the duplicate count and re-warns via
  `CPLog` when any were skipped.
- CodernityDB remains the upgrade path — nothing about *whether* it runs
  changed; only the logging/counting improved.

### Acceptance

- Migration module imports cleanly; duplicate skips are counted separately and
  surfaced via `CPLog.warning`, not swallowed into the generic error bucket.

## Constraints

- No changes to CodernityDB or anything under `libs/` / `couchpotato/lib/`.
  The `codernity` backend keeps working unchanged; only the `sqlite`
  schema/adapter/call-sites and the (SQLite-facing) migration logging changed.
- `schema.sql` covers fresh installs; existing SQLite DBs self-upgrade in
  `open()` (clean DBs) or run lock-only with a loud warning (dirty DBs) until a
  future dedup migration. No blind ALTER that could brick startup.

## Files

- `couchpotato/core/db/schema.sql`
- `couchpotato/core/db/sqlite_adapter.py`
- `couchpotato/core/media/movie/_base/main.py`
- `couchpotato/core/plugins/release/main.py`
- `couchpotato/core/migration/codernity_to_sqlite.py`
- `tests/unit/test_sqlite_adapter.py`
- `tests/unit/test_movie_add_integrity.py` (new)

## Gate

- `.venv/bin/python -m pytest tests/unit/ -q` fully green.
- `.venv/bin/ruff check .` clean.
- Commit locally on `fix/reg-004-p0-data-integrity`. **STOP after
  committing — do NOT push.**
