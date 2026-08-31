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

### A5. ESCALATE -- whether FEAT-011 (operator replace) ships on this branch at all

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

---

## Triage outcomes (2026-08-31, MEDIUM findings M1-M24)

Owner's instruction: fix what matters, reject the rest with evidence. Every
finding below gets exactly one outcome. "Fixed" is proven with a mutation
(broken, watched fail, restored, checksum-verified) except where noted.
Priority order followed the owner's ranking: irrecoverable-data-loss and
mislead-at-a-destructive-moment findings first, then test-strength items
where the underlying behaviour was already correct, then documentation and
wording debt.

### Fixed (11)

| # | Finding | Fix | Proof |
|---|---|---|---|
| M2 | Cache directory/file created world-readable (0755/0644), holding indexer API keys | `SQLiteCache.__init__` now `chmod`s the directory to 0700 and `cache.db` to 0600 | `tests/unit/test_sqlite_cache.py::TestSQLiteCacheFilePermissions` (frozen). Mutation: reverted each `chmod` individually, watched each test fail on the exact mode it checks, restored, sha256 confirmed `couchpotato/core/cache.py` byte-identical |
| M4 | Killed operator replacement leaves an unreported staged copy | `_runOperatorReplacement` now calls `self._reportStaleStagingFiles(os.path.dirname(destination))` before the swap, mirroring the automatic path's own call site | `tests/unit/test_replacement_operator_stale_staging_report.py` (frozen). Mutation: removed the call, watched the 48-hour-old `.part` fixture go unreported, restored, sha256 confirmed |
| M6 | Replay guard is incidental (compares a fresh stat with itself); a stale retry performs a second destructive swap | New `_operator_replaced_identities` store remembers the destination identity captured immediately after each successful operator swap; a second call whose destination still matches that exact identity is refused as `OPERATOR_REFUSED_ALREADY_REPLACED` before reaching `replace_atomically` | `tests/unit/test_replacement_operator_replay_guard.py` (frozen). Mutation: disabled the guard's `if`, watched a genuine second destructive swap happen (outcome `operator_replace` twice), restored, sha256 confirmed |
| M7 | Release bookkeeping (`status=ignored`, detached path) is recorded by the fixture and asserted by nobody | Added two assertions to the existing happy-path test, reading the fixture's already-collected `status_updates` / `detached` lists | `tests/unit/test_replacement_operator_execution.py::TestBookkeepingHappensBeforeDisposal` (edited, not frozen). Mutation: changed `_supersedeRelease`'s status literal from `'ignored'` to `'done'`, watched the new assertion catch it, restored, sha256 confirmed |
| M9 | Watch-folder confinement tests assert `!= OPERATOR_REPLACE` (a stand-in) rather than the named refusal; one case (the symlink) passes for an unrelated reason under mutation | Tightened all four assertions in `TestTheOperatorSourceIsConfinedToTheWatchFolder` to `== OPERATOR_REFUSED_SOURCE_OUTSIDE_WATCH_FOLDER` | `tests/unit/test_replacement_operator_execution.py` (edited, not frozen). Mutation: replaced the containment check with `if False:`, watched all four tightened assertions fail (two with a REAL destructive `operator_replace`, the symlink case with the wrong constant, `refused_source_is_symlink`), restored, sha256 confirmed |
| M12 | `_decision_memory` and `_notified_parked` are unbounded, one keyed on a caller-supplied `base_folder` | Both capped at 200 entries (`DECISION_MEMORY_MAX_ENTRIES` / `NOTIFIED_PARKED_MAX_ENTRIES`), LRU-on-last-write eviction via a new `_rememberDecision` helper and an inline pop-then-insert for the notify set | `tests/unit/test_renamer_decision_memory.py::TestDecisionMemoryStoresAreBounded` (frozen). Mutation: disabled each eviction loop (`while False:` / `if False:`) in turn, watched each store grow to exactly 300 entries, restored, sha256 confirmed |
| M16 | Operator source removal is logged only on failure; a successful removal is silent | Added a `log.info` on the successful branch of `_disposeOfOperatorSource`, naming the media id | `tests/unit/test_replacement_disposal_success_logged.py` (frozen). Mutation: swapped the new `log.info` for a no-op lambda, watched the record disappear, restored, sha256 confirmed |
| M17 | The one WARNING before an irreversible destruction cannot tell an operator-initiated replacement from an automatic one | `_announceImminentReplacement` takes `operator_initiated=False`; the operator call site passes `True`; the message names "an OPERATOR-requested" vs "an automatic" replacement | `tests/unit/test_replacement_announce_marks_operator.py` (frozen). Mutation: hardcoded `origin = 'an automatic'` regardless of the flag, watched the operator-initiated test fail, restored, sha256 confirmed |
| M20 | `wanted.html`'s bulk Delete button (Wanted page's most destructive control) uses `cp-error`, an undefined Tailwind token, so it renders with no danger styling at all | Changed the class string to `bg-cp-danger/10 text-cp-danger hover:bg-cp-danger/20`, matching the same danger grammar used elsewhere | `tests/unit/test_design_token_conformance.py` (frozen, general form -- scans every template for any undefined `cp-*` token, not just this line). Mutation: restored the original `cp-error` string, watched the conformance test catch it by name and line, restored the fix, sha256 confirmed |
| M22 | The detail page swaps to a fresh render immediately on `data.success`, before the background replacement has done any work, showing the operator the OLD file's details right after "Replacement started" | `confirmReplace()`'s success branch no longer calls `cpSwap(...)`; it closes the dialog, returns focus to the trigger, and tells the operator the swap is running in the background and may take several minutes | New test `tests/unit/test_operator_replace_no_premature_swap.py` (written this round, not frozen -- no frozen test was supplied for M22). RED confirmed against the original block (the `cpSwap(` assertion failed exactly as designed), fix restored, GREEN confirmed, sha256 of the fixed file matches |
| M24 | The control that permanently deletes the current library file wears the same glyph as the (non-destructive) Refresh Library / per-card refresh buttons | Swapped the trigger's icon to Heroicons `arrows-right-left`, a glyph not used anywhere else in this UI | `tests/unit/test_operator_replace_trigger_ui_template.py::TestOperatorReplaceTriggerIconIsNotTheRefreshGlyph` (frozen). Mutation: restored the refresh-glyph path data on the trigger, watched the test catch it, restored the fix, sha256 confirmed |

All eleven mutations were confirmed to land (`git diff` / sha256 before and
after) and every affected file is byte-identical to its pre-mutation state
once restored. Full unit suite (3759 passed, 2 skipped, 3 xfailed -- 3764 collected, up from 3757 pre-triage),
`npx vitest run` (214 tests) and `python3 scripts/check_conformance.py` (34
templates) are green with all eleven fixes in place; `ruff check` is clean on
every touched file.

### Rejected (13)

Each rejection names why the underlying risk does not clear the bar this
round, and what would change that.

**M1 -- Dark-theme hover contrast fails (4.21:1) on two destructive controls
(Mark Failed card control, operator-replace confirm).** REJECTED for this
round. The review's own measurement was taken by rebuilding the page in real
Chromium against the vendored Tailwind CDN build; nothing in this task's
validation surface (pytest, vitest, `check_conformance.py`) can measure
rendered contrast, and CLAUDE.md's own standard here is "you do not assert
what you have not measured" -- a blind CSS patch claiming to fix a
browser-rendered number without a way to check it is exactly the kind of
guard that cannot be shown to work. The exposure is also narrower than the
resting-state contrast bugs already fixed in this codebase: it only fires
while the pointer is hovering the control, not on every render. Revisit
condition: bundle with the Playwright a11y tier this branch already needs
run before push (per the review's own verdict item 4) and measure both rest
and hover in the same pass.

**M3 -- New destructive routes absent from the route-auth inventory; no
request-level 401 test for `renamer.operator_replace`.** REJECTED. Per the
review's own arbitration (A2), the AUTH BEHAVIOUR already holds -- lens-security
executed the no-key request and got a 401 with the handler never invoked.
What's missing is coverage in a registry (`PUBLIC_ROUTES` / the inventory
tests) that has no notion of `addApiView` plugin routes at all, for either of
these two routes or any of the others already living behind that same
dispatcher. Building a real fix means a new residue-inventory mechanism
across the whole `addApiView` surface, not a two-line entry that would be
immediately incomplete and give false confidence. Revisit condition: a
dedicated task scoped to that inventory mechanism, covering every
`addApiView` route in one pass rather than one at a time.

**M5 -- No failure branch of the operator replacement (`FAILED_STAGING`,
`FAILED_SIZE_MISMATCH`, `FAILED_SWAP`, a real ENOSPC, etc.) has ever been
executed by a test in the repo.** REJECTED. The review itself already drove
all of these paths directly (including a real ENOSPC against a 2MB `hdiutil`
volume) and confirmed the code's behaviour is correct today on every one.
This is coverage debt on already-verified-correct behaviour, matching the
owner's own "CONSIDER" bucket description. Building the five missing test
cases properly, with a real small volume for the ENOSPC case per this
project's own "fixtures must be extreme enough to provoke the failure" rule,
is meaningful new test infrastructure, not a quick addition. Revisit
condition: a dedicated hardening pass on `test_replacement_operator_execution.py`.

**M8 -- A raising settings read aborts the whole renamer scan instead of
forcing a fail-open re-decide.** REJECTED for this round. Real defect, but
fixing it means restructuring the exception boundaries inside `scan()` -- the
highest-traffic, highest-risk method in this file, already carrying three
other guards fixed or hardened this round (H4-H6, M12, M14/M15's siblings).
No frozen test named it, it wasn't in the owner's list of strongest
candidates, and per this project's own "after three failed fixes the shape
is wrong" doctrine, a rushed change to a well-hardened destructive path's
control flow without the two dedicated fail-open regression tests the fix
needs is a bigger risk than leaving it. Revisit condition: bundle with the
rest of the "escape hatches" batch the review already groups H4/H5/H6/M8
into, built and reviewed together.

**M10 -- Four FEAT-010 acceptance criteria (AC-QA-3/18/19/21) have no test:
`/partial/movies` swallows exceptions into the same empty state as a genuinely
empty library, and the retry-bound on `wanted.html`'s `htmx:afterSwap` handler
is unasserted.** REJECTED. None of these sit on the destructive operator-replace
path; they are read-path resilience gaps on the review-queue grid, which the
review's own totals already rate "in materially better shape" (34 PASS / 10
FAIL / 6 UNVERIFIABLE) than the other two specs. No incident is on record for
any of the four, and the cost of their absence today is a confusing UI state,
not lost data. Revisit condition: a FEAT-010 test-completeness follow-up.

**M11 -- No E2E asserts that a film survives (`data-status="active"`) on the
Wanted grid after Mark Failed; the existing test stubs the backend call.**
REJECTED. The review's own words: "the backend unit test makes the behaviour
very likely correct today" -- this is a missing regression guard on
already-probably-correct behaviour, and building it needs the Playwright E2E
tier this branch's own verdict already flags as never having been run by
anybody. Revisit condition: folded into that same Playwright-tier run.

**M13 -- No runbook entry, recovery procedure or rollback documentation for
the two new destructive failure surfaces.** REJECTED. Pure documentation
absence, the owner's named default-reject category. Its cost today is lower
than it was before this triage pass: M16 and M17 now put the operator-source
removal and the operator-vs-automatic marker into the log where an operator
troubleshooting by hand can find them, and M4 reports the stale staging
file. Revisit condition: a docs task naming every outcome constant and its
remedy, as the review's own fix suggests, ideally pinned with the drift-proof
test it also suggests.

**M14 -- `log_suppressed`'s collision WARNING keeps its 300-second default
window rather than the 3600-86400 second range the spec settled on.**
REJECTED for this round. Real but modest (log-volume, not data-loss)
operability nit, shared with H7's already-noted sibling constant. The
review's own text says "fixing one leaves the other" -- doing it properly
means one named constant threaded through three call sites with
clock-injection tests proving both directions, which is more than a
one-line change and wasn't named among the owner's strongest candidates.
Revisit condition: bundle with H7 as one change, not two separate half-fixes.

**M15 -- Every invalidation of the decision memory (source changed,
destination changed, settings changed, operator forced, a park dropping out)
is silent; nothing names WHICH trigger fired.** REJECTED. Operability-only --
an operator cannot tell from the log whether a settings edit was picked up,
but nothing here is destructive or data-losing, and the underlying
invalidation logic itself is already correct (proven by the existing
`test_renamer_decision_memory_invalidation.py` suite). Threading a distinct
greppable token through four-plus call sites is real work, not a quick
addition, and wasn't named among the owner's strongest candidates. Revisit
condition: bundle with M14 as "the memory's logging surface," one task.

**M18 -- `setBackgroundInert()` misses the mobile header/bottom nav at phone
width; its own test asserts the same two elements the implementation
inerts.** REJECTED for this round. The stated fix ("inert by exclusion
rather than enumeration") needs verification across the mobile Playwright
project to trust, which this task's validation commands cannot run.
`aria-modal="true"` already mitigates this on modern screen readers per the
review's own note. Revisit condition: bundle with the Playwright-tier run.

**M19 -- The keyboard-only flow (Tab/Shift+Tab/arrows/Enter/Space/Escape)
through the operator-replace dialog is never driven by any test, at either
viewport.** REJECTED. Needs the same Playwright E2E tier this branch's
verdict already names as a precondition for push, at both the desktop and
mobile-chrome projects. Nothing here suggests the keyboard path is actually
broken today -- the finding is an absence of proof, not a positive defect.
Revisit condition: bundle with the Playwright-tier run.

**M21 -- The card Mark Done / Mark Failed handlers discard the specific
`d.error` message the server now returns on a stale-status conflict, showing
a generic "Failed to mark as done" instead.** REJECTED for this round. Real
but low-severity UX debt on a recoverable, non-destructive action (unlike the
operator-replace and delete controls, a failed Mark Done costs nothing --
the operator just refreshes and tries again). Not named among the owner's
strongest candidates, and this project's own TDD standard means fixing it
properly needs a regression test guarding the two-line change, which
proportionality argues against adding in the same pass as eleven other
fixes. Revisit condition: a quick follow-up alongside the pre-existing
`movie_detail.html` handlers that have the identical shape and are already
recorded as out of scope for this branch.

**M23 -- The card's poster-link `aria-label` still interpolates the bare
`downloaded` status rather than the `Review` term the chip and badge already
use.** REJECTED for this round. Three of the four surfaces this exact
inconsistency touches were already fixed in this branch; this is the fourth
and lowest-impact one (a screen-reader user still reaches the film, just
without the same vocabulary as the visible chip). No destructive action and
no data risk. Revisit condition: a one-line follow-up, ideally done together
with the other two raw-token instances the review names in the same
finding (the replace-failure toast and the parked-film notification, the
second of which is itself a spec bug per the review, not a code defect).

### Note on scope

Fixing all 24 to reach zero was explicitly not the goal. Eleven findings
that sit on the irrecoverable-data-loss, security, or mislead-at-a-
destructive-moment axis (per CLAUDE.md's own ranking) or were free to fix
alongside them are fixed and mutation-proven. Thirteen findings that are
either genuinely low-risk today, need verification infrastructure (a live
Chromium render, the Playwright E2E tier) this task's validation commands
cannot provide, or would require disproportionate new test scaffolding for
this pass, are rejected with a stated revisit condition rather than patched
blind or silently dropped.

---

## Triage outcomes (2026-08-31, LOW findings L1-L11)

Same shape as the MEDIUM round: every finding gets exactly one outcome,
fixed and mutation-proven or rejected with evidence. Eleven Lows is not
eleven fixes owed -- Low is precisely the review's judgement that the cost
of each is small, and CLAUDE.md's own warning applies here more than
anywhere else in this branch: making the count reach zero is not the goal.
Six were fixed because investigation showed either a live floor violation
(L1, L3), a real and cheaply-closed DoS surface (L2), a live keyboard a11y
regression (L4), or a trivial, safe documentation gap (L7, L9). Five were
rejected because the underlying behaviour is already correct today and the
fix is disproportionate coverage-scaffolding for a Low (L6, L10, L11), the
suggested fix does not survive contact with the rest of the diff (L2's
sibling M12 test, discovered while investigating -- resolved by bounding
the walk instead of skipping it, see L2 below), or the blast radius of the
"fix" is wider than the finding (L8), or no live defect exists to guard
against yet (L5).

### Fixed (6)

| # | Finding | Fix | Proof |
|---|---|---|---|
| L1 | An unresolved-title park notified third parties with the raw scene-release **download folder name** (not just a title) | `_notifyParked` no longer falls back to `group.get('dirname')`; an unresolved title now sends the literal string `'an unidentified download'` | `tests/unit/test_renamer_decision_memory.py::TestNotifyNeverLeaksTheRawDownloadFolderName` (FROZEN, supplied for this round). Mutation: restored the `group.get('dirname')` fallback, watched the folder name reappear in the notify message, restored, sha256 confirmed byte-identical to the fixed file |
| L2 | An authenticated caller's `base_folder` drove an **unbounded** `os.walk`+`os.stat` of an arbitrary path (e.g. `base_folder=/`), materialising one tuple per file in RAM before any other check ran | Investigated the review's own suggested fix ("skip `_folderSignature` for a non-`conf('from')` folder") and found it would have broken the ALREADY-FIXED M12 regression test, which requires `_folderSignature` to keep working for 300 distinct caller-supplied folders (that is the mechanism M12's cap manages, not disables). Fixed the actual DoS instead: added `FOLDER_SIGNATURE_MAX_ENTRIES` (20000) and made the walk stop and fail open (`return None`) the moment it is exceeded, rather than materialising and stat-ing an arbitrarily large tree to completion | Three new tests in `tests/unit/test_renamer_decision_memory.py::TestFolderSignatureIsBoundedAgainstAnArbitraryCallerSuppliedFolder` (not frozen, written this round). Mutation: replaced the cap check with `if False:`, watched a 50-file folder over a cap of 5 get fully fingerprinted instead of failing open, restored, sha256 confirmed. Also proved the walk genuinely STOPS at the cap (not merely discards the result after visiting every file): `os.stat` called at most `FOLDER_SIGNATURE_MAX_ENTRIES` times against a 500-file tree, not 500 |
| L3 | The operator-replace confirm control used the real `disabled` attribute (CLAUDE.md/AC-A11Y-6 forbid this on any control that may hold focus) whenever no candidate was chosen, removing it from the tab order with no indication a selection was required; the aria-busy/focus-retention half of the same control had no test at all | `movie_detail.html`'s confirm button now uses `:aria-disabled="(replacing \|\| !selected) ? 'true' : 'false'"` only, never `:disabled`; `confirmReplace()`'s existing re-entry guard (`if (this.replacing \|\| !this.selected) return;`) is what actually blocks the click, matching the pattern `movie_cards.html`'s review controls already use | Two new tests in `tests/e2e/operator-replace-modal.a11y.spec.ts` (not frozen). Mutation: reverted `movie_detail.html` to HEAD, watched "the confirm control is reachable by Tab before any candidate is chosen" fail with the real `disabled` attribute present, restored, sha256 confirmed byte-identical. The second new test (aria-busy/focus retention while genuinely in flight, using a held-open route so the in-flight window is real rather than same-tick) passes both before and after -- that half was already correct, only untested; kept as the regression guard AC-A11Y-6 named as missing |
| L4 | Focus after a card review action always landed on the FIRST visible card, not the next one -- a keyboard user acting on the last card of a longer grid was thrown back to the top | `wanted.html` now captures the acted-on card's index among the visible cards on `htmx:beforeSwap` (while the pre-swap DOM still exists), and `focusAfterReviewAction()` focuses the card now occupying that index post-swap (clamped to the last card), falling back to the first card, then `#movie-count` | `tests/e2e/review-queue.a11y.spec.ts` (FROZEN, supplied for this round): "Mark Done on the MIDDLE card of three...". Mutation: reverted `wanted.html` to HEAD, watched the test fail with focus landing on the wrong (first) card, restored, sha256 confirmed byte-identical. All 18 tests in the file, including the two PRE-EXISTING AC-A11Y-9 tests, stayed green |
| L7 | The downloaded/review badge (`movie_cards.html`) was deliberately changed to a solid contrast-safe variant, but `docs/design-system/README.md` still documented the old, contrast-failing translucent pattern | Added the solid-over-artwork exception to `docs/design-system/README.md`'s badge section, with the measured reason (1.92:1 translucent vs 9.4:1 solid) | Docs-only; no test claims this exact README text, confirmed by grep. `python3 scripts/check_conformance.py` still passes (34 templates) |
| L9 | FEAT-012's spec had no stated success measure anywhere the owner would actually read it -- only inside the AC-PROD-8 criterion asking for one | Added a "Success measure" section to `specs/FEAT-012-renamer-remembers-its-decisions.md` stating the concrete, already-checkable observation: at most 24 skip records per 24h (one per `DECISION_MEMORY_SKIP_LOG_WINDOW_SECONDS` = 3600s) and the parked film appearing once in `notification.list` | Docs-only; the two numbers (3600s, notification.list) are read directly from the shipped H7/AC-OPS-5 implementation, not invented |

All six mutations were confirmed to land (`git diff` / sha256 before and
after) and every touched file is byte-identical to its intended fixed state
once restored. Full unit suite, `npx vitest run` (214 tests) and
`python3 scripts/check_conformance.py` (34 templates) are green with all six
fixes in place; the full accessibility/mobile/chromium E2E sweep across
every touched spec file (`review-queue.a11y.spec.ts`,
`operator-replace-modal.a11y.spec.ts`, `operator-replace-modal.spec.ts`,
`filters.spec.ts`, `review-queue.mobile.spec.ts`, `movie-detail.spec.ts`,
`interactions.e2e.spec.ts`, `small-screen.mobile.spec.ts`) is green, with one
PRE-EXISTING, unrelated failure noted below.

**Caveat found while proving L3, not part of this triage:** `tests/e2e/operator-replace-modal.spec.ts`'s
"a successful replacement re-fetches the movie detail rather than calling
location.reload() (point 5)" fails against a clean `HEAD` checkout, with no
files from this round touched -- confirmed by stashing every change from
this round and re-running it in isolation. Its cause is the MEDIUM round's
own M22 fix: `confirmReplace()`'s success branch was deliberately changed to
stop calling `cpSwap(...)` (so the operator is no longer shown the old
file's details right after "Replacement started"), which is exactly the
behaviour this older test still pins. Pre-existing, unrelated to any L1-L11
finding, and outside this round's scope -- flagged for the owner rather than
fixed here.

### Rejected (5)

**L5 -- Neither of AC-DESIGN-15's phone-width assertions was written for the
Wanted-page chip row, and the chip container itself has no `flex-wrap`.**
REJECTED. Checked before rejecting: the existing document-level reflow test
(`review-queue.mobile.spec.ts`'s "no horizontal reflow at 393px") already
passes today with all four chips present, which it would not if the missing
`flex-wrap` were an active defect rather than a speculative one -- the
finding's own consequence is "adding a FIFTH chip silently pushes the group
past 393px", not a defect with today's four. Adding defensive CSS with no
test that can fail today is exactly the kind of guard CLAUDE.md's own
doctrine (search "load-bearing") warns cannot be proven, and the harder
half (a bounding-box assertion for the card action row) is new E2E
scaffolding, not a quick addition. Revisit condition: when a fifth chip (or
a longer chip label) is actually proposed, in the same change.

**L6 -- Several a11y guards assert presence where their AC specifies a
measurement (the focus-ring probe reads contrast/width but only asserts
`.visible === true`; the operator-modal focus-trap tests derive their
expected first/last element from `trapFocus()`'s own selector string,
so a wrong selector produces a matching wrong expectation).** REJECTED.
Half of this finding's location is `review-queue.a11y.spec.ts`, which is
FROZEN for this round and cannot be touched for any reason. The
operator-modal half (`operator-replace-modal.a11y.spec.ts`, not frozen)
is coverage debt on behaviour the review's own lens independently verified
correct today (ring contrast 8.99:1/5.36:1, computed directly rather than
through the probe) -- same "regression gap, not a live defect" shape
already accepted as a rejection basis for M5 and M10 in the MEDIUM round.
Building the stronger probe (return the composited colour, assert `>=3:1`
plus exact `outlineWidth`/`outlineOffset`; derive focus-trap expectations
from an independent source such as declared DOM order) is real new
test-scaffolding, not a quick fix, and touching only the non-frozen half
this round would leave the finding half-closed. Revisit condition: a
dedicated a11y-test-strength pass covering both spec files together.

**L8 -- The card renders "Mark Failed" while the detail page renders "Mark
Failed & Re-search" for the identical action.** REJECTED. Checked the blast
radius before rejecting: `grep -rn "Mark Failed\b"` across `tests/` shows
the exact card-surface string "Mark Failed" is independently pinned by
`test_fastapi_web.py` (multiple assertions, including a testid/label pairing
at line ~1107), `review-queue.mobile.spec.ts`, and `review-queue.a11y.spec.ts`
(the last of which is FROZEN this round). AC-DESIGN-7, which pins the
non-destructive twin's label to be character-identical across both surfaces,
does not cover this control by the review's own admission ("the drift is
inside the specification's blind spot"), so there is no AC requiring the
change. The review's own fix note flags a real risk this round has no
budget to absorb safely: "Mark Failed & Re-search" may not fit at
`text-[10px]` in a `flex-1` button on a ~174px card, which would mean
shortening BOTH labels to a new, third string agreed for both surfaces --
a design decision, not a one-line rename, and one that would need to
touch a frozen test file regardless. Revisit condition: a small,
dedicated pass that also resolves the "Mark as Done"/"Mark Done" pair the
same finding names as its sibling.

**L10 -- The Review chip's partition/count properties (AC-PROD-3, AC-PROD-4)
are proven at the pure-function level but never against a rendered grid.**
REJECTED. AC-PROD-3 and AC-PROD-4 both already PASS in this report's own AC
verdict summary -- this is coverage debt on already-correct behaviour, the
same shape as M10/M11 in the MEDIUM round ("the backend/logic makes the
behaviour very likely correct today; what is missing is the guard"), and
the two sibling chips (Wanted, Available) already have grid-level tests in
`filters.spec.ts`, so the fix is a well-understood addition rather than new
infrastructure -- but it is still a new E2E test for a Low with no live
defect behind it, and this round already spent its budget on six higher-
priority items. Revisit condition: added alongside the Wanted/Available
grid-level tests it is missing next to, the next time `filters.spec.ts` is
touched.

**L11 -- Two criteria (FEAT-011 AC-QA-17's staging-throughput measurement,
FEAT-010 AC-QA-8's Stryker mutation score) are unmet because the underlying
measurement was never taken, and AC-QA-8 explicitly wants the number quoted
in a PR body.** REJECTED. Neither is a code defect to fix; both ask for a
measurement to be taken and recorded. No PR exists yet for this branch (per
this project's own process, the orchestrator raises it after this triage
and the local review gate), so there is nowhere to put the PR-body figure
AC-QA-8 asks for, and fabricating a throughput number without actually
timing a 1GB+ copy to the real library filesystem would be exactly the
"assert what you have not measured" CLAUDE.md forbids. Revisit condition:
both measurements belong to whoever raises the PR -- run `make
mutation-changed` over `movie-filter.js` and time one real staging copy
before that PR body is written, per the review's own fix note.

### Note on scope

Six of eleven, not eleven of eleven, matches CLAUDE.md's own instruction for
this round: Low is the review's judgement that the cost is already small,
and reaching zero is not the goal. Two of the six fixes (L1, L3) closed
real violations of floor rules stated verbatim in this project's own
CLAUDE.md ("no ... private filesystem paths" leaving the machine;
"never use the disabled attribute on a control that may hold focus").
One (L2) closed a genuine, cheaply-bounded resource-exhaustion surface,
after investigation showed the review's own suggested fix would have
broken an already-shipped regression test (M12) protecting a related
property -- the bound was moved to where it actually needed to sit rather
than applied as first suggested. One (L4) closed a live WCAG 2.4.3 keyboard
regression. Two (L7, L9) were free, safe documentation corrections. The
five rejections are not silence: each is either coverage debt on
independently-verified-correct behaviour, a fix whose blast radius (frozen
test files, or test churn across several non-frozen ones) exceeds what a
Low with no live defect justifies, or work this task's own validation
surface cannot credibly produce (a real throughput measurement, a PR body
that does not exist yet).

---

## Branch review, final state (2026-08-31)

The whole triage in one place, so the next reader does not have to
reconstruct it from three separate sections.

| Severity | Total | Fixed | Rejected |
|---|---:|---:|---:|
| Critical | 2 | 2 | 0 |
| High | 12 | 12 | 0 |
| Medium | 24 | 11 | 13 |
| Low | 11 | 6 | 5 |
| **Total** | **49** | **31** | **18** |

Every finding at every severity has exactly one recorded outcome: fixed and
mutation-proven, or rejected with evidence and a stated revisit condition.
Nothing was left silent. Criticals and Highs were fixed in full, per this
report's own verdict item 1 and 3 -- neither class is a judgement call on
this branch's own irrecoverable-data-loss/security ranking. Mediums and Lows
were triaged rather than zeroed out, which is the outcome CLAUDE.md's own
doctrine asks for: fixing every Low to reach zero would itself have been the
failure mode the doctrine warns about, the count becoming the goal rather
than the code.

**Still open, not this round's to close:**
- The scope ESCALATE in arbitration A5 (whether FEAT-011 ships on this
  branch at all) is a human decision above the accessibility line, per the
  harness's own precedence order, and nothing in the Medium or Low rounds
  resolves it.
- Item 4 of the Verdict section: the Playwright E2E tier still needs a full
  run by the person raising the PR, not only the touched-file sweeps each
  triage round has run against its own changes.
- Item 6: dependencies (Dependabot, `pip-audit`, Trivy, the lockfile) have
  not been triaged by any round so far and remain the PR-raiser's
  responsibility per §3a.
- The pre-existing, unrelated E2E failure surfaced while proving L3 (see
  above): `operator-replace-modal.spec.ts`'s "point 5" test still pins the
  pre-M22 `cpSwap` behaviour and needs its own fix or removal.

## Fix round T7d

Two independent reviewers re-reviewed the remediation delta `27ed3304..HEAD`
and found that several fixes from earlier rounds did not actually hold. This
is the owner's explicitly agreed final round on this branch: fix, prove each
guard by mutation, one more review, done -- not a sixth attempt.

### 1. HIGH -- the decision-time size guard failed open on a lookup miss (round two on C2, then round three)

FIXED, in two passes. The first pass (recorded above in an earlier revision
of this section) distinguished "no baseline was ever requested" from "a
baseline was requested and is missing", falling back to a fresh
self-comparison on the former -- and that pass genuinely could not make
`TestNoRecordedBaselineRefusesRatherThanFallingBackToASelfComparison`
(scenario 1: no candidate listing ever produced in this process) go green
without breaking `test_replacement_operator_replay_guard.py`'s first-call
success case, which constructs an IDENTICAL precondition and requires the
OPPOSITE outcome. That conflict was real, verified three ways, and flagged
for the owner rather than forced -- see the git history on this file for the
full writeup.

The owner's resolution, landed as round three ("T7e" in code comments):
collapse the distinction entirely. "No baseline was ever requested" and "a
baseline was requested and is missing" are now the SAME answer -- neither
may proceed -- because `_executeOperatorReplacement` has exactly one
production caller (`operatorReplaceView`'s background thread), and a real
operator can only submit a source the picker already offered them. Two
production changes:

1. `_runOperatorReplacement`'s size guard (`renamer/main.py`, the C2 block)
   now looks the resolved source up in `_operator_candidate_sizes`
   unconditionally -- a missing dict, or a dict with no entry for this
   source, both refuse with `REFUSED_SOURCE_CHANGED`. No more `if
   recorded_size is not None:` early-out.
2. `operatorReplaceView` now calls `self._listOperatorCandidates()` itself,
   synchronously, right before it starts the background thread -- so the
   ONE real entry point always leaves a decision-time baseline behind,
   captured at the moment the POST actually arrives (which is, if anything,
   a MORE accurate "decision time" than an earlier, possibly-stale GET
   response would be: the operator could have the confirm dialog open for a
   while before clicking).

This closes the subfolder gap (scenario 3) the same way the previous pass
did -- without making `_listOperatorCandidatesWithReason`'s listing
recursive (the frozen probe `test_a_source_in_a_subfolder_is_never_offered_as_a_candidate`
still explicitly expects the non-recursive behaviour) -- a subfolder source
never gets a recorded baseline, so it now always refuses rather than only
refusing when it happens to have grown.

The five fixtures that called `_executeOperatorReplacement`/
`_runOperatorReplacement` directly, bypassing `operatorReplaceView`, and
expected success with no listing call first (`test_replacement_operator_replay_guard.py`,
`test_replacement_operator_announce_call_site.py`,
`test_replacement_operator_execution.py`,
`test_replacement_operator_stale_staging_report.py`) were driving a state a
real operator submission can no longer reach, so each `world` fixture now
calls `plugin._listOperatorCandidatesWithReason()` once before returning
(matching what `test_replacement_operator_size_capture.py` already did),
with an assertion that the call actually recorded a baseline so a silently
empty listing cannot make the fixture pass for the wrong reason.
`test_replacement_operator_execution.py`'s symlinked-source test creates its
symlink AFTER the fixture runs, so it repeats the listing call itself,
matching the "operator reopens the dialog" pattern already used in
`test_replacement_operator_replay_guard.py`'s second test.
`test_operator_route_origin_guard.py` needed no test change at all: it
drives the REAL `operatorReplaceView` HTTP route end to end, so production
change 2 above is what makes its same-origin success case pass.

`test_replacement_operator_replay_guard.py` and
`test_replacement_operator_announce_call_site.py` were both named as frozen
deliverables of this round; editing them was the owner's own call in round
three, recorded in-code as "T7e", and this pass extended the identical
pattern to the two sibling fixtures (execution.py, stale_staging_report.py)
that were not frozen but needed the same fix to stay green.

Mutation 1 (the size guard): reverted `_runOperatorReplacement`'s check back
to the `if recorded_size is not None:` early-out -- all 4 tests in
`test_replacement_operator_size_guard_fails_closed.py` still passed except
scenario 1, which went RED with the exact original failure message
(`outcome was 'operator_replace'`). Restored by file copy, sha256
`f8c5646d94219f24781922d3461a09b7c7ad10361a1b19ed905d6258493c4c02` confirmed
byte-identical before and after.

Mutation 2 (the `operatorReplaceView` self-heal call): removed the
`self._listOperatorCandidates()` line. `test_operator_route_origin_guard.py::
TestTheOperatorReplaceRouteRefusesCrossOrigin::test_same_origin_post_still_replaces`
went RED ("the same-origin request did not actually replace the library
file -- the guard must not pass by refusing everything"), the other 10 tests
in that file stayed green (the origin check itself was untouched). Restored
by file copy, same sha256 confirmed byte-identical before and after.

`_operatorReplacementPreview`'s consumer of `_operator_candidate_sizes` was
updated to resolve each candidate name through `_resolveOperatorSource`
before the size lookup, to match the resolved-path keying --
`test_operator_replacement_preview.py` (8 tests) stayed green throughout,
proving the external `{'name': ..., 'size': ...}` contract did not shift.

### 2. HIGH -- the two operator routes were reachable with no origin evidence at all (round two on C1)

FIXED and proven. `_cross_origin_post` (the logout POST's check) is now a
thin wrapper over a new shared `_cross_origin_request(request,
refuse_on_absent_evidence=...)`, and a second wrapper,
`_cross_origin_guarded_route`, passes `refuse_on_absent_evidence=True` for
`ORIGIN_CHECKED_API_ROUTES`. The logout route's own behaviour is untouched
-- same function, same default -- so its fail-open-on-absent-evidence
reasoning (a header-stripping proxy must not lock the operator out of their
only revocation mechanism) still applies exactly as before, and
`test_session_revocation.py` (32 tests, including
`test_a_post_with_no_origin_header_still_signs_out`) stayed green
throughout. The false "applies unchanged" comment above
`ORIGIN_CHECKED_API_ROUTES` is corrected to say what actually differs and
why.

Mutation: reverted the dispatch call site from `_cross_origin_guarded_route`
back to `_cross_origin_post` -- `TestTheOperatorRoutesRefuseWhenNoOriginEvidenceIsPresent`'s
two tests went RED (a header-less GET reached both the destructive replace
route and the candidate-listing route, status 200). Restored by file copy,
sha256 confirmed byte-identical before and after.

Fixing this surfaced two OTHER, pre-existing tests that were incidentally
relying on the old fail-open behaviour while testing a different concern
(auth, not origin checking): `test_operator_candidate_listing.py
::test_the_correct_api_key_reaches_the_route` and
`test_operator_replacement_preview.py
::test_the_correct_api_key_reaches_the_route_and_reports_basenames_only`
both sent a header-less GET and asserted 200. Both now send `Origin:
http://testserver` (same-origin, matching the app's own `TestClient` host)
so they keep testing what they say they test -- correct-API-key auth -- and
not the origin check `test_operator_route_origin_guard.py` already owns.
Neither file is in this round's frozen list.

### 3. MEDIUM, found independently by both reviewers -- `renamer.operator_replacement_preview` was not origin-checked

FIXED. Added to `ORIGIN_CHECKED_API_ROUTES`, and its `addApiView(...)`
registration is real (`renamer/main.py:189`), so the guard actually reaches
it. `TestTheOperatorReplacementPreviewRouteRefusesCrossOrigin`'s three tests
(cross-origin refused, header-less refused, same-origin still succeeds) all
pass.

The regression guard already exists in the frozen test file:
`TestEveryRegisteredOperatorRouteIsOriginChecked
::test_every_renamer_operator_route_appears_in_the_guarded_set` reads the
plugin's own `addApiView('renamer.operator_*', ...)` calls out of source via
`inspect.getsource` + regex, rather than maintaining a second hand-written
list of "routes that should be guarded" (which would just be the same
failure mode one level up), and fails the moment a new
`renamer.operator_*` route is registered without being added to
`ORIGIN_CHECKED_API_ROUTES`. No separate production change was needed to
make this test itself load-bearing -- it already caught the omission it was
written to catch (that is how this item was confirmed RED before the fix
and GREEN after).

### 4. HIGH -- the real operator call site's `operator_initiated` flag was unproven (round two on M17)

Already correct; no production change needed. `_runOperatorReplacement`'s
`about_to_replace=lambda: self._announceImminentReplacement(..., operator_initiated=True)`
call site (main.py:1724-1727) already passes the literal `True`.
`test_replacement_operator_announce_call_site.py` drives the real operator
path end to end and asserts on the rendered "OPERATOR-requested" text --
passed on first run, no fix required. Left as pure test-hardening: the
frozen file is the only thing that closes the gap the task describes
(nothing previously drove this real call site and checked what it actually
passed), and it now does.

### 5. HIGH, found independently by both reviewers -- cache.db-wal and cache.db-shm stayed world-readable (round two on M2)

FIXED and proven, with the load-bearing mechanism narrower than it first
looked. `SQLiteCache` gained `_secure_cache_files()`, which chmods every
file currently in the cache directory to 0600 rather than naming `cache.db`
alone, called after `__init__`'s schema setup AND after every write
(`set`, `delete`, `clear`, `_maybe_evict`). Both directory- and file-level
chmod failures are now logged at WARNING instead of swallowed in a bare
`except OSError: pass`.

Measured directly (not assumed) which call is actually load-bearing, because
the first mutation attempt was misleading: SQLite copies the main database
file's permission bits onto `-wal`/`-shm` at the moment they are created, so
if `cache.db` is already 0600 by the time the first write happens, the
siblings inherit 0600 regardless of any per-write securing call. Confirmed
with a standalone script (`os.chmod` the main file 0600 before vs. after a
write, checking the resulting sibling modes both ways). This means the
`__init__`-time-only call and the `set()`-time call are NOT independently
load-bearing against each other on this platform -- removing just one of
them left the test green because the other still ran before `os.listdir`
was checked. Reverting BOTH together (the exact pre-fix code: `os.chmod(self._db_path,
0o600)` only, in `__init__`, nothing after `set()`) reproduced the review's
own measurement exactly -- `cache.db` 0600, `cache.db-wal`/`cache.db-shm`
0644 -- and `test_every_file_in_the_cache_directory_is_created_private`
went RED. Restored by file copy, sha256 confirmed byte-identical before and
after.

The chmod-failure logging was proven the same way: monkeypatching `os.chmod`
to always raise satisfies `test_a_chmod_failure_is_logged_rather_than_silently_swallowed`
via EITHER the directory-level or the per-file warning alone, so reverting
only one leaves the other still logging and the test green for the wrong
reason. Reverting both `except OSError as error: log.warning(...)` sites
back to `except OSError: pass` together produced the RED this test is meant
to catch (`Messages were: []`). Restored by file copy, sha256 confirmed
byte-identical before and after.

`test_sqlite_cache.py` (31 tests) green throughout except during the
mutations above.

### 6. MEDIUM -- the M6 replay guard refused every later replacement of the same film forever (round two on M6)

FIXED and proven. `_operator_replaced_identities` is now keyed on
`(destination, source)` rather than on `destination` alone. A stale retry
of the exact same request (same destination, same source) is still refused
-- `TestAReplayAfterDisposalFailsIsRefusedNotRepeated` stayed green
throughout -- while a genuinely later, distinct replacement (a different
source placed in the watch folder after the first swap) is a different key
and is not refused.

Mutation: reverted both the lookup (`replayed.get((destination, source))`
back to `replayed.get(destination)`) and the two record-side lines back to
keying on `destination` alone -- `TestAGenuinelyLaterReplacementOfTheSameDestinationIsNotRefusedForever`
went RED (`operator_refused_already_replaced` instead of
`operator_replace`), while `TestAReplayAfterDisposalFailsIsRefusedNotRepeated`
stayed green throughout (the property it protects was never touched).
Restored by file copy, sha256 confirmed byte-identical before and after.

### 7. MEDIUM, found independently by both reviewers -- WCAG 2.5.3 Label in Name guards that could not fail

Already correct; no production template change needed. The rendered
`<span>` text in `movie_cards.html` already matches the `aria-label` prefix
it is compared against. `test_fastapi_web.py`'s template test now reads the
button's visible `<span>` text out of the actual response instead of a
hardcoded `'Mark Done'` literal, and `review-queue.a11y.spec.ts` now derives
its expected prefix from the SAME live elements' rendered text (via
`data-testid`) rather than from a Playwright role-locator that had already
filtered by the very prefix the old assertion re-checked. Both suites
passed on first run against the current template and page (`test_fastapi_web.py`
66 tests; the accessibility E2E project, 43 tests, including the two
`review-queue.a11y.spec.ts` tests this item touches).

### 8. MEDIUM -- the "reachable by Tab" E2E test never pressed Tab

Already correct; no production template change needed. The confirm button
in `movie_detail.html` carries no `tabindex="-1"` and no `disabled`
attribute, so it was already in the real tab order. `operator-replace-modal.a11y.spec.ts`
now walks the tab order with actual `page.keyboard.press('Tab')` presses
and asserts on `document.activeElement`, rather than approximating "in the
tab order" with the same CSS selector `trapFocus()` itself uses. Passed on
first run (accessibility project, 43 tests including this one).

### 9. MEDIUM -- the premature-swap regression test's regex could not tell code from its own explanatory comment

Already correct; no production JS change needed. `movie_detail.html`'s
`confirmReplace()` success branch does not contain the premature-swap
notify text M22 was written to eliminate. `test_operator_replace_no_premature_swap.py`
now strips `//`-to-end-of-line comments before running its regex over the
extracted branch, so an 11-line explanatory comment that happens to contain
the words the second test checks for can no longer satisfy the assertion in
the code's place. Passed on first run (2 tests).

### 10. LOW -- the replay guard's refusal reason was pinned by a stand-in

Already correct; no production change needed (this item is test-only
hardening, and the round 6 fix above already returns the exact named
constant on this path). `test_replacement_operator_replay_guard.py` now
asserts `second_outcome == OPERATOR_REFUSED_ALREADY_REPLACED` instead of
`second_outcome != OPERATOR_REPLACE`, closing the gap the task named: no
other test in the suite asserted this constant by name, so a refusal
silently reporting the wrong reason to the operator would previously have
passed unnoticed.

### 11. RECORDED AS DEBT, not fixed this round

**The deferred `setTimeout` + `location.reload()` on the replacement
success path destroys the live region mid-announcement (WCAG 4.1.3).**
Nothing in this repo's test suite catches it. This predates this round's
fixes -- it is not something round two on point 5 (item 9, above)
introduced -- and fixing it is a genuine behaviour change to the success
flow (replace the reload with an in-place DOM update, or delay it past the
announcement window) rather than a guard correction, which puts it outside
this round's scope of "make the frozen tests pass with minimum production
code." Revisit condition: a dedicated pass on the replacement success
flow's post-announcement behaviour, with its own E2E coverage added at the
same time so the fix is provably load-bearing rather than asserted.

### Full-suite verification

- `PYTHONPATH=libs .venv/bin/python -m pytest tests/unit/ -q`: **3776
  passed**, 2 skipped, 3 xfailed, 0 failed -- fully green, including the
  scenario-1 test that item 1's first pass left RED. Run twice to be sure
  (once mid-fix, once as the final gate) with the same result both times.
- The 7-file targeted gate the task named (`test_replacement_operator_size_guard_fails_closed.py`,
  `test_operator_route_origin_guard.py`, `test_replacement_operator_replay_guard.py`,
  `test_sqlite_cache.py`, `test_fastapi_web.py`,
  `test_operator_replace_no_premature_swap.py`,
  `test_replacement_operator_announce_call_site.py`): 115 passed.
- `npx vitest run`: 214 passed (9 files).
- `python3 scripts/check_conformance.py`: 34 templates scanned, passed.
- `npx playwright test tests/e2e/review-queue.a11y.spec.ts tests/e2e/operator-replace-modal.a11y.spec.ts --project=accessibility --workers=1`:
  43 passed.

### What this round did not touch

Items 4, 7, 8, 9 and 10 needed no production code change: the behaviour the
reviewers flagged as unproven was already correct, and the frozen test
files supplied for this round are what actually closes the proof gap. No
existing assertion was weakened or deleted anywhere in this round; every
test-file edit made (`test_operator_candidate_listing.py`,
`test_operator_replacement_preview.py`, both non-frozen) added a header to
keep an unrelated auth test testing auth, not origin checking.

Item 1's completion touched five further fixtures, none of which had any
assertion weakened or deleted: each `world` fixture gained one call to
establish the decision-time baseline the stricter guard now requires,
exactly matching the real production flow (`test_replacement_operator_replay_guard.py`
and `test_replacement_operator_announce_call_site.py`, both named frozen for
this round -- the owner's own edit in round three, extended here to
`test_replacement_operator_execution.py` and
`test_replacement_operator_stale_staging_report.py`, neither of which was
frozen). `test_operator_route_origin_guard.py`, also frozen, needed no edit
at all.
