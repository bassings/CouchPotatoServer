# Multi-lens review: `deb414bd...e5bb172b` (M1b, PR 2/3 work)

Both lenses reported worktree drift: the worktree was at the BASE commit when they started. Each independently checked out `e5bb172b` and confirmed the SHA before and after every experiment; all results below are against that tip.

## 1. Lens verdicts

| Lens | Verdict | Could not check |
|---|---|---|
| lens-security | FINDINGS | Production's real config.ini auth state (needs SSH, spec explicitly required reading it before PR 2 was written); the Playwright E2E suite, where an auth-on default would actually break the UI; real browser/htmx behaviour of the 302 login redirect; Trivy and gitleaks; the three downstream secret-logging call sites against real devices; userscript add-via-URL under the login change; mutation testing beyond five hand-applied mutations |
| lens-qa | FINDINGS | Playwright E2E, mobile and a11y suites (auth touches every page and hard rule 5 requires them); `tests/integration/`, `make verify`, `make check-traps`, `make check-secrets`, Docker test run; all Settings.save filesystem behaviour on Alpine/musl (measured on macOS/APFS only); production config.ini state; concurrent Settings.save writers; eight named mutations deliberately not run (budget spent on destructive/security/data paths first), including the PrivacyFilter redaction itself never watched to fail |
| AC-SIMP mechanical check | Data only (orchestrator-scored below) | AC-SIMP-31 is not mechanically checkable: the spec defines the amendment rule but never enumerates the PR 2 allowlist it amends |

**Neither lens executed the E2E suite. The full local gate (`make verify`) has not run against this tip. That alone blocks a push under hard rule 2, independent of the findings.**

## 2. Findings (merged, deduplicated, by severity)

### HIGH

**H1. One-click, unguarded, unrecoverable-from-the-UI operator lockout: turning "Require login" on without a password denies every request and refuses every login. Reachable from the settings UI and the first-run wizard, and the shipped copy on the password field says it cannot happen.**
*Credited to: lens-qa (High) and lens-security (Medium). Merged at the higher severity; see §3.*

- **Location:** `couchpotato/core/_base/_core.py:346-356` (the new `auth_required` option) and `:373-376` (the false copy); `couchpotato/core/settings.py:478-482` (saveView, no hook); `couchpotato/__init__.py:81-89, 362-363`
- **Evidence:** Both lenses executed it independently against a real `create_app` with `auth_required=1` and `password=''`: `GET /wanted/` 302s to login; `POST /login/` with any credentials, including empty, returns 302 with NO cookie. There is no way in. Security confirmed the option is writable (`saveView(section='core', name='auth_required', value=0)` returned `{'success': True}`; no `ui-meta`, `wizard: True` on the group). Both greps confirm no `setting.save.core.auth_required` hook exists anywhere. `md5Password` shut the OTHER entrance to this exact state (clearing a password turns auth off) and its own comment names the failure mode; `login_post`'s comment even calls this state "one click away in the settings UI". No test drives `auth_required` through `saveView`.
- **Consequence:** One click costs a home-server operator all access to their own server. Recovery is shell access, hand-editing `config.ini` and a restart, on exactly the population least able to do it. The password field's copy ("so you cannot lock yourself out") tells them the outcome is impossible. This state did not exist before this branch.
- **Fix:** Add the mirror of the existing hook: `addEvent('setting.save.core.auth_required', ...)` in `Core.__init__` that refuses (returns 0) a truthy value when `Env.setting('password')` is empty, logging at WARNING. Same shape and file as `md5Password`'s guard, roughly six lines. Pin with a test driving `Settings.saveView` in both orders (toggle-then-password, password-then-toggle). Correct the password field's copy to match.

### MEDIUM

**M1. `/openapi.json` is served unauthenticated on a fully protected instance, and the new route-auth inventory structurally cannot see it or any other non-APIRoute.**
*Credited to: lens-security.*

- **Location:** `couchpotato/__init__.py:131` (`docs_url=None, redoc_url=None`; `openapi_url` left at default); `tests/unit/test_route_auth_inventory.py:79`
- **Evidence:** Executed with `auth_required=1` and a password set: `GET /openapi.json` returns 200, 26,655 bytes, 77 paths enumerated, while `/` and `/wanted/` both 302 to login. Route walk by type: 80 APIRoute, 1 Mount (`/static`), 1 plain starlette Route (`/openapi.json`). The inventory filters `isinstance(route, APIRoute)`, so the open route is invisible to both the assertion and PUBLIC_ROUTES; the whole file passes green with the route wide open. The api_key is not in the body. The guard is load-bearing for the routes it can see (stripping `require_auth` from `/wanted` reds it), which is why the blind spot matters: the spec calls this test the PR's highest-value criterion because it "fixes the class", and this is a live member of the class it cannot reach.
- **Consequence:** An unauthenticated LAN attacker gets a complete machine-readable map of all 77 endpoints from a server the operator believes is behind a login. Reconnaissance only, no credential disclosed. The larger cost: the next Mount, WebSocket or sub-application added is public and green.
- **Fix:** Pass `openapi_url=None` at `__init__.py:131` (or gate it behind `require_auth`). Widen the inventory's walk to yield every starlette BaseRoute, and add `/static` and any deliberate remainder to PUBLIC_ROUTES with a reason, so the fix is to the class, not the instance.

**M2. The startup `auth_required` migration and the spec-required "authentication DISABLED" warning are executed by no test; the only guard is a source-order string search. Related: the warning can state the opposite of what is enforced for non-canonical hand-edited values.**
*Credited to: lens-qa (Medium, untested migration) and lens-security (Low, warning/enforcement disagreement). Merged; the untested block is the root.*

- **Location:** `couchpotato/runner.py:272-291`; guard at `tests/unit/test_auth_required_gate.py:366-385`; parse split at `couchpotato/__init__.py:81-89`
- **Evidence:** `grep -rln runCouchPotato tests/` returns nothing; the migration block is never called by the suite. The single guard reads `runner.py` as text and asserts substring ordering only: it stays green if the migration condition is narrowed, `resolved` is inverted, the write-back is dropped, or the `log.warning` is deleted, and the spec's T2.1 lists that WARNING as required behaviour. Separately, security measured that `auth_required = banana` (or `yes`, `Y`, `2`) makes the untyped startup path and the typed request path disagree: the log says DISABLED while auth IS enforced. Enforcement itself is never weaker than intended. A latent ordering hazard was also recorded: if `registerDefaults` ever ran before the migration, an upgraded password-protected install stays open; safe today only because `runner.py:282` precedes `loader.run()` at `:333`, and nothing enforces that order.
- **Consequence:** The write-back is what makes `auth_required` grep-findable in `config.ini`, which both docstrings name as the documented lockout recovery path. It and the warning can regress with a green suite, and the warning can already be wrong, defeating the stated reason it was added ("the log is where an operator checks whether they made it"). The runtime gate fails safe, which caps this at Medium.
- **Fix:** Extract the block into a pure helper (`resolve_auth_required(env) -> int | None`), call it from `runCouchPotato`, unit-test the three inputs plus the warning via caplog, and have the warning computed from the value just resolved and written rather than re-read through the untyped path.

### LOW

**L1. Misplaced decorator in the repo's highest-risk file: `_ensure_release_download_index` carries `@_synchronised` twice; `_ensure_unique_media_identifier_index` has lost its own.**
*Credited to: lens-security and lens-qa (independent, identical diagnosis).*

- **Location:** `couchpotato/core/db/sqlite_adapter.py:179-180` (doubled) and `:211` (now bare)
- **Evidence:** Both lenses read the tip: the new method was spliced between the existing decorator and the function it belonged to. `_conn_lock` is an RLock so the double acquisition cannot deadlock, and the only caller of both is `open()`, itself `@_synchronised`, so nothing races today.
- **Consequence:** No live defect. But the REG-004 duplicate-media backstop's serialisation now depends on its single caller happening to hold the lock; the next direct caller runs DDL on the shared connection unserialised. This is also visible evidence of an edit landing one line off target in `sqlite_adapter.py`, which the project's own rules say gets reviewed as new work. No test can see decorator placement.
- **Fix:** Delete the duplicate at `:180`, add `@_synchronised` above `:211`.

**L2. Brute-force protection for the front door this PR creates is deliberately sequenced into the next PR: the rate limiter is disabled by an attacker-controlled `Accept: text/html` header on exactly `/login/` and `/getkey/`, and each attempt costs an inline bcrypt round on the event loop.**
*Credited to: lens-security. Pre-existing, specced as T2.4.*

- **Location:** `couchpotato/core/rate_limit.py:53-55`; `couchpotato/__init__.py:317, :363`
- **Consequence:** The instance this PR just switched from open to password-protected has an unmetered online password oracle and a trivial event-loop DoS. Reported so the sequencing is a recorded decision, not an omission.
- **Fix:** None here IF T2.4 is confirmed as the next PR. If it slips, delete the Accept-header clause and rely on `_EXEMPT_PREFIXES`.

**L3. `test_opening_twice_is_harmless` cannot fail for the property its docstring claims.**
*Credited to: lens-qa.*

- **Location:** `tests/unit/test_release_download_lookup.py:196-208`
- **Evidence:** Under the mutation that removed the `_ensure_release_download_index()` call from `open()`, this test stayed GREEN while its sibling went red. It passes because `create()` ran `schema.sql`, so no upgrade ever needs to run. Incidentally-passing shape.
- **Fix:** Drop the index between the two opens so the second open must recreate it, or delete the test as redundant.

**L4. Nothing pins that the `release_download` query uses `idx_release_download`; the SQL/index expression coupling breaks silently.**
*Credited to: lens-qa.*

- **Location:** `couchpotato/core/db/sqlite_adapter.py:826-834`; `couchpotato/core/db/schema.sql:44-56`
- **Evidence:** EXPLAIN QUERY PLAN measured: with the CASTs, `SEARCH ... USING INDEX idx_release_download`; with them removed from the query only, a scan via `idx_documents_type` (0.014 ms vs 0.050 ms per lookup over 2,000 releases), with every correctness test green either way. Two comments say the expressions must match exactly; no test enforces it.
- **Fix:** One assertion in `TestTheIndexReachesExistingInstalls`: run EXPLAIN QUERY PLAN for the real predicate, assert `idx_release_download` appears.

**L5. The `reindex` counter in `cleanDone` is write-only, and the comment left in its place claims a value it no longer delivers.**
*Credited to: lens-qa.*

- **Location:** `couchpotato/core/plugins/release/main.py:118-154`
- **Evidence:** Four `+= 1` sites remain, the only read was deleted, nothing logs or returns it, yet the comment says it "still records" the count. This branch elsewhere documents exactly this pattern (a comment asserting something false about the code below it) as how a defect survived review.
- **Fix:** Log it (`log.debug('Cleaned %s corrupt or orphaned releases', reindex)`) or delete counter and comment together.

**L6. `auth_is_required`'s string-parsing branch is never exercised: every test feeds an int.**
*Credited to: lens-qa.*

- **Location:** `couchpotato/__init__.py:87-89`; tests at `tests/unit/test_auth_required_gate.py:109,149,208,232`
- **Evidence:** The `isinstance(configured, str)` branch exists for the pre-registerDefaults window and for hand-edited values such as `auth_required = yes`, which is the documented lockout recovery path. No test reaches it; a dropped `'true'` or inverted membership test reddens nothing.
- **Fix:** Parametrise `TestTheDefault` over `'1'`, `'true'`, `'yes'`, `'on'`, `'0'`, `'false'`, `''`.

## 3. Conflict arbitration

- **H1 severity split (security Medium vs QA High):** not a directive conflict. Both lenses independently found the same defect, the same evidence and the same six-line fix; they differ only on the rating. Arbitrated to **High** without escalation: the consequence is total loss of operator access requiring shell recovery on an unattended home server, security itself confirmed the toggle is one writable click away, and the precedence order's operability tier does not soften a finding both lenses demand fixed identically. Recorded here rather than resolved silently.
- No other conflicts. No lens recommended a change another lens rejected. Nothing requires ESCALATE.

## 4. AC verdict summary

### lens-security (11 verdicts)

| AC | Verdict |
|---|---|
| AC-SEC-T2.1-a (six-case auth gate) | PASS, mutation-proven |
| AC-SEC-T2.1-b (plain bool + one-shot migration) | PASS, with recorded ordering hazard |
| AC-SEC-T2.1-c (startup warning) | PASS, qualified by M2 |
| AC-SEC-T2.2 (`/getkey/` returns 401) | **FAIL** as written (returns 200 with null key; substance closed, mutation-proven). The planning cycle's accepted simplicity veto ("delete `/getkey/` rather than gate it") is met neither way |
| AC-SEC-INVENTORY (route class closed) | **FAIL** (M1: the class is not closed; the guard cannot see non-APIRoutes) |
| AC-SEC-PLAN4 (bcrypt over MD5) | PASS, mutation-proven |
| AC-SEC-PLAN5 (blank password admits no one) | PASS, mutation-proven |
| AC-SEC-T2.6 (bare-secret redaction) | PASS, with residuals recorded (dict-repr, Bearer, Basic, `dev`-mode bypass unreconsidered against spec:1334) |
| AC-SEC-T2.0 (atomic credential save) | PASS; actively removes a pre-existing world-readable exposure |
| AC-SEC-T3.1 (release_download binding) | PASS; fails closed |
| AC-SIMP-2 (supply chain) | PASS on substance (zero packages added; version drift noted below) |

### lens-qa

**Zero AC verdicts, because zero AC-QA criteria exist for PR 2 or PR 3.** All 40 AC-QA hits in the spec sit inside PR 1. **SPEC BUG (QA Medium finding):** the review cycle had no contract to verify for a change altering authentication on every route and the lookup that files finished downloads. Test adequacy rested on implementer judgement, which was good, but that is luck, not process. Backfill numbered AC-QA criteria for T2.0-T2.7 and T3.1-T3.4, at minimum covering H1 and M2.

### AC-SIMP mechanical check

AC-SIMP-1 through 14 were written for PR 1's diff and are already scored in the spec. Applied mechanically to this diff: 4, 9, 14 PASS; 7, 8, 11, 12, 13 and the unnumbered criterion N/A; 1, 3, 5, 6 FAIL and 2 splits (versions moved, zero packages added). Those FAILs are not scored as findings: the spec's own PR 2 tasks (T2.0, T2.1, the route inventory) mandate the very changes they reject. **SPEC BUG:** AC-SIMP-31 is the only scope criterion assigned to this range and it is unenforceable, because the PR 2 allowlist it governs amendments to was never written. The observed footprint (13 M + 6 A files) is recorded in the raw data; the spec needs the allowlist added so AC-SIMP-31 means something next round.

### Findings with no AC behind them (spec bugs, per harness contract)

- **H1** (lockout via the toggle): no criterion covers saving `auth_required` through the settings UI. The spec specified the setting and the migration but never the write path a user actually uses.
- **L1** (decorator placement), **L3** (vacuous idempotency test), **L4** (index-usage pinning), **L5** (dead counter), **L6** (string-parse branch): none traceable to any criterion; all sit in the space AC-QA criteria for PR 2/3 would have occupied.
- **M1** is behind AC-SEC-INVENTORY (it is that criterion's FAIL evidence), and **M2** partially behind AC-SEC-T2.1-c; not spec bugs.

## 5. Verdict

**FINDINGS.** No lens returned BLOCKED, but the branch must not be pushed as it stands. Before push, in order:

1. Fix **H1**: the `setting.save.core.auth_required` refusal hook, the corrected password-field copy, and the saveView tests in both orders.
2. Fix **M1**: `openapi_url=None` plus the widened inventory walk with an explicit, reasoned PUBLIC_ROUTES for non-APIRoutes.
3. Fix **M2**: extract and unit-test the startup migration and warning; make the warning agree with enforcement.
4. Fix **L1** (two-line decorator correction) and take or explicitly defer L3-L6 with reasons recorded.
5. Backfill the spec: AC-QA criteria for T2.0-T2.7 and T3.1-T3.4, and the missing PR 2 AC-SIMP-31 allowlist. Confirm T2.4 (rate limiting) as the next PR or apply the interim L2 change.
6. Run the full gate against the tip: `make verify` including the Playwright E2E, mobile and a11y suites that neither lens could execute; auth now touches every page and no lens has seen a browser hit this code.
7. Re-run this review cycle over the amended range until clean, per hard rule 3 and the outstanding C3 escalation recorded in `QA/lens-review-2026-08-07-m1b-vs-master.md`.
