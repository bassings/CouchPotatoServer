# BUG-017: the orphan cleanup is a one-time migration that never stopped running

**Status:** agreed
**Reported:** 2026-09-04, from a production deploy of v3.76.0
**Severity:** data loss, recoverable tier. A library record is destroyed; the
media file is not touched.

## What happened

Restarting production removed "Passengers" (2016, tt1355644) from a library of
1,084 films. The 9.9 GB file is untouched on disk. What was destroyed is the
record that the library owns it.

Measured on the production host, against a backup taken minutes before the
restart:

    documents          4329 -> 4328
    media_identifiers  1097 -> 1096
    media status=done  1084 -> 1083

The deleted record was not metadata-less in any ordinary sense. It carried
`"title": "Passengers"`, `identifiers: {"imdb": "tt1355644"}`, a cached poster,
and a `release` document with status `done` pointing at the real file. Only its
`info` sub-document was empty, and `info` is the only thing the check reads.

## Root cause

`couchpotato/core/migration/clean_orphans.py` classifies a movie as an orphan
from `info.titles`, `info.original_title`, `info.year` and `info.plot` alone. It
never reads the document's own top-level `title`, its `identifiers`, or whether
any release points at a file on disk.

`couchpotato/runner.py:475` calls it on every startup, unconditionally, outside
any migration gate. The commit that introduced it (b40e433f5, 2026-02-11, two
days after the SQLite adapter landed) describes it as running "as part of the
upgrade process", but no upgrade check was ever written.

Two further facts establish that it is finished work:

- Roughly half the module decodes Python 2 `bytes` values. That branch is now
  unreachable: records are read through `json.loads`
  (`couchpotato/core/db/sqlite_adapter.py:386`), which only ever yields `str`.
- Its stated purpose, sweeping records broken by the CodernityDB to SQLite
  conversion, completed in February 2026.

It also cleans up incompletely. After deleting the media document it attempts to
delete child records inside `except (RecordNotFound, Exception): pass`. On
production the release document survived and still references the deleted
media id; two documents reference an id that no longer exists.

## Owner decision

2026-09-04: keep the cleanup as a migration, stop it running on every startup.
Quoted, because it sets the scope: "as long as this clean up runs as part of the
migration script, we don't need to run it on every start up".

## Scope

Gate the cleanup so it runs once and records that it has run. Nothing else.

## Not in scope

- **Rewriting the orphan test itself.** Once it stops running on every boot, a
  wrong answer is only reachable by a deliberate one-time migration on a
  database that has never had one. Correcting the check is a separate, smaller
  risk and is recorded as debt below rather than bundled here.
- **The other two boot-time routines.** `fix_release_quality` (which reports
  "Found 1268 releases to check" on every start) and `fix_profile_quality_order`
  have the same shape. They are not destructive, so they are noise and waste
  rather than risk. Recorded as debt.
- **Restoring the Passengers record.** Operational, done by hand from the
  verified backup after this ships, deliberately in that order so the final
  ungated run cannot delete it again.
- **A schema change.** The property store
  (`Env.prop`, `couchpotato/environment.py:79`, backed by `property` documents,
  1,139 already present in production) is the existing mechanism.

## Acceptance criteria

- **AC-DATA-1:** `clean_orphaned_movies` does not run when the property
  `migration.clean_orphans.applied` is already set. Proven by driving the real
  startup path twice against a database holding an orphan-shaped record, and
  asserting the record survives the second run.
- **AC-DATA-2:** The marker is set after a completed run, including a run that
  removed nothing. A migration that finds nothing is still a migration that has
  run.
- **AC-DATA-3:** The marker is NOT set when the cleanup raises. A failed
  migration must be allowed to retry rather than being silently skipped forever.
- **AC-QA-4:** A test proves the guard is load-bearing: with the marker absent
  the orphan-shaped record is removed, with it present the same record survives.
  Both directions, same fixture, so the test cannot pass vacuously.
- **AC-OPS-5:** The startup log distinguishes "skipped, already applied" from
  "ran, removed N". An operator reading the log can tell which happened.
- **AC-SIMP-6:** The change is confined to `couchpotato/runner.py` and its
  tests. `clean_orphans.py` itself is not edited, so the gate cannot be confused
  with a behaviour change in the cleanup.

## Recorded debt, not fixed here

1. The orphan test reads only `info` and ignores the top-level `title`,
   `identifiers` and any landed release. Still wrong, now only reachable
   deliberately.
2. Child cleanup is swallowed by a bare `except`; production carries a release
   document pointing at a deleted media id, and the same is true of any earlier
   deletion.
3. `fix_release_quality` and `fix_profile_quality_order` scan the whole library
   on every boot with no gate.
4. Log retention on the production host is roughly two days, so it cannot be
   established whether this routine deleted anything before 2026-09-04.
5. Eleven film folders in the managed movie roots are referenced by no library
   record. Cause unknown and NOT attributed to this defect. Worth an audit on
   its own merits; one of them, Moana (2026), is on disk while the library is
   still actively searching for it.
