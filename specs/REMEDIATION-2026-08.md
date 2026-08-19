# Remediation Plan: Audit 2026-08-02

Resolves every finding in the 2026-08-02 repository audit, plus the outstanding
half of FEAT-009. Sequenced into six milestone-sized PRs, each passing the full
local review gate before push.

**Baseline:** `bd4d69b8` (master, clean tree).

## Decisions taken (Scott, 2026-08-02)

1. **Auth fix shape:** add an explicit `auth_required` setting defaulting to ON
   whenever a password is set. Username becomes optional (blank = any username
   accepted). Open-on-LAN stays supported but must be chosen deliberately, and
   logs a startup warning. *Not* a hard fail-closed, so no existing install
   silently loses access on upgrade.
2. **Delivery:** milestone-sized PRs, each with the full `make verify` +
   ≥2 `code-reviewer` agent gate. Quick wins are distributed to the PR whose
   theme they match rather than batched at the end: the security-relevant ones
   are too cheap and too live to sit behind three other PRs.
3. **FEAT-009 Part B (upgrade replacement) is in scope**, as its own PR. It is
   not an audit finding, but it lives on the same destructive code path the
   audit found untested (`moveFile`), so it is sequenced behind those tests
   rather than run as an independent workstream.
4. **No schedule pressure. Do not split PR 1 to unblock later PRs.** It was
   suggested and declined (2026-08-02): PR 1's whole job is making later
   verification trustworthy, so fragmenting it to start PR 2 sooner trades away
   the thing it exists to provide. Thoroughness over sequencing speed applies
   throughout: where this plan offers a cheaper option and a more correct one,
   take the more correct one.
5. **PR 1 fixes the `moveFile` data-loss defects rather than only pinning them**
   (2026-08-03, after the planning cycle). PR 1 was scoped "no runtime behaviour
   change"; planning found three verified defects on that path that delete the
   user's download or corrupt the library. The precedence order puts
   irrecoverable loss above a self-imposed scope constraint, so they are fixed
   here, TDD: see T1.8. `AC-SIMP-1` is amended accordingly.
6. **The renamer re-entrancy lock moves ahead of PR 4** (2026-08-03). Two
   concurrent `moveFile` calls to one destination destroy a file and both return
   `True`. PR 4 adds a delete to that exact path, so shipping the delete before
   the lock turns "one download lost" into "the library copy lost too".

## Facts established before planning (verified, not assumed)

These change the work, so they are recorded here rather than left as assumptions:

- **`open()` never runs `schema.sql`**: only `create()` does
  (`sqlite_adapter.py:208-219`; the comment at `:217` states it). Any new index
  must ship with an idempotent self-upgrade call in `open()`, or it reaches
  fresh installs only and does nothing on production. This is the single
  highest-value gotcha in this plan.
- **`/getkey/` has no live consumer.** Only `couchpotato/simple_healthcheck.py:76`
  and `couchpotato/integration_test.py:156` call it; `simple_healthcheck.py` is
  referenced by nothing (the Docker HEALTHCHECK hits `/`, `Dockerfile:89`), and
  the JS client described in `specs/SEC-003-password-hashing.md` went away with
  the legacy UI. Gating it is safe; both files are dead code.
- **`db.opened` appears only at `database.py:402`** (the fossil migration): the broken compat surface is on a dead path, so deletion beats repair.
- **No `download_info` index exists** in `schema.sql`: the `release_download`
  fix needs one added, subject to the `open()` gotcha above.
- **`get_many()` defaults to `with_doc=True`** (`sqlite_adapter.py:857-858`), so
  fixing the re-fetch inside `query()` fixes all 44 `with_doc=True` call sites
  at once.
- **FEAT-009 state:** Part A shipped (`copyIdentity`/`copy_id`,
  `release/main.py:200-293,719-728`). Part B's *safety* half shipped (the
  `skipped = True` guard, `renamer/main.py:151-157`). Part B's *replacement*
  half is unimplemented: `renamer/main.py:154-157` still skips when the
  destination exists, and `remove_lower_quality_copies` is declared at
  `renamer/api.py:135` and read nowhere in the codebase.
- **`QualityPlugin.qualities` is a genuine global ordering**
  (`quality/main.py:26-38`, index 0 = 2160p → 11 = cam; "a lower number means
  higher quality"), so the ranking primitive FEAT-009 asks for exists.
  Conversely `isHigher` returns `'higher'` for any quality absent from the
  profile (`:542-548`): re-confirming the measurement that killed attempt #2.

## Process (per CLAUDE.md rules 1, 3, 4, 9, 10)

Every PR follows the same loop:

1. Delegate implementation to the `implementer` sub-agent: TDD, RED confirmed
   for the right reason before GREEN. Agents commit locally and **stop**.
2. Orchestrator validates against the repo, not the report: read the diff, run
   the command, confirm each new guard was proven load-bearing (break it, watch
   it fail, hash-verify the restore).
3. `make verify` green locally.
4. ≥2 independent `code-reviewer` agents on the branch diff, fresh context,
   different lenses. Iterate until clean; reject marginal nits with evidence.
5. Push, PR, merge. **No production deploy**: that is a separate, explicitly
   agreed step (rule 6).

---
## Tasks


Conductor checklist. States: `queued -> building -> pr-open #N -> awaiting-ci #N
-> in-review #N -> merged`. The box is ticked only at `merged`, and only from
`gh pr view`, never from memory.

- [x] T1: PR 1 — M0 safety net for the destructive paths — state: merged #225
- [x] T2: PR 2 — M1a authentication and web-surface security — state: merged #226
- [x] T3: PR 3 — M1b data correctness at the SQLite seam — state: merged #227
- [x] T4: PR 2b — HMAC-signed session cookie (the cookie is still the api_key) — state: merged #229 · spec `specs/PR2B-SESSION-COOKIE.md`, 85 ACs; ~25 review findings across six rounds, all fixed or recorded as T11-T15
- [x] T5: PR 4 — FEAT-009 Part B upgrade replacement — state: merged #235, #236, #238, #239, #240, #242 (B0-B4b) · spec extracted to `specs/FEAT-009B-UPGRADE-REPLACEMENT.md` with its three load-bearing claims re-verified against the repo: the `qualities` list order, the profile fallthrough in `QualityPlugin.isHigher`, and the unconditional destination skip in `Renamer._moveRenamedFiles`.

      Cited by SYMBOL rather than by line, because the line numbers this entry
      originally carried (`quality/main.py:530-548`,
      `renamer/main.py:154-157`) were moved by T5's own merged work and were
      pointing at unrelated code by the time the task was ticked. A citation
      that drifts is worse than none: it reads as precision and sends the next
      reader to the wrong function. The `/plan-cycle` this line called for ran on 2026-08-08; the spec carries its ACs and D1-D12
- [ ] T6: PR 5 — M2 performance — state: queued (needs: T5)
- [ ] T7: PR 6 — M3 documentation, dead code, polish — state: queued (needs: T6)
- [ ] T8: T3.3 — restore or delete the dead orphan-release cleanup — state: queued (needs: T3)
- [x] T10: `tests/e2e/suggestions.spec.ts:99` failed only inside a FULL run — state: merged #230

      **Root cause, and I had it wrong first.** I recorded that this was not
      caused by the PR 2b branch, on three structural grounds: the spec is
      untouched by it, the rate limiter returns early for localhost, and both
      sign-out controls sit inside `{% if auth_required %}` while E2E seeds no
      password. Every one of those is true. The conclusion was still wrong,
      because the mechanism was TIMING, not logic:

          full chromium project on master       136/136 pass
          full chromium project on the branch   136 + 1 failed

      PR 2b adds an `auth_is_required()` call to the common template context,
      so every partial render does slightly more work. That was enough to lose
      a latent race.

      **The race was real and in the app.** `fail()` deferred focus with
      `$nextTick`, which flushes Alpine's queue rather than the browser's style
      pass — so `x-show` had not necessarily applied `display`, and `focus()`
      on a `display:none` element is a SILENT no-op. A focus move that only
      lands on a fast machine is a WCAG 2.4.3 failure for anyone on a slow one.

      Fixed with a synchronous style flush (`void el.offsetHeight`), which is
      deterministic rather than probabilistic, in one shared helper across all
      three call sites, each now asserted. Not fixed by retrying the test:
      CI runs `--fail-on-flaky-tests`, so suppressing it locally would have
      made CI stop reporting it.

- [x] T16: the CI/local gate is paid for TWICE, serially — state: merged #241 · owner chose "both: path-aware hook + trimmed CI". `scripts/needs_e2e.sh` is the single source of truth for "does this change need a browser", called by the pre-push hook and by CI's `scope` job; browser suites now skip on a non-UI change and a nightly run keeps master honest. **Known gap, tracked as T19:** the matcher does not cover backend routes the UI calls, so a change to an API handler can skip the browser suites. Eleven review findings, three of them fail-opens: a SIGPIPE under `pipefail` that skipped the browser suites the MORE files a change touched (correct at 1,000 paths, wrong at 4,000), `couchpotato/static/` missing from the matcher so the JS driving the UI was never gated, and the classifier being read from the PR's own checkout so a PR could defang its own gate. All fixed and mutation-proven

      **Re-scoped 2026-08-09 after the owner asked whether moving CI local would be faster. Measured, and it
      would not — the premise inverts.** This repo is PUBLIC on standard `ubuntu-latest`, so its Actions
      minutes are free; the owner's spend is a different private repo. And the local gate is already both
      mandatory and faster: `core.hooksPath=.githooks` runs all of `scripts/verify.sh` before every push, at
      ~7 min against CI's 511s median to a mergeable PR (Python suite 107-150s local vs 234s per CI leg;
      chromium E2E 3.4m vs 4.4m).

      So the waste is not location, it is DUPLICATION: the same gate is paid ~7 min locally and ~8.5 min in
      CI, serially, every push. Containerising locally would make it worse — Docker on macOS is a VM with
      slow bind-mount I/O for a file-heavy suite.

      What CI alone can do: Python 3.10-3.13 (the venv is 3.14.6, so local covers one leg of five), the
      Alpine/Docker build, CodeQL (which caught two real defects on #232), and the AI review. Everything
      else on a PR run is duplication.

      Proposed: PR runs keep lint, secrets, CodeQL, review, docker and ONE Python leg; master and nightly
      keep the full matrix, E2E and accessibility; and the pre-push hook becomes path-aware so a
      Python-only change skips E2E. ~15 min per cycle to ~5, and it strengthens rule 2's "CI is
      confirmation, not discovery" rather than working against it. · **owner decision taken 2026-08-08: ship T9 first, decide this once T9's real numbers land**

      Raised by the review of T9 (finding M7) and confirmed by measurement, not
      inference. Across 15 successful PR runs, `accessibility` was the LAST
      required check to report in 15 of 15. T9 moves the accessibility verdict
      from 666s to ~140s, but `ui-e2e-tests` keeps
      `needs: [test, ui-unit-tests]` (`ci.yml:218`) and is itself a required
      context, so it takes over as last at ~514s.

      **So T9 takes the gate from ~11 minutes to ~8.5, not to ~2.5.** Reporting
      only the 79% cut to the accessibility verdict would tick AC-QA-60 while
      the owner still waits eight and a half minutes to merge, and would
      produce the same complaint again against a task already marked done.

      Removing this edge would land the gate at ~270s (~4.5 min). **It is not
      the same call as the accessibility edge**: that one had no reason at all,
      whereas this one plausibly exists to stop an expensive E2E job burning
      runner minutes on a branch whose unit tests have already failed. That is
      a cost trade, and the owner owns it.

      Decide with T9's measured after-numbers in hand, not these projections.

- [x] T19: the change-surface gate does not see backend code the UI depends on — state: **rule INVERTED** (owner decision 2026-08-10). See below

      Raised reviewing T16's own plan entry, and correct. As shipped by T16,
      the allowlist `UI_PATTERNS` matched `couchpotato/ui/`,
      `couchpotato/static/`, `couchpotato/templates/`, `tests/e2e/` and the
      harness files. It did NOT match the backend routes and API handlers
      those pages call — so a change to, say, a partial's handler or an API
      view could break the rendered page while the browser suites were
      skipped on the PR that did it.

      T16 is not reopened: #241 is merged and did what it set out to do. This
      is the next iteration of the same question, which is "what can change
      what a browser sees", and the honest answer is wider than the first
      version assumed.

      Not simply "add more patterns". Widening until it matches most of
      `couchpotato/` returns the gate to running everything on everything,
      which is the cost T16 removed. The useful shape is probably the routes
      the UI actually calls — `couchpotato/ui/**` already matches, so the gap
      is the API handlers behind it — established by reading the templates
      rather than guessed.

      Whatever it becomes, it needs the same treatment the rest of that gate
      got: err towards running, and a test per pattern, because
      `couchpotato/static/` shipped MISSING from the first version precisely
      because no case named it.

      **Outcome, and it went further than the task proposed.** The first
      attempt widened the allowlist to the backend the UI calls, derived from
      `callApiHandler`. Review found that incomplete twice, and the second
      round showed WHY it could not be completed: the UI also calls the API
      directly from templates, across 33 endpoints in 16 namespaces — `app
      category collection directory download logging manage media movie
      profile provider quality release search settings updater`. An honest
      allowlist would have been `couchpotato/`.

      So T16's saving was never independence between backend and UI; it came
      from UNDER-COVERING. `renamer`, `searcher`, `updater` and `quality` all
      skipped the browser suites while the browser called every one of those
      namespaces.

      Measured before deciding: of the last 60 commits, 6 touch only
      documentation, plans, QA notes, unit tests or agent scratch. So
      inverting recovers ~10% of runs, not the majority T16 implied.

      Owner chose to invert. `SKIP_PATTERNS` now lists what cannot reach a
      browser and everything else runs. The failure direction is the point: an
      unrecognised path RUNS the suites, which is how every other uncertainty
      in this script already resolves.

- [x] T17: the three SonarQube findings that survived triage — state: **fixed in code** (2026-08-11)

      From the first real SonarQube analysis of this repo (2026-08-10, project
      `couchpotato`). Of 84 raw vulnerabilities, 37 were marked false positive
      with a written reason and an explicit reopen condition, 44 were HTTP
      findings already accepted, and **these three are genuine**. Each was read
      at the call site rather than taken from the rule description, and
      reachability was established for each, because two of the three are
      narrower than the rule makes them sound.

      Security rating is D and stays D until these move. That is correct: a
      rating that went green while they were open would be the thing that
      teaches everyone to ignore it.

      **1. `python:S4830` — `downloaders/synology.py:140`, credentials over an
      unverified TLS connection.**

          req = requests.post(url, data = args, files = files, verify = False)

      That request is the `SYNO.API.Auth` call: it carries the operator's
      Synology username and password. `verify=False` disables certificate
      validation, so anything on the path can present its own certificate and
      read them. The same file also uses `http://` endpoints.

      Reachability: the downloader ships disabled (`'enabled'` default 0), so
      this affects operators who have turned it on — which is exactly the set
      who typed a password into it. Not urgent for everyone, serious for them.

      Fix shape: honour certificate validation by default and make disabling
      it a deliberate, per-downloader setting with the risk stated, rather
      than a hard-coded literal. A self-signed NAS certificate is the reason
      it is there, so removing the escape hatch entirely will break real
      setups.

      **`verify=True` alone does not close this.** The same file also builds
      `http://` URLs, and credentials over plain HTTP are exposed whatever the
      TLS setting says — fixing only the flag would clear the SonarQube
      finding while leaving the password readable on the wire. The scheme has
      to move with it.

      **2. `python:S2612` — `_base/updater/main.py:443`, 0o777 on a failed
      delete, then unbounded recursion.**

          except OSError as inst:
              os.chmod(inst.filename, 0o777)
              self.removeDir(path)

      Two defects in three lines. It makes a path world-writable in response to
      an error, and it retries by recursing with no depth bound and no
      guarantee the chmod changed anything — a permission error it cannot fix
      recurses until the stack ends.

      Reachability, narrower than it first looks: called from the SOURCE
      updater's extract paths (`updater/main.py:363`, `:379`), and
      `SourceUpdater.doUpdate` fires `cp.source_url` before reaching them
      (`:355`). Production runs the Docker image, so this is not how this
      deployment updates. The plugin still loads and registers API views, so
      it is reachable rather than dead — but it sits behind a source-install
      update attempt, not on any routine path.

      Fix shape: narrow the permission (owner-write, not world), bound the
      retry to one attempt, and let the second failure propagate. Do not widen
      permissions to force a delete through.

      **3. `python:S5247` — `plugins/base.py:85`, Jinja autoescape off.**

          env = _JinjaEnv(loader=_JinjaFSLoader(tmpl_dir))
          t = env.get_template(templ)
          return t.render(**params)

      Jinja defaults `autoescape` to False, so this renders caller-supplied
      values unescaped. Corroborated independently by the local gate's
      `ruff S701`.

      **`renderTemplate` has no callers IN THIS REPOSITORY** — its only
      mention is its own definition, checked across `.py`, `.html` and `.js`.
      So it is not a live XSS here.

      That is not the same as unused, and an earlier draft of this task
      conflated the two. It is a public method on `Plugin`, inherited by 35
      in-tree classes and by any installed third-party plugin, so an
      out-of-tree caller is invisible to every check available from inside
      this repo.

      Fix shape, revised: make it SAFE rather than absent — `autoescape=True`,
      with a test proving a `<script>` in a param comes out escaped. That is
      correct whether or not anything calls it, and it costs nothing.
      Deletion is a separate decision needing a deprecation path, and "no
      in-repo callers" is not evidence for it.

      **Do not resolve these in SonarQube to make the rating move.** Fix the
      code, re-scan, and let the rating follow. The 37 dismissals each carry a
      reason and a reopen condition; these three have no reason available.

      **Outcome.** All three fixed in code; nothing was touched in SonarQube.
      Re-scan after merge and let the rating follow the code.

      1. S4830: `ssl`/`ssl_verify`/`ssl_ca_bundle` added to Synology, matching
         rtorrent's existing options rather than inventing a shape.
         `getVerifySsl` hoisted to `DownloaderBase` so there is ONE
         implementation — with the trap that made hoisting worth care: a
         downloader with no `ssl_verify` option gets `None`, which the
         original returns `False` for, so a naive hoist would have silently
         disabled certificate checking for every downloader inheriting it.
         The base version treats absent as verify-ON, and that is the guard
         the mutation testing was aimed at.

         **What this does NOT do, stated plainly:** `ssl` still defaults to
         0, so a default install still sends the operator's Synology username
         and password over plaintext http. Flipping that default would break
         every install pointing at DSM's port 5000, so the risk is now
         *visible and fixable* rather than eliminated. That is why the
         warnings below are part of the fix and not a nicety.

      2. S2612: owner-write only (never group/other), retry bounded to one
         attempt, `None` filename propagates. Also refuses to chmod a
         SYMLINK — `os.stat`/`os.chmod` both follow links, and this runs on
         freshly-extracted archive content, so the original would reach a
         target outside the tree being deleted.

      3. S5247: `autoescape=True`. Method kept, not deleted: no in-repo
         caller exists, but it is public on `Plugin` and inherited by
         third-party plugins, so "no callers here" is not evidence of none.

      **The unsafe states are no longer silent**, which was the real defect
      behind (1): a WARNING fires when credentials are about to cross a
      plaintext connection, and when https verification is off. Both route
      through `log_suppressed` with independent keys — a fresh `SynologyRPC`
      is built per download, so an unbounded warning would fire on every one
      and train the operator to scroll past the line added so they would not
      miss it. Neither names a host, path or credential value.

      Two lessons recorded rather than the fix alone:
      - A present-but-blank `ssl_verify` coerces to `False`. `Settings.get`
        returns the caller's `default` only on the *exception* path, so
        `default=True` does not cover a blank value, and after coercion `''`
        and `'0'` are indistinguishable. The answer is the warning, not more
        parsing.
      - The key-independence test first passed against a deliberately
        broken build. It asserted only `len(records) == 2`, and a shared
        suppression key also produces two records (one full message, one
        "withheld" notice), so the count could not tell correct behaviour
        from the regression. Strengthened to assert each record's content.
        A textbook incidentally-passing guard, found only by mutating it.

      **Two findings in the neighbourhood, measured while fixing the above.**
      Recorded here so neither is rediscovered and re-argued later.

      - `ruff S113`, `synology.py`: `requests.post` had no timeout, so an
        unresponsive NAS parks the thread indefinitely and downloads stop
        with nothing in the log. Fixed here, since it is the same call the
        S4830 work already edited. 60s, matching `sabnzbd.py`'s file-carrying
        call rather than the house default of 30, because `_req` uploads the
        nzb/torrent payload and a too-short timeout would be a fix that
        causes an outage.
      - `ruff S202`, `updater/main.py:370` and `:374`: the path-traversal
        class. **Measured, not assumed: a false positive at both lines —
        but for two DIFFERENT reasons, and an earlier version of this entry
        got that wrong.** It described both lines as `tarfile.extractall()`
        and gave them a single reopen condition, having measured only the
        tar one. `:370` is `zip_file.extractall()`; only `:374` is tarfile.
        Both were then driven properly:

        `:374`, tarfile — a tar carrying a `../escaped.txt` member:

            OutsideDestinationError: '../escaped.txt' would be extracted to
            '.../escaped.txt', which is outside the destination

        Python 3.14 applies the `data` extraction filter by default, and
        3.14 is what production ships and the only version CI tests.
        **Reopen `:374` if this project ever supports Python < 3.14**, at
        which point that call becomes a genuine arbitrary-file-write.

        `:370`, zipfile — a zip carrying both `../escaped.txt` and
        `/abs_escaped.txt`: both landed INSIDE the destination
        (`out/escaped.txt`, `out/abs_escaped.txt`), and neither
        `./escaped.txt` nor `/abs_escaped.txt` was created. `zipfile`
        sanitises member names itself and has done since long before 3.14,
        so **the Python-version condition does NOT apply to this line** —
        it is contained by the library regardless of interpreter version.

        Neither changed. Adding `filter='data'` would be harmless but is
        justified only by "a scanner said so". The lesson worth keeping is
        the doc error rather than the finding: citing two lines from one
        measurement produced a confidently wrong reopen condition, which is
        the failure mode §7 warns about — a wrong doc costs more than a
        vague one.

      **Spec bug (recorded, per the harness rule that a review finding with
      no AC behind it is a spec bug).** T17 was written, built and reviewed
      with **zero** `AC-<LENS>-<n>` acceptance criteria, so the review had
      only the task's prose to check the built thing against. Every finding
      below therefore had to be discovered rather than verified against a
      contract, including the two serious ones. Tasks added mid-plan skip
      the planning cycle, which is exactly when criteria get written; that
      is the gap, not this task in particular.

      **Portability trap, measured — worth more than the finding that
      surfaced it.** Review raised the TOCTOU window between `removeDir`'s
      `os.path.islink` check and its `os.chmod`. Real, but both atomic
      remedies fail, and one fails in the worst possible way:

      - `O_NOFOLLOW` + `fchmod` (the idiom `renamer/swap.py` already uses)
        cannot open the directory at all — `PermissionError` — because
        lacking read permission is the exact condition being repaired.
      - `os.chmod(..., follow_symlinks=False)` works on macOS and **does
        not exist on Alpine**:

            macOS  : chmod follow_symlinks supported: True
            Alpine : chmod follow_symlinks supported: False

        (measured in `python:3.14-alpine`, the image this project ships.)

      So that "obvious" fix would have passed every local test and raised
      `NotImplementedError` in a delete path on production. This is §11's
      "match the environment to production" in its most expensive form: a
      green local run in an environment that cannot express the failure.
      **Check `os.supports_follow_symlinks` before reaching for it here.**

      The check-then-act stays. `chmod` requires ownership, so the worst
      outcome is owner-rwx on a file the process already owns. Reopen if a
      portable atomic chmod-without-follow appears, or if this ever runs
      where the process does not own the tree it is deleting.

      **Carried forward, not fixed here.** `removeDir`'s single retry can
      now raise where the old unbounded recursion might eventually have
      succeeded, and it sits AFTER `replaceWith()` has already overwritten
      the application directory (`updater/main.py:380`), before
      `version_file` is written (`:383`). The updater then believes it is
      still on the old version and re-applies next check. Speculative: a
      multi-entry blocked tree was never constructed, so the frequency is
      unmeasured. Non-destructive on the data-risk ranking (the recoverable
      end), which is why it is recorded rather than fixed under a security
      task. Reachable only via the SOURCE updater, which the Docker
      deployment does not use.

- [ ] T15: `_write_session_secret` hand-rolls a CAS retry the adapter already provides — state: queued, **narrowed** (2026-08-11) — the rejection rested on a false premise, corrected below

      Non-blocking review nit on #229, verified and deferred rather than done.

      `SQLiteAdapter.update_with_retry` (`sqlite_adapter.py:563`) exists and
      documents itself as "the safe primitive for read-modify-write callers":
      it re-`get()`s, applies a mutator, updates, and retries on
      `ConflictError`. `_write_session_secret`'s update branch reimplements
      exactly that. Mine exists because I did not know the primitive was
      there.

      Not a correctness problem — the hand-rolled loop is correct, and its
      test now genuinely proves it re-reads (a competing write bumps `_rev`,
      so a hoisted read fails). It is avoidable duplication of a primitive the
      codebase already trusts and tests, and duplication is what drifts.

      Deferred because rewriting the secret-write path at the end of a PR this
      size, on a branch where rule 11 already applies, buys no behaviour and
      risks a regression in the one function that must not lose a write. Its
      own small change, with its own review.

      **Investigated and REJECTED, with the measurements, so this is not
      re-raised.** The duplication is real; the conclusion that it can be
      removed is not. `update_with_retry` cannot express what
      `_write_session_secret` does, on two counts:

      1. **It is update-only, keyed by `_id`.** Driven against a real
         adapter:

             absent doc -> KeyError: 'Document not found: no-such-id'

         `_write_session_secret` is an UPSERT keyed by a queried
         `identifier` (`_session_secret_row`), not by an `_id` it already
         holds. The primitive covers the update half and cannot cover the
         insert half at all.

      2. ~~The insert branch is reachable mid-retry~~ — **WRONG, and
         corrected rather than quietly dropped.** The first version of this
         entry argued the row could VANISH between attempts via
         `Settings.getProperty`'s `except ValueError:` firing
         `database.delete_corrupted` from a reader path the write lock does
         not serialise. Review (#249) contradicted it, one reviewer having
         verified the call chain existed and the other having checked
         whether it WORKS. The second was right. Driven:

             get(with_storage=False) -> TypeError: unexpected keyword
             _delete_id_index        -> AttributeError: no attribute
             row still present after "delete"? -> v1

         `Database.deleteCorrupted` cannot delete on this adapter, and
         nothing else deletes a property row. So the mid-retry-vanish case
         is unreachable and the per-attempt re-check is defensive, not
         load-bearing.

         **What that changes:** the consolidation is no longer blocked by a
         correctness argument. Point 1 still stands — the primitive is half
         a function's worth of reuse — so this is now a judgement call about
         splitting one write path across two mechanisms, to be made with its
         own TDD cycle rather than settled in a docs PR. Reopened, not
         closed. See T22 for the dead `deleteCorrupted`.

      A variant catching `KeyError` to fall back to insert restores the
      recovery, but it is the same length as the loop it replaces, converts
      a re-read into exception-driven control flow, and risks masking a
      `KeyError` raised for a different reason by the `get()` inside the
      primitive.

      The lesson worth keeping is not about the retry loop. A rationale was
      written into a docstring and a spec on a reachability claim that was
      never driven, and it took a reviewer disagreeing with another reviewer
      to catch it. A wrong reason is worse than no reason: it would have
      blocked a legitimate consolidation for as long as anyone believed it.

- [x] T14: the password-change rotation commits before the save does — state: **fixed** (2026-08-11), rotation moved off `Core.md5Password` onto a new `.committed` event `Settings.saveView` fires only after `self.save()` succeeds

      P2 review finding on #229, **attempted and withdrawn twice** before this
      pass, so it was a task rather than a fix.

      `Core.md5Password` was the VALUE hook: it ran while the settings save was
      still in progress, before `Settings.save()` wrote `config.ini`. Rotating
      there meant a save that then failed -- read-only config directory, a
      permissions change, an I/O error -- had already signed the operator out
      of every device for a change that was never persisted, and after a
      restart the OLD password was still authoritative.

      **The fix this entry originally proposed does not work, and that is very
      likely why the first two attempts produced nothing usable.**
      `fireEvent()` auto-fires `'<name>.after'` as an intrinsic side effect of
      EVERY dispatch (`couchpotato/core/event.py`), including the value-hook
      call itself -- so a handler wired to `setting.save.core.password.after`
      runs a FIRST time immediately after the value hook, before
      `self.set()`/`self.save()` in `saveView`, and only a second time for
      real afterwards. A consume-and-clear rotation hook acts on the first,
      premature firing and never sees the second. Measured directly against
      this branch's own harness: wiring the rotation to `.after` still rotated
      the secret when `self.save()` was made to raise -- the exact defect this
      task exists to close, reproduced by the fix this entry described as
      "available and clean".

      **The actual fix** adds a new event, `setting.save.<section>.<option>.committed`,
      which `Settings.saveView` (`core/settings.py`) fires explicitly, once,
      only after `self.save()` returns without raising. `fireEvent` never
      auto-derives that name from anything else, so it is the one signal in
      `saveView` guaranteed to fire exactly once and only post-commit.
      `Core.rotateSessionSecretAfterSave` is wired to it instead of `.after`.

      The wrinkle this entry flagged held: the `.committed` event receives no
      value, so it cannot tell a password being SET from one being CLEARED,
      and D10 says clearing must not rotate. `Core.md5Password` sets a flag,
      consumed by the new hook. It is a per-thread `threading.local()`
      declared as a CLASS attribute rather than instance state: thread-local
      because `saveView` dispatches through `run_in_threadpool`, so two
      concurrent password-change requests must not read or clear each other's
      flag; class-scoped so it exists without `__init__` running, which
      several of this project's own tests rely on (`Core.__new__(Core)`).
      Assigned unconditionally (`bool(value)`, never `if value: ... = True`),
      so a failed SET cannot leave a stale True for a later CLEAR to inherit.

      **Residual window, recorded not fixed: T21.** A kill between the
      atomic `save()` and the rotation's database write leaves the new
      password live and the old signing secret intact, so a password change
      that DID persist revokes nothing until the cookie's own expiry. Much
      narrower than what this task fixed (a precise instant, versus any I/O
      error) and nothing is lost or locked out, but it is silent. Design and
      severity in T21.

      Existing `.after` consumers elsewhere (`automation.py`, `manage.py`,
      `updater/main.py`, `searcher/base.py` -- all cron-recompute hooks
      registered on a specific `<section>.<option>.after`) are double-fired by
      the same `fireEvent` quirk and were deliberately left alone: recomputing
      an idempotent cron schedule twice is wasteful, not incorrect, and
      touching four unrelated plugins was out of this task's scope. Worth a
      pass if `.after` semantics are ever revisited generally.

      **`rtorrent_.py` does NOT belong on that list**, measured after an
      earlier draft of this entry put it there. `rtorrent_.settingsChanged`
      registers on the literal wildcard `setting.save.rtorrent.*.after`
      (closing the active rTorrent connection, not a cron recompute), and
      `fireEvent`'s auto-derivation only ever produces `'%s.after' % name` for
      the CONCRETE name it was called with -- `saveView`'s value hook fires
      `'setting.save.rtorrent.<option>'`, never the literal string
      `'setting.save.rtorrent.*'`, so nothing auto-derives the wildcard early.
      It is reached only once, by `saveView`'s own explicit
      `fireEvent('setting.save.%s.*.after' % section, single=True)` (settings.py:515),
      genuinely after the save. Instrumenting a real `saveView` call
      confirmed the counts directly: `{'per_option_after': 2, 'wildcard_after':
      1, 'committed': 1}`. The distinction is the useful part for whoever next
      touches `.after` generally: a per-option `.after` double-fires, a
      wildcard `*.after` does not.

      Tests: `tests/unit/test_password_rotation_after_commit.py` (new -- a
      working rotation instrument proven first per this entry's own
      instruction, exactly-once-per-save as a regression guard against the
      "looks green for the wrong reason" shape above, failure injected at the
      real `self.save()` commit point, the flag's leak-across-attempts guard,
      and clearing never rotating or creating a secret row on a fresh
      install), plus `tests/unit/test_session_revocation.py` updated where it
      drove the password-change event directly and so needed the `.committed`
      event fired alongside it to still exercise real behaviour.

- [x] T13: `session_secret_store_is_readable()` cannot detect an unreadable store — state: **probe removed** (2026-08-11, option 2)

      Review Medium on #229, confirmed by execution and then **attempted and
      reverted**, which is why it is a task rather than a fix.

      `Settings.getProperty` wraps its read in a blanket `except Exception:`
      that logs at DEBUG and returns None (`core/settings.py:640-654`).
      Measured against a store whose reads raise:

          getProperty returned: None   <-- did NOT raise

      So `Env.prop` never reports a broken store, the probe's `except` is
      unreachable in production, and it answers "readable" for both "never had
      a secret" and "the store just raised" -- the exact ambiguity it exists to
      resolve. Its test passed only by monkeypatching `getProperty` wholesale,
      bypassing the handler a real fault goes through.

      **Not urgent.** The reviewer's own analysis, verified: `ensure_session_secret`
      reads via `_session_secret_row` (the adapter directly), which DOES
      propagate, and `login_post` catches it -- so fail-closed holds today,
      just via an undocumented path rather than the one AC-SEC-33's write-up
      names. The risk is fragility: consolidating the read paths would remove
      that backstop silently.

      **Why it is deferred rather than fixed.** Three attempts, each worse:
      pointing the probe at the adapter made the probe and `get_session_secret`
      read differently, so a login issued a cookie while the secret was
      unreadable (caught by
      `test_login_issues_no_cookie_when_the_secret_cannot_be_read`); pointing
      both at the adapter broke 22 tests. Project rule 11 says the fourth
      attempt is not the answer. All of it was reverted; the suite is green.

      Two shapes to choose between, both from the review:
      1. read through the adapter in BOTH the probe and `get_session_secret`,
         and fix every test that injects a `getProperty` fault (there are at
         least six, across three files);
      2. delete the probe and document `ensure_session_secret`'s own exception
         propagation as the AC-SEC-33 enforcement point.

      Option 2 is smaller and matches what already happens. Either way it is
      its own change on the authentication path, with its own review.

      **Done, option 2.** The probe is gone; `ensure_session_secret`'s own
      propagation is documented as the AC-SEC-33 enforcement point, at the
      function and at `login_post`'s `except`, and the call-site comment no
      longer describes a condition that does not exist. Recorded as D17 in
      `specs/PR2B-SESSION-COOKIE.md`.

      Behaviour-preserving under a REAL fault, and that was checked rather
      than asserted: `SQLiteAdapter.get` and `.query` both route through
      `_query_index`, so a store that cannot be read fails BOTH the
      `getProperty` path and `_session_secret_row`, and no cookie is issued
      with or without the probe.

      **The test carrying the property was itself vacuous, which is the find
      worth keeping.** `broken_store` patched `Settings.getProperty` to
      raise — a fault that cannot occur, since that method's own blanket
      `except` swallows what the layer beneath throws. It therefore never
      exercised `ensure_session_secret`'s read at all. Proof it mattered:
      with the old fixture retained, removing the probe made
      `test_login_issues_no_cookie_when_the_secret_cannot_be_read` FAIL,
      because the synthetic fault left the adapter read working, so a secret
      was created and a cookie issued. The fixture now breaks
      `_query_index`, the layer both real paths share.

      **Spec bug, same as T17.** T13 shipped with no `AC-<LENS>-<n>`
      criteria of its own, so review had only the task prose to check
      against. Tasks added mid-plan skip the planning cycle where criteria
      are written; that is the gap, not this task.

      **A claim of mine in the first draft was false, and the adversarial
      reviewer caught it as unproven before I disproved it.** I wrote that
      `Env.prop` NEVER raises in production and that the probe answered
      `True` unconditionally. Measured:

          getProperty RAISED: RuntimeError: store down on the retry

      `Settings.getProperty`'s `except ValueError:` recovery branch makes
      its own `db.get` call outside any handler, so a corrupt-document read
      followed by a failing retry propagates. The T13 conclusion is
      unchanged — the probe was blind to the ordinary raising-store fault,
      which is the one it existed to catch — but "unfalsified" is not
      "true", and §7 says assert only what the repo proves. Corrected in
      the code, in D17, and here.

      A second test pins the other half independently: a login against a
      raising store must write NO secret. No cookie is necessary but not
      sufficient — writing a fresh secret over a row nobody could read signs
      every OTHER device out, and inferring that from the cookie assertion
      would leave it unguarded. Confirmed distinct: a mutation that mints an
      in-memory fallback secret fails the cookie test and leaves the
      no-write test green.

- [ ] T11: a focus move that fails entirely tells only the developer console — state: queued (no deps)

      Raised in review of #230 and accepted as a follow-up rather than built
      there. `_focusWhenShown` warns to `console.warn` if both the flush and
      the retry fail. That reaches somebody with devtools open; it reaches
      nobody who is actually affected, and the person affected is exactly who
      WCAG 2.4.3 exists to protect.

      A user-visible fallback is the right shape: a toast, or
      `document.body.focus()` plus a visible status-line update.

      The path should never execute — but "should never" is what the original
      bug said too.

- [x] T12: JS inside a Jinja template gets no lint pass — state: merged #232 · bundled into `specs/CI-003-fast-gate.md` as Part B, implemented as rule 8 of `scripts/check_test_traps.py`

      Two things this task's original write-up got wrong, both corrected in the
      spec: it claimed ESLint covers `couchpotato/ui/static`, and **there is no
      ESLint in this repo at all** (no config, no devDependency; vitest's
      include is `tests/unit/**` only). And a dropped `+` is a syntax error only
      where ASI cannot terminate the expression — verified with `node --check`,
      `console.warn('a'\n'b');` is red but `var x = 'a'\n'b';` parses clean. The
      rule catches the #230 defect and a large class like it, not every dropped
      operator, and the PR must not claim otherwise.

      Found by breaking it: a missing `+` in a multi-line string inside
      `suggestions.html`'s `<script>` block made the whole Alpine component
      fail to parse, and four E2E tests went red. Ruff does not see template
      JS, ESLint does not, and vitest only covers `couchpotato/ui/static`.

      A syntax error in any template's inline script is invisible until a
      browser test happens to exercise that page — and pages with no E2E
      coverage would ship dead. A `check-traps` rule that extracts `<script>`
      blocks from templates and parses them would close the class for a few
      lines, per the standing preference for enforced checks over remembered
      ones.

- [x] T9: PR 7 — make the accessibility gate fast (owner request 2026-08-07) — state: merged #232 · **AC-A11Y-2 closed after merge** by a real red/green pair on CI (`b42a5845` run 31255505196 = failure, `2e545adc` run 31255866860 = success); it was UNVERIFIABLE when the box was first ticked, which review rightly flagged · spec `specs/CI-003-fast-gate.md`, 49 ACs written by `/plan-cycle` 2026-08-08 (security, qa, simplicity, operability, accessibility). Bundled with T12; both are gate-only changes

      **The owner was right and three rounds of my own "corrections" were
      measuring the wrong thing.** Every earlier version of this task reported
      the accessibility JOB duration (median 139s) and concluded the report of
      "more than ten minutes" needed correcting. Nobody had measured the wait.
      Wall-clock from workflow start to the accessibility verdict:

          632 637 648 649 653 656 656 664 671 678 678 682
          n = 12   median = 656s = 10 min 56s

      Accurate to within seconds. A second independent sample during the
      planning cycle returned 666s at n=13, so the figure is stable.

      Median offsets from workflow start (n=10): test 0→238s, ui-e2e-tests
      246→514s, accessibility 516→654s while itself taking 138s. **516 of the
      656 seconds is queueing behind `needs: ui-e2e-tests`** — an edge added
      2026-02-16 in `40539241` with no stated reason, and with no data
      dependency since T1.7 gave the job its own seeded server.

      So the priority inverted: the browser cache this plan originally
      headlined is worth ~27s (4%) and the edge is worth ~516s (79%). The cache
      is retained as the TAIL fix — it is the only step here that has ever
      stalled (610s of a 697s job).

- [ ] T20: the Discord notifier reports success on a rejected notification — state: queued (no deps)

      Raised reviewing T17 (#246) and explicitly held out of it as out of
      scope: T17 was the three SonarQube findings, and this changes
      notification delivery semantics.

      `couchpotato/core/notifications/discord.py`, in `notify`:

          r = requests.post(...)
          r.status_code

      Two defects, one cosmetic and one not.

      1. The bare `r.status_code` is a no-op — the value is never read.
         It reads as leftover debug code. Note it is NOT quite dead: it
         is the only thing that would raise on a torn response object,
         and deleting it is safe but should be done knowing that.

      2. `requests.post` does not raise on a non-2xx response, and
         nothing checks the status, so a webhook answering 400, 401, 404
         or 429 falls through to `return True`. The caller believes the
         notification was delivered when Discord rejected it. A rate-limited
         or revoked webhook therefore fails silently and permanently, which
         is the worst shape for a notifier: the operator learns nothing is
         arriving only by noticing its absence.

      Fix shape: `raise_for_status()`, matching the pattern the Synology
      work in T17 already establishes in this repo, so the existing
      `except` returns False and logs. Check the sibling notifiers for the
      same shape before assuming it is Discord-only.

      **Not folded into T17 deliberately.** Two of T17's own fixes each
      introduced a defect in adjacent code (the timeout made an
      `UnboundLocalError` reachable; the retry bound regressed multi-entry
      cleanup), so a third adjacent change to the same file, altering what
      `notify` returns, is exactly the shape that keeps going wrong. It
      gets its own task and its own tests.

- [ ] T21: a kill between the password save and the rotation loses the revocation — state: queued (no deps)

      Raised on #248 (T14) by two reviewers independently, one rating it P1
      and one Low. Recorded rather than folded in, because T14's diff already
      reshapes the auth path and this needs a startup reconciliation of its
      own.

      T14 moved the rotation AFTER `self.save()` commits, which fixes the
      common case: any I/O error on the save no longer signs every device out
      for a password change that was never persisted. The residual window is
      narrower and the opposite way round. If the process is killed between
      `save()` returning (`settings.py:512`, `config.ini` now holds the NEW
      password) and `rotate_session_secret()` completing its database write,
      a restart finds the new password live and the OLD signing secret
      intact. `ensure_session_secret` reuses it, so a cookie captured before
      the change stays valid until its own expiry — 24 hours, or 30 days with
      "remember me". A password change that DID persist silently revoked
      nothing, which is the AC-SEC-38 guarantee the feature exists to provide.

      Severity, honestly: much smaller than what T14 fixed. That fired on any
      save failure; this needs a kill inside a specific instant between two
      writes. Nobody is locked out and nothing is lost. But it is silent, and
      the operator's belief that they revoked access is exactly what they
      acted on.

      **Fix shape, and the reason this is tractable rather than a
      two-phase-commit rabbit hole:** `Settings.save` is already atomic
      (temp file, fsync, rename — `settings.py:268`), and `md5Password`
      already writes a second key (`auth_required`) into the in-memory parser
      specifically so the caller's single `save()` persists both together or
      neither. A rotation marker can ride the same write: set
      `session_rotation_pending` in the parser next to `auth_required`, so
      the one atomic save persists the new password AND the intent to
      rotate. `rotateSessionSecretAfterSave` clears it after rotating.
      Startup reconciles: marker present means the rotation did not complete,
      so rotate now.

      That does not eliminate a window so much as move it somewhere
      recoverable — a kill before the atomic save leaves neither the password
      nor the marker, which is correct. Prove it by killing between the two
      writes, not by reasoning about it: the previous three attempts in this
      area all failed on harnesses that could not distinguish the states.

- [x] T22: `Database.deleteCorrupted` cannot delete anything on the SQLite adapter — state: **fixed** (2026-08-12), report-only (owner decision, not the "implement the delete" option below)

      Found by review disagreement on #249: one reviewer verified the call
      chain existed, the other checked whether it works. Driven against a
      real adapter:

          get(with_storage=False) -> TypeError: unexpected keyword 'with_storage'
          _delete_id_index        -> AttributeError: no attribute
          row still present after "delete"? -> v1

      `core/database.py:330-331` calls `db.get('id', _id, with_storage=False)`
      — `SQLiteAdapter.get` takes `(index_name, key, with_doc=False)` — and
      then `db._delete_id_index(...)`, which exists nowhere in the tree.
      Both are CodernityDB survivors. The pair sits inside a blanket
      `except Exception:` logging at DEBUG, so every failure is invisible.

      Consequence: `database.delete_corrupted` is a no-op. Every caller that
      fires it believes a corrupt document has been removed, and it has not
      — `Settings.getProperty` fires it on a corrupt property row and then
      returns None, so the corrupt row is read again on the next call, for
      the life of the install. This is the same shape as the guard that
      cannot fail, one layer down: a recovery that reports success by
      logging nothing.

      Decide between: implement it against the real adapter API (`db.get`
      then `db.delete`), or delete it and remove the event, which is honest
      if nothing should be auto-deleting documents. **Deleting rows in
      response to a read is a destructive path** — whichever way, it needs
      the data-risk ranking applied, and a test proving the corrupt row is
      actually gone rather than that the call returned.

      **Decided: report, do not delete (owner, 2026-08-12).** The trigger is
      a JSON decode failure on a stored document -- the raw row is still
      there, in principle repairable by hand. Implementing the delete would
      convert "sits there unreadable and noisy" into "permanently gone" for
      a recovery mechanism nothing has needed working: the no-op has been in
      production for the whole SQLite era with no report of the missing
      auto-delete, and the data-risk ranking puts an irreplaceable loss
      above making a dead code path correct. `deleteCorrupted` /
      `database.delete_corrupted` are renamed to `reportCorrupted` /
      `database.corrupted_document` (the old name promised a deletion it
      never performed, which is a trap on its own); the new handler logs at
      ERROR, names the document id, says plainly it was not deleted, and is
      bounded via `log_suppressed` keyed per document id so one corrupt row
      hit on every read does not flood the ring buffer. All four call sites
      (`settings.py`, `release/main.py` x2, `media/_base/media/main.py`)
      updated; tree-wide grep confirms no other live reference to the old
      names. Tests: `tests/unit/test_corrupted_document_reporting.py` (15
      cases) -- proves the document survives against a real `SQLiteAdapter`,
      `db.delete` is never invoked, the ERROR record names the id and says
      "not deleted", suppression is per-id (two ids logged independently,
      repeats of one id withheld per `log_suppressed`'s contract), and a
      home-directory path in the traceback is redacted by `PrivacyFilter`.
      Every guard mutation-tested: reintroducing the delete, downgrading the
      log level, flattening the suppression key to a constant, and
      pre-interpolating the message all break the corresponding test; each
      mutation was hash-confirmed to land and the file was byte-identical
      after restore.

- [ ] T23: the corrupt-document handling family is unreachable, and the schema is why — state: queued (no deps)

      Found reviewing #250 (T22). A reviewer argued that
      `Settings.getProperty`'s `except ValueError:` branch can never reach
      its `fireEvent`, because the recovery `db.get('property', identifier)`
      re-queries the same corrupt row and `_query_index` parses eagerly via
      `_doc_from_row`, so it raises the identical `ValueError` a second time
      and propagates out of `getProperty` uncaught. Reading the adapter,
      that is correct.

      **But the real reason is one layer deeper, and it was measured.** A
      document whose JSON will not parse cannot be STORED at all:

          UPDATE documents SET data = '{not valid json' WHERE _id = ...
          -> OperationalError: malformed JSON

      That is not a `CHECK` on the table (there is none). It is the 16
      expression indexes over `json_extract(data, ...)`. Proven by removing
      them: with every expression index dropped, the same corrupt write
      SUCCEEDS. The indexes are the guard.

      So the whole `(ValueError, EOFError)` family — four call sites in
      `settings.py`, `release/main.py` x2 and `media/_base/media/main.py` —
      is unreachable on this adapter, and T22's honest reporter is honest
      about something that cannot currently happen. That is still the right
      shape (it was going to be honest about something that could not happen
      either way, and the old version was destructive-by-name), but the
      reachability should be recorded rather than implied.

      Two things to decide, and neither is urgent:

      1. Does the guard hold under maintenance? The indexes are what enforce
         it, so any path that drops or rebuilds them — a migration, a repair,
         a restore — opens a window where malformed JSON can land and then
         cannot be read. Worth knowing before someone writes such a
         migration, not after.
      2. If the family stays unreachable, the four call sites and the
         reporter are dead code, and `T18`'s sweep should either remove them
         or the entry should say why they are kept as a backstop against
         corruption arriving by a route the indexes do not cover (file-level
         damage, a restored backup written by an older schema).

      Do not "fix" the `getProperty` recovery branch in isolation: it is
      error handling for a condition that cannot occur, and repairing
      unreachable code was exactly the trap T15 fell into.

- [x] T24: `hadouken.py` calls `len()` on a boolean — state: **fixed** (2026-08-12), but see T27 — the downloader is still broken upstream of it

      `couchpotato/core/downloaders/hadouken.py:186`:

          'folder': sp(torrent.save_path if len(torrent_files == 1) else ...)

      `torrent_files == 1` compares a list to an int, which is always
      `False`, and `len(False)` raises `TypeError: object of type 'bool' has
      no len()`. It is a transposition of `len(torrent_files) == 1`. Any
      call reaching this line crashes rather than returning a status.

      SonarQube BLOCKER `python:S2159`, found by the first re-scan after
      T17. The test suite did not find it, which says the hadouken status
      path has no test executing this branch — fix and cover together, and
      check the sibling downloaders for the same transposition before
      assuming it is isolated. (`python:S2734` at `putio/main.py:25`, a
      return value in `__init__`, is the other BLOCKER and can ride along.)

- [ ] T25: 39 inputs in the new UI's wizard have no label — state: queued (no deps) · re-confirmed present by the 2026-08-18 scan (still 39 x `Web:InputWithoutLabelCheck`), i.e. NOT yet fixed. **Retracted 2026-08-18: an earlier version of this line called that "independent corroboration by a different tool with a different ruleset". It is not. T25 was CREATED from these same SonarQube findings — the body below says so — so a second scan reporting the same rule is the same tool agreeing with itself. A re-run is evidence the defect is still open, and nothing more.**

      `couchpotato/ui/templates/wizard.html`, all 39 instances of SonarQube's
      `Web:InputWithoutLabelCheck`. This is the NEW UI, not the legacy tree
      being retired, and this project states a WCAG 2.2 AA floor enforced as
      automated tests in both themes and at phone width.

      **The interesting part is not the labels, it is that the a11y gate is
      green.** Either the axe-core suite never visits the wizard, or it
      visits a state where those inputs are not rendered, or axe and Sonar
      disagree about what counts. Establish WHICH before fixing anything: if
      the suite cannot reach the wizard, the labels are a symptom and the
      coverage gap is the defect — the same "guard that looks like it is
      protecting something" shape this plan keeps finding.

      Do not add labels and call it done while the gate still cannot see
      the page.

- [x] T26: the analyser has never had coverage data, so the trend it exists for is blank — state: **fixed** (2026-08-11), 0.0 → 53.3%

      `sonar-project.properties` sets `sonar.python.coverage.reportPaths=coverage.xml`,
      but the first re-scan reported `coverage 0.0` because no `coverage.xml`
      was generated before running it. Every scan so far has published a zero.

      Coverage-as-a-trend is one of the two things the analyser is for (the
      other being issues that survive between sessions), so this is not
      cosmetic: a flat zero is indistinguishable from real zero coverage, and
      it makes the one metric that would show the suite improving useless.

      The fix is the invocation, not the config: generate `coverage.xml` in
      the same run that scans. The properties file already records why
      unit-only coverage would understate this project (the adapter and
      plugin loading are exercised by integration tests), so decide what to
      include before publishing a number people will read as the truth.

      **Done.** The config was never wrong — `sonar.python.coverage.reportPaths`
      and `sonar.javascript.lcov.reportPaths` were both already set, and the
      properties file even documented the two commands. The reports simply
      were not generated before scanning, every time. Measured after
      generating both and re-scanning master:

          coverage        0.0  ->  53.3
          line_coverage        ->  52.8
          lines_to_cover       ->  20917
          uncovered_lines      ->  9872

      Plausibility checked rather than assumed, which is what that file asks
      for: Python alone measures 56.74%, the properties file records a
      previous scan at 51.8%, and 53.3% is the expected blend once the
      untested legacy JS is included.

      **Mechanised, because a remembered step is exactly what failed.**
      `make coverage` generates both reports and fails if either is empty;
      `make sonar` depends on it so they cannot be skipped, and reads the
      token from a file into the environment so it never reaches the process
      list. `make sonar-token-check` runs FIRST, so a missing token fails in
      0.04s instead of after the four-minute coverage run — a target that
      wastes an evening gets abandoned rather than fixed. Not wired into
      `verify` and not in CI: it is reporting, not a gate, and the runners
      cannot reach the server.

- [x] T27: hadouken's `TorrentItem` subclasses shadow the base class's properties — state: **fixed** (2026-08-12)

      Found by the implementer while fixing T24, flagged rather than folded
      in, and it is the bigger of the two.

      `TorrentItem` (`couchpotato/core/downloaders/hadouken.py:359`) declares
      `info_hash`, `save_path`, `name` and `state` as `@property`.
      `TorrentItemv4` (`:468`) and `TorrentItemv5` (`:385`) redefine all four
      as **plain methods with no decorator**. The subclass wins in the MRO,
      so on a real instance the attribute is a bound method, not a value.
      Driven on a minimal repro of the same shape:

          type(v.info_hash)   -> method
          v.info_hash.upper() -> AttributeError: 'function' object has no
                                 attribute 'upper'
          v.info_hash()       -> 'abc123'      (the value, only if CALLED)

      `getAllDownloadStatus` does `torrent.info_hash.upper()` at `:180` and
      passes `torrent.info_hash` into `get_files_by_hash` at `:173`, both
      BEFORE the `len()` line T24 repaired. So the function raises earlier
      than the bug T24 fixed, and **T24 alone does not make this downloader
      work** — that is why T24 is ticked with a pointer here rather than as
      "hadouken status fixed".

      Same root cause as T24, one layer up: this downloader has no test that
      constructs a real `TorrentItemv4`/`v5`, so two guaranteed crashes have
      sat in it undisturbed. T24 added coverage for the one line in its
      scope using a plain fake torrent, which is deliberately narrow and
      does NOT exercise these classes.

      Fix shape: decide whether the base class's `@property` declarations or
      the subclasses' plain methods are the intended interface, make both
      subclasses match, and update the four call sites in
      `getAllDownloadStatus` accordingly. Then test against a real
      `TorrentItemv4` and `TorrentItemv5` built from representative API
      payloads, not a fake — a fake torrent is exactly what let this survive.

- [x] T28: hadouken's user_pass auth cannot connect — `b64encode` is handed a str — state: **fixed** (2026-08-12)

      Third guaranteed crash found in this one file, flagged by the T27
      implementer rather than folded in. `hadouken.py:57`:

          header = 'Basic ' + b64encode(self.conf('auth_user') + ':' + self.conf('auth_pass'))

      `b64encode` requires bytes. Driven:

          b64encode('user:pass') -> TypeError: a bytes-like object is
                                    required, not 'str'

      Fires in `connect()` for any v5 Hadouken configured with
      `auth_type = 'user_pass'`, so that authentication mode has never
      worked. `api_key` auth is unaffected and takes a different branch.

      Fix is `.encode()` on the joined string and `.decode()` on the result
      (the header must be a str), but **do not fix it blind**: this is a
      credential-carrying line, so check the encoding matches what Hadouken
      actually expects rather than what makes the TypeError go away, and
      keep the credentials out of any log added while testing.

      **What this file's record says about scope.** Three separate
      guaranteed crashes have now come out of `hadouken.py` (T24's `len()`
      on a boolean, T27's property shadowing, and this). That is the
      "question the frame" signal, so the frame was questioned before
      writing this entry, and the answer was measured rather than assumed:

      - `download()` does NOT use the broken attributes — it computes the
        info hash itself and calls `add_magnet_link`/`add_file`. It works.
      - `connect()` works under `api_key` auth.
      - `getAllDownloadStatus()` was the broken half, and T24 + T27 fixed it.

      So this downloader was **partially** functional, not dead: an operator
      on `api_key` auth could add torrents and simply never see them
      complete. That rules out the tempting conclusion — deleting it under
      T18 as obviously-dead code — because someone may have it configured
      and working to that extent. Fix T28, do not remove the module.

      > **SUPERSEDED — the paragraph above is wrong. See T30 and "The
      > hadouken question".** It was written before `JsonRpcClient.invoke`
      > was measured. That posts a `str` body, which Python 3 rejects, so
      > no RPC succeeds on either version: nothing could add a torrent and
      > nobody can have been using this. The "do not remove the module"
      > conclusion does not survive, and the recommendation is now to
      > remove. Left in place rather than rewritten so the correction is
      > visible, but do not read it on its own.

      The real lesson is the test gap, not any one bug: nothing constructed
      a real `TorrentItemv4`/`v5` or exercised `connect()`, which is how
      three crashes shipped. T24 and T27 added coverage for their own lines;
      `connect()` still has none.

- [x] T29: `HadoukenAPIv4` cannot be constructed, so the entire v4 protocol is unusable — state: **merged #261** (`e433ceba`, 2026-08-18) — closed by REMOVAL, not by a fix; verified from `gh pr view` and by `git ls-files` on master showing no hadouken file tracked

      Fourth guaranteed crash from this file, found by the T28 implementer
      driving `connect()`'s v4 branch for real instead of mocking the API
      class out — which is precisely the gap that hid the other three.

          HadoukenAPIv5(HadoukenAPI)   -> inherits __init__, constructs fine
          class HadoukenAPIv4:         -> inherits object, defines no __init__
          HadoukenAPIv4('client')      -> TypeError: HadoukenAPIv4() takes no arguments

      `connect()` does `HadoukenAPIv4(client)` at `:47`, so a v4 install
      cannot get past `connect()` at all — regardless of auth mode. And
      because `self.rpc` is never set, every method on the class would fail
      afterwards even if construction succeeded.

      Almost certainly a one-word fix (`class HadoukenAPIv4(HadoukenAPI):`),
      but **verify rather than assume**: check `HadoukenAPI.__init__` takes
      what the v4 call site passes, and that v4 does not rely on differing
      from the base elsewhere. Pinned as current behaviour by
      `test_connect_v4_raises_typeerror_pre_existing_unrelated_bug`; that
      test must be inverted, not deleted, when this is fixed.

      **What actually works, measured — the earlier note in T28 was right
      but incomplete.** Corrected here rather than left standing:

      | configuration | state |
      |---|---|
      | v4, any auth | unusable — `connect()` raises (this task) |
      | v5 + `api_key` | connects; **every operation then fails** (T30) |
      | v5 + `user_pass` | connects after T28; **every operation then fails** (T30) |

      **This table replaces a WRONG one, and the correction matters more
      than the table.** An earlier version claimed v5 + `api_key` "works:
      connect, download, and status". Review of #259 disproved it and I
      confirmed by driving it: `JsonRpcClient.invoke` passes a `str` body to
      `opener.open`, which Python 3 rejects, so NO RPC succeeds on either
      protocol version (T30). `download()` and `getAllDownloadStatus()` both
      route through it.

      So **no configuration of this downloader has ever worked**, and the
      "do not delete it, someone may be using it" argument I made twice was
      built on that wrong table. Nobody can be using it: it cannot add a
      torrent, cannot report status, and cannot connect at all on v4.

      **On the frame.** Four guaranteed crashes in one file is well past the
      point where patching individually deserves justifying. The
      justification is that each of the four arrived with tests, so the
      module is acquiring the coverage whose absence caused all of them:
      T24 covered the status dict, T27 the `TorrentItem` subclasses, T28
      `connect()`'s v5 branches. This task finishes `connect()`. Every one
      of these is a Python 3 migration artefact — `b64encode` str/bytes,
      property semantics, a dropped base class — which is what an
      unexercised module looks like after a language migration.

      **Closed by removal, not by fixing the constructor.** The owner
      answered "The hadouken question" below: remove rather than fix. This
      task's fix was never applied — `couchpotato/core/downloaders/hadouken.py`
      is deleted outright, so the `HadoukenAPIv4` construction bug and its
      test (`test_connect_v4_raises_typeerror_pre_existing_unrelated_bug`)
      no longer exist to fix or invert.

- [x] T30: no hadouken RPC can succeed — `invoke` posts a str body — state: **merged #261** (`e433ceba`, 2026-08-18) — closed by REMOVAL, not by a fix; verified from `gh pr view` and by `git ls-files` on master showing no hadouken file tracked

      Fifth guaranteed crash in this file, raised in review of #259 and
      confirmed by driving it:

          urllib.request.Request(url, data = json.dumps(data))
          opener.open(request)
          -> TypeError: POST data should be bytes, an iterable of bytes,
             or a file object. It cannot be of type str.

      `JsonRpcClient.invoke`. Every operation on both protocol versions routes
      through `JsonRpcClient.invoke`, so `download()`, `getAllDownloadStatus`,
      `pause`, `removeFailed` and `processComplete` all fail before any
      network call. The tests added by T24/T27/T28 never invoke an RPC —
      they inspect the constructed client — which is why none of them caught
      it.

      Likely also broken alongside it: `HadoukenAPIv5.add_file` passes
      `b64encode(data)` (bytes) into `json.dumps`, which cannot serialise
      bytes. Not separately verified; check it when this is fixed.

      **A credential exposure is gated behind this, and the ORDER matters.**
      Review of #259 also raised, correctly, that `connect()` strips any
      supplied scheme and hard-codes `http://` when building the v5 client
      URL, so once Basic auth
      works the operator's username and password go over the wire in
      trivially reversible base64. That is not currently reachable — the
      RPC dies first — but **fixing this task makes it live**. So: do not
      fix `invoke` without fixing the scheme in the same change. Same
      finding as T17's Synology `S4830`, in a second downloader.

      **NOT unreachable, and an earlier draft of this entry said it was.**
      `self.conf('auth_user')` returns `None` when never saved — the option
      declares no `'default'` in this file's config block — so `None + ':'`
      raised `TypeError: can only concatenate str (not "NoneType") to str`
      inside `connect()`, BEFORE any request. I recorded it as gated behind
      this task's RPC bug without tracing it; review of #259 corrected me.
      That is the second unverified reachability claim I published in that
      PR, in a PR whose subject was correcting one.

      Fixed in #259 rather than deferred here, since it was the very line
      being edited: a half-filled `user_pass` config is now refused with a
      logged error naming what is missing, matching how the two guards
      above it report a bad config.

      **Closed by removal, not by fixing `invoke`.** The owner answered "The
      hadouken question" below: remove rather than fix. `invoke`'s str-body
      bug, the credential-exposure ordering constraint it gated, and the
      hard-coded `http://` all left with the module —
      `couchpotato/core/downloaders/hadouken.py` is deleted, nothing was
      patched.

- [x] T31: `getValues()` returns an unregistered section's secrets UNMASKED — state: **merged #261** (`e433ceba`, 2026-08-18) — masking by registration, verified present on master after merge

      Found while removing hadouken, by an implementer driving the orphan
      `[hadouken]` config section rather than reasoning about it. General,
      pre-existing, and NOT specific to hadouken — it affects any section in
      `config.ini` whose plugin is not registered.

      Driven against a real `Settings` with an unregistered section:

          orphan section present in getValues()?  True
            api_key   -> 'SECRET_API_KEY_VALUE'
            auth_pass -> 'SECRET_PASSWORD_VALUE'
            SECRETS LEAKED UNMASKED? True

      `Settings.getValues` masks only when
      `self.getType(section, option) == 'password'`, and `getType` reads
      `self.types`, which is populated by `setType` during a plugin's
      `registerDefaults`. No plugin, no registered type, no masking — so the
      raw value goes into the response that the `settings` API view returns.

      Reachable for: any install carrying config for a plugin that was
      removed, renamed, or failed to load. Note the loader swallows
      ImportError at DEBUG, so a plugin that fails to import silently
      produces exactly this state for its own saved credentials.

      Removing hadouken makes it permanent for anyone who had one saved,
      which is how it surfaced — but fixing it there would be the wrong
      layer. The fix belongs in `getValues`: an unregistered section's
      values should be masked by default rather than exposed by default,
      since an unknown type is precisely when we cannot know it is safe.
      Beware the obvious over-correction — masking everything unregistered
      would also mask harmless values an operator may need to read to
      recover, so decide deliberately between masking all of it and masking
      on a name heuristic (`*_key`, `*_pass*`, `*token*`, `secret`), and say
      which and why.

      **That last paragraph used to read "not blocking the hadouken
      removal", and it was wrong.** Corrected 2026-08-18 after the codex
      reviewer blocked #261 on exactly this. The exposure does predate the
      removal, but the removal changes its kind for `[hadouken]`, not just
      its permanence: before #261 those two credentials were registered as
      type `password` and masked, and after it they are returned in the
      clear. A change that converts a masked secret into a plaintext one is
      a regression introduced by that change, whatever the state of the
      surrounding class of bug. So the fix ships in #261.

      The "mask all vs name heuristic" question above resolves to NEITHER.
      A name heuristic (`*_key`, `*_pass*`, `*token*`) misses the next
      secret, which is the whole failure mode of a denylist. Mask by
      REGISTRATION: an option that no plugin declared is masked, one that
      was declared is not. That also disposes of the operator-recovery
      worry, since anything an operator can read in the UI is by definition
      registered.

      One trap sits under the obvious implementation. `registerDefaults`
      records a type only `if option.get('type')`, so a legitimately
      registered plain-string option has NO entry in `self.types` either.
      Masking on "absent from `self.types`" would blank out real settings in
      the UI. The registration record has to be kept separately, at
      `registerDefaults`.

      Masking only: the orphan values stay on disk. Deleting a user's config
      data is irreversible, and that is not what a disclosure fix is for.

- [ ] T32: the pre-push hook runs the FULL gate on a branch DELETE, which has no diff to gate — state: queued (no deps)

      Found by collision, not by review. Another Claude session running in
      this same checkout ran `git push -q origin --delete
      fix/harness-triggers`, which fired `.githooks/pre-push`, which started a
      full `make verify` including a Playwright suite against the same
      `.e2e-data` directory an in-flight gate run was already using. Both
      verdicts became unreliable and the gate had to be re-run from scratch.

      That session then measured the same delete three ways, which is what
      turns this from a theory into a fact: two `git push --delete` attempts
      hung long enough to be killed (one at five minutes), both sitting in
      `make verify`; the same deletion issued as `gh api -X DELETE
      .../git/refs/heads/...` returned in under two seconds. Same outcome, no
      hook, no gate.

      `.githooks/pre-push` never reads stdin — there is no `read`, no `while
      read`, no reference to the ref arguments anywhere in it. So it cannot
      distinguish a deletion from an update, and it gates a push whose diff is
      empty by construction.

      **The signal is the LOCAL sha on stdin, not `$3`.** `$3` is not a
      positional argument of `pre-push` at all: git passes exactly two, the
      remote name and the remote URL. Everything about the refs arrives on
      stdin, one line per ref as `<local_ref> <local_sha> <remote_ref> <remote_sha>`,
      and a deletion is the all-zeroes LOCAL sha with `(delete)` as the local
      ref. The condition to skip on is "EVERY line is a deletion": a mixed
      push that deletes one ref and updates another still has real code to
      gate, and skipping that would be the exact false-green this hook exists
      to prevent. The test has to pin both directions (§11): it must fail if a
      delete-only push runs the gate, AND fail if a mixed push skips it.

      Note the hook must still consume stdin even when it decides to gate.
      Reading it is not optional bookkeeping — a hook that exits without
      draining stdin can hand git a broken pipe.

      Not folded into #261: it wants its own diff and its own review gate,
      and it has nothing to do with removing a downloader.

- [x] T33: dependency triage backlog — review AND apply the Dependabot updates — state: **merged #262** (`09a3d153`, 2026-08-18) — all five taken, decisions recorded; the five Dependabot PRs closed themselves once the versions landed

      Surfaced by the push on 2026-08-18: GitHub reported "1 vulnerability on
      the default branch (1 high)". Measured rather than relayed:

          npm audit --omit=dev  ->  found 0 vulnerabilities
          npm audit             ->  7 high severity vulnerabilities

      `package.json` declares NO runtime dependencies at all. Every high is in
      the test toolchain. The named alert, `extract-zip <= 2.0.1` (unvalidated
      symlink path traversal, alert #114), arrives via
      `@lhci/cli -> lighthouse -> puppeteer-core -> @puppeteer/browsers`, and
      `first_patched_version` is **null** — there is no fix to take. So its
      only correct outcome is HOLD, and the condition for revisiting is a
      patched `extract-zip` release or `@puppeteer/browsers` dropping the
      dependency. Worth stating plainly because the banner reads as shippable
      risk and is not: nothing here reaches a user's install.

      `nanoid` DOES have a fix available via plain `npm audit fix` (no
      `--force`), and per §3a an unchanged `package.json` afterwards is the
      good outcome — only resolved transitive versions moved.

      Open Dependabot PRs to decide, each needing take/reject/hold WITH the
      reason recorded: #255 rarfile 4.4->4.5, #254 uvicorn 0.51.0->0.52.1,
      #253 mutmut >=3.6.0->>=3.7.0, #252 ruff 0.16.1->0.16.2, #251
      qbittorrent-api 2026.7.0->2026.8.0. Note the standing HOLDs on
      stevedore 5.9.0 (drops Py3.10) and rebulk 6.0.1 (coupled to guessit
      3.8.0) — those get closed, not merged, and they re-propose each cycle.

      Run `pip check` / `npm ls` IMMEDIATELY after applying anything, before
      running anything else: a bump that breaks the graph is rejected outright
      regardless of what advisory it claims to fix.

      Deliberately NOT folded into #261. A lockfile change riding in on a
      downloader removal is the same mistake as riding the hook fix in on it,
      and a dependency bump is a code change made by someone else.

      **Owner instruction, 2026-08-18: these are to be reviewed AND APPLIED as
      part of this plan**, not left as a standing triage note. So the
      deliverable is a decision recorded for every one of them, with the taken
      ones actually landed:

      1. **Take it** — but run `pip check` / `npm ls` IMMEDIATELY after
         applying and BEFORE anything else. A bump that breaks the dependency
         graph is rejected outright no matter what advisory it claims to fix.
         Then re-run the full gate, because a dependency bump is a code change
         written by someone else.
      2. **Reject it, with evidence** — breaks the graph, drops a supported
         runtime, or fights a deliberate pin. CLOSE the PR so it stops
         re-proposing.
      3. **Hold it, with the reason and the condition for revisiting.**

      `extract-zip` is already decided: HOLD, because there is no patched
      version to take. `nanoid` is a plain `npm audit fix` (never `--force`),
      and an UNCHANGED `package.json` afterwards is the good outcome — it
      means only resolved transitive versions moved and nothing about the
      project's contract changed.

- [ ] T34: move option-name normalisation from the write site to the read site in `Settings` — state: queued (no deps)

      **This task exists because rule 11 fired, not because a bug is open.**
      Three commits in a row landed defects in `registerDefaults`, and a
      reviewer grading the third as new work identified one root cause for all
      of them: normalisation was put at the WRITE site instead of the READ
      site.

          e5ecaa9c  recorded names raw          -> mismatch with folded parser keys
          88405b3f  folded at the write site    -> needed `self.p` in a method whose
                                                   every other mutation is parser-optional
          df6c0e18  patched that dependency     -> a ternary that tracks the parser in
                                                   only one of its two branches

      `getValues` already REQUIRES the parser — driven, it raises
      `AttributeError: 'NoneType' object has no attribute 'sections'` at
      `self.sections()` when `self.p` is None — so the fold can live there
      unconditionally:

          # registerDefaults: no parser dependency at all
          self.registered_options.setdefault(section_name, set()).update(options)

          # getValues: where the parser is guaranteed
          registered_in_section = {
              self.p.optionxform(n) for n in self.registered_options.get(section, ())
          }

      That deletes the ternary, the comment defending it, and the whole "what
      if `self.p` is None" class, while making the parser-tracking guarantee
      unconditional rather than half-true. It is SMALLER than what is there
      now, which is the tell that the current shape is wrong.

      **The trap in doing it, and the reason it is a task rather than a fourth
      patch:** the current test asserts INTERNAL state —
      `assert settings.registered_options['early'] == {'apitoken'}` — so any
      reshape forces a test edit, and a test edited to match new internals is
      exactly where a false green enters. Drive the reshape from OBSERVABLE
      behaviour (`getValues()` does not star out a registered `ApiToken`) and
      DELETE that internal-state assertion rather than rewriting it. The
      coupling is a second-order finding in its own right: it is what makes
      this method expensive to correct.

      Not a bug. `df6c0e18` is correct and guarded — four landed mutations,
      one of them against the full 3406-test unit suite. This is the "question
      the frame" deliverable that rule 11 asks for after the third round.

- [x] T35: post-merge SonarQube scan — state: **done** (2026-08-18, against master `09a3d153`) — results below in tick 40; nothing resolved or dismissed

      Owner instruction, 2026-08-18: push a fresh scan once this work is
      merged. Ordered AFTER T33 deliberately, so one scan reflects both the
      merged code and the dependency decisions rather than needing two.

      `make sonar` (which runs `make coverage` first as a recipe line, so the
      reports cannot be forgotten). Reporting only.

      The rules on this are not negotiable and are restated here because a
      scan is exactly where they get quietly broken:

      - **Never resolve, dismiss or accept a finding to move a number, and
        never disable a rule to avoid one.** If a finding is real, fix the code
        or leave it open. On a dashboard, dismissal is indistinguishable from
        progress, which is what makes it the one action that silently destroys
        the tool's value.
      - **Ask the owner before resolving anything.** Every transition carries a
        comment, and the comment states the condition under which the decision
        expires.
      - **Use `SONAR_TOKEN`, never the admin token.** Keep the credential that
        can rewrite history out of routine commands. Load it without echoing
        it; never print, paste or commit the value.
      - **Never a gate.** Not in CI, and not a merge blocker. If a scan can
        fail a build, the pressure becomes making the number green rather than
        the code better. CI runners cannot reach the server anyway, and
        exposing SonarQube publicly to work around that is not on the table.

      Report the deltas against the last scan (vulnerabilities 3 -> 0, security
      rating D -> A, BLOCKER bugs 2 -> 0, coverage 0.0 -> 53.5%) so the trend
      is visible rather than just the current state.

- [x] T36: a hostile archive entry escapes the extraction directory via BACKSLASHES — state: **merged #265** (`b27bd49f`, 2026-08-19) — **security, pre-existing**. Verified on master rather than from the merge report: the guard constants are present in `extractor.py` and `tests/unit/test_extractor.py` runs 54 passing. Fifteen review rounds; the last **two** commits added no production code, only tests and records. (First written as "the last four", which review measured and refuted: `5fde7144` and `d7c1e30e` both changed `extractor.py`, +66/-24 between them. The clause matters because "has the code stopped moving" was the signal used to decide the PR had converged, so overstating it flatters exactly the judgement it was offered to support.)

      Found by the security lens while reviewing the rarfile 4.5 bump, and
      confirmed independently by driving the real `sp()` rather than reading it:

          entry name                             -> resolved target
          ../../../evil.txt                      -> /tmp/extract_here/evil.txt   contained
          ..\..\..\CP_PWNED_BACKSLASH.txt        -> /CP_PWNED_BACKSLASH.txt      *** ESCAPES ***
          /etc/passwd                            -> /tmp/extract_here/passwd     contained
          ....//....//evil.txt                   -> /tmp/extract_here/evil.txt   contained

      `extractor.py` flattens each entry with
      `os.path.basename(info.filename)`, which defeats `../`, absolute paths
      and `....//`. But on POSIX a BACKSLASH is not a separator, so
      `..\..\..\x` survives `basename` intact. `sp()`
      (`helpers/encoding.py`) then does the damage in its Windows-path
      conversion: it replaces `\` with `/` **and prepends `/`**, anchoring the
      result at root, after which `normpath` walks straight out of
      `extr_path`. The reviewer drove the full `extractArchive` and the file
      was written to disk outside the extraction directory.

      **Reachable from an ordinary automated download.** This is the library
      that parses a `.rar` from a torrent, i.e. exactly the hostile-input path
      the project's threat model names.

      **Bounded, and the bound matters for ranking.** `extractor.py` skips
      extraction when the destination already exists, so this is arbitrary
      NEW-FILE creation, not overwrite — measured against a stand-in
      `couchpotato.db` three levels up, the target resolved onto it and the
      bytes were unchanged. It cannot destroy the database, `config.ini` or
      media, which keeps it off the top of the loss hierarchy but does not make
      it acceptable.

      **Taking rarfile 4.5 does NOT close it.** 4.5 ships a realpath escape
      guard in `RarFile._extract_one`, but CouchPotato never calls
      `extract()`/`extractall()` — it rolls its own loop over `open(info)`, so
      it bypasses the guard entirely. That is worth stating plainly, because
      "we took the security bump" would otherwise read as coverage.

      Fix belongs in `extractArchive`: reject or sanitise the entry name before
      `sp()`, and assert the resolved target is under
      `os.path.realpath(extr_path)`. The test must feed the BACKSLASH form —
      a `../` fixture passes today and would guard nothing (§11: feed it
      hostile inputs, not polite ones).

      Symlink following is genuinely safe and needs no work: rarfile returns
      `io.BytesIO(redir_name)` for a symlink entry, so CP writes a regular file
      containing the link target as text and never creates a link.

- [ ] T37: the login throttle is bypassable by rotating `X-Forwarded-For` — state: queued (no deps) — **security**

      `rate_limit.py` rests on a premise that is the exact inverse of the
      truth. Its comment says "nothing here configures uvicorn's
      `proxy_headers` or `forwarded_allow_ips`, so `request.client.host` is the
      TCP peer". Not configuring them is precisely WHY
      `ProxyHeadersMiddleware` is active — verified against the installed
      uvicorn:

          proxy_headers        -> proxy_headers: bool = True
          forwarded_allow_ips  -> defaults to 127.0.0.1

      So on the deployment shape this project documents (nginx/Caddy/Traefik on
      the same host, or a proxy container talking to a port-mapped app) the
      peer IS 127.0.0.1, the middleware trusts it, and the client IP becomes
      whatever the request claims. Reviewer's measurement, real middleware
      wrapping the real limiter at `max_requests=5`, 12 x `POST /login/`:

          A  no XFF                    -> 7 x 429
          B  rotating X-Forwarded-For  -> 0 x 429   (all 12 accepted)
          C  fixed X-Forwarded-For     -> 7 x 429

      That is AC-SEC-42's protection removed entirely, leaving bcrypt's ~166ms
      as the only brake on credential stuffing.

      Not caused by the uvicorn 0.51->0.52 bump: the default is identical at
      0.51.0, and neither release touched proxy headers.

      Whatever the fix, the COMMENT must be corrected too — a comment asserting
      the inverse of the runtime default is how this survived review the first
      time.

- [ ] T38: `simple_healthcheck.py` is dead AND its assertions cannot pass — state: queued (needs: AC-OPS-12 production grep, same blocker as `/getkey`'s deletion)

      Surfaced by the 2026-08-18 SonarQube scan (3 x `python:S5779`) and driven
      before recording. Two defects, one file:

      `test_web_page_content` reads `response.read()`, which is BYTES, then
      asserts `assertIn("<!doctype html>", content)` with a str needle. Driven:

          assertIn(str, bytes): TypeError - a bytes-like object is required, not 'str'

      So the check can NEVER pass. And because every assertion sits inside
      `try: ... except Exception as e: self.fail("Failed to load web page: %s")`,
      and `AssertionError`/`TypeError` are both `Exception`, the failure is
      reported as "failed to load web page" when the page loaded fine. A
      healthcheck that always fails, and blames the wrong component when it
      does, is worse than no healthcheck: it trains the operator to ignore it.

      Sonar's S5779 names the mechanism exactly — an assertion inside a
      try/except that catches its own AssertionError. The other two instances
      have the same shape but DIFFERENT messages, and an earlier version of
      this entry wrongly gave them both the same one:

          :27  assertEqual(code, 200)      -> "Server is not responding: ..."
          :90  assertLess(elapsed, 5.0)    -> "Failed to measure response time: ..."

      So a server that responds slowly is reported as a failure to MEASURE,
      and a server returning 500 is reported as not responding at all. Each
      mislabels its own failure differently, which is worse than one shared
      wrong message: it sends the reader somewhere specific and wrong.

      **The fix is almost certainly deletion, not repair.** Its only consumer
      relationship is the reverse one: `simple_healthcheck.py:76` is the sole
      referrer of the `/getkey` endpoint, and that deletion is already recorded
      as blocked on AC-OPS-12's production grep. Same blocker, same removal.
      Repairing a dead file to keep a check nothing runs would be work spent
      moving in the wrong direction.

- [ ] T39: three provider scrapers access a parsed element without checking it exists — state: queued (no deps)

      2026-08-18 SonarQube scan, `python:S8904` x 6. **Six occurrences, but NOT
      six defects** — an earlier version of this entry said "six providers",
      which was wrong twice over: `awesomehd.py` supplies two of the six, and
      three of the six are not defects at all. Checked each site rather than
      trusting the rule:

          awesomehd.py:40     .get_text on soup.find('authkey')   REAL, unguarded
          filmweb.py:25       ['content'] on html.find('meta')    REAL, unguarded
          filmstarts.py:26    ['content'] on html.find('meta')    REAL, unguarded

          awesomehd.py:37     GUARDED — `if soup.find('error'):` on the line above
          bithdtv.py:83       GUARDED — `toUnicode(nfo_pre.text) if nfo_pre else ''`
          thepiratebay.py:71  TOLERATED — its own try/except leaves total_pages
                              at its initialised 1 and parsing continues

      So the family is three, not six. The two GUARDED ones look like false
      positives from the rule not following the enclosing condition; they are
      NOT being dismissed in SonarQube, because that is the owner's call and
      dismissal is the one action that silently destroys the tool's value.
      Recorded here instead.

      One the scan did NOT flag, found while checking the ones it did:
      `filmstarts.py:21` calls `table.find(...)` where `table` came straight
      from an unguarded `html.find(...)` at `:19`, TWO lines earlier (`:20` is
      blank). That is five lines above the flagged access at `:26`.

      This sentence has now been wrong twice, which is why it carries its own
      history: it first said "one line above the flagged one", conflating the
      distance to the unguarded source with the distance to the flagged line;
      the correction then said "one line earlier" for the `:19` -> `:21` gap,
      which is two. Cite both line numbers and let the reader subtract. Fix it in the same pass; it is the reminder that the rule list is
      a starting point, not the boundary.

      These are provider scrapers, so the input is a third party's markup and
      it changes without notice. The searcher tolerates a provider raising, so
      the blast radius is a dead provider rather than a crashed scan — CRITICAL
      by rule, not urgent by impact. Say which when fixing.

- [ ] T40: `synology.py` returns from inside a `finally` block — state: queued (no deps)

      2026-08-18 SonarQube scan, `python:S1143` (CRITICAL), `synology.py:76`.

      **Corrected 2026-08-18 after review.** An earlier version of this entry
      said the failure is "swallowed silently and the caller is told the
      operation succeeded". That is wrong, and reading the whole construct
      rather than the flagged line shows why:

          except Exception:
              log.error('Exception while adding torrent: %s', ...)
          finally:
              return self.downloadReturnId('') if response else False

      An ordinary failure inside the `try` is caught and LOGGED by the
      preceding `except Exception`, and `response` is still False, so the
      `finally` returns False. The caller is correctly told it failed and the
      log is not silent.

      What remains is narrower and still real: a `return` in `finally`
      discards anything the `except` clause does not catch — a `BaseException`
      such as KeyboardInterrupt or SystemExit, or an exception raised inside
      the handler itself. Those become a silent False rather than propagating.

      Fix it, but fix it for the accurate reason, and pin whichever mechanism
      the test actually drives. A test written against the WRONG mechanism
      would pass on the current code and guard nothing.

- [ ] T41: `sp()` mangles an extraction directory that contains a backslash — state: queued (no deps)

      Found while fixing T36, by trying a fix and measuring it rather than
      shipping it. `extractArchive` builds each target as
      `sp(os.path.join(extr_path, entry_name))`. When `extr_path` ITSELF
      contains a backslash — legal on POSIX, and choosable by a hostile
      torrent naming its folder — `sp()`'s Windows-path conversion rewrites
      the target into a DIFFERENT tree:

          real dir on disk : .../Movie.2020\Sample
          sp() target      : .../Movie.2020/Sample/movie.mkv
          target dir exists: False

      So no entry can be written, whatever the containment check decides. The
      only question is how it fails, and that was measured:

          base WITHOUT sp(): contained=False -> refused cleanly, loop continues
          base WITH    sp(): contained=True  -> write into a missing dir,
                                                raises, ABANDONS the archive

      T36 deliberately kept the first, because a clean per-entry refusal beats
      an exception that sinks the rest of the archive. That is containment of
      the symptom, not a fix.

      The fix is at the `sp()` seam, and it is NOT "change `sp()`": that
      function is used across the app and its Windows-path conversion exists
      for genuine remote-Windows-box paths. The question is whether
      `extractArchive` should be calling `sp()` on a path it is about to write
      to at all. Answer that before changing anything, and drive the
      alternative rather than reasoning about it — the last two attempts in
      this area were both measured worse than what they replaced.

- [x] T42: gate fixtures inherit GIT_DIR from a worktree push and corrupt the real repo — state: **merged #264** (`0a7b197e`, 2026-08-18) — closed by a process-level scrub at import time, not by the AST guard; eleven review rounds. **Two numeric claims here were measured and refuted in review (2026-08-19) and are corrected rather than deleted, because the pattern is the point.** "A four-line scrub" was a ten-line construct (`tests/conftest.py`: a `for` over six variable names, then the `pop`), and #264 added 41 lines to that file. "Last four commits removed code" is false: the last four are +43/-15, +34/-44, +11/-2 and +16/-5, net **+104/-66**, and only one of them is net-negative. This is the SAME error review caught on T36's tick, on the same branch, written by the same hand — and the T36 correction was committed while this line sat one screen away, untouched. Correcting the instance in front of me and not enumerating what else falls under it is the recurring failure of this whole run; see also T18's needs-list, wrong four times. Residual verification gap tracked as T46

      **Not a theory. It has now corrupted this repository TWICE in one day,**
      both times flipping `core.bare` to `true` so the main checkout stopped
      being a work tree (`fatal: this operation must be run in a work tree`),
      and the second time it also blocked T36's push.

      Git exports `GIT_DIR` into hook subprocesses **only when the push comes
      from a linked worktree** — measured: main checkout `GIT_DIR=[unset]`,
      worktree `GIT_DIR=[.../.git/worktrees/<name>]`. `pre-push` runs
      `make verify`, which runs this suite, so every git-invoking subprocess in
      the gate-fixture tests inherited it. With `GIT_DIR` set, `git init` in a
      fresh `tmp_path` does NOT create a repo there — it re-initialises the one
      `GIT_DIR` already names, silently (`warning: re-init`). Every later
      fixture `commit`/`checkout` then lands in the developer's real repo.

      What it actually did, observed rather than predicted: a real checkout
      left on a fixture branch, two fixture commits on a real feature branch,
      and `core.bare = true`.

      **Why it hid for so long:** the gate passes when run directly, because
      nothing sets `GIT_DIR`. It fails ONLY through the hook, ONLY from a
      worktree. So the standalone verdict and the push verdict disagree, and
      the standalone one is the one people look at.

      Fix: `sanitized_git_env()` in `tests/unit/conftest.py` strips `GIT_DIR`,
      `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`,
      `GIT_COMMON_DIR` and `GIT_ALTERNATE_OBJECT_DIRECTORIES` before every
      git-invoking subprocess call in both gate-fixture files — including the
      `needs_e2e.sh`/`push_base_ref.sh` invocations, since those shell out to
      git themselves. A plain function, deliberately NOT an autouse fixture, so
      it carries none of the blast radius across this directory's other ~150
      test files.

      Defence in depth: the `repo` fixture now asserts, immediately after
      `git init`, that `git rev-parse --absolute-git-dir` resolves inside the
      throwaway `tmp_path`. That converts a future unsanitised call site from
      silent corruption into a named assertion failure.

      Verified under the real condition rather than by reasoning: with
      `GIT_DIR` poisoned to the real repo, 75 gate-fixture tests pass,
      `core.bare` stays `false` and HEAD is unchanged. Mutation-proven — with
      the stripping removed, the defence-in-depth assertion fires and names the
      leak:

          assert PosixPath('.../victim/.git') == PosixPath('.../tmp_path/.git')

      Note the first mutation attempt produced a FALSE RED (a collection error,
      not the corruption assertion). Caught because the failure text did not
      name the behaviour being guarded, which is the whole reason for reading
      failure messages rather than counting reds.
      **Reframed 2026-08-18, after the guard was wrong four times.** The first
      fix sanitised each call site and added an AST guard to enforce it. That
      guard missed aliased imports (`subprocess as sp` — 17 of 20 sites in the
      file the incident happened in), missed subdirectories, accepted any
      `env=` whether sanitised or not, and could not see argv built by an
      `*args`-forwarding lambda — a shape with a LIVE unsanitised instance in
      `test_next_beta_version.py` that the guard passed clean.

      Four defects in one guard is the rule-11 signal, and the frame was
      wrong: policing call SHAPES is a losing game, because every wrapper,
      alias and lambda is a new spelling.

      So the hazard is removed instead of the callers policed.
      `tests/conftest.py` strips the six variables from `os.environ` once, for
      the whole process, before collection. Every subprocess is then clean by
      construction, whatever shape the call takes and whether or not its
      author ever heard of the helper. Proven in isolation: with the scrub
      removed, running `test_next_beta_version.py` (no sanitisation anywhere)
      under a poisoned GIT_DIR moves the victim repo's HEAD.

      Three layers, each failing on its own removal:

          process scrub          -> victim HEAD moves
          per-call sanitisation  -> 1 failed
          containment assertion  -> 1 failed neutered, 55 affected inverted

      The guard remains as defence in depth with its blind spot STATED rather
      than implied, and the condition for revisiting recorded: prove any change
      by planting an offender, never by reading — every defect in it was found
      that way and none by inspection.


- [ ] T43: an archive basename collision discards a file, and archive ORDER decides which — state: queued (no deps)

      Raised on #265 and driven rather than reasoned:

          ['movie.mkv', 'Sample\\movie.mkv'] -> movie.mkv = b'FEATURE-20GB'
          ['Sample\\movie.mkv', 'movie.mkv'] -> movie.mkv = b'SAMPLE-50MB'

      `extractArchive` flattens every entry to its basename, so a top-level
      `movie.mkv` and a `Sample\movie.mkv` map to ONE destination. The first
      listed wins, the second is skipped by the existing `os.path.isfile`
      check, and the release is still tagged extracted. In the bad order the
      operator gets a 50MB sample named like the feature and is told nothing.

      **Long-standing for `Sample/`** (RAR3, which rarfile normalises).
      **T36 widened it to `Sample\`** (RAR5, which rarfile does NOT normalise),
      because those archives previously aborted with FileNotFoundError instead
      of extracting at all. So T36 traded a loud failure for a quiet wrong
      answer in this one shape — worth being explicit about, since that is the
      direction this project treats as worse.

      #265 makes it VISIBLE (a warning naming the discarded entry) but does not
      change behaviour, because picking a winner does not belong in a security
      fix.

      The fix is to pick deliberately rather than by archive order.
      `RarInfo.file_size` is available, so "largest wins" would make the
      feature beat the sample every time. Check that against the case it could
      get wrong — an archive where the LARGER file is genuinely the unwanted
      one — before adopting it, and drive the decision rather than assuming
      size is a good proxy.

      Note `cleanup` (which deletes the source archive) is NOT reachable from
      the live caller: it defaults False and `renamer/main.py:1022` does not
      pass it. So the archive survives and the loss is recoverable by
      re-extracting. That is what keeps this off the irreplaceable tier.

- [ ] T44: a single archive entry can decompress to an unbounded size — state: queued (no deps) — **security, pre-existing**

      Raised on #265 as explicitly non-blocking and correctly so: the read loop
      in `_extractOneAtomic` is untouched by that PR. Recorded because the file
      has just had enough scrutiny to make the omission conspicuous.

      `rarfile.infolist()` parses HEADERS only, so a header claiming a large
      uncompressed size costs the attacker nothing, and the streaming loop
      writes whatever comes out with no cap:

          while True:
              chunk = source.read(1024 * 1024)
              if not chunk: break
              target.write(chunk)

      A hostile release therefore fills the disk. On this project that is worse
      than it sounds: the same volume holds the SQLite database and settings,
      and a full disk is exactly how this session lost a gate run to
      `sqlite3.OperationalError: disk I/O error`. Data at the top of the
      loss ranking sits behind a limit that does not exist.

      The fix is a per-entry byte budget in the read loop, refusing the entry
      when it exceeds what `info.file_size` claimed (plus a margin), and
      treating the refusal exactly like the other entry-derived failures —
      skip one entry, keep the archive, count it, cap the log.

      Note `info.file_size` is attacker-supplied, so it bounds nothing on its
      own; it is useful only as a CROSS-CHECK against bytes actually written.
      A budget derived from free space would be the belt to that braces.

      Do NOT reuse `_ENTRY_DERIVED_ERRNOS` for this. Nothing raises an OSError
      here — the write succeeds, repeatedly. It needs its own refusal path.

      **Second amplification site, same shape, raised on #265 round 15 and
      also non-blocking.** The containment check runs
      `isSubFolder(extr_file_path, extr_real_path)` per entry, and
      `isSubFolder` calls `os.path.realpath()` on both arguments — including
      on `extr_real_path`, which `extractArchive` has ALREADY resolved, so
      that half is pure redundancy. `realpath` `lstat`s every path component,
      so a header-only archive with a huge entry count buys the attacker
      per-entry syscalls for free.

      Smaller than the read loop and deliberately ranked below it: this is CPU
      and syscalls, not disk, and the per-entry log caps already bound the
      visible damage. It is recorded rather than fixed because the reason it is
      worth writing down is the PATTERN, not the cost — the same "headers are
      cheap, the per-entry loop is not" asymmetry, found on a third surface.
      `ENAMETOOLONG -> EISDIR -> EILSEQ -> EINVAL` were each rediscovered
      independently across four review rounds because the first was fixed as an
      instance instead of a category. Whoever takes T44 should look for the
      amplification everywhere the entry list is walked, not only in the two
      places named here.

      The redundant resolve is separately worth killing — **but not by editing
      `isSubFolder`.** Review caught a genuinely dangerous phrasing here: an
      earlier draft said "hoisting it costs nothing". It does not. `isSubFolder`
      has other production call sites that pass an UNRESOLVED base, including
      `couchpotato/core/_base/_core.py` (`data_dir` vs `app_dir`) and
      `renamer/scanner.py` (`sp(self.conf('from'))` — `sp` normalises separators,
      it does not resolve symlinks). Removing `realpath(base_folder)` from the
      shared helper would silently weaken symlink containment at both.

      The safe shape is a pre-resolved variant, or an opt-out parameter used only
      at the extractor call site where the caller has already resolved. Spelled
      out because this branch's own history is a fix introducing a worse defect
      than the one it replaced (T41), and "costs nothing" is how that happens.

- [ ] T45: nothing scans the STANDING dependency set, in either ecosystem — state: queued (no deps) — **security**

      Found while triaging the owner's dependency ask (tick 41), and **rewritten
      after review demolished its first premise.** The original text claimed
      "the JS half of §3a is covered — `npm audit` runs and the
      `dependency-review` CI job is green — but there is no Python equivalent".
      Three separate errors, all measured:

      **(a) `npm audit` runs nowhere.** `grep -rn "npm audit|audit-level"
      .github/ Makefile scripts/ .githooks/` is empty. It was run by hand in
      tick 41, exactly as `pip-audit` would have been. Neither ecosystem is
      automated.

      **(b) `dependency-review` is not "the JS half".** It consumes GitHub's
      dependency-graph compare endpoint, which is ecosystem-agnostic — the graph
      carries the pypi packages too, and a PR introducing a vulnerable pip
      package is already blocked by `fail-on-severity: high`.

      **(c) Trivy already scans the production image's Python packages —
      but only the FIXABLE ones.** `ci.yml` runs `trivy image` with `scanners:
      vuln`, `severity: CRITICAL,HIGH`, `exit-code: 1`, and **`ignore-unfixed:
      true`**. The runtime Python set is scanned on every PR and does find real
      CVEs. It structurally cannot report a Python advisory with no patched
      release — which is precisely the extract-zip-shaped class this task exists
      to worry about. Right for fixable CVEs, silent for the others, and the
      distinction matters because "Trivy covers it" was about to become the
      reason not to build the check.

      So the gap is NARROWER and differently shaped than first written, and
      naming it wrongly would have sent the implementer to build a duplicate of
      `dependency-review` while leaving the actual hole open. The actual hole:

      - **Nothing surfaces the standing set LOCALLY, which is the actual gap.**
        An earlier draft said "nothing scans the standing set", and review
        refuted it from this entry's own evidence: the `gh dependabot alerts` row
        two paragraphs up returned a result, and Dependabot alerts are produced
        by scanning the CURRENT dependency graph, not a PR diff. Something is
        already scanning the standing set; it just reports to GitHub's UI.

        What is missing is narrower and more useful: **no local command tells you
        what that scan found**, so `make verify` can be green while an open alert
        sits unread — which is exactly how this round's eight PRs went untriaged.
        `dependency-review` genuinely is diff-only (`fail-on-severity: high` on
        newly-INTRODUCED vulnerabilities, which is why the six pre-existing
        extract-zip HIGHs are green there), so it is not the answer either.

        Scoped this way, T45 may not need `pip-audit` at all: surfacing the
        alerts that already exist, and requiring a recorded decision for each,
        beats adding a dependency and a second scanner that duplicates work
        GitHub is already doing. Decide that before installing anything.
      - **Dev dependencies are in no IMAGE, but they are not unscanned.** An
        earlier draft of this bullet said "nothing scans dev dependencies at
        all", which contradicts point (b) three paragraphs above and is wrong:
        `requirements-dev.txt` IS a dependency-graph manifest, dev-only pypi
        packages DO appear in the SBOM, and `dependency-review` therefore
        already blocks a newly-introduced vulnerable dev pip package. Trivy is
        the one that cannot see them, because it scans the runtime image and
        `requirements-dev.txt` reaches no image. So the residual gap for dev
        deps is the same as for runtime deps — the STANDING set, not the diff —
        and stating it as total absence would send the implementer to rebuild
        coverage that exists.
      - **Nothing runs locally**, so `make verify` cannot tell you what
        `npm audit` told a human in tick 41.

      The §9 answer is a `deps` step in `verify` running BOTH `pip-audit` and
      `npm audit` over the standing set. `.venv/bin/pip-audit` does not exist and
      neither `pip-audit` nor `safety` appears in `requirements-dev.txt`, so that
      is a real addition, not a rewiring.

      Two constraints for whoever takes it. It must distinguish **fixable** from
      **unfixable** — tick 41 holds `extract-zip`, which has no patched release
      at all, and a gate that fails on findings nobody can act on gets bypassed
      within a week and then teaches nothing. And per §3a the outcome is a
      recorded decision, not a green number, so it must not become a merge
      blocker on a transitive advisory with no remedy.

      **Keep the thesis that survived its own premise being wrong:** an unrun
      scanner and a clean scanner produce the same sentence in a report. That is
      what happened here twice over — once to `pip-audit`, which was correctly
      flagged, and once to `npm audit`, which was described as running when it
      does not.

- [x] T46: T42's fix has never been exercised under the condition it was written for — state: **done** (2026-08-19) — **the simulation is faithful, and the scrub is load-bearing.** Measured, not reasoned; evidence in tick 43

      T42 is merged and its box is ticked, correctly: the scrub at
      `tests/conftest.py` pops the six git location variables at import time,
      before collection, and that is the right shape. But every test of it
      SIMULATES the poison by setting `GIT_DIR` in the environment by hand.

      The real condition is different in one way that matters: git exports
      `GIT_DIR` into the hook process itself, and **only from a linked
      worktree**. That path has not run since the fix landed, because every
      worktree was removed before it could be. Ticking the box does not close
      this, and the caveat currently lives 460 lines away in the tick 41 log
      where nobody executing the plan will meet it — which is why it is a task.

      There is precedent in this very file: T9 "was UNVERIFIABLE when the box
      was first ticked, which review rightly flagged". Same shape.

      **Do it in a throwaway clone, never in this checkout.** The failure mode
      under test IS corruption of the real repository, and per the loss ranking
      that is the irreplaceable class. Concretely: clone to scratch, create a
      linked worktree, install the pre-push hook, push to a LOCAL bare remote,
      and assert the clone's own `.git` is byte-identical afterwards. Then break
      the scrub, watch it fail, restore — a guard nobody has watched fail is not
      done.

- [ ] T47: `lhci autorun` publishes screenshots of the user's library to a public Google endpoint — state: queued (no deps) — **privacy, pre-existing**

      Surfaced by the security lens while reviewing tick 41's decision to KEEP
      `@lhci/cli` in the tree. This is the risk that decision actually carries,
      and it is larger than the advisory the tick spent a page holding.

      `lighthouserc.js` sets `upload.target: 'temporary-public-storage'`, and
      `@lhci/cli` POSTs the rendered HTML report to
      `https://us-central1-lighthouse-infrastructure.cloudfunctions.net/saveHtmlReport`,
      then prints the returned public URL. `autorun` runs the upload step **even
      when the assertions fail**.

      A Lighthouse HTML report embeds full-page screenshots. The configured
      targets are `/`, `/available/`, `/add/` and `/settings/`.

      **This paragraph has now been wrong in BOTH directions, which is worth
      more than either correction.** It first understated the payload as "the
      library, plus directory paths". A security review pointed out the settings
      page renders credentials unmasked, and I rewrote it to say the published
      report carries API keys and tracker passkeys. **Review then measured the
      screenshot itself and refuted that too**: Lighthouse only NAVIGATES to
      `/settings/`, it does not click. `settingsPanel()` initialises
      `activeTab: 'general'` and `showAdvanced: false`, the template renders only
      the active tab's groups, and `core.api_key` sits in a group marked
      `'advanced': True` — so the default screenshot cannot contain it, and the
      tracker and notification credentials live on other tabs entirely.

      **So the credential claim about the UPLOAD is withdrawn.** Demonstrating it
      would need an interaction script that opens those tabs, or evidence from a
      produced report, and I had neither — I verified that the settings *API*
      returns credentials in the clear and then asserted something about the
      *screenshot* that does not follow from it. Correcting an understatement by
      overstating is not a correction, and the second error was the more
      confident one.

      T47 therefore stands on what was actually measured: a public upload of
      rendered pages of the user's library, running even when assertions fail.
      That is a real privacy defect and it does not need inflating.

      **The unmasked rendering is real, independently verified, and is now T48.**
      It has nothing to do with Lighthouse. Masking is
      gated on `type == 'password'` (`couchpotato/core/settings.py`), 22 options
      declare that type, and the credential fields below do not — so they come
      back from `getValues()` verbatim and render through the default
      `<input type="text">` branch. Driven, not read:

          core.api_key            -> 'SUPERSECRET_LIVE_KEY'
          passthepopcorn.passkey  -> 'TRACKER_PASSKEY_9999'
          getType(core, api_key)  -> 'unicode'

      That is a defect on the PAGE, not in the upload: it fires for anyone who
      opens the relevant tab, in a screen share, or in a support screenshot.

      **And the operator is most likely to trigger it at the moment they think
      nothing happened:** `autorun` runs the upload BEFORE it exits non-zero, so
      a failing accessibility assertion reads as "the run aborted" while four
      reports have already been POSTed and four public URLs printed.

      `AGENTS.md` names the library as the personal data on this project, so the
      upload is a genuine finding on its own terms. **`target: 'filesystem'`
      closes it, and does not touch the unmasked rendering** — that half is T48
      and needs its own fix.

      Mitigating, and the reason this is queued rather than urgent: nothing runs
      `lhci` automatically (no workflow, no `make` target — see tick 41), so it
      fires only when a person types `npm run test:lighthouse` or `test:all`.
      That is a one-command distance, not a barrier.

      The fix is `target: 'filesystem'`, which keeps the reports local and loses
      nothing this project uses. **Also fix the comment directly above it**,
      which reads "Don't upload to Lighthouse CI server by default" — true and
      thoroughly misleading, since it does not upload to OUR server while
      uploading to a public one. A comment that reassures the reader about the
      exact risk it introduces is worse than no comment.

      Ranking note, recorded because tick 41 got this backwards: this is
      disclosure of irreplaceable personal data triggered by one documented
      command, versus a dev-only CWE-22 reachable through a browser-download
      path `lhci autorun` never takes. The tick argued at length about the
      second and did not notice the first.

- [x] T48: the settings page renders API keys and tracker passkeys UNMASKED — state: **merged #275** (`b1ef797a`, 2026-08-19) — **security, pre-existing**. **Ticked late, 2026-08-20:** the merge commit never ticked its own entry, so the box stayed open for a day while the work was on master — found by review of T52, not by me. Exactly the staleness T18's parenthesis predicts about itself, and the reason the needs-list is now a test rather than a promise

      Found by the security lens while reviewing T47, and it is the larger half
      of that finding. Independent of Lighthouse: anyone who opens `/settings/`
      sees these in the clear, and so does anyone looking over their shoulder, in
      a screen share, or in a support screenshot.

      **Mechanism.** `couchpotato/core/settings.py` masks a value only when
      `getType(section, option) == 'password'`. `getType` falls back to
      `'unicode'`, and `registerDefaults` calls `setType` only `if
      option.get('type')`. Twenty-two options across the tree DO declare
      `'type': 'password'`, so the convention exists and is honoured — these
      simply never got it. The UI then takes the default branch in
      `field_types.html` (`!opt.type || opt.type === 'string'`) and emits
      `<input type="text">`.

      Driven against the real object rather than reasoned about, registering
      exactly as the live plugins do:

          core.api_key            -> 'SUPERSECRET_LIVE_KEY'
          passthepopcorn.passkey  -> 'TRACKER_PASSKEY_9999'
          getType(core, api_key)  -> 'unicode'

      **Affected, non-advanced (visible without expanding anything):**
      `core.api_key` — CouchPotato's own API credential — plus `passkey` on
      `awesomehd`, `passthepopcorn` and `hdbits`; `telegrambot.bot_token`;
      `slack.token`; `pushbullet.api_key`; `pushover.user_key`; `emby.apikey`;
      `sabnzbd.api_key`. Advanced adds `putio.oauth_token`, `plex.auth_token`,
      `trakt.automation_oauth_token`, `pushover.api_token`, `join.apikey`.

      **The fix is to declare `'type': 'password'` on each, NOT to change the
      masking rule.** This is the trap: the obvious shortcut — "mask anything
      not in `self.types`" — is exactly what T31 deliberately rejected, and
      `tests/unit/test_settings_orphan_masking.py::
      test_registered_plain_string_option_is_not_masked` pins that rejection.
      Untyped-and-registered is the normal case for ordinary string settings
      like `host`, and masking by absence-of-type would star those out in the UI.
      So the change is per-option and additive.

      **`core.api_key` is the exception, and review caught it before this task
      could do harm.** It is declared `'ui-meta': 'ro'` and described as "Used by
      third-party apps to communicate with CouchPotato" — the operator's job is
      to READ it and paste it elsewhere. Password-typing it makes `getValues()`
      return only stars, and the password template has no reveal or copy control,
      so the operator could neither retrieve the key nor replace it. That turns a
      disclosure defect into a lockout, which is a straight downgrade.

      So `core.api_key` needs a reveal-or-regenerate path, not a mask, and it is
      explicitly OUT of the blanket remedy. Listing it above alongside the others
      was the error: "these all leak" is true, "these all take the same fix" is
      not, and the task nearly shipped the second as if it followed from the
      first.

      **Two more things the implementer must not miss.** Masking is display-only
      — the value still has to reach the plugin that uses it, so the round trip
      (save, reload, still works) is the test that matters, not just the render.
      And each field wants checking against its own template usage rather than
      being swept by name, because `core.api_key` will not be the only one whose
      whole purpose is to be read.

      Ranking: this sits above T47's upload path. The upload needs someone to
      type a command; this renders in the clear for anyone who opens the tab.
      Stated carefully this time — the credentials are on non-default tabs or
      behind the advanced toggle, so "every visit" would be the same
      overstatement T47 has just been corrected for. One click, not zero.

- [ ] T49: an E2E test times out only inside a full run — state: queued (no deps) — **flake**

      `tests/e2e/add-via-url.spec.ts:110` ("keeps the title-search box available
      alongside the URL flow") failed the local gate on 2026-08-19 with
      `page.goto: Test timeout of 30000ms exceeded`, navigating to
      `/add/?url=<encoded>`.

      Re-run in isolation immediately afterwards, the whole file passes and that
      test takes **1.5s against a 30s budget** — a 20x margin. So this is not a
      broken test and not a slow one; it is a test that fails only under
      full-suite load.

      **Recorded rather than re-run, because §11 ranks a flake below an absent
      test:** it teaches everyone to re-run until green, and a real regression
      gets re-run away with it. This is the second time this repo has produced a
      "fails only in a FULL run" E2E defect — T10 was the first, and its root
      cause was NOT the obvious one.

      Evidence to start from, gathered while diagnosing rather than guessing:

      - The test one line above it (`:90`) navigates to the **same** URL and
        passed in the same full run. So the URL-resolution path itself works;
        whatever bites is timing, not the fetch.
      - Playwright's own output in that run flagged
        `Slow test file: interactions.e2e.spec.ts (5.8m)`. Contention with that
        file is the first hypothesis to test, not a conclusion.
      - `playwright.config.ts` pins `retries: 0` locally, which is correct and
        should stay: retries would convert this into an invisible intermittent
        rather than a caught one.

      **The local flake and the CI stalls are plausibly ONE defect.** Separately
      from the local symptom, `ui-e2e-tests` stalled in CI **four times** on
      2026-08-19, each sitting `in_progress` for 35-96 minutes against a ~5
      minute norm, reporting no failures, and clearing on cancel-and-rerun. The
      measurement that links them, all from the same branch and same content:

          run 32217702516   ui-e2e-tests   completed/success
          run 32221210039   ui-e2e-tests   completed/success
          run 32223408029   ui-e2e-tests   STALLED -> cancelled
          run 32226381478   ui-e2e-tests   STALLED -> cancelled

      Two clean, two hung, nothing else different. So it is intermittent rather
      than a property of the branch — and an intermittent hang that clears on
      retry, appearing BOTH locally and in CI, is one defect at two scales far
      more parsimoniously than two.

      **The cost is already being paid.** Four cancel-and-retry cycles in one
      afternoon, each individually the right call. That is exactly how §11 says
      a flake does its damage: it trains everyone to re-run until green, and a
      real regression eventually gets re-run away with the noise.

      **The tempting wrong fix is raising the timeout.** A 20x margin says the
      budget is not the problem, and a longer one would hide the next
      regression in this flow behind a slower failure. Find why a 1.5s
      navigation takes >30s under load first — the `/add/` route resolves a
      user-supplied URL server-side, so a blocked or serialised handler is a
      more likely explanation than a slow browser, and if so it is a
      responsiveness defect rather than a test defect.

- [ ] T50: a hash-verified mutation restore can still run the MUTANT — state: queued (no deps) — **process, affects every guard in this repo**

      Found 2026-08-19 by an adversarial reviewer, in its own work, while
      verifying someone else's. It reported the anomaly against itself and
      traced the mechanism instead of re-running until green — which is the
      behaviour CLAUDE.md rule 10 exists to produce, and it caught a hole in
      rule 10.

      **Rule 10 is necessary and NOT sufficient.** It says: break the thing the
      guard protects, watch it fail, restore, and confirm the mutation landed by
      `git diff` or a hash. The reviewer did exactly that — mutated
      `'ui-meta' : 'ro',` to `'ui-meta' : 'rw',`, ran the test, restored by file
      copy, verified all 733 files byte-identical to HEAD — and the test then
      failed against a provably clean tree.

      **Cause: CPython's `.pyc` header records source mtime and source SIZE.**
      `ro` and `rw` are the same byte length, and the mutate/test/restore cycle
      finished inside one second, so both fields matched the restored file and
      Python reused the MUTANT bytecode:

          pyc records: source mtime=1787125061  source size=30013
          actual     : source mtime=1787125061  source size=30013

      Clearing `__pycache__` gave the correct result.

      **Here it produced a false RED, which is loud and self-correcting. The
      identical mechanism produces a false GREEN** when the stale cache holds
      the ORIGINAL bytecode while the source carries the mutation: you break the
      guard, watch it "still pass", and conclude the guard is vacuous when it is
      fine — or conclude a fix works when the test never ran against it.

      That is not a corner case. Same-length mutations are precisely the ones
      this repo's discipline encourages: `ro`->`rw`, `<`->`>`, `and`->`or`,
      `+`->`-`, swapping one errno member for another (which is exactly what T36
      did, sixteen times).

      **The obvious remedy is WRONG, and this task originally recorded it.**
      `PYTHONDONTWRITEBYTECODE=1` blocks the WRITE, not the READ, so it does
      nothing about an existing stale `.pyc`. Measured with mtime and size
      forced identical:

          no env var                 -> SEEN: ro   (stale; disk says rw)
          PYTHONDONTWRITEBYTECODE=1  -> SEEN: ro   (STILL STALE)
          PYTHONPYCACHEPREFIX=fresh  -> SEEN: rw   (correct)
          __pycache__ removed        -> SEEN: rw   (correct)

      It is worse than useless in one case: by preventing the mutant's bytecode
      being written it PRESERVES the pre-mutation `.pyc`, making the dangerous
      false GREEN more likely, not less.

      **Use `PYTHONPYCACHEPREFIX=$(mktemp -d)`.** Guaranteed cold, deletes
      nothing in the working tree (which matters given this project's data-risk
      stance), and keeps caching within the run. Cost measured at ~0.6s over
      1437 modules, which is cheap enough that arguing to keep the warm cache is
      not worth the words.

      **The dangerous half is easier to trigger than the incident that found
      it.** The false RED needs the RESTORE to land in the same second. The
      false GREEN needs the MUTATION to land in the same second as the preceding
      compile — which is the immediately preceding step of every mutation run.
      So an agent following rule 10 on a fast machine is MORE likely to conclude
      "this guard is vacuous, delete it" than to hit the loud failure.

      **`pytest` replicates the bug in its own assertion rewriter**
      (`_pytest/assertion/rewrite.py` writes and validates on mtime+size), so
      mutating a TEST file carries the identical trap. And the E2E servers are
      Python processes, so this reaches the Playwright layer too.

      **No detector is possible.** In timestamp mode the `.pyc` carries no
      content hash, so nothing can compare it against the source it claims to
      represent. Anything proposed as a "stale pyc lint" cannot exist. The
      answer is to eliminate the condition, not to detect it.

      **This wants promoting into `CLAUDE.md` rule 10 itself**, not just
      recorded here: every mutation claim made in this plan predates the
      discovery, and the rule as written would let the same false green through
      again tomorrow. Re-running past mutation proofs is NOT proposed — most
      used differing-length edits — but the rule should change before the next
      one is trusted.

- [x] T51: the first-run wizard discards every save response, so a refused save reads as success — state: **fixed** (2026-08-20), one gap recorded — **security amplifier**

      `saveSetting` now reads the response body and throws on `success: false`, on a
      non-2xx status, and on a 200 that is not JSON — an unreadable response is not a
      confirmed save. The fix is small because the error path already EXISTED:
      `nextStep()` wraps the save in try/catch and only advances when nothing throws.
      It was unreachable, because the one thing that could throw did not.

      **`res.ok` alone would not have been enough**, which this task recorded in
      advance and which held: `api.py` answers HTTP 200 for a refusal, so a status-only
      check would have looked correct and changed nothing.

      **The RED took three attempts to become honest**, and the first two would have
      shipped a green lie:

      - selectors matched nothing (the inputs are Alpine `x-model` with no `name`/`id`),
        so all three tests failed for reasons unrelated to their claims. Caught only
        because the CONTROL test failed too — it should pass before any fix, and that
        is the entire reason a control was written;
      - "the username field is still visible" passed trivially, being true during the
        transition either way.

      **The gap this entry recorded is CLOSED, and the record is corrected
      rather than quietly rewritten.** It said the "a refused save does not
      advance the step" assertion had been deleted and was not covered, because
      the disagreement between the assertion and a probe was not understood.

      Review explained it: it was a retrying web-first assertion on a NON-event,
      so it succeeded at its FIRST poll, at t~0, before the async advance had
      happened. Both earlier versions passed against unfixed code for that
      reason, and the second one had gone RED earlier for an unrelated cause
      (`textContent` including hidden steps' markup), which made it look like
      proof.

      The discriminating form needs a bounded settle -- mandatory when asserting
      that something must NOT happen -- plus a step-scoped locator
      (`[x-text="steps[currentStep]"]`, unique and unaffected by hidden markup)
      instead of body text. It now fails against the exact pre-fix code, and
      ships.

      Deleting it was the right call on the evidence available at the time: a
      guard whose failures cannot be explained is worse than none, because it
      will be trusted. The lesson is not "should not have deleted it" -- it is
      that an unexplained disagreement between two measurements is a finding
      worth one more look, not a reason to stop.

      Found while fixing T48, and it is the reason a bad guard there became a
      security hole rather than an annoyance.

      `wizard.html` saves settings with `return fetch(...)` and never reads the
      response; `await Promise.all(saves)` resolves regardless. The wizard's own
      summary then reports authentication as **Enabled** from LOCAL form state,
      not from what the server stored.

      So ANY server-side refusal during first-run setup is invisible. Measured
      concretely on T48's first attempt: an operator choosing a generated
      password containing `*` had the save refused, `Core.md5Password` never
      fired, `auth_required` was never set — and the wizard said authentication
      was on while the instance stayed public.

      T48's guard was narrowed so that specific case cannot happen, but **the
      amplifier is still there** and will convert the next refusal — a
      validation error, a disk-full write failure, a chroot rejection — into the
      same silent lie. This is worth fixing independently of what refuses.

      **Scoped 2026-08-19, so it does not start cold.** The exact shape:

          saveSetting()  ->  `return fetch(CP.apiBase + '/settings.save/', ...)`
                             no .ok check, no body parse
          caller         ->  `await Promise.all(saves)` , resolves regardless

      `api.py` returns HTTP 200 even for `{'success': False}`, so `.ok` alone is
      NOT sufficient — the body has to be read. That is the trap: a fix that
      only checks `res.ok` would look correct, pass a naive test, and change
      nothing.

      **Testing level, decided by measurement rather than preference.** The
      wizard's logic is inline in `wizard.html`; there is no shared JS module
      (`couchpotato/ui/static/js/` does not exist) and the only two
      `tests/unit/*.test.ts` files are about test configuration, not app code.
      So it is not unit-testable without restructuring, and E2E is the honest
      level: `/wizard/` is directly routable (`couchpotato/ui/__init__.py`), so
      a Playwright test can `page.route` the `settings.save` call to return
      `{"success": false}` and assert the user is actually told.

      Write that test FIRST and watch it fail, because the failure mode here is
      precisely a save that reports success — a test that does not force a
      refusal cannot distinguish the fixed code from the broken code.

      Two things for whoever takes it. The settings page already does better
      (`partials/settings/scripts.html` checks `success: false`), so the wizard
      is the outlier rather than the pattern — copy that. And a refusal that
      returns `{'success': False}` with no `error` renders as "HTTP 200" in the
      toast, which is worse than useless to a self-hosted user; T48 added an
      `error` string to its own refusal, and the other refusal paths in
      `saveView` still need one.

- [x] T52: the first-run wizard renders credentials as `type="text"` — state: **fixed** (2026-08-20) — **security, pre-existing**

      Seven fields typed, but **only five ever rendered**. `wizard.html:432` opens
      `<template x-if="false && formData.downloader">` spanning lines 432-653, so the
      `sabnzbd.api_key` at :447 and the `putio.oauth_token` at :633 are dead copies
      that never enter the DOM. Review measured that in a real browser; my own
      description said "each appearing twice — once in markup, once in a JS template
      string", which implied two LIVE copies and was wrong.

      The live leak was `newznab entry.api_key` (:168), `sabnzbd.api_key` (:1401),
      `putio.oauth_token` (:1465), `passthepopcorn.passkey` and `hdbits.passkey`.
      Typing the dead copies too is correct by consistency and harmless — but a
      222-line dead duplicate that has to be kept in sync with the live template
      literals is T18 material.

      **The enumeration nearly went wrong in the way this plan keeps recording.** A
      regex over `<input>` tags found the first five and reported the file clean
      otherwise. It cannot see the tracker passkeys: those render through ONE generic
      input (`:type="field.type || 'text'"`) fed by the `privateTrackers` array, so
      the credential's name never appears in the markup at all. They were found by
      reading how that loop works, not by sweeping.

      So the guard checks BOTH shapes, and both are mutation-proven: reverting one
      direct input fails naming `wizard.html:633`, reverting one tracker field fails
      naming `hdbits.passkey`. A vacuity guard pins each extraction, because the
      tag-only version of this sweep passed while two credentials rendered as text.

      Same shape as T48 twice over: 16 of the 21 credential inputs already declared
      the type, and every tracker `password` did. The convention existed; a handful
      were missed. That is the argument for a sweep rather than a list.

      T48 fixed the settings page by declaring `'type': 'password'` on the
      plugin options. The wizard does NOT read plugin `config` — it carries its
      own hard-coded field list — so it is unaffected and still renders
      credentials in the clear.

      Inconsistent within the single template, which is what makes it a
      defect rather than a decision: `jackett_api_key` and the tracker
      `password` fields already declare `type: 'password'`, while beside them
      the tracker `passkey` fields, `sabnzbd.api_key`, `putio.oauth_token` and
      `newznab.api_key` are hardcoded `type="text"`.

      Lower severity than T48 because the wizard only ever shows what the user
      is currently typing, never a stored secret — but it is the same
      shoulder-surf and screenshot class, on the one page every new install
      walks through.

      Note the wizard duplicating the field list is the root cause of both this
      and T51. Whoever takes either should consider whether the wizard can read
      the real option declarations instead, which would make this class of
      drift impossible rather than fixed-once.

- [ ] T53: the Trakt notifier reads a section that does not exist, so it can never authorise — state: queued (no deps)

      Found by an adversarial reviewer while tracing T48's read paths, and
      unrelated to that work.

      `couchpotato/core/notifications/trakt.py` reads its settings with
      `Env.setting(attr, 'trakt_automation')`. But `loader.py` registers options
      under the top-level ENTRY name, which is `'trakt'`; `'trakt_automation'`
      is the GROUP name. Driven against the real objects:

          Env.setting(.., 'trakt')             -> 'REAL_TRAKT_TOKEN'
          Env.setting(.., 'trakt_automation')  -> ''

      So the notifier reads an empty string no matter how the user has
      configured it, and always logs "Trakt not authorized". The feature has
      never worked, and the failure mode is a log line that reads like a user
      configuration problem rather than a bug — which is presumably why it has
      survived.

      Same family as the renamer event chain (see the `renamer.before/after`
      note): correct-looking plugin code wired to something that is not there.
      When fixing, check the other `Env.setting(..., '<section>')` call sites
      for the same entry-vs-group confusion rather than fixing this instance
      alone — that mistake has cost this plan repeatedly.

- [ ] T54: `saveView` is a read-modify-write with no lock — state: queued (no deps)

      Raised on #275 as explicitly non-blocking and correctly so: no locking
      existed there before, and the mask guard T48 added merely makes the window
      visible rather than creating it.

      `Settings.saveView` reads the currently-stored value (to build the
      comparison mask), then later writes via `set()` + `save()` in the same
      call. Nothing serialises two requests touching the same `section.option`,
      so a double-submit, two open tabs, or a password-manager autofill racing a
      manual edit gives: both read the same "current" value, both evaluate the
      guard against it, and the second write wins — with the guard's decision
      made against a value that may already be stale.

      Worth taking seriously on this project rather than filing as theoretical,
      because the same shape has bitten here before: `movie.add`'s duplicate
      race and the unlocked check-then-set in `renamer/main.py` are both in this
      plan's history. Settings writes are lower frequency, which is why this is
      queued rather than urgent.

      Note the fix interacts with T21 (a kill between the password save and the
      rotation loses the revocation) — both are about `saveView` not being
      atomic across its read, its write and the hooks it fires. Whoever takes
      either should look at whether one change closes both, rather than adding
      two different partial locks.

- [ ] T55: activating a wizard step destroys focus, and the toast is unfocusable — state: queued (no deps) — **accessibility**

      Found reviewing T51, and made load-bearing BY T51: the error path it
      reports on was previously unreachable.

      `wizard.html` binds `:disabled="saving"` on the Continue button, so
      activating it disables the element the user just pressed. Focus lands on
      `<body>` and is never restored — measured `FOCUS after save = BODY`. A
      keyboard or screen-reader user is dropped to the top of the document at
      the exact moment an error message appears, and the message itself carries
      no focusable target.

      T51 fixed the announcement half (the refusal now writes to base.html's
      persistent assertive region), so the failure is no longer silent. What
      remains is that the user is not left anywhere useful to act on it.

      The named remedy in this project's standard is `aria-disabled` plus a
      re-entry guard rather than `disabled`, which keeps the control focusable
      and keeps focus where the user put it. Check the other `:disabled` bindings
      in the same template while there — the pattern is repeated.

      Not fixed with T51 deliberately: it is a template restructure across
      several controls, and bundling it into a security fix would have made
      that fix harder to review for the thing it was actually for.

- [ ] T18: a final sweep for dead code, dead docs and dead instructions — state: queued (needs: **every other open task** — T6, T7, T8, T11, T15, T20, T21, T23, T25, T32, T34, T37, T38, T39, T40, T41, T43, T44, T45, T47, T49, T50, T53, T54, T55 — because each adds residue and several rewrite the code this would sweep. Deliberately phrased as "every other open task" FIRST and enumerated second: the list has now gone stale FOUR times by enumeration alone (count reconciled 2026-08-19; the running total in this clause had itself gone stale, which review caught). T19 was omitted by the very commit that wrote this line; T20, T21 and T22 were then added by later tasks and omitted again, caught in review of #249 — which is the same failure this parenthesis already described, reproduced while describing it. T13, T14, T17, T19 and T22 have since merged and are dropped from the list. T29 and T30 closed by removal (2026-08-12), not by a fix, and are dropped too. **Third incident, 2026-08-19, and both directions at once:** the commit that ticked T36 left it named here as open, and the same commit added T45 without listing it. Caught in review, not by the author — which is the third time this parenthesis has been proved right by the commit editing it. The enumeration is the defect; the phrase "every other open task" is the contract, and any reader should trust that phrase over the list that follows it.)
      **Add to its scope (2026-08-18):** citations that rot. This session
      converted three-line-number citations into a third-party package and
      several stale line references into symbol citations, for one reason:
      a wrong citation reads as precision and sends the next reader somewhere
      specific and wrong.

      One more class, raised by a peer session that hit it: a pinned COMMIT
      HASH does not survive a history rewrite.
      `tests/unit/test_check_test_traps.py` cites `git show f7f57b62` in a
      docstring. It is prose, not executable — grepped, and NO test or script
      in this repo shells out to a pinned SHA — so a rewrite would mislead a
      reader rather than fail a gate. Resolve it by commit SUBJECT with an
      assert-exactly-one-match, or drop the citation.

      The peer's second-order finding is the one worth carrying even though it
      does not bite us here: after a `filter-branch`, `refs/original/**` keeps
      the old object reachable, so a test pinning the OLD hash stays GREEN
      until `reflog expire && gc --prune=now`. A green suite run while the
      rewrite backups still exist proves nothing about the rewritten repo.
      Expire the backups first, then run the suite.


      **Runs LAST, and it is not a duplicate of T7 even though it sounds like
      one.** T7 is a scoped pass over the specific items this plan's reviews
      already named (M9, M10, L7, the copy set). T18 is the sweep for what
      nobody named — the residue this remediation itself created, which by
      definition is not on any earlier list.

      Sequenced after the others deliberately: doing it earlier deletes things
      the remaining tasks still need, and every task between now and then adds
      more residue.

      **Seed evidence, measured rather than assumed:**

      | Candidate | Size | The question |
      |---|---|---|
      | `couchpotato/core/**/static/*.js` | 4,487 lines | Legacy `/old/` UI. An earlier note said the userscript add-via-URL keeps part of it alive; that is obsolete — `add_via_url` is served by the NEW UI (`couchpotato/ui/__init__.py:384`) via `callApiHandler`. Re-establish what, if anything, still needs these |
      | `libs/CodernityDB/` | 7,147 lines | Kept for one-time migration per CLAUDE.md. Has every install migrated? If the answer is unknowable, it stays and the docs say why |
      | `Plugin.renderTemplate` | 1 method | Zero callers anywhere (`.py`, `.html`, `.js`). Also T17's third finding |
      | `remove_lower_quality_copies` | 1 setting | Deliberately inert, warns once. Delete once operators have had a release to notice |
      | `specs/` | 56 files | Which describe shipped behaviour, and which are abandoned drafts that read as current intent? |
      | `QA/` | 9 files | Point-in-time findings. `review-cycle-run-recovery` in memory is explicitly "delete after a clean review cycle" |

      **The docs half matters as much as the code half**, and this repo has a
      rule for it: assert only what the repo proves. This session alone found
      an AC describing a signal two commits after it changed, a spec claiming
      "four" while naming three, a comment claiming `with_doc=False` isolates
      corrupt documents when it does not, and a test docstring describing a bug
      that had been fixed. Every one of those was written by somebody
      confident, and every one would have sent the next reader somewhere the
      behaviour is not.

      So the pass covers CLAUDE.md, AGENTS.md, `docs/`, `specs/` and the
      long-form task write-ups in THIS file — several of which now describe
      decisions that were superseded by the work that followed them.

      **Method, because a delete-everything sweep is how load-bearing code
      dies.** For each candidate: prove it is unreachable, delete it, and run
      the full gate.

      Grep is a hint, not a proof: `couchpotato/__init__.py` re-exports are
      load-bearing for plugins, and a plugin that fails to import is SKIPPED
      rather than fatal (`loader.py:151`), so a broken reference can look like
      a working deletion until somebody uses the feature.

      An earlier draft of this paragraph said the loader hides ImportError at
      DEBUG. It does not, and has not since REG-001: `loadModule` logs at
      ERROR with a full traceback and carries a comment saying why. Writing
      the task about stale documentation using a stale fact is the joke
      telling itself, and it is recorded rather than quietly corrected because
      it is the best argument available for the task existing. If it
      cannot be proven unreachable, it stays and the reason is written down
      next to it. "Probably unused" is not a finding, it is a guess.

      Nothing here is urgent. It is the difference between a codebase that has
      been remediated and one that looks like it has.

T4 carries the deferred review finding M2 (the startup `auth_required`
migration is executed by no test; its only guard is a source-order string
search). T7 carries the accessibility and product sets recorded in
`QA/lens-review-2026-08-07-m1b-vs-master.md` and the three defects in
`scratchpad/findings-from-read.md`.

`needs:` is ordering, not exclusivity: T4, T5 and T8 all unblock on T3 and may
run in parallel.

### Review findings NOT fixed in PR 3, carried forward

From `wf_3eafdf36-b0b` (2026-08-07). Recorded so the backlog stays true rather
than being closed by omission -- the review's own H2 was that two tasks went
missing without a note.

| Finding | Carried to | Why not here |
|---|---|---|
| M1 cleanup still authorises a whole-library delete on one found movie | T8 | Further tightening of a delete path; same review as T3.3 |
| M2 orphan cleanup dead, "Cleaned up N" can never fire | T8 | Same defect as T3.3; documented at the line meanwhile |
| M3 `_delete_id_index` / `opened` still unresolved | T8 | Same compat surface as T3.3 |
| M5 client-side password/refusal changes have no automated coverage | T7 | Needs a password-protected E2E fixture, which is its own change |
| M6 error toast 3.92:1 in dark theme (below AA) | T7 | Accessibility floor; batched with the rest of the a11y set |
| M7 6s toast covers the bottom nav at phone width | T7 | Same |
| M9 refusal message names an internal key, defers to a log | T7 | Copy, batched with the product set |
| M10 "Require login" gives no forward disclosure it needs a password | T7 | Copy |
| M11 adding an index needs three coordinated edits, 16/19 never reach existing installs | T6 | Structural; belongs with the performance/index work |
| M12 index expression duplicated in three places | T6 | Same |
| M13 one skip decision expressed as two conditions | T8 | Same function as T3.3 |
| M14 the repo forks a 206-line orchestrator to change a 4-entry table | — | Harness tooling, not product; raise upstream |
| M15 SPEC BUG: the reviewed surface has no AC in any lens namespace | T7 | The plan-cycle must write ACs before the next PR; see below |
| L1 unauthenticated caller can evict the 5 MB log ring via the lockout ERROR | T4 | Auth path, belongs with the session-cookie work |
| L2, L6 toast dismiss/pause, `/settings/` overflow at 375px | T7 | Accessibility set |
| L4 adapter locking guard enumerates methods by hand | T6 | Structural |
| L5 E2E port guard proven only by a comment | T7 | Needs a harness test |
| L7 dead import keeps a core->web dependency edge alive | T7 | Dead-code pass |
| L8 `auth_required` parsed by two modules with no shared constant | T4 | Auth path |
| L9 `release_download` string-key branch has no in-tree caller | T6 | Structural |

**M15 is the process finding and it binds the next PR:** every PR from here runs
`/plan-cycle` FIRST so its lenses write numbered `AC-<LENS>-<n>` criteria into
this spec, because a review with no acceptance criteria can only report what it
happens to notice.

## Scanning discipline (added 2026-08-11, after it was skipped)

T17 was closed saying "re-scan after merge and let the rating follow the
code". **No scan was run.** Four PRs merged after it, and the dashboard
kept showing all three vulnerabilities as open at their pre-fix line
numbers — so anyone reading SonarQube would have concluded T17 never
happened. The owner asked whether scans were being run; they were not.

The first re-scan (master `04121da4`) confirmed the fixes:

    vulnerabilities   3 -> 0
    security rating   D -> A

and it moved because the code changed, not because anything was
dismissed. It also surfaced three findings nothing else had: a BLOCKER
`len()`-on-a-boolean crash (T24), 39 unlabelled inputs in the new UI
behind a green a11y gate (T25), and coverage published as 0.0 for want
of a report file (T26).

**So: scan after a merge that changed analysed code.** Locally, never in
CI — the runners cannot reach the server, and the answer to that is not
to expose it. Use `SONAR_TOKEN` (the analysis token), never the admin
token, and pass it via the environment so it stays out of the process
list and shell history:

    export $(grep -E '^SONAR_TOKEN=' ~/.sonar-token)
    npx --yes sonarqube-scanner -Dsonar.host.url=http://<server>:9000

A scan is a measurement, not a gate. Findings are claims to be read at
the call site, and nothing is resolved or dismissed to move a number.

status: resolved (2026-08-12): the owner chose removal. T29 and T30
closed by removal, not by a fix — see "The hadouken question" below.

## The hadouken question (2026-08-12)

Five guaranteed crashes have come out of `couchpotato/core/downloaders/hadouken.py`,
each found by fixing the one before it:

| # | defect | reach | state |
|---|---|---|---|
| T24 | `len()` on a boolean | v4+v5 status | fixed |
| T27 | subclasses shadow the base `@property` members | v4+v5 status | fixed |
| T28 | `b64encode` handed a `str` | v5 `user_pass` connect | fixed |
| T29 | `HadoukenAPIv4` cannot be constructed | ALL v4 | closed by removal |
| T30 | `invoke` posts a `str` body | EVERY operation, both versions | closed by removal |

**No configuration has ever worked.** It cannot add a torrent, cannot
report status, and cannot connect at all on v4. Every defect is a Python
3 migration artefact — str/bytes, property semantics, a dropped base
class — which is what an unexercised module looks like after a language
migration.

I argued twice against removing it, on the grounds that an operator might
have it partially working. That argument was wrong: it rested on a table
I published before measuring `invoke`, and review disproved it. Nobody can
be using this.

So the decision is the owner's, and it is a product decision rather than
an engineering one:

1. **Fix it.** T29 and T30, plus the hard-coded `http://` that T30 would
   otherwise turn into a live credential exposure, plus whatever the next
   layer down produces — the base rate in this file is one new crash per
   fix. Nothing verifies the result short of a real Hadouken instance,
   which we do not have.
2. **Remove it.** It is a downloader that has never functioned in this
   fork. Removal is honest about that, and T18's sweep is the natural
   home. It IS user-facing: the option disappears from the settings UI,
   and anyone with it configured (and silently broken) would notice the
   entry go.

My recommendation is **remove**, with the reasoning that a downloader
nobody can have used is not a feature being withdrawn, and that keeping
it means committing to maintain a protocol client we cannot test against
real hardware. But the counter-argument is real: someone may want it, and
deleting is harder to undo than leaving it broken.

**Resolved 2026-08-12: the owner chose removal**, closing T29 and T30.
`couchpotato/core/downloaders/hadouken.py` is deleted, along with its
config-registration block, its tests, and the settings-UI entry.
Driven (not just reasoned about) before removal: an existing install's
orphan `[hadouken]` section in `config.ini` is never touched by `save()`
(the parser still round-trips it) and never rendered by `getOptions()`
(no plugin registers it any more, so it silently drops out of the UI
form) — confirmed by loading a real `Settings` instance against a fake
config.ini carrying `[hadouken]` and reading `getOptions()`/`getValues()`
directly, not by inspection. One caveat found the same way, not
previously flagged here: the orphan section's raw values (including
`api_key`/`auth_pass`, unmasked, because the `password` type was only
ever known while the plugin's `registerDefaults` had run) still come
back in `getValues()`, which the `settings` API view returns alongside
`getOptions()`. That is pre-existing general behaviour of `Settings` for
any unregistered section, not something this removal introduces, but
removal makes it permanent for anyone with a saved hadouken config —
those two fields sit in the API response, unmasked, until the operator
edits `config.ini` by hand. Not fixed here: it is a pre-existing gap in
`Settings`, out of scope for a downloader removal, and inventing a
migration was explicitly out of scope for this task.

Also driven: `fireEvent('download.enabled', ...)` returning nothing
truthy (the state after hadouken was the only enabled downloader) is the
same code path every fresh install already exercises before any
downloader is configured — `release/main.py`'s `download()` logs "Tried
to download, but none of the ... downloaders are enabled" and returns
`False`. No crash, nothing hadouken-specific to remove.

## Conductor log

- **Tick 44** — **the Dependabot round is closed: 7 merged, 1 superseded, 0 open.**
  Recorded with the date and the command, because the entry this closes is the
  one that recorded `0 open` when eight were.

      measured 2026-08-19 (after the merges)
      gh pr list --author "app/dependabot" --state open  ->  0

      #266 platformdirs 4.11.0 -> 4.11.3   PROD  TAKE       09e1a5ac
      #271 packaging    26.2   -> 26.3     PROD  TAKE       bf7c1ecc
      #273 certifi   2026.6.17 -> .7.22    PROD  TAKE       74fcb680
      #272 coverage     7.15.2 -> 7.15.4   dev   TAKE       cbe51d10
      #269 ruff         0.16.2 -> 0.16.3   dev   TAKE       c2af7554
      #268 axe-core/playwright 4.12 -> .13 dev   TAKE       7a498dff
      #267 stryker (core + vitest-runner)  dev   TAKE PAIR  d1b8cbbe
      #270 stryker/vitest-runner           dev   SUPERSEDED closed

  **§3a's graph check, run the way the earlier trap taught.** The adversarial
  reviewer refused to run `pip check` in `.venv` because that venv still held
  the PRE-bump versions — it would have returned "No broken requirements found"
  while proving nothing. So this time the environment was brought up to the
  merged pins first, and the versions confirmed from `pip show` (the installed
  artefact) rather than from `requirements.txt` (the claim):

      certifi 2026.7.22 · packaging 26.3 · platformdirs 4.11.3
      pip check -> No broken requirements found.

  **Two stale CI runs were hanging, and the fix was the same as the diagnosis.**
  #273's `accessibility` had been "in progress" for **96 minutes** and #268's
  `ui-e2e-tests` for 50, while master's E2E — started four minutes earlier —
  progressed normally. Those runs were created before five merges moved the base
  out from under them. Cancelled, both branches rebased onto master, and the
  fresh runs went 16/16 green in about ten minutes each. The general point is
  the one T44's neighbour already earned: **a Dependabot PR's green is a
  statement about ITS base, and Dependabot does not rebase for you.** Reading
  those two as "slow CI" and waiting would have burned the afternoon.

  **A self-inflicted cost worth recording rather than quietly absorbing.** One
  tick after writing "the gate is reading my working tree, so editing files now
  would invalidate it", I checked out two other branches to rebase them — while
  that gate was mid-E2E. The run was discarded, `node_modules` resynced with
  `npm ci`, and the gate restarted from scratch. Nothing was corrupted and the
  only loss was time, but the reasoning was already written down one screen
  above the mistake. Knowing the rule and applying it are separate acts, and
  this run keeps demonstrating that the first does not imply the second.

  Gate on the rebased branch: `make verify` **exit 0**.

- **Tick 43** — **T46 closed by measurement.** The question was whether T42's
  tests, which SIMULATE a poisoned `GIT_DIR` by setting it themselves, actually
  reproduce the condition git creates. Answered in a throwaway repo under the
  scratchpad, never in this checkout, because the failure mode under test is
  corruption of the repository.

  **The control arm is the finding.** Same repo, same hook, same push, one
  difference:

      push from the main checkout   ->  GIT_DIR = <unset>
      push from a linked worktree   ->  GIT_DIR = .../main/.git/worktrees/wt

  So the asymmetry T42 was written for is real and is now measured rather than
  cited. `GIT_WORK_TREE` stays unset in both, which is worth knowing: the leak is
  `GIT_DIR` alone, and a fix that only guarded `GIT_WORK_TREE` would look
  reasonable and do nothing.

  **The control arm also nearly did not run.** The first attempt pushed `master`
  into a repo whose `git init` had defaulted to `main`, so every control push
  died on `src refspec master does not match any` and printed no hook output at
  all. Read carelessly that is "the main checkout does not leak" — the right
  conclusion from a test that never executed. It was caught only because the
  ABSENCE of output looked wrong, not because anything failed loudly. A control
  arm that silently does not run is the quietest false green there is.

  **Why the simulation is faithful:** the scrub is `os.environ.pop(name, None)`,
  which is value-independent. The real condition and the simulated one differ
  only in who set the variable, and nothing downstream can tell. So the
  simulated tests were testing the real thing all along — which is the answer
  T46 asked for, and it was not knowable without running it.

  **End to end, with `GIT_DIR` pointed at the THROWAWAY repo** so a failure could
  not reach this one: `tests/unit/test_fixtures_do_not_leak_gitdir.py` 5 passed,
  and this repo's HEAD byte-identical before and after.

  **Mutation, because a guard nobody has watched fail is not done.** Replacing
  the `pop` with `pass` — confirmed landed by SHA-256, not by assumption
  (`933eb24d...` -> `05e61a2f...`) — produced:

      AssertionError: the victim HEAD moved -- the scrub did not protect it
      1 failed, 4 passed

  The assertion names the actual corruption, not a proxy for it. Restored by
  file copy rather than `git checkout --` (which would have reverted to HEAD and
  eaten uncommitted work), and verified byte-identical by hash, with the suite
  green again at 5 passed.

  **T18's needs-list is now a test, not a promise.** Ticking T46 left T46 sitting
  in that list minutes later — the FOURTH incident of an error the surrounding
  parenthesis has been predicting about itself since it was written. Four of the
  previous four were caught by a human or a reviewer re-deriving the list by
  hand, which is the precise definition of §9's "a rule that should be a check":
  prose asking the next author to remember something they have already forgotten
  four times.

  `tests/unit/test_plan_needs_list.py` now asserts the list is exactly the set of
  open tasks. Deliberately a SET comparison — file order and reading order differ
  (T11/T15 are transposed) and that carries no meaning, so an order-sensitive
  assertion would fail on a CORRECT list, which is how guards get switched off.
  Proven in both directions rather than assumed: leaving a ticked T46 in fails
  with "T18 names ['T46'] as open, but they are ticked", and dropping an open T45
  fails with "T18 omits open task(s) ['T45']". Plan restored by file copy and
  verified byte-identical, suite green at 4 passed. There is also a guard on the
  guard — if either regex stops matching, the file fails loudly instead of
  passing vacuously on an empty set.

  Measured with `git 2.50.1 (Apple Git-155)` — recorded because this is upstream
  behaviour that could in principle change, and a claim about git with no version
  attached is a claim about one machine on one day. Independently reproduced in
  review, which found it slightly STRONGER than recorded: `GIT_COMMON_DIR` and
  `GIT_INDEX_FILE` are unset in both cases too, so `GIT_DIR` really is the sole
  leak.

  **What this does NOT prove**, stated so the next reader does not over-claim it:
  the pre-push hook was a synthetic three-line script, not `.githooks/pre-push`
  running the real gate. What is established is that git exports `GIT_DIR` from
  a worktree push and that the scrub removes it before collection. Whether the
  full gate has some OTHER worktree-sensitive path is a different question, and
  this experiment does not answer it.

- **Tick 42** — **the Dependabot triage tick 41 recorded as "nothing to do".**
  Owner asked for these directly, and two independent reviewers had already
  flagged the false-zero, so this is the correction and the work in one place.
  A decision for each of the eight, per §3a:

      #266 platformdirs 4.11.0 -> 4.11.3   PROD   TAKE     merged 09e1a5ac
      #271 packaging    26.2   -> 26.3     PROD   TAKE     merged bf7c1ecc
      #272 coverage     7.15.2 -> 7.15.4   dev    TAKE     merged cbe51d10
      #273 certifi      2026.6.17 -> .7.22 PROD   TAKE     awaiting checks
      #268 axe-core/playwright 4.12 -> .13 dev    TAKE     awaiting checks
      #269 ruff         0.16.2 -> 0.16.3   dev    TAKE + companion fix
      #267 stryker/core        9 -> 10     dev    TAKE as a PAIR
      #270 stryker/vitest-runner 9 -> 10   dev    CLOSED, superseded by #267

  **Three needed more than a merge button, and each is a different lesson.**

  **#269 `ruff` failed for the right reason.** `test_the_ruff_pin_agrees_across_
  requirements_dev_and_both_ci_jobs` went red because Dependabot moved
  `requirements-dev.txt` and `ci.yml` pins ruff TWICE more (the lint job and the
  security-lint job). That guard exists precisely so the linter enforcing the
  tree cannot silently differ from the one the developer runs, and it worked.
  Fixed by moving both CI pins, then verified rather than assumed — a linter
  bump ships new rules, so `ruff 0.16.3` was installed locally and run over the
  tree: `All checks passed!`, pin suite 6 passed.

  **#267 and #270 could never have merged separately, and no amount of
  re-running would have shown why.** `@stryker-mutator/vitest-runner@9.6.1`
  declares an EXACT peer dependency on `core@9.6.1`, so bumping either half
  alone dies in `npm ci` with ERESOLVE — which is exactly how both failed. Taken
  together in one commit on #267; #270 closed as **superseded, not rejected**,
  with the reasoning in a comment so it does not read as a silent dismissal.
  Stryker 10 drops Node 20, which is the §3a "drops a supported runtime" test:
  checked, every `node-version` in `.github/workflows` is `'24'`, and mutation
  testing never runs in the merge path. Verified after applying — `npm ls --all`
  exit 0, both packages read 10.0.0 **from disk**, 202 vitest passing, and
  `stryker run --dryRunOnly` completing on 194 tests.

  **#273 `certifi` is the one that made the false zero matter.** It is the CA
  trust store `requirements.txt` pins, `Dockerfile` installs and the runtime
  image carries, so it is the single bump in the set that reaches
  `ghcr.io/bassings/couchpotatoserver` and validates every outbound TLS call to
  indexers, Jackett and TMDB. A `certifi` release is normally a distrust or an
  addition to that store. Tick 41 spent a page on six advisories that cannot
  execute in production and recorded this one as absent.

  **What the two reviews changed in the record itself**, all corrected above
  rather than defended: the false `0 open PRs` row (H1); the reachability grep,
  which was a BRE whose literal pipes made it match nothing in any tree — a §11
  vacuous guard cited as the load-bearing evidence for holding six HIGHs (H2);
  a revisit trigger naming `puppeteer-core` when that trigger has ALREADY fired
  and the real wall is `@lhci/cli@0.15.1` hard-pinning `lighthouse@12.6.1` (H3);
  T45's premise, wrong in three ways — `npm audit` runs nowhere either,
  `dependency-review` is ecosystem-agnostic rather than "the JS half", and Trivy
  already scans the runtime Python set (H4); T36's tick claiming "the last four
  commits added no code" when two of them changed `extractor.py` (M2); T18's
  needs-list stale in BOTH directions for the third time, introduced by the
  commit that ticked T36 and added T45 (M1); and T44's advice to hoist the
  redundant `realpath` because it "costs nothing", when `isSubFolder` has other
  callers passing an unresolved base and the edit would weaken symlink
  containment at two of them (L1).

  Two new tasks came out of the reviews rather than the bumps: **T46**, because
  T42's fix has still never run under the worktree push it was written for, and
  **T47**, because `lighthouserc.js` uploads rendered screenshots of the user's
  library and settings paths to a public Google endpoint — a bigger privacy risk
  than the advisory tick 41 was busy holding, sitting one typed command away.

  **Three corrections from the adversarial pass, which found things the two
  rubric reviews did not.**

  1. **I broke the local gate while validating #269, and the breakage blocked
     every branch in the checkout.** To check that ruff 0.16.3 was clean I
     installed it into the shared `.venv`. But `scripts/verify.sh` fails at
     preflight when the installed ruff differs from the `requirements-dev.txt`
     pin, and master still pinned 0.16.2 — so `make verify` exited 2 before lint
     or any test ran, and since `.githooks/pre-push` runs `verify.sh`, nothing
     could be pushed at all. Measured, not theorised: the gate run launched for
     this very branch came back `exit 2` on exactly that message.

     The general shape is worth more than the incident. **Validating a bump by
     installing it into the shared environment makes that environment disagree
     with every branch that has not taken the bump yet** — including the branch
     you are trying to push. The pin-agreement guard did its job by refusing;
     the mistake was mine.

     **This paragraph originally ended "Resolved by landing #269", and review
     caught that #269 had not landed.** The plan was to land it; the sentence
     described the plan as an accomplished fact. That is the same defect this
     entire entry exists to correct — a state written into a durable file in the
     past tense, where the query would have returned the opposite — committed
     inside the correction, one screen below the new rule ("date every §3a
     measurement") that forbids it. Three occurrences of one habit in a single
     tick is not carelessness about a detail; it is the habit itself.

     The honest form: the resolution path is to land #269, so the environment
     and the repo converge rather than flip-flopping, and until it lands the
     gate stays red and this branch cannot be pushed without `--no-verify`.

     **Closed 2026-08-19, and dated this time.** #269 merged as `c2af7554`.
     After rebasing, `requirements-dev.txt` pins `ruff==0.16.3`,
     `.venv/bin/ruff --version` reports 0.16.3, and `scripts/verify.sh` gets
     past preflight into "1/7 ruff lint — All checks passed!". The environment
     and the repo agree, and nothing was downgraded to make that true.

  2. **#269's CI green was measured against a stale base.** `db-ruff` forked at
     `0a7b197e`, which predates #265 — so the tree its checks ran over did not
     contain the T36 extraction fix, and a two-dot diff against master rendered
     T36 as *removed*, which is a diff artefact rather than a reversion but
     would badly mislead a reviewer. Rebased onto master before merging.
     Generalising: **a Dependabot PR's green is a statement about its base**, and
     Dependabot does not rebase for you.

  3. **The Stryker engine floor cited above is the wrong floor.** The record says
     Stryker 10 requires `node >=22`, which is Stryker's own `engines`. The
     lockfile the bump actually produces drags in Babel 8, and **76 packages**
     in it declare `"node": "^22.18.0 || >=24.11.0"`. The merge stays safe —
     `setup-node` with `'24'` resolves to the latest 24.x — but the reasoning as
     written would not have caught a pin to `24.0.0`, and it understates what the
     bump imposes. Pinning `node-version` more precisely than `'24'` is the
     follow-up.

  **What the adversarial pass CONFIRMED**, so it is not re-litigated: a clean
  venv built from master's pins gives `pip check` "No broken requirements found"
  with all three merged bumps present; certifi's path to the runtime image lands
  on exactly the three lines cited; mutation testing is genuinely outside the
  merge path (`mutation.yml` is `schedule` + `workflow_dispatch` only, and is not
  in the required checks); and the ruff pin guard is real, not vacuous — three
  distinct mutations (each of the two `ci.yml` pins, plus unquoting one) each
  produced a failure on the assertion that names the condition.

  Also worth recording because it nearly produced a false green: the adversarial
  pass was ASKED to run `pip check` in `.venv`, and refused, because that venv
  still held the pre-bump versions. It would have returned "No broken
  requirements found" while proving nothing about the three bumps — a real
  command, a green result, unrelated to the claim. It built a clean venv from
  master's pins instead. That is the incidentally-passing shape, caught in the
  instruction I wrote rather than in the code.

  The through-line, and it is the same failure in three costumes: **depth
  applied to the interesting risk while step one is recorded from memory.**

- **Tick 41** — **T36 merged (#265, `b27bd49f`), closing the last of the four
  tasks this run opened.** Sixteen checks green, head confirmed equal to local
  immediately before merging, and the fix verified ON MASTER afterwards rather
  than from the merge report: the guard constants are present in
  `extractor.py`, and `tests/unit/test_extractor.py` runs 54 passing.

  **Round 15 arrived after CI went green and was correctly not a fix.** A
  `claude-review` nit: `isSubFolder` calls `os.path.realpath()` on BOTH
  arguments per entry, including on `extr_real_path` which `extractArchive` has
  already resolved. Recorded on T44 as a second amplification site and ranked
  below the read loop — CPU and syscalls, not disk. The reviewer explicitly
  asked for a record rather than a change, and got one. The interesting half is
  the pattern, not the cost: `ENAMETOOLONG -> EISDIR -> EILSEQ -> EINVAL` were
  each rediscovered one at a time across four rounds of this PR because the
  first was fixed as an instance instead of a category, and this is that same
  asymmetry on a third surface.

  **Correction to my own reconciliation, before it becomes folklore.** Earlier
  in this tick I recorded "T42's box is wrong, it still reads `pr-open #264`".
  That was true of the file I was looking at and the wrong conclusion. The tick
  existed in a local commit (`ebc1e15b`, rebased to `600f394c`) that had **never
  been pushed**; the branch I read it from predated that commit. So the box was
  ticked and the correction was published nowhere — `git show
  origin/master:specs/REMEDIATION-2026-08.md` still read `[ ] pr-open #264`.
  The drift was real as PUBLISHED and imaginary as WORK, which is a different
  defect with a different fix: the failure was an unpushed commit, not a missed
  update.

  **T42 still carries a residual gap that ticking its box does not close.** The
  scrub is proven against a *simulated* poisoned `GIT_DIR`. The real condition —
  a push from a linked worktree, where git exports `GIT_DIR` into the hook
  itself — has not been exercised since the fix landed, because every worktree
  was removed before it could be. That needs a throwaway clone, not this
  checkout: the failure mode under test IS corruption of the real repository.

  **Dependency triage (the owner's ask), round 2.** T33 was round 1 and is
  merged; this is new work. Measured, not relayed:

      gh dependabot alerts (open)         1   extract-zip, HIGH, first_patched: null
      gh pr list --author app/dependabot  8   ALL EIGHT MISSED — see the correction below
      npm audit                           7 high, 0 critical, 0 moderate
      pip-audit                           NOT RUN — not installed in .venv

  **CORRECTION, and it is the most important line in this entry.** The row above
  originally read `0 no open PRs`. That was false, and it was false about the
  only dependency in the whole exercise with a path to production. Eight
  Dependabot PRs (#266-#273) were open, created `02:13:15Z`-`02:13:39Z`; the
  commit recording zero was made at `02:24:43Z`, eleven minutes later. Five were
  pip, including **#273 `certifi` 2026.6.17 -> 2026.7.22** — the CA trust store
  that `requirements.txt:19` pins, `Dockerfile:27` installs and `Dockerfile:69`
  copies into the runtime image, and therefore the store the production
  container validates every outbound TLS call against.

  **The failure is not "I forgot to check".** The query ran and returned empty,
  and the empty result was written into a durable file as an undated fact. A
  measurement is only evidence at the instant it is taken; recorded without a
  timestamp it becomes a standing claim, and the next session reads the claim,
  not the instant. Two rules follow, and they are cheap:

  - **Date every §3a measurement in the record**, so a reader can see whether it
    predates the thing it denies.
  - **Take step 1 last, not first.** Advisories move on GitHub's schedule; a
    triage that opens with the PR list and closes an hour later has stale
    evidence at the top of the entry and fresh evidence at the bottom.

  There is a real irony worth keeping: this entry spends a page reasoning
  carefully about six HIGH advisories that **cannot execute in production** (the
  npm tree is dev-only test tooling — `.dockerignore:80` excludes
  `node_modules/`, the image installs no node runtime, and `package.json`
  declares zero runtime dependencies), while step 1 of the checklist silently
  dropped the one bump that reaches the shipped artefact. Depth on the
  interesting risk is not a substitute for the boring first step.

  **Six of the seven npm highs are one root cause.** `extract-zip` <= 2.0.1 has
  no patched release at all, and the chain above it — `@puppeteer/browsers`,
  `puppeteer-core`, `lighthouse`, `@lhci/utils`, `@lhci/cli` — is flagged only
  for carrying it. Decision: **HOLD**, on evidence rather than on a feeling that
  dev dependencies do not matter.

  1. **The offered remedy is a downgrade.** `npm audit` reports
     `fixAvailable: @lhci/cli@0.12.0` against an installed `0.15.1`. Taking it
     walks Lighthouse CI back three minor versions to silence a scanner.
  2. **The real upstream fix is pinned away.** `@puppeteer/browsers@3.2.1`
     drops `extract-zip` outright (deps are now `yargs` + `modern-tar`), so a
     fix genuinely exists — but `puppeteer-core@24.37.3` depends on
     `"@puppeteer/browsers": "2.12.1"`, an **exact** pin, not a range. An
     override to 3.x hands `puppeteer-core` an API it does not expect, to fix a
     path it does not execute.

  **Reachability — the conclusion holds, the evidence originally cited did not.**
  This was first recorded as `grep -rln "lhci|lighthouse|test:lighthouse"
  .github/ Makefile scripts/` returning nothing. That command is a **BRE**: the
  pipes are literal, so it searches for the one string
  `lhci|lighthouse|test:lighthouse`, which exists in no repository anywhere. It
  returns empty for every possible tree, including a tree with Lighthouse wired
  into CI on every job. It was cited as the load-bearing justification for
  holding six HIGH advisories, and it is a §11 vacuous guard — an assertion that
  cannot fail — reached in the course of arguing carefully about everything else.

  Re-run correctly as `grep -rlnE`, the answer is genuinely empty: Lighthouse
  appears in no workflow, no `make` target and no script, only in
  `package.json:15,17` and `lighthouserc.js`. So the conclusion survived on luck,
  which is exactly the property that makes a vacuous guard dangerous — it is
  indistinguishable from a real one until the day the answer should have changed.

  Two corrections to the surrounding prose while it is being fixed:

  - "only under a manual `npm run test:lighthouse`" understated the entry
    points: `package.json:17` `test:all` chains it too.
  - "over a ZIP fetched from Google's CDN" describes a path `lhci autorun` does
    not take. `extract-zip` is reached only from `@puppeteer/browsers`'s browser
    **download** path; `@lhci/cli` launches a locally installed Chrome via
    `chrome-launcher`. The real exposure is LOWER than recorded — which is still
    not what was measured, and a hold argued from the wrong mechanism is not
    improved by the mechanism turning out to be favourable.

  **Revisit condition — the first version of this named the wrong package, and
  its trigger had ALREADY fired.** It read "`puppeteer-core` raising its
  `@puppeteer/browsers` pin to 3.x". Measured: `puppeteer-core@25.8.0` is
  published today and already depends on `@puppeteer/browsers@3.2.1`, the clean
  one. A future session checking that trigger literally would conclude a TAKE is
  available, bump `puppeteer-core`, and find the advisory count unmoved. A
  revisit condition that is already true is worse than none: it converts the
  next reader's correct instinct into wasted work.

  The actual wall is two links further up and was never named:

      npm view @lhci/cli dist-tags.latest          -> 0.15.1  (newest release)
      npm view @lhci/cli@0.15.1 deps.lighthouse    -> 12.6.1  (EXACT pin)
      npm view lighthouse@12.6.1 deps.puppeteer-core -> ^24.10.0
      npm view lighthouse version                  -> 13.4.1  (clean, unreachable)

  So the correct trigger is: **`@lhci/cli` publishes a release pinning
  `lighthouse >= 13.4.0`.** The other trigger stands unchanged: Lighthouse being
  wired into CI or the gate, which changes the reachability half of the argument.

  **A remedy this repo already uses twelve times was neither taken nor
  rejected — it simply was not considered.** `package.json` carries an
  `overrides` block (`tmp`, `vite`, `js-yaml`, `qs`, `ws`, `undici`, ...), and
  `specs/CI-002-dependabot-unblock.md` records `js-yaml` being overridden
  specifically to unblock `@lhci/utils`. An `overrides: {"lighthouse": "13.4.1"}`
  is therefore the obvious candidate here. It may well be the wrong call — 12 to
  13 across a programmatic API that `@lhci/utils` calls directly — but "rejected
  with evidence" and "never considered" read identically in a record, and only
  one of them is triage.

  **The seventh is a genuine TAKE:** `nanoid` < 3.3.18, reached via
  `vitest -> vite -> postcss`, with a real transitive patch and no
  `package.json` change implied. Applied in this commit — `package.json`
  byte-identical, `npm ls --all` exit 0, 202 JS unit tests passing, `npm audit`
  7 high -> 6.

  **Applying it turned up two things worth more than the bump.**

  1. **`npm audit fix` is not surgical, and its extra work bought nothing.** The
     plain invocation moved **20** package entries, not one: `puppeteer-core`
     24.37.3 -> 24.43.1, `@puppeteer/browsers` 2.12.1 -> 2.13.2, the whole
     `bare-*` family, dropping `bare-os` and adding `teex`. Measured after:
     `extract-zip@2.0.1` **still present**, and `@puppeteer/browsers@2.13.2`
     **still depends on `extract-zip: ^2.0.1`** — so the advisory count fell
     7 -> 6 purely from `nanoid`, and the entire puppeteer chain moved for
     nothing. It was reverted and re-applied as `npm update nanoid`, giving a
     one-package diff. Taking that churn would have silently contradicted the
     HOLD recorded three paragraphs above, in the same commit, under a message
     naming only `nanoid`.

  2. **The lockfile and the installed tree disagreed, and npm's own bookkeeping
     took the lockfile's side.** After the bump, `package-lock.json` said
     `nanoid 3.3.18` and `node_modules/.package-lock.json` — npm's hidden
     record of what it believes is installed — ALSO said 3.3.18, while
     `node_modules/nanoid/package.json` on disk still said **3.3.17**. Two
     successive `npm install` runs did not reconcile it; only `rm -rf
     node_modules/nanoid && npm install` did. Anyone verifying the fix by
     reading a lockfile, or by trusting `npm ls`, would have recorded a patch
     that was not on disk.

     This is §11's "correct in source, absent from the build" with the twist
     that the build system's own metadata asserts the source version. The
     general rule it earns: **for a dependency fix, verify the version in
     `node_modules/<pkg>/package.json`, not in any lockfile.** Both lockfiles
     are claims; only the installed file is the artefact that runs.

     **It happened a SECOND time in the same session, which is what turns this
     from an anecdote into a rule.** While validating the Stryker pair, that
     install silently reverted `node_modules/nanoid` to 3.3.17 — so review found
     the checkout disagreeing with its own lockfile again, and the recorded
     "7 high -> 6" did not reproduce locally, in the very tick that derived the
     lesson. The deliverable was never wrong: the lockfile integrity hash
     matches the registry byte-for-byte, so `npm ci` in CI always installed the
     patched version. It is the local tree that drifts, and it drifts whenever
     an unrelated install touches the same tree.

     So the rule gains a second half: **`npm install` reconciles unreliably;
     `npm ci` is what actually makes the tree match the lockfile.** Verified —
     after `npm ci` the three packages read 3.3.18, 10.0.0 and 10.0.0 from disk.
     A per-package `rm -rf` plus `npm install` also works but only for the
     package you thought to name, which is precisely the trap: the drift is
     never in the package you are looking at.

  **`pip-audit` is absent, so the Python half of §3a did not actually run.**
  Recorded as a gap rather than reported as a clean result — an unrun scanner
  and a clean scanner are indistinguishable in a summary, which is why this
  line exists. Wiring it into `make verify` is the §9 answer and is now T45.

- **Tick 40** — **T35 done: SonarQube scanned against merged master. Nothing resolved, nothing dismissed.**
  `make sonar` exit 0 against `09a3d153`, so one scan covers both #261 and #262.

      metric                     now      previous
      vulnerabilities            0        0   (was 3 before this plan)
      security_rating            A        A   (was D)
      security_hotspots          0        —
      coverage                   53.7%    53.5%
      sqale_rating (maintainab.) A        —
      duplicated_lines_density   1.9%     —
      bugs                       62       —
      reliability_rating         D        —
      ncloc                      38,016   —

  The security posture the earlier work bought has HELD: 0 vulnerabilities, A
  rating, 0 hotspots. Coverage nudged up rather than regressing, which is the
  thing a big deletion could plausibly have moved the wrong way.

  `bugs: 62 / reliability D` is the headline number and it is misleading
  without the breakdown, which is why the breakdown is here: **39 of the 62 are
  one rule in one file** — `Web:InputWithoutLabelCheck` in `wizard.html`.

  **That is T25, and an earlier version of this entry called it "found
  independently by a different tool with a different ruleset". Retracted.**
  T25 was CREATED from these same SonarQube findings, so a second scan
  reporting the same rule is the same tool agreeing with itself, not
  corroboration. It is evidence the defect is still open, which is worth
  recording, and it is not evidence of anything more. The claim was flattering
  and false, and it is exactly the kind that gets repeated once it is written
  down.

  Of the 17 CRITICAL bugs, three families were verified and recorded as tasks
  rather than left in a dashboard nobody reads:

  - **T38** `simple_healthcheck.py` — `assertIn(str, bytes)` raises TypeError,
    driven, so the check can NEVER pass; and every assertion sits inside
    `except Exception` so the failure is reported as "failed to load web page"
    when the page loaded fine. Fix is deletion, blocked on the same AC-OPS-12
    production grep as `/getkey`.
  - **T39** THREE provider scrapers access a parsed element without a None
    check. (This line said "six" until review caught it. Six S8904
    OCCURRENCES, but `awesomehd.py` supplies two, and three of the six are not
    defects: two are already guarded and one is tolerated by its own
    try/except. See the task entry.)
  - **T40** `synology.py:76` returns from inside `finally`. (This line said it
    discards "any in-flight exception" until review caught it. An ordinary
    exception IS caught and logged by the preceding `except Exception`, and
    the caller is correctly told it failed. What a `return` in `finally`
    actually discards is narrower: a BaseException, or an exception raised
    inside the handler. See the task entry.)

  **One finding I am NOT acting on, and deliberately NOT dismissing:**
  `typescript:S5845` at `category-editor.spec.ts:90` claims an equality
  assertion compares incompatible types. Reading the source, `categoryToForm`
  is plain JS with `id: c._id ?? ''`, so Sonar infers `string` from the fallback
  while the runtime value with `_id: 0` is the number `0` — the test passes and
  the assertion is correct. It looks like a false positive from type inference
  on untyped JS. Marking a finding resolved is the one action that silently
  destroys this tool's value and it needs the owner's decision, so it stays
  open with the reasoning recorded here instead.

  Scanner note, not a defect: the JS bridge failed to parse
  `partials/movie_detail.html`, because `'{{ movie.get('profile_id', '') }}'`
  nests single quotes inside a single-quoted JS string — the raw template is not
  valid JavaScript and only becomes valid after Jinja renders. One template goes
  unanalysed; 90 source files were analysed. Worth knowing the hole exists.

- **Tick 39** — **#261 and #262 both merged; T29, T30, T31 and T33 ticked. Plan 10 of 20.**
  #261 merged as `e433ceba`, verified from `gh pr view` and confirmed on master
  by `git ls-files` showing no hadouken file tracked and the masking present.
  #262 merged as `09a3d153`.

  T33 took all five bumps. The instructive one was #252 (ruff), which was RED in
  CI for a good reason: it failed the guard pinning ruff across
  `requirements-dev.txt` and both `ci.yml` jobs. Dependabot knows about one of
  the three, so its PR was INCOMPLETE rather than wrong, and taking it meant
  moving all three. Two reviewers independently mutated the `security-lint` pin
  back and watched the guard fail with an accurate message.

  rarfile 4.5 turned out to be GHSA-94vx-95fq-wwvp (High), not a routine minor —
  no CVE assigned, which is exactly why it read as routine. Recorded at the pin,
  with a HOLD condition for 5.0 (removes root-level config; would break
  `rarfile.UNRAR_TOOL = ...` silently).

  Added `TestQbittorrentApiSignatureGuard` rather than filing it: that surface
  had been verified BY HAND in review, which covers the bump in front of you and
  nothing after it. Proven against both drift shapes — a removed method, and a
  renamed kwarg that would otherwise fail silently because the call is
  keyword-only.

  Three corrections to my own work this tick, all caught by review: a commit
  message claiming the mutmut comments cited behaviour when they cited three
  line numbers the bump had moved; an over-correction that stripped the stable
  `_load_config()` symbol along with them; and an overclaimed reachability in a
  `settings.py` comment. All three were assertions that tell the next reader not
  to check, which is what makes them worse than the drift they described.

  T36 and T37 recorded from the security lens, both pre-existing. T36 is
  attacker-reachable from an ordinary automated download and rarfile 4.5 does
  NOT close it.

  Armed: `make sonar` running detached (T35), covering both merges in one scan.
  Next wake reads the scan result and reports deltas against the previous one.

- **Tick 38** — **gate green, local review gate passed after two real findings, both in T31's own fix.**
  `make verify` exit 0 on `e5ecaa9c`: 3401 python unit / 42 integration / 202 UI
  unit / 136 E2E + 40 accessibility. The earlier exit-2 was entirely a stale
  `.e2e-w0-data` left by the SIGTERM'd run — same commit, green once cleaned
  through `scripts/e2e_worker_data.py cleanup 0` rather than a bare `rm -rf`.

  Two `code-reviewer` agents on the branch diff (security/privacy, and
  correctness/test-quality). Both returned safe-to-ship, and both found the
  same two latent defects independently, which is the useful signal:

  - Option names were recorded as DECLARED; `RawConfigParser` lower-cases on
    store and `getValues` reads back through `p.items()`, so a registered
    option with a capital letter is starred out. Driven: `{'ApiToken'}` vs
    `[('apitoken', ...)]` -> `'***********'`.
  - The record was built inside the loop, so a plugin raising part way through
    leaves later options renderable but unregistered. `loader.loadSettings`
    fires `settings.options` BEFORE `settings.register` and `event.py` swallows
    the exception, so the loader's own `try` never sees it. Driven with a
    non-string `ui-meta`: `opt_c` renders as `*` instead of `C`.

  **Both were CREATED by T31, not merely surfaced by it.** `self.types` carries
  the same raw-key inconsistency, but before masking existed its only
  consequence was a lost type declaration with the value still rendering.
  Keying masking off registration escalates that to a wrong display. That is
  why they were fixed in this PR rather than deferred: a change does not get to
  leave behind the defects it introduced.

  Fixed in `88405b3f`. Neither was reachable — all 425 in-tree options are
  lower-case and measured renderable/registered divergence across every plugin
  is zero — so nothing in the suite would have failed today. Landmines for the
  next plugin, which is precisely the case §9 says to enforce mechanically.
  Each guard mutation-proven to fail exactly one test and nothing else.

  Rejected with evidence rather than silently dropped: the mask discloses the
  plaintext LENGTH, but it is exactly as leaky as the `password` branch beside
  it (`nzbget.password` is stored plaintext and masked identically), so
  changing one means changing both — out of scope. `test_log_call_arity.py`'s
  3-line diff is docstring prose, not a hardcoded count. `[DEFAULT]`-inherited
  keys do get masked in every section, but they were returned in CLEAR TEXT
  before, so the change moves in the safe direction. Leaving `[hadouken]` on
  disk stands: settings are irreplaceable, the credential is masked in transit
  and never read, and deleting it would move a recoverable state up the
  data-risk ranking to close a leak masking already closes.

  **Process defect, mine.** I ran both reviewers against the SAME working tree
  and told one to mutate files in it. The security reviewer consequently
  observed `settings.py` on disk with the masking removed — verbatim the bug
  under review — and correctly refused to trust the tree, re-measuring against
  a pristine `git archive HEAD` export. Its lead finding was not about the diff
  at all but about that window: a `git commit -a` inside it ships the unmasked
  form, indistinguishable from the defect. Verified afterwards that
  `settings.py` and the test file were byte-identical to `e5ecaa9c` with no
  stray `.bak`. Parallel reviewers that mutate need worktrees, same rule as
  implementers.

  Armed: full gate re-running detached on `88405b3f`. Next wake reads the exit
  code, then pushes and merges #261.

- **Tick 37** — **T31 built, committed and independently verified; T32 opened from a cross-session collision.**
  T31 committed as `e5ecaa9c`. Validated against the repo rather than the
  implementer's report: reverting `settings.py` to its pre-fix contents by file
  copy fails 4 of the 6 new tests on the raw secret, and the 2 that stay green
  are exactly the two asserting registered options are NOT masked — a failure
  there would have meant over-masking. Restored file is byte-identical
  (`7b0e0c27...` before and after).

  Measured the blast radius against a real `config.ini` instead of reasoning
  about it: 44 sections have no source anywhere in this fork, 27 carry
  credential-shaped options, and 2 hold live non-empty values
  (`omdbapi.api_key`, `prowl.api_key`). Every one has been readable through the
  settings API. Hadouken was the 45th, not a special case. Masking cannot blank
  a field a user needs, because `loader.loadSettings` fires `settings.options`
  (what the UI renders) and `settings.register` (what the fix keys off) from
  the same loop over the same section dict — registered and renderable are the
  same set. `getValues()` has exactly one caller, the settings API view.

  Two process findings, both recorded to memory rather than left in the log:

  - A background `make verify` is SIGTERM'd at the turn boundary (`make: ***
    [verify] Terminated: 15` at 69%). Relaunched under `nohup`+`disown` with a
    `.done` sentinel; that run survived the next turn boundary, which confirms
    it. A killed gate reads exactly like a red one, which is the dangerous part.
  - Another session (`AI-Harness`) was running a full gate in THIS checkout,
    triggered by `git push --delete` firing `.githooks/pre-push`. Two Playwright
    suites over one `.e2e-data`. Messaged it directly; it confirmed with better
    evidence than my inference (two `--delete` pushes hung in `make verify`, the
    same delete via `gh api` returned in under two seconds) and is now out of
    the repo with no queued writes.

  That collision produced T32: the pre-push hook never reads stdin, so it
  cannot tell a deletion from an update and gates a push whose diff is empty by
  construction. Deliberately NOT folded into #261 — a gate change riding in on
  an unrelated downloader removal is how it lands without the review its own
  diff would get.

  Armed: detached gate on `chore/remove-hadouken` writing to a `.done`
  sentinel. Next wake expects an exit code to read, then the review cycle and
  the codex thread on #261.

- **Tick 36** — **storage resolved; #261 is blocked by one review thread, not a red check.**
  The owner freed the volume (260Gi free, was 6.6Gi), so the gate is runnable
  again. Reconciled from `gh`, not from memory: #261 has all
  16 checks SUCCESS but `mergeStateStatus: BLOCKED`, and the cause is one
  unresolved review thread, not a red check — `required_conversation_resolution`
  is on. The thread is the codex reviewer's P1 on orphan-section masking, which
  is T31.

  Drove it before acting on it. An unregistered `[hadouken]` section returns
  `{'api_key': 'SUPERSECRET_KEY', 'auth_pass': 'hunter2'}` from `getValues()`
  while a registered password in the same call returns `*****************`. T31's
  own note saying it does not block the removal is corrected in place above,
  with the reason: the removal turns two masked credentials into plaintext ones,
  which is a regression regardless of the age of the underlying class of bug.

  T29 and T30 were ticked on 2026-08-12 when the owner APPROVED the removal.
  That is the decision, not the merge, and the checklist's own rule says the box
  is ticked only from `gh pr view`. Both un-ticked and set to `pr-open #261`.

  Armed: implementer building T31 on `chore/remove-hadouken` (TDD, mask by
  registration, mutation proof required). Next wake expects a local commit and a
  `make verify` verdict to validate against the repo.

- **Tick 35** — **#232 merged (`f97b3ab2`), T9 and T12 ticked. Plan 7 of 16.**

  **All three figures re-derived as medians over the same population**, after
  review caught the first version quoting a single run's 511s beside two
  medians as if they were the same kind of number. Every completed run on the
  branch, n = 9, same `gh api` method as the baseline:

  | | before (n=15) | after (n=9) | range |
  |---|---:|---:|---|
  | wall to a11y verdict | 666s | **138s** | 123-164 |
  | a11y job duration | 139s | 136s | 120-155 |
  | wall to last required check | 666s | **511s** | 503-541 |

  The a11y job duration is unchanged, which is the load-bearing detail: the win
  is queueing removed, not work skipped.

  **The honest summary of this PR is the ratio, not the speedup — and the
  first version of this paragraph undercounted it, which review also caught.**
  Recounted against the spec rather than from memory, rule 8 (the gate written
  to prevent false greens) shipped:

  - **four false GREENS** — `</script >` unmatched; `data-src=` classified
    external; the legacy `<!-- //-->` idiom eating a whole body; and a live
    Jinja render root covered by a hardcoded filename instead of a walk, so a
    new template with a broken script exited 0.
  - **five false REDS** — a Jinja control tag in expression position; a `>`
    inside an attribute value; `<script-loader>` matching because `\b` is not
    an HTML5 tag-name terminator; a commented-out `<script>` being parsed; and
    an unquoted `type=application/json` parsed as JavaScript.
  - **three vacuous or wrong guards** — the `--fail-on-flaky-tests` check
    matching a whole multi-line block; the AC-A11Y-6 enumeration test passing
    for a reason unrelated to what it claimed to guard; and the
    `skip-unterminated` attribution printing four false lines on every green
    run.

  Every one found by review or CodeQL. **None by my own testing**, despite
  mutation-proving each guard as I went.

  What that says about the mutation discipline: proving a guard fires on the
  defect you thought of says nothing about the defects you did not. The
  probes that found these were adversarial inputs from someone who had not
  written the code.

  Two process lessons worth carrying, both now written into the spec:

  1. **A line budget set at planning must be RE-OPENED when review finds
     defects whose fixes do not fit it** — never silently breached, and never
     used as an argument against fixing them. Measured at the merge commit
     (`git diff --numstat f97b3ab2^ f97b3ab2`): AC-SIMP-5 ran to **+58**
     against a cap of 30, AC-SIMP-8 to **+311** against 120. The `+287` first
     recorded here was taken mid-branch and was stale by merge — in the very
     paragraph telling the next reader to re-measure at merge.
  2. **A figure asserted once goes stale.** I recorded "+36" (in `907c7f51`,
     measured mid-branch and true at the time; the merge commit `f97b3ab2`
     makes it +58) and pointed at a
     PR body that never restated the real number, inside a document whose
     stated principle is not to assert what you have not measured. Re-measure
     at merge, not at the time of writing.

  T16 (the residual ~8.5 minutes to mergeable) is the owner's call and is
  recorded with the measurement behind it.

- **Tick 34** — PR #232 open, T9 measured and closed on evidence, 16 review
  threads worked to 0.

  **T9's acceptance criteria closed on measurement.** Figures deliberately NOT
  restated here — they live in one place, the n=9 table in
  `specs/CI-003-fast-gate.md`'s AFTER section, and this entry references it.
  Restating them inline is what produced five separate stale-figure findings on
  this change, including one where a note claiming three medians had been
  recomputed sat above a table where only one had.

  What this tick established: the job duration did not change, so the win is
  queueing removed rather than work skipped. AC-QA-62 closed with a hit on the
  PRIMARY key (269 MB, run 31247191287), AC-QA-64 with the cold run that
  created it.

  **The review found more in my work than the work found in the codebase, and
  two of them were false GREENS** — the gate exiting 0 with a real syntax error
  in the file, which is the exact failure rule 8 exists to prevent:
  `</script>` not matching `</script >` (CodeQL, twice: narrowing to `\s*`
  earned a second alert for `</script\t\n bar>`, so it is now the general
  `</script\b[^>]*>`), and `\bsrc\s*=` matching `data-src=` because `-` is a
  non-word character. Plus three false REDs: a Jinja control tag in expression
  position, a `>` inside an attribute value, and `<script-loader>` matching
  because `\b` is not an HTML5 tag-name terminator.

  **I got one finding wrong twice, in opposite directions, and that is the
  lesson worth keeping.** A reviewer said an unterminated `<script>` followed
  by a terminated one merges into a bogus block. I dismissed it (my test used a
  semicolon, forcing a SyntaxError), then reproduced their exact case, declared
  it a confirmed false green, and wrote a linear opener/closer scan to fix it.
  **That fix was a regression.** Per HTML5 `<script>` content is RAW TEXT
  terminated only by `</script`; stdlib `HTMLParser` sees ONE start tag there,
  so a browser parses the file identically and fails at runtime, not at parse.
  Exit 0 was correct. The scan also broke the real `base.html:238` pattern
  (`// <script>` in a comment). Reverted. I had conflated "the gate passes"
  with "the gate is wrong", and only a spec-following parser settled it.

  **Two of my own guards were vacuous.** The `--fail-on-flaky-tests` guard
  matched the whole multi-line `run:` block, and `ui-e2e-tests` already carries
  two `--project=` lines — so a third without the flag would pass. And the
  Alpine container run would have gone red: removing `node` from PATH produced
  12 failures. The fix for THAT had its own bug — keying on a live
  `shutil.which` meant `monkeypatch.setattr(check_test_traps.shutil, ...)`
  patched the shared module, so `test_missing_node_is_a_hard_named_failure`
  skipped instead of asserting. Caught by reading `-rs` output.

  Also: a push was rejected by the pre-push hook for stale `.e2e-w0-data`, left
  by a `make verify` that timed out and was backgrounded while another started.
  Two gate runs must not overlap, and a gate run whose files change under it is
  not evidence.

- **Tick 33** — T9 + T12 built on `ci/fast-gate-and-template-js`. Part B (the
  template-script parse rule) delegated to the implementer; Part A (`ci.yml`)
  done by the orchestrator, because it carries the branch-protection trap and a
  conflict in that file would have been expensive.

  **The measurement that reframed the task is in T9's entry above: the owner's
  "over ten minutes" was accurate, and three earlier rounds of correction had
  each measured the job rather than the wait.** That is the third time a
  section of this plan arguing against diagnosis by inference has itself been
  wrong by inference. The pattern is specific enough to name: when a report is
  about *elapsed time*, measure elapsed time, not the duration of the component
  you suspect.

  Verified against the repo rather than the implementer's report, all
  independently re-run: the #230 defect reintroduced turns the gate red at the
  real `suggestions.html:226` (SHA-256 `a25f14c5…` → `c6815626…` → `a25f14c5…`,
  byte-identical restore); a syntax error inside a Jinja-bearing block is
  reported at real line 367, so the placeholder substitution has not become a
  blanket silencer; `partials/movie_detail.html` is parsed rather than excluded
  and no template filename appears in the checker's operative code; the
  accessibility test listing is byte-identical between master and the branch
  (40 tests, 3 spec files); `git diff master -- couchpotato/` is empty.

  New guard `tests/unit/test_ci_required_contexts.py`, mutation-proven in three
  directions (rename the job, gate its run step behind `if:`, drop
  `--fail-on-flaky-tests`), each red, file byte-identical after restore. It
  replaces a hand-written comment at `ci.yml:88-92` that asked the next person
  to remember the same thing — CLAUDE.md rule 9.

  **Two findings against my own work, recorded rather than quietly fixed.**
  AC-SEC-7 caught me pinning `actions/cache@v4` when the repo already pins
  `@v6` — a silent action downgrade nothing else in the gate would have seen.
  And AC-SIMP-5's 30-line cap on `ci.yml` is breached by 6, entirely by
  comments AC-OPS-8 and AC-SIMP-6 require; recorded in the spec as an AC-vs-AC
  conflict for the review cycle to arbitrate. The generalisable lesson: a
  net-line budget on a file whose house style is long explanatory comments
  should count code lines, not total lines.

  Armed: `make verify` running to completion before any push. Next wake expects
  a green gate, then `/review-cycle`, then the PR.

- **Tick 32** — #229 merged (`aac4c31c`), T4 ticked, bookkeeping PR #231 merged
  (`9eb66da7`). Plan stands at 5 of 15. T5's spec extracted to
  `specs/FEAT-009B-UPGRADE-REPLACEMENT.md`; T9 + T12 taken through
  `/plan-cycle`, which returned 49 criteria and found six defects in the
  drafted spec's own prose — including an assertion that ESLint covers this
  repo, which it has never done.

- **Tick 31** — **PR #229 raised** for T4 after `make verify` went green
  (exit 0, captured to a log rather than through a pipe). Five implementation
  tranches, then a nine-lens review returning eleven findings: seven fixed,
  four deferred with reasons in `specs/PR2B-SESSION-COOKIE.md`.

  Two of the fixed findings were criteria a tranche had reported DONE and had
  not built (AC-DESIGN-7's `HX-Redirect`, AC-OPS-47's log clause), which is the
  argument for the review gate existing at all. One was a **lockout**: on a
  `url_base` install the pre-upgrade `path=/` cookie shadowed the new one and
  the operator could not log in, while the page told them their password still
  worked. AC-SEC-44's upgrade drill missed it because that drill runs at root,
  where the two paths coincide.

  **I introduced a startup crash and the gate caught it.** The posture log
  called `session_cookie_attributes()` above the line that sets `web_base`, so
  a real server died on boot -- and all three of my unit tests passed because
  every one of them monkeypatched the function that breaks. Fixed by ordering,
  plus a test that drives the real function and one that pins the ordering by
  source. That is the second fix on this branch to introduce a defect; both
  were caught before push, which is the frame holding rather than failing.


- **Tick 10** — #228 merged (`085160eb`, verified from `gh pr view`, 19/19
  green). **T9 stays unticked:** what merged is the PR 7 *plan*;
  `git diff cd358c20..origin/master -- .github/workflows/ci.yml` is empty, so
  the gate is exactly as slow as it was. A merged plan is not a merged fix.

  T4 started, and per M15 it started with `/plan-cycle`, not code. Spec split
  out to `specs/PR2B-SESSION-COOKIE.md` so the lenses had a one-PR surface;
  nine ran, none skipped, 85 ACs and eight settled decisions. Four executed
  claims re-verified against source rather than relayed: the `text/html`
  rate-limit exemption (so `POST /login/` is unlimited), `listDocuments`
  iterating `db.all('id')` (so an `api_key` holder can read a property row),
  `setProperty`'s bare `except Exception:` turning a lost CAS into a duplicate
  insert, and zero logout controls in the UI. Re-measuring the binary
  round-trip *strengthened* a criterion: the corruption is length-variable
  (lens saw 31 chars, I saw 29), so a naive length assertion would be flaky.

  Open concern recorded rather than acted on: at 85 ACs over eight source
  files this is a big PR, and the one genuinely separable piece is the
  rate-limit fix (AC-SEC-42) — it is a real finding but independent of the
  cookie. Left in scope because nine lenses just agreed it; split it if the
  diff proves unreviewable. Armed: nothing external — T4 implementation is next.

- **Tick 9** — #228 is 19/19 green; BLOCKED was two more unresolved review
  threads, not a check. Both were arithmetic in tick 8's own correction, and
  both were right: the median of an even-length sample is `(118 + 129) / 2 =
  123.5s`, not the 7th sorted value, and the eleven non-outlier runs span 38s,
  not 30s. Recomputed rather than argued, in the section, in the tick 8 entry
  above, and in the sentence T9.1 hands to whoever measures next. That is the
  third round of wrong numbers in a section whose thesis is "do not diagnose by
  inference" — so the raw twelve-run series is now printed alongside every
  statistic derived from it, which is the only fix that survives the next
  editor. Armed: CI watcher on #228 after the push.

- **Tick 8** — #228 review returned five findings, all correct, all fixed in
  392c268c. Two were the T9 section failing at its own stated purpose: it said
  "the last six runs" over a five-row table and used "one in six" as the
  evidence for calling the spike isolated. Re-measured rather than edited:
  n=12, median 123.5s, exactly one run over 5 min, eleven spanning 38s. The
  P1 had teeth -- `accessibility` is a REQUIRED status check, so T9.2's
  advertised "biggest win" would have deleted the job publishing it and blocked
  every subsequent merge; acceptance now requires keeping the context or
  changing protection in the same change. And T9 had no AC-<LENS>-<n> forty
  lines below the rule requiring them, now marked NOT YET WRITTEN with
  /plan-cycle as the precondition.

  Process note: the first push FAILED the gate and my `echo` printed regardless
  -- the exit-code trap. Retry passed (transient E2E flake), known only because
  the second attempt captured `$?` directly. Armed: CI watcher on #228.

- **Tick 7** — **#227 MERGED** (master `cd358c20`), verified with `gh pr view`,
  not from memory: CI 19/19, 0 unresolved threads, mergeStateStatus CLEAN.
  Branch deleted. T3 ticked. T4, T5 and T8 are now unblocked and may run in
  parallel.

  Added **T9 / PR 7** at the owner's request: make the accessibility gate fast.
  Measured before scoping, and the framing needed correcting -- the job builds
  no Docker container. It is normally ~2 minutes (1m39s, 2m17s, 2m10s, 1m58s
  across four runs) with ONE 11m37s outlier, while the unrelated `docker` job
  is a steady ~1m20s. The real complaint is wall-clock: `accessibility` is
  `needs: ui-e2e-tests`, itself `needs: [test, ui-unit-tests]`, so it is third
  in a serial chain. Scoped as measure-first (T9.1), then the duplicated
  uncached `playwright install --with-deps` paid twice (T9.2), then the
  unexplained `needs:` edge (T9.3). Reducing what the suite covers is
  explicitly out of scope.

- **Tick 6** — push of ce4a0894 landed, local gate green, local == remote.
  Armed: CI watcher on #227. Next wake expects CI settled; if green and threads
  clear, merge #227 -> T3 `merged`, which unblocks T4, T5 and T8 to run in
  parallel. Per review M15, PR 4 (T5) runs /plan-cycle FIRST so its lenses write
  numbered AC-<LENS>-<n> into this spec before any code is written: a review
  with no acceptance criteria can only report what it happens to notice, which
  is exactly what this cycle's own coverage statements showed.

- **Tick 5** — review cycle wf_3eafdf36-b0b returned: 7 lenses, all FINDINGS,
  none BLOCKED. 3 High, 15 Medium, 9 Low.

  **H1 confirmed against the repo, and my verification was the false green.**
  The committed `.claude/workflows/review-cycle.js` had a `//` inside an array
  literal, swallowing the closing bracket. `node --check file.js` exits 0; the
  same bytes as `.mjs` -- the mode the runtime loads, given `export const meta`
  -- fail with exactly the error two lenses reported. I approved it with a
  check run in the wrong mode, which is CLAUDE.md §11's "green test in the wrong
  environment". The cycle only ran at all because the runtime fell back to the
  global copy, which has none of this repo's seven fixes -- and that fallback is
  also why `lens-operability` never triggered on a diff that changes scheduled
  behaviour. Fixed, plus a test that parses every workflow script the way the
  runtime does, proven by reinstating the exact shipped line.

  Also fixed this tick: H3 (repeated settings toast never re-announced, WCAG
  4.1.3 -- the panel took base.html's persistent-region half and left the
  clear-then-$nextTick half behind), M8 (the refusal path still set
  `lastSaved`, so the green "Saved" tick and its polite region fired alongside
  the assertive error -- on the one flow this change exists to make truthful),
  M4 (the lockout guard's `addEvent` wiring was executed by no test: deleting
  one line made it inert with the suite green), L3 (the password mask keyed on
  `== 'password'`, and `getType` returns 'unicode' for an UNREGISTERED option,
  so it failed OPEN -- now keyed on whether the option was registered at all).
  M2 recorded at the line: the orphan-release loop is dead on SQLiteAdapter, so
  the new "Cleaned up N" log can never fire; pre-existing, and repairing it
  changes a delete path, so it is deferred rather than folded in here.

- **Tick 4** — woken by the #227 CI watcher. CI green: 19 passing, 0 failing;
  20 review threads, all resolved. (The watcher's own thread-count query
  returned a GraphQL quoting error, not a number -- re-ran it properly rather
  than reading a broken result as zero.) Review workflow wf_3eafdf36-b0b still
  running, 8 lenses in flight. Nothing else unblocked, so used the wait to load
  T5's scope: PR 4 is the third attempt at upgrade replacement after two
  withdrawals, and its sequencing constraint is the important part -- T4.1's
  profile-independent ranking must be green BEFORE T4.2 attaches releases,
  because attaching them is what makes the gate live and on attempt #2 that
  would have activated the destruction. Armed: the review workflow. Next wake
  expects the synthesised report.

- **Tick 3** — push of d1c30476 landed, local gate green, local == remote.
  Ran /review-cycle as a workflow against base fd5b43e8 (the #226 merge) with
  the spec attached, so each lens verifies its own AC-<LENS>-<n> criteria. Run
  wf_3eafdf36-b0b. This is the gate before merge, and it is warranted rather
  than ceremonial here: the two committed lens reports predate six commits of
  substantial security change, and two of my own fixes on this branch made a
  disclosure WORSE and were caught only by review. Armed: the review workflow,
  plus a CI watcher on #227's checks for the new push. Next wake expects a
  synthesised report -- fix findings or record evidenced rejections -- then
  merge if clean.

- **Tick 2** — woken by the #227 check watcher. CI green: 19 passing, 0 failing.
  One thread, marked a nit by the reviewer and agreed with: the per-directory
  cleanup guard makes cleanup permanently inert for a legitimately empty folder.
  Acted rather than merely recorded — the WARNING said what happened but not
  what to do, so it now names the remedy (remove the folder from Settings >
  Library, or check the mount). d1c30476. T3 -> `in-review`. Armed: push of
  d1c30476 (pre-push hook re-runs the full gate). Next wake expects the push
  landed, then runs /review-cycle against the final tip before merging.
  Deliberately NOT running the review cycle concurrently with the gate: both
  want the shared .venv, and worktree agents damaging it via its symlink is a
  recorded hazard on this repo.

- **Tick 1** — first invocation; checklist created from measured state, not memory.
  `gh pr list` confirms T1 merged #225 and T2 merged #226. T3 is `awaiting-ci
  #227`: 16 checks SUCCESS, 2 still running, 0 failing, 0 unresolved review
  threads. T4 and T5 stay `queued` deliberately rather than starting in
  parallel — both edit `couchpotato/__init__.py` and `release/main.py`, which
  #227 changes heavily, so starting either now buys a rebase conflict for no
  wall-clock gain. Armed: background watcher on #227's checks (single
  notification on settle). Next wake expects #227 either green (then:
  /review-cycle, then merge) or red (then: fix, push, re-arm).

## PR 1: M0: Safety net

> **Revised 2026-08-03 after the planning cycle.** Six lenses ran
> (security, QA, data, operability, simplicity, accessibility). Every task below
> changed. The original PR 1 would have shipped a fix that fixed nothing (T1.5),
> a fix that introduced a worse bug (T1.2), a deletion of a file that does not
> exist (T1.3), a sweep scoped 10× low (T1.4), and an `rm -rf` one directory
> from 139 MiB of git-unrecoverable data (T1.7). Full lens reports: session
> transcript, 2026-08-03.

**Goal:** put tests under the destructive paths, **stop the data loss those
tests uncovered**, make the E2E suite trustworthy, and stop the lint gate
floating.

**Why first:** PR 3 and PR 4 edit code adjacent to `moveFile` and the release
lookup: if M0 lands after, those fixes ship unguarded. And every later PR is
gated on an E2E suite currently red ~1-in-5 for unrelated reasons.

**Scope change from the original plan.** PR 1 is no longer "changes no runtime
behaviour". Planning found three verified data-loss defects in `moveFile`
(T1.8), and the precedence order puts irrecoverable loss above a self-imposed
constraint. Decided 2026-08-03: **fix them here, TDD**: tests pin the current
behaviour, the fix lands, the tests assert the new behaviour.

### T1.1: `moveFile` branch tests · M · risk: low

`MoverMixin.moveFile` (`plugins/renamer/mover.py`). The only existing tests monkeypatch it away
(`test_renamer_cleanup_safety.py:70`).

New `tests/unit/test_renamer_mover.py`. Real files in `tmp_path`, real `shutil`,
real `os`. **Stub only `self.conf` and `Env.getPermission`**: a test that stubs
`shutil.move` on a happy path is rejected; that is the shape that let this
function go unexecuted.

Fixtures use distinct, asserted content (`'THE DOWNLOAD'` vs `'THE LIBRARY
COPY'`) and ≥1 MiB payloads with SHA-256 comparison, so a size-only check cannot
pass a content test.

- **AC-QA-1** `move`: destination holds the source's exact bytes, source gone,
  returns `True`, mode == `Env.getPermission('file')`.
  *Break:* `shutil.move` → `shutil.copy`; the "source is gone" assertion fails.
- **AC-QA-2** `copy`: source survives byte-identical, destination is an
  **independent** file: assert `st_ino` differs. *Break:* swap `copy` for
  `link`; the inode assertion fails.
- **AC-DATA-2 / AC-QA-3** `link`: `st_ino` equal and `st_nlink == 2`. If the
  filesystem cannot hardlink the test **fails loudly**: it does not skip. A
  silent skip is how this branch stayed untested.
- **AC-QA-4** `symlink_reversed` happy path: destination is a regular file with
  the content; `old` is a symlink whose `realpath` is `dest`.
- **AC-QA-5** `use_default=True` reads `default_file_action`, `False` reads
  `file_action`. Set the two to **different** branches and assert which ran by
  observing the filesystem, not a mock's call args. *Break:* delete the
  `if use_default:` block at `:23-24`.
- **AC-DATA-3 / AC-QA-7** Failed move, **equal-size** destination: the source
  **is** unlinked, returns `True`. Docstring states the check is size-only.
  *Break:* `os.unlink(old)` at `:34` → `pass`.
- **AC-DATA-4 / AC-QA-8** Failed move, **equal size, different content**: the
  source is destroyed and the corrupt destination kept. `xfail(strict=True)`
  with reason "recovery verifies size, not content": the day a checksum is
  added this XPASSes and the suite reds, forcing acknowledgement.
- **AC-DATA-5 / AC-QA-9** Failed move, **short** destination: source survives
  byte-identical, partial destination removed, **exception propagates**.
  *Break, two directions:* `os.unlink(dest)` at `:37` → `pass`; delete `raise`
  at `:38`.
- **AC-DATA-6** Failed move where the **source no longer exists**:
  `os.unlink(dest)` is never reached and the destination keeps full content.
  This is the regression pin against "hardening" `os.path.getsize(old)` at
  `:32`: today the `FileNotFoundError` is the *only* thing preventing the
  `else` branch deleting the last copy.
- **AC-DATA-9 / AC-QA-13** `link` fallback, copy succeeds: `old` is a symlink
  resolving to `dest`, **no stray `<old>.link`**. *Break:* delete
  `os.rename(old_link, old)` at `:64`.
- **AC-DATA-10** ~~`link` fallback, copy fails part-way: source survives, a
  truncated file sits at `dest`, and a **second** call raises `Destination
  already exists`: the destination-poisoning recorded as known behaviour.~~
  **INVERTED at the second review round, 2026-08-06.** Accepting the
  poisoning was itself the planning error. `link` is the shipping default and
  its hardlink fails whenever the download directory and the library are on
  different filesystems, so this is the likeliest branch in the function to
  meet a full disk -- and the accepted outcome was a truncated file at the
  library filename that `_moveRenamedFiles` then skipped on every subsequent
  run, with the scanner attaching it to the movie. The criterion now reads:
  `link` fallback, copy fails part-way: source survives, the partial `dest`
  is **removed**, and a **second call succeeds**. *Break:* drop the
  `_discard_partial_destination` call from the fallback.
  Left visible rather than rewritten silently, because a stateless reviewer
  reading the old text would have filed the correct behaviour as a
  regression -- which is exactly the mechanism that produced the
  fix-the-instance-miss-the-class history this PR keeps hitting.
- **AC-DATA-10b** *(added at the second review round; corrected at the
  fourth, which found it mis-enumerated)* **Every branch of `moveFile` that
  writes bytes to `dest` removes a SHORT destination on failure, and never
  removes an equal-size one.** Four byte-writing branches, **three** helper
  call sites plus one inline equivalent:
  - `copy`, `symlink_reversed` and the `link` fallback each call
    `_discard_partial_destination`. *Break:* remove any one call; a distinct
    named test reds for each.
  - the default `move` branch implements the property **inline**, with
    different edge semantics (`os.path.exists` rather than `lexists`, and on
    an equal-size destination it unlinks the SOURCE and returns True). Pinned
    by `test_failed_move_with_a_short_destination_...`.

  **SUPERSEDED at the fifth review round: the clause below is not achievable
  as written, and the sixth round found that its recorded remedy DELETES THE
  DOWNLOAD if implemented literally.** `shutil.move` is `copy_function` PLUS
  `os.unlink(src)`, so removing one failing half always leaves another; four
  rounds of trying is the evidence. See docs/technical-debt.md's "STOPPED
  after four rounds" for the measurement, the frame diagnosis, and the two
  constraints any replacement must satisfy (verify CONTENT not size; an
  end-state success must unblock the retry, never authorise cleanup).
  **Do not attempt a fifth fix against the struck text below.** It is kept as
  the record of what was tried:

  ~~And no branch may use a composite `shutil` call whose non-copy half can
  fail alone. `shutil.copy` is copyfile+copymode; `shutil.move` falls back to
  `copy2`, which is copyfile+copystat. Either one failing after the bytes land
  leaves a COMPLETE destination that the helper correctly refuses to remove
  and the `lexists` guard then blocks for ever. `copy` and the `link` fallback
  use `shutil.copyfile`; `symlink_reversed` passes
  `copy_function=shutil.copyfile`. The default `move` deliberately does not,
  because it recovers on its own and mtime preservation is worth keeping on
  the most common path.~~

  This criterion was written to stop a branch being missed by enumeration and
  was itself mis-enumerated twice: first claiming four call sites where three
  exist, then covering `shutil.copy` while `shutil.move` had the same shape.
  Recorded rather than quietly corrected, because that is the finding.
- **AC-QA-14** `link` with both `link()` and `symlink()` failing: degrades to a
  plain copy, both paths exist, returns `True`.
- **AC-QA-18** `os.chmod` raising is swallowed; the move still returns `True`
  and the destination is intact. Monkeypatch `os.chmod`: a permission trick is
  unreliable when the suite runs as root in Alpine.
- **AC-QA-12** Failed move with a **directory** at the destination: assert
  "raises, and the source is intact": **not the errno**. Measured
  `PermissionError` on macOS, `IsADirectoryError` on Linux; an errno assertion
  is green-on-macOS, red-on-Alpine.
- **AC-DATA-15 / AC-QA-19** The `os.name == 'nt'` branch carries an explicit
  `skipif` whose reason **cites the `os.popen` string-concatenation at
  `moveFile`'s `os.name == 'nt'` branch (`os.popen`/`icacls`)**, so the gap is knowingly uncovered rather than silently
  absent. (`lens-security` flagged that line as command injection reachable
  from indexer-supplied release names on Windows with `ntfs_permission`. Not
  PR 1's to fix: filed to PR 3, which already edits `renamer/`.)
- **AC-DATA-16** Hermetic: every path derives from `tmp_path`; the suite passes
  twice consecutively; `git status --porcelain --ignored` unchanged; `.config/`,
  `test_data/` and `.e2e-data*` mtimes unchanged.
- **AC-SEC-14** Every path passed to `moveFile` is asserted to be a child of
  `tmp_path`. A test for the `os.unlink(old)` branch that resolves outside the
  fixture is the one way this PR can itself destroy data.
- **AC-QA-21** `test_renamer_mover.py` runs in **< 2 s** and contains no
  `time.sleep`. Baseline to protect: 1936 unit tests / 29.0 s on CPython 3.14.6.
- **AC-DATA-17 / AC-QA-22** The whole file passes under `./scripts/test-local.sh`
  (Alpine/musl). Every measurement behind these criteria is macOS/APFS;
  hardlink, symlink and `chmod` semantics differ. An assertion that cannot hold
  on both is skipped with a reason naming the platform and syscall: never
  weakened to pass everywhere.

### T1.8: Fix the three data-loss defects in `moveFile` · M · risk: **high**: NEW

All three verified by execution during planning. TDD: the T1.1 tests pin current
behaviour first, then the fix lands, then the assertions invert.

**(a) A directory at the destination is treated as a successful move.**
`moveFile`'s destination-exists guard tests `os.path.exists(dest) and os.path.isfile(dest)`, so a
directory does not fire the guard. Measured: the file moves *inside* it as
`dest/<original basename>`: unrenamed: `os.chmod(dest, Env.getPermission('file'))`
at `mover.py:69` on `master` (the literal `0o644` written here before is not in
the code; the value comes from the `permission_file` setting) then
strips `+x` (measured `traversable: False`), and `True` is returned, so
`_moveRenamedFiles` sets `moved_any=True` and cleanup deletes the source folder.
*Fix:* test `os.path.exists(dest)` (or `lexists`) alone.

**(b) The hardlink fallback unlinks the source before the rename.**
the `link` fallback. Measured with `link()` and `os.rename` both failing: `old`
gone, stray `<old>.link` left, return `True`. *Fix:* drop `os.unlink(old)` at
`:63`, use `os.replace(old_link, old)`: atomic, never leaves `old` absent.

**(c) `symlink_reversed` swallows a failed move and returns `True`.**
the `symlink_reversed` branch. Measured: move fails, exception swallowed, symlink
then fails and is swallowed at `:50-51`, `chmod` fails and is swallowed at
`:72-73`, returns `True` with the source unmoved and nothing at the destination.
`_moveRenamedFiles:160-162` then sets `moved_any=True`, `skipped` stays `False`,
and `:174-177` calls `deleteFolder(parentdir)`: **on a full disk or a dropped
NAS mount, the completed download is deleted and nothing reaches the library.**
*Fix:* re-raise (or return falsy) when the move fails in this branch, so the
existing `skipped` guard engages.

- **AC-DATA-12 / AC-QA-17** Each fix is proven at the **caller** level, not just
  in `moveFile`: drive `Renamer._moveRenamedFiles` with `cleanup=True` against a
  real filesystem and assert the source folder is **not** deleted. The unit-level
  assertion alone is a curiosity; the caller-level one is the data-loss guard.
- **AC-DATA-8 / AC-QA-11** After (a), a directory at the destination raises and
  neither file is touched. PR 4 builds its replace-or-skip decision on this same
  guard, so it may not inherit the old behaviour quietly.
- **AC-QA-15** After (b), no stray `<old>.link` survives any failure ordering.
- Every fix is proven load-bearing by reverting it, watching the test fail, and
  confirming via `git diff` that the revert landed before restoring.

### T1.2: `correctRelease` tests + the `:419` fallback · M · risk: medium

**The fix sketched in the original plan was wrong.** Verified against a real
`SQLiteAdapter` with two quality rows:

```
db.get('quality', None, with_doc=True) -> cam      # first row, no error
db.get('quality', 'nope')              -> KeyError  # correct
```

`_query_index` treats `key is None` as "no filter", so the natural repair: `quality.get('identifier')` on a falsy `quality`: resolves `preferred_quality`
to Cam, whose `size_min`/`size_max` gates pass almost any release, in the
function that decides what gets downloaded.

**And `:419` is not the only crash on that path.** `quality.single()`
(`quality/main.py:128-142`) returns a dict with **no `custom` key**: it is
grafted on only at `searcher.py:326`: so `:429` raises `KeyError: 'custom'`
when `searcher.correct_3d` is falsy; and for an unresolvable identifier
`single()` returns `{}`, so `:433` raises on `size_min`.

- **AC-DATA-18 / AC-QA-29** When `quality` is falsy (`None`, `{}`, `False`),
  `correctRelease` returns `False` with a logged reason: it does **not**
  resolve a quality from the database.
- **AC-QA-30** The fallback path returns a verdict without raising for (a)
  `correct_3d` stubbed **falsy** and (b) an unresolvable identifier. A test that
  stubs `correct_3d` truthy passes **incidentally** and leaves two live crashes.
- **AC-DATA-19** Every accept/reject assertion uses **two** fixtures differing
  only in the key under test. A one-row fixture passes against a key-ignoring
  lookup: the defect class this repo has already shipped twice.
- **AC-QA-23/24/25** Happy path `True`; wrong quality → `False`; banned-word →
  `False`. **Assert the rejection reason via `caplog`**, not just the verdict: a bare `assert result is False` passes for any of six reasons.
- **AC-QA-26** Size gates: below `size_min` → `False`; above `size_max` →
  `False`; **`size == 0` (unknown) is not rejected**.
- **AC-QA-27** Retention: `seeders is None` and `age > retention` → `False`;
  `age == retention` **not** rejected (the `<` boundary at `:411`); a torrent is
  never retention-rejected.
- **AC-QA-28** `media['type'] != 'movie'` returns **`None`**, not `False`: `providers/base.py:361-370` does `if is_correct:` then `float(is_correct)`, so
  the distinction is load-bearing.
- **AC-SEC-13** At least one release rejected today by each of the quality,
  word and size gates is still rejected after the fix, with the reason asserted.
  `correctRelease` is the only filter between indexer-supplied metadata and a
  queued download.
- Fixtures build quality dicts the way `QualityPlugin.single()` does (static
  entry merged with a DB doc), **not** hand-rolled minimal dicts: a hand-rolled
  dict that happens to carry `custom` hides AC-QA-30.

### T1.3: Delete dead files, wire `tests/integration/` · S · risk: low

**Corrected:** the original list named `test_startup_local.py`, which is
gitignored (`.gitignore:33`) and untracked. Deleting untracked local files is
not the implementer's business. Two root files are tracked, not three.

Delete: `couchpotato/simple_healthcheck.py`, `couchpotato/integration_test.py`,
`couchpotato/environment_test.py`, root `test_migration_local.py`,
`test_sqlite_adapter.py`, `tests/e2e/test_existing_user.py`,
`test_fresh_install.py`, `test_real_data_migration.py`, `tests/e2e/__init__.py`,
`ui-prototype/index.html`, and `pytest.ini`'s now-dead
`--ignore=tests/e2e/test_real_data_migration.py`.

- **AC-QA-36** The two `tests/e2e/test_*.py` suites are **deleted, not wired**.
  Measured: 15 tests, 0.02 s, asserting that `os.makedirs` works and that fields
  exist in a JSON fixture. They import no application module, so no product
  regression can turn them red.
- **AC-QA-34** `tests/integration/` is executed by **both** `verify.sh` and
  `ci.yml`. Measured cost: 38 tests, 2.4–3.2 s. `test_duplicate_detection.py` is
  the direct regression net for the `_query_index` defects PR 3 edits.
- **AC-QA-35 / AC-DATA-22** `test_real_database.py` **moves out of the executed
  path** (decided 2026-08-03): to `tests/local/`, outside `pytest.ini`'s
  `testpaths`, with a module docstring stating it is a local-only tool requiring
  `/var/media/config_backup.zip`. Its 7 tests are gated on a 39 MB machine-local
  file that will never exist on a runner; wiring them in place would have bought
  7 permanent silent skips and let "38 integration tests now run in CI" become a
  claim that is only true on one laptop. CI gets **31 tests that can actually
  fail**, and the reported count means what it says.
  **The real backup must never be committed or uploaded as an artifact**: it
  carries live credentials, real library paths and ~849 media documents. State
  that in the docstring so the next person does not "fix" the relocation by
  supplying the fixture via a CI secret.
- **AC-DATA-23** ~~If the round-trip migration test is kept:~~ **Unconditional,
  amended at review 2026-08-06.** The conditional form had no owner and was
  still unwritten when the PR was otherwise complete: the test was kept, and
  nobody was accountable for the criterion. Running the migration **twice**
  yields the same document count, with no duplicated `_id` and no duplicated
  `media_identifiers` row (`verify()` compares only the `documents` table), and
  the source CodernityDB directory is **byte-identical afterwards**, hashed per
  file. *Break:* a plain `INSERT` in `insert_bulk`, and a stray write into the
  source from `read_codernity_docs`; each must red.
- **AC-QA-38** The new `check_test_traps.py` rule keys on the **runner
  invocations** in `verify.sh` + `ci.yml`, not on `pytest.ini`'s `testpaths`.
  `testpaths = tests` already "covers" `tests/integration` while no runner
  executes it: a rule anchored on `pytest.ini` passes today against an orphaned
  suite and is therefore vacuous. *Break:* delete the `tests/integration`
  invocation from `verify.sh`; the guard must red.
- **AC-DATA-21** The guard **reports and never removes**, and enumerates from
  `git ls-files` rather than a filesystem walk, so an untracked local scratch
  file can neither fail the gate nor be swept up by a later "fix the finding".
- **AC-QA-38b** *(added at review 2026-08-06, see spec gap 9)* The guard's
  **predicate** counts **both** pytest naming conventions, `test_*.py` and
  `*_test.py`. `pytest.ini` narrows `python_files` to the first, which is
  exactly what made the suffix form dangerous: `couchpotato/settings_test.py`,
  `couchpotato/core/softchroot_test.py` and
  `couchpotato/core/plugins/browser_test.py`
  were tracked, read like a live suite, and were collected by nothing. They are
  **relocated into `tests/unit/`, not deleted** — 24 of their 26 tests passed
  immediately and the other two were failing on a live defect. *Break:* remove
  the suffix branch; the predicate's own unit test must red. (Every other test
  of this rule injects `tracked_files`, so none of them exercises the predicate.)
- **AC-SEC-3** After the deletions, `docker build` produces an image where
  `ls /app/couchpotato/simple_healthcheck.py` and `ls /app/test_*.py` return "no
  such file". Verified against the built image: these five files ship in
  `:latest` today (confirmed by pulling it).
- **AC-OPS-12** Before `simple_healthcheck.py` is deleted, the **production**
  compose at `/var/lib/plexmediaserver/CouchPotato/` is grepped for
  `simple_healthcheck` and the result pasted into the PR. In-repo evidence is
  complete (no consumers; the Docker HEALTHCHECK at `Dockerfile:89` uses stdlib
  `urllib` against `/`); the prod file is the only unchecked consumer.

  **NOT SATISFIED, so the deletion is not taken in PR 1.** The production grep
  needs SSH to `homemedia.maeewing.com`, which this branch could not perform.
  The file is therefore RESTORED and its removal deferred to a follow-up gated
  on that one command.

  The criterion is deliberately not amended to fit what was achievable. That is
  the mistake this same spec records at AC-SIMP-1, where amending the scope
  criterion four times is what let scope control fail silently; doing it again
  here, on a criterion protecting a production healthcheck, would be the same
  error with higher stakes.

  For the record, and it is why this is a deferral rather than a blocker: the
  file is a `unittest.TestCase` carrying `#!/usr/bin/env python2` while
  importing `from urllib.request import ...` (Python 3 only). It cannot execute
  under its own shebang, so a compose `healthcheck:` invoking it would already
  be failing today. That makes the residual risk small -- but "small" is not
  the bar the criterion set, and the grep costs one command.
- **AC-SEC-5** `/getkey/` is byte-identical after this PR, and
  `grep -rn getkey` returning only `couchpotato/__init__.py` and
  `tests/unit/test_fastapi_web.py` is captured in the PR body as the standing
  evidence for PR 2's "no live consumer" premise.

### T1.4: Vacuous E2E tests: enumerate, then delete or fix · M · risk: low

**Rescoped.** The original named 2 sites and estimated S. Measured population:
**~21 tests with zero assertions outside a conditional**, across 5 files: 30 conditionals in `interactions.e2e.spec.ts` (19 of its tests assert only
`checkNoErrors`), 11 in `movie-detail.spec.ts`, 7 in `functional.e2e.spec.ts`,
5 in `settings.spec.ts`, 2 in `navigation.spec.ts`. And the named site was
wrong: `interactions.e2e.spec.ts:338` has `checkNoErrors` **outside** the
conditional. `navigation.spec.ts:75` is a true case.

Rule: **enumerate the closed list first.** For each, the choice is **delete** or
**make unconditional**: not "fix". A conditional whose precondition is
guaranteed (the seeded movie, the desktop viewport) becomes unconditional; the
rest assert both branches or go.

- **AC-SIMP-8 (decided 2026-08-03)** Two deletions, then repair the rest:
  1. **One of the two sidebar-collapse tests goes.** `navigation.spec.ts:75` and
     `interactions.e2e.spec.ts:65` assert the same behaviour. Keep
     `navigation.spec.ts:75` (made unconditional per AC-QA-39) because it is
     also the suite's only assertion of the collapse control's accessible name
     (AC-A11Y-12); delete the `interactions` one.
  2. **`functional.e2e.spec.ts` is deleted in full**: 6 tests, 7 conditionals,
     named coverage (add a movie, trailer modal, TorrentPotato test button,
     settings save) duplicated by `interactions.e2e.spec.ts` and `search.spec.ts`.
     **Precondition:** before deleting, map each of its 6 tests to the spec that
     covers the same behaviour and paste that mapping into the PR. If any test
     has no counterpart, it is repaired and kept rather than deleted: deleting
     on the assumption of duplication is how real coverage disappears.
  The remaining ~14 vacuous tests are **repaired**, not deleted. Deleting more
  aggressively was considered and rejected: without a per-test coverage check
  the saving is not worth the risk.
- **AC-QA-39 / AC-A11Y-12** `navigation.spec.ts:75-88` asserts unconditionally.
  The `chromium` project is desktop-only (`playwright.config.ts:114` ignores
  `*.mobile.spec.ts`), so the visibility guard protects nothing. That `if` also
  contains the suite's **only** assertion that the sidebar collapse control has
  an accessible name. *Break:* remove the `aria-label` from the template: the
  test must red. It cannot today.
- **AC-QA-40** `interactions.e2e.spec.ts:329` either exercises a real skip or is
  renamed. Measured cause: `mockSuggestionsCharts` (`helpers.ts:51-75`) returns a
  card with **no Skip control**, so the test burns 5 s and asserts only
  `checkNoErrors`. A test whose name promises behaviour it never touches is
  worse than no test: it closes the question.
- **AC-A11Y-7** The accessibility suite carries the same defect and is in scope:
  `accessibility.a11y.spec.ts:285-289` assigns the computed outline and never
  asserts it (so the "keyboard accessible" test says nothing about a visible
  focus indicator), and `:305` `expect(await img.getAttribute('alt')).toBeDefined()`
  **cannot fail**: verified: `expect(null).toBeDefined()` passes, and
  `getAttribute` returns `null` for a missing attribute. Assert a non-zero image
  count first, then assert the attribute is a string.
- **AC-QA-42 / AC-A11Y-3** Enforceable version (§9): a `check_test_traps.py`
  rule flagging `expect(` inside an `if (await …isVisible()/…count())` body
  under `tests/e2e/**`, with a justification-comment opt-out, proven in **both**
  directions *and* proven to fail when the opt-out is used without a
  justification. `AGENTS.md:104-106` currently asks a human lens to look for this
  every review; a rule retires that.
- **AC-QA-43** Each repaired test is proven load-bearing by removing the element
  from the template, watching it red, restoring, and hash-verifying the restore.

### T1.4b: Close the accessibility guard's own gaps · S · risk: low: NEW

Found by `lens-accessibility` while checking whether the a11y guard survives
T1.7. All are in the existing suite, all cost **zero** today (live probes of
Wanted, Available, Add, Settings, Wizard found no violations at any impact, in
either theme, and at Pixel 5 width).

- **AC-A11Y-8** `checkA11y` (`accessibility.a11y.spec.ts:37-46`) stops filtering
  by `impact === 'critical' || 'serious'` and asserts on the full WCAG-tagged
  violation list. It is the assertion for 5 of the 18 tests, and the same file
  documents the identical bug one notch tighter at `:578-591`, where an
  `impact === 'critical'` filter made the contrast test unable to fail while two
  toasts were failing 1.4.3.
- **AC-A11Y-9** `.withTags()` at `:13` gains `wcag22aa` (currently stops at
  `wcag21aa`), so 2.5.8 target-size and 2.4.11 focus-not-obscured are exercised.
  The project standard is WCAG 2.2 AA; the automated floor is currently 2.1 AA.
- **AC-A11Y-10** At least one page-level sweep runs with `cp-theme` seeded to
  `dark` via `addInitScript` **before** navigation, asserting
  `classList.contains('light') === false` so it cannot silently run in the wrong
  theme. Measured: the default with no localStorage is **light**, so every
  page-level scan today is light-only: the same blind spot that let the dark
  success toast ship at 3.30:1.
- **AC-A11Y-11** `small-screen.mobile.spec.ts:159-165` stops filtering to
  `button-name` + `target-size`, or names its ignored rule ids in an allowlist
  with a reason.

### T1.5: Pin ruff for real · S · risk: low

**Corrected: the original fix was a no-op.** Three lenses independently
concluded this. `.github/workflows/ci.yml:35` (`ruff>=0.9.0`) and `:134`
(`ruff>=0.15.16`) are unquoted shell redirections: verified by execution, the
`>` creates a file named `=0.9.0` and installs floating-latest. But
`requirements-dev.txt:8` is **also** floating (`ruff>=0.16.0`), so "pin, sourced
from `requirements-dev.txt`" relocates the problem rather than fixing it. Three
floors exist, none pinned.

- **AC-SEC-6 / AC-OPS-1 / AC-QA-44** `requirements-dev.txt` reads
  `ruff==X.Y.Z`, and both workflow lines install that exact version. Proven by
  reading `ruff --version` in the `lint` and `security-lint` job logs: the two
  must print the same version.
- **AC-SIMP-9 (amended)** T1.5 is confined to `ci.yml` (quoting + a single
  version literal), `requirements-dev.txt`, and `check_test_traps.py`. The
  `lint` job does **not** gain `pip install -r requirements-dev.txt`: that
  installs pytest/mutmut/coverage into a lint job for no benefit. **Duplicating
  one version string across two files is cheaper than any mechanism that removes
  the duplication.** No new workflow, no new job, no new script.
- **AC-OPS-5** `scripts/verify.sh` **fails** (not warns) when the locally
  installed ruff differs from the pin, printing both versions and the install
  command. Today's preflight (`:54`) only checks `import ruff`, so pinning CI
  without this creates a new "green locally, red in CI" class.
- **AC-QA-45 / AC-OPS-4 / AC-SEC-7** The new trap rule flags an unquoted
  `>=`/`>` in a workflow `pip install`, proven in **both** directions against
  the real file: `ci.yml:35`/`:134` reported; the correctly quoted
  `'pyyaml>=6.0'` at `:44` **not** reported; and a legitimate redirect
  (`echo x > file`) not reported. Regression test in
  `tests/unit/test_check_test_traps.py`.
- **AC-SEC-8** The `secrets` job is untouched: gitleaks stays at
  `zricethezav/gitleaks:v8.30.1`, config stays `.gitleaks.toml`, `--redact`
  stays, `.gitleaksignore` gains no entry.
- **AC-QA-46** No `=0.9.0` artefact was ever committed (checked). Say that in
  the PR body rather than implying a stray file exists.

### T1.6: Prod interpreter + repo hygiene · S · risk: low

- **AC-OPS-6** A unit test parses `Dockerfile`'s `FROM python:<ver>-alpine`
  (lines 10, 30) and asserts `<ver>` appears in `ci.yml`'s test matrix **and**
  equals `scripts/test-local.sh`'s default. It fails when either side is bumped
  alone. Modelled on `tests/unit/test_gitleaks_config.py`. *Break:* change the
  Dockerfile to `3.15-alpine`, watch it red, restore, `git diff` to confirm.
  This is the enforceable fix (§9): T1.6 alone fixes the instance and leaves
  the class.
- **AC-QA-47** `'3.14'` added to `ci.yml:147` and that leg is green. Local
  evidence: **1936 unit tests pass on CPython 3.14.6 in 29.0 s** and every
  requirement resolves on 3.14. Green on macOS is necessary, not sufficient: Ubuntu wheels are the residual risk.
- **AC-QA-48 / AC-OPS-7** `scripts/test-local.sh:11` moves off 3.12 to the
  production interpreter; `scripts/verify.sh:57`'s "3.10–3.13" message,
  `docs/development-process.md:506`, `README.md:7,15` and `CONTRIBUTING.md:5`
  all agree with the matrix afterwards.
- **AC-OPS-8** `fail-fast: false` retained so a 3.14-only failure is
  attributable. **No branch-protection edit is needed**: `test-summary`
  (`ci.yml:364-376`) already aggregates the matrix and is the required context.
  Say so in the PR.
- **AC-OPS-9** No CI **job** is renamed, removed or added-as-blocking. All 12
  required contexts report. If T1.7 restructures the E2E jobs, `ui-e2e-tests` /
  `accessibility` are renamed in branch protection in the same change.
- **AC-SEC-1 / AC-OPS-10** `.env` is added to `.gitignore` in the **same
  commit** that untracks it (`git check-ignore .env` exits 0 afterwards), and
  the consequence is written down: after pulling, `docker compose` no longer
  selects `docker-compose.local.yml`, so it pulls the published image and
  creates root-owned `/path/to/downloads`. One-line restore in the PR body and
  dev docs. Without the ignore entry the trap is left armed and CI can never
  catch it: the `secrets` job only sees tracked files.
- **AC-SEC-2** No history rewrite. Evidence recorded: `git log --follow -- .env`
  shows one commit, one content (`COMPOSE_FILE=docker-compose.local.yml`). A
  rewrite of `master` history is a larger risk than what it would remove.

### T1.7: E2E per-spec isolation · L · risk: **medium** (was: low)

Moved into M0 after challenge; **risk raised from low after planning**.

**Prerequisite: add `--port` to the runner** (decided 2026-08-03). `runner.py:28-41`
accepts only `--data_dir`, `--config_file`, `--debug`, `--console_log`,
`--quiet`, `--daemon`, `--pid_file`, so "a server per worker" is not expressible
today: the port comes from `config.ini`. The alternative (the seed writing a
distinct port into each data dir's `config.ini`) was rejected: it couples the
test harness to config-file internals and leaves the collision mode live for
anyone running two servers by hand.

- **AC-OPS-20** `CouchPotato.py --port N` binds N. When omitted, behaviour is
  byte-identical to today: the `config.ini` value wins, and no existing
  install changes port on upgrade. Pin both directions in a unit test.
- **AC-OPS-21** Precedence is explicit and tested: `--port` overrides
  `config.ini`; an invalid or already-bound port fails at startup **naming the
  port**, rather than falling back silently to the default. A silent fallback
  would reintroduce the shared-server coupling this task exists to remove
  (AC-QA-57) while every spec still reported green.
- **AC-SEC-16** `--port` does not change the bind address. The server binds
  whatever it binds today (`runner.py:253,258`); this argument selects a port,
  not an interface, and must not become a way to expose an instance more widely
  than `config.ini` would.
- **AC-SEC-16b** *(added at review 2026-08-06, see spec gap 10)* AC-SEC-16 was
  satisfied and the exposure happened anyway: `host` defaults to `0.0.0.0`, is
  absent from the settings list, and has no CLI surface, so a `--workers=N` run
  opens **N unauthenticated instances on the LAN**, each with a generated
  `api_key` and no password (`get_current_user` returns `True` when neither is
  set). Every per-worker server binds **loopback only**, fixed in the **seed
  script** rather than by adding `--host` — widening the CLI to fix this would
  defeat AC-SEC-16 itself. The write is idempotent and must **not** overwrite a
  `host` the operator already set.
- This is the second production change in PR 1 (with T1.8) and is reflected in
  `AC-SIMP-1`.

**Data-loss hazard: this is why the risk moved.** `CouchPotato.py:53` gates on
truthiness, so `--data_dir=` (empty) falls through to `Env.setting('data_dir')`
and then `getDataDir()`. Measured neighbours: `.config` 68 MiB (live database),
`test_data/` 71 MiB (gitignored, **git-unrecoverable**). `verify.sh:97,106,115`
already `rm -rf` sibling paths in the repo root.

- **AC-DATA-24** The run **fails loudly, before starting a server**, when a
  derived data dir is empty, is not under the designated scratch root, or whose
  basename does not begin with `.e2e`.
- **AC-DATA-25** Every `rm -rf` goes through **one guarded helper**, unit-tested
  with hostile inputs: `''`, `'/'`, `'.'`, `'..'`, `'~'`, `'.config'`,
  `'test_data'`, a path containing a space, and a **symlink pointing at
  `test_data/`**. Each refused. `scripts/backup.sh:244-301` documents this exact
  class on this repo and is the shape to copy.
- Prefer siting the dirs under `os.tmpdir()`, out of the repo root entirely.
- **AC-SEC-9** Dirs are named `.e2e-<spec>-data/`, **not** `.e2e-data-<spec>/`.
  Verified: `.gitignore:57` (`.e2e-*data/`) and `.gitleaks.toml:58`
  (`^\.e2e-[^/]*data/`) both require the name to **end** in "data". The existing
  `.e2e-data-mobile` / `.e2e-data-a11y` match neither, which is why
  **`make check-secrets` is red on master today** (3 findings, verified by
  running it). The naming choice decides whether that becomes ~30. Rename the
  two existing dirs to the same shape and delete the now-redundant hardcoded
  `.gitignore` lines. Testable: after a full run,
  `for d in .e2e-*; do git check-ignore -q "$d/config.ini" || echo LEAKABLE: $d; done`
  prints nothing **and** `make check-secrets` exits 0 with all dirs present.
- **AC-SEC-10** `.dockerignore` gains `.e2e-*`. Verified: it excludes `.config/`
  but not the E2E dirs, and `Dockerfile:72` copies the whole context, so a local
  `docker build` (the normal `docker-compose.dev.yml` path) bakes a live
  `api_key` into an image layer.
- **AC-SEC-11** `.config/config.ini` is byte-identical (sha256) after a full
  run, and no new `config.ini` with a non-empty `api_key` appears in `$HOME` or
  `/tmp`.
- **AC-QA-50** **A direct test of the property, not just a green suite.**
  Spec A mutates global singleton state (create/delete a category, mark the
  seeded movie done); spec B asserts the pristine state. Both orders, in
  parallel, pass. This fails today and is the only thing that proves isolation
  rather than luck.
- **AC-QA-50b** *(added at review 2026-08-06, see spec gap 11)* Spec B has a
  **happens-after edge on spec A**. As originally specified this was a race:
  Playwright gives each spec file to a different worker and runs them
  concurrently, so B reached its assertion before A had created anything and
  passed against an empty world — a green that would survive isolation being
  removed entirely. B must also distinguish "A ran on a different server"
  (the property under test) from "A ran on *this* server" (both halves on one
  worker, which proves nothing) and fail differently for each. *Break:* run B
  alone; it must red naming the missing partner, where it previously passed.
  Run the pair at `--workers=1`; it must red naming the misconfiguration.
- **AC-QA-52 / AC-A11Y-2** Acceptance bar: **≥10 consecutive full parallel runs
  green**, each with a freshly created data dir, driven by a script that stops
  on first red and prints the failing spec and worker assignment. Hand-counted
  runs do not qualify: n=3 and n=4 both came back green before n=5 found the
  flake (`docs/technical-debt.md:186`). **Green must be measured by test count,
  not exit code:** `0 skipped` and a passed-count equal to
  `--list` total. Measured during planning: at `--workers=4`, run 2 of 3 exited
  **0** while reporting `1 skipped, 17 passed`: the skipped test was the only
  axe scan of a filtered movie-detail page, and the seed data was present and
  identical to the passing run, so the cause was contention, not seeding.
- **AC-A11Y-1** No accessibility spec converts a missing precondition into a
  skip. `accessibility.a11y.spec.ts:142-150` asserts
  `expect(releasesLoaded, '<seed guidance>').toBe(true)`: FAIL, don't skip, the
  pattern `movie-detail.spec.ts:55` already documents. Proven by running the
  a11y project against an unseeded data dir and watching it **red**.
- **AC-A11Y-4 / AC-QA-56** A retry-pass cannot green the gate. **Decided
  2026-08-03: CI keeps `retries: 2` and adds `--fail-on-flaky-tests`** (present
  in the installed Playwright 1.62.0) to every Playwright invocation in
  `ci.yml`: the E2E, mobile and `accessibility` jobs, and in `verify.sh`.
  Dropping retries to 0 was rejected: it would red a PR on a genuine
  infrastructure blip. This keeps that resilience while making a fail-then-pass
  **red instead of flaky-green**, so AC-QA-52's ten runs stay measurable on the
  machine that matters. `accessibility` is a required check, so its exit code is
  the whole gate.
  *Prove it load-bearing:* introduce a deliberately flaky test (fails on first
  attempt, passes on retry), confirm the job reds, then remove it.
- **AC-QA-53** At least 3 of the 10 runs use a different worker count (2 / 4 /
  8). Playwright has no shuffle; worker count changes the file→worker
  assignment, which is the variable that produced the coupling. Ten runs of an
  identical schedule prove the schedule, not the isolation.
- **AC-DATA-26 / AC-QA-54** The run **fails** if a per-spec dir already exists
  at start. Precedent in-repo: `verify.sh:88-97` records a gate that flipped
  green→red purely from an inherited `.e2e-data`.
- **AC-QA-55** Parallel wall-clock ≤ the measured serial baseline of **4.0 min**
  (142 chromium tests, measured during planning; the debt doc's ~4.1 min
  corroborates). Above that, the isolation cost exceeded the parallelism gain
  and the trade is re-argued, not shipped.
- **AC-SIMP-12** If the isolated suite is not faster, `workers: 1` **stays** and
  only the isolation lands. Parallelism is a measured benefit or it is dropped.
- **AC-QA-58** The harness fails with "the application under test exited" rather
  than 30 tests reporting `ERR_CONNECTION_REFUSED`. Measured during planning:
  the server was SIGKILLed at test 112 of 142 and every downstream failure named
  a URL rather than the cause.
- **AC-QA-58b** *(added at review 2026-08-06, see spec gap 12)* The same holds
  **after** readiness, which is when the planning measurement above actually
  happened. The worker watches its server for the whole run, fails the run if it
  exits, and **retains the application log** at a named path — it previously
  lived only in a closure and was discarded at teardown, so the one artefact
  that could explain a mid-run failure was the one thing never kept. *Break:*
  kill the listening server mid-test; teardown must error naming the signal, the
  log file must exist, and the **process exit code** must be non-zero (checked
  explicitly: Playwright's summary line still reads "1 passed").
- **AC-A11Y-5** Isolation applies to the CI `accessibility` job too, which today
  starts its own server by hand (`ci.yml:345-350`, `--data_dir=.config`) and
  never reads `CP_E2E_DATA_DIR`. **`playwright.config.ts` disables `webServer`
  when `CI` is set**, so isolation implemented only there leaves CI running
  today's shared-state suite while local runs the isolated one: both green,
  testing different things (AC-OPS-15).
- **AC-OPS-15** *(text supplied at review 2026-08-06; it was cited above as
  satisfied while having no definition anywhere in this spec, which nobody can
  verify)* **The local gate and CI run the same suite the same way.** Every
  Playwright invocation in `scripts/verify.sh` has a counterpart in
  `.github/workflows/ci.yml` with the same project, the same worker count and
  the same `--fail-on-flaky-tests`, and neither file special-cases
  `process.env.CI` to change what is executed. *Break:* remove one project's
  invocation from either file; hard rule 2 says the local gate mirrors CI, and
  a divergence must be visible rather than inferred from two green ticks.
- **AC-OPS-16** A failed seed is **red, not skipped**. Today **two** seed steps
  swallow failure into `:warning:` with `continue-on-error: true`
  (`ci.yml:253` and `:343` on `master`), and the workflow's own message says
  tests "will skip instead of running". The third seed step, `:285`, does NOT:
  it carries no `continue-on-error` and its message already says "mobile tests
  will fail loudly", so it is the shape the other two should copy rather than a
  third instance of the defect. An earlier version of this line listed all
  three, which would have sent the implementer to "fix" the one that was
  already right. Per-spec
  seeding turns one such chance into fifteen.
- **AC-OPS-17** After a completed **and** an interrupted `make verify`,
  `pgrep -f CouchPotato.py` is empty. A port already in use fails naming the
  port and the spec, not a 120 s `webServer` timeout.
- **AC-SIMP-11 (amended 2026-08-05)** Confined to `playwright.config.ts`, at
  most one new fixture file, `ci.yml`, `scripts/seed_e2e_data.py`, plus the
  AC-DATA-24/25 safety helper and its tests (`scripts/e2e_worker_data.py` +
  `tests/unit/test_e2e_worker_data.py` -- new files, since no existing file
  owns rm-rf safety), and `tests/e2e/isolation-a-mutate.spec.ts` +
  `isolation-b-assert.spec.ts` (AC-QA-50's direct proof; see AC-SIMP-6). No
  new npm dependency, no new config file. Both `test.describe.configure({
  mode: 'serial' })` lines and the ~40-line `workers: 1` rationale block
  (`playwright.config.ts:47-86`) are **deleted**, not amended: it argues for
  a decision this task reverses. `verify.sh` and `couchpotato/core/helpers/
  variable.py` (`removePyc`, see AC-SIMP-1) also touched -- not in the
  original file list, both load-bearing for T1.7 to work at all.
- **AC-SIMP (new)** Delete the `firefox` and `webkit` project entries
  (`playwright.config.ts:117-125` on `master`; the `:105-115` written here
  before is the **chromium** entry, which must NOT be deleted) as the
  **first** commit of T1.7. Verified
  dead: only `chromium`, `mobile-chrome` and `accessibility` are ever invoked,
  and CI installs chromium only. Deleting them shrinks the task before it starts.
- **Land T1.7 as the last commit of PR 1**, and take the ≥10-run measurement
  against a tree where only T1.7 changed. As written those runs would
  simultaneously validate three test deletions, a spec rewrite, a new matrix
  entry and a CI topology change: a red run would have seven candidate causes
  and the evidence the AC buys becomes uninterpretable. This does not split the
  PR and does not let PR 2 start sooner, so it is consistent with decision 4.
- **T1.7a (seed fixture) lands first** (decided 2026-08-05). The flake below
  blocks T1.7's acceptance bar, so the seeded movies are separated first: the
  already-`done` release moves onto its own movie, so the Wanted-page specs keep
  an active one. Test-fixture change only, no production code, which keeps PR 1
  in character. The restatus timing in `searcher.py` is the root cause but was
  rejected as the fix here: it is production code on the download path PR 3 also
  edits, and it does not belong in a test-focused PR.
- **A second flake source exists, independent of spec coupling** (found during
  T1.4, 2026-08-05). The app's own `app.load` to `searchAll` restatus pass can
  promote a seeded movie straight to `done` mid-run, which drops it out of the
  Wanted page's server-side `status=active` query. Both seeded movies carry an
  already-`done` release deliberately, for `release_controls.spec.ts`. Measured
  at roughly 1 run in 2 during T1.4. The old vacuous conditionals absorbed this
  silently forever; repairing them turned it into a loud, rare failure, which is
  the correct outcome but means **T1.7's ten green runs cannot be reached by
  isolation alone**. Fix the seed fixture or the restatus timing first, or the
  ten-run bar will be chasing a defect that per-spec data dirs cannot remove.
  This is pre-existing app behaviour, not a regression from this PR.
- **Note on implementation:** Playwright has **no per-spec primitive**. The
  natural implementation is per-**worker**, which is what
  `docs/technical-debt.md:184-186` and `playwright.config.ts:79-81` both
  actually recommend. Do not build a per-spec abstraction to satisfy a phrase in
  this spec when per-worker is what the tool supports.

### Simplicity constraints (verified by the orchestrator against the diff)

`lens-simplicity` runs at planning only; these are checked at review by reading
the diff, not by an agent.

> **OUTCOME: AC-SIMP-1, 4, 5 and 6 FAILED. Read this before auditing them.**
>
> Measured against `master` at the close of PR 1:
>
> | Criterion | Required | Actual |
> |---|---|---|
> | AC-SIMP-1 | only the files listed below under `couchpotato/` | **9 unlisted modifications** (`db/migrate.py`, `db/sqlite_adapter.py`, `logger.py`, `plugins/browser.py`, `plugins/manage.py`, `settings.py`, `softchroot.py`, `templates/add.html`, `templates/partials/settings/profiles.html`) **and 3 unlisted deletions** (`core/plugins/browser_test.py`, `core/settings_test.py`, `core/softchroot_test.py`) |
> | AC-SIMP-4 | no new file under `scripts/` | `scripts/e2e_worker_data.py` added |
> | AC-SIMP-5 | `git ls-files \| wc -l` lower after than before | 650 → 656 |
> | AC-SIMP-6 | 5-6 named new files under `tests/` | 19 |
> | AC-SIMP-7 | `if (await` count strictly lower | 63 → 34. **PASSED** |
>
> Every row is scored at the branch tip with
> `git ls-tree -r <ref> --name-only | wc -l` and
> `git diff --name-status master...HEAD`. Re-score the WHOLE table when the
> branch moves: an earlier version had AC-SIMP-5 at 653 (the count one commit
> back) sitting beside an AC-SIMP-6 scored at the tip, so two rows in one
> table measured different commits.
>
> The criteria below are left exactly as written rather than amended to fit,
> because amending them is what broke them: AC-SIMP-1 was amended four times,
> each amendment individually defensible, and the mechanism designed to catch
> scope growth was edited away by the growth it existed to catch. A criterion
> that moves whenever it would fail measures nothing. The lesson is recorded
> at line ~1075 in the PR 2 section as "PR 1's allowlist was the right shape
> and failed because amending it was free" -- but a reader auditing PR 1
> arrives *here*, 310 lines earlier, so the verdict belongs here too.
>
> What actually grew the scope is worth naming, because most of it was not
> feature creep: `sqlite_adapter.py` is a production concurrency defect found
> by reading the server log this PR started keeping, and `softchroot.py` is a
> path-traversal fix made reachable by repairing the file browser. Those are
> the precedence order working as intended (irrecoverable data loss and
> security outrank a no-runtime-change constraint). The honest failure is
> that nothing forced the trade-off to be *declared* at the moment it was
> taken. `AGENTS.md` requires changes near `_query_index` to be reviewed as
> new work rather than as corrections; that applied here and was not invoked.

- **AC-SIMP-1 (amended)** Under `couchpotato/`, the diff contains only:
  (a) `core/media/movie/searcher.py`: the `:419`/`:429`/`:433` fallback,
  (b) `core/plugins/renamer/mover.py`: the three T1.8 fixes,
  (c) `runner.py`: the `--port` argument only,
  (d) `core/media/_base/media/main.py` and/or `core/plugins/release/main.py`:
  the `has_releases` row-shape fix only (T1.9, added 2026-08-05),
  (e) `ui/__init__.py`: `partial_movies`'s `with_releases` default fix only
  (T1.9 follow-up, added 2026-08-05 -- was missing from this list, corrected
  here rather than left silently uncovered),
  (f) `core/helpers/variable.py`: `removePyc`'s `os.listdir` guard only
  (T1.7, added 2026-08-05 -- concurrent per-worker CouchPotato.py processes
  race on cleaning the shared `__pycache__` tree; reproduced directly with
  `--workers=3`, one worker crashed before binding a port),
  (h) `ui/templates/wanted.html`: the redundant `x-init="init()"` removal
  only (T1.7, added 2026-08-05 -- a double `init()` call double-registered
  the arrow-key handler, which T1.7's acceptance runs made deterministic
  once the seed grew from 1-2 to 3 Wanted movies; blocks the local gate
  hard rule 2 requires, so this could not be left red and deferred),
  (g) whole-file deletions of `simple_healthcheck.py`, `integration_test.py`,
  `environment_test.py`. **Any other modified file under `couchpotato/` fails.**
  *(Amended 2026-08-03: the original allowed only `searcher.py:419`. The
  precedence order puts irrecoverable data loss above the no-runtime-change
  constraint: see T1.8, and `--port` was added to scope as a T1.7
  prerequisite. Amended again 2026-08-05 for (e), (f) and (h).)*
- **AC-SIMP-2 (amended 2026-08-06)** `requirements.txt` unchanged;
  `package.json` dependencies and devDependencies unchanged. No new runtime or
  npm dependency.
  *(Amended 2026-08-06: `requirements.txt` DID change -- `cryptography`
  49.0.0 → 50.0.0 and `pyOpenSSL` 26.3.0 → 26.4.0, coupled because 26.3.0 caps
  `cryptography<50`. CVE-2026-69247 is a fixable HIGH in a shipped image and
  the `docker` job is a required check, so the precedence order puts it above
  the no-runtime-change constraint -- the same reasoning AC-SIMP-1's own
  amendments already apply. Recorded here rather than left silent: a
  constraint that quietly stops matching what shipped is the thing that made
  AC-SIMP-1 fail to catch anything, and an amendment that is WRITTEN DOWN is
  the opposite of one made by editing the criterion away. No devDependency or
  npm change; `ruff>=0.16.0` → `ruff==0.16.0` in requirements-dev.txt is a
  tightening of an existing pin, not a new dependency.)*
- **AC-SIMP-3** No new configuration setting: zero additions to the settings
  lists in `core/_base/_core.py`, zero new `os.environ` / `Env.setting` reads
  under `couchpotato/`. *(One agreed exception: the `--port` CLI argument added
  as a T1.7 prerequisite. It is a command-line override, not a stored setting: it must not appear in the settings UI or be written to `config.ini`.)*
- **AC-SIMP-4** No new file under `scripts/`. Every new guard lands inside the
  existing `scripts/check_test_traps.py`.
- **AC-SIMP-5** Net-negative in tracked files: ≥10 deletions, and
  `git ls-files | wc -l` lower after than before.
- **AC-SIMP-6 (amended 2026-08-05)** New files under `tests/` limited to
  `tests/unit/test_renamer_mover.py`, `tests/unit/test_searcher_correct_release.py`,
  at most **one** Playwright fixture file, `tests/unit/test_e2e_worker_data.py`
  (the AC-DATA-25 safety helper's own tests -- "the safety helper and its
  tests" was explicit scope for T1.7), and **two** Playwright spec files,
  `tests/e2e/isolation-a-mutate.spec.ts` + `isolation-b-assert.spec.ts`
  (AC-QA-50's direct isolation proof -- "Spec A" and "Spec B" cannot be
  expressed as `describe` blocks in one file and still prove separate-worker
  scheduling; splitting them is what makes the file-naming/sort-order
  mechanism in their own header work at all). No new `conftest.py`, no new
  shared helper module for the mover tests: they instantiate the mixin
  directly, as `test_renamer_cleanup_safety.py` already does.
- **AC-SIMP-7** In every touched `tests/e2e/*.spec.ts`, zero test bodies remain
  wholly wrapped in a visibility/count conditional; the summed
  `grep -c "if (await"` is strictly lower after than before; no new such
  conditional is added.
- **AC-SIMP-13** `pytest.ini`'s `--ignore=tests/e2e/test_real_data_migration.py`
  is removed in the same diff that deletes the file. No dead reference to a
  deleted path survives (`grep -r` for each deleted filename returns only
  `specs/`).
- **AC-SIMP-14** No new file under `docs/`. `docs/technical-debt.md:149-186`
  (both E2E entries, resolved by T1.7) is deleted or collapsed to a one-line
  resolved note: a third entry is not added alongside them. Also correct
  `:118`, which claims `make check-secrets` "reports clean"; it is red.

### Vetoes and trade-offs

| Item | Raised by | Decision | Rationale |
|---|---|---|---|
| "Pin ruff sourced from `requirements-dev.txt` rather than duplicated" | simplicity (veto), security, operability | **Vetoed** | No criterion requires single-sourcing; the criterion is "CI does not install floating ruff". Duplicating one version string across two files is cheaper than a mechanism that removes it |
| Delete `test_startup_local.py` | simplicity, QA | **Vetoed** | Untracked and gitignored (`.gitignore:33`). Deleting untracked files is not the implementer's business |
| PR 1 changes no runtime behaviour | plan (original) | **Overridden** | Three verified data-loss defects in `moveFile`. Precedence #1 (irrecoverable loss) outranks a self-imposed scope constraint. See T1.8 |
| T1.4 "sweep it through" | simplicity, QA | **Rescoped** | 21 sites, not 2. Enumerate the closed list; most are deleted, not repaired |
| Wire `tests/integration/` into CI | simplicity, QA, data | **Accepted, conditioned** | Measured 38 tests / 2.4 s, no fixing required, but 7 tests skip permanently in CI. Conditioned on AC-QA-35 |
| Merge state-mutating specs into one serial file (the S-effort alternative to T1.7) | simplicity | **Rejected with evidence** | The mutating set is larger than three files: `movie-detail.spec.ts` and `small-screen.mobile.spec.ts` also mutate. Merging three leaves the coupling. Recorded so it is not re-proposed |
| mypy gate (T6.7, PR 6) | simplicity | **Veto overridden** (Scott, 2026-08-03) | Simplicity's objection stands on its own terms: no defect has been identified that mypy would have caught. Kept anyway, scoped to `core/db/*`, as a **preventive** gate: that package is the highest-consequence code in the repo and already typed, so the gate starts green and ratchets rather than migrating. Recorded as a deliberate override, not an unanswered veto |
| Fix `os.popen` injection at `moveFile`'s `os.name == 'nt'` branch (`os.popen`/`icacls`) | security | **Deferred to PR 3** | Windows-only, gated on `ntfs_permission`. PR 3 already edits `renamer/`. Recorded in the T1.1 skip reason so it is not silently uncovered |
| Fix `extractor.py:174` (`cleanup` passed into the `use_default` slot) | QA | **Deferred to PR 3** | Real argument-position bug coupling two unrelated settings, but not on PR 1's path |
| Move the renamer re-entrancy lock (T5.4) ahead of PR 4 | data | **Accepted** | Two concurrent moves to one destination destroy a file and both return `True`. PR 4 adds a delete to that path: shipping the delete before the lock turns "one download lost" into "the library copy lost too" |

### Spec gaps found at planning

Findings with no acceptance criterion behind them: each is a planning lens
catching something the *plan* missed, which is the signal the harness is meant
to produce:

1. **`make check-secrets` is red on master today** (3 findings, verified). Not
   caused by this PR; discovered while planning it. `docs/technical-debt.md:118`
   claims it reports clean.
2. **Five dead files ship in the published `:latest` image**: verified by
   pulling and listing.
3. **`.dockerignore` omits the E2E dirs**, so a local build bakes a live
   `api_key` into a layer.
4. **The a11y suite's alt-text assertion cannot fail** (`expect(null).toBeDefined()`
   passes), and `checkA11y` discards non-critical/serious violations: the same
   bug the file documents at `:578-591`.
5. **Every page-level axe scan runs light-theme only**; dark has no page-level
   scan at all.
6. **`CouchPotato.py` has no `--port`**, so per-worker servers are not
   expressible: a capability gap the plan assumed away.
7. **Concurrent `moveFile` calls to one destination** destroy a file and both
   report success (forced interleave; real-world reachability inferred from the
   unlocked check-then-set at `renamer/main.py:72-79`).

### Spec gaps found at review (PR 1)

Findings the review cycle raised that no `AC-` covers. Recorded because that
list is how the harness improves rather than merely runs:

8. **A repaired `has_releases` filter widens what a destructive path deletes.**
   `AC-DATA-*` covered the filter's correctness and `manage.py`'s cleanup was
   not in scope at all, so nothing asked the obvious follow-up: which *other*
   callers change behaviour when a filter that never filtered starts
   filtering. The answer was `media.delete(delete_from='all')` admitting
   `active` (upgrading) movies, in an unattended scan. **A criterion of the
   form "enumerate every caller of a predicate whose behaviour this change
   alters" belongs in the template**, not just in this spec.
9. **The orphaned-test rule was written against one of pytest's two naming
   conventions.** `AC-QA-38` specified what the rule keys *on* (runner
   invocations, not `testpaths`) and was right about it, but said nothing
   about what counts as a test file. Three `*_test.py` files under
   `couchpotato/` were invisible to it, and one was sitting on a live Python 3
   port defect (`FileBrowser.view()` calling `len()` on a `map`). A guard's
   *predicate* needs a criterion as much as its *anchor* does.
10. **Per-worker servers bind `0.0.0.0`.** `AC-SEC-16` correctly stopped
    `--port` from widening exposure, and was satisfied — while the harness it
    enabled opened N unauthenticated instances on the LAN, because the host
    comes from a setting with no CLI surface at all. The criterion guarded the
    argument that was added instead of the exposure that resulted.
11. **The isolation proof had no happens-before edge.** `AC-QA-50` asked for a
    direct proof of isolation and got two specs that Playwright runs
    concurrently, so the asserting half regularly ran first and passed against
    an empty world. A criterion asking for a proof between *parallel* actors
    has to say how they synchronise, or it specifies a race.
12. **Nothing watched the application under test after startup.** `AC-QA-58`
    covered the server exiting *before* readiness. A server dying mid-run —
    the same failure, ten seconds later — had no criterion, no diagnosis and
    no retained log.
13. **`AC-DATA-23` was written as a conditional** ("if the round-trip
    migration test is kept"). It was kept, and the criterion was still
    unwritten at review. Conditional acceptance criteria have no owner.

14. **`AC-SIMP-7` measured a proxy, and the proxy moved without the property.**
    It counted `if (await` occurrences in `tests/e2e/**` as a stand-in for "no
    test asserts nothing". The count fell 63 → 34 while roughly 13
    assertion-free tests survived, because moving one weak assertion outside
    the brace satisfies the count. What T1.4 wanted was "every touched test
    asserts a property named in its own title", which is not expressible as a
    diff-level count. The survivors are recorded in `docs/technical-debt.md`
    rather than being reported as done.
15. **A criterion can guard the implementation instead of the exposure, twice
    in a row.** `AC-SEC-16` guarded the `--port` argument while `host` did the
    widening. `AC-SEC-16b` was written to fix that and then guarded the
    `_bind_to_loopback` helper while the call site went untested: two review
    lenses independently deleted the call and watched the whole suite pass.
    The criterion shape that catches both rounds is **"the guard is proven at
    the call site that makes it load-bearing, not only at the function that
    implements it"**. Worth promoting into
    `~/.claude/templates/SPEC-TEMPLATE.md`.
16. **`AC-QA-11` asks for a caller-level proof that cannot exist.** It requires
    T1.8 fix (a) to be demonstrated through `_moveRenamedFiles`, but
    `renamer/main.py:154-157` refuses any pre-existing `dst` before `moveFile`
    is reached, so the caller can never drive the branch. Amended: fix (a) is
    proven at the unit level, and the file says so in
    `TestCallerLevelDataLossGuards`'s own comments rather than quietly renaming
    the test. (Cited by symbol, not line: the first draft of this gap cited a
    line range that three inserted tests had already shifted by ~90 lines,
    which is the failure mode section 7 warns about.)

### Spec gaps found at PR 1's second review round

17. **Three production security/correctness changes shipped with no AC.** The
    softchroot traversal refusal, the sqlite connection serialisation, and the
    `withStatus` `with_doc`/types fix are all production behaviour changes made
    in response to review findings, and none has a criterion. `AC-SEC-16b` and
    `AC-QA-38b` were written when the same thing happened earlier in this PR;
    these were not. **A review-driven production change needs an AC as much as
    a planned one does** -- otherwise the second review round has nothing to
    verify against and simply re-derives it.
18. **No criterion states "no method touching the connection is left
    unsynchronised".** The enumeration was done by hand, twice, by two
    different lenses. That is exactly the kind of property a mechanical check
    should own, and its absence is why `close()` was missed on the first pass.
19. **Uploading the application log as a public CI artefact is a new
    disclosure surface with no AC** saying what is permitted to appear in it.
    What was actually verified is narrower than the comment claimed: the app's
    own api_key is redacted in records emitted through logging handlers, while
    direct `print()` paths and credentials in URL userinfo or path segments are
    not filtered at all. There are none in the E2E environment, which is the
    only reason this is safe today.
20. **`AC-QA-43` ("each repaired test proven load-bearing") has no mechanism
    behind it, and three tests written to satisfy this PR's own review were
    incidentally passing** -- the interrupted-migration probe, the mixed
    read/write concurrency hammer, and the repaired text-filter test. Each was
    caught only because a lens ran a mutation the author had not. The criterion
    should say **who** runs the mutation and that the result is recorded, not
    just that it happened.
21. **A shared helper on the most destructive path shipped with no AC.**
    `_discard_partial_destination` has three call sites on the renamer's
    delete path and was verified only by tests written after it. Gap 17 listed
    three review-driven production changes with no criterion and missed this
    one, which is the fourth and the most dangerous. Now `AC-DATA-10b`.
22. **A criterion can be left pinning the behaviour its own fix inverted.**
    `AC-DATA-10` accepted destination-poisoning as known behaviour; round 2
    fixed the code and the test and left the criterion saying the opposite.
    The spec is what the review cycle verifies against, so a later round would
    have filed the fix as a regression. **When a review finding inverts an
    AC, amending the AC is part of the fix, not follow-up.**

### Spec gaps found at the third to sixth review rounds

23. **CLOSED at the seventh round.** ~~`AC-QA-42` pins Rule 6's semantics but
    not its robustness across spellings.~~ The corpus is checked in at
    `tests/unit/rule6_guard_corpus.py` and scored by a parametrised test, with
    the wrong-answer count of every previous spelling recorded in its
    docstring, re-derived at round 8 against the real historical files
    rather than reconstructions (shipped 0/30; the seven shipped versions
    score 1, 2, 3, 5, 16, 16, 17). It
    earned its place on the first run by catching a false positive no
    individual test could see. Original text:
    **`AC-QA-42` pins Rule 6's semantics but not its robustness across
    spellings.** The same function regressed in four consecutive rounds, each
    time on a formatting shape rather than on the rule's meaning, and each
    round's fix was validated by one ad-hoc test for the shape that round
    happened to notice. What closes it is a **checked-in, table-driven corpus
    of guard spellings with expected verdicts**, so any routing edit is scored
    against all of them at once instead of against the last bug.
24. **A review-driven REMOVAL needs an AC as much as an addition.** Round 5
    removed `PrivacyFilter`'s re-entrancy guard, correctly, with nothing
    stating the property now relied on: *no shared mutable state gates
    redaction*. This is the third recurrence of gap 17's shape after
    `AC-SEC-16b` and `AC-QA-38b` were written for exactly it.
25. **Nothing says how a loop precondition must be written.** Round 3 added
    them, round 4's version was a flake, round 5 converted two to polls and
    put the wrong justification on one. One line would have prevented all
    three: *a precondition over asynchronously rendered content polls; over
    server-rendered content it asserts an exact count.*
26. **`AC-QA-21`'s "under 2 s" has no mechanical enforcement.** Measured
    0.56 s to 1.89 s across four runs; the worst is within 6% of the bar and
    nothing fails if it crosses.
27. **A deferral recorded in prose is not a guard, and a recorded REMEDY can
    itself be a defect.** Round 5 deferred the `moveFile` composite class with
    a documented remedy sketch. Round 6 implemented that sketch literally and
    measured that it **deletes the download**: it accepted size equality as
    proof of success, which this repo already carries an `xfail(strict=True)`
    against (`AC-DATA-4`), and returning success authorises `_moveRenamedFiles`
    to delete the source. The deferral is now an `xfail(strict=True)` that
    XPASSes the day it is closed, and the remedy carries the two constraints
    any replacement must satisfy. **A deferral needs a failing test and its
    remedy needs the same scrutiny as code**, because the next person will
    implement it exactly as written.

**PR 1 acceptance:** `make verify` green **and `make check-secrets` green**;
every new test proven load-bearing (break, watch fail, `git diff`-confirm,
restore); the T1.8 fixes proven at the `_moveRenamedFiles` caller level; CI
green on the 3.14 matrix leg; no tracked test file outside the executed roots;
T1.1 green under `./scripts/test-local.sh` (Alpine); E2E suite green over ≥10
parallel runs measured by **test count**, at ≥3 different worker counts, with
retries disabled.

---

## PR 2: M1a: Authentication and web-surface security

**Goal:** close every finding where an unauthenticated request reaches something
it should not.

**Risk note:** this PR changes access behaviour on a live instance. Take
`./scripts/backup.sh` and note the current `config.ini` auth state *before*
deploying it. Recovery path (edit `config.ini`, restart) must be in the release
notes. Settings live in `config.ini`, not `settings.conf`.

### PR 2 planning cycle, 2026-08-06: what changed

Four lenses ran (security, QA, operability, simplicity). Every task below moved.
Three findings are **Critical** and two of them would have shipped a fix that
fixes nothing, which is the T1.5 failure repeating.

**Verified by the orchestrator, not taken from the reports:**

1. **The `auth_required` tri-state does not work.** All three lenses found it
   independently. `registerDefaults` materialises the literal `auth_required =
   None` into `config.ini`, and `Env.setting`'s own default is `''`, so the
   natural call returns falsy and auth stays off on every install, silently.
   The tri-state only round-trips via a `ValidationError` swallowed per auth
   check. **Use a plain `{'default': 0}` plus a one-shot startup migration.**
2. **A `sessions` table would brick login on every existing install.**
   `SQLiteAdapter.open()` runs no DDL, so a table in `schema.sql` reaches fresh
   installs only and the first login raises `no such table`. Store sessions as
   `documents` rows with `_t = 'session'`: zero DDL.
3. **A session lookup reaching `_query_index`'s generic branch authenticates any
   cookie.** Executed: with two session documents present,
   `db.get('session', 'TOKEN_B')` returned a **media** document, because the
   `else` branch discards the key. `release_download` is a live example of
   exactly that shape. This repo has shipped this defect twice.
4. **Passwords set through the UI or wizard are stored as unsalted MD5.**
   `_core.py:57` wires `setting.save.core.password` to `md5Password`. The
   comment at `variable.py:143` claiming "New passwords are always bcrypt" is
   false; bcrypt is reached only by the login-time upgrade, and this cohort has
   never logged in. `scripts/backup.sh` copies `config.ini`. **New task.**
5. **`auth_required` on with a blank password accepts any password** (executed:
   `POST /login/` issues a cookie for arbitrary credentials). T2.1 would create
   a state that looks protected and admits everyone.
6. **T2.6's Synology fix closes nothing.** `synology.py:110-111` strips the
   scheme and hardcodes `http://`, so `verify=False` at `:140` is unreachable
   on an http URL and removing it changes no observable behaviour.

**Vetoes accepted from `lens-simplicity`** (planning-only, so these stand unless
an owning lens supplies a criterion): the sessions table becomes an HMAC-signed
cookie with a rotating secret in the existing property store (L to S, no schema);
the SSRF private-address guard is **deleted**, not deferred, because every
default downloader points at `localhost` and Jackett is a LAN host, so the guard
would break downloads, and `belongsTo` requires a host that is a substring of a
hardcoded film-site pattern; CSP defers until PR 5 removes the Tailwind CDN;
`/getkey/` is **deleted rather than gated**.

**Scope mechanism (AC-SIMP-31).** PR 1's allowlist was the right shape and
failed because amending it was free. PR 2's may be amended **once**; a second
file leaves for a follow-up PR unless it is precedence tier 1-3 **and** already
on an allowlisted path. Countable at review.

**Highest-value single criterion**, from both security and QA: a **route
inventory test** asserting every route either carries the auth dependency or is
in an explicit public allowlist. T2.2 fixes one endpoint; this fixes the class,
and the class is how `/getkey/` came to exist.

**Before PR 2 is written**, read production's actual `username`/`password` state
into this spec. The cohort this PR protects is also the cohort that has never
typed its password, because the server never asked.

### T2.0: Make `Settings.save()` atomic · S · risk: **Critical** — NEW

Found by `lens-operability` during PR 2 planning (2026-08-06), verified by
reading the code. `core/settings.py:236-238` is:

```python
def save(self):
    with open(self.file, 'w', encoding='utf-8') as configfile:
        self.p.write(configfile)
```

Truncate-then-write, no temp file, no rename. `Env.setting(attr, value=...)`
calls it unconditionally (`environment.py:71`), and **PR 2 is what makes this
fire**: forcing a first-ever login on installs that never logged in triggers
the legacy-md5-to-bcrypt rehash at `__init__.py:277-278` and `:306-307`, each
of which rewrites the whole file.

If the process dies or the volume fills mid-write, `config.ini` is truncated:
the password, the `api_key` and every downloader and notifier credential go in
one step, and the instance restarts as a fresh public install with a new key.
`config.ini` is also the documented lock-out recovery file, so the failure
destroys the remedy along with the configuration.

Precedence tier 1 (irrecoverable loss) outranks everything else in this PR, and
the fix is roughly eight lines.

- **AC-OPS-40** Write to a temp file in the same directory, then `os.replace()`
  onto the target, so the previous file stays intact until the rename succeeds.
  A failed save logs at ERROR naming the file.
- Prove it load-bearing: interrupt the write and assert the original file is
  still complete and readable.

### T2.1: Fail-closed auth via explicit setting · M · risk: medium

> **The tri-state default sketched below does not work. Verified by execution
> 2026-08-06** (`lens-simplicity`, reproduced by the orchestrator):
> `registerDefaults` materialises the literal line `auth_required = None` into
> `config.ini` on first boot, so "unset" survives exactly one start. Reading it
> back, `get(default=None)` returns `None` but `get(default='')` returns `''`,
> and `Env.setting`'s own default **is** `''`. So the natural
> `Env.setting('auth_required', type='bool')` yields a falsy value and auth stays
> off, silently, on every install, with no failing test and no log line. The
> tri-state also only round-trips via a `ValidationError` raised and swallowed
> per auth check (`settings.py:154-155`), so adding `'none'` to the falsy list
> as a tidy-up would turn every protected install public.
>
> **Use instead**: a plain `{'default': 0, 'type': 'bool'}` plus a one-shot
> startup migration that writes `auth_required = 1` when the key is absent and a
> password is set. After the first boot the value is an explicit `0` or `1` that
> the operator can read with `grep`, which is also the documented recovery path.

`couchpotato/__init__.py:57-71` currently gates on `if username and password:`,
so a password with a blank username leaves the server fully public: verified by
executing `get_current_user`.

```python
# new setting in core/_base/_core.py, 'basics' group
{'name': 'auth_required', 'default': None, 'type': 'bool',
 'label': 'Require login',
 'description': 'Require login for the web interface. Defaults on once a '
                'password is set. Turn off only for a trusted LAN.'}
```

- Gate becomes: auth enforced when `auth_required` is on; default derives from
  `bool(password)` so existing password-only installs become protected.
- Username blank = any username accepted, rather than a master off-switch.
- Log a `WARNING` at startup when serving with auth disabled.
- Move the "Leave empty to disable authentication" copy off the **username**
  field (`_core.py:272-284`): it is on the wrong option today and is the
  proximate cause of the trap.

**Acceptance:** unit tests pin all four username/password combinations plus both
`auth_required` states: six cases. The password-only case, which returns `True`
today, must return falsy.

### T2.2: Gate `/getkey/` · S · risk: low

`couchpotato/__init__.py:265-283` has no auth dependency; with default settings
both credential clauses short-circuit true and it returns the API key that
authorises `media.delete`, `settings.save`, `directory.list` and `app.shutdown`.

Safe to gate: no live consumer (verified above). Return 401 when auth is
required and no valid credential is supplied.

**Acceptance:** unauthenticated `GET /getkey/` returns 401 on a default install;
`tests/unit/test_fastapi_web.py:266-285` updated to cover the gated behaviour.

### T2.3: Separate the session credential from the API key · L · risk: medium

`__init__.py:315` sets the cookie to the api_key itself, so `/logout` revokes
nothing, a password change revokes nothing, and the 30-day "remember me"
persists a permanent credential.

Issue a random session token stored server-side (a `sessions` table in the
existing SQLite DB, or a signed itsdangerous-style token with a rotating secret: prefer the table; it makes revocation real). Set `secure` when TLS is
configured (`runner.py:336-340`) and `samesite='lax'` explicitly rather than by
Starlette default.

**Acceptance:** logout invalidates server-side (a replayed cookie fails);
changing the password invalidates existing sessions; `secure` set under TLS.

### T2.4: QW3 + QW4: rate limiter and event-loop bcrypt · S · risk: low

- `core/rate_limit.py:51-55` exempts any request with `text/html` in `Accept`
  and no `/api/` in the path: an attacker-controlled header that uncaps
  `/login` and `/getkey`. Remove the exemption; exempt by *path prefix* only
  (static assets), which is what the adjacent `_EXEMPT_PREFIXES` check already
  does correctly.
- `login_post` and `get_key` are `async def` calling `bcrypt.checkpw` inline on
  the event loop. Wrap in `run_in_threadpool`, the pattern already used at
  `__init__.py:248` and `ui/__init__.py:167`.

**Acceptance:** a test asserts `Accept: text/html` requests to `/login` are rate
limited; a test asserts the login path does not block the loop (mirror the
existing `test_api_dispatch_concurrency.py` shape).

### T2.5: QW5 + QW6: headers and constant-time comparison · S · risk: low

- Add a security-headers middleware: `Content-Security-Policy`,
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`.
  The UI has one-click delete controls and is framable today.
- `__init__.py:148,155-158` compares the API key with `!=` / `startswith`; the
  cookie path already uses `hmac.compare_digest`. Make them match.
- Raise the minimum API key length above 4 (`_core.py:93`).

**CSP gotcha:** the templates use Alpine.js, which needs `unsafe-eval` unless the
CSP build of Alpine is used. Land the header with the E2E suite as the guard: a too-strict CSP breaks the UI silently in ways unit tests will not catch.

### T2.6: QW2 + QW7: TLS verification and log redaction · S · risk: low

- ~~`core/downloaders/synology.py:140`: `verify=False` while POSTing
  `account`/`passwd`. Honour the global `ssl_verify` setting; this is the last
  `verify=False` in the tree.~~ **RETRACTED as written -- this fix closes
  nothing, and the real exposure is worse. Verified 2026-08-07 by reading the
  file:**

  `synology.py:109-110` hardcodes the scheme:

  ```python
  self.download_url = 'http://%s:%s/webapi/DownloadStation/task.cgi' % (host, port)
  self.auth_url     = 'http://%s:%s/webapi/auth.cgi' % (host, port)
  ```

  `verify` is a TLS parameter. On an `http://` URL `requests` never reaches a
  TLS handshake, so `verify=False` at `:140` is unreachable and honouring
  `ssl_verify` there would change no observable behaviour. Shipping it would
  produce a commit that reads like a TLS hardening fix and hardens nothing --
  the same "fix the appearance" shape T1.5 already cost this project once.

  **The actual finding:** `_login` (`:117-121`) POSTs `account` and `passwd`
  over plaintext HTTP on every download action, so the operator's NAS password
  crosses the LAN in the clear. The `host` setting (`:227-229`, "Hostname with
  port. Usually localhost:5000") accepts no scheme, so a user whose DSM offers
  HTTPS on 5001 cannot opt in even if they want to.

  **Correct fix, deferred to its own task:** honour a scheme if the user
  supplies one in `host`, default to `http://` for compatibility, and set
  `verify=True` whenever the resolved scheme is https. Not taken here because
  it changes downloader transport and cannot be exercised without a real
  Synology -- and a downloader that silently stops working is a worse outcome
  for the operator than the exposure it fixes. It wants a device to test
  against, which is a prerequisite this branch does not have.
- Extend `PrivacyFilter`'s allowlist (`core/logger.py:27`) with `token`,
  `authkey`, `torrent_pass`, `sid`, `passkey`; fix the three call sites that log
  secrets outside query-param form: `notifications/telegrambot.py:37`,
  `downloaders/synology.py:125`, and full-URL logging at `http_client.py:236`.
- Reconsider `logger.py:64-65`, which disables redaction entirely under `dev`.

**Acceptance:** a test feeds each secret shape through the filter and asserts
redaction: including the non-query-param forms, which is the gap today.

### T2.7: SSRF: userscript host matching · M · risk: low

`providers/userscript/base.py:39-47` matches hosts by substring against patterns
like `http://*.imdb.com/title/tt*` and never checks the path. Reproduced:
`a.imdb.co` → True, `a.imdb.c` → True, `a.imdb.com:9200/internal` → True.

Replace with exact host-suffix matching against a parsed allowlist, and add a
private/loopback/link-local address guard in `http_client.py` for URLs whose
origin is user- or feed-supplied.

**Acceptance:** the three strings above are rejected; a URL resolving to
`127.0.0.1` or RFC1918 space is refused with a logged reason.

**PR 2 acceptance:** all of the above green; E2E suite green (the auth change
touches every page); a manual pass against a scratch instance confirming login,
logout, remember-me and the open-instance path all behave.

---

## PR 3: M1b: Data correctness at the SQLite seam

**Goal:** every `_query_index` branch honours its key or raises; no live code
path calls an adapter method that does not exist.

### T3.1: `release_download` key matching · S · risk: low

`sqlite_adapter.py:703-711` filters only on the *existence* of `download_info`
("for now return all with download_info"). The live caller
`renamer/scanner.py:197` takes the first row and stamps its `imdb_id`, `quality`
and `release_id` onto the download; `scanner/folder_scanner.py:360-363` then uses
that `imdb_id` to decide which movie the files belong to, on a job scheduled
every minute (`renamer/main.py:46`).

- **RED first:** insert two releases with different `download_info.id`, assert
  the lookup returns only the requested one. Fails today.
- Match on the two extracted fields independently rather than reconstructing the
  `'%s-%s'` string: a downloader name containing `-` makes the split ambiguous.
- Confirm the stored type of `download_info.id`: a numeric id stored as int will
  not match a string bind, and a fixture that does not mirror production data
  will pass for the wrong reason.
- Add `idx_release_download` on
  `json_extract(data,'$.download_info.downloader')` and `…'$.download_info.id'`.

**Critical:** `open()` does not run `schema.sql` (`:208-219`). Add an idempotent
upgrade call in `open()` following `_ensure_unique_media_identifier_index`
(`:132-206`), or the index reaches fresh installs only. Prove it by opening a
copy of a pre-change database and asserting the index exists afterwards.

### T3.2: Reconcile the adapter compat surface · M · risk: medium

`db.reindex()` is called with no argument at `database.py:218,316`,
`manage.py:199`, `release/main.py:155`, but the signature is
`reindex(self, index_name)` (`:836`): a guaranteed `TypeError`. In `manage.py`
it aborts the enclosing `try` before `Env.prop(last_update_key, …)` is written,
so every full library scan logs "Failed updating library" and never records
completion.

`db.opened` (`database.py:402`) and `db._delete_id_index` (`:209`) do not exist
either. `db.opened` is on the fossil v1 migration path only (verified), so
delete that path rather than repairing it: after confirming reachability.

**Acceptance:** a library scan writes its completion timestamp (assert on
`Env.prop`); a test asserts every `db.<method>` call in `couchpotato/` resolves
to a real adapter method: the enforceable version of this class of bug, and it
would have caught all three.

### T3.3: Restore or delete orphan-release cleanup · S · risk: low

`release/main.py:117-152` reads `release.get('key')`, a CodernityDB index-row
field `_doc_from_row` never produces (`:287-292`). `db.get('id', None)` raises
`KeyError`, which misses the `except ValueError` / `except RecordDeleted`
clauses and lands in `except Exception: log.debug` at `:151-152`. Dead since the
SQLite migration, invisible above DEBUG.

Decide: restore (with a test proving an orphan is deleted) or delete. Prefer
restore: orphaned releases accrue otherwise.

### T3.4: Narrow the dangerous exception swallowing · S · risk: low

Not a campaign against all 377 `except Exception:` blocks: most are legitimate
resilience. Three specific ones:

- `database.py:130-134,177-181` return `traceback.format_exc()` bodies to API
  clients (internal path disclosure). Log server-side, return a generic error.
- `fireEvent`'s outer handler returns `None` implicitly (`event.py:266-267`),
  violating its own list contract for callers like `searcher.py:102`. Return `[]`.
- `api.py:68-70` collapses every handler failure into one generic error; the UI
  documents working around this (`ui/__init__.py:389,406`). Preserve the error
  type for logging at minimum.

**PR 3 task outcomes (recorded 2026-08-07, review finding H2):** T3.1, T3.2 and
T3.4 shipped. **T3.3 is DEFERRED, not done** -- the review measured the
orphan-release loop as fully dead on `SQLiteAdapter` (`release.get('key')` is
always `None`, so every arm below it is unreachable), which means deferring
regresses nothing, but restoring it means deleting orphaned rows, and this
project's rules put a delete path in its own change with its own review rather
than folded into a data-correctness PR. Tracked as T8 in the conductor
checklist. The dead loop is documented at the line in `release/main.py` so the
"Cleaned up N" log does not read as a working report.

**PR 3 acceptance:** the two-download fixture attributes files to the correct
movie; library scan records completion; the adapter-method-existence test passes.

---

## PR 4: FEAT-009 Part B: upgrade replacement

**Goal:** complete the deferred half of FEAT-009: an upgrade must be able to
land, without ever putting the user's library at risk.

**Why here:** it depends on PR 1's `moveFile` tests (this is the same code path)
and on PR 3, which also edits `release/main.py` and the renamer scanner. It must
not be folded into the performance PR: it is the one code path that deletes
files from the user's library and needs to be reviewed on its own.

**Status entering this PR:** two attempts were made and both withdrawn, each
because it moved a possible loss from the replaceable side (a download) to the
irreplaceable side (the library). Per CLAUDE.md rule 11, this third attempt is
reviewed as **new work, not a correction**: and it is the case that rule was
written for.

### The two withdrawn attempts (do not repeat)

1. **No quality comparison at all.** Measured: a 720p download overwrote a 2160p
   remux.
2. **Comparison via `quality.isHigher`.** That is a *search* heuristic: it
   returns `'higher'` whenever the existing quality is not a rung of the profile
   (`quality/main.py:542-548`, re-verified 2026-08-02). The default `Best`
   profile excludes 2160p, so it still authorised destroying a remux. It was
   also **inert**: the scanner-supplied `group['media']` has no `releases` key
   (`media.get` attaches it, and the scanner never calls it), so the gate always
   refused: meaning *fixing the inertness would have activated the destruction*
   on the default profile.

That last point sets the sequencing inside this PR: **the ordering must be
correct and tested before the gate is made live.** Do not fix the missing
`releases` attachment first.

### T4.1: Profile-independent quality ranking · S · risk: low

Add a ranking primitive over `QualityPlugin.qualities` (`quality/main.py:26-38`): rank by index, lower index = better. "Is this file better than what is on
disk" is a global question, not a profile question.

- New event/method, e.g. `quality.rank`, returning the index or `None` when the
  quality is unknown.
- **Unknown quality on either side ⇒ refuse to replace.** Degrade to today's
  skip-and-warn rather than guessing, matching FEAT-009 Part A's AC3 philosophy.
- Decide and pin the 3D rule: `is_3d` is not part of the global list ordering, so
  a 3D and non-3D copy at the same rung are not comparable: treat as "not
  better" and refuse.

**Acceptance:** a test table over the full `qualities` list pins the ordering,
including `bd50` above `1080p` and `brrip` below `720p`. Explicitly pin
**720p vs 2160p → not better**, the case measured to fail in attempt #1, and the
default-`Best`-profile case from attempt #2: the ranking must not consult a
profile at all, so a test that passes a profile and asserts no behaviour change
is the guard against regressing to `isHigher`.

### T4.2: Attach releases at the call site · S · risk: medium

The scanner's `group['media']` carries no `releases` key, which is why attempt
#2 was inert. Attach them where the renamer needs them.

**Do this only after T4.1 is green**: this is the change that makes the gate
live, and on the previous attempt it would have activated destruction.

**Acceptance:** a test asserts the renamer sees the media's releases; the
replacement gate is exercised rather than silently refusing (an inert gate is a
vacuous guard: CLAUDE.md §11).

### T4.3: Atomic replacement · M · risk: **high**

Replace `renamer/main.py:154-157`'s unconditional skip with: replace when
`remove_lower_quality_copies` is on **and** the incoming copy ranks strictly
better; otherwise keep the existing file and preserve the download (the safety
half already shipped).

Replacement must never be `os.remove` + move. Sequence:

1. Move the incoming file into the destination directory under a temporary name
   (same filesystem, so the later swap is atomic).
2. Verify it landed: size matches the source.
3. `os.replace(tmp, dst)`: atomic within a filesystem.
4. Only then account for the old copy.

If any step fails, the destination is untouched and the download survives.

**Gotchas:** `os.replace` is atomic only *within* a filesystem: the library and
the download directory are frequently different mounts on this project's target
deployment, so the temp file must be created in the **destination** directory,
not the source. This interacts directly with `moveFile`'s hardlink/symlink
fallback branches (the `link` fallback), which PR 1 now covers: reuse those tests
as the foundation rather than writing a parallel harness.

**Acceptance (every one is a destructive-direction test):**
- Old file is **not** removed when the new one did not land (kill the move
  mid-way and assert both the original and the download survive).
- A strictly-better copy replaces; an equal or worse copy does not.
- With `remove_lower_quality_copies` off, the existing file is untouched **and**
  the incoming file is not silently destroyed.
- `cleanup` does not delete the source folder when any file was skipped or
  failed: regression-pin the shipped safety half so this PR cannot undo it.

### T4.4: Path ownership · S · risk: medium

The spec names an open design question: which release owns a given path when two
legitimately claim it. Resolve it explicitly (`copy_id` from Part A is the
natural discriminator) and write the rule down: an ambiguous answer here is how
the wrong file gets deleted.

**PR 4 acceptance:** all of the above green; the replacement path exercised
end-to-end against a real tmp filesystem; a reviewer lens specifically on "can
this delete something irreplaceable" in addition to the standard two. Update
`specs/FEAT-009-durable-set-aside-and-upgrade-replacement.md` to retire the
`STATUS: NOT IMPLEMENTED` block once it ships.

---

## PR 5: M2: Performance

### T5.1: Kill the triple-fetch · M · risk: low

`_query_index` already returns complete documents (`:789-790`), yet
`query(with_doc=True)` discards them and re-fetches each by id (`:546-550`);
named-index `get()` does the same (`:317-323`); and `Release.forMedia` stacks a
third (`release/main.py:766-773`). Every release document is read and JSON-parsed
three times. `get_many` defaults to `with_doc=True`, so one fix covers 44 call
sites.

**Acceptance:** a test counting adapter `get` calls asserts zero additional
fetches for a `query(with_doc=True)`. Assert on the *count*, not on timing: a timing assertion is a flake generator.

### T5.2: Paginate the movie list · M · risk: low

`ui/__init__.py:291-301` calls `media.list` with no `limit_offset`, and
`media/_base/media/main.py:276-399` fetches all ids, filters with list-membership
(O(N·M)), re-iterates the full library, then fires `media.get` per movie, which
itself does four more queries. Thousands of queries per page load at 1,000 movies.

Pass a limit from the UI; convert the list-membership filters to sets.

**Open question (§6.4):** target library size decides the page size. Assume 100
per page until told otherwise.

### T5.3: Build-time Tailwind · M · risk: medium

`ui/templates/base.html:19` loads `tailwindcss-cdn.js`: 407,279 bytes, the
in-browser JIT compiler: synchronously in `<head>` before anything renders.
htmx (51KB) and Alpine (46KB) follow without `defer`. This is the project's
largest self-inflicted Core Web Vitals violation.

Replace with a built stylesheet; add `defer` to the remaining scripts. Enforce a
CSS/JS size budget in CI so it cannot regress.

**Gotcha:** the design-system conformance check (`docs/design-system/CONFORMANCE.md`,
CI-gated) and the a11y E2E suite are the guards against visual regression here: this change cannot be verified by unit tests. Compare rendered screenshots before
and after.

### T5.4: Renamer re-entrancy · S · risk: low

`renamer/main.py:22-23,72-79` uses unlocked class attributes as guards, so the
cron thread and an API thread can both pass check-then-set and run two
destructive scans concurrently. Small window, destructive landing zone. Use the
existing per-instance lock pattern (`plugins/base.py:47`).

### Deliberately **not** in this PR

- **Per-route locks (`api.py:34`)**: real throughput cost, but removing them
  assumes handler thread-safety nobody has measured. Needs a concurrency test
  first, and it is not a user-visible problem at home-server scale. Open
  question §6.7 asks whether they are deliberate; answer that before touching.
- **Dirty reads during transactions (`:236-270`)**: genuine hazard, but the fix
  (per-thread connections or read locks) is a structural change that needs its
  own PR and a failing test that demonstrates the dirty read first. Write the
  test in this PR, mark it `xfail`, fix in a follow-up.

---

## PR 6: M3: Documentation, dead code, polish

### T6.1: Outward-facing docs · S

- `README.md:5`: badge for `.github/workflows/lint.yml`, which does not exist.
  Remove.
- `:13`: "What's New in v3.0.0" on a v3.9+ project. Retitle without a version.
- `:17`: "457 tests" vs ~1,743 today. **Remove the number**, don't update it;
  it will rot again by definition (project doc rule §7).
- `:22`: "no more vendored libraries" contradicts `:25` three lines later.
- `:75`: stale tag list.

### T6.2: CONTRIBUTING rewrite · S

`CONTRIBUTING.md:23` gives the test command as bare `pytest`, which collects
integration and e2e tests without the `PYTHONPATH=libs` that
`docs/development-process.md:507-509` warns is required. It never installs
`requirements-dev.txt` and never mentions `make setup`, `make verify`, npm,
Playwright, the pre-push hook, or the rule that UI changes require E2E updates.
Point it at the existing good content.

### T6.3: Docs that contradict the code · S

- Retire or rewrite `docs/reference/GITHUB_ACTIONS.md`: its section 3 documents
  `release.yml`, which no longer exists.
- Reconcile `docs/technical-debt.md:72` ("E2E … RESOLVED") against `:149-186`,
  which establish the suite is back at `workers: 1` with ~20% flake. The later
  entries are the truth.
- Decide CHANGELOG.md's fate (stops at v3.4.0): keep current or retire with a
  pointer to GitHub release notes.

### T6.4: Dead code · M

`helpers/variable.py` unused helpers (`removeListDuplicates`, `flattenList`,
`sha256`, `toIterable`, `dictIsSubset`); the unused `natsortKey` import at
`event.py:5`; `couchpotato/lib/` (empty shell, still on `sys.path`, still
ruff-excluded); `gntp==1.0.3` (no Growl plugin exists) plus its `logger.py:184`
quiet-list entry; a `# transitive: python-dateutil` comment on the `six` pin.

**Open question §6.5:** `hadouken.py` (606 lines) and `pneumatic.py` target
defunct services: removal is trivial but users cannot be surveyed. Deferred
pending a decision.

### T6.5: Remaining low-severity security · S

`tarfile.extractall(filter='data')` (`_base/updater/main.py:373`); list-args
`subprocess.run` instead of `os.popen` (`moveFile`'s `os.name == 'nt'` branch (`os.popen`/`icacls`)); strip `/`, `\`
and `..` in `renamer/namer.py:63`; validate `cors_origins` against `*` with
credentials (`__init__.py:109-118`); self-host the Google Fonts references
(`templates/login.html:25-26`, `ui/templates/base.html:53-54`); double
URL-decoding at `helpers/request.py:31,42`.

### T6.6: Enforcement, not prose · S

- SHA-pin GitHub Actions (the repo already pins gitleaks by version for exactly
  this reason).
- Mirror the required `secrets` check in `verify.sh` so a tree secret fails the
  pre-push hook, not just CI.
- Document the Node minimum and the Docker prerequisite; make `make setup`
  either create `.venv` or refuse to install into ambient python, matching
  `verify.sh:39-45`.

### T6.7: mypy on `core/db/*` (Q2, narrow start) · M · risk: low

Scheduled on 2026-08-02 after challenge: the *repo-wide* gate is XL and stays
deferred, but the narrow start was already identified and there is no reason to
park it. `core/db/*` is the one package that already carries type hints
throughout, so it should pass at or near clean immediately, which makes it a
gate that starts green and ratchets, not a migration.

**`lens-simplicity` vetoed this task at planning** on the grounds that no defect
has been identified that mypy would have caught, making it "a gate looking for a
job". **Veto overridden by Scott, 2026-08-03**, with the rationale recorded: it
is preventive rather than remedial, and `core/db/*` is where a type-shaped
regression would be most expensive. The objection is fair and is kept here so
the decision is visible: if the gate produces nothing but noise across a few
PRs, that is the evidence to remove it.

Add mypy to `requirements-dev.txt`, configure it in `pyproject.toml` scoped to
`couchpotato/core/db/`, and wire it into `verify.sh` and CI alongside ruff.

**Acceptance:** the gate is green on `core/db/*` and **fails** when a wrong type
is introduced there: prove it by breaking one signature and watching CI go red
before restoring. A type gate nobody has watched fail is decoration (§11).

**Explicitly not in scope:** widening beyond `core/db/`. Each additional package
is its own decision with its own annotation cost.

---

## PR 7: Make the accessibility gate fast

**Raised by the owner, 2026-08-07:** the accessibility check feels like it takes
over ten minutes, which is too slow for a gate that runs on every push.

**Measured before scoping, and the framing needs correcting.** The report was
"more than 10 mins just to build the docker container for the accessibility
test". There is no container build in that job. `.github/workflows/ci.yml`'s
`accessibility` job checks out, sets up Node and Python, `pip install -r
requirements.txt`, `npm ci`, `npx playwright install --with-deps chromium`, then
runs `--project=accessibility`. The separate `docker` job takes ~1m20s
consistently and the two are unrelated.

What the last **twelve** completed runs actually show for `accessibility`
(seconds, newest first):

    108  101  697  99  137  130  118  132  118  130  102  129

    n = 12    median = 123.5s (2.1 min)    runs over 5 min = 1
    excluding the 697s outlier: n = 11, min 99s, max 137s, spread 38s

**Corrected 2026-08-07 after review.** The first version of this section said
"the last six runs" above a five-row table and then used "one run in six" as the
evidence for calling the spike isolated. Both numbers were wrong, in a section
whose entire point is not diagnosing by inference -- so it is restated here from
a real twelve-run sample rather than quietly patched. The spike is 1 in 12, and
the job's normal cost is tightly clustered around two minutes.

**Corrected again 2026-08-07, same section, same failure mode.** The first
correction stated `median = 129s` and a "30-second band". Both were also wrong:
129 is the 7th of twelve sorted values, not the median of an even-length sample
(`(118 + 129) / 2 = 123.5`), and the eleven non-outlier runs span `137 - 99 =
38s`. Every statistic in this section is now computed rather than eyeballed, and
the raw series is printed above so the next reader can check the arithmetic
instead of trusting it. Two rounds of wrong numbers in a section arguing against
diagnosis by inference is the point, not an aside.

The `docker` job over the same period is a steady ~1m20s and is unrelated.

Two separate things are therefore in scope, and conflating them would fix
neither:

1. **Wall-clock to feedback.** `accessibility` is `needs: ui-e2e-tests`, which is
   itself `needs: [test, ui-unit-tests]` — third in a serial chain, so the
   elapsed time an operator experiences is the whole chain, not the job. That is
   the number the report is really about.
2. **The 11m37s outlier.** One run in twelve. Until its cause is known, any
   "optimisation" is guessing, and the honest possibility is that it was a slow
   runner or an apt mirror and nothing in this repo caused it.

### T9.1: Measure before changing anything · S

Get the per-step breakdown for both a normal and the slow run (`gh api
.../actions/runs/<id>/jobs`; the step timings did not come back cleanly through
`gh run view --json`, so this may need the raw API or the logs). Attribute the
time to steps, not to intuition. **No optimisation lands before this exists:**
this repo has a recorded habit of diagnosing by inference and being wrong.

Specifically answer: what did the 697s run spend its time on, and is
`--fail-on-flaky-tests` retrying? At 1 in 12 with the other eleven spanning 38s
(99s to 137s), a per-run cause (runner, apt mirror, a retry) is more likely than
a workflow one -- but "more likely" is not a measurement.

**Both questions are now answered below, and the guess above was half right:**
the cause was per-run, but it was not a retry, and the 12-run sample it rests on
is superseded by a 23-run one. Kept as written so the prediction can be scored
against the measurement rather than quietly edited to match it.


**T9.1 ANSWERED 2026-08-07 by the orchestrator.**

#### Method

`gh api repos/bassings/CouchPotatoServer/actions/runs/<id>/jobs` over the last 25
CI runs, then `.../actions/jobs/<job_id>` for the step timings. n = 23 successful
`accessibility` jobs (one skipped and one cancelled run excluded). This is a
wider sample than the twelve-run one recorded earlier, and it supersedes it.

#### The outlier is one step, and it is not the tests

Job `92791614728` (697s) against a normal job `92806433719` (115s):

| Step | Slow run | Normal run |
|---|---|---|
| Install Python dependencies | 17s | 27s |
| Install Node dependencies | 8s | 8s |
| **Install Playwright browsers** | **610s** | **22s** |
| Run accessibility tests | 51s | 46s |
| everything else | ~5s | ~9s |

**The test suite took 51s on the slow run and 46s on the normal one.** The spike
is entirely `npx playwright install --with-deps chromium`.

#### Across all 23 runs

| Step | n | min | median | max |
|---|---|---|---|---|
| job total | 23 | 99 | **115** | 697 |
| Install Playwright browsers | 23 | 21 | 27 | **610** |
| Run accessibility tests | 23 | 46 | **51** | 55 |
| Install Python dependencies | 23 | 15 | 17 | 30 |

Excluding the single stall, the Playwright install is 21-35s (median 26.5s).

**The test step never misbehaved once in 23 runs: 46-55s, including on the run
that took 697s.** So `--fail-on-flaky-tests` retrying is ruled out as the cause,
which was the open question T9.1 was written to answer.

#### What this changes about T9.2 and T9.3

1. **Caching the Playwright browser download is now the highest-value change,
   and for a reason the plan did not have.** It was scoped as "save ~25s on the
   median". It also removes the only mechanism that has ever produced an
   outlier: a 610s network or apt stall in a step that downloads a browser on
   every single run. Median win is modest; tail win is the whole 10-minute
   complaint.
2. **The 697s run needs no further diagnosis.** It was a slow download, not the
   repo, not the suite, not a retry. T9.1's question "is
   `--fail-on-flaky-tests` retrying?" is answered: no.
3. **The ~51s test step is the floor** for this job as it stands, and cutting it
   means cutting coverage, which the plan explicitly rules out. So the job
   cannot go much below ~60s even with perfect caching, and the remaining
   complaint is wall-clock from the serial chain (T9.3), exactly as scoped.
4. **The earlier twelve-run figures are superseded**: median 123.5s becomes 115s
   at n=23. Same conclusion, better sample.

### T9.2: Stop paying for the same install twice · S · risk: low

`npx playwright install --with-deps chromium` runs in BOTH `ui-e2e-tests`
(`:242`) and `accessibility` (`:340`), uncached. npm is cached (`cache: 'npm'`)
but the Playwright browser download and its apt `--with-deps` are not, and
`pip install -r requirements.txt` has no pip cache either.

Options, in increasing order of change: cache `~/.cache/ms-playwright` keyed on
the Playwright version from `package-lock.json`; add `cache: 'pip'` to
`setup-python`; or run the accessibility project inside the existing
`ui-e2e-tests` job so the install is paid once. The last is the biggest win and
the biggest change — it merges two gates, so their failures stop being
separable, which is a real cost on a gate whose job is to name what broke.

### T9.3: Reconsider the serial chain · S · risk: low

`accessibility` waits for `ui-e2e-tests` for no stated reason: it starts and
seeds its own server (see the comment at `:342-350` -- an earlier version of
this line cited `:329-338`, which is the Python/Node install steps), so it has
no data dependency on that job. If the `needs:` is only there to stage runner load, say
so at the line; if it is not needed, removing it moves accessibility from third
in a chain to parallel, which addresses the reported wall-clock directly and
without touching the tests.

**Acceptance:**

1. A measured before/after of BOTH numbers -- job duration and wall-clock from
   workflow start to accessibility completion -- over at least three runs each,
   because a single comparison cannot distinguish an improvement from runner
   variance. The baseline above is the "before".
2. The suite still runs the same specs. A faster gate that covers less is not
   the deliverable.
3. **The `accessibility` status context must survive.** It is a REQUIRED status
   check on `master` (verified: `lint, test-summary, ui-unit-tests,
   ui-e2e-tests, claude-review, Analyze (python), Analyze (javascript),
   dependency-review, docker, accessibility, conformance, secrets`). T9.2's
   "biggest win" -- folding the accessibility project into `ui-e2e-tests` --
   would delete the job that reports that context, and branch protection would
   then wait forever for a check nothing publishes, blocking this PR and every
   one after it. Either keep a job named `accessibility` that reports the
   result, or change branch protection in the same change. Not one without the
   other.

**AC-<LENS>-<n> criteria: NOT YET WRITTEN.** Per the M15 rule recorded in this
same plan, `/plan-cycle` runs on this task before any implementation, and its
lenses write numbered criteria here. Treating PR 7 as implementation-ready
before that would repeat exactly the gap M15 was added to close -- and it was
raised against this section, which is a fair hit.

**Explicitly NOT in scope:** reducing what the accessibility suite tests. WCAG
2.2 AA in both themes and at phone width is this project's stated floor, and
speeding the gate by lowering it would be the wrong trade.

---

## Deferred with rationale (not scheduled)

Revised 2026-08-02 after challenge: two rows moved into the plan (O2 → PR 1,
Q2's narrow start → PR 6), one missing rationale written (A5), one row
relabelled from "deferred" to "won't fix" (legacy deps), which is what it
always was.

| Finding | Why not now |
|---|---|
| Per-route locks (A4) | The lock is **inherited from upstream's Tornado era** (`af2876bd "Lock same api routes"`, carried through the FastAPI migration in `44224f03`): it is a decade-old guard around handlers written assuming they never run concurrently, not accidental carryover. Removing it makes ~100 legacy handlers concurrent for the first time. Cost of keeping: latency on a single-user server. Cost of removing wrongly: DB races on irreplaceable data. Answer open question §6.7 first |
| Circular-import hub (A5) | Architectural refactor with **no user-visible symptom** and a wide blast radius (~40 modules do `from couchpotato import get_db`). The repo's own history (#148) shows these re-exports break plugins *silently*, because the loader swallows `ImportError` at DEBUG. The real prerequisite is making plugin import failures loud: do that first; the imports are the second job, not the first |
| Dirty reads (P4) | Structural: the fix is per-thread connections or read locks, a redesign of connection handling in the best-engineered file in the repo. Partially scheduled: PR 5 writes the failing test and marks it `xfail`. A *demonstrated* dirty read is what tells you which fix is right, and nobody has demonstrated one |
| Broad `except Exception` (Q1, bulk) | ~377 blocks, most of them legitimate resilience: a media server *should* survive one bad file. A sweep is an enormous diff with no tests behind it. The three genuinely dangerous ones are scheduled in T3.4; the rest is a ruff `BLE` ratchet, incremental by nature |
| mypy beyond `core/db/*` (Q2, bulk) | Repo-wide is XL. The narrow start is now scheduled as T6.7; each further package is its own decision with its own annotation cost |
| Widen mutmut scope | Real value, but CI-minutes cost; decide after M2 |
| Shipped TMDB/fanart.tv keys | **Deliberate**: documented in `technical-debt.md:98-121`; removing them broke artwork once already. Do not "clean up" |

### Won't fix (a decision, not a deferral)

| Finding | Why |
|---|---|
| Legacy deps: bencodepy, putio.py, deluge-client, rtorrent-rpc (D4) | Dormant upstreams, but the code is live, working, pure-protocol, and no CVE was found. Replacing a working torrent-protocol library is pure risk with no benefit. This was mislabelled "deferred"; it is a decision to keep them |

## Sequencing and risk

```
PR1 (M0) ──▶ PR2 (M1a auth) ─────────────────┐
   │                                         ├──▶ PR5 (M2 perf) ──▶ PR6 (M3 polish)
   └────────▶ PR3 (M1b data) ──▶ PR4 (FEAT-009 Part B)
```

PR 2 and PR 3 are independent of each other and both depend on PR 1. PR 4
depends on **both** PR 1 (the `moveFile` tests are its foundation) and PR 3
(which also edits `release/main.py` and the renamer scanner). PR 5's adapter
work touches `query()`, which PR 3 also touches: land PR 3 first.

**PR 4 is the highest-risk PR in this plan** despite not being the largest. It
is the only one that deletes files from the user's library, and two prior
attempts at it were withdrawn. Give it a third reviewer with an explicit
"can this destroy something irreplaceable" lens, and do not let it ride along
with any other change.

**T5.4 (renamer re-entrancy lock) must land before PR 4**: decision 6. It is
listed under PR 5 for thematic grouping, but its dependency is PR 4, not PR 5.
Land it at the end of PR 3, or as the first commit of PR 4 before any
replacement logic. Two concurrent scans currently destroy a file while both
report success (`renamer/main.py:72-79`, unlocked check-then-set); PR 4 adds a
delete to that path.

**Production deploy is out of scope of this plan.** PR 2, PR 3 and PR 4 all
change behaviour on a live instance holding irreplaceable data. When a deploy is
agreed: `./scripts/backup.sh` first, record the current `config.ini` auth state,
promote a tested beta byte-for-byte, and keep the rollback tag to hand. Consider
letting PR 4 soak on `:beta` longer than the others: its failure mode is silent
and only visible after an upgrade actually lands.

## Finding coverage

Every audit finding maps to a PR or to the deferred table above.

| PR | Findings / work resolved |
|---|---|
| PR 1 | T1, T2, T3, T4, O1, **O2**, O5, D1 (partial), A6 |
| PR 2 | S1, S2, S3, S4, S5, S6, S7, S8, S9 (partial) |
| PR 3 | A1, A2, A3, Q1 (targeted subset) |
| PR 4 | FEAT-009 Part B (not an audit finding: deferred feature work) |
| PR 5 | P1, P2, P3, P5, P4 (failing test only, `xfail`) |
| PR 6 | C1, C2, C3, C4, D2, D3, D5, O3, O4, O6, Q3, S9 (remainder), **Q2 (narrow start)** |
| Deferred | A4, A5, P4 (fix), Q1 (bulk), Q2 (beyond `core/db/*`), mutmut scope |
| Won't fix | D4 (legacy deps: a decision, see above) |
