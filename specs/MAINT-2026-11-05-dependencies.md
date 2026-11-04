# Dependency refresh, 5 November 2026

## Scope

Refresh applicable dependencies from master `1454367d1`. Use
`MAINT-2026-10-31-dependencies.md` as the prior exemplar. Preserve unrelated
local work and the shared development environment. Deliver through the normal
review, PR, CI and merge process. Production promotion and deployment remain
outside this request.

## Acceptance criteria

- AC-SEC-1: Fresh Python/npm graphs resolve and audit clean. Secret scanning
  and the resulting Alpine image scan pass at every severity, including unfixed
  findings. Record the scanned image identity and retain existing security floors.
- AC-SEC-2: Actual application login/API forms preserve successful parsing,
  invalid-credential rejection, field-count/size limits and controlled malformed
  request errors, without disclosing submitted credentials or form contents.
- AC-SEC-3: Reassess Lighthouse and the scoped minimatch override using fresh
  graphs/advisories. A minimatch update requires all three actual Stryker consumers
  and the real arithmetic-mutation canary. Preserve direct six for its other users.
- AC-SEC-4: A real Docker COPY probe excludes root/nested harness state
  while retaining a control file. Removing the rule must fail the same probe;
  restoration must pass. The final runtime image excludes local harness state.
- AC-ARCH-1: Resolve without adding dependencies, broadening unrelated parent
  constraints or changing supported engines. Keep Vitest/coverage-v8 matched.
  Preserve the Stryker command runner and existing component boundaries.
- AC-ARCH-2: Dateutil 4 preserves real Newznab, PassThePopcorn and updater
  timestamps, including offsets and leap dates, and their existing invalid-date
  failure paths. Exercise GuessIt's real valid/impossible filename-date parsing.
  APScheduler does not consume dateutil; no recurrence migration is needed.
- AC-SIMP-1: Limit changes to dependency pins, their resolved graphs and
  reproduced compatibility fixes. Preserve application, persistence, UI and runner
  behaviour. Do not force unrelated majors to reduce an outdated count.
- AC-SIMP-2: Record each candidate and remaining installed outdated package as
  taken, held or already allowed, with actual parent constraints. Exclude absent
  optional peers/platform packages. A floor-only edit is not an installed upgrade.
- AC-PROD-1: Existing login/settings outcomes and saved settings after reload
  remain covered by real route/browser contracts. Provider/updater outcomes and
  candidate clarity are owned by AC-ARCH-2 and AC-SIMP-2 respectively.
- AC-OPS-1: Build the final Alpine image without cache using pip 26.3; verify
  staged/copied dependencies, native imports, retained OS floors and absent
  runtime installer tooling.
- AC-OPS-2: With owned synthetic volumes, verify non-root execution, health,
  actual detail/releases/settings content and clean logs. SIGTERM stops within
  budget; restart retains settings/fixture counts and SQLite integrity.
- AC-OPS-3: Run retained Lighthouse against an owned synthetic target on its
  fixed address, completing all twelve audits with unchanged policy and browser
  cleanup. Run actual JavaScript coverage and configured mutation suite/canary,
  retaining non-empty reports, sandbox exclusions and reviewed survivors.
- AC-QA-1: Complete the canonical make verify gate, Python XML and JavaScript
  LCOV generation. Inspect source attribution/executed lines, including sw.js's
  VM filename; matching package versions and non-empty files alone are insufficient.
  Check installed Node engines against all declared minimum versions.
- AC-QA-2: Real form contracts cover blank/Unicode/encoded/repeated fields;
  provider/updater probes use explicit time zones and distinguish pre-existing
  timestamp conversion from regressions. Remaining QA criteria are deduplicated
  into AC-SEC-1/2, AC-ARCH-1/2 and AC-OPS-1/2/3.
- AC-REVIEW-1: Two independent code-reviewer agents clear the final diff before
  every push. Follow CI/cloud review through merge and verify the automatic beta.
  Observe the review-action self-edit skip, then a real final-pin execution.

## Candidate decisions

| Dependency | Master | Candidate | Initial disposition |
| --- | --- | --- | --- |
| python-multipart | 0.0.32 | 0.0.33 | Take subject to real form contracts |
| python-dateutil | 3.0.0 | 4.0.0 | Take subject to actual parser consumers |
| filelock | 4.2.5 | 4.2.9 | Take subject to graph/gates |
| platformdirs | 4.14.0 | 4.14.5 | Take subject to graph/gates |
| coverage | 7.17.0 | 7.17.2 | Take; exercise actual report generation |
| Vitest and coverage-v8 | 5.0.5 | 5.1.0 | Update together; exercise mutation runner |
| WebSocket override | 8.22.0 | 8.22.1 | Take after real protocol and browser consumers |
| Scoped Stryker minimatch | 11.0.3 | 11.0.4 | Take after actual consumer probes |
| Builder pip | 26.2.2 | 26.3 | Take after actual Alpine build |
| Claude review action | 1.0.266 | 1.0.268 | Exact pin; observe real hosted execution |
| mutmut | >=3.8.0 | 3.8.1 | Already allowed; fresh resolver selects it |
| Lighthouse | 13.5.0 | 13.6.0 | Hold: fresh candidate audit still finds vulnerable glob/minimatch |
| rarfile | 4.5 | Same stable | Current; future v5 extractor configuration migration is separate work |
| Compatible npm indirect updates | Existing lock | Within parent ranges | Refresh, inspect and audit actual graph |
| Python Alpine base | 3.15.2 | Same digest | Current official tag remains unchanged |
| htmx / Alpine.js | 2.0.11 / 3.17.5 | Same | Current stable browser bundles |
| Tailwind Play CDN | 3.4.17 | 4.3.4 browser | Hold: separate theme/build migration; 3.4.19 endpoint still reports unknown version |

## Implementation sequence

1. Finish specialist planning and upstream/advisory triage.
2. Update compatible pins/lockfile in isolation and install fresh Python/npm graphs.
3. Run real consumer probes, coverage/mutation tooling, image and local gates.
   Behavioural adaptations require a demonstrated failing test and restored green.
4. Obtain independent local review, push through the mandatory hook, open a PR,
   resolve CI/cloud review, complete final acceptance review, merge and confirm beta.

## Initial evidence

- All 57 direct Python requirement names were checked against PyPI. Five exact
  pins have updates; mutmut's current lower bound already admits its latest release.
- Fresh Lighthouse 13.6 resolution still has two moderate advisory families:
  GHSA-3g3m-2fjr-6pw4 (glob) and GHSA-g3hv-75wg-m249 (minimatch).
  The current npm graph audits clean. Preserve the clean graph rather than force
  a new major through Sentry's parent constraints.
- Dateutil's direct consumers call public parser.parse, not the stricter isoparse.
  GuessIt is the sole declared indirect consumer. APScheduler neither imports
  nor declares dateutil in this graph.
- Claude action 266 to 268 changes only Claude Code/Agent SDK pins to
  2.1.318/0.3.318 and their lock entries. Workflow permissions need no change.
- The official Python 3.15 Alpine tag remains at the existing multi-platform
  digest. Other action major tags, Trivy 0.36.0, Gitleaks 8.30.1 and Sonar scanner
  5.0.2 remain current in upstream release/registry checks.

## Planning synthesis

Security, QA, simplicity, architecture, operability and product planning ran
independently and read-only. Data/design/accessibility specialists are not triggered:
there are no data, UI, browser-bundle or accessibility-gate edits. Existing browser
and accessibility gates remain required. Reject the proposed dateutil recurrence/DST
scheduler expansion: source and installed metadata establish that APScheduler does
not consume dateutil. Preserve six and existing runner/configuration behaviour.

## Local verification record

- Fresh Python 3.15.2 development installation with pip 26.3 passes pip check
  and audits with no known vulnerabilities. Every installed Python package is
  current at this inventory. No shared environment was modified. Version-only
  changes required no application adaptation, so no artificial failing regression
  was introduced. Existing real contracts and mutation proof remain load-bearing.
- Fresh npm resolution/install and full graph/audit pass with zero vulnerabilities.
  All installed engines accept Node 22.22.2, 24.15.0 and 26.0.0. The only direct
  outdated package is the deliberately held Lighthouse. The dated holds report
  records 86 installed locations across 79 families, with actual retaining parents.
- Identical before/after probes execute actual Newznab, PassThePopcorn, source
  updater and Docker updater consumers for six valid/invalid/missing date formats
  under UTC, Brisbane and New York. GuessIt preserves leap-day/ordinary dates
  and rejects impossible dates. Existing timetuple/mktime conversion semantics
  remain unchanged; this refresh does not claim to fix offset handling.
- Real application probes match before/after for URL-encoded and multipart
  login, rejected credentials, blank/Unicode/escaped/repeated API fields, missing
  boundaries and invalid headers. URL-encoded 1,001-field and over-1-MiB requests
  remain HTTP 400. Submitted synthetic secrets are absent from error responses
  and captured logs. Starlette's own limits remain in force; new upstream
  opt-in FormParser limits are not assumed enabled.
- The actual packaged Stryker FileMatcher, ProjectReader and OptionsValidator
  preserve brace/dot matching, exclusions, negation/partial directory traversal,
  file ranges and glob/range rejection with minimatch 11.0.4.
- make coverage passes 5,014 Python unit/integration tests (13 skips, four
  expected failures) and all 327 JavaScript tests. Python XML attributes 13,949
  executed lines across 252 classes; SQLite adapter has 447 executed lines.
  JavaScript LCOV attributes all nine configured files, including sw.js at 47/49
  executed lines. The VM filename attribution survives the Istanbul v2 update.
- The configured JavaScript mutation suite executes all 731 mutations: 703
  killed, ten timeouts, 18 survivors, no compile/runtime errors. All 18 survivors
  match the previous actual report by file, location, operator and replacement:
  five log-parser bounds/guards, three movie-filter fallback/year edges, eight
  profile-editor metadata/array/quality guards and two settings fallback cases.
  Scores remain informational; no tests or thresholds were weakened.
- No-cache Alpine build succeeds with pip 26.3 staging requirements under
  /install. Built/scanned image ID is
  sha256:cc73f5b17a59cdad03da786ae9a4d440b3afd3d77a1a72c7e69bcf71e5d253d1.
  Full-severity Trivy scan including unfixed findings reports zero vulnerabilities.
  Runtime Python is 3.15.2; dateutil/multipart are 4.0.0/0.0.33, pip is absent,
  native imports and MediaInfo work, and the application PID runs as uid 1000.
- Chromium renders actual seeded detail/title/releases and settings from that
  image. A real settings.save request persists an updater preference. SIGTERM
  stops the final image in 0.59 seconds with exit zero; restart retains the preference,
  SQLite integrity and counts (media 9, profile 15, property 4, quality 12,
  release 14). Startup/shutdown/restart logs contain no errors or tracebacks.
- All twelve real Lighthouse audits against the owned loopback-only synthetic
  container complete, with 24 non-empty HTML/JSON reports plus summary. Blocking
  HTTP/accessibility/name/alt checks pass. Performance, SEO, FCP and LCP warnings
  remain visible across all runs under concurrent verification load; thresholds
  are unchanged. The launched Lighthouse Chromium is gone after completion.
- Working-tree secret scan finds no leaks. Full canonical gate, independent
  review and remote delivery remain pending at this local record.

## Review follow-up

Independent review identified ws 8.22.1 behind our own exact override. Assess
and take the patch, then recheck its actual network/browser consumers. Correct
report labels to show an effective override only when it changes the raw spec.

A final runtime inventory found local .codex conductor state copied into the
first image. That image is superseded. Add a recursive .codex exclusion using
an actual Docker COPY regression, prove removal/restoration, and rebuild/rescan
and repeat runtime lifecycle/browser verification before final review.

## Final local corrections verified

- ws 8.22.1 updates our exact security override. Upstream fixes IPC-colon paths
  and frame/masking details. Real loopback text/Unicode/binary/boundary-length
  echoes, fragmented frames, ping/pong and clean close all pass. Fresh npm ci,
  graph/audit, all declared Node minimums and the three Stryker consumers pass
  again. The final holds report has 86 installed locations across 79 families.
- Real Docker COPY with synthetic root/nested .codex markers failed before the
  exclusion, passed after it, failed with the confirmed removal in an isolated
  rules copy, and passed after restoration with byte-identical source rules.
  The control file remained included. The recursive .dockerignore rule is the
  mechanism preventing this class for root and nested local harness state.
- The final no-cache image is the ID recorded above, with zero full-severity
  vulnerabilities including unfixed findings. It has no .codex, development
  environment, mutation sandbox, node_modules or test_data. Final native imports,
  health, uid 1000, actual detail/releases/settings, saved preference, shutdown,
  restart, SQLite integrity and fixture counts all pass again with clean logs.
- After ws's patch, all twelve actual Lighthouse audits run again with complete
  report pairs and unchanged blocking checks. Existing performance/SEO/FCP/LCP
  warnings remain disclosed. Lint, trap and conformance checks pass.
- Final independent review and the full canonical pre-push gate remain pending.
