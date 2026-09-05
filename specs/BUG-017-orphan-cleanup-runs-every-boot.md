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
  run on every boot with no gate, but they are not the same shape as each
  other. Measured: `fix_profile_quality_order` is not destructive and is
  noise and waste, as originally stated. `fix_release_quality` OVERWRITES
  `quality` and `is_3d` on release documents on every boot whenever the
  guessed quality disagrees with the stored one
  (`fix_release_quality.py:81-85`), so a quality corrected by hand is
  silently reverted on the next restart. It converges within a boot and the
  value is derived metadata rather than a user record, so it sits in the
  "expensive to redo" tier of this project's data-risk ranking rather than
  "gone forever" -- but it is a low-severity overwrite to gate next, not
  mere noise. Recorded as debt, restated below.
- **Restoring the Passengers record.** Operational, done by hand from the
  verified backup after this ships, deliberately in that order so the final
  ungated run cannot delete it again.
- **A schema change.** The property store
  (`Env.prop`, `couchpotato/environment.py:79`, backed by `property` documents,
  1,139 already present in production) is the existing mechanism.

## Pre-deploy (required)

Production has never carried `migration.clean_orphans.applied`. Before this
release reaches production, the marker MUST be written to the production
database first, so the deploy itself is not one more ungated run of the
cleanup on a database that has never had one. See
`docs/development-process.md` for the read-only query that checks the
marker's current state, and how to set it.

**Standing operational rule:** the marker lives inside `couchpotato.db` as an
ordinary `property` document, not a separate file, so any restore of that
database -- including the disaster-recovery restore already documented for
this project -- resets it. A restored database runs the cleanup once more on
its next boot, gated exactly as if it were a fresh install.

## Acceptance criteria

- **AC-DATA-1:** `clean_orphaned_movies` does not run when the property
  `migration.clean_orphans.applied` is already set. Proven by driving the real
  startup path twice against a database holding an orphan-shaped record, and
  asserting the record survives the second run.
- **AC-DATA-2:** The marker is set after a completed run, including a run that
  removed nothing. A migration that finds nothing is still a migration that has
  run.
- **AC-DATA-3:** The marker is NOT set when an exception escapes the run --
  either the marker write itself raising, or (rare) an exception escaping
  `clean_orphaned_movies`. This only covers exceptions that actually escape:
  `clean_orphaned_movies` almost never lets one, because its own scan loop
  catches `Exception` internally, logs a warning on its own logger, and
  returns 0 (recorded as debt item 6 below). A failed migration must be
  allowed to retry rather than being silently skipped forever; in practice
  the retry is delivered by the marker write failing, not by the cleanup
  call failing.
- **AC-QA-4:** A test proves the guard is load-bearing: with the marker absent
  the orphan-shaped record is removed, with it present the same record survives.
  Both directions, same fixture, so the test cannot pass vacuously.
- **AC-OPS-5:** The startup log distinguishes "skipped, already applied" from
  "ran, removed N". An operator reading the log can tell which happened.
- **AC-SIMP-6:** The change is confined to `couchpotato/runner.py` and its
  tests. `clean_orphans.py` itself is not edited, so the gate cannot be confused
  with a behaviour change in the cleanup.
- **AC-DATA-7:** (fix round two, FIX A) An exception that escapes the marker
  READ (`Env.prop(ORPHAN_CLEANUP_MARKER)`) leaves the marker unset, logs the
  same "did not complete, will retry on next start" warning as any other
  failure in this function, and does NOT run `clean_orphaned_movies`. This
  supersedes fix round one's nested try/except, which treated a read failure
  as "not yet applied" and ran the cleanup anyway -- measured, against a
  marker that was genuinely already set, to run a completed destructive
  migration a second time with no warning logged at any level.
- **AC-QA-8:** (removal criterion, phrased to fail if it is not really gone)
  The nested try/except that used to sit around the marker read in
  `couchpotato/runner.py` is gone, and a marker read that raises results in
  zero records deleted and a warning logged, proven by driving
  `_run_orphan_cleanup` directly with the read patched to raise.
- **AC-QA-9:** (removal criterion) `test_docstring_mention_is_not_miscounted_as_a_call`
  no longer exists in `tests/unit/test_orphan_cleanup_call_site_guard.py`.

## Recorded debt, not fixed here

1. The orphan test reads only `info` and ignores the top-level `title`,
   `identifiers` and any landed release. Still wrong, now only reachable
   deliberately.
2. Child cleanup is swallowed by a bare `except`; production carries a release
   document pointing at a deleted media id, and the same is true of any earlier
   deletion.
3. `fix_release_quality` and `fix_profile_quality_order` scan the whole library
   on every boot with no gate. `fix_profile_quality_order` is noise;
   `fix_release_quality` also OVERWRITES `quality` and `is_3d` on release
   documents whenever the guessed quality disagrees with the stored one
   (`fix_release_quality.py:81-85`), silently reverting a hand-corrected
   quality on the next restart -- a low-severity overwrite to gate next,
   not mere noise.
4. Log retention on the production host is roughly two days, so it cannot be
   established whether this routine deleted anything before 2026-09-04.
5. Eleven film folders in the managed movie roots are referenced by no library
   record. Cause unknown and NOT attributed to this defect. Worth an audit on
   its own merits; one of them, Moana (2026), is on disk while the library is
   still actively searching for it.
6. A scan that fails completely inside `clean_orphaned_movies` is caught by
   its own `except Exception` (`clean_orphans.py:66-70`), logged as a warning
   on ITS OWN logger, and returns 0 -- which this gate then records as a
   completed migration that removed nothing. A failed scan is currently
   indistinguishable from a genuinely clean one.
7. `Settings.getProperty` (`couchpotato/core/settings.py:818`) swallows most
   read failures (any `db.get` exception other than a corrupt document) into
   a debug log and returns `None`, indistinguishable here from "never set".
   `_run_orphan_cleanup` cannot tell the two apart and still fails open on
   that path: it attempts the run. Fix round two (FIX A) closed the narrower
   case where the read raises and escapes `getProperty` entirely; this wider,
   swallowed case is untouched.
8. A failed marker WRITE does not always raise. `Settings.setProperty`
   (`couchpotato/core/settings.py:834-850`) wraps its `db.update` in a bare
   `except Exception:` and falls back to `db.insert` on any failure at all.
   Measured: with `db.update` raising `ConflictError`,
   `Env.prop(MARKER, value='true')` raised NOTHING, produced a second
   `property` row for the same identifier, and the marker still read back
   `None` afterwards. The same hazard is already documented for the session
   secret at `couchpotato/runner.py` around line 596.
