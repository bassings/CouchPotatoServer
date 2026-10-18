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
- AC-A11Y-2: Movie, chart, recommendation and search cards expose their visible title,
  year and badges in their accessible names, so voice selection and screen
  reader labels cannot drift from the rendered card content. Preserve
  meaningful status/quality information and align the charts test fixture.
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
| Bundled htmx | 2.0.4 | 2.0.11; retain supported version 2 API, assess version 4 separately |
| Bundled Alpine | 3.15.12 | 3.17.4 |
| Bundled Tailwind Play CDN | 3.4.17 | Retain; current published version of that browser bundle |
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

## Bundled browser assets

The active UI also ships three libraries outside package.json. htmx 2.0.11
and Alpine 3.17.4 are included in this refresh, using the official npm release
files with registry integrity verification. The htmx bytes additionally match
the official repository at commit `fa978b24e75fb03c137bf2cdae4fef0e711cf8a1`.
Rename the htmx asset and update its template reference; the custom-base route
test must fetch the referenced files and fail on missing assets. Existing
browser, accessibility and phone-width tests exercise the library upgrades.

Hold htmx 4: it changes attributes, events and extension interfaces, requiring
a separate application migration. The npm version-2 distribution remains
available and receives fixes. Hold Tailwind at 3.4.17: the existing file is
byte-identical to the versioned official Play CDN response. Although npm has
Tailwind 3.4.19 and 4.3.3, the Play CDN rejects 3.4.19 as an unknown version.
Version 4 changes configuration/theme integration, so substituting it would
require a design-system/build migration beyond a compatible dependency refresh.

## Verification findings carried into this batch

The first full gate passed 4,950 Python unit tests, 42 integration tests,
311 JavaScript tests, Chromium and worker isolation. Axe 4.14 then exposed
`label-content-name-mismatch` on wanted/library/chart cards: explicit labels
omitted visible badge or placeholder text. Correct that single class using
content-derived names across all four card templates and matching fixtures;
retain the new rule and the full WCAG 2.2 AA gate. The final gate is rerun
after this fix, browser-bundle refresh and compatible transitive npm refresh.

The transitive npm check includes installed packages, not only direct entries.
Refresh packages within their parents' supported ranges; hold unsupported
major upgrades and uninstalled optional peers/platform artefacts. Forcing
unsupported versions globally is the same failure mode as the stale undici
override removed above.

Compatible transitive refreshes taken: css-color 7.1.7, Puppeteer browsers
3.2.5, baseline-browser-mapping 2.11.29, caniuse-lite 1.0.30001816,
electron-to-chromium 1.5.459, es-module-lexer 3.0.4, modern-tar 0.8.6,
node-releases 2.0.59, puppeteer-core 25.14.0, web-features 3.43.0,
whatwg-url 17.3.0 and zod 4.6.7. No lockfile package entries added or removed.
Retain parent-pinned OpenTelemetry 0.220 and DevTools protocol snapshots;
upgrading those requires a supported Sentry/Lighthouse/Puppeteer release.

Use versioned htmx and Alpine filenames and update the service-worker precache
list with them, so renamed assets cannot produce precache 404s and the new
Alpine file cannot be served from an existing cache under its former URL.
Search poster controls have their visible title outside the button; retain
movie identity with screen-reader text inside the control while allowing
its visible content to contribute to the native name.
