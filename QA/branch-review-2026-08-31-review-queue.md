# Multi-lens review: `feat/review-queue-and-manual-replace` (FEAT-010 / FEAT-011 / FEAT-012 / T67)

## Tree state at synthesis time

`git rev-parse HEAD` **now** returns `e4657801ba9c098dc7f4128b119d7efaf60047a3` on branch `feat/review-queue-and-manual-replace`. The lenses were pinned to `ccdf622965bd9e97ca5bddef01509eb9c22e0ae4`.

`ccdf6229` **is** an ancestor of the current HEAD. The only commit between them is `e4657801 plan: tick 16, all build tasks done, adversarial branch review launched`, and `git diff --stat ccdf6229..HEAD` shows a single file changed: `specs/PLAN-2026-08-30-review-queue-delivery.md` (+20/-2). **No production or test code moved**, so every finding below still applies to the tree as it stands.

Separate and worth naming: **six of the seven lenses reported checkout drift**. Every one of them found the worktree checked out at `e34fe07e` (branch `fix/t47-lighthouse-local-only`) rather than the reviewed tip, and each recovered by extracting or detaching onto `ccdf6229` explicitly. One lens (lens-operability) recorded that while it was detached, something outside its session deleted and recreated the local branch ref from origin at `9b478911`, which it then reset. Parallel sessions are sharing these checkouts and mutating branch refs under running reviews. That is a process defect independent of the code.

**No lens returned BLOCKED.** All seven returned FINDINGS.

---

## 1. Verdict table

| Lens | Verdict | Could not check (verbatim summary) |
|---|---|---|
| **lens-security** | FINDINGS | Worktree drift (HEAD `e34fe07e`, reviewed `ccdf6229` explicitly). Playwright tier not executed, so FEAT-010 AC-SEC-2's end-to-end half and every assertion in `operator-replace-modal.*.spec.ts`, `review-queue.*.spec.ts` and `filters.spec.ts` judged from source. Did not run `make verify`, `make check-secrets`/gitleaks, or any dependency scan. `swap.py`, `softchroot.py`, `searcher.py` unchanged and not re-audited. Did not drive `Renamer.scan()` with operator marker strings planted in filename and NFO. FEAT-011 AC-SEC-12 and AC-SEC-13 judged by construction. |
| **lens-qa** | FINDINGS | Checkout drift (HEAD `e34fe07e`). Entire Playwright E2E tier not executed (no `node_modules`, no live server), so every AC proven only at E2E is UNVERIFIABLE. Vitest run for `movie-filter.spec.ts` not executed. `make mutation-changed`/Stryker not run. `make verify` not run. No PR body exists, so FEAT-011 AC-QA-16/17 and FEAT-012 AC-QA-18 cannot be checked. Deliberately did not mutate: SQLiteCache round-trip, `swap.py` refusals, `_notifyParked` dedup, fail-open `None` returns, seed verify, chip exclusions, `markDone` conflict branches, every a11y/mobile E2E assertion. |
| **lens-design** | FINDINGS | Did not execute Playwright, so every rendered-pixel claim (contrast, 24x24 and 44x44 targets, 393px boxes, scrim/Escape at runtime) is unverified; judged markup and CSS rules only. Alpine runtime behaviour read, not run. Neither theme rendered in a browser. Did not open `docs/design-system/screenshots/`. Worktree HEAD not the reviewed tip (merge-base confirmed clean). FEAT-012 carries no AC-DESIGN. |
| **lens-accessibility** | FINDINGS | Checkout drift; reviewed an extracted pinned tree. Did NOT run the Playwright accessibility or mobile-chrome projects, so the suite is not confirmed green. No real assistive-technology verification (VoiceOver/NVDA/JAWS/Dragon) reasoned from spec, not observed. No verification that `seed_e2e_data.py` produces the two review fixtures the a11y specs depend on. Contrast measured on a reconstructed page rather than the running app. Python backend outside this lens. |
| **lens-data** | FINDINGS | Checkout drift (merge-base verified, worktree restored). Full `pytest tests/unit/` timed out at the 2-minute tool limit; ran four relevant modules only. FEAT-011 AC-DATA-8 and the `copy_id` limbs of AC-DATA-9 unverified: never drove real `release.add`/`_supersedeRelease` against a production-shaped `SQLiteAdapter`. AC-DATA-1's two-films-one-template fixture not built. FEAT-012 AC-DATA-11's 20x thread stress not run; its eviction clause unrunnable because no AC-OPS-12 cap exists. No Playwright. No migration exists to run forward or roll back; no backup/restore exercise. Did not measure the real production `/downloads` folder. |
| **lens-operability** | FINDINGS | Worktree drift, and while detached the local branch ref was deleted and recreated by something outside the session (recovered). Did NOT run Playwright, a11y/mobile suites, or `make verify`. Did NOT exercise `fireEvent('notify')` against a real database, so FEAT-012 AC-OPS-5's "read the notification list back" half is unproven. Did NOT verify `renamer.operator_replace` is reachable through the running server: the only E2E touching it intercepts the route. Per-day log volume figures are extrapolations from an in-process 1:1 measurement. FEAT-010 declares no AC-OPS; T67 has no AC-OPS. |
| **reviewer-verification** (adversarial) | FINDINGS | Drift: worktree arrived at master (`e34fe07e`); detached onto `ccdf6229` explicitly. Not executed: the entire Playwright E2E tier (~1800 new lines across five files), so every a11y/mobile/focus/contrast/target-size claim is unverified; the JS unit tier (vitest), so FEAT-010 AC-QA-8 is unchecked; `make mutation-changed`; the Python integration tier; `make verify` end to end. FEAT-011 AC-QA-7 (threaded double-submission), AC-DATA-5/6 (real ENOSPC, concurrency) and AC-QA-17/18 not driven. No PR body exists. Reviewed only QA/verification and security/privacy lenses. Nothing validated against production or a real NAS mount. |

**Coverage gap that spans every lens: the Playwright E2E tier was never executed by anybody.** Roughly 1,800 new lines across five spec files, carrying every accessibility, mobile, focus-management, contrast and target-size claim on this branch, were read but not run. Twelve AC verdicts are UNVERIFIABLE for that single reason. Two lenses independently found that specific E2E tests in that tier are stubbed against response shapes the server cannot produce (finding H12), so "read the assertions" is not a safe substitute here.

---

## 2. Merged findings

Findings are deduplicated across lenses. Where two or more lenses reached the same defect independently, all are credited and the highest severity is taken.

---

### CRITICAL

---

#### C1. The destructive operator replacement is issued and served as a plain GET with no cross-origin check
**Lenses:** reviewer-verification (Critical), lens-security (High). Merged at Critical.
**AC:** FEAT-011 AC-SEC-8, AC-SEC-9.
**Location:** `couchpotato/ui/templates/partials/movie_detail.html:763-764`; `couchpotato/core/plugins/renamer/main.py:83`, `:1184`; `couchpotato/__init__.py:1173-1175`, `:1196`.

**Evidence (executed by two lenses independently, against a real app built by `create_app` + TestClient):**

```
GET /api/<key>/renamer.operator_replace/?media_id=media-1&source=incoming.mkv
  -> 200 {"success": true}
  -> library file sha256 2c8ce1ed6cac7da468d3f464b173045ea3da5eb0a4668246fce2a02092762448
                      ->  3a5fdfc2788cfa63210c8f774f94f2365943ca6e975f0729e707f8f6d204a3aa
  -> operator's source file deleted from the watch folder
GET  same URL + Origin: https://evil.example  -> 200, library file destroyed
POST same route + Origin: https://evil.example -> 200, handler invoked
GET  /api/renamer.operator_replace/?...  (no key) -> 401, handler NOT invoked
```

The dispatcher is bound to both `@app.get` and `@app.post` on `/api/{route:path}` with no per-route method restriction. `_cross_origin_post` has exactly one call site in the whole tree (`couchpotato/__init__.py:1507`, the logout route); nothing on the `/api/` path consults it. The client fires a bare `fetch(url)`, so the api_key travels in the query string. `tests/e2e/operator-replace-modal.spec.ts:171` asserts on `replaceRequests[0].searchParams`, so the E2E tier **pins** the GET shape rather than catching it. FEAT-011 AC-SEC-8 and AC-SEC-9 required the opposite and wrote out the rationale in full.

**Consequence:** A URL that irrecoverably deletes a media file, api_key included, lands in browser history and in every reverse-proxy access log. A reload, a back-navigation or a link prefetch re-fires the deletion. Being a GET, no CORS preflight applies: any page the operator visits can fire it with a single `<img src>` or `<iframe>` once the key is known, and the key is embedded verbatim in every rendered page as `CP.apiBase` (`couchpotato/ui/__init__.py:73`, `base.html:227`). Chained with H2 below, one hostile film title reads the key and destroys arbitrary library files. Top of this project's own irrecoverability ranking.

**Fix:** Make the destructive route POST-only (a method check inside `operatorReplaceView` is the minimum; enforcing it in `_dispatch_api` for routes marked destructive is the durable form) and switch the client to `fetch(url, {method:'POST', body: new URLSearchParams({media_id, source})})` with the identifiers out of the query string. The dispatcher already parses form bodies at `__init__.py:1261-1264`. Call `_cross_origin_post` from `_dispatch_api` before dispatching a non-GET, matching the logout route, refusing with a WARNING naming both values. Then reissue the four probes and assert the destination is byte-identical by sha256 in the refused cases.

**Recurrence:** Yes, and pervasive rather than new. Every mutating call in this UI is already a GET carrying the api_key: `movie_detail.html` at :275, :286, :296, :531, :582, :967, :998; `movie_cards.html` at :135 and :151; `movie_releases.html`; `wanted.html`'s bulkDelete loop. **This change adds three more.** AC-SEC-8 deliberately broke with that convention for the one action that destroys a file, so the ask here is the named route, with the whole-surface sweep recorded as the standing debt behind it.

---

#### C2. The operator replacement's source-size guard compares a fresh stat with itself, so a partially-written file can replace a complete library copy and the partial is then deleted
**Lens:** lens-data (Critical). **Contested by** lens-security's AC-SEC-4 PASS: see arbitration A1.
**AC:** FEAT-011 AC-DATA-3.
**Location:** `couchpotato/core/plugins/renamer/main.py:1276` and `:1303`.

**Evidence (executed):** `main.py:1276` takes `expected_source_size = os.path.getsize(source)` at execution and passes it at `:1303` to `replace_atomically`, which at `swap.py:190` stats the same file again microseconds later and compares the two values. Probe: called `_listOperatorCandidates()` (the operator's confirmation moment), appended 75,000 bytes to the source, then `_executeOperatorReplacement('media-1','incoming.mkv')`. Outcome `operator_replace`; the 112,000-byte library file became 102,000 bytes, its sha changed, and the source was then removed.

The automatic path does **not** have this defect: `main.py:514` uses `_sourceStillMatchesTheScan`, which compares against the scanner's earlier recorded size.

Mutation, hash-verified: rewriting `:1303` to the literal `os.path.getsize(source)` left all 36 operator tests green. Rewriting it to `None` failed exactly one test, and that test asserts only `expected_source_size is not None` (`test_replacement_operator_execution.py:440`), which is a stand-in, not the behaviour. File restored by copy, md5 `1742196489e09d2241942da7212c9f5f`, `git status` clean.

Stated as judgment rather than measurement by the lens: the dangerous window is a source that has stopped growing (a stalled NAS copy, a paused torrent, an aborted `cp`); a source still actively growing during staging usually trips `swap.py`'s staged-size check instead.

**Consequence:** An operator picking a file that is still landing in the watch folder, which is the 20.3 GB cross-mount case the spec is written around, installs a truncated copy over the complete library file, and `_disposeOfOperatorSource` then deletes the partial. **Both copies of the film are gone.** No undo.

**Fix:** Capture the source size when the candidate list is produced, return it with the candidate, and require the caller to hand it back as part of the confirmed action; compare against that captured value in `_runOperatorReplacement` and refuse with a named outcome on mismatch. Smallest safe interim change: measure the source, sleep briefly, measure again, refuse if it moved.

**Recurrence:** Yes, same root cause, same function. `destination_identity=identity_of(destination)` at `main.py:1304` is stat'ed at execution too, so the replay guard is equally self-comparing (see M6). The class is: **the operator path has no server-side decision step, so every "compare against the value captured at decision time" guard degenerates into comparing a value with itself.** Expect it wherever this entry point is extended.

---

### HIGH

---

#### H1. Every outcome of an operator replacement is invisible: the route answers success before any work starts, discards the worker's result, logs nothing on five of six refusal branches, and notifies nobody
**Lenses:** lens-qa (High), lens-design (High), lens-operability (High), lens-product (High), reviewer-verification (High). **Five lenses, independently.**
**AC:** FEAT-011 AC-OPS-3, AC-OPS-4, AC-OPS-5, AC-OPS-11, AC-PROD-4, AC-DESIGN-9/10/11, AC-QA-7.
**Location:** `couchpotato/core/plugins/renamer/main.py:1184-1212` (`operatorReplaceView`), `:1242-1331` (`_runOperatorReplacement`); client at `partials/movie_detail.html:762-796`.

**Evidence (executed with a root handler at DEBUG, by three lenses):**

```
'no releases at all'            -> {'success': True} | INFO+ records: [] | below-INFO: [] | notify: 0
'source outside watch folder'   -> {'success': True} | INFO+ records: [] | below-INFO: [] | notify: 0
'ambiguous release'             -> {'success': True} | INFO+ records: [] | below-INFO: [] | notify: 0
'source does not exist'         -> {'success': True} | INFO+ records: [] | below-INFO: [] | notify: 0
```

`operatorReplaceView` is eight statements with no branches: it reads `media_id` and `source`, spawns a daemon thread, and returns the literal `{'success': True}` at `:1212` before any bytes move and with no validation, so even a missing `media_id` returns success. The thread's `(outcome, destination)` tuple is never read by anything except tests. Grepping `_runOperatorReplacement`'s line range for `notify` returns nothing; grepping for `log.` returns exactly one record, `log.info('Renamer is already running...')` at `:1232`. Fourteen terminal outcomes are reachable on this path and thirteen are silent. The client reads `data.success`, toasts "Replacement started", and immediately `cpSwap()`s the detail body. The route's own API docstring at `main.py:83-92` says "Backgrounded; poll notifications for the outcome", naming a surface that does not exist.

**Consequence:** An operator who picks a file, reads a confirmation saying the current library copy will be permanently deleted, and clicks confirm is told "Replacement started" and shown a refreshed page with the old file still in place, whichever way it went. Path-confinement refusal, no completed release, ambiguous release, destination outside the library, vanished source, refused or failed atomic swap, and full success all look identical. On the partial-success path (swap done, release bookkeeping refused) the operator is told success while the database is left claiming a replaced path. FEAT-012 then reasonably parks the leftover download, and the operator has no record anywhere saying why. **This is the silent-failure-of-the-feature shape, on the branch's highest-risk action, and it reproduces on the new path the exact failure FEAT-012 exists to end.**

**Fix:** Log each terminal outcome at INFO or above naming the outcome constant, the media id and the release ids (no paths, matching the file's existing convention at `main.py:296-311`), and fire one `fireEvent('notify', ...)` per terminal outcome, reusing the durable notification pattern `_notifyParked` already implements at `main.py:193-231`. Map each outcome constant to a sentence, which is what AC-DESIGN-10 already specifies including its table-driven test that fails when a new constant has no mapping. Then pin it with a unit test per outcome and an E2E in which the operator sees the failure rather than "Replacement started".

**Recurrence:** Yes, and the contrast is instructive: FEAT-012's parked path got exactly this treatment (`_notifyParked` plus a bounded WARNING, both tested), so the omission is specific to the FEAT-011 operator path rather than a house habit. The two were built a task apart against the same spec family. Expect the same gap on `_disposeOfOperatorSource`'s failure branch, and on any future backgrounded route in this plugin.

---

#### H2. A film title is interpolated into an Alpine JS expression, so an apostrophe breaks out of the string literal
**Lenses:** lens-security (High), reviewer-verification (High).
**AC:** FEAT-010 AC-SEC-1, which names this exact line, states it is fixed in this change, and requires a load-bearing test. Neither happened.
**Location:** `couchpotato/ui/templates/partials/movie_cards.html:163`.

**Evidence (executed, real Jinja render via `couchpotato.ui._jinja`, not a copy):** rendering the partial for a downloaded movie titled `Ocean's Eleven'+(window.pwn=1)+'`, then HTML-entity-decoding every attribute whose name begins with `@`, `:` or `x-`, yields exactly one hit:

```
:aria-label => refreshing ? 'Refreshing metadata for Ocean's Eleven'+(window.pwn=1)+''
                          : 'Refresh metadata for Ocean's Eleven'+(window.pwn=1)+''
```

The payload sits outside the quoted JS literal. Jinja autoescape turns the apostrophe into `&#39;`, and the HTML parser decodes attribute values before Alpine evaluates them, which is the mechanism AC-SEC-1 spells out verbatim. `git show master:...movie_cards.html` confirms the line is pre-existing at `:108`. Grep across `tests/` for `window.pwn`, `Refreshing metadata` or any Alpine-attribute scan returns nothing.

**Consequence:** Two harms. **Security:** arbitrary script execution in the operator's authenticated page, which carries the api_key verbatim as `CP.apiBase`; chained with C1, one hostile title reads the key and issues a single GET that permanently deletes a library file. Titles are reachable through TMDB metadata and the userscript add-via-URL path. **Accessibility, which fires with no attacker at all:** any ordinary title with an apostrophe ("Ocean's Eleven", "Schindler's List") produces an invalid Alpine expression, so the `:aria-label` binding fails and the icon-only refresh control has no accessible name. That is a WCAG 2.2 AA 4.1.2 failure on a very common case, in a codebase whose stated floor is AA.

**Fix:** Stop interpolating the title into the expression. Emit it as data and read it at runtime, as AC-SEC-1 prescribes: `data-title-label="{{ title }}"` (a plain autoescaped attribute) with `:aria-label="refreshing ? 'Refreshing metadata for ' + $el.dataset.titleLabel : ..."`, or pass it through the registered `| tojson` filter (`couchpotato/ui/__init__.py:33`). Then add the AC's own guard: render with the hostile title, decode every `@`/`:`/`x-` attribute, assert none contains the payload, and prove it load-bearing by reverting the line.

**Recurrence:** Checked and bounded within `movie_cards.html`: this is now the only instance, and the two aria-labels this change adds (`:134`, `:150`) are plain autoescaped attributes. The safe forms elsewhere in this change (`x-text="candidate"`, `:title="candidate"`) show the pattern is understood, which makes this an omission rather than a habit. Outside the diff, a repo-wide grep for `{{ ... }}` inside an attribute whose name starts with `@`, `:` or `x-` is worth one pass; the bare `{{ movie_id }}` interpolations inside `@click` JS strings are the same shape but are not attacker-influenced.

---

#### H3. The guard that stops an operator replacement destroying the wrong half of a multi-file release has no test: it was deleted and the whole suite stayed green
**Lenses:** lens-qa (High, mutation M3), reviewer-verification (Medium, mutation C). Merged at High.
**AC:** FEAT-011 AC-QA-5, AC-QA-16.
**Location:** `couchpotato/core/plugins/renamer/main.py:1261-1263`, the `if len(movie_files) != 1: return OPERATOR_DECLINED_AMBIGUOUS_FILE` block.

**Evidence:** two lenses ran the same mutation independently. lens-qa deleted the two lines (single-occurrence assert-then-replace, landing confirmed by `git diff --stat` showing 1 file changed, 2 deletions) and ran `pytest tests/unit/ -q -k "operator or renamer or replacement or swap"`: 330 passed. reviewer-verification replaced the condition with `if False:` and ran the **full** unit tier: 3696 passed, 2 skipped, 3 xfailed. Both restored by file copy, sha256 back to `33aa52957be7a7c28d4ad3c13ffa913afc061dc873163fed0b70eea06877c334`. Grep confirms no test constructs a completed release whose `files['movie']` holds two entries: `OPERATOR_DECLINED_AMBIGUOUS_FILE` appears only in `test_replacement_operator_decision.py` for the two-**releases** case, which mutation M2 showed is guarded.

**Consequence:** `decide_operator_replacement` only checks that `files['movie']` is truthy, so this length check is the sole thing standing between a two-part film (CD1/CD2, or any release recording two movie files) and `movie_files[0]` being overwritten and permanently deleted. It is the exact "do not guess which file the operator meant" rule the spec's owner decision names, on the code path the module docstring says has already destroyed an irreplaceable file twice, and nothing in the repo would notice if it went away. `DECLINED_MULTI_FILE_GROUP` exists on the automatic path for the same reason, so the case is real rather than hypothetical.

**Fix:** Add a case to `tests/unit/test_replacement_operator_execution.py`: a world fixture whose single `done` release carries `files['movie'] = [dst_a, dst_b]`, driven through `_executeOperatorReplacement`, asserting `outcome == OPERATOR_DECLINED_AMBIGUOUS_FILE`, `destination is None`, and `_tree_shas(lib)` unchanged. Re-run the mutation and watch it fail.

**Recurrence:** Yes, and lens-qa expects this to be the branch's dominant class. FEAT-011 AC-QA-5 lists **nine** pre-flight refusals for the operator path and **three** are present (source symlink, destination symlink, destination outside library). The six absent (source missing, broken symlink, destination missing, same inode under `file_action=link`, source size changed since confirmation, multi-file) are all guards in the same function with the same "returns a named constant, no test names it" shape. Check every early return in `_runOperatorReplacement` for a matching test before closing this. See also M5.

---

#### H4. The set that decides which renamer refusals are remembered is guarded by nothing: widening it to include the transient outcomes and REPLACE itself leaves the entire unit suite green
**Lenses:** reviewer-verification (High, mutation E), lens-qa (AC-QA-9 FAIL).
**AC:** FEAT-012 AC-QA-9, AC-DATA-4, AC-QA-14.
**Location:** `couchpotato/core/plugins/renamer/main.py:64-71` (`REMEMBER_ELIGIBLE_OUTCOMES`).

**Evidence:** added `declined_error`, `declined_incomplete_evidence`, `declined_not_better`, `declined_no_owner`, `declined_unknown_quality`, `declined_source_changed` **and `replace`** to the frozenset. Hash confirmed the edit landed. Full unit tier: 3696 passed, 2 skipped, 3 xfailed. Restored, sha256 back to `33aa5295...`. Nothing enumerates the set or exercises its members by name.

**Consequence:** Nothing stops a future edit adding a transient outcome to the remembered set. If `declined_error` or `declined_incomplete_evidence` were remembered, a one-off read failure (NAS blip, permission hiccup) parks the folder until the container restarts, which is the permanent skip AC-QA-14 exists to forbid. If REPLACE were remembered, a folder that just performed a successful destructive swap is recorded as settled. The code is correct today; the guard around it does not exist.

**Fix:** Add a parameterised test importing the outcome constants from `renamer/replacement.py` that asserts, for each of the five eligible outcomes, that a second unchanged scan skips; and for each of the seven ineligible ones plus REPLACE, that a second scan re-decides. Prove it by re-running the mutation.

**Recurrence:** Yes, same class as H3 and M5: constants and conditionals on the new paths that the tests exercise only through the happy path.

---

#### H5. The decision memory's invalidation surface omits the quality documents, so a park survives the settings change that would clear it
**Lenses:** lens-data (High), lens-qa (Medium, AC-QA-7 FAIL). Merged at High.
**AC:** FEAT-012 AC-DATA-6, merged into AC-QA-7, which names this case verbatim.
**Location:** `couchpotato/core/plugins/renamer/main.py:55` (`DECISION_MEMORY_SETTINGS`) and `:162-165` (`_settingsSignature`).

**Evidence (executed):** parked a group at `declined_size_contradicts_quality`, then changed the quality document's `size_min` from 4000 to 1, which is the edit an operator makes in the settings UI. `_settingsSignature()` returned the identical tuple before and after, and `fireEvent('scanner.scan', ...)` was never called again (1 call across both scans, RE-DECIDED? False). The band is read at `main.py:843-858` via `fireEvent('quality.single', identifier)`, a **database document**, while `DECISION_MEMORY_SETTINGS` reads only `config.ini` keys (`upgrade_replace`, `to`, `folder_name`, `file_name`). The repo's own test (`test_renamer_decision_memory_invalidation.py:226-262`) parameterises over `DECISION_MEMORY_SETTINGS` itself, so it structurally cannot catch an input missing from that tuple.

**Consequence:** The operator widens the quality band precisely to unblock a refused replacement, the scan silently continues to skip the folder, and the download sits unfiled indefinitely while the UI shows nothing wrong. Recovery requires restarting the container, **because the kill switch is also broken (H6)**. The download is "expensive" rather than irreplaceable on the recoverability ranking, but the silence is total.

**Fix:** Either fold the quality band for each parked group's rung into the recorded signature, or, smaller and safer, drop `DECLINED_SIZE_CONTRADICTS_QUALITY` from `REMEMBER_ELIGIBLE_OUTCOMES`, since its cause demonstrably can change without a filesystem or `config.ini` change, which is the precise property that set is documented to require.

**Recurrence:** Yes. `DECLINED_UNVERIFIED_IDENTITY` has the same shape: `_identityIsAsserted` (`main.py:794-809`) reads `group['identity_source']`, which `folder_scanner.determineMedia` derives from the media and release documents, not from the watch folder or `config.ini`. Adding the movie to the library, the obvious operator remedy for "unverified identity", will not expire that park either. **Both members of `REMEMBER_ELIGIBLE_OUTCOMES` that depend on database state need auditing.**

---

#### H6. The feature's documented kill switch does not work: `renamer.scan` through `scanView` is answered from the memory and does nothing, and a targeted scan never clears the entry
**Lenses:** lens-data (High), reviewer-verification (Medium), lens-qa (Medium, AC-QA-10 FAIL). Merged at High.
**AC:** FEAT-012 AC-QA-10, AC-DATA-12, AC-OPS-10.
**Location:** `couchpotato/core/plugins/renamer/main.py:116-126` (`scanView`) and `:290` (`targeted = media_folder is not None or release_download is not None`).

**Evidence (executed by two lenses):** after scans parked a group with `fireEvent('scanner.scan')` at 1, `plugin.scanView()` left it at 1, and `plugin.scanView(base_folder=<downloads>)` left it at 1. Only a `media_folder`-carrying call bypassed the memory, **and it left the entry in place** ("memory survived the targeted scan: True"), so the next scheduled scan skips again. Grep for `forced` in `renamer/main.py` returns nothing, so the AC-OPS-7 "operator forced" record does not exist either. Grep across both memory test modules for `targeted`, `media_folder`, `release_download`, `scanView` matches exactly one comment (`test_renamer_decision_memory.py:334`) and no test.

Worse: `test_renamer_decision_memory.py::test_scanner_scan_is_asked_for_at_most_once_across_five_scans` drives `scan(base_folder=...)` and asserts the skip, so **the suite currently pins the opposite of AC-QA-10**.

**Consequence:** AC-QA-10 states the purpose: "one API call restores the previous behaviour for the affected group without restarting the container." That is false as built. An operator who hits H5, or any stale park, has no remedy short of a container restart, and the button they press reports success while doing nothing. It compounds directly with H5.

**Fix:** Have `scanView` pass an explicit operator-forced flag through `fireEvent('renamer.scan', ...)`; in `scan()`, treat it as bypassing the memory check **and** popping `self._decision_memory[scan_folder]`, so the next scheduled scan re-decides too. Emit the AC-OPS-7 forced-scan record. Add the test AC-QA-10 asks for, driving `scanView` rather than `scan()`, and fix the existing test that pins the contradiction.

**Recurrence:** The only kill switch this change introduces, so no second instance expected. But FEAT-012's untested criteria cluster in the same area and share the shape "the memory's escape hatches are unproven": AC-QA-9 (H4), AC-QA-11 (identity_source change forces a re-decide), AC-QA-12 (a skip never becomes a delete), AC-QA-14 (M8) and AC-DATA-11 (M12). Treat them as one batch rather than five.

---

#### H7. The decision memory's skip record is emitted once per scan with no bound, so log volume still grows one-for-one with scan count
**Lens:** lens-operability (High).
**AC:** FEAT-012 AC-OPS-3.
**Location:** `couchpotato/core/plugins/renamer/main.py:317-321`.

**Evidence (measured against the AC's own test):** 100 scans of one unchanged parked group emitted 102 records at INFO or above; **500 scans emitted 500**. All 500 were `Renamer: 1 group(s) already decided and unchanged; skipping the scan`. It is a plain `log.info`, not wrapped in `log_suppressed`, unlike the collision WARNING at `main.py:600`. The existing guard (`test_renamer_decision_memory.py:340`) asserts `len(records) <= 4` but calls `_moveRenamedFiles` directly and never reaches `scan()`, so it cannot see this record at all. In production `checkSnatched` (`renamer/scanner.py:17`, scheduled every `run_every` minutes, default 1) calls `self.scan()` whenever there are snatched or seeding releases and no downloader status, which is the state the original incident was in.

**Consequence:** FEAT-012 replaces a two-records-per-scan flood with a one-record-per-scan flood. The spec measured the incident at roughly 1,100 records; a parked group at the one-minute cadence produces about 1,440 a day. `log_suppressed`'s own docstring records that the 5.5 MB log ring is "the only diagnostic a self-hosted install has" and that roughly 10,300 records evict it. **The feature that exists to stop the log being churned still churns it.**

**Fix:** Wrap `main.py:317` in `log_suppressed` with a key of `renamer_memory_skip:%s % scan_folder` and the named window constant AC-OPS-4 requires (see M14), and extend the existing test to drive `scan()` rather than `_moveRenamedFiles`.

**Recurrence:** Yes, and this is the **third** time the same bound has been required: the spec itself records FEAT-009B's AC-OPS-6 shipping unmet for exactly this reason. The pattern is that the bound gets proven on one code path while a second path emits the same information unbounded. Check every `log.info` added by this diff for the same shape.

---

#### H8. An unhandled exception in the operator replacement thread bypasses the application logger entirely and lands only on stderr
**Lens:** lens-operability (High).
**AC:** FEAT-011 AC-OPS-11.
**Location:** `couchpotato/core/plugins/renamer/main.py:1214-1240` (`_executeOperatorReplacement` has no try/except around the body).

**Evidence (executed):** making `release.for_media` raise `RuntimeError` printed the full traceback via threading's default excepthook as `Exception in thread Thread-1 (_executeOperatorReplacement)`, while the attached root-logger handler captured `log records captured: []` and the HTTP response was `{'success': True}`. Grep for `stderr`/`excepthook` across `logger.py`, `CouchPotato.py`, `runner.py` finds only the console StreamHandler at `logger.py:439`: nothing installs `sys.excepthook` or `threading.excepthook`, and nothing pipes stderr into the rotating file handler. The path from `_resolveOperatorSource` through `replace_atomically`, `identity_of`, `_destinationIsInsideTheLibrary` and `_supersedeRelease` is all outside any handler, **and part of it runs after `os.replace` has already destroyed the old library file**.

**Consequence:** A crash mid-replacement writes nothing to the log file the operator reads, so the only durable evidence of a destroyed library file is the About-to-replace WARNING that preceded it, with no record of what went wrong afterwards. The traceback also skips `PrivacyFilter`, so filesystem paths in it are unredacted on the console stream.

**Fix:** Wrap the body in `try/except Exception` with `log.error('Operator replacement for media %s failed: %s', media_id, traceback.format_exc())`, matching the pattern already used in the scan loop, so the failure reaches CPLog and PrivacyFilter.

**Recurrence:** This is the first `threading.Thread` in the renamer plugin, so the gap is new here, but any future backgrounded work started the same way inherits it. Worth checking whether other plugins spawn raw threads with no logging wrapper.

---

#### H9. The confirmation for an irreversible deletion names neither the file it will destroy nor the file it will install, and no size on either side
**Lenses:** lens-design (High, AC-DESIGN-5/7), lens-product (High, AC-PROD-3), lens-qa (Medium, AC-QA-12), lens-accessibility (Medium, AC-A11Y-8), reviewer-verification (folded into their High). Merged at High.
**Location:** `couchpotato/ui/templates/partials/movie_detail.html:428-433` and `:479-487`.

**Evidence (rendered output):** the entire confirmation body is `Replacing <strong>{{ title }}</strong> will permanently delete its current library copy and put the file you choose in its place. This cannot be undone.` Each candidate row is a truncate button whose whole content is `<span x-text="candidate"></span>` with `:title="candidate"`. No filename, quality or size for the library file; no size for the replacement. **The data is never sent:** `operatorCandidatesView` (`main.py:1172-1182`) returns bare names, and `grep -i size` over the production half of the diff finds no size exposed to any client.

The test standing for this criterion (`test_operator_replace_modal_ui_template.py:153-179`) asserts only that the substrings `current library copy`, `delete` and `cannot be undone` appear. Those are fixed template strings; none is derived from the data under test, so the assertion cannot distinguish a correct confirmation from one that omits every file detail, and it would pass unchanged if the destination resolution were pointed at the wrong film.

**Consequence:** The operator cannot tell, before committing, whether the server resolved the right library file, and on a real watch folder holding a season pack plus sidecars several rows differ only in a token the truncation hides. A 700 MB source silently replacing a 17 GB library copy passes this confirmation unremarked. The spec's own framing: "A confirmation that says only replace with X? is not sufficient and is the single most likely way this ships wrong." For a screen-reader user arriving at the confirm control by Tab, selection state lives only in `aria-checked` on a radio elsewhere in the dialog, so there is no read-back of what they are committing to. This is the code path whose module docstring records having destroyed an irreplaceable file twice.

**Fix:** Add a server-side lookup returning, for a `media_id`, the resolved destination's basename, quality label and byte size, plus each candidate's size. `_runOperatorReplacement` already resolves the destination (`main.py:1256-1263`) and measures the source (`:1272`); the read-only half can reuse `decide_operator_replacement` without touching the destructive path. Render both sides using the release table's mono-numeric grammar (`movie_releases.html:222-230`), and rewrite the test to assert fixture-derived values that differ per case so a hardcoded string cannot satisfy it. **This is the same server-side decision step C2 and M6 need, so build it once.**

**Recurrence:** The missing-size half is specific to this picker. The "destructive control with no comparison shown" class is not: `movie_detail.html:534` (Delete) and `:296` (Mark Failed & Re-search) both confirm with prose naming nothing concrete, as does `movie_cards.html:154`. Those are scoped to a card the user is looking at, so fix the picker now and leave them.

---

#### H10. The candidate listing offers every regular file in the watch folder, cannot distinguish "nothing here" from "I could not look", has no cap and no total count
**Lenses:** lens-qa (High), reviewer-verification (High), lens-design (Medium, AC-DESIGN-3), lens-operability (Medium, AC-OPS-11). Merged at High.
**AC:** FEAT-011 AC-QA-14, AC-DESIGN-3.
**Location:** `couchpotato/core/plugins/renamer/main.py:1369-1410` (`_listOperatorCandidates`), `:1172-1182` (`operatorCandidatesView`), client at `movie_detail.html:449-461`.

**Evidence (executed across four states with the root logger at DEBUG):**

```
not configured    -> {'success': True, 'candidates': []} | logs: []
empty folder      -> {'success': True, 'candidates': []} | logs: []
unreadable folder -> {'success': True, 'candidates': []} | logs: []
missing folder    -> {'success': True, 'candidates': []} | logs: []
```

`_listOperatorCandidates` does `os.listdir(sp(watch))`, keeps anything `os.path.isfile` accepts and `_resolveOperatorSource` does not refuse, and returns the names: **no extension filter, no cap, no total count.** The `except OSError: return []` at `:1391` and the per-entry `continue` at `:1397` discard the reason. The client renders `operator-replace-error` only when the fetch threw or `success` was false, so a real unreadable watch folder renders the EMPTY state, "No files were found in the download folder to replace this with." `test_operator_candidate_listing.py` has no case for an unset or unreadable folder, and its fixtures contain only `.mkv`/`.mp4`, so the absent filter is invisible.

The two E2E tests that claim to prove the states differ both stub the route with `route.fulfill({status: 500})`, **a response the server has no code path to produce** (see H12).

**Consequence:** Two harms. **Data:** the operator's fat-fingered click on a stray `.srt`, `.nfo`, `.txt` or `.part` in `/downloads` destroys the library copy and puts junk in its place, with no size shown to catch it, no undo, and nothing downstream to refuse it (the operator path deliberately never calls `decide_replacement`, and `swap.py`'s refusal list has no size-plausibility check). **Operability:** the prompting scenario for this whole feature is a NAS mount. When that mount drops, or `conf('from')` is unset after a settings edit, the operator is told their download folder is empty and goes looking for a file they know they put there. Three of those four states have different remedies, and the UI sends all three to the same dead end while the modal has the information to say "I could not check" and throws it away.

**Fix:** Filter candidates to `FileDetectorMixin.extensions['movie']`; apply a stated cap and return the total found alongside; return a named reason (`not_configured`, `folder_missing`, `folder_unreadable`, `empty`) rather than a bare `[]`, and log at WARNING for the three that are faults with the path at DEBUG only. Give each its own sentence in the template, naming the configured folder. Add unit tests driving the unset and raising cases asserting the named error. Keep the E2E stubs, but add one exercising a real server response.

**Recurrence:** Yes, and it is a third instance of a pattern already recorded and deliberately parked on this branch: FEAT-010's "Vetoed at planning" table drops a distinct error state for a failed grid fetch, noting that `/partial/movies` swallows the exception and renders "No movies found", indistinguishable from an empty library, and `partial_movie_detail` has the same shape. **Worth deciding once across all three rather than case by case.**

---

#### H11. Both card review controls fail WCAG SC 2.5.3 Label in Name, and the project's axe configuration cannot detect it
**Lens:** lens-accessibility (High).
**AC:** FEAT-010 AC-A11Y-5, which passes on its own terms; the SC 2.5.3 breach is outside what it covers (see spec bugs).
**Location:** `couchpotato/ui/templates/partials/movie_cards.html:134` and `:150`.

**Evidence (executed):** the buttons render visible text `Mark Done` / `Mark Failed` (`:137`, `:153`) but override the name with `aria-label="Mark {{ title }} as done"` / `"Mark {{ title }} as failed"`. "Mark Done" is not a contiguous substring of "Mark The Thing as done", because the title interrupts it. Proven undetectable: running axe-core via `@axe-core/playwright` over the exact button markup with the project's own tag set (`wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa`) reported `VIOLATIONS: (none)` and `rule ran at all? false` for `label-content-name-mismatch`, because that rule is experimental and excluded. `review-queue.a11y.spec.ts:327` matches on `/mark .* as done/i`, which **asserts the mismatched form rather than catching it.**

**Consequence:** A Level A conformance failure on two newly added controls, invisible to both the axe gate (AC-A11Y-13) and the naming test (AC-A11Y-5). Voice Control and Dragon users cannot activate Mark Done or Mark Failed by the label they can see; they must fall back to numbered overlays.

**Fix:** Reorder so the visible text is a prefix: `aria-label="Mark Done: {{ title }}"` and `"Mark Failed: {{ title }}"`, which keeps AC-A11Y-5's uniqueness and title-bearing properties. Change the regex at `review-queue.a11y.spec.ts:327` in the same commit, and **add the generic assertion that would have caught this**: that the accessible name contains the button's own visible `textContent`. That does not depend on axe's experimental rules.

**Recurrence:** Every `aria-label` in the three changed templates was checked. Only these two are new controls where an `aria-label` overrides visible text; `movie_cards.html:36/:49/:163` and `movie_detail.html:327/:345/:412` are icon-only or non-text. Expect no further instances in this diff, but the missing generic assertion means the next author who adds a labelled text button repeats it, which is why the fix must add the containment check rather than only editing two strings.

---

#### H12. E2E tests that appear to guard refusal reporting are incidentally passing: they stub response shapes the server cannot produce, and one asserts the raw internal token AC-DESIGN-10 forbids
**Lenses:** reviewer-verification (folded into their outcome-reporting High), lens-product (Medium), lens-design (AC-DESIGN-10 FAIL), lens-qa (AC-QA-14 evidence). Merged at High, because it is the reason H1 could ship unnoticed.
**Location:** `tests/e2e/operator-replace-modal.a11y.spec.ts:531-575`; `tests/e2e/operator-replace-modal.spec.ts:229`, `:246`, `:266`.

**Evidence:** `:558-575` stubs the replace route with `{success: false, error: 'declined_not_better'}` and asserts the assertive announcer `.toContain('declined_not_better')`. `operatorReplaceView` returns `{'success': True}` on every path and never sets an `error` key, so that branch of `confirmReplace()` (`movie_detail.html:796-798`) is unreachable in production: **deleting the entire server-side outcome path would not make this test fail.** `:531-556` stubs `{"success":true}` and asserts the polite announcer matches `/replac/i`, which the client emits as "Replacement started" whether or not the replacement will succeed, while the test is named "a successful replacement is announced". The candidate-listing error tests at `:229` and `:246` stub `route.fulfill({status: 500})`, a response `operatorCandidatesView` has no code path to produce. Separately, AC-DESIGN-10 requires that after any outcome the rendered text contains none of the substrings `declined_`, `refused_`, `failed_`; **this test asserts that it does.**

**Consequence:** A reviewer scanning the suite sees "a successful replacement is announced" and "a declined replacement is announced, naming the reason" both green and concludes the outcome surface exists. It does not. These tests are why H1 and H10 could ship. If the outcome surface is built later, the second test will pressure it toward emitting the raw internal token.

**Fix:** Rewrite so the refusal case is produced by the real server (an unreplaceable seeded movie) rather than a stubbed response, and assert a sentence rather than a constant. Until the server surfaces outcomes, mark them explicitly in the file as pinning client rendering of a contract the server does not yet honour, so the gap is visible in the test rather than only in this report.

**Recurrence:** Yes. `movie-detail.spec.ts:215-243` is a conditional no-op whose own comment says the "downloaded" fixture cannot exist, which **this change made false** by seeding `e2e-seed-movie-007/008`. Both are tests that pass without exercising the behaviour they are named for. Worth a sweep of every FEAT-011 E2E `page.route` stub for a fabricated server response shape.

---

### MEDIUM

---

#### M1. Dark-theme contrast fix loses to Tailwind's hover utility on specificity: both new destructive controls drop to 4.21:1 on hover
**Lens:** lens-accessibility (Medium). **AC:** FEAT-011 AC-A11Y-11, which quotes this exact figure as the failure to avoid.
**Location:** `couchpotato/ui/templates/base.html:156` and `:165`.

**Evidence (measured in real Chromium against a page rebuilt from the exact tokens and the vendored `tailwindcss-cdn.js`):** dark theme, card Mark Failed rest 4.57:1 / **hover 4.21:1 FAILS**; modal Replace file rest 4.57:1 / **hover 4.21:1 FAILS**; release Mark failed 4.57:1 in both states, passes. The mechanism is confirmed by that third line: `#movie-releases [data-testid=...]` is (1,1,0) and beats `.hover\:bg-cp-danger\/15:hover` at (0,2,0), while the two failing rules are themselves (0,2,0) and tie. Ties resolve by source order, and `tailwindcss-cdn.js` does `document.head.append(Yt)` (byte offset 406695), appending after `base.html`'s inline `<style>`. The comment at `base.html:155` reasons only about "the plain Tailwind utility's specificity" and does not account for `:hover` adding a specificity unit. The lens's composite maths reproduces the spec's own quoted 4.46/4.57/4.21 figures to two decimal places, so the model is calibrated against the author's numbers.

**Consequence:** WCAG 1.4.3 fails in the dark theme whenever the pointer rests on the control that commits an irreversible file deletion, and on the card control that discards a completed download. No test measures hover; the only contrast test (`operator-replace-modal.a11y.spec.ts:625`) measures rest, which is the gap the AC's own text calls out.

**Fix:** Add the hover state to both rules, then extend `operator-replace-modal.a11y.spec.ts:625` and `review-queue.a11y.spec.ts:481-493` to measure after `.hover()`. Prove the guard by reverting the `:hover` selector and watching it go red.

**Recurrence:** Yes, and expected beyond this diff. Any `base.html` override written to beat a `bg-*` utility silently loses to that utility's `hover:`, `focus:` or `active:` variant unless it names the state or reaches (1,1,0). The same pattern is on the operator-replace trigger (`movie_detail.html:361`) and the delete button (`:531`); those sit on `cp-bg` and measure ~4.59:1 on hover, so they pass **by accident of surface, not by design**. A guard that walks every element carrying a `hover:bg-` class and measures both states would close the class.

---

#### M2. Fixing the cache turns a dead store into a live on-disk one holding provider response bodies, including indexer download links carrying the indexer's own API key
**Lens:** lens-security (Medium). **AC: none. T67 carries no AC-SEC criterion at all, so this is a spec bug as well as a finding.**
**Location:** `couchpotato/core/cache.py:100-133`.

**Evidence (executed against both versions):** against master's `cache.py`, `cache.set('k1', b'<rss>apikey=SECRET</rss>', expire=300)` leaves 0 rows in `cache.db` because `json.dumps` raised `TypeError` and the write was skipped (that is the T67 bug). Against this tip the same call leaves 1 row, and reading `cache.db` directly with `sqlite3` and base64-decoding the marker dict returns the body verbatim: `<rss><item><link>http://jackett:9117/dl/torznab/?apikey=JACKETT_SECRET_abc123&amp;file=x</link></item></rss>`. **File mode 0644.** The values reaching this cache are exactly HTTP response bodies (`plugins/base.py:289` stores whatever `self.urlopen(url)` returned), and Torznab/Jackett responses routinely embed the indexer apikey in `<link>` elements. Retention is bounded but soft: `_maybe_evict` runs only from `get()`, at most once per 300s, so expired rows persist until something reads. `scripts/backup.sh` copies only `database_v2/couchpotato.db` and settings, so backups are not amplified.

**Consequence:** Credentials belonging to the operator's indexers, plus a rolling record of which films they searched for, now sit unencrypted and world-readable in the config data directory on a box that runs unattended. Before this change they did not, because the write silently failed. A new data-at-rest surface created by a performance fix, with no stated minimisation or retention decision behind it.

**Fix:** State the decision and tighten the defaults. Add an AC to T67 covering what the cache may hold and for how long; create the cache directory `0o700` and chmod `cache.db` to `0o600` at creation; run eviction on a timer rather than piggy-backed on `get()`. If provider bodies are judged too sensitive to persist at all, gate byte-body caching behind an explicit `cache_timeout`.

**Recurrence:** Not another instance of this exact defect. Worth checking whether anything else in the config data directory is created 0644 without a stated retention.

---

#### M3. The new destructive routes are absent from the route auth inventory, so nothing records what a passwordless default install now exposes and nothing fails when the next such route is added
**Lenses:** lens-security (Medium), reviewer-verification (Low). Merged at Medium.
**AC:** FEAT-011 AC-SEC-10, AC-SEC-7.
**Location:** `tests/unit/test_route_auth_inventory.py:38` (`PUBLIC_ROUTES`), `:139-260`; routes registered at `renamer/main.py:83`, `:94`.

**Evidence:** grep for `operator_replace` / `operator_candidates` / `renamer.` in the inventory returns nothing. Every test there enumerates FastAPI route objects (`app.routes`) and compares against `PUBLIC_ROUTES`; **it has no notion of an `addApiView` plugin route at all**, so the two new routes are invisible in both directions. All `addApiView` routes hide behind the single `/api/{route:path}` entry already listed in `PUBLIC_ROUTES` with the reason "authenticated by api_key inside callApiHandler, not by session". The candidate-listing route does have a real request-level auth test (three cases, executed, passing); **the destructive route has none.**

**Consequence:** On an install with no password every route is served to an unauthenticated caller (`test_auth_required_gate.py::TestTheDefault` asserts this passes today). This change adds to that surface an action that permanently deletes a media file, and one that lists the contents of the operator's download folder, and nothing records the decision. The second-order cost is larger: the inventory is the mechanism meant to catch the next destructive `addApiView` route, and it structurally cannot see this class.

**Fix:** Add an explicit residue inventory for `addApiView` routes keyed off `couchpotato.api.api`, one entry per destructive route naming the capability and the accepted reason, and a test that fails when a route in that registry has no entry. Prove it load-bearing by deleting the `renamer.operator_replace` entry. Add one request-level 401 test for the destructive route mirroring `TestTheRouteRequiresAuthentication`, hashing the target file across the refused request.

**Recurrence:** Yes by construction. `renamer.operator_candidates` is the sibling instance in this same diff. Beyond it, the entire `addApiView` registry is unaudited, so any prior or future destructive API route is in the same position.

---

#### M4. A killed operator replacement leaves a full-size staged copy in the library folder that nothing ever reports
**Lens:** lens-data (Medium). **AC:** FEAT-011 AC-DATA-13.
**Location:** `renamer/main.py:1240-1330` (operator entry point) vs `:478` (the only `_reportStaleStagingFiles` call site).

**Evidence (executed, real SIGKILL / exit 137 substituted for `os.replace` between staging and the swap):** the library file survived byte-identical at 112,000 bytes, the source survived, and `.cp-upgrade-e775cb800abb4366ab349a9d2d193138.part` (27,000 bytes) was left in the library folder. `grep -n _reportStaleStagingFiles renamer/main.py` returns exactly two lines: the definition at `:730` and one call at `:478`, inside `_moveRenamedFiles`' destination-collision branch. `_runOperatorReplacement` never reaches it, which the AC names explicitly as the requirement.

**Consequence:** On the prompting 20.3 GB case, a container restart mid-replacement silently consumes 20 GB of library storage under a dot-file name the scanner ignores, with nothing in the log naming it. For an operator who uses this feature and never hits an automatic destination collision, the reporting at `:730` is dead code. Recoverable by hand, which is why this is Medium.

**Fix:** Call `self._reportStaleStagingFiles(os.path.dirname(destination))` in `_runOperatorReplacement` immediately before `replace_atomically`, mirroring `:478`, and assert it in the operator test with an aged-mtime artefact.

**Recurrence:** No other new entry point stages files. The general class, a diagnostic proven only against the path it was written for and silently absent from a second caller, is worth watching if a third replacement entry point appears.

---

#### M5. No failure branch of the operator replacement has ever been executed by a test
**Lens:** lens-data (Medium). Sibling of H3, which is the mutation-proven instance.
**AC:** FEAT-011 AC-DATA-6, AC-QA-5.
**Location:** `tests/unit/test_replacement_operator_execution.py:73-74`, `:462`, `:483`.

**Evidence:** the only named outcomes imported and asserted are `REFUSED_SOURCE_IS_SYMLINK` and `REFUSED_DESTINATION_IS_SYMLINK`. `FAILED_STAGING`, `FAILED_SIZE_MISMATCH`, `FAILED_SWAP`, `FAILED_DESTINATION_CHANGED`, `REFUSED_SAME_FILE`, `REFUSED_SOURCE_CHANGED` and `REFUSED_IDENTITY_UNVERIFIABLE` appear nowhere; grep for ENOSPC across `tests/unit` finds only `test_extractor.py`. The lens drove four itself and the mechanism is correct every time: stage raises -> `failed_staging`; stage lands short -> `failed_size_mismatch`; `os.replace` PermissionError -> `failed_swap`; **a real ENOSPC**, staging a 3 MB source onto a 2 MB APFS volume created with `hdiutil` -> `failed_staging`. Destination byte-identical, source byte-identical, no `.cp-upgrade-*` survivor in all four.

**Consequence:** The code is right today and nothing in the repo would notice if it stopped being right. A future change to `swap.py`'s cleanup rule, or to the operator path's error handling, can silently turn a safe refusal into a destructive one with every gate green.

**Fix:** Add the five named cases to `test_replacement_operator_execution.py`, asserting the outcome constant, the destination hash and the source's presence individually; use a real small-volume ENOSPC as the AC requires rather than a mocked OSError; add the consuming-stage case proving the staged file is deliberately left when it is the only complete copy.

**Recurrence:** Yes, and it is the same class as C2: the operator tests assert on stand-ins (a kwarg being not-None, a route being registered) rather than on behaviour under failure. Expect the same shape in the FEAT-010 review-queue backend tests, which use hand-rolled `FakeDB` objects rather than a real `SQLiteAdapter` for every case except the ones the lens drove itself.

---

#### M6. The replay guard is incidental rather than the identity-at-decision-time check the criterion names, and it fails open when source disposal fails
**Lens:** lens-data (Medium). **AC:** FEAT-011 AC-DATA-4.
**Location:** `renamer/main.py:1304` and `:1425-1436`.

**Evidence (executed):** AC-DATA-4 states the mechanism explicitly, that identity must be captured at decision time. `main.py:1304` stats it at execution. An ordinary replay is refused, but **only because the source was deleted** (outcome `refused_no_source`, library unchanged). With `os.remove` forced to raise OSError, the branch `main.py:1429-1436` explicitly tolerates with a warning (a read-only or busy watch folder), the second execution returned `operator_replace` and performed a second swap. In the fixture the bytes were identical so nothing observable was lost, which is why this is Medium.

**Consequence:** The property AC-DATA-4 protects holds only as a side effect of a best-effort cleanup the code itself says may fail. A double-click on a slow 20 GB replacement is caught by the re-entrancy guard; a retry after the first attempt finished and its disposal failed is not, and the operator has no signal either way because the view returns success before the work starts.

**Fix:** Capture `identity_of(destination)` when the candidate list / confirmation is produced and pass it to `_executeOperatorReplacement` alongside the captured source size from C2. **Same change, same cost.**

**Recurrence:** Same root cause as C2. Fixing one without the other leaves half the class open.

---

#### M7. The operator replacement's database bookkeeping is recorded by the fixture and asserted by nobody
**Lens:** lens-qa (Medium). **AC:** FEAT-011 AC-QA-1.
**Location:** `tests/unit/test_replacement_operator_execution.py:133-149` against `renamer/main.py`'s call to `self._supersedeRelease(existing_release, group, destination)`.

**Evidence:** the world fixture appends `(release_id, status)` to `state['status_updates']` and `(release_id, path)` to `state['detached']`. **Neither list is read by any assertion in the file.** The nearest test asserts only that `state['calls']` contains an entry starting `bookkeeping:` and that it precedes disposal. Grep for `'ignored'` across all operator test modules finds it only as a parametrize input in the pure-decision test, never as an expected status.

**Consequence:** AC-QA-1 requires the superseded release to be set `ignored` with the destination detached. If `_supersedeRelease` set `done`, or detached a path belonging to a different release, every test still passes. Downstream that is a release document still claiming a file that has been overwritten, which is the stale-claimant condition AC-QA-9 exists to prevent and which makes the next automatic replacement decision act against the wrong quality.

**Fix:** Assert on the two lists already being collected: `state['status_updates'] == [('r-old', 'ignored')]` and `state['detached'] == [('r-old', dst)]` in the happy-path test. Break `_supersedeRelease`'s status argument and confirm the assertion fails.

**Recurrence:** Likely. A fixture that collects evidence no test reads is cheap to write and easy to leave behind. Check the other new fixtures in this diff for collected-but-unasserted state, particularly the event recorders in the renamer memory tests.

---

#### M8. A raising settings read aborts the whole renamer scan instead of forcing a re-decide, which is the opposite of the fail-open behaviour required
**Lens:** lens-qa (Medium). **AC:** FEAT-012 AC-QA-14.
**Location:** `renamer/main.py`, `scan()`: `current_settings = self._settingsSignature()` sits inside the try whose handler is `except Exception: log.error("Failed during renamer scan: %s", ...)`.

**Evidence:** `_folderSignature` swallows OSError and returns None, and the reuse condition requires `current_signature is not None`, so the filesystem half genuinely fails open, verified by the passing invalidation tests. `_settingsSignature` does not: `self.conf(key)` raising propagates to the outer handler, which logs and returns **before `fireEvent('scanner.scan', ...)` is ever reached**. No test drives either case; grep for a raising `conf` or a raising `stat` across both memory test modules returns nothing.

**Consequence:** AC-QA-14's rule is that "could not measure" must never be treated as "unchanged". For a settings read it is worse than that: the scan does not merely skip the memory, it processes no groups at all and logs a generic "Failed during renamer scan". A settings backend hiccup silently stops the renamer for that cycle with no group-level diagnosis.

**Fix:** Move the two signature computations into their own try, returning None on any exception so the memory is bypassed and the scan proceeds, and add the two fail-open tests AC-QA-14 names asserting the group is re-decided, nothing raises, and one rate-limited WARNING is emitted.

**Recurrence:** Same batch as H4/H5/H6. Not expected outside the FEAT-012 memory block, because the operator path resolves its settings inside narrower try blocks.

---

#### M9. The watch-folder confinement tests assert "not the success value" rather than the named refusal, and one of the four passes for an unrelated reason
**Lens:** lens-qa (Medium). **AC:** FEAT-011 AC-QA-4, AC-SEC-2.
**Location:** `tests/unit/test_replacement_operator_execution.py:292`, `:300`, `:308`, `:316`, all asserting `outcome != OPERATOR_REPLACE`.

**Evidence (mutation M1):** deleted the containment check from `_resolveOperatorSource`. Three of the four cases failed, but **`test_a_symlink_whose_target_leaves_the_watch_folder_is_refused` PASSED**, because `replace_atomically` independently refuses a symlinked source. Re-running the class's collective test under the same mutation printed the outcome set `{'operator_replace', 'operator_refused_source_outside_watch_folder', 'refused_no_source'}`: **with the guard gone, one hostile source name reached and completed a real destructive replacement.** File restored, sha256 `33aa5295...` unchanged.

**Consequence:** As written the class is saved only by `test_every_hostile_case_produces_the_same_named_refusal`, which pins that the four outcomes are identical but never says which value they must be. If that one test is weakened or split, three cases become non-specific and the symlink case becomes vacuous. AC-SEC-2 and AC-QA-5 both call for the named outcome constant, never a proxy.

**Fix:** Change all four assertions to `== OPERATOR_REFUSED_SOURCE_OUTSIDE_WATCH_FOLDER`, keeping the collective test as the belt. Re-run M1 and confirm all four now fail.

**Recurrence:** Yes, **the branch's most repeated test-quality shape.** AC-QA-7's concurrency test uses the same `second_outcome != OPERATOR_REPLACE` proxy; the modal template tests assert template-constant prose (H9); the a11y guards assert presence where the AC specifies measurement (L6). The repo's own memory names this as a recurring defect ("guards that check a stand-in"). A lint or review-checklist item for "assert the named constant, never `!=` the success value" would close it once instead of per round.

---

#### M10. Four FEAT-010 acceptance criteria have no test of any kind
**Lens:** lens-qa (Medium). **AC:** FEAT-010 AC-QA-3, AC-QA-18, AC-QA-19, AC-QA-21.
**Location:** `couchpotato/ui/__init__.py:325-328`; `couchpotato/ui/templates/wanted.html`.

**Evidence:** grep for `No movies found` across `tests/` matches only `review-queue.a11y.spec.ts` (a different assertion) and never for a raising `media.list` handler; grep for `zzz-not-a-status` returns nothing; grep for `filter=downloaded` across `tests/e2e/` returns nothing; no test counts requests to `/partial/movies` during grid load.

**Consequence:** AC-QA-3 matters most: `/partial/movies` swallows every exception and renders the same empty state as an empty library, so a backend failure reads to the user as "my films have vanished", **which is precisely the failure this feature exists to fix arriving on a different code path.** AC-QA-21 matters more than before, because `wanted.html`'s new `htmx:afterSwap` handler can now issue up to three extra grid refetches (`window.__cpReviewActionRetries <= 3`) with nothing asserting the bound.

**Fix:** AC-QA-3 is a five-line unit test in `test_fastapi_web.py` in the style of the existing charts/suggestions failure tests at `:1110`: install a raising `media.list` handler, assert 200, assert the empty-state text, assert no `Traceback` and no exception class name in the body. AC-QA-18/19/21 are E2E additions to `filters.spec.ts` reusing the `stubMovieGrid` helper at `:209` and a request counter.

**Recurrence:** Yes, and the shape is worth naming: the FEAT-010 criteria that survived are exactly the ones with a unit-level home; the four with no test are all ones the spec assigned to E2E or left unassigned. Expect the same split in FEAT-011's UI criteria.

---

#### M11. The criterion this whole feature exists to satisfy, that the film does not disappear after Mark Failed, has no assertion on the surface it names
**Lens:** lens-product (Medium). **AC:** FEAT-010 AC-PROD-7, and the `/library` half of AC-PROD-6.
**Location:** `tests/e2e/filters.spec.ts:467-514`.

**Evidence:** `git grep "toHaveAttribute('data-status', 'active')"` over `tests/` returns nothing. `filters.spec.ts:467` **stubs** `movie.searcher.mark_failed` with `{success: true}` so the real backend transition never happens, and its closing assertion is that the **other** card is still `downloaded`. `movie-detail.spec.ts:215-243` sits on the surface the AC explicitly excludes and is a conditional no-op whose comment claims no "downloaded" fixture exists, which this change made false. Separately, `git grep` finds no navigation to `/library` in any E2E spec, so AC-PROD-6's "the film is present on /library" half is likewise unasserted.

**Consequence:** The spec's Problem section opens with "A film that finishes downloading disappears from the application entirely." The regression that would reintroduce exactly that, a Mark Failed leaving the film in a status the widened Wanted query does not ask for, would ship green. The backend unit test makes the behaviour very likely correct today; what is missing is the guard that keeps it correct.

**Fix:** One E2E: on the Wanted page, confirm Mark Failed on the destructive seed movie **against the real backend**, then assert that card is present with `data-status="active"`. Two seeded fixtures already exist for exactly this. While there, add AC-PROD-6's missing half.

**Recurrence:** Both are the same omission: the state-change tests stop at the grid they started on and never check the destination the film moved to. Expect no instances outside FEAT-010.

---

#### M12. Neither in-memory store added by this change has a cap or an eviction order, and one is keyed on a caller-supplied value
**Lenses:** reviewer-verification (Medium), lens-data (Low), lens-operability (Low). Merged at Medium.
**AC:** FEAT-012 AC-OPS-12, AC-DATA-11.
**Location:** `renamer/main.py:382-390` (`_decision_memory`), `:213-217` (`_notified_parked`), `:116-126` (`scanView`).

**Evidence (executed):** 300 scans with 300 distinct `base_folder` values left `len(plugin._decision_memory) == 300`, no eviction. `base_folder` is client-reachable through `scanView` (`main.py:118`) and does not make the scan targeted, so each call writes a new key. Each value holds a frozenset of `(relpath, st_size, st_mtime_ns)` for every file walked. `_notified_parked` is likewise uncapped and never pruned: after a five-scan run it still held `{('media-1', 'declined_unverified_identity')}` with the group long gone from the folder. AC-OPS-12 requires "a stated hard cap ... with the eviction order named in the spec", proven by a 200-scan test; **AC-DATA-11's eviction clause is untestable as written because the cap it depends on does not exist.**

**Consequence:** Slow unbounded process memory growth in a container designed to run for months, driven by an input the API accepts, with a per-entry payload proportional to the file count of the named folder. Cheap on the recoverability ranking, since a restart clears it. The operational cost is that a stale `_notified_parked` entry **permanently suppresses the notify signal** for a (media, outcome) pair, so a film that is parked, cleared, and parked again the same way is never re-announced.

**Fix:** Add named cap constants to both with a stated eviction order (LRU on last-write), a test that scans a changing folder set and asserts the store never exceeds it, and the companion case that a targeted scan prunes nothing. Prune `_notified_parked` entries for groups absent from a full scan. Then AC-DATA-11's eviction case becomes writable.

**Recurrence:** Two instances already, both introduced by this change, which suggests the cap was never built rather than missed once.

---

#### M13. The change adds two new destructive failure surfaces and no runbook entry, no recovery procedure and no stated rollback
**Lens:** lens-operability (Medium). **AC:** FEAT-011 AC-OPS-10, AC-OPS-9; FEAT-012 AC-OPS-13.
**Location:** absence. `git diff --name-only master...ccdf6229 -- docs/` returns empty.

**Evidence:** no `docs/` file is touched by the diff. Grep for `operator_declined_no_file_to_replace` / `operator_refused_already_running` / `operator_refused_source_outside` across `docs/` and `specs/` returns nothing, so **not one** of the outcome constants the operator path can return is documented. Grep for `parked` / `already decided and unchanged` / `renamer_collision` across `docs/` returns nothing, so none of the three "3am" questions AC-OPS-13 names is answered. Grep for Rollback/Recovery in `specs/FEAT-011-replace-with-this-file.md` returns only the AC text itself at lines 168, 250, 251, never a procedure. The drift-proof tests both ACs require (in the style of `tests/unit/test_backup_policy_exempt_list.py`) do not exist.

**Consequence:** Two new failure modes ship with nothing for the person on the pager: an abandoned `.cp-upgrade-*.part` with no instructions for finding or removing it (M4), a release left claiming a replaced path with no correction procedure, and a renamer that can now go quiet with no documented way to make it look again (H6). The rollback claim, "a plain image re-tag with no data step", is asserted and never written down or tested.

**Fix:** One section in an existing `docs/` file naming every operator-path outcome constant and its remedy, the two recovery cases, FEAT-012's three questions and the forced-scan kill switch. Pin it with a test that imports the constants from `renamer/replacement.py` and asserts each appears in the document.

**Recurrence:** Two instances in one branch already (FEAT-011 AC-OPS-10 and FEAT-012 AC-OPS-13). Any further task in this plan adding an outcome constant needs the same entry, so **the drift-proof test is the fix that scales.**

---

#### M14. The collision WARNING keeps `log_suppressed`'s 300-second default window, the value this spec measured and rejected
**Lens:** lens-operability (Medium). **AC:** FEAT-012 AC-OPS-4.
**Location:** `renamer/main.py:600-607` (and `:763`, `:1547`).

**Evidence:** `grep -n 'window=' couchpotato/core/plugins/renamer/main.py` returns **no match**, so all three `log_suppressed` call sites take the default `LOG_SUPPRESSION_WINDOW = 300` (`couchpotato/core/logger.py:97`, `:140`). The AC requires "a single named module-level constant between 3600 and 86400 seconds, passed as the `window=` argument". The spec's own conflict table records that lens-security measured the unchanged 300-second window still emitting 734 records over 36 hours. No such constant exists anywhere in the diff, and no test injects a clock to prove either direction.

**Consequence:** The restatement bound for a parked group is twelve times tighter than the spec decided, so the backstop that must hold on the targeted-scan path (which never touches the memory) leaves roughly 576 records a day per parked group rather than one to twenty-four.

**Fix:** Define a module-level constant in the 3600 to 86400 range, pass it as `window=` at `:600` and at the new skip record (H7), and prove both directions against an injected clock (`log_suppressed` already takes `now=` for exactly this).

**Recurrence:** Same omission as H7 and probably the same cause. Both need the constant; fixing one leaves the other.

---

#### M15. Every invalidation of the decision memory is silent, and so is a group being dropped
**Lens:** lens-operability (Medium). **AC:** FEAT-012 AC-OPS-7, AC-OPS-6, AC-OPS-1, AC-OPS-14.
**Location:** `renamer/main.py:346-360` (the memory-comparison block falls through with no record) and `:395` (the silent pop).

**Evidence (measured across a five-scan sequence):** scan 3 changed `upgrade_replace`; the only WARNING was `log_suppressed`'s generic "The message above is repeating...", which names neither the media nor the trigger, and nothing said the memory had been invalidated. Scan 4 deleted the destination by hand; only the ordinary Processing/Moving/Moved records. Scan 5, with the parked group gone from the folder, emitted only `Renamer found 0 groups to process in <path>`: **no media id, no drop record.** There is no greppable token per trigger anywhere in the diff. Separately, AC-OPS-1's surviving record interpolates only `remembered['group_count']`, not both counts as required, and AC-OPS-14 is failed by four bare paths (`main.py:357-359`, `:395`, `:1391-1392`, `:1396-1399`) plus the "Leaving source folder in place" downgrade from `log.info` to `log.debug`.

**Consequence:** The two questions AC-OPS-13 says this feature creates are unanswerable from the log: "I changed a setting and nothing happened" and "the renamer has gone quiet but my download is still in /downloads". An operator cannot tell whether a settings edit was picked up, and cannot tell a working memory from one wrongly holding a group parked.

**Fix:** Emit one `log.info` per invalidation naming media/folder and a distinct greppable token per trigger (`source_changed`, `destination_changed`, `settings_changed`, `operator_forced`), and one at `:395` naming what was dropped. The comparison at `:346-360` already knows which signature differed, so the token is a branch, not new machinery.

**Recurrence:** Same class as H1: state transitions computed and acted on without being named in the log. Both the invalidation branch and the drop branch need records; fixing only one leaves the other as the next round's finding.

---

#### M16. The operator's source file is deleted from the watch folder with no log record on the success path
**Lens:** lens-operability (Medium). **AC:** FEAT-011 AC-OPS-12.
**Location:** `renamer/main.py:1412-1435` (`_disposeOfOperatorSource` logs only in its `except OSError` branch).

**Evidence (executed on a full successful replacement):** the source file was gone (`source still present: False`) and the complete record set for the whole operation was three lines: the About-to-replace WARNING, `INFO | Replaced a library copy: media m1, 720p -> 1080p (release rel-1 superseded)`, and the release-bookkeeping WARNING. None mentions a deletion. `os.remove(source)` at `:1430` sits inside a try whose only log call is in the except branch.

**Consequence:** A file the operator placed by hand disappears from their download folder with nothing in the log saying it was this feature that removed it. This path deliberately ignores `default_file_action`, **so it deletes even for operators whose configuration says copy.**

**Fix:** Log at INFO immediately after a successful `os.remove`, naming the media id and the fact that the operator-placed source was consumed, keeping paths out of it per the file's existing convention.

**Recurrence:** Contained to this method as far as the lens could see. The automatic path's `_disposeOfSourceAfterReplacement` (`main.py:962`) is not in this diff and was not audited. Worth one grep for other `os.remove`/`deleteFolder` calls added by the change.

---

#### M17. The one WARNING preceding an irreversible file destruction cannot tell an operator-initiated replacement from an automatic one
**Lens:** lens-operability (Medium). **AC:** FEAT-011 AC-OPS-2.
**Location:** `renamer/main.py:938-960` (`_announceImminentReplacement`), called from `:540` (automatic) and `:1300` (operator).

**Evidence:** one method, no operator parameter, both call sites. Measured on a real operator replacement: `WARNING | About to replace a library copy: media m1, 720p (300 bytes) -> 1080p (15000 bytes), superseding release rel-1. This destroys the old file.` Byte-identical in shape to the automatic path's record. No test asserts either half of the AC's requirement (marker present on the operator path, absent on the automatic one).

**Consequence:** This record is, by its own docstring, "the only thing that can explain the deletion afterwards". When a library file is found destroyed, the log cannot say whether a human asked for it or the upgrade logic decided it, which is the first question anyone asks and the one that decides whether it was a bug.

**Fix:** Add an `operator_initiated=False` parameter and interpolate a distinct literal token into the record when True, pinned in both directions.

**Recurrence:** The same reasoning applies to the `Replaced a library copy` INFO at `main.py:1045`, also shared and also unmarked. Fix both or the next round finds the second.

---

#### M18. The background-inert guard misses the mobile header and bottom nav, and its test asserts the implementation rather than the property
**Lens:** lens-accessibility (Medium). **AC:** FEAT-011 AC-A11Y-8.
**Location:** `movie_detail.html:692-701`; `tests/e2e/operator-replace-modal.a11y.spec.ts:431-456`.

**Evidence:** `setBackgroundInert()` sets `inert` on `#main-content` and `document.querySelector('aside')` only. `base.html` has two further body-level siblings of `<main>` carrying interactive content: `<header class="lg:hidden fixed top-0 ...">` at `:439` with the menu toggle, and `<nav class="lg:hidden fixed bottom-0 ..." aria-label="Mobile navigation">` at `:484`. Both are `display:none` at the accessibility project's 1280px and displayed at 393px, and neither is inerted. The test reads exactly `#main-content` and `aside`, **the same two elements the implementation sets**, so it cannot fail for a third element that was never inerted, and `operator-replace-modal.mobile.spec.ts` has no inert test at all.

**Consequence:** At phone width, with the replace dialog open, a screen reader's browse cursor can walk into the top bar and bottom navigation. `aria-modal="true"` mitigates this on most modern screen readers, but the team's own stated position (the comment at `:686-691` and the test rationale at `:425-430`) is that `aria-modal` and Tab trapping are insufficient and `inert` is required. By that standard the guard is incomplete exactly where it was never checked. Keyboard Tab is unaffected.

**Fix:** Inert by exclusion rather than enumeration: iterate `document.body.children` and set `inert` on each except the dialog's wrapper, restoring on close. Rewrite the test to assert **the property**, that no element outside the dialog is in the accessibility tree, rather than naming two ids, and run it in the mobile project too.

**Recurrence:** Yes. Any future dialog copying this component inherits the same two-element list. It is also the "guard checks a stand-in" shape already recorded as a recurring defect on this project: the assertion was derived from the code it is meant to police, so it can only ever confirm what was written.

---

#### M19. The keyboard-only flow is unproven at phone width and never reaches a commit
**Lens:** lens-accessibility (Medium). **AC:** FEAT-011 AC-A11Y-1, AC-A11Y-3.
**Location:** `tests/e2e/operator-replace-modal.mobile.spec.ts:77-260`.

**Evidence:** `grep -n "keyboard\|press("` over the mobile spec returns **no matches**: its four tests are overflow, in-viewport bounding boxes, a wheel gesture and target sizes. AC-A11Y-1 requires the flow driven with Tab, Shift+Tab, arrows, Enter, Space and Escape "on both the chromium and mobile-chrome projects", reaching a committed replacement and, separately, a cancel. In the accessibility project the only Enter is at `:188` (opening) and the only Space at `:689` (selecting a radio); the focus-ring test tabs onto the confirm control at `:699-701` and stops without activating it. Separately, AC-A11Y-3's Cancel-button path is covered by no test in any of the three operator-replace spec files, and neither Cancel nor Escape asserts zero calls to the replace endpoint via a route interceptor.

**Consequence:** The end-to-end keyboard path to the one action that destroys a file has never been executed. A regression breaking activation on the confirm control, for example the `disabled`/`aria-disabled` interaction at `movie_detail.html:519` (L3), would pass every test in the suite. At 393px, where an external keyboard or a switch device is the realistic AT, nothing is exercised at all.

**Fix:** Add one test to each project that opens by keyboard, arrows to a candidate, Space-selects, Tabs to confirm, presses Enter against a stubbed replace route, and asserts exactly one request plus the announced outcome; and a second that Tabs to Cancel, presses Enter, and asserts focus returns to the trigger with zero replace requests.

**Recurrence:** Yes, same class on the FEAT-010 surface: `review-queue.mobile.spec.ts` also contains zero keyboard interaction, so Mark Done and Mark Failed have no keyboard activation coverage at 393px either. **Both mobile specs test geometry only, which is the standing shape of this repo's mobile project.**

---

#### M20. The Wanted page's most destructive control uses `cp-error`, which no Tailwind token defines, so bulk Delete renders with no danger tint at all
**Lens:** lens-design (Medium). **AC:** FEAT-010 AC-DESIGN-13, a named one-line fix that was not made.
**Location:** `couchpotato/ui/templates/wanted.html:33`.

**Evidence:** the line still reads `class='px-2 py-1 text-[10px] rounded-md bg-cp-error/10 text-cp-error hover:bg-cp-error/20 transition-colors'`. `grep -rn cp-error couchpotato/` over the pinned tree returns **exactly this one line**, where AC-DESIGN-13 requires it to return nothing. `base.html:62-75` lists the `cp.*` palette: bg, card, surface, border, accent, accentHover, text, muted, success, warning, danger, blue. **There is no `error`**, so Tailwind generates no rule and the button paints as default text on a transparent background. `scripts/check_conformance.py` passed on 34 templates, so the CI gate does not catch an undefined token.

**Consequence:** This change deliberately improved the bulk-delete confirmation copy for AC-QA-20, and AC-DESIGN-13 says why the token fix is in scope with it: better copy on a control that does not look destructive is half a fix. Delete sits next to Refresh (accent-tinted) and Clear (muted) and reads as the least emphasised of the three, which is exactly backwards.

**Fix:** One line: `bg-cp-danger/10 text-cp-danger hover:bg-cp-danger/20`, matching `movie_cards.html:145` and `movie_detail.html:297`.

**Recurrence:** No further instances; the grep is exhaustive. Worth naming separately that `check_conformance.py` passed with an undefined colour token, so **this class of drift is currently undetectable by the CI gate.** A token allowlist derived from `base.html`'s `cp.*` block would make it mechanical.

---

#### M21. The card review actions throw away the specific, actionable error this change added on the server
**Lens:** lens-design (Medium). **AC: none.**
**Location:** `couchpotato/ui/templates/partials/movie_cards.html:135` and `:154`.

**Evidence:** this diff adds the `expected_status` optimistic-concurrency guard to `markDone` (`media/_base/media/main.py:678-682`), returning `{'success': False, 'error': 'Media status changed, refresh and try again'}`, which is plain, specific and tells the user what to do. The card's handler reads `else { toast('Failed to mark as done', 'error'); }` and never reads `d.error`. Same in the Mark Failed handler. `test_review_actions_backend.py` passes and asserts the server-side message, so the string exists and is simply not shown.

**Consequence:** The one case the new guard exists to catch, another session or the renamer moving the film on while the card is on screen, is reported as an unexplained failure. The user has no reason to refresh, clicks again, gets the same generic failure, and concludes the feature is broken rather than that their view is stale. **The branch paid for a good message and does not display it.**

**Fix:** One expression in each handler: `toast(d.error || 'Could not mark as done', 'error')`, matching `movie_detail.html:174`.

**Recurrence:** Yes, and fix both card handlers in the same round. The pre-existing detail-page handlers at `movie_detail.html:287` and `:296` have the identical shape and are outside this diff, so they are follow-up, but the pattern propagates: every new handler on this branch was copied from one of them.

---

#### M22. The detail page refreshes before the replacement has started, so the operator lands on a page describing the copy that is about to be destroyed
**Lenses:** lens-product (Medium, AC-PROD-7), lens-design (folded into their AC-DESIGN-11 finding).
**Location:** `movie_detail.html:766-777`.

**Evidence:** `confirmReplace()` on `data.success` announces "Replacement started" and immediately awaits `cpSwap('.../partial/movie/{{ movie_id }}' + window.location.search, '#movie-detail-container', 'innerHTML')`. The `data.success` it keys on is the unconditional `{'success': True}` returned before the thread has read a single byte. There is no polling and no completion callback anywhere in the component (`:648-825`). The delivery plan records this at tick 14: "Progress reporting beyond the in-flight refusal is NOT built and is recorded as debt."

**Consequence:** For the spec's own prompting case, a 20.3 GB copy across NAS mounts, the operator is shown a page asserting the old 17.0 GB copy is the current library file, for minutes, immediately after being told the replacement started. Combined with H1 they never see it change, and the natural next action is to click Replace again. No copy anywhere says the copy can take several minutes or not to close the page: grep for "minutes" over the rendered modal returns zero.

**Fix:** Either hold the modal open in its existing `replacing` in-flight state, add the copy AC-DESIGN-9 names ("This can take several minutes. Do not close this page."), and poll until a terminal outcome arrives before swapping; or, at minimum, **do not swap on "started"**: leave the page as it was and say the replacement is running in the background. The second is a two-line change and is honest.

**Recurrence:** One related instance elsewhere in the diff, **handled correctly**, worth citing as the pattern to copy: the card review actions set `window.__cpReviewActionMovieId` and re-fetch up to three times until the card's `data-status` has settled (`wanted.html:264-283`), because the author recognised the same read-after-write race there. The operator-replace path did not get that treatment.

---

#### M23. A film awaiting review is announced to screen-reader users by its raw internal status token, on the line the spec named as needing the fix
**Lens:** lens-product (Medium). **AC:** FEAT-010 AC-PROD-8.
**Location:** `couchpotato/ui/templates/partials/movie_cards.html:49`.

**Evidence:** the line is untouched by this diff and still reads `aria-label="{{ title }} ({{ year }}) - {{ 'wanted' if status == 'active' else status }}"`. Rendered: `aria-label="Bride Hard (2025) - downloaded"`. AC-PROD-8 names this exact line as "which currently interpolates the bare status" and requires the same user-facing term as the chip. Three of the four named surfaces were fixed (chip reads `Review`, badge reads `downloaded / review`, empty-state and announcer route through `statusLabel()`); this is the fourth. No test asserts the card link's accessible name.

**Consequence:** A sighted user sees "downloaded / review" and "Review"; a screen-reader user tabbing the grid hears "Bride Hard (2025) - downloaded, link" with no word connecting that card to the Review chip they would use to find it. The inconsistency is now the odd one out rather than uniform.

**Fix:** `{{ 'wanted' if status == 'active' else ('review' if status == 'downloaded' else status) }}`, and assert the poster link's accessible name in `review-queue.a11y.spec.ts` alongside the existing chip assertion.

**Recurrence:** Yes, **the branch's most repeated user-facing class**: three instances of an internal token reaching a human. This one; the replace-failure toast (`movie_detail.html:797`, `data.error` rendered verbatim, which the a11y test pins as `declined_not_better`, see H12); and the parked-film notification (`renamer/main.py:228`, `'"%s" is parked and needs a look: %s' % (media_title, outcome)`). **The third is built to FEAT-012's AC-OPS-5, which asks for "the outcome value" by name, so that one is a spec bug rather than a code defect.** Fixing all three together is cheaper than three rounds of the same paraphrase.

---

#### M24. The control that permanently deletes a film's library file wears the refresh icon
**Lens:** lens-design (Medium). **AC: none.**
**Location:** `movie_detail.html:384`.

**Evidence:** the trigger's SVG path `d="M16.023 9.348h4.992..."` appears three times in the tree: `wanted.html:46` (the Refresh Library button), `movie_cards.html:165` (the per-card refresh button) and this new destructive trigger. `docs/design-system/README.md`'s legacy glyph table maps this Heroicon, `arrow-path`, to `icon-refresh`. Rendering the action row for a downloaded movie gives Mark Done (success token), "Mark Failed & Re-search", "Replace with this file" and Delete, of which **three carry `bg-cp-danger/10` and only the new one carries an icon.**

**Consequence:** Three same-coloured red controls sit adjacent, two of which destroy an irreplaceable file and one of which does not, with no visual ranking. The only one distinguished by an icon is distinguished by a glyph that means "refresh" everywhere else in this UI, including on the sibling Wanted page. On a distracted scan the icon is what the eye lands on first, and it says the safest possible thing about the most dangerous control in the row.

**Fix:** Swap for a glyph whose meaning is not already spoken for (`arrows-right-left` or `arrow-path-rounded-square`, both Heroicons outline 24x24 stroke-1.5 and both unused), or drop the icon and let the label carry it, matching the neighbouring Delete and Mark Failed.

**Recurrence:** Likely one more instance of the broader class rather than of this glyph: `movie_releases.html:315` uses `x-circle`, at least semantically destructive. Expect the next destructive control added to this row to reach for whichever icon is nearest, **because nothing in CONFORMANCE.md says which glyphs are reserved for destructive actions.**

---

### LOW

---

#### L1. When a parked film has no resolved title, the new notification sends the raw download folder name to every configured third-party provider and stores it for 28 days
**Lens:** lens-security (Low). **AC:** FEAT-012 AC-SEC-8, whose letter is met.
**Location:** `renamer/main.py:221`, `:229-233`.

**Evidence (executed):** driving `Renamer.scan` over a parked group whose media has no title resolves `media_title` via `getTitle(library) or group.get('dirname') or 'Unknown'` and fires notify with `"Minions.and.Monsters.2015.1080p.BluRay.x264-GRP" is parked and needs a look: declined_unverified_identity`. AC-SEC-8's letter is met (no token beginning `/`), but the value is a directory name read off the operator's download folder, not decision metadata. **The path that produces it is the common one:** an unresolved identity is exactly why the group is parked, so the fallback fires precisely when the film could not be named.

**Consequence:** The scene release name of an unidentified download, including its source, group and quality markers, leaves the system to whatever notification providers are configured (Pushover, Telegram, Prowl) and is retained 28 days in the notification document (`notifications/core/main.py:42`, `:78-83`). A film title reaching a provider is an accepted design decision recorded in the spec; a filesystem-derived folder name is a different thing nobody chose, and it says more about how the operator obtains media than the title does.

**Fix:** Drop the dirname fallback: send "an unidentified download" (or the media id, which the data payload already carries) when `getTitle` returns nothing. One line at `main.py:221`. Extend the AC-SEC-8 assertion to cover the no-title case, since the current fixture always has a title and cannot reach this branch.

**Recurrence:** Yes, one more instance of the same expression at `main.py:1588`. That one is pre-existing and feeds a different sink; worth checking whether its sink is also outbound before deciding to leave it.

---

#### L2. A caller-supplied `base_folder` now drives an unbounded recursive walk-and-stat materialised in memory
**Lens:** lens-security (Low). **AC: none.**
**Location:** `renamer/main.py:128-160` (`_folderSignature`), `:292` (call site), `:115-121` (`scanView`).

**Evidence:** `scanView` takes `base_folder` straight from request kwargs and passes it to `renamer.scan`; `scan()` sets `scan_folder = base_folder or conf('from')` and, after the isdir check, calls `self._folderSignature(scan_folder)` **unconditionally** at `:292`. That method `os.walk`s the entire tree and appends one `(relpath, size, mtime_ns)` tuple per file into a list before freezing it. Master's `scan()` has no such call, so this is a surface the change adds. The docstring calls it "a cheap fingerprint", true for a watch folder and not for an arbitrary directory. The retained half is conditional; **the transient list build is not.**

**Consequence:** An authenticated caller issuing `GET /api/<key>/renamer.scan/?base_folder=/` makes the server walk the whole filesystem, including any mounted NAS, and materialise a tuple per file in RAM before any other check runs. On a media host that is millions of entries and an OOM of the container. Not a privilege gain, since the caller already holds the key; it is a new way for a mis-typed or replayed request to take the service down, on a route a cron also drives.

**Fix:** Only fingerprint the folder the memory is keyed on: skip `_folderSignature` entirely when `scan_folder` is not `conf('from')`, since a caller-supplied `base_folder` is already treated as carrying no authority elsewhere in this file. A cap on the entry count, returning None past it so the scan fails open, is the belt-and-braces version.

**Recurrence:** No other instance in this diff. The general shape, a request parameter reaching an unbounded filesystem walk, is worth watching on any future `addApiView` that accepts a folder.

---

#### L3. The committing control uses the `disabled` attribute the AC forbids, and the aria-busy/focus-retention half has no test
**Lens:** lens-accessibility (Low). **AC:** FEAT-011 AC-A11Y-6.
**Location:** `movie_detail.html:519`.

**Evidence:** `:disabled="!selected"` ships on the confirm control; AC-A11Y-6 says it "uses aria-disabled, never the disabled attribute". The comment at `:500-506` justifies it on focus-loss grounds, **and that reasoning holds**: the lens traced every write to `selected` (`open()` at `:668`, click at `:481`, `moveSelection` at `:719`) and none can clear it while the control is focused. But `grep -n aria-busy` over both operator-replace spec files returns nothing: the AC's required assertion (press Enter, activeElement unchanged, aria-busy `'true'`) exists nowhere, so the in-flight behaviour on a multi-minute file copy is unproven.

**Consequence:** Before a candidate is chosen the confirm control is out of the tab order, so a keyboard user tabbing the dialog meets Cancel and then wraps, with nothing telling them a selection is required. More materially, the in-flight state of a destructive operation the spec says can run for minutes has no coverage.

**Fix:** Replace with `:aria-disabled="(!selected).toString()"` and extend the existing `if (this.replacing || !this.selected) return;` guard at `:743` (already correct) to cover it; add the AC's own test. Note the focus-trap tests at `:319`/`:341`/`:362` use `button:not([disabled])` and need the same edit.

**Recurrence:** Confined to this control. The card review controls already do it the right way (`aria-disabled` plus a re-entry guard, `movie_cards.html:130-131`, `:146-147`), so it is inconsistent within one change rather than systemic.

---

#### L4. Focus after a card review action lands on the first card in the grid, not the next one
**Lens:** lens-accessibility (Low). **AC:** FEAT-010 AC-A11Y-9, whose mechanical clause is met.
**Location:** `wanted.html:360-374`.

**Evidence:** `focusAfterReviewAction()` does `document.querySelector('#movie-grid .poster-card:not([style*="display: none"]) a')`, returning the **first** visible card in document order regardless of which card was acted on. AC-A11Y-9's own wording names "the next card's link, or the movie-count region". The test at `review-queue.a11y.spec.ts:646-658` asserts only not-body, not-documentElement, still-attached and named, so it passes either way.

**Consequence:** After marking done a film partway through a grid, a keyboard user is returned to the top and must re-traverse everything they had already passed. On a Wanted list of thirty films that is a real cost, and it is what WCAG 2.4.3 asks focus order to preserve.

**Fix:** Record the acted-on card's index before triggering the reload (the handler already stashes `__cpReviewActionMovieId`) and prefer the card now occupying that index, falling back to the last card, then to `#movie-count`. Assert that the focused link belongs to the card that followed the acted-on one.

**Recurrence:** Single instance, but the same helper is the model any future grid action will copy, so fixing it now is cheaper than after the second caller exists.

---

#### L5. Neither of AC-DESIGN-15's phone-width assertions was written, and the chip group has no `flex-wrap` to satisfy the first
**Lens:** lens-design (Low). **AC:** FEAT-010 AC-DESIGN-15.
**Location:** `tests/e2e/review-queue.mobile.spec.ts:42-104`; `wanted.html:64`.

**Evidence:** the mobile spec contains exactly three tests, at `:42`, `:62` and `:83`, all the accessibility criteria its own header names (AC-A11Y-7, 8, 14). Nothing asserts the four-chip group wrapping rather than scrolling off, and nothing asserts each card's action row inside its card's bounding box with no clipped label. The chip container renders as `flex gap-1 text-[10px]` with **no `flex-wrap`**, so the four chips cannot wrap among themselves; only the whole group can wrap onto its own line via the parent's `flex-wrap` at `:21`. The criterion says the assertion must live in a `*.mobile.spec.ts` because the mobile project runs nothing else.

**Consequence:** Adding a fifth chip, or lengthening a label, silently pushes the group past 393px with nothing to catch it. The card action row is likelier to break first: at 393px the two-column grid gives each card roughly 174px, the row is two `flex-1` buttons plus `px-2.5` and `gap-2`, and "Mark Failed" at `text-[10px]` is close to the available width. The reflow test at `:83` catches a document-level overflow but not a label clipped inside a card.

**Fix:** Add `flex-wrap` to the chip container, then add the two assertions: the chip group's `scrollWidth <= clientWidth`, and for each review card the action row's bounding box contained within the card's with the button's `scrollWidth <= clientWidth`.

**Recurrence:** Yes, symmetrically. FEAT-011's AC-A11Y-13 mobile half **is** covered (`operator-replace-modal.mobile.spec.ts:100` checks the dialog, candidate rows and footer controls against the device width), so the modal has what the card row lacks. Expect any future chip or card control added at phone width to arrive without a bounding-box assertion.

---

#### L6. Several a11y guards assert presence where their AC specifies a measurement, and the focus-trap tests reuse the implementation's own selector
**Lens:** lens-accessibility (Low). **AC: none.**
**Location:** `review-queue.a11y.spec.ts:93-128`, `:190-196`; `operator-replace-modal.a11y.spec.ts:318-320`, `:340-342`, `:361-363`, `:553-555`.

**Evidence:** `FOCUS_RING_PROBE` reads `outlineWidth`, `outlineStyle` and `outlineColor` but the assertions only check `indicator.visible === true`; neither AC-A11Y-1's "3:1 non-text contrast" nor AC-A11Y-12's "2px accent ring with outline-offset 2px" is ever computed. The three focus-trap tests build their expected first/last elements from the string `'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'`, **byte-identical to `trapFocus()`'s own query at `movie_detail.html:794`**, so a wrong selector in the implementation produces a matching wrong expectation and the test still passes. The announcement tests at `:553` and `:571` poll for text but never assert the region updated exactly once, as AC-A11Y-5 requires. The lens verified the underlying properties hold today by computing them independently (ring 8.99:1 dark, 5.36:1 light; `toast()` at `base.html:260-263` does one clear-then-set), so these are regression gaps rather than live defects.

**Consequence:** If the focus ring were changed to 1px or a low-contrast colour, or `trapFocus`'s selector narrowed so it skipped a control, or a future refactor announced an outcome twice, every one of these tests would stay green. **The suite reports coverage of criteria it does not measure.**

**Fix:** Return the composited ring colour and the surface behind it from the probe and assert `>= 3:1` plus `outlineWidth '2px'` and `outlineOffset '2px'`. Derive first/last in the focus-trap tests from an independent source (the dialog's declared DOM order, or Playwright's accessibility snapshot). Wrap the announcers in a MutationObserver and assert one text change, **as `review-queue.a11y.spec.ts:279` already does correctly** for the empty-state announcer.

**Recurrence:** Yes: the same probe and the same contrast helper are copied into both new a11y spec files, so every focus-ring assertion in this diff shares the weakness. The correct pattern already exists in the same branch, which is the cheapest evidence the stricter form is achievable here.

---

#### L7. The downloaded/review badge no longer matches the pattern the design system documents, and the design system was not updated
**Lens:** lens-design (Low). **AC:** FEAT-010 AC-DESIGN-14, which passes on its operative clause.
**Location:** `movie_cards.html:89`; `docs/design-system/README.md`.

**Evidence:** the badge changed from `bg-cp-warning/20 text-cp-warning on-dark backdrop-blur-sm` to `bg-cp-warning text-black backdrop-blur-sm`, with a measured justification in the template comment (1.92:1 over poster artwork against the 4.5:1 floor). `README.md`'s Status & quality badges section still documents `downloaded/review bg-cp-warning/20 text-cp-warning`, and CLAUDE.md names that file as the visual source of truth. `check_conformance.py` passed, so nothing detected the divergence.

**Consequence:** The next person porting a badge reads the README, reproduces the translucent pattern over poster artwork, and reintroduces the contrast failure this change measured and fixed. The measurement that makes the solid variant necessary lives in a Jinja comment rather than the document people are told to follow.

**Fix:** Add the solid variant to README.md with the one-line reason: badges over poster artwork use solid `bg-cp-warning` with `text-black`, because a translucent tint sharing its hue with its text cannot reach 4.5:1 at any opacity.

**Recurrence:** One further instance in this diff of the same "fix recorded only in the template" class: `base.html:143-176` adds three testid-scoped background overrides (`review-mark-failed`, `operator-replace-confirm`, `release-mark-failed`) all correcting the same composited 4.46:1 for `bg-cp-danger/10` on a `cp-card` surface. **Three sites needing the same override is a token problem, not three component problems**, and none of it is in the design system doc either. Worth resolving once as a documented on-card danger variant.

---

#### L8. The same destructive action is named differently on the card and on the detail page
**Lens:** lens-design (Low). **AC: none.**
**Location:** `movie_cards.html:152` vs `movie_detail.html:300`.

**Evidence:** the card renders "Mark Failed"; the detail page renders "Mark Failed & Re-search". Both call `movie.searcher.mark_failed` with the same media_id and both carry identical `confirm()` text, so they are the same action with the same consequence. AC-DESIGN-7 pins the non-destructive twin to be character-identical across both surfaces and gives the reason. AC-DESIGN-8 names the detail page as the source for this control's token but says nothing about its label, so **the drift is inside the specification's blind spot rather than against it**.

**Consequence:** Small, but it lands on the control whose consequence the shorter label omits. "Mark Failed" does not say a fresh search starts immediately; "Mark Failed & Re-search" does. The card is the denser, more distracted surface of the two and carries the less informative label.

**Fix:** Use the detail page's label on the card; if it does not fit at `text-[10px]` in a `flex-1` button on a 174px card, shorten both surfaces together to one agreed label rather than keeping two.

**Recurrence:** One more pair on the same surface in the opposite direction: `movie_detail.html:278` reads "Mark as Done" while its review-gate twin at `:290` reads "Mark Done". Both pre-existing. Checking all four labels at once is a five-minute pass and closes the class.

---

#### L9. FEAT-012 ships with no statement of how the owner will tell on production whether it worked
**Lens:** lens-product (Low). **AC:** FEAT-012 AC-PROD-8, a spec-content criterion.
**Location:** `specs/FEAT-012-renamer-remembers-its-decisions.md:160`.

**Evidence:** `git grep -i "24 hours|we will know|tell.*worked|success measure|next parked download|notification list"` over the spec returns exactly one line: AC-PROD-8 itself. The spec has Problem (`:11`) and Costs (`:43`) sections but no success-measure sentence.

**Consequence:** The change ships to a production incident that ran ~1,100 scans over 36 hours with nothing written down saying what the owner should observe afterwards to know it is fixed. AC-OPS-3 and AC-OPS-5 supply the raw numbers but nobody turned them into an observation the owner can make. The likely outcome is that nobody checks, and the next recurrence is rediscovered rather than caught.

**Fix:** One sentence, agreeing with AC-OPS-3 and AC-OPS-5: after the next parked download, 24 hours of `docker logs` contain at most one "Destination already exists" record per restatement window for that media id, and the parked film appears in `notification.list`. Checkable today with no new instrumentation.

**Recurrence:** Not expected elsewhere. FEAT-011's AC-PROD-8 **is** its success measure and is stated concretely; FEAT-010's benefit is directly observable on the Wanted page. FEAT-012 is the one whose benefit is a non-event, which is exactly why it needed the sentence and exactly why it was easy to skip.

---

#### L10. The Review chip's partition and count properties are asserted only at the pure-function level, never against a rendered grid
**Lens:** lens-product (Low). **AC:** FEAT-010 AC-PROD-3, AC-PROD-4, both of which pass on behaviour.
**Location:** `review-queue.a11y.spec.ts:279-320`; `tests/unit/ui/movie-filter.spec.ts:60-92`.

**Evidence:** `matchesFilter` is well covered as a function (six cases, both directions). At grid level, every E2E that activates the Review chip either drives it **deliberately to empty** (`:279-301`) or measures contrast (`:459-480`); `:303-320` clicks it with review films present but asserts only that the announcer did not mutate. `git grep "setFilter('downloaded')"` over `filters.spec.ts` returns nothing, so the Review chip has no counterpart to the Wanted (`:72`) and Available (`:109`) filtering tests. The anti-vacuity half of AC-PROD-3 ("the visible count equals the number of seeded downloaded films, so the chip cannot pass by hiding everything") and AC-PROD-4's summation check are both unasserted.

**Consequence:** A future change breaking the wiring between the chip and `CP.ui.matchesFilter`, for example a `data-status` attribute rename which is exactly the coupling `wanted.html:412` depends on, leaves the unit tests green and the chip showing nothing, and **the only E2E that would notice is the one that expects it to show nothing.**

**Fix:** One E2E in `filters.spec.ts` alongside the existing chip tests: click Review, assert the visible card count equals two (the seeded downloaded films) and that the set of `data-status` values on visible cards is exactly `{'downloaded'}`; then assert the three chips' visible counts sum to the unfiltered count.

**Recurrence:** Expect no further instances: Wanted and Available already have grid-level tests, so Review is the one chip added by this change and the one left without.

---

#### L11. Two criteria are unmet because the measurement they require was never taken
**Lens:** lens-qa (Low). **AC:** FEAT-011 AC-QA-17, FEAT-010 AC-QA-8.
**Location:** `specs/FEAT-011-replace-with-this-file.md:162`; `specs/FEAT-010-review-queue-in-wanted.md:127`.

**Evidence:** grep for "throughput", "MB/s" and "measured staging" in the FEAT-011 spec matches only the AC text itself: no 1 GB+ staging measurement, no machine named, no page-cache state, no implied wall-clock for the 20.3 GB production case. AC-QA-8 requires a Stryker mutation score for `movie-filter.js` quoted in the PR body; not runnable in the worktree and no PR exists. By contrast FEAT-011 AC-QA-18 **is** met and was measured: 258 tests in 1.42s against a 10s ceiling (baseline 198 in 0.42s).

**Consequence:** AC-QA-17's measurement is the stated evidence for the backgrounded-versus-synchronous design decision, so that decision currently rests on an estimate. Since the branch also has no way to report a background failure (H1), backgrounding without the measurement compounds rather than mitigates.

**Fix:** Time one real staging copy of a 1 GB+ file to the library filesystem, record the machine, the page-cache state and the implied 20.3 GB wall-clock in the spec, and run `make mutation-changed` over `movie-filter.js` before the PR is raised.

**Recurrence:** Contained. These are the only two criteria across the three specs needing a number rather than a test, and FEAT-010 correctly declined to invent a latency budget without a baseline (AC-QA-21's note), which is the right call.

---

## 3. Conflicts arbitrated

Precedence order applied: **irrecoverable data loss > security > accessibility floor > operability > product/design > performance.** A tie above the accessibility line escalates to a human rather than resolving silently.

### A1. lens-security AC-SEC-4 PASS vs lens-data AC-DATA-3 FAIL, same code line

Both lenses examined `renamer/main.py:1303` and reached opposite verdicts.

- **lens-security** passed FEAT-011 AC-SEC-4 on a mutation: forcing `expected_source_size=None` failed exactly one test and left 19 green, so "the kwarg is present and the guard discriminates".
- **lens-data** failed FEAT-011 AC-DATA-3 by executing the harm: the value handed over is `os.path.getsize(source)` taken at execution, which `swap.py:190` then compares against a stat of the same file microseconds later. It grew the source between listing and execution and watched a complete 112,000-byte library file be destroyed by a 102,000-byte partial.

**Resolution: lens-data wins, and this is C2.** Both are correct about what they measured; lens-security's mutation proves the kwarg is passed and asserted, and the test it names asserts `expected_source_size is not None`, which is a stand-in for the behaviour rather than the behaviour. Irrecoverable data loss is the top of the precedence order and lens-data's evidence is an executed destruction of a real file. AC-SEC-4 should be re-read as PASS-on-plumbing / FAIL-on-semantics; the criterion as worded is satisfiable by a guard that cannot fail, which makes it a weak criterion (recorded as a spec observation, not a spec bug, since AC-DATA-3 covers the real property).

### A2. lens-security AC-SEC-7 PASS vs reviewer-verification AC-SEC-7 FAIL (FEAT-011)

- **lens-security** executed the no-key request and got 401 with the handler never invoked: the behaviour holds.
- **reviewer-verification** failed it because the AC also demands a request-level test, and grep shows the destructive route has none (the candidate-listing route does).

**Resolution: both are right and neither overrides the other.** Record as **PASS on behaviour, FAIL on coverage**. The auth gate works today; nothing pins it. Folded into M3, whose fix adds both the inventory entry and the request-level 401 test.

### A3. AC-DESIGN-14: the badge broke the documented design-system pattern to fix a measured contrast failure

lens-design resolved this itself, correctly: the badge moved from the documented translucent `bg-cp-warning/20 text-cp-warning on-dark` to solid `bg-cp-warning text-black` because the translucent form measured 1.92:1 over poster artwork. **Accessibility floor outranks design intent**, so the change stands; the design system document is what must move (L7). Recorded, not escalated.

### A4. AC-DATA-2's wording is stale against the owner's own AC-PROD-4 decision

lens-data found that with two completed releases at different qualities the operator path **refuses** (`operator_declined_ambiguous_file`) rather than selecting the named release, so the AC's literal wording ("the destination the confirmation names is the one actually replaced") cannot be satisfied as written. The refusal is documented at `replacement.py:187-192` as the AC-PROD-4 owner decision. **Resolution: the code follows the later decision; the AC text is stale.** No wrong file can be destroyed in this state. Recorded as a spec-text drift, not a defect.

### A5. ESCALATE — whether FEAT-011 (operator replace) ships on this branch at all

This is a tie **above the accessibility line** and is not the lenses' to resolve.

The operator-replace feature carries, on its own:
- **Irrecoverable data loss:** C2 (a partial file can destroy a complete library copy and both are then gone), H3 (the multi-file guard is untested and its removal is invisible), M5 (no failure branch has ever been executed by a test), M6 (the replay guard is incidental).
- **Security:** C1 (a GET with no origin check destroys a library file; re-firable from history, a prefetch or a cross-origin `<img src>`, with the api_key on every rendered page).
- **Operability/product:** H1 (every outcome invisible, five lenses), H8 (a crash mid-replacement never reaches the log), H9 (the confirmation names nothing), H10 (the picker offers `.nfo` files as replacements).

Set against that: `specs/PLAN-2026-08-30-review-queue-delivery.md` records T5, T5b and T5c as **partial or building**, so some of the FEAT-011 gaps are work not yet done rather than work done wrongly. FEAT-010 (review queue) and FEAT-012 (decision memory) are in materially better shape, and FEAT-010's own AC-SEC-1 defect (H2) is a one-line template fix.

**The decision for a human:** whether to fix all of the above before the PR, or split FEAT-011 out of this branch and ship FEAT-010 + FEAT-012 + T67 with H2, H4, H5, H6, H7, H11, M2 and M20 fixed. That is a scope call weighing irrecoverable data loss against delivery, and per the harness contract a tie above the accessibility line is escalated, never resolved silently.

---

## 4. AC verdict summary

All three specs were found and read, plus `specs/REMEDIATION-2026-08.md` (T67) and `specs/PLAN-2026-08-30-review-queue-delivery.md`. Criteria are therefore anchored, except where noted in the spec-bugs array.

### Totals

| Spec | PASS | FAIL | UNVERIFIABLE | Total judged |
|---|---:|---:|---:|---:|
| **FEAT-010** review queue | 34 | 10 | 6 | 50 |
| **FEAT-011** replace with this file | 34 | 33 | 4 | 71 |
| **FEAT-012** renamer remembers | 17 | 19 | 3 | 39 |
| **T67** cache fix | 0 | 0 | 0 | **0 (no AC exists)** |
| **Total** | **85** | **62** | **13** | **160** |

### By lens and spec

| | FEAT-010 | FEAT-011 | FEAT-012 |
|---|---|---|---|
| **AC-SEC** | 6 PASS, 1 FAIL (SEC-1) | 9 PASS, 3 FAIL (8, 9, 10) + SEC-7 contested (A2) | 5 PASS |
| **AC-QA** | 6 PASS, 4 FAIL (3, 18, 19, 21), 6 UNVERIFIABLE | 3 PASS, 10 FAIL (1, 2, 5, 7, 9, 12, 14, 15, 17, 19), 1 UNVERIFIABLE | 5 PASS, 7 FAIL (6, 7, 9, 10, 11, 12, 14), 1 UNVERIFIABLE |
| **AC-DESIGN** | 7 PASS, 2 FAIL (13, 15) | 4 PASS, 7 FAIL (3, 4, 5, 7, 9, 10, 11) | none declared |
| **AC-A11Y** | 14 PASS | 8 PASS, 5 FAIL (1, 3, 6, 8, 11), 1 UNVERIFIABLE | none declared |
| **AC-DATA** | none declared | 6 PASS, 5 FAIL (3, 4, 6, 11, 13), 2 UNVERIFIABLE | 5 PASS, 2 FAIL (6, 12), 1 UNVERIFIABLE |
| **AC-OPS** | none declared | 1 PASS, 9 FAIL (1, 2, 3, 4, 5, 9, 10, 11, 12) | 1 PASS, 8 FAIL (1, 3, 4, 6, 7, 12, 13, 14) |
| **AC-PROD** | 5 PASS, 3 FAIL (6, 7, 8) | 3 PASS, 3 FAIL (3, 4, 7) | 1 PASS, 2 FAIL (6, 8), 1 UNVERIFIABLE |

### What the shape says

- **FEAT-011's AC-OPS is 1 PASS out of 10.** That is not ten separate defects; it is one root cause (the operator path was built fire-and-forget with the outcome value dropped) expressed ten ways. H1 closes most of it.
- **FEAT-012's AC-OPS is 1 PASS out of 9**, for the mirror-image reason: the memory computes state transitions and names none of them in the log.
- **FEAT-010 is in materially better shape**, with the single exception of AC-SEC-1 (H2), which the spec explicitly said would be fixed in this change and was not.
- **All 13 UNVERIFIABLE verdicts trace to two causes**: the Playwright tier was never run by anybody (12), and no PR body exists to hold the mutation logs and measurements four criteria require.
- **T67 (the SQLite cache fix) carries no acceptance criteria of any kind.** M2 is a genuine new data-at-rest surface, created by that fix, that no criterion decided.

---

## 5. Verdict

**FINDINGS.** No lens returned BLOCKED; all seven returned FINDINGS. Two Critical, twelve High, twenty-four Medium, eleven Low, across 62 failed acceptance criteria.

**Before this branch is pushed to a PR:**

1. **Fix both Criticals.** C1 (destructive GET with no origin check) and C2 (self-comparing source-size guard, which destroyed a real file under test). Both are irrecoverable-data-loss or security class and neither is a judgment call.
2. **Resolve the ESCALATE in A5 with the owner:** fix FEAT-011 fully, or split it out and ship FEAT-010 + FEAT-012 + T67. The plan already records T5/T5b/T5c as partial, so "not yet done" is a legitimate answer; shipping it as-is is not.
3. **Fix the remaining High findings on whatever ships**, in particular H2 (a one-line template fix the spec already promised), H4, H5, H6, H7 and H11.
4. **Run the Playwright E2E tier.** It was never executed by any lens, it carries every accessibility and mobile claim on the branch, and two lenses independently found tests in it that pass against server responses the server cannot produce (H12). Until it runs, thirteen criteria stay UNVERIFIABLE and the a11y floor is asserted rather than proven.
5. **Run `make verify` end to end on the tip**, which no lens did.
6. **Triage dependencies before the PR** per §3a: open Dependabot PRs, `pip-audit`, Trivy on the image, and the lockfile. No lens ran any dependency scan.
7. **Then re-run this review cycle.** Per the bounded fix loop: these are rounds 1 to 3 territory (resume the same implementer), but note that the branch has now produced a new class of defect rather than more instances of a known one on the FEAT-011 destructive path, which is the signal to question the approach rather than spend another round on it.

**One process finding outside the code:** six lenses found the worktree on a different branch than the one under review, and one had its branch ref deleted and recreated by another session mid-run. Parallel sessions are mutating shared checkouts under running reviews. Every lens recovered correctly and recorded it, but the next one may not.
