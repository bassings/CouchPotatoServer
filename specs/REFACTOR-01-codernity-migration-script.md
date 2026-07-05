# REFACTOR-01 — Move CodernityDB->SQLite migration to a standalone script

## Problem

The one-time CodernityDB->SQLite database migration (needed only for
installs that predate the SQLite rewrite) lived inside the live application
tree:

- `couchpotato/core/migration/codernity_to_sqlite.py`,
  `fix_indexes.py`, and `rebuild_buckets.py` implemented the migration and
  its two Py2->Py3 database-format repair helpers.
- `couchpotato/runner.py` imported and called
  `migrate_codernity_to_sqlite()` inline, directly in the startup path
  (`runCouchPotato()`), on every process start.

This meant every CouchPotato server process pulled in the migration code
(and transitively `CodernityDB.database_super_thread_safe`) even on an
already-migrated, SQLite-only install that will never need it again. It also
meant the migration's ~230 lines of one-time, disaster-recovery-flavoured
logic lived alongside, and was indistinguishable from, code that runs on
every startup.

CodernityDB itself (`libs/CodernityDB`) is **not** going away — it remains
the read path for the one-time upgrade of pre-SQLite installs — but the
migration logic that reads it should not be part of the live server
process's normal import graph.

## Design

1. **New standalone script**: `scripts/migrate_codernity_to_sqlite.py`.
   - Directly runnable: `python scripts/migrate_codernity_to_sqlite.py
     --data-dir <dir>` (plus `--codernity-path` / `--sqlite-path` overrides).
   - Bootstraps its own `sys.path` (repo root + `libs/`) at import time, the
     same way `CouchPotato.py` does, so it works whether it's invoked as a
     subprocess by `runner.py`, run manually by an operator, or imported
     directly by tests.
   - Contains the full migration logic, unchanged in behavior: `fix_index_files()`
     (Py2->Py3 index-file repair), `rebuild_after_migration()` (hash-bucket
     rebuild), and `migrate_codernity_to_sqlite()` (the migration itself,
     including the REG-004 duplicate-identifier vs. generic-`IntegrityError`
     attribution and the `database.bak`-preservation log messages).
   - `main(argv=None) -> int`: validates the CodernityDB source exists and
     `database.bak` doesn't already exist, runs the migration, renames
     `database` -> `database.bak` on success, and returns a process exit
     code (0 success, 1 failure) so a subprocess caller can detect failure.
     `if __name__ == '__main__': sys.exit(main())`.
   - `migrate_codernity_to_sqlite()` (and the two helpers) stay
     importable as plain functions for tests and for the manual recovery
     script `test_migration_local.py` at the repo root.

2. **`couchpotato/runner.py`** no longer imports the migration code or
   CodernityDB. The former inline DB-setup block was extracted into two
   small, independently-testable functions:
   - `_resolve_migration_script(base_path)` — resolves and validates the
     absolute path to `scripts/migrate_codernity_to_sqlite.py` relative to
     the install root (`base_path`, already passed into `runCouchPotato()`).
     Raises `RuntimeError` with an actionable message if the script is
     missing (e.g. a broken/partial install) rather than silently
     continuing.
   - `_open_or_create_database(db, data_dir, base_path)` — the detection
     logic:
     - SQLite DB file already exists -> open it, return `True`.
     - Legacy `database/` exists and `database.bak` doesn't -> resolve the
       script, run it **once** via `subprocess.run([sys.executable,
       script_path, '--data-dir', data_dir], check=False)`. On `returncode
       == 0`, open the now-migrated SQLite DB (the script already did the
       `database` -> `database.bak` rename, so `runner.py` does not repeat
       it) and return `True`. On nonzero `returncode`, **raise**
       `RuntimeError` — this aborts startup instead of falling through to
       fresh-database creation, which would otherwise silently discard the
       user's unmigrated library.
     - Otherwise -> create a fresh SQLite DB, return `False` (unchanged
       fresh-install behavior).

   This preserves the historical zero-touch upgrade experience (a legacy
   install still self-migrates on first startup with the new code, no user
   action required) while keeping the live process's own import graph free
   of the migration chain.

3. `clean_orphans.py` and `fix_release_quality.py` were **not** touched —
   both run unconditionally on every startup (`runner.py`'s `app.migrate`
   section, independent of the CodernityDB-migration branch), so they are
   not "one-time migration" code in the same sense and correctly stay in
   `couchpotato/core/migration/`.

## Module-usage map (verified via repo-wide grep before moving anything)

| Module | Used by (besides itself) | Verdict |
|---|---|---|
| `codernity_to_sqlite.py` | `runner.py` (inline, migration branch only); `test_migration_local.py`; `tests/unit/test_migration_dup_detection.py` | Migration-only -> **moved** into the script |
| `fix_indexes.py` | `codernity_to_sqlite.py` (nested import); `tests/unit/test_migration_modules.py`, `test_database_class.py`, `test_migration_dup_detection.py` | Migration-only -> **moved** into the script |
| `rebuild_buckets.py` | `codernity_to_sqlite.py` (nested import, opening-failure fallback); `tests/unit/test_migration_modules.py`, `test_database_class.py` | Migration-only -> **moved** into the script |
| `clean_orphans.py` | `runner.py` line ~236, **unconditionally on every startup** (`app.migrate` section, Py2-legacy orphan cleanup); `tests/unit/test_migration_modules.py`, `test_database_class.py` | Runtime-used -> **kept** in `couchpotato/core/migration/` |
| `fix_release_quality.py` | `runner.py` line ~245, **unconditionally on every startup**; `tests/unit/test_fix_release_quality.py` | Runtime-used -> **kept** in `couchpotato/core/migration/` |

## What moved / what was deleted

- **New**: `scripts/migrate_codernity_to_sqlite.py` — combines the (renamed
  in-place, behavior-unchanged) logic of the three migration-only modules
  plus a new `argparse`-based CLI (`main()`).
- **Deleted**: `couchpotato/core/migration/codernity_to_sqlite.py`,
  `fix_indexes.py`, `rebuild_buckets.py`.
- **Kept as-is**: `couchpotato/core/migration/clean_orphans.py`,
  `fix_release_quality.py`, `__init__.py`.
- **`couchpotato/runner.py`**: replaced the inline `migrate_codernity_to_sqlite`
  import/call + `os.rename()` with `_resolve_migration_script()` +
  `_open_or_create_database()`, which invoke the script as a subprocess and
  raise on failure instead of falling through to fresh-DB creation. Added
  `import subprocess`.
- **`test_migration_local.py`** (repo-root manual recovery script, not run
  by CI/pytest): import updated to the new script location.
- **`CodernityDB` itself**: untouched — `libs/CodernityDB` remains fully
  intact, as does its unrelated use in `couchpotato/core/database.py` (a
  different, pre-existing module providing legacy exception-class
  compatibility for the live app's `Database` plugin; out of scope here).

## Tests

- **`tests/unit/test_migrate_codernity_script.py`** (new; consolidates and
  relocates prior coverage):
  - `TestFixIndexFiles`, `TestRebuildBuckets` (+ edge cases previously
    split across `test_migration_modules.py` and `test_database_class.py`)
    — unchanged assertions, now calling
    `migrate_codernity_to_sqlite.fix_index_files` /
    `.rebuild_after_migration`.
  - The REG-004 duplicate-identifier vs. generic-error dup-detection tests
    (previously `test_migration_dup_detection.py`), with `patch.object`
    targets and the `caplog` logger name updated to the module's new import
    identity (`migrate_codernity_to_sqlite`, imported flat via
    `sys.path.insert(0, .../scripts)` + `import migrate_codernity_to_sqlite`,
    matching the existing `test_check_conformance.py` convention).
  - `TestMigrationPipeline` (fix_indexes -> rebuild -> clean_orphans),
    now importing across both the new script module and the
    still-in-place `clean_orphans.py`.
  - New CLI/`main()` coverage: `--help` and missing-required-arg smoke
    tests via `subprocess`; `main()` unit tests for missing-source-dir,
    already-migrated (`database.bak` exists), successful
    migration+rename, failed migration (no rename, nonzero exit), and
    `--codernity-path`/`--sqlite-path` overrides.
- **`tests/unit/test_runner_migration.py`** (new): unit tests for
  `_resolve_migration_script()` and `_open_or_create_database()` with a
  mocked `subprocess.run` and a `MagicMock` db — covers opening an existing
  SQLite DB, fresh-DB creation, successful subprocess-based migration (exact
  `argv` assertion), migration-subprocess failure (raises, does **not**
  create/open a DB, leaves `database/` untouched), an already-migrated
  (`database.bak` present) skip case, a missing-script case, and a static
  source-text check that `runner.py` no longer references the CodernityDB
  migration chain or CodernityDB directly.
- **`tests/unit/test_clean_orphans.py`** (renamed from
  `test_migration_modules.py`): now scoped to only `clean_orphaned_movies()`
  tests, since that's the only module of the original three that stayed.
- **`tests/unit/test_database_class.py`**: `TestRebuildBucketsEdgeCases` and
  `TestFixIndexesEdgeCases` removed (relocated into
  `test_migrate_codernity_script.py`); `TestCleanOrphansEdgeCases` untouched.

## Verification

- `.venv/bin/python -m pytest tests/unit/ -q` — 831 passed.
- `.venv/bin/ruff check .` — clean.
- `.venv/bin/python -c "import couchpotato.runner"` — imports cleanly (with
  `libs/` on `sys.path`, as the real app always has it via
  `CouchPotato.py`); `runner.py`'s own source contains zero references to
  `core.migration.codernity_to_sqlite`, `core.migration.fix_indexes`,
  `core.migration.rebuild_buckets`, or `CodernityDB` (verified by a
  dedicated static-source test, since `CodernityDB` remains transitively
  importable overall via the unrelated `couchpotato/core/database.py`).
- `python scripts/migrate_codernity_to_sqlite.py --help` — runs standalone,
  exits 0.
