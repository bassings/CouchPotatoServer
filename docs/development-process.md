# Development Process — Path to Production

> Moved out of `CLAUDE.md` on 2026-07-13 during a restructure. This is the full,
> authoritative description of the push/review/deploy process. `CLAUDE.md` holds
> the short version; when in doubt, this file governs.

## Path to Production (full flow)

```
make setup → code → make verify → LOCAL agent review (must pass) → push/open PR →
  cloud claude-review → (findings? fix → LOCAL review again → push) → merge →
  auto beta build (:beta, per-commit) → manual promote to prod (:latest) →
  backup + record rollback tag → deploy → post-deploy checks
```

> Merging does **not** ship to production. Every merge auto-publishes a *beta*
> image only; production is a deliberate, manual promotion of a tested beta
> (**Actions → Release to Prod**). See "Release & production deployment" below.

> **The rule, stated plainly — never skip it: any push that needs the gate does
> not happen until its clean-agent local review is clean.** ("Needs the gate" =
> any code change, or a change touching `CLAUDE.md`/`AGENTS.md` or a `specs/**`
> file; **pure docs-only prose may skip** — see the carve-out below.) For a
> gated push the loop is: run the local review → fix every real finding →
> re-verify → **re-run the local review** → repeat **until it comes back
> clean**, and only *then* `git push`. Running the review agents *is* the gate —
> self-verifying the diff yourself does **not** substitute for it. This governs
> **every** gated push, not just the first:
> - the **initial** PR push;
> - **every fix commit** pushed in response to a cloud `claude-review` finding —
>   fix → local review again until clean → push; never fix-and-push without
>   re-reviewing. (But apply the **Exit condition** below for a genuine false
>   alarm / marginal nit: reject it with evidence and stop — don't chase forever.)
> - any push touching `CLAUDE.md`/`AGENTS.md` or a `specs/**` file.
>
> Pushing before the local review is clean defeats the point: the cloud reviewer
> is stateless per push, so it dribbles out — one push at a time — the findings a
> single local pass would have surfaced together.

## Local agent review gate

**MANDATORY for code changes, before every push to the cloud review; docs-only
changes may skip it and push directly.**

*"Docs-only"* means the diff touches **only** documentation prose — `*.md`
**outside** `specs/**`, or files under `docs/**` — and nothing else, **except
the policy docs `CLAUDE.md` and `AGENTS.md`**, which define how we work and so
are treated as code-changes (run the gate) even though they are markdown. A
change touching any code, template, test, config, or workflow file, **or any
`specs/**` file (including a `specs/*.md` spec, which accompanies code)** —
even alongside docs — is a **code change** and the gate applies. When in doubt,
run the gate.

Run a clean-agent review on the full branch diff (vs `master`) and make it pass
*before* pushing to the `claude-review` gate. Spawn ≥2 independent
`code-reviewer` subagents (defined in `.claude/agents/code-reviewer.md`, which
carries the persona, the evidence discipline and the AGENTS.md rubric) in
parallel — e.g. one frontend/a11y, one backend/tests. Invoke them BY NAME
rather than hand-writing a persona: prompts composed from memory are how the
AGENTS.md rubric came to be skipped for ten consecutive review rounds, leaving
four of its nine dimensions — including two it flags high-priority — unchecked.

Give the reviewers the **currently-verified facts** below so they don't
re-litigate things already confirmed *for the code as it stands* — but
**re-verify each fact against the tree before relying on it**; these are
point-in-time, not eternal, and a dependency bump or refactor can invalidate
any of them. A fact that no longer holds is a real finding, not a false alarm —
never suppress on the say-so of this list alone.

As of 2026-06 (verify before reuse):
- htmx 2.0.4 dual-dispatches camelCase+kebab so `@htmx:*` kebab handlers fire
  (check the bundled `htmx-*.min.js` if the version changes);
- `callApiHandler` returns `{'success': False}` instead of raising
  (check `couchpotato/api.py`);
- `CPLog` has no `.exception()` (check `couchpotato/core/logger.py`);
- CP.ui loads before Alpine in `base.html`.

Fix everything real the reviewers surface, re-verify locally, and re-review
until clean. **If the cloud review later raises anything, fix it and run the
local review again until it passes — then push.**

**Exit condition (avoid an infinite loop):** if the cloud review keeps flagging
a point the local review clears, investigate it once more; if it's a verified
false alarm (or a marginal/subjective nit on a low-risk change), reject it with
evidence in the PR thread, resolve the thread, and **stop** — do not keep
pushing. A stateless reviewer will always find "one more" angle; converge on
substance, not on silencing every comment.

Rationale: cloud `claude-review` is stateless per push, so each push
re-discovers the same already-cleared points and dribbles out genuine findings
one at a time; the local loop front-loads that discovery and collapses many
serial ~15-min cloud rounds into one.

This gate is **policy/agent-enforced, not hook-enforced**: the `make setup`
pre-push hook only runs `make verify` and cannot tell whether the local agent
review ran — honour the gate as a rule, don't rely on the hook to block a
gate-less push.

## Verification discipline (CLAUDE.md rules 9–11)

Three rules that exist because a green suite has repeatedly *not* meant correct
on this repo. They are judgement calls, deliberately not mechanical gates — the
mechanical half of the same problem lives in `scripts/check_test_traps.py`.

**A sub-agent's report is not evidence (rule 9).** Validate against the repo:
read the diff, run the command. Agents have reported "all green" with a gate
failing and described fixes they did not make. The orchestrator's sign-off is
its own verification, not a restatement of the agent's summary. (This is the
practice `docs/development-process.md` already implied; as of 2026-07-30 it is
policy, not instinct.)

**Run the mutation, and prove the mutation landed (rule 10).** "Mentally
mutating" the code does not work — every vacuous test caught here survived
mental review. Break the guarded behaviour, watch the test fail, restore.

The second half of that rule is the one earned locally, on
`feat/release-list-sort-filter` (2026-07-30): an attempt to prove a
`quote(movie_id)` test was load-bearing used a `sed` that silently matched
nothing, so the test "passed" against code that was never actually reverted. It
was caught only because *passing was the wrong answer*. A no-op mutation is
indistinguishable from a passing test unless you check the edit applied — so
`git diff` (or hash) the file after mutating and before running.

A passing test after a mutation has **two** possible causes, and they call for
opposite responses — which is why the check is not optional:

| Mutation applied? | Test result | What it means | Action |
|---|---|---|---|
| Yes (`git diff` non-empty) | **Failed** | The guard is real | Restore and move on |
| Yes (`git diff` non-empty) | **Passed** | The guard is genuinely vacuous | Fix the test |
| **No** (`git diff` empty) | Passed | You learned nothing at all | Re-apply the mutation |

The third row is the trap: it is indistinguishable from the second unless you
check, and it reads as reassuring.

**After three failed fixes, question the frame (rule 11).** The tripwire that
prompted writing this down: on `feat/release-list-sort-filter`, four fixes each
introduced a fresh defect — `tryInt` truncating scores, a contrast fix rendering
poster badges illegible, an `HX-Request` branch breaking the Back button, and a
seeder-health comparison against a raw provider value that 500'd the whole
movie-detail body. Each was caught by a review round rather than by the suite,
and each looked obviously correct when written. Two general lessons worth
carrying beyond that branch:

- **Fixes are new work.** A one-line correction gets the same TDD and the same
  review as a feature; "it's just a fix" is how all four shipped.
- **A first-of-its-kind change has no precedent to lean on.** The Back-button
  defect came from this branch introducing the codebase's first `hx-push-url`,
  which engaged htmx's history machinery for the first time ever — it snapshots
  `body.innerHTML` including Alpine's `x-teleport`ed copy, so a cache-hit Back
  restored a duplicate with no scope (measured: 3 duplicated ids, 42 uncaught
  page errors, deterministic). When a change is the first use of a mechanism,
  the blast radius is unknown by definition; go looking for it explicitly.

## PR gate (cloud review)

Every PR is auto-reviewed by Claude (`.github/workflows/claude-review.yml`,
authenticated via the `CLAUDE_CODE_OAUTH_TOKEN` subscription secret — no API
billing). Resolve every thread it opens; branch protection on `master` requires
the `claude-review` check to pass + conversation resolution. No separate human
approval is required (solo-maintainer setup), so the agent review *is* the
review gate.

**Note:** GitHub only runs `claude-review` with its token once the workflow
exists on `master`; the PR that introduces/edits it is a no-op (expected).

## Required CI checks

Required (i.e. enforced by branch protection on `master`, verified via
`gh api repos/bassings/CouchPotatoServer/branches/master/protection/required_status_checks`):

`lint` (ruff **+ the test-trap guard**), `test-summary`, `ui-unit-tests`,
`ui-e2e-tests`, `claude-review`, `Analyze (python)`, `Analyze (javascript)`,
`dependency-review`, `docker`, `accessibility` (axe), `conformance`
(`scripts/check_conformance.py` — design-system drift gate, added in #147),
`secrets` (gitleaks — enabled 2026-07-31, immediately after #214 merged).

**Runs but does NOT gate:** `security-lint` only — informational by design (see
below). A PR can merge with it red.

`secrets` (gitleaks) **is** enforced as of 2026-07-31: it was added to `master`'s
required status checks immediately after #214 merged, which is the first moment
it was safe. Enabling it earlier would have deadlocked every PR branched from
master, because a required context the default branch does not produce blocks
those PRs forever — and Dependabot opens master-based PRs on a schedule. Verify
with:

```bash
gh api repos/bassings/CouchPotatoServer/branches/master/protection/required_status_checks --jq '.contexts'
```

`ci.yml` uses `concurrency: cancel-in-progress: true` — a new push supersedes the
in-flight run. Note this is deliberately **false** in `docker.yml` and
`release-to-prod.yml`, where cancelling mid-run could leave a half-published
image.

## SAST / security gates

- **CodeQL** (`codeql.yml`) — Python + JS static analysis, per-PR + weekly.
- **dependency-review** (`dependency-review.yml`) — blocks PRs that add deps
  with known high/critical vulns.
- **Trivy** image scan in the `docker` job — fails on fixable HIGH/CRITICAL
  CVEs (`ignore-unfixed`, `.trivyignore` for the DS-0002 false positive).
- **secrets** (gitleaks, pinned `v8.30.1`) — scans the **working tree**, not full
  history. Full history holds 37 findings — 31 of them upstream CouchPotato's own
  committed provider keys spanning 2011–2017, and 6 authored by this fork (see
  `make check-secrets-history` for the breakdown) — and a gate that is red on
  arrival gets disabled; the working-tree check
  answers "is there a secret in the code as it stands?". Two known upstream
  provider keys still in the tree are baselined by fingerprint, each with a
  justification, in `.gitleaksignore` — **an entry there without a comment is
  indistinguishable from a suppressed real leak**. Local equivalents:
  `make check-secrets` (same command CI runs) and `make check-secrets-history`
  (the noisy full-history scan; use it when a credential is suspected to have
  been committed and later deleted, which the tree scan cannot see).
- **test-trap guard** (`scripts/check_test_traps.py`, in the `lint` job and
  `make verify`) — blocks *false greens*: jsdom layout-zero reads in vitest specs
  without a stub, test runners piped into filters without `pipefail`, and shell
  gates missing `set -euo pipefail`. This is the mechanical half of CLAUDE.md
  rules 9–11; see "Verification discipline" above for the judgement half.
- **security-lint** (ruff `S`/bandit) — INFORMATIONAL, non-blocking (~169
  legacy findings); ratchet S codes into the blocking `lint` as cleared.
- Plus the `claude-review` prompt covers security qualitatively.

## Mutation testing

Informational only — there is no score threshold. Review the survivor list and
strengthen the weak assertions; a survivor usually means a missing or weak
assertion, and genuinely *equivalent* mutants (ones that cannot change observable
behaviour) should be noted and skipped rather than chased.

| Command | Scope |
|---|---|
| `make mutation-changed` | **Only files changed vs `master`** — fast enough to run per-change. `BASE=origin/master` to compare elsewhere. To see the commands without running them, invoke the script directly: `python scripts/mutation_changed.py --dry-run` (`make mutation-changed --dry-run` does not work — make consumes `--dry-run` as its own `-n`). |
| `make mutation-py` | Everything in `[tool.mutmut] source_paths` (mutmut) |
| `make mutation-js` | Everything in stryker's `mutate` (Stryker over the extracted UI logic in `couchpotato/static/scripts/ui/`, ~96% score) |

Also runs nightly + on-demand via the *Mutation Testing* workflow. Config lives
in `[tool.mutmut]` (`pyproject.toml`) and `stryker.conf.json`;
`scripts/mutation_changed.py` **reads those** rather than keeping its own copy of
the scope, so the two cannot drift — pinned by
`tests/unit/test_mutation_changed.py`.

`make mutation-changed` exists because the full run is slow enough that in
practice it only happened nightly, which meant survivors went unreviewed and the
"review the survivor list" half of this rule quietly stopped happening.

## E2E tests

- E2E tests live in `tests/e2e/*.spec.ts` (Playwright).
- `make verify` runs them with an auto-started server, or run directly against
  a booted app:
  `.venv/bin/python CouchPotato.py --data_dir=.e2e-data --console_log` then
  `CP_TEST_URL=http://localhost:5050 npx playwright test tests/e2e/<spec> --project=chromium --workers=1`.
- CI also runs the full suite. (See also AGENTS.md's local-verification step,
  which runs the whole suite via `npm run test:e2e`.)
- For any UI change, check and update:
  - `tests/e2e/filters.spec.ts`
  - `tests/e2e/navigation.spec.ts`
  - `tests/e2e/interactions.e2e.spec.ts`

## Sonnet agent delegation

Scott (Eggbert) plans and reviews — architecture, specs, QA. Sonnet sub-agents
do the coding: spawn the `implementer` agent (`Agent` tool,
`subagent_type: "implementer"`), defined in `.claude/agents/implementer.md`,
which carries the persona, the TDD and mutation discipline, and the
commit-locally-never-push boundary. Invoke it by name rather than hand-writing
a prompt.

Workflow:
1. Write a clear spec in `specs/` (problem, fix, acceptance criteria, files).
2. Spawn one or more Sonnet sub-agents to implement the spec. TDD: write the
   failing test first, make it pass, then run `ruff` + `pytest`. The agent must
   **STOP after committing locally — it does not push** (the local-review gate
   still applies).
3. Report start to user, then stop monitoring — do NOT poll the agent
   transcript repeatedly, read output incrementally, or narrate each step.
4. Wait for completion, review the diff; run the local-agent review and push
   only once it passes.

Notes:
- **Hallucination risk:** agents may invent package versions — always verify
  with `pip index versions <pkg>`.
- **Docker timing:** Docker Desktop takes 1–2 min to fully start — start it early.

## Release & production deployment

Two channels: **beta** (automatic, every push) and **prod** (manual
promotion). Full design: `specs/FEAT-release-channels.md`.

### Beta channel (automatic)

1. Every push to `master` triggers `.github/workflows/docker.yml` — build,
   smoke-test, publish. No action needed.
2. Version: **minor bump on every commit**
   (`scripts/release/next_beta_version.py`) — the next version is the highest
   minor across all existing tags (stable *and* beta) plus one, always
   `-beta.1`. So the beta line climbs `v3.10.0-beta.1 → v3.11.0-beta.1 →
   v3.12.0-beta.1 …`; minor numbers rise quickly by design, and a re-run on an
   unchanged commit simply wastes a minor rather than colliding.
3. GHCR tags written: `:beta` (moving), the immutable `:X.Y.0-beta.1`, and
   `:sha-<short>`, plus a GitHub **prerelease** with an auto-generated
   changelog. `:latest` is never touched.
4. The image bakes `CP_VERSION` as the **base** version (`X.Y.0`, no `-beta`)
   — so a promoted image reports a clean version and the updater keeps
   notifying stable users. The `-beta.N` identity lives only on the git tag /
   prerelease, not inside the image. (Don't "fix" the image to report `-beta`;
   it would silence stable-channel update checks — see the spec.)

### Prod channel (manual promotion)

1. Once a beta has been tested, go to **Actions → Release to Prod → Run
   workflow**. Optionally name a specific beta tag (e.g. `v3.10.0-beta.1`);
   blank promotes the newest prerelease.
2. The workflow re-tags the tested beta image **byte-for-byte**
   (`docker buildx imagetools create` — no rebuild) to `:latest`, `:X.Y.0`,
   `:X.Y`, and `:X`, and cuts a **stable** GitHub Release (`vX.Y.0`, `-beta`
   dropped).
3. **Never deploy to production until explicitly agreed.**
4. Scan the promoted image before deploying:
   `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --scanners vuln ghcr.io/bassings/couchpotatoserver:latest`.
   Target 0 CVEs. `.trivyignore` suppresses only the DS-0002 misconfig false
   positive (gosu/su-exec privilege-drop pattern).
5. Deploy using the procedure below — **back up and record the rollback tag
   first**. Prod compose stays pinned to `:latest`, which is now guaranteed
   stable-only, so a `docker compose pull` there can never pick up an untested
   beta.

### Deploying to prod (backup → rollback tag → restart → verify)

A promotion is reversible only if you capture two things *before* restarting:
the database, and the digest of the image currently running. Neither is
recoverable afterwards — `:latest` has already moved by the time you deploy, so
"just re-pull the old one" is not available.

```bash
# SSH credentials in Openclaw memory (topics/couchpotato.md)
cd /var/lib/plexmediaserver/CouchPotato

# 1. Back up the DB + settings (see "Backups" below; ~seconds, live-safe).
./scripts/backup.sh

# 2. Record what is running now, so rollback has a target.
#    The digest is the only reliable handle — the tag :latest is about to move.
docker inspect couchpotato --format '{{.Config.Image}} {{.Image}}'
#    The version is written into /app/version.py at build time (Dockerfile:74-76
#    bakes the CP_VERSION *build arg* into that file). Read the file:
docker exec couchpotato cat /app/version.py     # -> VERSION = '3.18.0'
#    NOT `printenv CP_VERSION` — CP_VERSION is an ARG, not an ENV, so it is absent
#    from the running container. And do not fall back to grepping the env for
#    /version/i: that matches PYTHON_VERSION and hands you the interpreter version
#    (3.14.6) as a rollback tag, silently and plausibly, mid-incident.
# Note BOTH the digest and the version down before continuing.

# 3. Pull and restart.
docker compose pull
docker compose up -d
docker logs couchpotato --tail=50
```

**Post-deploy checks** — do all five; a clean log is not enough, and three of
the four defects on `feat/release-list-sort-filter` were rendering faults a
healthy container reports nothing about:

1. `http://homemedia.maeewing.com:5050/` loads and the movie list renders.
2. Open one movie's detail page — the release table renders (this is the body
   that a single bad provider value 500'd; a healthy `/` proves nothing about it).
3. Wanted + Manage pages load; library counts match what they were pre-deploy.
4. Settings loads and a save round-trips (settings live in `config.ini`, not
   `settings.conf`).
5. `docker logs couchpotato --tail=50` shows no tracebacks, and the search /
   Jackett path returns results (`http://homemedia:9117` reachable).

### Rollback

Because every promoted version keeps its immutable tag, rollback is a tag pin —
no rebuild, no registry surgery:

**Edit the compose file's image line — do not hand-roll a `docker run`.** The
container needs `/config` *and* `/data` plus the media/download mounts
(`Dockerfile:84` declares `VOLUME ["/config", "/data"]`; `Dockerfile:97` runs with
`--data_dir=/data --config_file=/config/config.ini`, and the database lives under
`/data`, not `/config`). A `docker run` that mounts only `/config` gives the
rolled-back container a **fresh anonymous `/data`** — i.e. it comes up on an
empty database, during an incident, which is the worst possible moment to
discover it. Compose already has every mount right; change one line:

```bash
cd /var/lib/plexmediaserver/CouchPotato

# Pin the previous good version explicitly (do NOT rely on :latest — it has moved).
# In docker-compose.yml, set:
#   image: ghcr.io/bassings/couchpotatoserver:X.Y.0
# (or the digest from step 2: ghcr.io/bassings/couchpotatoserver@sha256:...)
$EDITOR docker-compose.yml

docker compose up -d
docker logs couchpotato --tail=50

# If the DB also needs restoring (only if a migration or a write corrupted it).
# Note: INSIDE the container the DB is under /data, not /config. On the host it
# happens to live beneath .../CouchPotato/config/data — the prod compose maps that
# host directory to the container's /data. Confirm with the docker inspect below
# rather than trusting either path.
docker compose stop
cp <BACKUP_DIR>/<timestamp>/couchpotato.db \
   /var/lib/plexmediaserver/CouchPotato/config/data/database_v2/couchpotato.db
docker compose start
```

Confirm the compose mounts before relying on the path above —
`docker inspect couchpotato --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'`
prints exactly where `/data` lands on this host. The prod compose file is not in
this repo, so that is the authority, not this document.

Prefer re-pinning the image alone first — restoring the DB discards anything
added since the backup. Once the pinned old version is confirmed healthy, revert
the compose file back to `:latest` only after the bad release is superseded,
otherwise the next `docker compose pull` silently re-deploys the broken image.

> ⚠️ `config.bak/` under `/var/lib/plexmediaserver/CouchPotato/` must **never**
> be deleted, by a backup script or by hand. It is not a scratch directory.

### Backups

`scripts/backup.sh` snapshots the SQLite DB (via `sqlite3 .backup`, or Python's
`sqlite3` backup API when the CLI is absent or broken — both are safe against a
live database; a plain `cp` of an in-use SQLite file is not) plus `config.ini`,
into a timestamped directory under `BACKUP_DIR`. It never touches `config.bak/`
and prunes only its own timestamped output.

`config.ini` is looked for in **both** `$CP_DATA_DIR/config.ini` (where
`couchpotato/runner.py:48` defaults it) and `$CP_DATA_DIR/../config.ini` (where
the Docker image puts it — `Dockerfile:97` runs
`--config_file=/config/config.ini` with `--data_dir=/data`, so it sits one level
above the data dir). Checking only the first would have meant prod snapshots
quietly containing the database alone: the script warns and exits 0, so a nightly
cron would report success forever while never capturing settings.

Both paths default to the prod layout, so on the server it takes no arguments
(`make backup` is a shortcut for the no-argument form):

```bash
./scripts/backup.sh                # snapshot, keep everything (= make backup)
./scripts/backup.sh --retain 14    # snapshot, then keep the 14 newest
./scripts/backup.sh --help         # full usage

# Override the paths (this is how the tests drive it):
CP_DATA_DIR=/var/lib/plexmediaserver/CouchPotato/config/data \
BACKUP_DIR=/var/lib/plexmediaserver/CouchPotato/backups \
  ./scripts/backup.sh
```

Snapshots land in `<BACKUP_DIR>/<YYYYMMDD-HHMMSS>/{couchpotato.db,config.ini}`.
`--retain 0` is rejected rather than treated as "keep nothing", and retention
only ever deletes directories matching its own timestamp pattern — behaviour
pinned by `tests/unit/test_backup_script.py`. The `.backup`-vs-`cp` distinction in
particular is caught by the WAL-mode fixture.

A note on mutation scores quoted anywhere in this repo: they describe *the set of
mutants that was run*, not adequacy. A 23/23 on a hand-picked set and 16/25 on an
independently-chosen one are both true of the same suite — reviewers found
survivors this way twice. Treat a score as "these specific behaviours are pinned",
never as "the tests are sufficient".

Two manual steps, both on the server — neither is automated by this repo:

1. The server holds a compose + config directory, **not** a repo checkout, so
   copy `scripts/backup.sh` there once (`scp scripts/backup.sh
   homemedia:/var/lib/plexmediaserver/CouchPotato/scripts/`).
2. Schedule it with `crontab -e`:
   ```cron
   0 3 * * * cd /var/lib/plexmediaserver/CouchPotato && ./scripts/backup.sh --retain 14 >> /var/log/couchpotato-backup.log 2>&1
   ```

### Beta testers

To track the beta channel instead of stable: point your compose file's
image at `:beta` **and** enable **Updater → Include Beta Releases** in the
app settings. `:latest` users never receive betas, regardless of that
toggle.

## Test infrastructure

| Script | Purpose |
|---|---|
| `pytest tests/unit/ -q` | All unit tests (see PYTHONPATH note below) |
| `ruff check .` | Linting |
| `./scripts/test-local.sh` | Full Docker container test |
| `scripts/check_test_traps.py` | False-green guard — stage 2 of `make verify` |
| `scripts/check_conformance.py` | Design-system drift gate |
| `scripts/mutation_changed.py` | Mutation testing scoped to changed files |
| `scripts/backup.sh` | Prod DB + settings snapshot (pre-deploy and nightly) |

Each of these is itself unit-tested (`tests/unit/test_check_test_traps.py`,
`test_check_conformance.py`, `test_mutation_changed.py`, `test_backup_script.py`)
— a guard script that silently stops guarding is the exact failure mode they
exist to prevent, so they do not get to be the untested part of the suite.

- Unit tests use `pytest` + the `tmp_path` fixture — no Docker needed locally.
- SQLiteAdapter tests instantiate against a temp path:
  `adapter.create(str(tmp_path / 'name'))`.
- `test_api_auth.py`, `test_fastapi_web.py`, `test_security.py` run locally too —
  `httpx` is installed in `.venv`, so run them via `.venv/bin/python -m pytest`.
- CI matrix: Python 3.10, 3.11, 3.12, 3.13.
- Note: a bare `pytest tests/unit/ -q` may hit import errors for tests touching
  vendored `libs/` — `make test-py` sets `PYTHONPATH=libs`. Prefer `make verify`
  / `make test-py`, or add the prefix if invoking pytest directly.

## QA process

- Test plan: `QA/QA_TEST_PLAN.md`
- Findings: `QA/QA_FINDINGS.md`
- Session logs: `QA/QA_SESSION_YYYY-MM-DD.md`

Run through core flows before any release: add movie, view detail,
filter/search wanted list, settings tabs, searcher/downloader connections,
suggestions.
