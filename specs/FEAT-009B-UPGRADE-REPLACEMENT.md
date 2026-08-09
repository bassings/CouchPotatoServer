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

Written by `/plan-cycle` on 2026-08-08. Lenses run: `lens-security`, `lens-qa`,
`lens-simplicity`, `lens-data`, `lens-operability`, `lens-architecture`.
Skipped: `lens-product` (no user-facing surface beyond one existing settings
entry, whose wording is covered by AC-SEC-2), `lens-design` and
`lens-accessibility` (no template, style or UI copy change).

Four decisions are **not** settled by these criteria and must be recorded in the
spec body by the owner before implementation starts: the shipped default of
`remove_lower_quality_copies` (AC-SEC-1 and AC-SEC-2 force fail-closed either
way), the renamer re-entrancy lock as a first sub-task (AC-DATA-13,
AC-ARCH-11), what "account for the old copy" means (AC-QA-27, AC-DATA-17,
AC-OPS-9), and the single source of truth for the quality of the file already on
disk (AC-DATA-5).

### lens-security

- **AC-SEC-1**: Replacement stays off on every install that existed before this change, regardless of the persisted setting; given a config.ini already containing `remove_lower_quality_copies = True`, a scan in which the incoming copy ranks strictly better leaves the destination byte-identical and the download in place, and enabling replacement requires an act taken after this change ships (a new option key, a migration that rewrites the persisted value, or a separate acknowledgement flag). Proof: executed unit test against a seeded config.ini on a real tmp filesystem.
- **AC-SEC-2**: Replacement is off by default on a fresh install (after `registerDefaults` against an empty config the value the renamer reads for its gate is falsy and a strictly better copy does not replace), and the option description states in plain words that the existing library file is deleted and cannot be recovered. Proof: executed unit test on `Settings.registerDefaults` plus a string assertion on the description.
- **AC-SEC-3**: A quality claimed only by a filename cannot authorise a deletion: replacement is refused when the incoming file's on-disk size falls outside the declared `size_min`..`size_max` band of the quality it is credited with, pinned in both directions (a 700 MB `Movie.Name.2019.2160p.UHD.BluRay.REMUX.HDR.x265-GRP.mkv` does not replace a 1080p library file; a 25 GB file with the same name does). Proof: executed unit test driving the real gate, both directions.
- **AC-SEC-4**: No file outside the library is ever a replacement target: before any destructive step the resolved destination (`os.path.realpath`) must be inside the resolved configured `to` root using `isSubFolder` (`couchpotato/core/helpers/variable.py:339`), and a media title of `/etc/cron.d` or `..` makes the renamer skip with nothing created, replaced or removed outside the root and the download intact. Proof: executed unit test with a crafted title on a real tmp filesystem.
- **AC-SEC-5**: One replacement removes at most one path and that path is the destination itself: with decoys present in the destination folder (another copy of the same movie under a different filename or extension, a `cd2` part of the old copy, a `.srt` and a `.nfo`) every decoy still exists unmodified after a successful replacement, and no sweep of other copies is performed. Proof: executed test asserting directory contents before and after. (Covers AC-QA-22, AC-DATA-11, AC-ARCH-9.)
- **AC-SEC-6**: Aliased paths are refused, not replaced: replacement is refused when source and destination are the same file (`os.path.samefile`, which includes the hardlink the shipping default `file_action = link` creates) and when the destination is a symbolic link (with the symlink's outside target still byte-identical afterwards); a broken symlink at the destination is a deliberate refusal, not an unnoticed overwrite. Proof: executed unit tests on a real tmp filesystem, hardlink case, symlink case and broken-symlink case. (Covers AC-QA-23, AC-QA-24; the refuse reading wins over "replace the link" by irrecoverable-loss precedence.)
- **AC-SEC-7**: The staging file is created in the destination directory under a name unique per attempt, carries no wider permissions than `Env.getPermission('file')`, is never left behind while the source file still exists, and is never deleted when it is the only complete copy (the source having been consumed by the move); each failure point is forced separately (size mismatch, `os.replace` failure, an exception between steps). Proof: executed unit tests, one per forced failure point, asserting on destination directory contents and on the survival of a complete copy.
- **AC-SEC-8**: Every completed replacement emits exactly one INFO record naming the destination, both quality identifiers and the deciding rank; every refusal emits an INFO or WARNING record naming the reason; all records go through the existing `CPLog` handlers (no `print`, no new sink) and after `PrivacyFilter.filter` no `/home/<name>` or `/Users/<name>` prefix and no `api_key=`, `password=` or `token=` value survives. Proof: executed unit test using caplog plus a direct call to `PrivacyFilter.filter` over the emitted records.
- **AC-SEC-9**: The quality attributed to the file being deleted is tied by evidence to that file (its recorded path after `sp()` normalisation and size, or the `copy_id` from FEAT-009 Part A); replacement is refused when no release can be tied to the file at the destination and when more than one release claims that path. Proof: executed unit test with two constructed release documents. (Covers AC-QA-8.)
- **AC-SEC-10**: The change adds no new attack surface: no new API view (the ranking primitive is an event or method only, so the registered api view names are unchanged), no new HTTP route, no new runtime dependency; and `renamer.scan`, which this change turns into a trigger for library deletion, returns 401 for a request carrying no valid api key, asserted by issuing the request rather than by reading the route. Proof: executed request against the app plus a diff assertion on the api view registry and requirements files.
- **AC-SEC-11**: The replacement decision depends only on the two files being compared: after a 3D release has been guessed in the same process (which leaves `is_3d = True` on the cached quality dict for that rung indefinitely), a comparison of two non-3D copies returns the same verdict as it does in a fresh process, because the 3D determination is taken from each file's own metadata rather than from a shared cached dict. Proof: executed unit test running the 3D guess first, then the comparison, in one process. (Amended: the "pass a profile" half is vetoed, see below; the profile guard is AC-QA-5 plus AC-SIMP-6.)
- **AC-SEC-12**: The change introduces no new persistent record of file paths, titles or sizes outside the existing database and the rotating log ring, and if a record of the replacement is written to the database then deleting the media removes it, asserted by querying for the record after `media.delete`. Proof: executed unit test plus a diff read for new files written outside the log ring and the DB.

### lens-qa

- **AC-QA-1**: A table test drives the ranking primitive over all twelve identifiers and pins the exact order 2160p, bd50, 1080p, 720p, brrip, dvdr, dvdrip, scr, r5, tc, ts, cam, including bd50 better than 1080p and brrip worse than 720p, with the expected order derived from `QualityPlugin.qualities` in the test so that adding a rung fails the test rather than silently shifting the ranking. Proof: unit. (Covers AC-DATA-1's pair table.)
- **AC-QA-2**: The ranking primitive returns None (not 0, not an exception) for an unknown identifier, an empty string, None, a non-string and a dict with no `identifier` key, asserted per input. Proof: unit.
- **AC-QA-3**: The is-better comparison returns False when either side ranks None, in both argument orders, and the caller degrades to today's skip-and-warn. Proof: unit.
- **AC-QA-4**: Regression pin for withdrawn attempt #1: incoming 720p against existing 2160p returns not-better, and the test name states this is the case measured to destroy a remux. Proof: unit.
- **AC-QA-5**: Regression pin for withdrawn attempt #2: the ranking code path fires no `profile.default` event and calls no `isHigher`, proven by counting calls on a monkeypatched `fireEvent` and `QualityPlugin.isHigher`, and incoming 720p against existing 2160p is not-better with the default `Best` profile seeded in the database. Proof: unit. (Amended: no profile argument is passed to the primitive, see the veto below.)
- **AC-QA-7**: Any difference in `is_3d` between incoming and existing returns not-better, in both directions and at two rung relationships (same rung, and the 3D copy at a worse rung), and equal rung with equal `is_3d` also returns not-better, so only a strictly better rung authorises replacement. Proof: unit.
- **AC-QA-9**: When two or more releases claim the destination path with different qualities, the renamer refuses, logs the ambiguity naming both release ids, and preserves both the library file and the download; `copy_id` is the discriminator, tested in the resolvable case (one release's `copy_id` matches the file on disk, so it wins) and the unresolvable case (neither or both match, so it refuses). Proof: unit.
- **AC-QA-10**: When no release claims the destination path (a manually placed file, or a file attached to a different media), the renamer refuses to replace and preserves both files: unknown never means replaceable. Proof: unit.
- **AC-QA-11**: The code records a distinguishable outcome per file (`replaced`, `declined_worse`, `declined_equal`, `declined_unknown_quality`, `declined_ambiguous_owner`, `declined_setting_off`, `failed`), every "no replacement happened" test asserts on that outcome value rather than only on file contents, and a test asserting `declined_worse` fails if the gate is made inert by removing the releases attachment. Proof: unit. (Covers AC-OPS-4, AC-DATA-4a.)
- **AC-QA-12** (amended during B4a review, see D9): When `release.for_media` returns an empty list, returns None, raises, or the media dict has no `_id`, the renamer refuses, does not propagate an exception out of `_moveRenamedFiles`, and leaves the library file and the download intact. The recorded outcome names the CAUSE and the four are distinct: `declined_no_owner` (empty list, or no `_id` -- nothing claims this destination), `declined_incomplete_evidence` (None -- a release document exists but could not be read), `declined_error` (raised). Proof: unit.
- **AC-QA-13**: When the incoming group's `meta_data['quality']` is missing, is None (reachable: `quality.guess` returns None at `quality/main.py:362` and `:373`) or lacks an `identifier`, the renamer refuses and does not raise; a test drives `_processGroup` with `{'meta_data': {'quality': None}}` and asserts no AttributeError escapes and no file is removed. Proof: unit.
- **AC-QA-14**: Happy path: with the setting on and a strictly better incoming copy, the destination holds the new bytes afterwards (asserted by SHA-256, not by mtime or size alone) and the outcome recorded is `replaced`. Proof: integration.
- **AC-QA-15**: Equal-rung and worse-rung incoming copies leave the destination byte-identical (SHA-256 before and after), leave the download present and suppress `cleanup`, tested as three cases: worse, equal rung with equal 3D, and better rung with mismatched 3D. Proof: integration.
- **AC-QA-16**: With `remove_lower_quality_copies` off, a strictly better incoming copy does not replace: destination byte-identical, download surviving, source folder not cleaned up, outcome `declined_setting_off`. Proof: integration.
- **AC-QA-17**: A simulated cross-device rename (monkeypatching `os.rename`/`os.replace` to raise `OSError(errno.EXDEV)` for any pair of paths whose dirnames differ) still completes the replacement, and that test fails if the temp file is created in the source directory. Proof: integration.
- **AC-QA-19**: Interruption before the atomic swap loses nothing: with the transfer forced to raise part-way, the destination is byte-identical, the download intact, the partial temp removed and the outcome `failed`, run for each `default_file_action` value (move, copy, link, symlink_reversed). Proof: integration.
- **AC-QA-20**: The size verification is real: a transfer that completes without raising but lands a shorter file at the temp path refuses the replacement, leaves the destination byte-identical, removes the temp and preserves the download, with the source size captured before the transfer so the check still works for `move` and `symlink_reversed`. Proof: integration. (Covers AC-DATA-9b.)
- **AC-QA-21**: A failing `os.replace` (monkeypatched `PermissionError`, the Windows open-destination case) leaves the destination byte-identical, removes the temp, preserves the download, records `failed` and suppresses cleanup for that group. Proof: integration. (Covers AC-DATA-9c.)
- **AC-QA-26**: A multi-file group is all-or-nothing: if the replacement of any one file is refused or fails, no file in that group is replaced, the source folder is not cleaned up, and a single warning names the group; a test with cd1 replaceable and cd2 failing asserts both library files byte-identical afterwards. DVD (`is_dvd`) groups are refused outright and fall through to today's skip. Proof: integration. (Covers AC-DATA-12, AC-ARCH-10.)
- **AC-QA-27**: After a successful replacement the release document that claimed the destination path no longer claims it, so a later `media.restatus` plus searcher pass does not treat the superseded rung as a copy still on disk, and a following `Release.add` for the new copy does not leave two done releases claiming the same file. This is the pin against the unbounded re-download loop that killed FEAT-009 designs #2 and #4. Proof: integration.
- **AC-QA-29**: The whole of `tests/unit/test_renamer_cleanup_safety.py` passes with its assertions unedited after the change, pinning the shipped safety half. Proof: unit.
- **AC-QA-31**: Every destructive-direction guard is proven load-bearing by a recorded mutation run per CLAUDE.md rule 10: for AC-QA-4, AC-QA-5, AC-QA-7, AC-QA-10, AC-QA-11, AC-QA-15, AC-QA-16, AC-QA-17, AC-QA-20, AC-QA-26, AC-QA-29, AC-SEC-5 and AC-SEC-9, plus the two whole-branch mutations (delete the replacement branch; force the gate to always refuse), the guard is removed or inverted, the named test observed to fail for the stated reason, the file restored, and the restoration confirmed byte-identical by hash, with the output pasted into the PR body. Proof: unit. (Covers AC-DATA-4b.)

### lens-simplicity

- **AC-SIMP-1**: No new configuration: the diff adds no new entry to the settings list in `renamer/api.py`, and the replacement path reads no renamer setting other than `remove_lower_quality_copies`, `cleanup`, `file_action` and `default_file_action`. Changing the default value of the existing entry, or replacing it with a single successor key required by AC-SEC-1, is permitted; adding a second key is not. Proof: grep the diff for added `'name':` entries and added `self.conf(` keys.
- **AC-SIMP-2**: No new dependency: `requirements.txt`, `pyproject.toml` and `package.json` are byte-identical before and after. Proof: `git diff --name-only`.
- **AC-SIMP-3**: No second quality ordering: production code added by the diff contains no new literal list, tuple or dict of quality identifiers; the rank derives from `QualityPlugin.qualities` or the existing `quality.order` event. Test tables that pin the order are exempt. Proof: grep the production diff for quality identifier literals outside `tests/`.
- **AC-SIMP-4**: No new public surface on the quality plugin: the diff adds no `addApiView` to `quality/main.py` and at most one `addEvent`, and if it adds one the same diff contains its production caller. Proof: grep the diff.
- **AC-SIMP-5**: The search path is untouched: `QualityPlugin.isHigher` is unchanged and no file under `couchpotato/core/media/movie/searcher/` is modified. Proof: `git diff`.
- **AC-SIMP-6**: The replacement decision is profile-free and guess-free: renamer code added by the diff contains no occurrence of `profile`, `isHigher`, `ishigher` or `quality.guess`. Proof: case-insensitive grep of the added lines.
- **AC-SIMP-7**: No new persistence and no backfill: the diff writes no new key into any release or media document, adds no file under `couchpotato/core/migration/` and adds no rescan-and-upgrade sweep over the existing library. Updating an existing field of an existing document, where AC-QA-27 or AC-DATA-17 requires it, is permitted. Proof: `git diff --name-only` plus grep of the diff for `db.update` / `db.insert` with new keys.
- **AC-SIMP-8**: Ambiguous ownership is refused, not inferred: when the destination path cannot be matched to exactly one release of this media from data already stored, control reaches the existing skip branch (`skipped = True`, no move, no delete), and a test proves the refusal is reached rather than never called. Proof: read the ownership branch plus the named test.
- **AC-SIMP-9**: No new file-transfer implementation: bytes reach the destination directory via `MoverMixin.moveFile`; the diff adds no `shutil.move`, `shutil.copy`, `shutil.copyfile`, `link(` or `symlink(` call outside `renamer/mover.py` and no new module for moving files, and the only new filesystem primitive in `renamer/main.py` is `os.replace` and its guards. Proof: grep the added lines per file. (Covers AC-ARCH-7.)
- **AC-SIMP-10**: Bounded blast radius: the production diff modifies at most `renamer/main.py`, `renamer/mover.py` and `quality/main.py`, plus a default change in `renamer/api.py`, plus `release/main.py` only where the AC-QA-27 / AC-DATA-17 bookkeeping decision requires it. `renamer/scanner.py`, `renamer/cleanup.py` and `couchpotato/core/media/**` are unchanged. Proof: `git diff --stat` restricted to `couchpotato/`.
- **AC-SIMP-11**: No quarantine, trash or undo mechanism: the diff adds no backup or set-aside copy of the destination file before replacing it, no directory or constant naming one, and no setting governing one. Refusal on doubt (AC-SIMP-8) plus the pre-destruction record (AC-OPS-2) is the safety mechanism. Proof: grep the diff for trash / backup / `.bak` / quarantine / set_aside identifiers and for any copy of `dst`.
- **AC-SIMP-12**: The shipped safety half is regression-pinned by tests only: the diff adds no new branch to the skipped / cleanup logic at `renamer/main.py:167-177`, and the replacement path signals a refusal by setting the existing `skipped` flag. Proof: read the diff of `_moveRenamedFiles`.
- **AC-SIMP-13**: No new test scaffolding: destructive-direction tests live in the existing `tests/unit/test_renamer_mover.py` and `tests/unit/test_renamer_cleanup_safety.py` (or one new sibling module under `tests/unit/`), use `tmp_path` and the helpers already there, and the diff adds no new `conftest.py` and no new mocking or filesystem-fake dependency. Proof: `git diff --name-only` under `tests/` plus AC-SIMP-2.

### lens-data

- **AC-DATA-2**: Replacement is authorised only on a strictly better rank: each of five inputs leaves the destination byte-identical (hash compared) after a full `_moveRenamedFiles` run against a real temp filesystem, namely equal rung, worse rung, unknown quality on the incoming side, unknown quality on the existing side, and same rung with `is_3d` differing. Asserting only on the comparator's return value does not satisfy this. Proof: end-to-end on `tmp_path`.
- **AC-DATA-3**: The releases attached at the call site belong to the group's own media: with two media documents in a real SQLite database differing only in imdb identifier and each holding a release at a different quality, the decision for movie A is unchanged by anything recorded against movie B, in both the replace and the refuse direction. A one-movie fixture does not satisfy this. Proof: integration against a real `SQLiteAdapter` database.
- **AC-DATA-5**: The quality of the copy on disk comes from one named source that the spec states, and the implementation reads only that source, proven by diverging the on-disk file from the release doc in both directions and asserting the documented source decides; when that source is absent (no release doc claims the destination path, or none records a quality) the replacement is refused with the destination byte-identical. Proof: end-to-end on `tmp_path` with a real release doc.
- **AC-DATA-6**: Replacement is refused unless the file at the destination is verifiably the copy the release doc describes: the recorded size (Part A's `copy_id`, `release/main.py:24-56`) must equal the actual size on disk, and a mismatch or an absent `copy_id` leaves the destination byte-identical and preserves the download. Proof: end-to-end with a hand-swapped destination file of the same path and a different size.
- **AC-DATA-7**: Replacement is refused for a group whose media identity was inferred by `folder_scanner.determineMedia`'s `movie.search` fallback rather than by a hard identity link (release_download imdb_id, a CP tag, an nfo imdb id, or an imdb id in the filename); a group whose only identity evidence is a fuzzy title match deletes nothing. Proof: end-to-end with a group built via the search fallback path.
- **AC-DATA-8**: The temporary file is created inside the destination directory and on the destination's filesystem, asserted at the moment it exists by `os.stat(tmp).st_dev == os.stat(os.path.dirname(dst)).st_dev` and `os.path.dirname(tmp) == os.path.dirname(dst)`, with a name unique per attempt whose extension is not in `FileDetectorMixin.extensions['movie']` so a crash orphan cannot be ingested as a movie. Proof: test intercepting the temp path mid-operation. (Covers AC-QA-18, AC-ARCH-8 first half, AC-OPS-5 first half.)
- **AC-DATA-10**: The old library file is destroyed only by the atomic `os.replace`, never by a prior removal: the replacement path contains no `os.remove`, `os.unlink`, `shutil.move` or `open(dst,'w')` targeting the destination, proven by patching `os.replace` to raise and asserting the original survives byte-identical, plus a source-level assertion over the replacement function. Proof: failure injection plus static assertion.
- **AC-DATA-13**: The renamer re-entrancy lock is in place before any replacement logic exists in the tree and is proven: two threads entering `renamer.scan` through a deliberately slowed transfer produce exactly one complete file at the destination, never a truncated, missing or mixed one, and the second entrant is refused rather than proceeding into the same destination. Asserting only on the current unlocked class attribute does not satisfy this. Proof: threaded test against a real filesystem. (Covers AC-QA-30. Required by `specs/REMEDIATION-2026-08.md:2496`.)
- **AC-DATA-14**: A source still being written never replaces a complete library file: the size of the incoming file at the moment of the move must equal the size recorded when the scanner measured it for quality detection, and a mismatch leaves the destination byte-identical and preserves the download. Proof: end-to-end test that appends to the source between the scan and the move.
- **AC-DATA-16**: With `remove_lower_quality_copies` off, the shipped safety half is unchanged (destination byte-identical, incoming file still in the download folder, source folder not deleted), and the same three assertions hold when the setting is on but the gate refuses and when any file in the group was skipped or failed. Proof: end-to-end tests extending `tests/unit/test_renamer_cleanup_safety.py`.
- **AC-DATA-17**: The database is left consistent with the disk after a replacement: following a successful replacement and a subsequent library rescan, exactly one release document lists the destination path, its quality is the incoming one, its `copy_id` equals the size of the file now on disk, and no document retains the replaced copy's `copy_id` against that path; if the process dies immediately after `os.replace` and before any bookkeeping, a later rescan reaches the same end state. Proof: integration against a real database, run once normally and once with the bookkeeping step killed.
- **AC-DATA-18**: Attaching releases at the call site does not persist them: after a renamer scan the stored media document contains no `releases`, `category` or `profile` key it did not have before, and its `_rev` is unchanged, read straight from the database rather than from the in-memory group. Proof: integration.
- **AC-DATA-19**: The change degrades safely on a pre-existing library: a release document with no `copy_id` (every document written before FEAT-009 Part A) never authorises a replacement, per AC-DATA-6, and the refusal is recorded with its own token per AC-OPS-3 so the field rate of that refusal is observable. Proof: integration on a copy of a production-shaped database. (Amended: the executed rollback run is vetoed, see below; rollback safety rests on AC-SIMP-7.)

### lens-operability

- **AC-OPS-1**: The armed state is visible before anything is deleted: at startup, or on the first scan after startup, exactly one record at INFO or above states the effective value of `renamer.remove_lower_quality_copies` and, when it is on, that the renamer may now delete an existing file from the library; a test asserts the state named in that record equals the value the replacement gate uses in the same run. A record emitted only at DEBUG fails this criterion, because `setup_logging(debug=False)` leaves the root logger at INFO. Proof: unit test with caplog against the real Renamer and a real settings object.
- **AC-OPS-2**: Every replacement is recorded on both sides of the irreversible step: one record at WARNING or above before it, naming the destination path, the existing quality identifier and byte size and the incoming quality identifier and byte size; one at INFO or above after it, naming the outcome and the media identifier; both carrying a stable greppable token that appears verbatim in the source. Proof: driving the replacement to success on a real tmp filesystem and asserting on the captured records. (Covers AC-DATA-20.)
- **AC-OPS-3**: Every way the gate declines is distinguishable from the log alone: each of setting off, no releases attached, unknown incoming quality, unknown existing quality, not strictly better, 3D mismatch, ambiguous owner, unverified `copy_id` and search-derived identity emits exactly one record at INFO or above with its own distinct greppable token naming the destination and both quality identifiers where known, and none of these paths is a bare `pass`, `continue` or `log.debug`. Proof: parametrised unit test, one case per decline reason, asserting all tokens differ.
- **AC-OPS-5**: A pre-existing staging leftover, of the kind a killed process leaves, is reported at WARNING with its path and byte size on the next scan rather than being ignored, and if a temp cannot be removed after a failure one record at WARNING names the leftover path and its size. Proof: unit test with a stale-temp fixture.
- **AC-OPS-6**: A situation that does not change between scans cannot evict the log ring: refusal and failure records from the new code go through `log_suppressed` (`couchpotato/core/logger.py:112`) keyed per destination path and reason, so 500 consecutive scans of the same unchanged group emit at most 10 records at INFO or above from the new code while the first record in each window still carries the full reason. Baseline: the existing skip warning measures 138 bytes per record against a 500,000 x 11 byte ring, which one refusal per minute exhausts in about 28 days. Proof: unit test looping the scan and counting records, both directions.
- **AC-OPS-7**: A failed replacement names the step and the operating-system reason: exactly one record at ERROR names which of the four steps failed, the source and destination paths, and for an `OSError` the errno and strerror, with injected `ENOSPC`, `EXDEV` and a permission failure each distinguishable from the others by reading the log alone, and no new failure path swallowing the exception into `pass` or `log.debug`. Proof: parametrised unit test injecting `OSError` at each step.
- **AC-OPS-8**: The operator kill switch is turning the setting off, taking effect on the next scan with no restart, proven by changing the stored setting between two runs in one test and observing the behaviour change; and the spec carries one plain sentence stating that neither the kill switch nor a code rollback restores a library file that has already been replaced. Proof: unit test plus the spec sentence. (Amended: the executed previous-release rollback run is vetoed, see below.)
- **AC-OPS-9**: The fate of the old copy is stated once, unambiguously, in three places: the spec (replacing "Only then account for the old copy"), a comment at the call site, and the AC-OPS-2 pre-record wording. Since AC-SIMP-11 forbids a set-aside, the statement is that `os.replace` destroys it and there is no undo. Proof: spec text plus the call-site comment in the diff.
- **AC-OPS-10**: A section under `docs/` answers three operator questions using the exact greppable tokens from AC-OPS-2, AC-OPS-3 and AC-OPS-7: why did my upgrade not land, what removed the file that used to be in my library, and what is this leftover temporary file in my library folder; it also names the kill switch from AC-OPS-8. Proof: the doc section, reviewed against the tokens in the diff. (Amended: the token-drift unit test is vetoed, see below.)
- **AC-OPS-11**: The replacement path leaves no silently broken link: it is exercised under each `default_file_action` value (move, copy, link, symlink_reversed), and in the symlink_reversed and hardlink-fallback cases the link left in the download folder after a successful replacement resolves via `os.path.realpath` to the final destination path, not to the temporary name that `os.replace` renamed away; any configuration the design cannot support refuses through its own AC-OPS-3 token rather than proceeding. Proof: parametrised test on a real tmp filesystem. (Covers AC-QA-25, AC-DATA-15.)

### lens-architecture

- **AC-ARCH-1**: The ranking primitive lives in `QualityPlugin` and is reached from the renamer only through the event system (registered in `QualityPlugin.__init__` alongside the existing `quality.*` registrations), and no module under `couchpotato/core/plugins/renamer/` imports `couchpotato.core.plugins.quality` or any other plugin's `main` module: production code today contains zero cross-plugin class imports and this change does not add the first one. Proof: grep plus a test asserting the event name is registered.
- **AC-ARCH-2**: The rank derives from the index of the identifier in the in-code `QualityPlugin.qualities` list and never from the persisted `order` field of a quality document, nor from `self.all()`'s merged docs, nor from any profile; a test seeding a quality database whose stored `order` values are reversed relative to the code list asserts the ranking answers are unchanged. Proof: test.
- **AC-ARCH-3**: `QualityPlugin.isHigher` is unchanged (no line of `quality/main.py:530-556` appears in the diff), its one production consumer `couchpotato/core/media/movie/searcher.py:301` is unchanged, and no file under `couchpotato/core/plugins/renamer/` fires or references `quality.ishigher`. Proof: `git diff` plus grep. (Covers AC-QA-6.)
- **AC-ARCH-4**: Every comparability rule (unknown quality on either side refuses; 3D versus non-3D refuses) is decided inside the quality-side comparison function, not at the renamer call site: the renamer contains zero quality identifier string literals and no branch on `is_3d` (passing whole quality records through to the comparison is permitted), and the renamer's replacement decision is a single call to one comparison helper. Proof: grep the renamer package plus reading the single decision expression.
- **AC-ARCH-5**: Releases are obtained in the renamer by firing the existing `release.for_media` event immediately before the move, `couchpotato/core/plugins/scanner/` is unchanged, and a counting stub asserts `scanner.scan` (shared with `manage.py:158`, the whole-library scan) issues zero release lookups while the renamer path issues at most one per group and none per file. Proof: test plus `git diff` of the scanner package. (Covers AC-QA-28's work bound.)
- **AC-ARCH-6**: `remove_lower_quality_copies` (or its AC-SEC-1 successor key) is read at exactly one place in the codebase, through `self.conf(...)`, not via `Env.setting`, not re-read inside a helper and not passed around as a duplicate boolean. Proof: grep.
- **AC-ARCH-8**: A stale staging file left in the library folder does not block a subsequent replacement attempt for ever: it is reclaimed or a fresh name is used, rather than being refused permanently by `moveFile`'s `lexists` guard (`mover.py:68`). Proof: test with a colliding stale temp in place.
- **AC-ARCH-11**: The re-entrancy guard is a real lock rather than the unlocked class-attribute check-then-set at `renamer/main.py:22-23,72-79`, and it uses a mechanism already in the codebase: `couchpotato.core.media_lock.media_lock` or an instance lock created in `registerPlugin`, explicitly not `Plugin.acquireLock` (whose lock-map creation is itself unguarded, `base.py:393-399`) and not a newly invented utility. Proof: test plus reading which mechanism was chosen.
- **AC-ARCH-12**: The shipped default of the gate setting is pinned by a test in `tests/unit/`, asserting the value declared in `renamer/api.py`, so the value that decides whether deletion is on for every existing install at upgrade cannot drift silently. Proof: test.
- **AC-ARCH-13**: No document in the repository still asserts that replacement is unimplemented once it ships: the `STATUS: NOT IMPLEMENTED` block in `specs/FEAT-009-durable-set-aside-and-upgrade-replacement.md:82-109` is retired, and `_moveRenamedFiles`'s docstring, which currently states that replacement "was removed", describes what the function now does. Proof: grep `specs/` for "NOT IMPLEMENTED" plus reading the docstring in the diff.

### Vetoed at planning

`lens-simplicity` holds a veto at planning over requirements not traceable to
the spec's stated goal. It cannot override irrecoverable data loss, security or
the accessibility floor, so nothing in AC-SEC-*, and nothing guarding an
irreversible deletion, was dropped.

1. **The "pass a profile and assert no behaviour change" test** (spec lines 103-106, AC-QA-5 as first written, AC-DATA-1's three-profile matrix, AC-SEC-11(a)). Dropped: the ranking primitive takes no profile argument, so the test is unwritable without adding an unused parameter, which invites the coupling the test exists to prevent. Replaced by AC-QA-5 (no `profile.default` event fired, `isHigher` never called, counted on monkeypatched callables) and AC-SIMP-6 (the word `profile` does not appear in the added renamer code). The behavioural half, default-`Best` profile seeded and 720p still not better than 2160p, is retained in AC-QA-5.
2. **AC-OPS-1's six-value stored-setting matrix** (`{absent, '', '0', '1', 'True', 'False'}`). Dropped: it exercises `Settings._coerce_value`, which is pre-existing and untouched by this change. The load-bearing half, that the announced state equals the state the gate uses in the same run, is retained.
3. **The executed rollback run** (AC-OPS-8(b), AC-DATA-19(b)): starting the previously released image against a data directory written by this change and recording its duration in the spec. Dropped: AC-SIMP-7 already forbids any new key, schema or document type, which makes the rollback a no-op by construction; an image-level execution is out of proportion for a change that persists nothing new. The kill switch (AC-OPS-8) and the no-undo sentence are retained.
4. **AC-OPS-10's unit test asserting every runbook token appears verbatim in the source.** Dropped under AC-SIMP-13 (no new test scaffolding): it is drift protection for a document that does not exist yet, and the tokens are already pinned by AC-OPS-2, AC-OPS-3 and AC-OPS-7. The runbook section itself is retained.
5. **AC-QA-28's 15-second wall-clock budget** for the affected unit files. Dropped: `lens-qa`'s own coverage records that no renamer scan baseline exists, so the threshold is invented and would flake. The work bound (at most one release lookup per group, none per file) is retained in AC-ARCH-5.
6. **Any quarantine, trash or set-aside of the replaced file** (the set-aside branch of AC-OPS-9, and the recoverability option `lens-data` asked to be decided). AC-SIMP-11 is sustained: the accepted substitute is refusal on doubt (AC-SIMP-8, AC-SEC-9) plus the pre-destruction record (AC-OPS-2). This stands only because `lens-data` raised recoverability as a decision to record rather than a mechanism to build; a mechanism requirement from `lens-data` or `lens-security` would override the veto.

Merged rather than vetoed, with both IDs kept in the surviving line:
AC-QA-6 into AC-ARCH-3; AC-QA-8 into AC-SEC-9; AC-QA-18 into AC-DATA-8;
AC-QA-22, AC-DATA-11 and AC-ARCH-9 into AC-SEC-5; AC-QA-23 and AC-QA-24 into
AC-SEC-6; AC-QA-25 and AC-DATA-15 into AC-OPS-11; AC-QA-28 into AC-ARCH-5;
AC-QA-30 into AC-DATA-13; AC-DATA-1 into AC-QA-1 and AC-QA-5; AC-DATA-4 into
AC-QA-11 and AC-QA-31; AC-DATA-9 into AC-QA-19, AC-QA-20 and AC-QA-21;
AC-DATA-12 and AC-ARCH-10 into AC-QA-26; AC-DATA-20 into AC-OPS-2; AC-OPS-4
into AC-QA-11; AC-ARCH-7 into AC-SIMP-9.

One conflict was resolved by precedence rather than by merging: AC-SEC-6
(refuse when the destination is a symbolic link) beats AC-QA-23 as first
written (replace the link without following it), because irrecoverable loss
outranks feature completeness and a symlinked destination is exactly the case
where the file that would be lost is not the one the library thinks it is.

---

## Decisions taken after planning, each verified against the repo

The planning cycle returned six defects that acceptance criteria alone could not
fix. These are the answers, with their evidence, settled before any code.

### D1 — ships behind a NEW key, defaulting off (owner decision 2026-08-08)

`remove_lower_quality_copies` has been declared `'default': True`
(`renamer/api.py:135`) for the life of the fork while being read by nothing, and
`setDefault` writes only when the option is ABSENT (`settings.py:396`) — so
`True` is already persisted into real config files, measured at
`.config/config.ini:151`. Wiring the existing key up would begin deleting
library files on the first scan after upgrade, on every install including
production, with no operator action. Both withdrawn attempts' failure mode,
arriving through a different door.

**Decision: a new option key that defaults to off.** The stale `True` can then
never activate anything, because the new code does not read that key. The old
key is ignored. Its presence should be logged once so an operator who set it
deliberately learns it no longer does anything — **and that clause is NOT yet
implemented.** It belongs where the new key is read, which is the wiring step
(B4), not in the pure decision layer. Review caught the gap between this
paragraph and the code, so it is recorded here rather than left to be
discovered: B4 does not ship without it.

### D2 — the on-disk quality comes from the RELEASE DOC, never `quality.guess`

The spec never named the right operand of "ranks strictly better", and the
tempting answer is dangerous: the default naming template carries no quality
token, so `quality.guess` on a renamed library file collapses to size and rates
a 2160p remux as `brrip`.

There is an authoritative source. A release document records
`'quality': <identifier>` and `'is_3d'` at creation (`release/main.py:281-282`)
from the scanner's `group['meta_data']['quality']` — a recorded fact about the
file, not a re-guess of it.

**Resolve the destination path to the release that owns it and read that
release's `quality`. If no release owns the path, or it carries no quality
identifier, REFUSE.**

### D3 — "account for the old copy" means moving the old release off `done`

`os.replace` has already destroyed the old file by that step, so the phrase can
only mean a database change, and none was described. Leaving the old rung's
release at `status: done` while it still claims the path is what produced the
unbounded re-download loop in FEAT-009 designs #2 and #4: `Release.add` keys on
`<imdb>.<audio>.<quality>` (`release/main.py:222`) and would create a second
`done` release beside it.

### D4 — B0: the re-entrancy lock lands FIRST, as its own change

`REMEDIATION-2026-08.md:2496` records this as a prerequisite that must land
before any replacement logic; extracting this spec lost it. Verified still
absent: `renaming_started` is an unlocked class-attribute check-then-set
(`renamer/main.py:22,72,79,109`), so two concurrent scans can both pass the
check and run the renamer at once — on the code path that deletes files.

`couchpotato/core/media_lock.py` already provides a reference-counted per-key
reentrant lock, already used by `release/main.py:218`; the renamer does not
import it. **Use that, not `Plugin.acquireLock`, which the architecture lens
flagged as itself racy.**

### D5 — path ownership is path-THEN-size, corrected 2026-08-09

**This decision was wrong as first written and is corrected here rather than
quietly patched, because B2 was about to be built on it.** It said release
documents carry `copy_id` "not a file list". They carry both:

  - `release['files']` — a bucket→paths dict, written unconditionally on the
    scan path (`release/main.py:314`);
  - `release['copy_id']` — a SIZE-derived identity, written only when
    computable (`copyIdentity`, `release/main.py:24-56`, which returns None if
    a file cannot be stat'ed).

So resolving the owner is two steps, which is what AC-SEC-9 actually describes
("its recorded path after `sp()` normalisation and size, OR the `copy_id`"):

1. **Candidates by path.** Releases whose `files['movie']` contains the
   destination after `sp()` normalisation.
2. **Disambiguate by size.** Path alone is not enough and the reason is
   recorded in `copyIdentity`'s own docstring: the default template is
   `<namethe> (<year>)/<thename><cd>.<ext>` with no quality or group token, so
   **every copy of a movie renames to the same path**. When more than one
   release claims it, the one whose `copy_id` matches the file actually on disk
   wins.

**Refuse on any residue**: no candidate, several candidates none of which match
by size, several that all match, or a candidate with no `copy_id` at all.
Unknown never means replaceable — that ambiguity is how the wrong file gets
deleted.

### D6 — sub-tasks renumbered B0–B4

`T5.4` named path ownership here and the re-entrancy lock in
`REMEDIATION-2026-08.md:2163`; that collision is how D4 went missing. Now
B0 (lock), B1 (ranking), B2 (attach releases), B3 (atomic replacement),
B4 (path ownership).

Two smaller corrections: the likely-touched-paths list named
`couchpotato/core/plugins/renamer/test_*.py`, which do not exist — all three
test files live in `tests/unit/`; and `quality/main.py` was missing from
FEAT-009's affected-files table although B1 necessarily changes it.

### D7 — replacement is refused for multi-file groups (raised in B0's review)

Review found the criteria **mutually unsatisfiable**, and it is a live case:
`renamer/main.py:251` sets `replacements['cd'] = ' cd%d' % (idx + 1)`, so a
group really can carry cd1 and cd2, and `_moveRenamedFiles` iterates
`rename_files.items()`.

If cd1's `os.replace` commits and cd2's then fails — a permission change, a
mount interruption — cd1's old bytes are already irrecoverable. AC-SIMP-11
forbids a set-aside, so **no implementation could honour "both library files
remain byte-identical"**. Preflight cannot close it: the failure is at the
second swap.

**Decision: refuse replacement for any group containing more than one video
file.** Single-file groups only, declined with an explicit outcome and a log
line naming why.

Chosen as a subtraction rather than the retain-until-all-commit alternative,
which would mean holding a full second copy of a multi-GB group on the delete
path and inventing a new failure mode to guard the first one. Multi-part movies
simply do not get upgrade-replacement. One swap, atomic by construction,
nothing to roll back.

### D8 — the replacement log records an IDENTIFIER, never the destination path

AC-SEC-8 as written requires every irreversible replacement to log the
destination path. Review showed I had over-trusted `PrivacyFilter`: its
`_HOME_PREFIX_RE` rewrites only the `/home/<name>` or `/Users/<name>` prefix,
so `/home/alice/Media/Movies/Title.mkv` reaches the rotating ring and
`docker logs` as `<home>/Media/Movies/Title.mkv` — still carrying library
layout and title. On a record that fires for every deletion, that is a viewing
history written to disk.

**AC-SEC-8 is amended before B3: the operator-facing record identifies the
media by its existing identifier (imdb id / media `_id`) and names both quality
identifiers and the deciding rank — not the raw path.** Whoever is diagnosing a
bad replacement needs to know which movie and which two rungs; the path adds
nothing they cannot get from the database with the id.

The general tension worth stating: the more useful a log line is for post-hoc
diagnosis of an irreversible delete, the more it leaks. The identifier keeps
the diagnosis and drops the leak.

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

### D9: a refusal names its cause (amends AC-QA-12)

AC-QA-12 as written required a single outcome, `declined_unknown_quality`, for
three unrelated causes. That is wrong, and the review that caught it was right:
the outcome string is the only thing an operator sees in the log when a
replacement does not happen, and the three causes send them to different
places. "Nothing claims this destination" is a library question. "A release
document could not be read" is a database question. "The lookup raised" is an
availability question. Collapsing them into one word means the log records that
something was refused without recording anything useful about why, and the
first person to debug it has to reproduce the failure to learn what the code
already knew.

`declined_unknown_quality` is retained for its actual meaning -- the quality
identifier is not on the ranking ladder -- which is a fourth, genuinely
different cause.

This is a spec bug, not an implementation deviation: the AC was under-specified
and the implementation was more correct than the criterion it was written
against.
