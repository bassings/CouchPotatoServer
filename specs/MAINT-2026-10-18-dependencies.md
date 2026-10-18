# Dependency refresh and delivery, 18 October 2026

## Scope

Apply the dependency updates published since the previous refresh. Reassess
explicit pins and overrides against the installed graph. Preserve existing
application behaviour and deliver through the full local gate, independent
review, PR CI and cloud review, beta publication and authorised production
promotion and deployment. Prior exemplar: `MAINT-2026-10-13-dependencies.md`.

## Acceptance criteria

- AC-QA-1: Python 3.14 installs the updated production and development requirements;
  the full `make verify` gate passes with those versions.
- AC-QA-2: A clean `npm ci` succeeds; the installed jsdom/undici versions satisfy
  jsdom's declared dependency range; Vitest and coverage versions agree.
- AC-SEC-1: Audit the resolved Python and npm graphs and production image.
  No known vulnerabilities are introduced; required image/security gates pass.
- AC-ARCH-1: Every explicit pin/override is triaged as update, retain or remove.
  Remove stale overrides for packages absent from the graph, and remove the
  undici override that forces version 7 despite jsdom declaring version 8.
  Retain security floors that still protect installed dependencies.
- AC-OPS-1: Keep all Ruff pins in CI and requirements in sync. Build the Alpine
  runtime image without cache, confirm startup/health and preserve rollback.
- AC-A11Y-1: The updated axe and browser tooling passes accessibility checks in
  both themes and the existing phone-width suite without weakening assertions.
- AC-DESIGN-1: Existing browser workflows pass with the updated tooling and
  application framework; no UI or design-system changes are intended.
- AC-PROD-1: The tested beta is promoted without rebuild after all required
  checks pass; take a verified backup and record rollback before deployment.
  Verify library counts, detail/release rendering, wanted/manage, settings
  persistence and provider connectivity after deployment.
- AC-SIMP-1: No new package or application abstraction is added for this refresh.

## Triage snapshot

PyPI/npm metadata and GitHub action tags were queried on 18 October 2026.
This snapshot defines the batch; later releases are assessed separately.

| Dependency | Current | Target / disposition |
| --- | --- | --- |
| FastAPI | 0.143.0 | 0.143.5 |
| Starlette | 1.7.0 | 1.8.0 |
| chardet | 7.6.0 | 7.7.0 |
| subliminal | 2.7.1 | 2.8.0 |
| tomlkit | 0.15.1 | 0.15.2 |
| filelock | 4.1.1 | 4.2.2 |
| platformdirs | 4.13.0 | 4.13.4 |
| Ruff | 0.17.0 | 0.17.1, including both CI copies |
| axe Playwright | 4.13.0 | 4.14.0 |
| Playwright | 1.64.0 | 1.64.1 |
| Vitest / coverage-v8 | 5.0.4 | 5.0.5 together |
| jsdom | 30.1.2 | 30.1.3 |
| qs override | 6.16.0 | 6.16.1 |
| undici override | ^7.28.0 | Remove; jsdom declares ^8.12.1 and resolves 8.12.2 |
| tmp, lodash, basic-ftp, ip-address, path-to-regexp, uuid, js-yaml overrides | Not installed | Remove obsolete constraints; preserve audit gate |
| vite, lodash-es, ws overrides | Current installed versions | Retain security constraints |
| Claude action | v1.0.248 | v1.0.252 |
| Sonar scanner | 5.0.1 | 5.0.2 |
| Other Python/Node pins and development lower bounds | Current | Retain; fresh environments resolve current versions |
| Docker Python base digest | Current published manifest | Retain identical digest in both stages |
| Docker pip | 26.2.1 | Retain; current |
| gitleaks / Trivy action / dependency-review action | Current | Retain |
| Other GitHub Actions | Floating current major | Retain; receives compatible patch/minor updates |
| Alpine security minimums | Patched minimums | Retain; image scan verifies resolved packages |
| rarfile | 4.5 | Retain; current stable, documented v5 config migration not released |

## Verification approach

These are dependency-only changes, so no meaningful new behavioural failing
test distinguishes the published versions. Use the existing application tests
against freshly installed candidates. Record the pre-change jsdom/undici
contract mismatch and prove it resolves after removing the stale override.
Any application adaptation discovered during verification requires its own
failing regression test before implementation. Do not weaken existing gates.

## Tasks

- [ ] T1 Apply updates and record full local verification. — state: building
- [ ] T2 Independent local review, PR CI/cloud review and merge. — state: queued
- [ ] T3 Beta publication, backup, production promotion and deployment checks. — state: queued

## Release-note assessment

- [Starlette 1.8.0](https://github.com/Kludex/starlette/releases/tag/1.8.0)
  raises the minimum Python to 3.11, compatible with production 3.14. Its
  file-response, multipart, session and compression fixes are covered by the
  application and browser gate.
- [Subliminal 2.8.0](https://github.com/Diaoul/subliminal/releases/tag/2.8.0)
  adds provider-result reporting. Verify the plugin's dictionary lookup and
  subtitle-saving integration against the real package, beyond signature checks.
- [jsdom 30.1.3](https://github.com/jsdom/jsdom/releases/tag/v30.1.3)
  fixes cross-origin XHR credential/cookie handling and focus/style regressions.
  The pre-change graph forced undici 7.30.0 against jsdom's ^8.11.2 requirement.
  Removing that override resolves undici 8.12.2 for jsdom's new ^8.12.1 range.
- [Vitest 5.0.5](https://github.com/vitest-dev/vitest/releases/tag/v5.0.5)
  preserves Vite's file-deny defaults and fixes runner lifecycle issues.
- [chardet 7.7.0](https://github.com/chardet/chardet/releases/tag/7.7.0)
  fixes quadratic scans on hostile input and validates detected encodings.
- Filelock 4.2.x fixes interruption/hold-count and stale-lock handling;
  platformdirs 4.13.x fixes directory isolation and platform resolution.
  Tomlkit 0.15.2 fixes malformed-input parsing and document round-tripping.
- Ruff 0.17.1 and Playwright 1.64.1 are patch fixes. Axe 4.14.0 upgrades its
  accessibility rules; keep the existing assertions and fix real regressions.
- qs 6.16.1 fixes object mutation, encoding and nesting-limit handling.
- [Sonar scanner 5.0.2](https://github.com/SonarSource/sonar-scanner-npm/releases/tag/5.0.2)
  hardens provisioned cache paths and secret redaction. Update both the Makefile
  pin and direct CLI default. Sonar remains reporting-only after merge.
- Claude action v1.0.248 to v1.0.252 updates its bundled CLI/SDK. Editing this
  workflow triggers its documented self-validation skip on the PR; inspect the
  visible skip notice and use the independent local reviews for that surface.
  Confirm the updated action executes a real review after merge.
