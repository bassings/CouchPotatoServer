# Audit remediation, 2026-11-11

## Objective

Resolve every finding from the whole-repository audit of 2026-11-11 (audited at
`1454367d1`; claims re-checked against `0b6b9a478` on 2026-11-11), in the order the
audit recommends: safety net, then critical security and correctness, then
high-leverage improvements, then polish. Every finding is either mapped to a
task below or listed under "Not fixing" with the reason.

Production deployment is outside this plan. Betas publish per merge as usual.

## Owner decisions this plan is built on (Scott, 2026-11-11)

1. The project is open to anyone. Findings are rated for public users.
2. Every rename-chain listener matters; **Plex rescan goes first**.
3. **No-password installs stay supported.** The wizard does not gain a
   mandatory password. The `Host` allow-list (T5) is therefore the fix for the
   DNS-rebinding exposure and is not optional.
4. The source-archive self-updater is **deleted**, not repaired.
5. **SonarQube-driven sweeps are paused until M1 is merged.** `make sonar`
   may still run after merges as reporting; nothing acts on it.
6. Library-size target: recommended 5,000 movies, paged 50 per request,
   measured at 500 / 5,000 / 20,000. **Not yet confirmed by Scott**; T18
   records the baseline and T19 does not start until the target is confirmed.

Decisions taken after the planning cycle (Scott, 2026-11-11):

7. The planning cycle's ordering corrections are applied, T15 is split into
   T15, T30 and T31, and the defects it surfaced that the audit missed get
   tasks: T32 (`Plugin.createFile` deletes the existing file on a failed
   overwrite) and T33 (a part-finished CodernityDB migration is opened as
   complete). The third, `scripts/backup.sh` skipping `config.ini` on the
   corrected compose layout, is folded into T2 by AC-DATA-3.
8. The vetoes on regenerating coverage (F-T5) and on the informational type
   checker (half of F-O1) are accepted. Both are listed under "Not fixing".
9. T20 is reversed: API routes stay serialised by default with a tested
   opt-out (AC-DATA-25), and T20 runs only if T18's measurements show
   same-route queuing is a real cost.
10. T29 (splitting `couchpotato/__init__.py`) is cut. F-A2 moves to "Not
    fixing".
11. T17, T18 and T24 no longer wait for the rename chain.
12. Docs-only and config-only tasks keep the full standing criteria. The
    simplicity lens's proposed exemption is declined.

## Standing acceptance criteria (apply to every task)

- TDD per CLAUDE.md hard rule 1, delivered through `/tdd-task`. The failing
  test is confirmed RED for the right reason before implementation.
- Every new test or guard is proven load-bearing per hard rule 10: break what
  it guards, watch it fail, restore by file copy (never `git checkout`),
  confirm by hash that the mutation landed and that the restore is
  byte-identical, and clear `__pycache__` before trusting the result.
- `make verify` green locally before push. Local review gate per hard rule 3.
- A UI change updates the E2E specs named in hard rule 5, in both themes and
  at phone width.
- Dependencies triaged before each PR is raised.
- Tasks marked **needs spec** get their own `specs/` file from
  `SPEC-TEMPLATE.md` and a `/plan-cycle` run before `/tdd-task`. The draft
  criteria here are the starting point, not the contract.
- Audit claims marked "reported, not re-verified" below must be re-verified
  against the tree as the first step of the task. If the claim is wrong, the
  task closes with the evidence and no code change.

## Finding index

Finding ids are prefixed `F-` to keep them distinct from task ids.

| Finding | Severity | Summary | Task |
|---|---|---|---|
| F-T1 | High | Nightly CI red four nights (Trivy, fixable zlib finding); no alert | T1 |
| F-T2 | High | `docker-compose.yml` omits the `/data` mount; the database lands in an anonymous volume | T2 |
| F-S1 | High | Auth off by default, binds `0.0.0.0`, no `Host` validation, api_key embedded in pages | T5 |
| F-S2 | High | `nzbget.removeFailed` runs `shutil.rmtree` on a path from the downloader response with no containment; per-file `os.unlink`/`os.rmdir` on downloader-supplied paths at `rtorrent_.py:553` | T3, T6 |
| F-A1 | High | `renamer.before` / `renamer.after` have no fire site; seven listeners plus every notification provider's rename hook are dead | T4, T11 to T14 |
| F-P1 | High | `Media.list` parses the whole library several times and issues several reads per movie; UI requests it unpaginated | T18, T19 |
| F-S3 | Medium | `PrivacyFilter` misses URL-embedded credentials; `exc_text` gets path scrubbing only | T7 |
| F-S4 | Medium | Third-party Actions pinned by tag in jobs that can publish images | T9 |
| F-S5 | Medium | api_key cannot be rotated; service worker caches pages containing it; logout does not clear the cache | T21 |
| F-S9 | Medium | `deleteFolder` can target the watch folder itself; "junk only" is a substring test | T3, T6 |
| F-Q1 | Medium | About 40 handlers catch CodernityDB `RecordNotFound`/`RecordDeleted`, which `SQLiteAdapter` never raises | T15, T31 |
| F-Q2 | Medium | `release/main.py:701` treats any read error as "absent" and inserts; identifier index is non-unique | T8 |
| F-Q3 | Medium | Broad `except Exception` on data paths hides failures (`core/media/_base/searcher/main.py:204`, `core/loader.py:117`, `core/media/_base/media/main.py:892`; the audit also cited `core/event.py`, where the handler-failure logging is T11's under AC-OPS-10) | T16, T11 |
| F-P2 | Medium | `with_doc=True` reads each document twice | T19 |
| F-P3 | Medium | One lock per API route serialises same-route calls | T20 |
| F-P4 | Medium | `fix_release_quality` runs ungated on every boot | T17 |
| F-A2 | Medium | `couchpotato/__init__.py` is a 1,714-line god module; core imports `get_db` from the web layer | Not fixing |
| F-T4 | Medium | Python mutation testing covers `sqlite_adapter.py` only | T27 |
| F-T5 | Medium | `coverage.xml` stale (2026-09-21); lowest large files include `nzbget.py`, `core/database.py`, `updater/main.py` | T3 (tests only); regeneration not fixing |
| F-D1 | Medium | Python deps version-pinned, not hash-locked; transitives float | T24 |
| F-O1 / F-Q5 | Medium | No type checker; ruff targets `py310` on a 3.15-only codebase | T25 (ruff target); type checker not fixing |
| F-DOC1 | Medium | README stale (dead badge, test count, "no vendored libraries", v3.0.0 headline); CHANGELOG stops at v3.4.0 | T23 |
| F-DOC3 | Medium | `docs/technical-debt.md` buries live items under review narrative; several stale entries | T23 |
| F-S6 | Low | Login shares the general 300/min rate limit | T22 |
| F-S7 | Low | api_key compared with `!=` / `startswith` | T22 |
| F-S8 | Low | `/getkey` takes `md5(password)` in a GET query string; `p`/`u` not redacted | T7, T22 |
| F-A4 | Low | Dead second migration path (`db/factory.py`, `codernity_adapter.py`, `db/migrate.py`) loads CodernityDB at start | T30 |
| F-P5 | Low | `idx_notification_unread` predicate does not match the query | T28 |
| F-D2 | Low | `bencodepy` declares "GPLv2" against GPL-3.0-or-later; "only" unverified | T24 |
| F-O2 | Low | Healthcheck fetches `/`; no real health endpoint | T26 |
| F-O3 | Low | `make verify` does not cover image scan, secret scan or CodeQL; docs say "mirrors CI" | T23 |
| F-DOC2 | Low | Rollback runbook cites stale Dockerfile line numbers | T23 |
| (decision 4) | n/a | `SourceUpdater` crashes on every attempt (`cp.source_url` unhandled) | T10 |
| F-NEW-1 | Critical | `Plugin.createFile` unlinks the existing destination when an overwrite fails (`couchpotato/core/plugins/base.py:117-128`); found at planning | T32 |
| F-NEW-2 | High | A CodernityDB migration that dies part-way leaves a database the next boot opens as complete; found at planning | T33 |
| F-NEW-3 | Medium | `scripts/backup.sh` skips `config.ini` on the corrected compose layout; found at planning | T2 |

### Not fixing

| Finding | Reason |
|---|---|
| F-A3: `Env` global state, import-time registries | Inherited design; `tests/unit/test_event_wiring.py` contains the risk. A rewrite costs more than it returns. |
| F-T6: source-reading and mock-heavy tests | Rewriting working tests buys nothing. New tests are behavioural; existing ones stay. |
| F-S10: shipped public TMDB / fanart.tv keys | Deliberate, recorded in `docs/technical-debt.md`; reversing it broke users on 2026-07-31. |
| CSRF, api_key in URL | Already recorded as accepted debt. T5 and T21 reduce the exposure; neither is re-opened here. |
| F-T5: stale `coverage.xml` | Regeneration vetoed at planning (AC-SIMP-5): nothing consumes the output. The coverage gap that mattered, the delete paths, is closed by T3's tests. Decision 8. |
| F-O1 / F-Q5, type-checker half | Vetoed at planning (AC-SIMP-11): an informational report nothing acts on. The ruff target half stays in T25. Decision 8. |
| F-A2: `couchpotato/__init__.py` god module | T29 cut (decision 10): XL, no behaviour change, and the same re-export breakage class as the #148 regression. The core-imports-web-layer edge it causes stays open; T23 adds it to the live items in `docs/technical-debt.md`. |

## Task detail

Amended 2026-11-11 after the planning cycle. The numbered criteria under
"Acceptance criteria" are the contract wherever they are stricter than, or
contradict, the draft text here. The amendments that change a task's scope:

- **T1:** the alert cannot be proven by a branch run, which never takes the
  schedule-only path (AC-QA-11, AC-OPS-1). Prove it the way those criteria
  state. The alert covers `ci.yml`, `mutation.yml` and `codeql.yml`. Checked
  2026-11-11: the current upstream `python:3.15-alpine` (amd64) still ships
  `zlib-1.3.2-r1`, so a digest bump alone does not clear the finding; the
  remedy is the runtime `apk` version floor (AC-SEC-17).
- **T2:** also fixes `scripts/backup.sh` for the corrected layout (AC-DATA-3).
- **T3:** "regenerate coverage" is vetoed (AC-SIMP-5). Tests only.
- **T5:** bare LAN hostnames and `.local` names are in scope for the
  allow-list design, and the setting must not lock the operator out mid-edit
  (AC-PROD-3, AC-A11Y-6, AC-A11Y-7).
- **T9:** the Dependabot configuration step is vetoed as already true
  (AC-SIMP-3).
- **T15** is split. T15 keeps the first-party `DocumentNotFound` and the
  handler conversion (AC-QA-23 first sentence, AC-DATA-11, AC-DATA-12,
  AC-ARCH-13). **T30**
  deletes `db/factory.py`, `codernity_adapter.py` and `db/migrate.py` with
  their tests, and the stale `db/__main__.py` (the `db/__init__.py` sentence
  of AC-SEC-25, AC-DATA-13, AC-PROD-10, AC-OPS-13, the file half of
  AC-SIMP-8, the T15 clause of AC-QA-37). The migration script names none of
  the deleted files, but it imports `couchpotato.core.db.sqlite_adapter`,
  which runs `db/__init__.py`, which imports `codernity_adapter` and
  `factory`. Edit `db/__init__.py` in the same change as the deletions, or
  the migrator fails on import, and so does every boot, because
  `runner.py` imports `sqlite_adapter` on each start. Effort S. Risk medium: it borders the migration path. **T31**
  removes the remaining live CodernityDB imports and index subclasses and
  adds the AST import guard (AC-ARCH-15, the guard in AC-QA-23, the
  `sys.modules` sentence of AC-SEC-25, the grep half of AC-SIMP-8). Effort
  M. Risk medium. A criterion that names T15 binds whichever of the three
  delivers the behaviour it describes; AC-OPS-19 binds all three and T33.
- **T7:** also covers `runHandler` in `couchpotato/core/event.py`, which
  joins T7's files. Outside dev mode it appends `Env.all()` (application
  and data directories, start-up arguments and options) to its ERROR
  record. Measured 2026-11-11 through the real `PrivacyFilter`: Docker and
  NAS-style paths reach the log unchanged, and under a home directory only
  the `/home/<user>` or `/Users/<user>` prefix is replaced. It also
  `print`s the exception message and full traceback to stdout, which never
  passes through the filter. The dump is directory layout, not credentials;
  an exception message carrying a URL with a key in it would reach stdout
  unredacted (read, not reproduced). T7 removes the dump and the prints, or
  routes both through the filter, with a test for each. T10 edits a
  different region of the same file.
- **T16:** three sites, not four. T16 changes nothing in `event.py`
  (AC-ARCH-12): the catch the audit cited there cannot be reached by a
  listener registered through `addEvent`, and the logging improvement is
  T11's (AC-OPS-10).
- **Event dispatch, as measured (2026-11-11), for T11's spec.** Two reviewers
  independently removed catches from in-memory copies of `event.py` with two
  listeners registered through `addEvent`, the first raising:

  | Catches removed | Second listener runs | Exception reaches the caller |
  |---|---|---|
  | none | yes | no |
  | `createHandle`'s only | yes | no |
  | `fireEvent`'s dispatch-loop only | yes | no |
  | both of the above | no | no |
  | both, and `fireEvent`'s outer catch | no | yes |

  Also measured or read: `runHandler` logs and re-raises, and `createHandle`
  catches, so a failure produces two ERROR records today and the second
  already contains the event name and the handler's repr. `Renamer.scan()`
  wraps each group in its own `except Exception`, so a test driven through
  `scan()` cannot see an exception escaping `_processGroup`. The renamer
  imports `fireEvent` by name, and `fireEventAsync` does not route through
  that name. The automatic rename path writes no `done` status itself today.
  The writer for a renamed file is manage's `renamer.after` listener
  (`after_rename` in `plugins/manage.py`, priority 110, so it runs after
  Plex at the default 100), through `scanFilesToLibrary` and `release.add`;
  it is dead today because the event never fires. Whether T11 writes the
  status in the renamer before firing (AC-ARCH-9) or leaves it to that
  listener is for T11's spec, and the choice decides whether AC-QA-18 (a)
  can be tested separately from (b): if a listener is the writer, a failing
  Plex listener leaves `done` written through isolation alone, with or
  without a renamer guard.
- **T19:** the library page's filter, chips, count and Select All run in the
  browser over the full list today and must keep working under paging
  (AC-DESIGN-9 to AC-DESIGN-15, AC-A11Y-8 to AC-A11Y-11).
  Before delegating T19 the conductor raises the decision 6 confirmation
  through `.claude/blocked-on-human`; T19 starts only once the conductor log
  records the owner's answer.
- **T20:** reversed. Serialised stays the default with a tested opt-out
  (AC-DATA-25), and the task runs only if T18 shows same-route queuing is a
  real cost; otherwise it closes with the measurement and no code change.
- **T23:** delete the review narratives and the test count instead of moving
  or correcting them (AC-SIMP-10). Also records the F-A2 core-imports-web-layer
  edge as a live item in `docs/technical-debt.md`.
- **T25:** ruff target only. The type checker is vetoed (AC-SIMP-11).
- **T28:** must change the index on existing installs, not only in
  `schema.sql` (AC-DATA-28).
- **T26:** `/healthz` is not exempt from the host check; AC-SEC-36 and
  AC-SEC-4 override the "loopback only" wording below.
- **T29:** cut (decision 10). Its text below is retained as a record only.
  AC-DATA-29 and AC-ARCH-24 are lapsed.
- **T32 (new).** `Plugin.createFile` writes to a temp file in the same
  directory and `os.replace`s it; a failed write leaves a pre-existing file
  byte-identical and never unlinks the destination. The artwork path does
  not use `createFile`: `metadata/base.py:120-130` copies with
  `shutil.copy2` and `shutil.copyfile` straight onto the destination, so T32
  makes that copy atomic too (the atomic-write sentences of AC-DATA-18,
  which cover metadata and artwork; its user-created-sidecar sentence stays
  with T13). Files: `couchpotato/core/media/movie/providers/metadata/base.py`,
  `couchpotato/core/plugins/base.py`, tests. Lands before T13. Effort S.
  Risk low.
- **T33 (new).** A CodernityDB migration killed after the SQLite database is
  created and before the rename is retried into a fresh destination or
  refused at the next boot; the partial database is never opened as complete
  (AC-DATA-14). The same state follows an ordinary exception in the
  migration script, which returns non-zero without removing the partial
  file, so a forced exception is enough to reproduce it; do that first.
  Files: `couchpotato/runner.py`, `scripts/migrate_codernity_to_sqlite.py`,
  tests. Effort M. Risk medium: this is the irreplaceable tier.

### M0: safety net

**T1. Restore the nightly build and alert on failure.** F-T1.
Files: `Dockerfile`, `.github/workflows/ci.yml`, `mutation.yml`, `codeql.yml`.
Acceptance: the Trivy step passes on the rebuilt image; the scheduled run has
a step that notifies on failure, proven by a deliberately failed dry run on a
branch; `specs/` records the digest bump decision. Re-verify the cause first
(reported: zlib CVE-2026-4738, fix 1.4-r0). Effort S. Risk low.

**T2. Mount `/data` in the shipped compose file.** F-T2.
Files: `docker-compose.yml`, a unit test that parses it.
Acceptance: `./data:/data` present; the `/config` comment no longer claims the
database; a test fails if either `VOLUME` path from the `Dockerfile` has no
bind mount in `docker-compose.yml`; `UPGRADING.md` tells existing users how to
find and move a database stranded in an anonymous volume. Effort S. Risk low.

**T3. Pin today's destructive-delete behaviour and regenerate coverage.**
F-S2, F-S9, F-T5.
Files: `tests/unit/` only, plus the regenerated reports (untracked).
Acceptance: characterisation tests against `tmp_path` for
`NZBGet.removeFailed`, the rTorrent removal path and
`CleanupMixin.deleteFolder`, covering the normal case and hostile cases (path
equal to the root, an ancestor of the root, outside the root, a symlink that
escapes, a loose file at the top of the watch folder). Hostile cases are
`xfail(strict=True)` naming T6. No production code changes. `make coverage`
re-run and the current lowest-covered files recorded in the conductor log.
Effort M. Risk low.

**T4. Contract test for the rename-completion chain.** F-A1.
Files: `tests/unit/`.
Acceptance: one test drives the real `Renamer.scan()` against `tmp_path` and
asserts `renamer.after` then `renamer.before` reach a registered probe
listener with the payload keys each in-tree listener reads. Marked
`xfail(strict=True)` naming T11 and T14, so it fails the build the moment the
chain starts firing and must be un-marked then. Effort S. Risk low.

### M1: critical security and correctness

**T5. Validate `Host` when authentication is off.** F-S1. **Needs spec.**
Files: `couchpotato/__init__.py`, `couchpotato/core/_base/_core.py`
(new `allowed_hosts` setting), settings UI, an error template, E2E.
Draft acceptance: with auth off, a request whose `Host` is not localhost, an
IP literal, or a configured name is refused with 400 and a page naming the
setting; with auth on, behaviour is unchanged; `X-Forwarded-Host` is honoured
only from a trusted proxy; the wizard is not changed (decision 3); the
refusal page passes axe in both themes at phone width. Ships in a beta before
any promotion. Effort M. Risk medium: reverse-proxy users with a custom
domain and no password are refused until they add the name.

**T6. Containment guard on every recursive delete.** F-S2, F-S9. **Needs
spec.** (needs: T3)
Files: a new first-party helper, `couchpotato/core/downloaders/nzbget.py`,
`couchpotato/core/downloaders/rtorrent_.py`,
`couchpotato/core/plugins/renamer/cleanup.py`, and a structural test.
Draft acceptance: one helper resolves target and root with `realpath` and
refuses when the target is the root, an ancestor of it, outside it, or a
symlink; every `shutil.rmtree` in `couchpotato/` goes through it, enforced by
a test that fails on an unguarded call; `rmtree(path, True)` loses its
ignore-errors flag; a refusal logs through `PrivacyFilter`; T3's hostile
cases pass and their `xfail` markers are removed. A downloader that reports a
path from inside its own container is refused, not remapped. Effort M. Risk
medium: a refusal leaves failed downloads on disk, which is the cheap tier.

**T7. Redact URL credentials and tracebacks in logs.** F-S3, part of F-S8.
Files: `couchpotato/core/logger.py`, `couchpotato/core/event.py` (`runHandler` only).
Acceptance: `scheme://user:pass@host` is redacted in `msg`, `args` and
`exc_text`; every existing redaction pass also runs over `exc_text`; `p` and
`u` join the query-string redaction list; a test reproduces the NZBGet
`ProtocolError` case end to end through the real filter. Effort S. Risk low.

**T8. Stop inserting a duplicate release on a read error.** F-Q2.
Files: `couchpotato/core/plugins/release/main.py`.
Acceptance: the handler at `:701` catches the adapter's not-found error only;
a simulated `sqlite3.OperationalError` on the lookup propagates and inserts
nothing. Effort S. Risk low.

**T9. Pin GitHub Actions to commit SHAs.** F-S4.
Files: `.github/workflows/*.yml`, `.github/dependabot.yml`, a unit test.
Acceptance: no third-party action is referenced by tag or branch; a test
fails on a non-SHA `uses:`; Dependabot is configured to update SHA pins.
Effort S. Risk low.

**T10. Delete the source-archive updater.** Decision 4.
Files: `couchpotato/core/_base/updater/main.py`, `couchpotato/core/event.py`
(`cp.source_url` leaves `OPTIONAL_EVENTS`), `docs/technical-debt.md`, tests.
Acceptance: `SourceUpdater` and its selection branch are gone; an install
with no `.git` outside Docker gets the notify-only behaviour; the
`OPTIONAL_EVENTS` stale-entry test passes; whether `release-to-prod.yml`
keeps attaching source archives is checked and recorded, not assumed.
Effort S. Risk low.

**T11. Rename chain, slice 1: payload and Plex.** F-A1. **Needs spec**
(re-baseline `specs/RENAMER-EVENT-CHAIN.md` first; it describes a 234-line
renamer and the file is now 2,337 lines). (needs: T4, T6)
Files: `couchpotato/core/plugins/renamer/main.py`,
`couchpotato/core/notifications/plex/main.py`,
`couchpotato/core/plugins/manage.py`, `couchpotato/core/event.py`.
Draft acceptance: `_processGroup` builds the `group` payload and fires
`renamer.after` after a successful move; only `Plex.addToLibrary` and
`manage`'s rescan are live on it in this slice, the rest stay gated; a
listener that raises neither undoes nor blocks a completed move; a release
reaches `status: done`. Effort L. Risk high.

**T12. Rename chain, slice 2: notifications, Synology, scripts.** F-A1.
(needs: T11)
Draft acceptance: every notification provider's rename notification fires
once per completed rename and honours its existing on/off settings; the
script notifier's path setting is validated before it can execute anything.
Effort M. Risk medium: this slice starts running external commands again.

**T13. Rename chain, slice 3: metadata and trailers.** F-A1. (needs: T11)
Draft acceptance: `.nfo`/artwork written beside the placed file through the
T6 helper's containment rules for writes; trailer search runs when enabled.
Effort M. Risk medium.

**T14. Rename chain, slice 4: subtitles, and close the gap.** F-A1.
(needs: T12, T13)
Draft acceptance: `renamer.before` fires before the move and subtitle files
travel with the movie; both names leave `UNFIRED_EVENTS` and
`HANDLERS_REACHABLE_ANOTHER_WAY` is corrected; T4's `xfail` is removed; the
renamer entry in `docs/technical-debt.md` is closed. Effort M. Risk medium.

### M2: high-leverage improvements

**T15. First-party not-found error; remove live CodernityDB imports.** F-Q1,
F-A4. (needs: T8)
Acceptance: `SQLiteAdapter` raises `DocumentNotFound(KeyError)`; no module
outside the migration script imports from `libs/CodernityDB`, enforced by a
test; `db/factory.py`, `codernity_adapter.py` and `db/migrate.py` are deleted
with their tests after confirming `scripts/migrate_codernity_to_sqlite.py`
does not use them; `media.get` on a missing id takes its not-found branch.
Effort M. Risk medium.

**T16. Narrow the three data-path catch-alls.** F-Q3.
Acceptance: `searcher/main.py:204`, `loader.py:117` and
`media/main.py:892` each catch named exceptions or log at error and re-raise;
each has a test showing a real failure is now visible. One PR per site if any
changes behaviour a caller depends on. Effort M. Risk medium.

**T17. Run `fix_release_quality` once per install.** F-P4.
Acceptance: gated by a stored property in the same manner as
`_run_orphan_cleanup`; a second boot does not call it. Effort S. Risk low.

**T18. Measure the library list.** F-P1.
Acceptance: a seeded benchmark at 500, 5,000 and 20,000 movies records
`media.list` wall time and statement count on the current code, in the
conductor log. No production change. Scott confirms or amends the target in
decision 6 from these numbers. Effort S. Risk low.

**T19. Rewrite the library list.** F-P1, F-P2. **Needs spec.** (needs: T18)
Draft acceptance: id-only projection, set membership, one batched fetch,
server-side paging at 50; `with_doc=True` reuses the row in hand; the UI pages
or scrolls incrementally with E2E updated; the confirmed budget from T18 is
enforced as a test. If T18 shows the current code already meets the target at
5,000, this task shrinks to paging only. Effort L. Risk medium.

**T20. Make per-route API locks opt-in.** F-P3. (needs: T19)
Acceptance: `addApiView` takes a flag; only routes that need serialising set
it, each with a stated reason; two concurrent `media.list` calls overlap in a
test; the concurrency rules in the existing cross-route notes still hold.
Effort M. Risk medium.

**T21. api_key rotation and cache hygiene.** F-S5. **Needs spec.**
(needs: T22)
Draft acceptance: an authenticated action regenerates the key and takes
effect without a restart; the service worker stops precaching HTML that
contains the key; logout clears Cache Storage; HTML responses send
`Cache-Control: no-store`. Effort M. Risk medium.

**T22. Authentication hardening.** F-S6, F-S7, F-S8. (needs: T5)
Acceptance: auth routes get their own small rate-limit bucket with back-off,
keyed so one client cannot lock out another behind a shared proxy address;
api_key comparisons use `hmac.compare_digest`; `/getkey` is POST-only or
removed, decided in the PR with evidence of who calls it. Effort S. Risk low.

### M3: quality and polish

**T23. Documentation refresh.** F-DOC1, F-DOC2, F-DOC3, F-O3. (needs: T14)
Acceptance: README "What's New", badge, test count and vendored-library claim
corrected and the notification list matches what fires; CHANGELOG policy
decided (maintain or point at GitHub releases); `docs/technical-debt.md` cut
to live items with the review narratives moved to `docs/` history and the
stale entries the audit listed corrected; the rollback runbook references
instruction names, not line numbers; the CLAUDE.md commands table states what
`make verify` does not cover. Effort M. Risk low.

**T24. Hash-locked Python dependencies; confirm bencodepy's licence.** F-D1,
F-D2.
Acceptance: a generated lock with hashes; the image installs with
`--require-hashes`; `pip check` clean; Dependabot still proposes updates;
bencodepy's licence text read and the outcome recorded (keep, or replace).
Effort M. Risk medium.

**T25. Type checker, informational; ruff target to 3.15.** F-O1, F-Q5.
Acceptance: pyright (basic) runs over `couchpotato/core/db` and
`couchpotato/core/event.py` in `make verify` as a non-blocking report; ruff
`target-version` matches the shipped runtime, with any newly raised findings
fixed or individually justified. Effort M. Risk low.

**T26. Real health endpoint.** F-O2.
Acceptance: `/healthz` performs a database read and reports scheduler state,
is exempt from auth and from T5's host check for loopback only, leaks nothing
beyond ok/not-ok; the Dockerfile `HEALTHCHECK` uses it. Effort S. Risk low.

**T27. Widen Python mutation scope.** F-T4. (needs: T6)
Acceptance: `renamer/mover.py`, `renamer/cleanup.py` and the T6 helper join
`[tool.mutmut] source_paths`; survivors triaged per
`when-a-mutation-survives`; the nightly stays inside its time budget.
Effort S. Risk low.

**T28. Fix the unread-notification index predicate.** F-P5.
Acceptance: index predicate and query agree; `EXPLAIN QUERY PLAN` on a seeded
database shows the index used, asserted in a test. Effort S. Risk low.

**T29. Split `couchpotato/__init__.py`.** F-A2. **Needs spec; XL, to be
broken down by that spec.** (needs: T21)
Draft acceptance: auth/session and the app factory live in their own modules;
`get_db` moves out of the web layer so core no longer imports it from
`couchpotato/__init__.py`; the re-exports plugins depend on are preserved
(see `loader-silent-import-swallow`); no behaviour change, proven by the
existing suite plus the plugin import sweep. Effort XL. Risk medium.

## Acceptance criteria

Written by the planning cycle of 2026-11-11 against the tree at `1454367d1`.
Each criterion names the task it binds. Where a criterion here is stricter
than, or contradicts, the draft acceptance text under "Task detail", the
criterion is the contract. Tasks marked **needs spec** carry these criteria
into their own spec as the starting set.

### lens-security

- **AC-SEC-1:** T5: with auth off, a request carrying Host `evil.example` returns 400 on every route registered on the app. The test enumerates `app.routes` and mounts rather than a hand-written list, so `/`, `/new/...`, `/partial/*`, `/api/<key>/*`, `/getkey`, `/login`, `/logout`, `/static/*` and `/robots.txt` are all covered, and a route added later is covered automatically. The same 400 is returned for a missing or empty Host header.
- **AC-SEC-2:** T5: host matching is exact, never by prefix, suffix or substring. `localhost`, `127.0.0.1`, `[::1]` and any IP literal that `ipaddress.ip_address` accepts are allowed, with or without a port. Matching is case-insensitive and tolerates a trailing dot. `localhost.evil.example`, `127.0.0.1.nip.io`, `evil.example.localhost` and `allowedname.evil.example` (when `allowedname` is configured) are each refused with 400.
- **AC-SEC-3:** T5: `X-Forwarded-Host` (and `Forwarded: host=`) cannot satisfy the allow-list unless the TCP peer is in an explicit trusted-proxy setting, and that setting defaults to empty. A request from peer 192.168.1.50 carrying Host `evil.example` and `X-Forwarded-Host: localhost` returns 400. The same request from a configured trusted peer is allowed.
- **AC-SEC-4:** T5: the decision depends on the Host value only and is never relaxed because the peer is loopback. A request from peer 127.0.0.1 with Host `evil.example` returns 400.
- **AC-SEC-5:** T5: the refusal response contains neither the api_key nor `api_base`: rendering it with a realistic 32-character key set gives a body that does not contain that key. Any Host value it echoes is HTML-escaped and capped in length: a Host of `<script>x</script>` appears only in escaped form. The response sends `Cache-Control: no-store`. The log line for the refusal records Host via repr or with CR/LF stripped, so a Host containing CR LF produces exactly one log line.
- **AC-SEC-6:** T5: the new `allowed_hosts` setting defaults to empty. If a wildcard value (`*`) is supported at all, it is an explicit opt-out that logs a WARNING naming the DNS-rebinding exposure on every startup where it is set.
- **AC-SEC-7:** T6: the containment helper deletes nothing and returns a refusal when the target is: equal to the root; an ancestor of the root; outside the root; itself a symlink; a path with a symlinked component that resolves outside the root; equal to, an ancestor of, or inside the configured renamer `to` library root or any Manage library folder, even when that target lies inside the downloader or from-folder root; or when no root is configured (fails closed). Each case is checked with a whole-tree hash of tmp_path before and after, including from=`/x`, to=`/x/movies` with targets `/x/movies` and `/x/movies/Film (2020)`. (merges AC-DATA-6)
- **AC-SEC-8:** T6: the helper deletes the realpath it validated, never the caller's original string. A test that swaps a path component to a symlink between resolution and deletion (via an injected hook) finds that nothing outside the root was deleted.
- **AC-SEC-9:** T6: an rTorrent removal whose `file_item.path` is absolute or contains `..` resolving outside `torrent.directory`, or whose `torrent.directory` is outside the configured root, unlinks no file and removes no directory. A sentinel file placed at the traversal target survives.
- **AC-SEC-12:** T7: for records whose msg, args and exc_text contain `http://user:pass@host`, `https://user:p%40ss@[::1]:6789/x` and `ftp://u:p@h`, the output of both the console and file handlers contains neither the user nor the password, and still contains the host.
- **AC-SEC-13:** T7: every existing redaction pass (query list, bare list, exact list, api_key, home prefix) also applies to `exc_text`. A raised exception whose message contains the api_key and `token=abc` produces a log file with neither value.
- **AC-SEC-14:** T7: `?p=`, `&p=`, `?u=` and `&u=` values are redacted in msg and exc_text, and NZBGet's `xmlrpc.client.ProtocolError` with a credentialled URL, logged through the real `removeFailed` error path, leaves no password in the written log file.
- **AC-SEC-15:** T9: a unit test parses every `.github/workflows/*.yml` and every `action.yml` under `.github/` as YAML. It fails on any `uses:` whose ref is not exactly 40 lowercase hex characters, and that includes first-party `actions/*` and `github/*`. It excludes only local `./` actions and requires `@sha256:` on any `docker://` reference. Fixtures that must fail: `@v4`, `@main`, a 7-character short SHA, and a 40-character ref containing a non-hex character; a SHA followed by a version comment passes. Changing one real pin back to a tag is proven to make the test fail. (merges AC-QA-15)
- **AC-SEC-16:** T9: each pinned SHA carries a `# vX.Y.Z` comment, and at review `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` (peeled) resolves to exactly that SHA in the upstream repository. No pin points at a fork-network commit that the named tag does not reference.
- **AC-SEC-17:** T1: the fixable Trivy finding is cleared by shipping the fixed package: raise the version floor in the runtime `apk add` line (the existing idiom for `c-ares` and `libcrypto3`; zlib already has a floor there, `>=1.3.2-r1`, which rises to `>=1.4-r0`, and the stale comment beside it is corrected), or bump the base image digest if, and only if, the new base is shown to carry the fixed version. The image is inspected to confirm the fixed version is installed. No `.trivyignore` entry, `ignore-unfixed`, severity or exit-code change is added. Both `FROM` lines remain `@sha256:` pinned and identical. The failure-alert job declares job-level `permissions` limited to what it uses.
- **AC-SEC-18:** T10 (removal): the `zipfile` and `tarfile` imports and both `extractall` calls are gone from `couchpotato/core/_base/updater/main.py`. On an install with no `.git` outside Docker, on tmp_path, the notify-only updater is selected, and a POST to `updater.update` with the HTTP boundary patched to raise makes no network call and writes no file. (merges the behaviour half of AC-QA-16)
- **AC-SEC-19:** T12: T12 declares `needs: T5` in the Tasks list and does not merge before T5 is on master, because re-enabling `renamer.after` makes the settings-controlled `script.path` executable on unauthenticated installs.
- **AC-SEC-20:** T12: the script notifier executes only when `script.path` is an absolute path to a regular file (checked with lstat, so not a symlink) that is executable, owned by the process user or root, and not group- or world-writable. Otherwise it logs a WARNING and runs nothing. Popen keeps `shell=False` with list argv. A destination_dir containing spaces, `;` and `$(id)` reaches the script as one literal argv element.
- **AC-SEC-21:** T12: for every provider that sends to a third party, a `renamer.after` fired with a group containing a sentinel absolute path and file name produces outbound request URLs, headers and bodies that do not contain the sentinel. Local providers (script, synoindex, plex, emby, xbmc) are excluded by an explicit list. The test patches the provider's HTTP call and covers every module in `couchpotato/core/notifications/`.
- **AC-SEC-22:** T13/T14: every .nfo, artwork, trailer and subtitle file is written or moved only inside the placed movie's resolved directory, using the T6 containment predicate. A pre-existing symlink at the target name pointing outside that directory is not followed, and a destination folder that is a symlink escaping the library root results in no write outside the root: the outside file's hash is unchanged after the rename. (merges AC-QA-21)
- **AC-SEC-23:** T13/T14: with the metadata, trailer and subtitle providers disabled, a completed rename makes zero outbound HTTP requests. This is tested with the HTTP client patched to fail on any call.
- **AC-SEC-24:** T11: a Plex `addToLibrary` call with a token configured, logged at DEBUG, leaves no token value in the written log file.
- **AC-SEC-25:** T31 (first sentence), T30 (second sentence): starting the server process against a SQLite data directory (no legacy `database/` dir) leaves no module whose name starts with `CodernityDB` or `couchpotato.core.db.codernity_adapter` in `sys.modules`, checked in a subprocess after app creation. `couchpotato/core/db/__init__.py` no longer imports `codernity_adapter` or `factory`. (merges AC-OPS-12)
- **AC-SEC-26:** T19: the paging parameters of `media.list` are validated. Non-integer, negative or above-maximum `limit`/`offset` values (including `1;DROP TABLE media`) are rejected or clamped to a stated maximum. The SQL uses bound parameters only, and a test asserts the media table is intact after the hostile inputs.
- **AC-SEC-27:** T20: routes that change credentials or auth state (`settings.save`, the T21 rotation route (if T21 has not landed when T20 runs, T21 adds its route to this test), any password route) keep their serialisation, and a test asserts the lock is in force on each.
- **AC-SEC-28:** T21: within one process and with no restart, after rotation the old key returns 401 via the `X-Api-Key` header, the `/api/<old>/...` URL prefix, `nonblock/` routes and `file.cache/`, and the new key succeeds on each. The api_key captured as a `create_app` argument is no longer what requests are compared against.
- **AC-SEC-29:** T21: after rotation, a log record containing the new key is redacted by both the console and file PrivacyFilter instances, and the rotation's own log line contains neither the old nor the new key.
- **AC-SEC-30:** T21: the rotation route is POST-only (GET returns 404 or 405), requires the current session when auth is on or the current api_key, is refused cross-origin through the same check as `ORIGIN_CHECKED_API_ROUTES`, and its response sends `Cache-Control: no-store`.
- **AC-SEC-31:** T21 (removal): an E2E test visits `/`, `/wanted/`, `/available/`, `/add/` and `/settings/`, then reads every Cache Storage entry, and finds no response body containing the api_key. The HTML routes leave the precache list in `sw.js`. The cache names are bumped so `couchpotato-dynamic-v1` and `couchpotato-static-v1` from earlier installs are deleted on activation. The offline fallback no longer serves cached app HTML.
- **AC-SEC-32:** T21: every HTML response (UI pages, `/partial/*`, login, error pages) sends `Cache-Control: no-store`, asserted across the enumerated HTML routes. After logout, an E2E check finds Cache Storage empty.
- **AC-SEC-33:** T22 (removal): no api_key comparison in `couchpotato/` uses `==`, `!=`, `startswith` or `in`. An AST test fails on any comparison or `startswith` involving a name or attribute containing `api_key` outside `hmac.compare_digest`. The URL-prefix route extracts the first path segment and compares it with `hmac.compare_digest` on bytes. Re-introducing `!=` is proven to fail the test.
- **AC-SEC-34:** T22 (removal): `GET /getkey?u=..&p=..` returns 404 or 405 and never the key. If a POST form is kept, credentials travel in the body, the response sends `no-store`, and the route counts against the auth rate-limit bucket.
- **AC-SEC-35:** T22: the login bucket is keyed on the TCP peer unless the peer is in the T5 trusted-proxy setting. Twenty login attempts from one untrusted peer, each with a different `X-Forwarded-For`, are throttled as a single client.
- **AC-SEC-36:** T26: an unauthenticated `GET /healthz` returns only a fixed ok/not-ok body (no version, path, exception text, job names or counts). With the database read forced to fail, it returns not-ok, and the body is byte-identical across all not-ok causes. Any Host-check exemption is by exact path, not by peer address, and `/healthzx`, `/api/healthz` and `/healthz/../` gain no exemption. (supersedes the draft's "for loopback only"; merges part of AC-QA-34)
- **AC-SEC-37:** T2: UPGRADING.md states that the anonymous volume still holds a full copy of the database (password hash, api_key, library and history) after the move, and gives the command to remove it once the move is verified.
- **AC-SEC-38:** T24: every `pip install` in the Dockerfile uses `--require-hashes` against a lock covering every installed distribution, transitives included, with no secondary unhashed install. Altering one hash in the lock is proven to fail the image build.

### lens-qa

- **AC-QA-1:** T3/T4: every strict-xfail introduced by T3 and T4 declares `raises=AssertionError` (or a named project exception), and its body asserts the precondition (fixture built, scan or delete actually ran) before the guarded assertion. Deleting the fixture setup or making the call under test raise TypeError makes the test report FAILED rather than XFAIL.
- **AC-QA-2:** T4 is two tests, not one: `renamer.after` reaches a probe listener (strict xfail naming T11) and `renamer.before` reaches a probe listener before the move (strict xfail naming T14). Each drives the real `Renamer.scan()` over a tmp_path from-folder with a real movie-like file and asserts the payload keys each in-tree listener reads. After T11 lands, only the `renamer.after` test XPASSes and gets its marker removed.
- **AC-QA-3:** T3: characterisation for `CleanupMixin.deleteFolder` covers, against tmp_path: the normal case (only sample, .nfo and .jpg left, so it is deleted); folder equal to the watch root; an ancestor of the root; a path outside the root; a symlink inside the folder pointing outside it (the outside files survive); a loose file at the top of the watch folder; and a folder holding one real movie whose name contains "sample" or ".txt" (for example `Free.Sample.2019.1080p.mkv`). The last case is strict-xfail naming T6 because today it is deleted.
- **AC-QA-4:** T3: characterisation for `NZBGet.removeFailed` stubs only the RPC boundary (`history`, `editqueue`) and uses a real filesystem. Cases: DestDir inside the configured root (deleted); DestDir equal to the root; DestDir `/` or an ancestor; DestDir outside; DestDir a symlink escaping the root; DestDir a container-internal path that does not exist on the host. The test also asserts whether `HistoryDelete` was sent in each refused case.
- **AC-QA-5:** T3: characterisation for rTorrent `processComplete(delete_files=True)` covers what the code does there: the per-file `os.unlink` of `torrent.directory` joined with `file_item.path`, and the bottom-up `os.rmdir` walk. Hostile cases: a `file_item.path` containing `../` that escapes `torrent.directory`; an absolute `file_item.path`; `torrent.directory` equal to the root or to `/`; a symlinked file. Escapes are strict-xfail naming T6.
- **AC-QA-6:** T6: every T3 hostile case passes with its xfail removed. The out-of-root sentinel files are byte-identical before and after (checked by hash). Each refusal returns a defined value (False) and emits exactly one log record at warning or above, and that record passes through PrivacyFilter with no home path in it.
- **AC-QA-7:** T6: the structural guard is AST-based and fails on any of these in `couchpotato/` outside the helper: `shutil.rmtree`, `from shutil import rmtree` (including aliased) and `os.removedirs`. It also fails on any `os.unlink`, `os.remove` or `os.rmdir` in `couchpotato/core/downloaders/` outside the helper, except an explicit allow-list of self-created probe files (the blackhole and pneumatic test_file), each with a stated reason. Proven by adding each form to a scratch module and watching the guard fail, and by reverting rTorrent to today's code. (merges AC-SEC-10, AC-DATA-7 and the guard half of AC-ARCH-5)
- **AC-QA-8:** T6: the helper also refuses when root is empty or `/`. It accepts when root itself is a symlink to the real location (both sides go through realpath), and when the case differs only on a case-insensitive filesystem. Every refusal and acceptance case is a separate parametrised test id.
- **AC-QA-10:** T2: the compose test reads the `VOLUME` instruction from the Dockerfile, resolves `${CONFIG_DIR}` and `${DATA_DIR}` from the Dockerfile's own ENV/ARG, and fails if any resolved path lacks a bind mount in docker-compose.yml. It does not hardcode `/data`. Proven twice: by deleting the `./data:/data` line, and by adding a third VOLUME path to a copy of the Dockerfile.
- **AC-QA-11:** T1: the failure notification is proven by a run whose trigger satisfies the same `if:` condition the scheduled run uses. Either the condition includes `workflow_dispatch` and a dispatched run with a forced failing step produces the notification, or the evidence is a real scheduled run. A dispatched run that skips the notify step does not count as proof.
- **AC-QA-12:** T7: the tests feed the real PrivacyFilter through a real logging.Logger and handler, and assert on the formatted output string. Hostile inputs beyond AC-SEC-12: a password containing `@` and `:`; a user with no password; schemes scgi and http+xmlrpc. Non-cases that must be left alone: `?top=5` and `?up=1` are not redacted, because the `p`/`u` match is on the whole parameter name.
- **AC-QA-13:** T8: with a real SQLiteAdapter on tmp_path, (a) a missing identifier inserts exactly one release; (b) an existing identifier inserts none and updates quality; (c) `sqlite3.OperationalError` injected at the adapter's connection (not by mocking `db.get`) propagates, or is logged at error, and the release count is unchanged. Restoring `except Exception` makes (c) fail.
- **AC-QA-17:** T11: the probe `renamer.after` listener asserts at call time that the destination file exists and the source is gone. Moving the fireEvent call above `_moveRenamedFiles` makes the test fail. The event fires exactly once per successfully moved group; it fires zero times for a group whose move fails, for a group skipped for no media_info, and on a second scan of an already-processed folder.
- **AC-QA-18:** T11: two outcomes are the contract. (a) Caller safety: a failing `renamer.after` listener never undoes, masks or interrupts a completed move; the release still reaches its final status and the rest of that group's processing still runs. (b) Listener isolation: one failing listener never stops the listeners registered after it. How each is tested and proven load-bearing is designed in T11's own spec and planning cycle, against the facts in "Event dispatch, as measured" under Task detail. Three attempts to prescribe the mutation here each produced a test that could not fail, so this plan prescribes none.
- **AC-QA-20:** T12: with three notification providers registered, two enabled and one disabled, a single completed rename produces exactly one call to each enabled provider and zero calls to the disabled one. The script notifier, given each of a nonexistent path, a non-executable file and a relative path, never reaches the subprocess boundary (a stub that raises if called).
- **AC-QA-22:** T14: a fixture folder holds a movie plus `.srt`, `.en.srt`, `.forced.en.srt` and a subtitle belonging to a different movie in the same folder. The first three arrive beside the placed movie and the fourth does not move. `renamer.before` is observed before the source file is removed.
- **AC-QA-23:** T15: `media.get` on a missing id takes its not-found branch on a real adapter. The import guard is AST-based and fails on `import CodernityDB`, `from CodernityDB...`, `from libs.CodernityDB...` and an `importlib.import_module('CodernityDB...')` string anywhere in `couchpotato/` (proven by adding each form to a scratch module). The only permitted importer outside `libs/` is `scripts/migrate_codernity_to_sqlite.py`. (merges AC-ARCH-14)
- **AC-QA-25:** T16: for each site T16 changes, a test injects a real failure at that site and asserts, via caplog, an ERROR record containing the exception type, and asserts the documented outcome (re-raised or handled). Restoring the original catch-all makes that test fail. This binds the three sites T16 changes; `event.py` is not one of them (AC-ARCH-12).
- **AC-QA-27:** T18: the benchmark records media.list wall time (median of 5) and SQL statement count (via `sqlite3.Connection.set_trace_callback`) at 500, 5,000 and 20,000 seeded movies, with the seed, the machine and the commit stated in the conductor log.
- **AC-QA-28:** T19: the enforced budget is a statement-count ceiling per page request, which is deterministic. Any wall-time threshold is informational only. Paging tests cover: page 1, the last partial page, a page past the end (empty with a correct total), page 0 or negative and a limit above the maximum (rejected or clamped, as the spec decides), and that concatenating all pages yields every id exactly once.
- **AC-QA-29:** T20: overlap is proven without sleeps. Two concurrent `media.list` calls each block on a `threading.Barrier(2)` inside the handler and both complete. A route that keeps its lock deadlocks the same barrier test, which is caught by a bounded timeout and asserted as serialised. Both directions are tested.
- **AC-QA-30:** T5, through the real app with auth off: `evil.com@localhost` and a request with two conflicting Host headers are refused with 400, and `LOCALHOST:5050`, `localhost.` and a configured name are accepted. The check applies to page, API, static and service-worker routes. With auth on, the same refused inputs behave as before T5.
- **AC-QA-31:** T21: a JS unit test asserts the service worker's precache list contains no HTML route. HTML responses carry `Cache-Control: no-store` and hashed static assets do not.
- **AC-QA-32:** T22: the failed login one past the limit within the window from one client key returns 429, and a different client key in the same window is unaffected. The keying rule is named in the T22 PR and tested with two clients sharing one proxy address.
- **AC-QA-35:** T27: the nightly mutation job's budget is stated as a number (the measured baseline is 17 to 23 minutes over the last five runs) and enforced with `timeout-minutes` on the job in `mutation.yml`. The conductor log records the run URL and wall time of one full nightly after the scope is widened. Each surviving mutant in the newly added files is recorded with a triage outcome. (merges AC-OPS-18)
- **AC-QA-36:** T28: a test on a seeded tmp_path database runs `EXPLAIN QUERY PLAN` on the unread-notification query and asserts the plan names `idx_notification_unread`. Reverting the predicate makes it fail.
- **AC-QA-37:** Removals in the QA area: the strict-xfail markers on the T3 hostile cases (removed in T6) and on the two T4 tests (removed in T11 and T14 respectively) are gone, and no `xfail` in the repo still names a task this plan has closed. The SourceUpdater tests (T10) and the factory, codernity_adapter and migrate tests (T15) are deleted, not skipped.

### lens-simplicity

- **AC-SIMP-3:** T9 leaves `.github/dependabot.yml` byte-identical to master. Its existing `github-actions` ecosystem entry already updates SHA pins.
- **AC-SIMP-4:** T1: the failure notification uses only the workflow's built-in `GITHUB_TOKEN`. The T1 diff adds no `secrets.*` reference other than `GITHUB_TOKEN` and no new third-party `uses:` action.
- **AC-SIMP-5:** T3: the diff touches only paths under `tests/unit/`. Regenerating coverage and recording the lowest-covered files is not part of T3's acceptance.
- **AC-SIMP-7:** T10: `grep -rn 'SourceUpdater' couchpotato/` and `grep -n 'cp.source_url' couchpotato/core/event.py` both return no matches, and the T10 diff deletes more lines than it adds under `couchpotato/`.
- **AC-SIMP-8:** T31: `git grep -lE 'RecordNotFound|RecordDeleted' -- couchpotato/` returns no files (on 2026-11-11 it returns 15 tracked files, including `couchpotato/core/migration/fix_release_quality.py`; `git grep` so stale bytecode cannot match). T30: The files `couchpotato/core/db/factory.py`, `couchpotato/core/db/codernity_adapter.py` and `couchpotato/core/db/migrate.py` do not exist.
- **AC-SIMP-9:** T17 adds no new module and no generic run-once helper: the gate is an inline stored-property check of the same shape as `_run_orphan_cleanup`. The diff touches only `couchpotato/runner.py`, `couchpotato/core/migration/fix_release_quality.py` (to signal completion, as AC-DATA-22 requires) and test files. (file scope widened from the lens's wording to admit AC-DATA-22)
- **AC-SIMP-10:** T23: README.md contains no literal test count (no match for `[0-9]+ tests`). The review narratives removed from `docs/technical-debt.md` are deleted outright rather than moved, so T23 creates no new file under `docs/`.
- **AC-SIMP-11:** T25 is limited to the ruff target: `pyproject.toml` has `target-version = "py315"`. No pyright or mypy entry appears in `requirements*.txt`, `pyproject.toml`, `package.json` or the `Makefile`.
- **AC-SIMP-14:** Every `(needs: ...)` edge in the Tasks list matches the task's detail section, or the edge carries a one-line stated reason. In particular, T17, T18 and T24 are not gated on T14 unless a file overlap with T11 to T14 is named.
- **AC-SIMP-15:** Across the whole plan, no new top-level package name is added to `requirements.txt`, `pyproject.toml` dependencies or `package.json`. T24 may change how existing packages are pinned and hashed, but not which packages are installed.
- **AC-SIMP-16:** Removals this plan owes in the simplicity area: the source updater (AC-SIMP-7), the CodernityDB not-found handlers and the dead migration path (AC-SIMP-8), the `ignore_errors` argument on `rmtree` (AC-ARCH-6), the README test count and the technical-debt review narratives (AC-SIMP-10). Nothing else in scope is replaced.

### lens-product

- **AC-PROD-1:** T2: a user who installs from the shipped docker-compose.yml, adds a movie, then runs `docker compose down` followed by `docker compose up -d` still sees that movie in the library, and couchpotato.db exists under the host's `./data` directory.
- **AC-PROD-3:** T5: a no-password user who, after upgrading, reaches CouchPotato by a name not on the allow-list (a bare LAN hostname such as `nas`, an mDNS name such as `nas.local`, or a reverse-proxy domain) either is still served or gets a refusal page that shows the exact Host value refused, names the setting that allows it, and gives both ways to set it: from Settings via an address that is still accepted (IP or localhost), and without the UI (the config.ini section and key). An E2E test adds the name through each route and asserts the next request is served. The T5 spec records whether the machine's own hostname and its `.local` form are allowed by default.
- **AC-PROD-4:** T5: the CHANGELOG or release-note entry for the first beta containing T5 says, in plain words, that installs without a password reached by hostname or proxy domain will be refused until that name is added, and says how to add it. The entry ships in the same beta as the code.
- **AC-PROD-5:** T11: with the Plex notifier configured, a download the renamer moves into the library triggers exactly one Plex library refresh request with no operator action, and the release reaches status `done` even when the Plex call fails.
- **AC-PROD-6:** T12: a user with an enabled notification provider gets one rename notification for each completed rename. For a release under a manual-confirmation profile, the "downloaded, awaiting review" message and the rename message are two separate messages with different text, and neither is sent twice.
- **AC-PROD-7:** T11 to T14: each rename-chain slice that turns a dormant listener back on ships with a CHANGELOG or release-note line naming the behaviour that will start again (for example that configured post-rename scripts will run again after each rename), in the same beta as the code.
- **AC-PROD-8:** T13/T14: after a completed rename with the feature enabled, the movie's library folder contains the subtitle files fetched for it (T14) and the .nfo and artwork (T13). With each feature disabled, none of those files appear.
- **AC-PROD-10:** T30: no document in the repo tells users to run a command that no longer exists. `docs/reference/DATABASE_SCHEMA.md` stops citing `python -m couchpotato.core.db.migrate` and points at the surviving migrator, a grep of the repo for that invocation returns nothing, and every migration command documented in README.md, UPGRADING.md and `docs/` is executed once and runs. (merges AC-PROD-20; the first-start migration half is AC-DATA-13)
- **AC-PROD-11:** T10: on an install with no .git directory and not running in Docker, when a newer version exists the user sees an "update available" message that says where to get it. No "update now" or "install update" control or menu entry is offered. (merges AC-PROD-19)
- **AC-PROD-14:** T22: the `/getkey` decision record names the external clients checked for use of `/getkey` (searched outside this repo, with sources) and what they send. If the endpoint changes method or is removed, the CHANGELOG names the affected clients.
- **AC-PROD-15:** T11 to T14: each completed rename writes exactly one INFO record, visible on the in-app Logs page without debug enabled, containing only the event name, the media's internal id, and one outcome per listener (ok, failed or disabled). It contains no title, path, host or credential. A raising listener shows as failed. (merges AC-OPS-11; the media id replaces that criterion's release name, on privacy grounds)
- **AC-PROD-17:** Plan level: when the plan closes, the conductor log maps every F- id in the finding index either to the merged PR that closed it or to its "Not fixing" row, with none left unmapped.
- **AC-PROD-18:** Scope boundary: no task in this plan adds a mandatory password, a new step in the setup wizard, or any outbound telemetry or phone-home request. `couchpotato/ui/templates/wizard.html` and its handlers do not change except where a criterion names them, and no new outbound HTTP call is added outside existing provider and notifier code. (merges AC-DESIGN-6)

### lens-design

- **AC-DESIGN-1:** T5: the response to a refused Host is a standalone HTML page built on the same frame as `couchpotato/templates/login.html` (wordmark, bg-cp-card panel, h1 heading, a message block styled like `#login-message`, cp-* tokens). It shares that frame by template inheritance, include or the same renderer, not a copy of the markup. It is not a bare text, JSON or default FastAPI 400 body, and it is not a new layout component.
- **AC-DESIGN-2:** T5: the refusal page renders fully styled even though every other request carrying the refused Host is also refused. It loads no stylesheet, script, font or image from the refused origin. An E2E test requests a page with a disallowed Host and asserts two things: no same-origin subresource request is made, and the panel's computed background is the cp-card token, not the browser default.
- **AC-DESIGN-4:** T5: the refusal copy states, in plain words: (a) the address that was refused; (b) why it was refused (no password is set, so CouchPotato only answers on addresses it knows); (c) a way out that works without reaching the refused address, either opening CouchPotato by its IP or localhost and adding the name at the exact settings path shown in the settings UI, including the Advanced step if the field sits behind it, or setting a password; (d) the config.ini key name, for headless installs. A unit test asserts that the settings path in the copy matches the label, group and tab that `couchpotato/core/_base/_core.py` defines for `allowed_hosts`.
- **AC-DESIGN-5:** T5: the `allowed_hosts` settings field shows a label, plus a description saying it only applies while no password is set and giving one example value in the accepted format. A malformed entry is refused through the existing settings save-refusal path: an error toast names the bad entry, the field stays dirty and "Saved" is not shown. (the restart-or-immediate question is settled by AC-ARCH-3: immediate)
- **AC-DESIGN-7:** T10 (removal): on an install type whose updater cannot install an update (Docker, and the notify-only branch for installs with no .git), the Settings > Updates group renders no "Auto-Update" toggle. No control is left in that group whose setting that install type ignores. The `git_only` key in `couchpotato/core/_base/updater/__init__.py` is either read and enforced or deleted.
- **AC-DESIGN-8:** T10: on a notify-only install with an update available, the settings banner and the sidebar link name the available version and give a concrete next step in the same pattern as Docker's docker_message. Neither shows only a bare hash with no action.
- **AC-DESIGN-9:** T19: with server-side paging, the title filter, the status chips (All, Wanted, Available, Review) and the `#movie-count` text apply to the whole list, not just the loaded page. E2E on a seeded library of more than 100 movies: filtering for a title that exists only beyond the first page shows that movie on first view, each chip shows every matching movie in the library, and the count's total equals the number of movies. (merges AC-PROD-9)
- **AC-DESIGN-11:** T19: Select All and bulk actions state their scope exactly. The "N selected" text, the bulk Delete confirmation count and the number of `movie.delete` calls are always equal. Either Select All selects every matching movie, or its label says how many it selects. No state exists in which the confirmation names a number different from the number deleted.
- **AC-DESIGN-12:** T19: incremental loading has every state. Loading the next page appends the existing skeleton or spinner below the loaded cards without clearing them. With exactly 50 movies no control leads to an empty page. A failed page fetch shows the design-system Error state (exclamation-triangle, message and a retry control) below the loaded cards and keeps them. At 375px the load control is full-width.
- **AC-DESIGN-13:** T19 (removal): when the list request fails, the grid shows the design-system Error state, not "No movies found". The exception swallow in `partial_movies` in `couchpotato/ui/__init__.py`, which turns any failure into an empty list, is gone. A route test or E2E forces a `media.list` failure and asserts the error copy and the absence of the empty-state copy.
- **AC-DESIGN-14:** T19: a library of zero movies shows the ordinary empty state with no paging control. A library of one movie shows one card and no paging control. After a card or bulk action reloads the grid, focus does not fall to the body element and the user is not returned to page 1 with the acted-on movie out of view.
- **AC-DESIGN-15:** T19 (removal): the `#movie-count` total is no longer derived from the number of DOM cards in `wanted.html`. The count shown comes from the server's total for the current filter.
- **AC-DESIGN-16:** T21: there is exactly one "Regenerate API key" control, placed beside the read-only API Key field and styled as the README Danger or Ghost button. It opens a confirmation built on the existing dialog pattern in `partials/settings/modals.html`, not a new component. The confirmation copy says what stops working (apps and scripts using the current key stop working until given the new one). The confirm button is labelled "Regenerate key", not "OK". Cancel, Escape and a scrim click all leave the key unchanged.
- **AC-DESIGN-17:** T21: after a successful rotation, the API Key field shows the new key in the same tab without a manual reload or a fresh sign-in, a success toast confirms it, and the tab's next API action succeeds (E2E: rotate, then trigger a movie refresh). A failed rotation shows an error toast saying the key was not changed, and the field still shows the old key. (merges AC-PROD-13)
- **AC-DESIGN-18:** T21: a second open tab still holding the old key shows one message on its next API call, saying the API key was changed and offering a Reload action. It does not show a raw "HTTP 401" toast or a generic failure toast for each action.
- **AC-DESIGN-19:** T21 (removal): the plain-text "Offline" 503 body in `couchpotato/static/sw.js` is gone. With the server unreachable, a navigation shows a styled page (both themes, design-system tokens) saying CouchPotato cannot be reached and what to check. That page contains no api_key and is built into the worker or served from a keyless static asset, never from a cached app page. (constrained by AC-SEC-31)
- **AC-DESIGN-20:** T21: deploying the changed service worker does not show the "New version available! Reload to update?" confirm with misleading wording. Either the prompt does not fire for this change, or its copy says the app was updated and a reload is needed to finish.
- **AC-DESIGN-21:** T22: the rate-limited sign-in messages (`rate_limited` and `rate_limited_signout` in LOGIN_MESSAGES) state the actual remaining wait, including any back-off growth. Their "from this address" wording matches how the new auth bucket is keyed. A unit test renders the message after repeated failures and asserts both the wait and the wording.
- **AC-DESIGN-22:** T12: an invalid script-notifier path is refused through the existing save-refusal path. The error toast names the field by its label, not the raw key `path`, and says in plain words what is wrong (does not exist, not executable, or not in an allowed location). The value is not saved and "Saved" is not shown.
- **AC-DESIGN-23:** Removal scope: T5, T12 and T22 remove nothing on screen. The on-screen removals in this plan are exactly AC-DESIGN-7, AC-DESIGN-13, AC-DESIGN-15 and AC-DESIGN-19. If `/getkey` is removed in T22 it has no UI caller, so it has no design removal.

### lens-accessibility

- **AC-A11Y-1:** T5: an E2E spec in the accessibility project loads the Host-refusal page by requesting the real server under a Host the server refuses (for example a hostname mapped to 127.0.0.1 via a Chromium host-resolver rule), not by `page.route` or `route.fulfill` at an allowed origin. axe (wcag2a, wcag2aa, wcag21aa, wcag22aa tags) reports zero violations on it in light and dark colour schemes and at 375 CSS px width.
- **AC-A11Y-2:** T5: the refusal page renders legibly with every `/static/` and third-party request failing: its styling is inline in the response, its theme follows prefers-color-scheme (localStorage is per-origin and unavailable on the refused host), and every text node measures at least 4.5:1 (large text 3:1) against its rendered background under `page.emulateMedia` for both light and dark. (merges part of AC-DESIGN-3)
- **AC-A11Y-3:** T5: the refusal page has `<html lang="en">`, a non-empty `<title>` that states the request was refused, exactly one h1, its content inside a main landmark, and states in text (not colour or icon alone) the setting name and how to recover.
- **AC-A11Y-4:** T5: at 320 CSS px viewport width and at 200% zoom (1280px viewport), the refusal page has `document.documentElement.scrollWidth <= clientWidth`, so no horizontal scrolling is needed. (merges part of AC-DESIGN-3)
- **AC-A11Y-5:** T5: the allowed-hosts settings input has an accessible name containing "Allowed hosts" (a textbox role query for that name resolves exactly one element) and an accessible description, via aria-describedby, that contains the accepted format (separator and example).
- **AC-A11Y-6:** T5: the allowed-hosts field persists on commit (change or blur), not on the per-keystroke 500ms debounce: an E2E test that types a hostname with a 700ms delay between keystrokes observes zero settings save requests until the field is blurred, then exactly one save carrying the full value.
- **AC-A11Y-7:** T5: a rejected allowed-hosts value (a malformed entry, or a list that would exclude the Host the page is currently served on) is reported as visible text associated with the input via aria-describedby, the input carries `aria-invalid="true"` only while the error stands, and the error is announced exactly once (one mutation of one live region per rejection).
- **AC-A11Y-8:** T19: the control that loads the next page of the library is a native button with an accessible name stating what it does (for example "Show 50 more movies"), operable with Enter and Space, with a focus indicator measured at least 3:1 against the surface it is painted on (parentElement for an offset outline) in both themes, and a target of at least 44 by 44 CSS px. Loading further pages never depends solely on scroll position or IntersectionObserver.
- **AC-A11Y-9:** T19: after a page loads, (a) a card element that held focus before the load is the same DOM node afterwards (existing cards are appended to, not re-rendered), (b) `document.activeElement` is never `document.body`, and (c) a single polite live region is mutated exactly once with the new total shown. The loading skeleton's status region does not additionally announce for an append.
- **AC-A11Y-10:** T19 (removal): when the final page has loaded, the load-more button is removed from the DOM (not left disabled-but-focusable, not visually hidden only). If it held focus, focus moves to the first card added by that final load, asserted by `document.activeElement` identity.
- **AC-A11Y-11:** T19: with server-side paging, the "no movies match this filter" state and its announcement fire only when the filter matches nothing in the whole library (server-side result count 0), never because the match falls outside the loaded pages, and the count it shows is the server-side total. For a filter typed one character at a time the announcer is mutated at most once per settled filter value, not per keystroke. (merges AC-DESIGN-10)
- **AC-A11Y-12:** T21: the API-key regenerate control is a native button named "Regenerate API key". Its confirmation is a modal (role dialog or alertdialog, aria-modal true, aria-labelledby resolving to visible text) with initial focus on the non-destructive action, Tab and Shift+Tab confined to the dialog, and Escape cancelling. Focus returns to the regenerate button on both cancel and confirm. Success is announced once through the existing toast announcer. axe reports zero violations with the dialog open in both themes and at 375 CSS px.
- **AC-A11Y-13:** T22: the login rate-limited or back-off state is added as a rendered state in `tests/e2e/render_login_states.py` and covered in `login-page.a11y.spec.ts` in both themes: the message uses the existing login-message region with the error role, states the wait in text, does not run a live-updating countdown that re-announces, the password input references it via aria-describedby, and axe reports zero violations.
- **AC-A11Y-14:** T12: if the script notifier's path validation rejects a value in the settings UI, the rejection is visible text associated with the path input via aria-describedby with `aria-invalid="true"`, and is announced once. If validation happens only server-side at execution time with no UI surface, the PR states so and this criterion is recorded as not applicable.
- **AC-A11Y-15:** Every a11y or mobile spec added or modified by T5, T12, T19, T21 or T22 contains no `test.skip`, `test.fixme`, or conditional early return on a missing element, and each was proven load-bearing by deliberately breaking the property it guards (the accessible name, the aria-describedby, the focus return, or the inline contrast) and observing the spec fail before restoring.
- **AC-A11Y-16:** Removal scope: apart from AC-A11Y-10, nothing in the accessibility area is replaced by this plan. The sidebar update-available link keeps its accessible name "Update available (opens in new tab)". (the lens's "T10 deletes no UI control" clause is superseded by AC-DESIGN-7)

### lens-data

- **AC-DATA-1:** T2: following UPGRADING.md's stranded-database section verbatim against a real container started from the pre-change docker-compose.yml (no /data mount, library seeded with N media docs), the library that comes up on the new compose file has exactly N media docs. The old anonymous volume still exists until the procedure's final, explicitly-labelled step. The procedure stops the container before copying, so WAL contents are checkpointed or copied with the -wal and -shm files. It verifies the copy (`PRAGMA integrity_check` returns ok, and `database_v2/couchpotato.db` is present) before it tells the user to switch compose files or remove anything. (merges AC-OPS-4)
- **AC-DATA-2:** T2: UPGRADING.md never instructs `docker compose down -v`, `docker volume prune`, `docker system prune --volumes` or `docker volume rm` before the verified-copy step, and warns against them. Its commands are copy-pasteable. It also tells users who have run `down` then `up` that several anonymous volumes may each hold a different database, and how to identify the most recent one by mtime and row count before choosing. (merges AC-PROD-2)
- **AC-DATA-3:** T2: `scripts/backup.sh` captures config.ini when run against the layout the shipped docker-compose.yml now produces (`./data` holding database_v2, `./config/config.ini`). In a scratch reproduction of that layout, the snapshot directory contains both couchpotato.db and config.ini, or the script exits non-zero.
- **AC-DATA-4:** T3: every hostile characterisation case runs its real delete inside a tmp_path sandbox: the root, ancestor, outside and symlink targets are all subdirectories of tmp_path. A sentinel file placed in tmp_path's parent and a sentinel placed outside the configured root both survive the full T3 test run, including the xfail cases that are expected to delete.
- **AC-DATA-5:** T6: the spec names the containment root for each call site: nzbget removeFailed, rtorrent processComplete, renamer deleteFolder. A call site with no configured root refuses; it does not fall back to allowing. A test drives each call site with a target outside its named root and asserts the target is byte-identical afterwards.
- **AC-DATA-8:** T6: in `nzbget.removeFailed` the containment check runs before the `HistoryDelete` editqueue call. When containment refuses, HistoryDelete is not called (asserted on the mock RPC) and the directory is untouched.
- **AC-DATA-9:** T6 (F-S9): the "junk only" decision in `deleteFolder` no longer uses substring matching. A folder whose only remaining file is `The.Sample.Movie.2020.mkv`, `The.Txt.Files.2020.1080p.mkv` or `x.nfo.mkv` is not deleted, and no folder containing a file with a video extension and a size above the sample threshold is ever deleted. A folder with only `sample.mkv` under 50 MB and a .nfo is deleted. The rule is stated in the spec as extension plus size, or as a filename-token rule. (merges AC-SEC-11 and AC-QA-9)
- **AC-DATA-10:** T8: with an injected `sqlite3.OperationalError` on the release_identifier lookup, the documents table holds the same count of release rows before and after. Two concurrent calls that add the same new release_identifier, synchronised by a barrier at the lookup, leave exactly one release row; otherwise the spec records the check-then-insert race as an accepted, named residual with the test written as strict xfail. A lookup against a database already holding two rows with the same identifier returns a deterministic one (ORDER BY on a stated column), asserted with a two-row fixture. (merges AC-QA-14)
- **AC-DATA-11:** T15: no code path translates `sqlite3.OperationalError`, `sqlite3.DatabaseError` or ConflictError into DocumentNotFound. A test injects each of them into `adapter.get` and asserts it surfaces as itself.
- **AC-DATA-12:** T15: every except-RecordNotFound/RecordDeleted handler that becomes live under DocumentNotFound is listed in the PR. Each one whose not-found branch inserts, updates or deletes has a test with two documents differing only in the key, proving the branch acts on the right document and only when that key is absent.
- **AC-DATA-13:** T30: after `db/factory.py`, `codernity_adapter.py` and `db/migrate.py` are deleted, `runner._open_or_create_database` migrates a real CodernityDB fixture with M documents, end to end through `scripts/migrate_codernity_to_sqlite.py`, to an SQLite database with M documents and renames the source to database.bak. Every behaviour pinned by TestMigrationDataIntegrity, TestMigrationIsRepeatable and TestMigrationFailureModes in `tests/integration/test_migration.py` is either re-pinned against the live script or recorded as not applicable, before those tests are deleted. (merges AC-QA-24 and the migration half of AC-PROD-10)
- **AC-DATA-14:** T33: a CodernityDB migration killed after the SQLite database is created and before the rename does not leave a `database_v2/couchpotato.db` that the next boot opens as complete. Test: with `database/` present, `database.bak` absent and a leftover `database_v2/couchpotato.db`, the next boot either retries the migration into a fresh destination or refuses to start. It does not open the partial database.
- **AC-DATA-15:** T11: a completed move followed by a `renamer.after` listener that raises leaves the placed file byte-identical at its destination and the source folder state unchanged relative to the no-listener run. The release status is the same as with no listener. Asserted with a real file in tmp_path and a hash.
- **AC-DATA-16:** T11: `renamer.after` does not fire for a group whose move left `skipped` true. A test with one of two files failing to move asserts no `renamer.after` listener runs and the source folder survives.
- **AC-DATA-17:** T11: a movie that reaches status done through the rename chain while a full `manage.updateLibrary` is between its directory walk and its cleanup pass is not passed to `media.delete`. Test: interleave a rename completion after the scan's walk, then assert the media document and its releases still exist.
- **AC-DATA-18:** T32 (atomic write), T13 (user-created sidecar): a metadata or artwork write over an existing sidecar file is atomic: temp file in the same directory, then `os.replace`. When the write fails mid-way, the pre-existing file is byte-identical afterwards, and `Plugin.createFile` never unlinks the destination on failure. A sidecar the user created is not overwritten unless the spec names a setting that allows it. This lands before, or with, the first slice that makes metadata writes live.
- **AC-DATA-19:** T13: the trailer listener's destination can never equal any path in the group's movie files. The under-1 MB `os.unlink` in `trailer.py` removes only a file this call created. Test: a trailer name pattern resolving to the movie's own filename and extension leaves the movie file byte-identical.
- **AC-DATA-20:** T14: when a subtitle file in a group fails to move, the source folder is retained and the movie file at its destination is unaffected. Test: a two-file group (movie plus .srt) with the .srt move forced to fail.
- **AC-DATA-21:** T10: after the deletion, no updater code path removes or moves files under app_dir except removePyc. A no-.git, non-Docker install never constructs an object that walks app_dir for deletion.
- **AC-DATA-22:** T17: the once-only marker is written only when `fix_release_quality` completed its scan. A run where every `get_many` on release_status raises, or where the function takes its outer except, leaves the marker unset, so the next boot retries. A second boot after a completed run on the same tmp_path database does not call `fix_release_quality`. (merges AC-QA-26)
- **AC-DATA-23:** T18: the benchmark seeds and measures only a database it created under a temporary directory. The SHA-256 of every file under `test_data/` and `data/` is unchanged after a benchmark run.
- **AC-DATA-24:** T19: paged `media.list` ordering ends in a unique tiebreaker (`_id`). With 51 movies sharing an identical title, pages 1 and 2 together return each movie exactly once. The batched with_doc fetch, given two documents differing only in key, returns each id's own document, asserted with that two-row fixture.
- **AC-DATA-25:** T20: every API route that writes to the database or filesystem keeps serialisation unless a test proves two concurrent same-route calls on the same target lose no update and create no duplicate row. The default for a route that sets no flag is serialised, not unlocked, and each opt-out carries a non-empty stated reason. (takes precedence over the draft's opt-in default and over AC-ARCH-18 and AC-ARCH-19, on data-loss grounds)
- **AC-DATA-26:** T21: after an api_key rotation, config.ini differs from its pre-rotation bytes only in the api_key value. No masked value is written back. A rotation concurrent with a `settings.save` of a different key keeps both changes.
- **AC-DATA-27:** T26: `/healthz` performs no database write. sqlite3 `total_changes` and the property table row count are identical before and after 100 calls. A healthz call during an open write transaction returns within its timeout without raising "database is locked" in the writer.
- **AC-DATA-28:** T28: the predicate change reaches existing installs, not only fresh ones, through an `_ensure_*` step in `SQLiteAdapter.open()` that drops and recreates the same-named index. On a database created from the pre-change schema.sql, opening with the new code leaves sqlite_master holding the new predicate for `idx_notification_unread` and no index with the old predicate. Opening twice is idempotent. A failure to recreate logs at WARNING and does not stop startup. Opening the resulting database with the previous beta's open logic still succeeds and returns the same unread notifications. (merges AC-OPS-16)
- **AC-DATA-29:** Lapsed, T29 cut (decision 10). Was T29: after the split there is exactly one SQLiteAdapter instance per process. `Env.get('db')`, `get_db()` at its new location and `Database().getDB()` return the same object (identity), so no second connection or second lock exists over the same file.
- **AC-DATA-30:** Removal list for the data area: the ignore-errors `rmtree` call in nzbget is gone (T6); `db/factory.py`, `codernity_adapter.py` and `db/migrate.py` are gone (AC-DATA-13); the old unread-index predicate is gone (AC-DATA-28); SourceUpdater's app_dir deletion is gone (AC-DATA-21); the docker-compose.yml `/config` comment no longer claims it stores the database (T2). Nothing else in the data area is replaced.

### lens-architecture

- **AC-ARCH-1:** T5: the Host allow-list lives in its own module under `couchpotato/core/` (exemplar: `couchpotato/core/rate_limit.py`) and is registered in `create_app` with a single `app.add_middleware` call. The diff adds no request-handling logic for it to `couchpotato/__init__.py` beyond that registration, and the new module has no module-level import from the `couchpotato` package root.
- **AC-ARCH-2:** T5/T22: exactly one function resolves the request's effective host and effective client address, honouring `X-Forwarded-Host` and `X-Forwarded-For` only under the trusted-proxy setting. The T5 host check, the T22 auth rate-limit bucket key and `_cross_origin_request` all call it. An AST or grep test fails if any other module under `couchpotato/` reads an `x-forwarded-` header directly.
- **AC-ARCH-3:** T5: the allowed_hosts and trusted-proxy values are read through the settings layer at request time, not cached in a module global at import, so a settings save takes effect without restart. A test changes the setting and observes the next request's verdict change.
- **AC-ARCH-4:** T6: the containment helper lives under `couchpotato/core/helpers/` (not under `plugins/renamer/` or `downloaders/`), so the nzbget and rtorrent downloaders gain no import from `couchpotato.core.plugins`. It exposes the containment predicate separately from the delete operation so T13's write path can reuse the predicate without a second implementation.
- **AC-ARCH-5:** T6: the diff adds no new inline `os.path.realpath` plus `os.path.commonpath` containment pair anywhere in `couchpotato/`. (the structural-guard half is merged into AC-QA-7)
- **AC-ARCH-6:** T6 (removal): `shutil.rmtree(path, True)` in `nzbget.py` is gone, and no call under `couchpotato/` passes ignore_errors to rmtree.
- **AC-ARCH-7:** T10 (removal): SourceUpdater, `SourceUpdater.replaceWith` and `SourceUpdater.removeDir` no longer exist in `couchpotato/core/_base/updater/main.py`. `tests/unit/test_source_updater_removedir.py` and every other test exercising SourceUpdater are deleted, not skipped. `cp.source_url` appears nowhere in `couchpotato/`, and the OPTIONAL_EVENTS stale-entry test passes. The fallback branch in `Updater.__init__` selects an existing class, and no new updater class is introduced for it. (merges the deletion half of AC-QA-16)
- **AC-ARCH-8:** T11: the `renamer.after` payload is built by one function in the renamer, and the fire site uses a constant from `couchpotato/core/event_names.py`, not a string literal. T4's contract test asserts against that function's output.
- **AC-ARCH-9:** T11: `renamer.after` is fired only after the move and the release's status write have committed, and the decision whether it is dispatched synchronously or via fireEventAsync is recorded in the T11 spec with the reason. If synchronous, a test shows a listener that sleeps does not hold the renamer's scan lock or delay the next group's move.
- **AC-ARCH-10:** T11: the slice gate that keeps the non-Plex, non-manage `renamer.after` listeners dormant is a single named structure in one module. No listener file gains a slice-specific conditional. The gated listeners (Script, Synoindex, metadata, trailers, subtitles and the other notification providers) are registered, and a test asserts they are not called when `renamer.after` fires. (merges AC-QA-19)
- **AC-ARCH-11:** T14 (removal): the T11 slice gate structure is deleted (grep for its name returns nothing). `renamer.before` and `renamer.after` are absent from UNFIRED_EVENTS. No comment under `couchpotato/` still asserts the chain is never fired.
- **AC-ARCH-12:** T16 changes nothing in `couchpotato/core/event.py`. Listener isolation there (AC-QA-18 b) is kept, and its test is delivered by T11. (overrides the draft's "catch named exceptions or re-raise" for `event.py`)
- **AC-ARCH-13:** T15: DocumentNotFound is defined in a backend-neutral module under `couchpotato/core/db/`, and no caller outside `couchpotato/core/db/` imports it from sqlite_adapter.
- **AC-ARCH-15:** T15 (removal): `couchpotato/core/db/__init__.py` no longer exports CodernityDBAdapter, create_adapter or get_backend. Every index class that subclasses a CodernityDB index is deleted or no longer subclasses CodernityDB, and `Database.setupIndex` no longer instantiates CodernityDB index objects.
- **AC-ARCH-17:** T19: paging uses the existing limit_offset parameter of `media.list`. No new list route or second paging parameter is added. The with_doc row reuse is implemented inside SQLiteAdapter, not as a caller-side special case in `media/main.py`.
- **AC-ARCH-20:** T22: the auth rate-limit bucket is added inside the existing middleware in `couchpotato/core/rate_limit.py` (or a second class in that module), not as a second, independently configured limiter elsewhere.
- **AC-ARCH-21:** T26: the exemption of `/healthz` from auth, rate limiting and any Host-check exemption is expressed through each mechanism's own exemption list, not by a path check inside the health handler. The handler reads the database through the adapter interface, not a raw sqlite3 connection. The route is defined outside the `create_app` body except for its registration.
- **AC-ARCH-22:** T24: one file is the input for direct runtime dependencies and the hashed lock is generated from it. The Dockerfile installs only from the lock. A test fails if a direct pin in the input disagrees with the lock. The lock generator is a dev-only dependency in requirements-dev.txt and absent from the image.
- **AC-ARCH-24:** Lapsed, T29 cut (decision 10). Was T29: `get_db` is defined in a module under `couchpotato/core/` and re-exported from `couchpotato/__init__.py`. An AST test fails if any module under `couchpotato/core/` imports from the `couchpotato` package root, with any remaining edge listed in that test's allow-list with a reason. `test_plugin_import_sweep.py` stays green.
- **AC-ARCH-25:** Removal scope: T1, T2, T3, T4, T7, T8, T9, T18, T21, T23, T27 and T28 replace nothing in the architecture area. Their removals, where any, are owned by other lenses.

### lens-operability

- **AC-OPS-1:** T1: every scheduled workflow (ci.yml, mutation.yml, codeql.yml) has a step that runs only when a scheduled run fails, or a manually dispatched run used as the proof under AC-QA-11 fails, and opens a GitHub issue, or comments on an already-open one, titled with the workflow name. The body links the failed run and names the failed job. A later green scheduled run of the same workflow closes that issue, so repeated nightly failures produce one open issue, not one per night. Both proving run URLs are recorded in the conductor log.
- **AC-OPS-2:** T1: the alert step's own failure is visible. If issue creation fails (for example a missing permission), the job still ends red and the step log names the API error. The workflow declares `issues: write` explicitly at job level.
- **AC-OPS-3:** T2: when the app creates a fresh database, it logs at WARNING (not INFO) the database directory it is creating, plus one sentence saying an existing library from a container without a /data mount may be in an anonymous Docker volume and pointing to UPGRADING.md. Opening an existing database does not emit this line.
- **AC-OPS-5:** T5: a refused request is logged at WARNING with the refused Host value (sanitised and truncated to 255 characters) and the setting name allowed_hosts. Logging is rate-limited to at most one line per distinct Host per 10 minutes, plus a periodic count of suppressed refusals, so a flood of hostile Host headers cannot push earlier diagnostics out of the rotating log. (merges AC-PROD-16)
- **AC-OPS-6:** T5: a refused operator has a recovery path that needs no browser access through the refused name, and UPGRADING.md names both the config.ini allowed_hosts key and access by IP literal or localhost. Removing allowed_hosts from config.ini returns the instance to the default allow-list on the next start without error.
- **AC-OPS-7:** T6: every containment refusal logs at WARNING through PrivacyFilter, naming the caller (nzbget removeFailed, rtorrent removal, or renamer deleteFolder), the release or download identifier, and which rule refused (target is root, ancestor of root, outside root, or symlink). The record reaches the handler the in-app Logs page reads. A refusal never raises out of the downloader's status-check loop, which continues to the next item. (merges AC-PROD-12)
- **AC-OPS-8:** T10: a non-Docker, non-git install logs one INFO line at startup naming the updater mode as notify-only, and `updater.info` still returns version and update_version for that install.
- **AC-OPS-9:** T10: the outcome of checking whether release-to-prod.yml keeps attaching source archives is written into the conductor log as keep or remove, with the reason. If removed, the "Build source archives" step and both source-archive release assets are gone from release-to-prod.yml.
- **AC-OPS-10:** T11: when a `renamer.after` listener raises, exactly one ERROR record is written for that failure, and it names the event and the handler's qualified name as its own text, not only inside an object repr or a traceback. The test is shown failing against the code as it stood before T11. The release still reaches status done, and the moved file is not touched. This applies to handler-failure logging generally, so every later slice inherits it. Where the change lands is for T11's spec, from the measured facts under Task detail.
- **AC-OPS-13:** T15: the upgrade path for an install that still has a legacy `database` directory under data_dir is unchanged. `_open_or_create_database` still runs `scripts/migrate_codernity_to_sqlite.py` as a subprocess and opens the result. A non-zero exit still raises the "refusing to create a fresh database" RuntimeError rather than creating an empty database.
- **AC-OPS-14:** T16: the settings-load failure in `loader.py` logs at WARNING or above, naming the plugin. Each of the narrowed sites leaves an ERROR or WARNING record naming the item (event name, plugin name, media id or search target) when a real failure occurs, checked with the logger at INFO. None of them logs a data-path failure at DEBUG. The event-name half is delivered by T11 under AC-OPS-10, not by T16.
- **AC-OPS-15:** T17: a failed `fix_release_quality` run logs at WARNING that it will retry on the next boot. A second boot after success logs nothing about it.
- **AC-OPS-17:** T26: the Dockerfile HEALTHCHECK no longer fetches `/`; it fetches `/healthz`, asserted by a Dockerfile parse test. `/healthz` returns 200 when the database read succeeds and the scheduler is running, and 503 when the database read fails or the scheduler is not running, each proven by a test. It answers within the HEALTHCHECK's 5-second client timeout under normal load. A successful probe writes no log line at INFO or above. (merges AC-QA-34)
- **AC-OPS-19:** Rollback: for each of T5, T15, T30, T31, T33, T17, T21 and T28, the PR body states what the previous beta image does when started against data written by the new one (new config.ini key, property marker, rotated api_key, recreated index). For T28 this is tested, as AC-DATA-28 requires.

### Vetoed at planning

`lens-simplicity` holds the veto. It cannot override data loss, security or
the accessibility floor, and a rejection lapses where the owning lens
supplied the criterion the requirement traces to.

Sustained (the requirement or criterion is dropped):

- Dropped `AC-ARCH-16` (one shared run-once function for the boot migrations): vetoed by `AC-SIMP-9`. Two call sites do not justify a generic helper; the fail-open it was meant to fix is closed by `AC-DATA-22`.
- Dropped `AC-ARCH-23` and `AC-QA-33` (pyright pinned, and proven to run): the pyright half of T25 is vetoed by `AC-SIMP-11`. An informational report nothing acts on, a new dependency and a slower gate; decision 5 already pauses acting on the other informational reporter. No lens supplied a criterion that needs it. Consequence: the type-checker half of F-O1 has no task and wants a "Not fixing" row.
- Dropped requirement, T3 "regenerate coverage and record the lowest-covered files": vetoed by `AC-SIMP-5`. Nothing consumes the result. Consequence: F-T5 has no task and wants a "Not fixing" row.
- Dropped requirement, T9 "Dependabot is configured to update SHA pins": vetoed by `AC-SIMP-3`. Already true in `.github/dependabot.yml`.
- Dropped requirement, T23 "review narratives moved to `docs/` history" and "test count corrected": vetoed by `AC-SIMP-10`. Git history is the archive, and a corrected count drifts again within a week; both are deleted instead.

Not sustained (the simplicity criterion is dropped, the requirement stays):

- Dropped `AC-SIMP-1` (T5 reads the Host header only, no trusted-proxy setting): overridden by security. `AC-SEC-3` and `AC-SEC-35` need an explicit trusted-proxy setting, default empty; the lens deferred to security in its own finding.
- Dropped `AC-SIMP-2` (T5 refusal is plain text or JSON, no template): overridden by the accessibility floor. `AC-A11Y-3` needs a titled HTML document with a language, a heading and a main landmark, which a plain-text body cannot carry; the lens deferred to accessibility and product in its own finding.
- Dropped `AC-SIMP-6` (one helper function, called from the rmtree sites only, no write path): overridden by data loss and security. The rTorrent deletes are `os.unlink` and `os.rmdir`, not rmtree (`AC-SEC-9`, `AC-QA-7`), and `AC-SEC-22` needs the same predicate for T13 writes. `AC-ARCH-5` keeps the intent: no further inline containment copies.
- Dropped `AC-SIMP-12` (remove T29): not applied by the planning cycle, because T29 traced to finding F-A2 and the owning lens supplied `AC-ARCH-24`. The owner then cut T29 (decision 10), so the veto's outcome stands and `AC-ARCH-24` is lapsed.
- Dropped `AC-SIMP-13` (remove T20, T26 and T28 unless the owning lens supplies a criterion): lapsed on its own condition. The owning lenses supplied `AC-DATA-25` (T20), `AC-OPS-17` and `AC-SEC-36` (T26), and `AC-DATA-28` (T28). The lens's point that T20 has no measured contention behind it stands as a recommendation: gate T20 on T18's numbers.

Dropped on precedence, not by veto:

- Dropped `AC-ARCH-18` and `AC-ARCH-19` (per-route locks opt-in, the unconditional lock removed): contradicted by `AC-DATA-25`, which keeps serialisation as the default on data-loss grounds. The reason-string requirement carries over to the opt-out.

Merged as duplicates (the surviving criterion carries a note): AC-SEC-10, AC-SEC-11, AC-QA-9, AC-QA-14, AC-QA-15, AC-QA-16, AC-QA-19, AC-QA-21, AC-QA-24, AC-QA-26, AC-QA-34, AC-PROD-2, AC-PROD-9, AC-PROD-12, AC-PROD-13, AC-PROD-16, AC-PROD-19, AC-PROD-20, AC-DESIGN-3, AC-DESIGN-6, AC-DESIGN-10, AC-DATA-6, AC-DATA-7, AC-ARCH-14, AC-OPS-4, AC-OPS-11, AC-OPS-12, AC-OPS-16, AC-OPS-18.

## Dependency reasons

Where a `(needs: ...)` edge below differs from the draft text under "Task
detail", the edge below wins. The reasons (AC-SIMP-14):

- **T1 before everything except T2, T3 and T4:** a pull request cannot be
  told apart from a red baseline while the nightly build is red.
- **T6 needs T10:** the updater holds one of the three `rmtree` call sites;
  deleting it first leaves two to guard.
- **T11 needs T6 and T7:** making the rename chain live exercises the delete
  paths and logs downloader URLs.
- **T12 needs T5:** the script notifier runs operator-supplied commands and
  must not go live on installs with no password before the host check
  (AC-SEC-19).
- **T13 needs T32:** T13 makes the metadata and artwork writes live, and T32
  makes both write paths atomic.
- **T15, T16, T19 and T22 need T14:** no file overlap is claimed by the chain's
  file lists. This is milestone order only, as for T28 and T30 below.
- **T31 needs T15 and T30:** the AST guard and the grep-zero check pass only
  once T15 has converted the handlers and T30 has deleted the adapter files.
- **T23 and T27 need T14:** the documentation and the mutation scope describe
  the renamer as it stands after the chain lands.
- **T28 and T30 need T14:** no file overlap. This is milestone order only:
  M1 lands before M2 and M3 work so review attention stays on M1.
- **T30 needs T33:** the partial-migration guard is proven against the live
  migrator before the second path and its tests are deleted.
- **T16 needs T7:** widening what is logged must follow the log scrubbing.
- **T25 needs T31:** the newer ruff target raises findings in files T31
  deletes or rewrites.
- **T21 needs T22, T26 needs T5, T20 needs T19:** each builds on the code the
  earlier task introduces.

## Tasks

- [ ] T1: Restore the nightly build (ship the fixed zlib) and alert on scheduled failure — state: queued
- [ ] T2: Mount /data in docker-compose.yml, with a guard test, upgrade note and backup.sh fix — state: queued
- [ ] T3: Characterisation tests for destructive deletes — state: queued
- [ ] T4: Strict-xfail contract test for the rename-completion chain — state: queued
- [ ] T5: Host allow-list when auth is off — state: queued (needs: T1)
- [ ] T7: Redact URL credentials and tracebacks in logs — state: queued (needs: T1)
- [ ] T8: Catch not-found only in the release identifier lookup — state: queued (needs: T1)
- [ ] T9: Pin GitHub Actions to commit SHAs — state: queued (needs: T1)
- [ ] T10: Delete the source-archive updater — state: queued (needs: T1)
- [ ] T6: Containment guard on every recursive delete — state: queued (needs: T3, T10)
- [ ] T32: Make Plugin.createFile atomic; never unlink the destination on a failed write — state: queued (needs: T1)
- [ ] T33: Refuse or retry a part-finished CodernityDB migration instead of opening it — state: queued (needs: T1)
- [ ] T11: Rename chain slice 1, payload and Plex rescan — state: queued (needs: T4, T6, T7)
- [ ] T12: Rename chain slice 2, notifications, Synology, scripts — state: queued (needs: T11, T5)
- [ ] T13: Rename chain slice 3, metadata and trailers — state: queued (needs: T11, T32)
- [ ] T14: Rename chain slice 4, subtitles; close the unfired-event gap — state: queued (needs: T12, T13)
- [ ] T17: Gate fix_release_quality to run once — state: queued (needs: T1)
- [ ] T18: Benchmark media.list at 500 / 5,000 / 20,000 — state: queued (needs: T1)
- [ ] T24: Hash-locked Python dependencies; bencodepy licence — state: queued (needs: T1)
- [ ] T15: First-party DocumentNotFound; convert the not-found handlers — state: queued (needs: T8, T14)
- [ ] T30: Delete the dead second migration path — state: queued (needs: T33, T14)
- [ ] T31: Remove the remaining live CodernityDB imports, with an AST import guard — state: queued (needs: T15, T30)
- [ ] T16: Narrow the data-path catch-alls (no change in event.py) — state: queued (needs: T7, T14)
- [ ] T19: Rewrite the library list with paging — state: queued (needs: T18, T14)
- [ ] T20: Tested opt-out from per-route API serialisation, only if T18 shows queuing — state: queued (needs: T19)
- [ ] T22: Authentication hardening (login bucket, constant-time compare, /getkey) — state: queued (needs: T5, T14)
- [ ] T21: api_key rotation and cache hygiene — state: queued (needs: T22)
- [ ] T23: Documentation refresh — state: queued (needs: T14)
- [ ] T25: Ruff target to 3.15 — state: queued (needs: T31)
- [ ] T26: Real health endpoint — state: queued (needs: T5)
- [ ] T27: Widen Python mutation scope to the renamer — state: queued (needs: T6, T14)
- [ ] T28: Fix the unread-notification index predicate on existing installs — state: queued (needs: T14)

## Conductor log
