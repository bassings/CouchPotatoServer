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

Synthesised from six planning lenses (security, qa, simplicity, product, data,
operability) at HEAD `742e35a6`. Three decisions the lenses flagged as open are
settled here and are binding on the implementation:

1. **The skip lives entirely in `Renamer`**, and is evaluated in
   `Renamer.scan` *before* `fireEvent('scanner.scan', ...)` (`main.py:120`),
   keyed on a cheap read of names, sizes and mtimes plus the remembered
   destinations and the settings that feed the decision. `folder_scanner.py`
   is not touched: it is shared with `manage.updateLibrary`, whose cleanup
   deletes any `done` movie absent from the scan result
   (`manage.py:274-275`), which is the one irrecoverable loss in this codebase.
2. **Nothing is persisted.** The "Persist decisions across restarts" row in
   Vetoes and trade-offs is closed as rejected.
3. **The out-of-band surface is one `fireEvent('notify', ...)` per parked
   group**, using the existing durable notification document and the existing
   `notification.list` API. No new route, no new template, no new setting.

### lens-security

- **AC-SEC-1:** The change adds no unauthenticated surface: the diff registers no new `@app.get`, `@app.post` or `APIRouter` route (proven by grep of the diff), and if one is added despite that it goes through `addApiView` (the api_key gate at `couchpotato/__init__.py:1174-1193`) or a router carrying `require_auth` (`:1160`), proven by an executed request with no `X-Api-Key` header and no session cookie asserting 401 for an API route or a redirect to `/login/` for a UI route.
- **AC-SEC-5:** Nothing is written outside the process, so rollback is a plain image revert with no migration, backfill or downgrade step: after a scan that parks at least one group, a recursive listing of the data directory, the download folder and the library folder is identical to the listing taken before it, the SQLite database gains no document type, table, row or settings property attributable to the memory, and a freshly constructed `Renamer` re-decides the same group and re-emits the AC-QA-1 record. (Merges AC-QA-8, AC-DATA-10, AC-OPS-11; the diff-level half is AC-SIMP-5.)
- **AC-SEC-6:** No filesystem path escapes at INFO or above: with `caplog` at INFO, every record this change emits (the first refusal, the bounded restatement of AC-OPS-4, each invalidation record of AC-OPS-7 and the failure record of AC-QA-14) contains neither the source nor the destination absolute path, matching the rule already held at `main.py:315-320` and by `tests/unit/test_replacement_end_to_end.py::test_no_destination_path_reaches_the_log`; paths appear only at DEBUG, and the assertion is made against the whole record, not against a substring that would match either way.
- **AC-SEC-7:** No surface names a film the system no longer holds: a remembered entry whose source file no longer exists, or whose media id no longer resolves, is dropped on the next scan and is named by no subsequent record and by no read of the parked list, proven by park, delete, rescan, read.
- **AC-SEC-8:** The out-of-band signal carries no absolute filesystem path and does not repeat: across 1,100 simulated scans of one unchanged parked group `notify` fires exactly once, and its rendered message matches no token beginning `/` other than a bare separator, so a film title reaches the configured third-party providers and the 28-day `notification` row (`couchpotato/core/notifications/core/main.py:42`, `:78-83`) once per park rather than once per scan.

### lens-qa

- **AC-QA-1:** The first refusal is unchanged: for a colliding destination whose decision refuses, scan 1 still emits the existing record at WARNING naming the media id and the outcome value (for example `declined_unverified_identity`), and every silence criterion below asserts this positive control in the same test so that "nothing was logged" can never pass because the code was never reached. A record emitted only at DEBUG fails this criterion, because `setup_logging(debug=False)` leaves the root logger at INFO (`couchpotato/core/logger.py:421`). (Merges AC-OPS-2.)
- **AC-QA-3:** The decision is computed once, not merely logged once: across ten consecutive scans of an unchanged parked group, `release.for_media` fires at most once and `decide_replacement` is entered at most once. Measured baseline on this branch: one `release.for_media` per scan, five lookups for five cycles.
- **AC-QA-4:** The third-party lookup is paid once: across ten consecutive scans of an unchanged folder whose group resolves through the title-and-year search fallback, `movie.search` and `movie.info` each fire at most once in total. Measured baseline: ten of each for ten scans, all paid inside `folder_scanner.determineMedia` before the renamer sees the group, which is why the skip is evaluated before `fireEvent('scanner.scan', ...)`. (Merges AC-PROD-2.)
- **AC-QA-5:** A changed source forces a re-decide and a fresh refusal record, parameterised over (a) the size changing and (b) the mtime changing while the size is identical, using `st_mtime_ns` precision so a same-second rewrite is still detected.
- **AC-QA-6:** A changed destination forces a re-decide, parameterised over (a) the destination file deleted, which is the operator's remedy and must file the download on the next scheduled scan with no restart, (b) the destination replaced in place at the same path with different bytes or size, and (c) a destination that did not exist and now does; asserted on the bytes at the destination, not on a return value. This carries FEAT-011's cross-spec note (`specs/FEAT-011-replace-with-this-file.md:224`): a completed operator replacement is an input change that must expire any remembered decision for that media.
- **AC-QA-7:** A change to any setting that feeds the decision forces a re-decide without a restart, parameterised over at least `upgrade_replace` off to on, `to` (the library root), `folder_name`, `file_name`, and the `size_min` band of the incoming quality rung, which is edited through the quality documents rather than `config.ini`. (Merges AC-DATA-6.)
- **AC-QA-9:** The spec's remembered set is enumerated and each member is exercised by name: only outcomes whose cause cannot change without a filesystem or settings change are remembered (`declined_setting_off`, `declined_unverified_identity`, `declined_multi_file_group`, `declined_outside_library`, `declined_size_contradicts_quality`); `declined_error`, `declined_incomplete_evidence` and every outcome derived from release documents (`declined_not_better`, `declined_no_owner`, `declined_unknown_quality`) are re-decided on every scan, and a group whose processing raised anywhere in the scan loop (`main.py:129-133`) is never recorded. Parameterised over the outcome constants imported from `renamer/replacement.py`, never over raw strings. (Merges AC-DATA-7, AC-OPS-9.)
- **AC-QA-10:** A scan the operator asked for ignores and clears the memory for the groups it covers: `renamer.scan` through `scanView` (with and without `base_folder` / `media_folder`) and a scan carrying a `release_download` each re-decide a parked group and emit the AC-OPS-7 "operator forced" record, while the scheduled scan is unaffected. This is the feature's kill switch: one API call restores the previous behaviour for the affected group without restarting the container. (Merges AC-DATA-12, AC-OPS-10.)
- **AC-QA-11:** A group parked as `declined_unverified_identity` from a generic scan is re-decided when the same source is next scanned with an asserted identity (`identity_source` in `download_id`, `cp_tag`, `nfo`, `filename`), because the decision's inputs changed even though the file did not.
- **AC-QA-12:** "Already decided" never becomes "already done": across ten parked scans the source file's bytes are unchanged and its folder still exists, `deleteFolder` and cleanup are never called, and zero `release.update_status`, `release.detach_file`, `release.clean`, `media.delete`, `media.update` and `download.process_complete` events are fired as a consequence of the skip, asserted on disk contents and on the recorded event list. (Merges AC-DATA-9, AC-PROD-5.)
- **AC-QA-14:** Unreadable state fails open, never into a permanent skip: when stat-ing the source or destination raises `OSError` (permission denied, NAS unmounted), when a settings read raises, when `release.for_media` returns the incomplete-evidence sentinel, or when the path carries a lone surrogate, the scan re-decides that group, raises nothing, records no entry that would outlive the outage, and emits one WARNING through `logger.without_paths` rate-limited by `log_suppressed`. "Could not measure" is never treated as "unchanged". (Merges AC-DATA-8, AC-OPS-8.)
- **AC-QA-18:** Every guard is proven load-bearing by mutation: removing the memory lookup makes the AC-QA-3, AC-QA-4 and AC-OPS-3 tests fail, and restoring it makes them pass, with the file hash recorded before the break and after the restore to prove the edit landed where intended and the file is byte-identical afterwards. Restore by file copy, never `git checkout --`. Result pasted into the PR, not summarised.
- **AC-QA-19:** The new tests are deterministic and leak no instance or class-level state: the new module passes when run twice inside one pytest session and when run alone, and any store held on the `Renamer` instance or class is reset by a fixture rather than by test ordering.

### lens-simplicity

- **AC-SIMP-1:** `couchpotato/core/plugins/renamer/replacement.py` has an empty diff against `master`, and the branch adds no new replacement-outcome constant anywhere. Remembering a decision is not making a new one.
- **AC-SIMP-2:** `couchpotato/core/plugins/scanner/folder_scanner.py` has an empty diff against `master`. This is the data-loss guard as well as a scope bound: the module is shared with `manage.py:158` and `manage.py:403`, whose cleanup at `manage.py:274-275` deletes any `done` movie absent from the scan result. A renamer refusal must never be able to alter what a library scan sees.
- **AC-SIMP-3:** All production changes are confined to `couchpotato/core/plugins/renamer/main.py`, and the branch adds no new file under `couchpotato/`. No new class, module, registry or injectable store is introduced for the memory; it is plain attributes and methods on `Renamer`.
- **AC-SIMP-4:** No new configuration option: the diff of `couchpotato/core/plugins/renamer/api.py` adds no `'name':` entry to the `config` list, and the branch reads no `self.conf('<name>')` that was not already registered before this change.
- **AC-SIMP-5:** The remembered decisions are process-local only: the branch adds no database document, index, table or migration, writes no state file, and passes the memory through neither `get_db()` nor `Env`. A restart re-decides because there is nothing to survive it.
- **AC-SIMP-6:** Invalidation is one comparison, not a mechanism: the branch adds no `addEvent` subscription, no `schedule.interval` registration, and no timer, TTL or expiry constant for the memory itself. A remembered decision is re-used only when a key recomputed from the current inputs equals the stored key; any difference re-decides. The restatement window of AC-OPS-4 is exempt: it bounds a log record, not the memory, and is the `window=` argument of the existing `log_suppressed`.
- **AC-SIMP-7:** No new dependency: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml` and `package.json` are unchanged.
- **AC-SIMP-8:** No new operator surface: the branch adds no `addApiView(` call, no file under `couchpotato/ui/` or `couchpotato/static/`, and no notification provider. The parked refusal is signalled by a single `fireEvent('notify', ...)`, listable through the existing `notification.list` API.
- **AC-SIMP-9:** No new "done" state: the branch introduces no new release status string and no new release tag value, and the remembered-skip path contains no call to `release.update_status`, `tagRelease` or `deleteFolder`.
- **AC-SIMP-10:** Proportionality bound: `git diff master...HEAD --numstat` shows no more than 150 added lines outside `tests/`, and at most one new test file.
- **AC-SIMP-11:** No bespoke log de-duplication: any bounding of a repeated record uses the existing `couchpotato.core.logger.log_suppressed` (already imported at `main.py:11` and used at `:463` and `:965`). The branch adds no new suppression, throttle or repeat-counter helper.

### lens-product

- **AC-PROD-4:** An operator who fixes the cause never has to know the memory exists: for each invalidation trigger (source size or mtime, destination appearing, disappearing or changing in place, a setting that feeds the decision, an explicitly requested scan, a process restart) the next scan re-decides and acts on the new answer, with no cache-clearing step, no new command, no new setting and no manual file move required.
- **AC-PROD-6:** No replacement decision changes: for every outcome reachable through `_moveRenamedFiles` (the `REPLACE` and `DECLINED_*` constants at `replacement.py:44-81`), the first decision under the change equals the decision the current code returns for identical inputs, and no library or download file is created, moved or deleted on any repeat scan, proven by a table-driven comparison over the outcome set plus a hash of both directory trees taken before the first scan and after the twentieth.
- **AC-PROD-7:** The fix reaches everyone with the symptom, not only the reported case: with `default_file_action` set to `link` or `copy` and `cleanup` off, the settings under which a correctly filed download stays in the folder and re-collides on every scan (`mover.py:71-75`, `api.py:129-132`), twenty consecutive scans over the unchanged folder produce at most one operator-facing "destination already exists" record for that group, exactly as the refusal case does.
- **AC-PROD-8:** The spec states in one sentence how the owner will tell on production whether this worked, as an observation available without new instrumentation, naming the bound and the surface (for example: after the next parked download, 24 hours of container logs contain at most N records for it, and the parked film appears in the notification list). N and the surface agree with AC-OPS-3 and AC-OPS-5.

### lens-data

- **AC-DATA-1:** No remembered decision is read or written inside `couchpotato/core/plugins/scanner/`: with the renamer's memory populated for every group in a fixture folder, `fireEvent('scanner.scan', folder=F, ...)` returns a dict whose keys and per-group `files` are equal to those returned with the memory empty.
- **AC-DATA-2:** Running `manage.updateLibrary(full=True)` with cleanup enabled twice in the same process, over a fixture library whose files have not changed, fires zero `media.delete` events on the second run. This is the irrecoverable direction: `manage.py:274-275` deletes any `done` movie absent from `added_identifiers`, taking the media document, releases, watch state, tags, profile and review state with it.
- **AC-DATA-3:** The memory key distinguishes entries on both sides, asserting that the decision function ran for the second member rather than merely that nothing crashed: (a) two groups with the same media id and the same scanner string identifier but different source paths, using the measured collision pair where `/downloads/Minions.and.Monsters.2015.1080p.BluRay.x264-GRP/movie.mkv` and `/downloads/Minions.and.Monsters.2015.720p.WEBRip.x264-OTHER/other.mkv` both yield `minions and monsters 2015`; (b) one source with two destinations; and (c) a folder of many groups where every fresh group is decided while every parked one is skipped, including a hand-placed replacement for a film that already has a parked entry. (Merges AC-SEC-3 and AC-QA-17.)
- **AC-DATA-4:** A `REPLACE` outcome is never remembered and never replayed: every call to `replace_atomically` is preceded, within the same scan, by a fresh evaluation of `_identityIsAsserted`, `_sourceStillMatchesTheScan`, `_sizeSupportsTheClaimedQuality` and `_destinationIsInsideTheLibrary`, proven by priming the memory with a `REPLACE`-shaped entry for `(src, dst)`, growing the source past `SCAN_SIZE_TOLERANCE_BYTES`, and asserting no swap occurs and the destination's sha256 is unchanged. Additionally, a group whose refusal is remembered and is then re-scanned with `identity_source` flipped to `search` and a destination resolving outside `conf('to')` results in zero `os.replace` and `os.remove` calls against the library path. (Merges AC-SEC-2.)
- **AC-DATA-11:** The memory is thread-safe and eviction fails open: running the record path in several threads concurrently with a reader iterating the memory completes without raising (no "dictionary changed size during iteration") and loses no recorded entry, repeated at least twenty times; two threads calling `scan()` at once through the existing re-entrancy harness produce exactly one decision for a parked group; and when the AC-OPS-12 cap evicts a still-parked entry, that group is decided again rather than treated as suppressed. (Merges AC-QA-15.)

### lens-operability

- **AC-OPS-1:** A scan whose work was skipped is distinguishable from a scan that found nothing to do: the record that survives the AC-OPS-4 bound names both counts, groups decided this scan and groups skipped as already decided, so `Renamer found 0 groups to process` (`main.py:124`) never means both "the download folder is clear" and "every group in it is parked and needs a human". Proven by two real scans, one over an empty folder and one over a folder holding a single parked group, asserting the two records differ.
- **AC-OPS-3:** The number of records at INFO or above that one unchanged parked group produces does not grow with the number of scans: 500 consecutive scans emit no more records than 100 do, aside from the bounded restatement of AC-OPS-4. Measured baseline on the current tree: twenty consecutive `_moveRenamedFiles` calls on one unchanged colliding group emit 40 records at INFO or above (20 WARNING "Destination already exists, keeping it" and 20 INFO "Leaving source folder in place"), neither bounded. The bound is held by `log_suppressed` on the refusal record independently of the memory, so that an outcome class the memory deliberately does not remember cannot reproduce the flood. (Merges AC-QA-2 and AC-PROD-1. This restates FEAT-009B's AC-OPS-6, which shipped unmet: a recorded spec bug.)
- **AC-OPS-4:** A parked group is quiet but not silent: exactly one record at INFO or above per parked group per restatement window states that the group is still parked, its media id and its outcome value; the window is a single named module-level constant between 3600 and 86400 seconds, passed as the `window=` argument of the existing `log_suppressed` (`couchpotato/core/logger.py:140`); and both directions are proven against an injected clock over 24 simulated hours, at most one record per window and at least one per window for as long as the group stays parked.
- **AC-OPS-5:** A parked film is discoverable without reading the log: entering the parked state fires exactly one `fireEvent('notify', ...)` naming the media and the outcome value, which inserts a durable notification document (`couchpotato/core/notifications/core/main.py:149`) retrievable through the existing `notification.list` API; re-entering the same parked state on later scans fires nothing further; and the signal is not hung on `renamer.before` or `renamer.after`, which have twelve registration sites and zero firing sites in this tree. Proven by recording every event fired across three scans of one parked group, asserting exactly one signal on scan 1 and none on scans 2 and 3, and by reading the list back both populated and empty. (Merges AC-QA-16 and AC-PROD-3.)
- **AC-OPS-6:** The parked set reflects live state rather than memory: when a parked group stops appearing in a scan because its files were moved or deleted by hand, which is how the production incident ended, the group is dropped on that scan and one record at INFO or above says so, naming the media id.
- **AC-OPS-7:** No invalidation is silent: each trigger that forces a re-decide (source size or mtime changed, destination appeared, disappeared or changed in place, a setting that feeds the decision changed, an operator-forced scan) emits exactly one record at INFO or above naming the media id and carrying a distinct greppable token per trigger, proven by a parameterised test asserting all tokens differ and that none of these paths is a bare `pass`, `continue` or `log.debug`.
- **AC-OPS-12:** The store cannot grow without bound: entries for groups absent from a scan are pruned on that scan; pruning happens only on a full scan of the configured from-folder and never on a targeted scan carrying `media_folder` or `release_download`, which would otherwise evict every group it did not look at; and a stated hard cap bounds the store regardless, with the eviction order named in the spec. Proven by scanning a folder whose group set changes across 200 scans, asserting the store size stays bounded and never exceeds the cap, plus a test that a targeted scan prunes nothing. (Merges AC-SEC-4 and AC-QA-13.)
- **AC-OPS-13:** A section added to an existing document under `docs/` answers the three questions this change creates at 3am, using the exact greppable tokens the diff emits: "the renamer has gone quiet but my download is still in /downloads" (where the parked list lives, per AC-OPS-5), "I changed a setting and nothing happened" (which triggers invalidate, per AC-OPS-7), and "how do I make it look again" (the forced scan of AC-QA-10, and that a restart clears everything, per AC-SEC-5). No new document file.
- **AC-OPS-14:** No new decision, skip or invalidation path is a bare `pass`, a bare `continue`, or a `log.debug` with nothing at INFO or above beside it, proven by grepping the diff for every new `except` block and every new early return on the remember and skip paths and confirming each has a record or is covered by a criterion above that says it should be quiet.

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

### Vetoed at planning

**Vetoed by `lens-simplicity`, or arbitrated where simplicity could not veto.**
Simplicity may reject any requirement not traceable to the spec's stated goal,
and cannot override irrecoverable loss, security or the accessibility floor.

| Dropped | Raised by | Decision | Reason |
|---|---|---|---|
| A new API view or UI page for the parked list (the "page or route an operator already reaches" half of `AC-PROD-3`, and the API-view option inside `AC-QA-16` and `AC-OPS-5`) | lens-product, lens-qa, lens-operability | vetoed | The new UI renders no persistent notification view and the renamer exposes no state today, so building one turns a 150-line renamer change into a UI feature with a template, a route and a WCAG obligation, for a condition that has occurred once. Replaced by one `fireEvent('notify', ...)` per park: durable, already listable through `notification.list`, already the precedent used by the downloaded-review gate. Residual risk recorded: if no client renders that list, discoverability rests on `AC-OPS-4`'s bounded restatement. |
| An `addEvent('media.delete', ...)` subscription to purge the memory (the mechanism half of `AC-SEC-7`) | lens-security | mechanism vetoed, outcome kept | `AC-SIMP-6` forbids a new subscription, and for a per-process in-memory store it buys nothing `AC-OPS-6`'s drop-on-absence does not. Security's outcome survives: `AC-SEC-7` is restated as an outcome rather than a mechanism. |
| The 50-group scale case in `AC-QA-17` | lens-qa | vetoed | The spec claims no scale and no lens measured how many groups a real `/downloads` holds. The load-bearing half, that two entries never contaminate each other, survives inside `AC-DATA-3`. |
| Persisting decisions across restarts (the open row in Vetoes and trade-offs above) | orchestrator | closed as rejected | The design constraint already answers it: a stuck refusal surviving a restart removes the operator's most obvious remedy, and persistence adds a schema change, a forward migration and a downgrade path with no criterion behind any of them. `AC-SIMP-5` and `AC-SEC-5` make the rejection checkable. |
| A wall-clock or scan-duration budget | lens-qa (declined to propose) | not written | Nobody has measured the folder walk on the production share. A threshold invented without a baseline is theatre. |

**Arbitrated, not vetoed.**

| Conflict | Resolution | Precedence used |
|---|---|---|
| Skip point: the spec's own `folder_scanner.py` row versus the stated TMDB cost | The scanner is untouched (`AC-SIMP-2`, `AC-DATA-1`, `AC-DATA-2`) and the skip is evaluated in `Renamer.scan` before `fireEvent('scanner.scan', ...)`, which is `lens-simplicity`'s proposal and keeps `AC-QA-4` satisfiable. The `folder_scanner.py` row in "Affected files" is superseded; treat it as struck. | Irrecoverable loss (1). `lens-data` proved that suppressing groups in the shared scanner feeds `manage.py:274-275`, which deletes the media document, releases, watch state, tags, profile and review state. |
| "Say it once" (`lens-qa`, `lens-product`) versus "never go silent" (`lens-operability`) | `AC-OPS-4`: one named window between 3600 and 86400 seconds, passed as the `window=` argument of the existing `log_suppressed`, so no new suppression machinery is added (`AC-SIMP-11`). | Operability (4) over product (5). `lens-security` measured that reusing `log_suppressed` unchanged still emits 734 records over 36 hours at its 300-second window. |
| Discoverability surface: `notify` (third-party fan-out, 28-day row) versus a gated route | `notify`, once per park, with `AC-SEC-8` bounding both the repetition and the content. | Security did not object to `notify` as such, only to it being chosen by accident. Naming it here makes the fan-out a decision. |

**Merged, not dropped.** The surviving ID carries the more testable wording and
names the merged ID inside it: `AC-SEC-2` into `AC-DATA-4`; `AC-SEC-3` and
`AC-QA-17` into `AC-DATA-3`; `AC-SEC-4` and `AC-QA-13` into `AC-OPS-12`;
`AC-QA-2` and `AC-PROD-1` into `AC-OPS-3`; `AC-QA-8`, `AC-DATA-10` and
`AC-OPS-11` into `AC-SEC-5`; `AC-QA-15` into `AC-DATA-11`; `AC-QA-16` and
`AC-PROD-3` into `AC-OPS-5`; `AC-PROD-2` into `AC-QA-4`; `AC-PROD-5` and
`AC-DATA-9` into `AC-QA-12`; `AC-DATA-5` into `AC-QA-5` and `AC-QA-6`;
`AC-DATA-6` into `AC-QA-7`; `AC-DATA-7` and `AC-OPS-9` into `AC-QA-9`;
`AC-DATA-8` and `AC-OPS-8` into `AC-QA-14`; `AC-DATA-12` and `AC-OPS-10` into
`AC-QA-10`; `AC-OPS-2` into `AC-QA-1`.

**Spec bug recorded at planning**, not at review: FEAT-009B's `AC-OPS-6`
required that refusal records go through `log_suppressed` so 500 scans emit at
most 10 records. The shipped record at `main.py:315` is a plain `log.warning`,
measured at 40 records over 20 scans. `AC-OPS-3` restates it and requires the
backstop independently of the memory.

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
