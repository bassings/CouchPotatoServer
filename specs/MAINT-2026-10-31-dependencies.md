# Dependency refresh, 31 October 2026

## Scope

Refresh applicable Python, npm and review-action dependencies from master
`b5fdd67ad`. Prior exemplar: `MAINT-2026-10-23-dependencies.md`.
The stale local changes are preserved in a stash and the local-only
`archive/stale-local-2026-10-31` branch. Do not include them in this change.
Production promotion and deployment are outside this request.

## Acceptance criteria

- AC-QA-1: A fresh Python 3.15 runtime/development graph resolves and passes
  the canonical `make verify` gate, including Chromium, phone, accessibility
  and worker-isolation projects. Keep Ruff's CI pins aligned.
- AC-SEC-1: Fresh npm installation, full dependency graph checks, Python and
  npm vulnerability audits, secret scan and the resulting Alpine image scan
  pass without suppressing findings or weakening gates.
- AC-OPS-1: Build the production Alpine image and verify startup, health and
  graceful shutdown. Exercise the real Lighthouse and JavaScript mutation
  runners after their updates; report genuine mutation survivors.
- AC-COMPAT-1: Verify auth, settings and form flows with FastAPI 0.162.0 and
  Starlette 1.10.0. Review upstream form/default changes rather than inferring
  compatibility from version numbers. Behavioural adaptations require a
  demonstrated failing regression and restored green tests.
- AC-DEPS-1: Record dispositions for explicit update candidates and remaining
  outdated indirect packages. Preserve parent constraints except for a scoped
  security override with measured consumer compatibility, and omit absent
  optional peers/platform packages from the update inventory.
- AC-REVIEW-1: Two independent code-reviewer agents review the final diff;
  fix material findings and repeat affected checks and review before any push.
  A review-action workflow self-edit requires observing its documented cloud
  skip and a real subsequent execution if delivered remotely.

## Candidate decisions

| Dependency | Master | Candidate | Initial disposition |
| --- | --- | --- | --- |
| FastAPI | 0.161.0 | 0.162.0 | Test omitted boolean form defaults |
| Starlette | 1.9.0 | 1.10.0 | Test form parsing and repeated values |
| Pydantic | 2.14.1 | 2.14.2 | Take subject to gates |
| Dulwich | 1.2.19 | 1.2.20 | Take subject to gates |
| Certifi | 2026.10.19 | 2026.10.23 | Take subject to gates |
| pysubs2 | 1.9.0 | 1.9.1 | Take subject to gates |
| filelock | 4.2.4 | 4.2.5 | Take subject to gates |
| platformdirs | 4.13.5 | 4.14.0 | Take subject to gates |
| pytest | 9.1.1 | 9.2.0 | Check collection and plugin compatibility |
| Ruff | 0.17.2 | 0.17.3 | Update CI pins together |
| Stryker core and Vitest runner | 10.0.0 | 10.1.1 | Keep command runner; run real mutations |
| Lighthouse | 13.5.0 | 13.6.0 | Hold: introduces vulnerable glob via Sentry 11 |
| Claude review action | 1.0.258 | 1.0.266 | Retain exact pin; review upstream changes |
| mutmut | >=3.8.0 | 3.8.1 | Already allowed; fresh resolver selects it |
| Compatible npm indirect updates | Existing lock | Within parent ranges | Refresh and audit actual graph |
| Stryker's minimatch | 10.2.6 | 11.0.3 | Scoped security override; verify actual FileMatcher and mutation runner |
| Python Alpine base | 3.15.1 | 3.15.2 | Refresh both stages to the verified official multi-platform digest |

## Verification record

- Initial assessment: candidate Python pins resolve together for Python 3.15.
  Current master and the three direct npm candidates install with valid graphs
  and zero npm audit findings in an isolated temporary directory. These are
  resolution checks, not application verification.
- The wider npm refresh exposed GHSA-3g3m-2fjr-6pw4 (glob) and
  GHSA-g3hv-75wg-m249 (minimatch). Lighthouse 13.6.0 introduces glob through
  Sentry 11; retain 13.5.0 rather than overriding that new consumer's graph.
  Stryker 10.0.0 and 10.1.1 both require minimatch ~10.2.4, whose latest
  10.2.6 is affected. No patched v10 exists. A scoped override to 11.0.3
  requires testing the actual packaged FileMatcher, ProjectReader and
  OptionsValidator consumers, and the full mutation runner. Upstream v11
  removes internal matcher APIs; Stryker uses the retained minimatch function,
  Minimatch.match (including partial matching), negate and hasMagic APIs.
- Independent review corrected the initial compatibility inventory: the
  FileMatcher-only probe does not establish compatibility of ProjectReader
  and OptionsValidator. Verify these additional consumers explicitly.
- Fresh full-severity image scanning found 24 libcurl findings on 8.22.0-r0,
  all with the available 8.23.0-r0 fix. Require that floor in the runtime apk
  instruction. The added test failed without it, passed with it, and rejected
  its deliberate removal in an isolated copy; restoration passed all five
  OS-package cases with the original Dockerfile bytes intact.
- Full local verification exposed a sandbox isolation defect: Stryker copied
  the old Python environment into its sandbox, which both confused the
  first-party Tenacity-import check and entered a concurrent local Docker
  build. Exclude development environments, mutation artefacts and local state
  in Stryker, and exclude mutation artefacts from Docker contexts. Synthetic
  markers in the actual runner failed before the fix and passed afterwards;
  deliberately removing the .venv exclusion reproduced the failure and
  restoration passed. No application test was weakened.
- Reassessed existing exact npm overrides: ws 8.22.0 is current; qs advances
  from 6.16.1 to 6.17.1. The latter is our override, not the raw upstream
  typed-rest-client pin (6.15.1). Its actual URL/query builder preserves
  escaped values, repeated arrays and nested parameters with the update.
  A wildcard DevTools peer also advances within its actual parent constraint.
- Remaining npm holds are recorded in `REPORT-2026-10-31-dependency-holds.md`:
  84 actual installed locations across 78 families, all with a retaining
  constraint, older latest tag or explicit Lighthouse hold; absent peers and
  platform binaries are excluded. Fresh installation, graph and audit pass.
- The official Python 3.15 Alpine tag now resolves to multi-platform digest
  `sha256:20a82dbc2783112ddb91d1534603f802d222a3e63e593cd002eb2ac534e70211`.
  Running it confirms Python 3.15.2 and Alpine 3.24.3. Refresh both stages
  together and retain all security floors. Builder pip 26.2.2, Sonar scanner
  5.0.2, Trivy action 0.36.0 and Gitleaks 8.30.1 remain current in their
  respective upstream registry/release checks.
- Final upstream tag inventory supersedes the initial Claude action candidate:
  1.0.266 is now available. The 1.0.262-to-1.0.266 diff updates Claude Code
  and Agent SDK to 2.1.316/0.3.316 plus plugin documentation. Keep the exact
  version pin and exercise the reviewed action through the normal workflow.
- Local gate preflight passed 4,972 Python unit tests, 42 integration tests
  and 327 JavaScript unit tests. Existing 13 skips and four expected failures
  remain. Transfer the remaining browser verification to the mandatory full
  pre-push hook so the hook is the authoritative final full-gate result.
- The final configured JavaScript mutation run completed all 731 mutations:
  696 killed, 17 timeouts, 18 survivors, zero runtime or compile errors.
  The survivor set is identical before/after sandbox exclusions. Reviewed all
  18: log-parser helper guards/bounds (five), movie-filter fallback/year edges
  (three), profile-editor metadata/array/quality-boundary validation edges
  (eight), and settings help/value fallbacks (one each). They are existing
  redundant conditions or uncovered boundary/fallback cases, with no changed
  application source in this batch. Scores remain informational.
- Real Docker COPY proof retained its control file while excluding all four
  synthetic root/nested mutation markers; confirmed removal of the ignore
  rules included those markers, and restoration excluded them again.
- The rebuilt Python 3.15.2 image has zero Trivy vulnerabilities at every
  severity, including unfixed findings; scanned and built image IDs match.
  Actual movie detail, title, release rows and settings rendered in Chromium.
  SQLite integrity is OK; synthetic fixture counts are media 9, profile 15,
  property 4, quality 12 and release 14. No development environment, Stryker
  sandbox, mutants tree or test_data directory is present in the image.
- Both independent code-reviewer agents cleared the final dependency, sandbox,
  Docker, workflow-pin and inventory changes. Secret scan reports no leaks.

## Upstream compatibility assessment

- [FastAPI 0.162](https://fastapi.tiangolo.com/release-notes/#01620) changes
  omitted boolean Form defaults. This application parses Request.form directly
  in API dispatch and login, with no FastAPI Form declarations. Existing real
  framework/auth/settings contracts and browser flows remain the verification
  boundary; no application adaptation is needed on source inspection.
- [Starlette 1.10](https://github.com/Kludex/starlette/releases/tag/1.10.0)
  changes form-parser finalisation and repeated-value equality. Exercise the
  actual form routes, not only direct settings validation.
- [Pydantic 2.14.2](https://github.com/pydantic/pydantic/releases/tag/v2.14.2)
  addresses two security advisories and changes extra-field/alias validation.
  Retain the application's settings validation tests.
- [Dulwich 1.2.20](https://github.com/jelmer/dulwich/releases/tag/dulwich-1.2.20)
  hardens LFS object paths, receive-pack refs and .gitmodules symlinks, with
  fetch and patch fixes. Run updater contracts.
- [pytest 9.2](https://github.com/pytest-dev/pytest/releases/tag/9.2.0) makes
  extra parametrize arguments keyword-only and changes plugin-error exit codes.
  Run the complete collection and real configured mutation canary.
- [Stryker 10.1](https://github.com/stryker-mutator/stryker-js/releases/tag/v10.1.0)
  adds Vitest 5 support and fixes mutation error reporting. Keep the configured
  command runner, with its existing arithmetic-mutation proof and the new
  sandbox isolation assertion; do not silently change runner semantics.
- [minimatch advisory](https://github.com/advisories/GHSA-g3hv-75wg-m249) and
  [glob advisory](https://github.com/advisories/GHSA-3g3m-2fjr-6pw4) explain the
  scoped security override and Lighthouse hold. The actual three Stryker
  consumers passed targeted compatibility probes, reproduced by the root.
