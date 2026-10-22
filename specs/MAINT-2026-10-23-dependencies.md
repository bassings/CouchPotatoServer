# Pipeline security repair and dependency refresh, 23 October 2026

## Scope

Resolve nightly CI security failures and reassess all Python, Node, bundled
browser, Docker and CI-tool dependencies, including exact pins, lower bounds,
overrides and parent-pinned transitives. Prior exemplar:
`MAINT-2026-10-18-dependencies.md`. Preserve unrelated main-checkout work.

## Observed failures

Nightly CI runs 39801141502 and 39622241938 fail the existing Docker scan:
certifi 2026.7.22 has GHSA-6q48-6c7w-9gw2 and musl/musl-utils 1.2.6-r2
have CVE-2026-107891. Required fixed versions are certifi 2026.10.19 and
Alpine musl/musl-utils 1.2.6-r3. Keep every severity in the existing gate;
do not suppress the findings. Dependabot PR 550's Python 3.15 change fails
three existing cross-file interpreter-alignment guards, not application tests.

## Acceptance criteria

- AC-QA-1: Fresh Python 3.15 runtime/development environments resolve, and the
  canonical full local gate passes using the production interpreter. Keep the
  CI matrix, auxiliary Python jobs and local Alpine runner aligned with both
  Docker stages. If measured incompatibility prevents 3.15, record it and ship
  the security fixes with the current supported interpreter instead.
- AC-QA-2: Fresh npm ci, unit, Chromium, mobile, isolation and accessibility
  tests pass with a valid installed graph and supported declared Node engines.
- AC-SEC-1: Certifi and musl findings are fixed in the resulting runtime image;
  Python/npm audits and full-severity image scans pass. Preserve secret checks.
- AC-SEC-2: Framework updates preserve authentication, CSRF, untrusted-input
  validation, redirects, private logging and dependency integrity. Verify any
  newly introduced telemetry API has no exporter or outbound telemetry enabled.
- AC-ARCH-1: Record an update, retain, remove or evidence-backed hold for every
  explicit dependency/pin/override and remaining outdated installed transitive.
  Accept supported compatible updates; do not force unsupported parent majors.
- AC-OPS-1: Both Docker stages share a verified immutable multi-platform base.
  Establish patched musl minimums, keep Ruff and tooling references consistent,
  build without cache and prove startup, assets, health, stop and restart.
- AC-A11Y-1: Updated Alpine and browser tooling preserve both themes and phone
  workflows with no accessibility exclusions or weakened assertions.
- AC-DESIGN-1: The bundled-library refresh preserves existing responsive
  layouts and core browser workflows; no visual redesign is intended. Verify
  template/style preservation and the browser/mobile gate.
- AC-DATA-1: Dateutil 3 time-zone changes preserve the real APScheduler and
  application date-parsing boundaries, including DST transitions. No schema or
  destructive-operation changes are needed for this dependency refresh.
- AC-PROD-1: Merge after independent local reviews and all required CI/cloud
  checks. Verify the exact resulting beta and the updated Claude action runs.
  Promote the tested digest without rebuild under existing authority, verify a
  recoverable backup and rollback target, then validate production counts,
  detail/releases, wanted/library, settings persistence and Jackett search.
- AC-SIMP-1: Keep the fixes scoped. Add no application framework or abstraction;
  accept only required upstream graph additions. Preserve CodernityDB migration.

## Initial package triage

Registry metadata was checked on 23 October 2026. Lower bounds are current
unless the resolved graph demonstrates otherwise. Reassess pins using actual
parent constraints and release notes, not only semver labels.

| Dependency | Current | Candidate |
| --- | --- | --- |
| fastapi | 0.143.5 | 0.161.0 |
| starlette | 1.8.0 | 1.9.0 |
| dulwich | 1.2.17 | 1.2.19 |
| certifi | 2026.7.22 | 2026.10.19 |
| qbittorrent-api | 2026.10.0 | 2026.10.1 |
| python-dateutil | 2.9.0.post0 | 3.0.0 |
| filelock | 4.2.2 | 4.2.4 |
| platformdirs | 4.13.4 | 4.13.5 |
| coverage | 7.16.2 | 7.17.0 |
| ruff | 0.17.1 | 0.17.2 |
| Python runtime | 3.14 | 3.15, with all runner references updated together |
| Docker pip | 26.2.1 | 26.2.2, builder only |
| Alpine.js browser bundle | 3.17.4 | 3.17.5, official bytes and versioned asset |
| Claude review action | 1.0.252 | 1.0.258, latest exact upstream stable tag |
| Compatible Node transitives | Existing lock | Refresh within parent ranges |

## Initial holds and retained constraints

- htmx 2.0.11 remains the upstream latest stable tag. Version 4 is the next
  distribution and requires an application migration, so retain current stable.
- Tailwind Play CDN remains 3.4.17. The 3.4.19 endpoint still returns an unknown
  version error; 4.3.3 requires a separate theme/build migration.
- rarfile 4.5 remains current stable. Its documented future v5 config migration
  is not a released update to take in this batch.
- Sentry's OpenTelemetry instrumentation 0.220 and Lighthouse's DevTools
  protocol snapshot are parent-pinned; refresh parents where supported, not
  global overrides. Recheck the resolved graph after compatible updates.
- Keep vite, lodash-es, qs and ws security constraints while their actual
  parent ranges still admit vulnerable/unsupported versions.
- CodernityDB is the sole remaining vendored Python library and is retained
  for supported migration. Replacing it is outside a routine dependency bump.

## Release-note assessment and verification

- [Certifi advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
  removes compromised emSign roots; install the latest corrected CA bundle.
- [Alpine security database](https://secdb.alpinelinux.org/v3.24/main.json)
  records CVE-2026-107891 fixed in musl 1.2.6-r3.
- [Python 3.15 porting guide](https://docs.python.org/3.15/whatsnew/3.15.html)
  covers interpreter removals and changed defaults. Exercise the real app,
  SQLite, native dependencies and the Alpine image, not only config guards.
- [FastAPI releases](https://fastapi.tiangolo.com/release-notes/) change nullable
  body handling and form/query validation between the existing and candidate
  versions; use the auth/settings/API and real browser suites as boundaries.
- [Starlette 1.9](https://github.com/Kludex/starlette/releases/tag/1.9.0) streams
  TestClient bodies and fixes URL escaping, host matching and Vary preservation.
- [Dateutil 3.0](https://github.com/dateutil/dateutil/releases/tag/3.0.0) replaces
  bundled timezone data with tzdata and changes nonexistent-time offsets to
  PEP 495 semantics. Check scheduler triggers and date parsing before taking it.
- Workflow edits trigger Claude's documented self-validation skip. Confirm its
  visible notice and independent local review, then rerun after merge to prove
  the new action executes a real review before production promotion.

Dependency version changes use existing application contracts and fresh graph
checks. New behavioural adaptations require a demonstrated failing regression
before the minimum fix. Any new guard requires a real mutation/failure/restore
proof. Record verification and final dispositions in the local conductor log.

## Completed inventory details

All 13 GitHub Action repositories were checked against current upstream tags.
The floating majors are current; exact dependency-review v5.0.0 and Trivy
v0.36.0 remain current. Only the exact Claude action changes, to v1.0.258;
the upstream diff contains CLI/SDK and lock updates. Gitleaks v8.30.1 and
Sonar scanner 5.0.2 remain current. CI uses supported Node 24; the application
ships no Node runtime.

The candidate Python 3.15 base is the verified multi-platform digest
`sha256:d44b1254cb92329418d164b22b20d86bbd3869d48e80e09e476531a409a728bb`.
It contains Python 3.15.1 and Alpine 3.24.3, with musl/musl-utils 1.2.6-r3,
OpenSSL libraries 3.5.9-r0, libuuid 2.42.3-r1 and zlib 1.3.2-r1. C-ares is
absent from this base, so its source comment's condition for dropping the
explicit package minimum has not been met. Retain patched package floors.

The retained Tailwind bundle is byte-identical to the official versioned
3.4.17 CDN response, SHA256
`176e894661aa9cdc9a5cba6c720044cbbf7b8bd80d1c9a142a7c24b1b6c50d15`.
Every direct Node manifest entry (including exact aliases and overrides) was
checked: direct tooling versions remain current. Compatible installed Node
transitives are refreshed; absent optional peers/platform binaries are not
installed solely to make an outdated report empty.

All unchanged Python exact pins and development lower bounds in the two
requirements files were checked against PyPI and remain current. Only the ten
Python candidates listed above differ. Fresh resolution also reassesses the
full transitive Python graph; any unresolved update must be recorded before
completion.

## Final graph triage

Fresh Python 3.15.1 resolution contains 87 compatible distributions. The full
resolved graph has no outdated packages and its audit reports no known
vulnerabilities. Fresh npm ci and npm ls succeed, npm audit is clean, and the
installed Node engine constraints accept the declared 22.22.2, 24.15.0 and
26.0.0 minimums. The compatible refresh changes 45 lockfile version entries,
including platform artefacts.

After refresh, npm reports 122 outdated installed rows across 80 unique
locations and 74 package families. Each location was matched to its actual
installed incoming dependency edges. None admits the latest version across all parent constraints; absent
optional peers are excluded. The table records a blocking parent range for
each family. Shared installations may also have parents that allow newer
versions: forcing that shared copy still violates the recorded constraint.
Entries whose upstream latest tag is older than the installed parent-selected
version are retained rather than downgraded.

| Retained Node family | Installed | Latest tag | Blocking parent range / reason |
| --- | --- | --- | --- |
| @babel/helper-string-parser | 7.29.7 | 8.0.6 | @babel/types: ^7.29.7 |
| @babel/helper-validator-identifier | 7.29.7 | 8.0.6 | @babel/types: ^7.29.7 |
| @babel/parser | 7.29.9 | 8.0.7 | magicast: ^7.29.7 |
| @babel/types | 7.29.8 | 8.0.6 | magicast: ^7.29.7 |
| @formatjs/ecma402-abstract | 2.3.6 | 3.2.0 | @formatjs/icu-messageformat-parser: 2.3.6 |
| @formatjs/fast-memoize | 2.2.7 | 3.1.7 | @formatjs/ecma402-abstract: 2.2.7 |
| @formatjs/icu-messageformat-parser | 2.11.4 | 3.5.22 | intl-messageformat: 2.11.4 |
| @formatjs/icu-skeleton-parser | 1.8.16 | 2.1.12 | @formatjs/icu-messageformat-parser: 1.8.16 |
| @formatjs/intl-localematcher | 0.6.2 | 0.9.0 | @formatjs/ecma402-abstract: 0.6.2 |
| @jridgewell/gen-mapping | 0.4.0-beta.0 | 0.3.13 | latest tag is older than parent-selected version |
| @opentelemetry/api | 1.9.1 | 1.10.0 | @opentelemetry/core: >=1.0.0 <1.10.0 |
| @opentelemetry/api-logs | 0.220.0 | 0.223.0 | @opentelemetry/instrumentation: 0.220.0 |
| @opentelemetry/core | 2.12.0 | 3.0.0 | @opentelemetry/resources: 2.12.0 |
| @opentelemetry/instrumentation | 0.220.0 | 0.300.0 | @sentry/node: ^0.220.0 |
| @opentelemetry/resources | 2.12.0 | 3.0.0 | @opentelemetry/sdk-trace: 2.12.0 |
| @opentelemetry/sdk-trace | 2.12.0 | 3.0.0 | @opentelemetry/sdk-trace-base: 2.12.0 |
| @paulirish/trace_engine | 0.0.65 | 0.0.67 | lighthouse: 0.0.65 |
| @sec-ant/readable-stream | 0.4.1 | 0.7.0 | get-stream: ^0.4.1 |
| @sentry/conventions | 0.16.0 | 0.27.0 | @sentry/core: ^0.16.0 |
| @sentry/core | 10.76.2 | 11.9.0 | @sentry/node: 10.76.2 |
| @sentry/node | 10.76.2 | 11.8.0 | lighthouse: ^10.0.0 |
| @sentry/node-core | 10.76.2 | 10.75.2 | latest tag is older than parent-selected version |
| @sentry/opentelemetry | 10.76.2 | 11.8.0 | @sentry/node: 10.76.2 |
| @sentry/server-utils | 10.76.2 | 11.8.0 | @sentry/node: 10.76.2 |
| @types/jsesc | 2.5.1 | 3.0.3 | @babel/generator: ^2.5.0 |
| @typescript/old:typescript@^6 | 6.0.3 | 7.0.2 | @typescript/typescript6: npm:typescript@^6 |
| @vitest/istanbul-lib-coverage | 1.0.2 | 2.0.0 | @vitest/coverage-v8: ^1.0.2 |
| @vitest/istanbul-lib-report | 1.0.2 | 2.0.0 | @vitest/coverage-v8: ^1.0.2 |
| angular-html-parser | 10.11.0 | 10.13.0 | @stryker-mutator/instrumenter: ~10.11.0 |
| ansi-regex | 5.0.1 | 6.4.0 | strip-ansi: ^5.0.1 |
| ansi-styles | 4.3.0, 6.2.3 | 7.0.0 | wrap-ansi: ^6.2.1; wrap-ansi: ^4.0.0 |
| balanced-match | 4.0.4 | 5.0.0 | brace-expansion: ^4.0.2 |
| chalk | 5.6.2 | 6.0.1 | @stryker-mutator/core: ~5.6.0 |
| chromium-bidi | 157.0.8090-0 | 158.0.8118-0 | puppeteer-core: 157.0.8090-0 |
| cliui | 8.0.1 | 9.0.1 | yargs: ^8.0.1 |
| color-convert | 2.0.1 | 3.1.3 | ansi-styles: ^2.0.1 |
| color-name | 1.1.4 | 2.1.1 | color-convert: ~1.1.4 |
| commander | 14.0.3 | 15.0.0 | @stryker-mutator/core: ~14.0.0 |
| configstore | 7.1.0 | 8.0.0 | lighthouse: ^7.0.0 |
| define-lazy-prop | 2.0.0 | 3.0.0 | open: ^2.0.0 |
| devtools-protocol | 0.0.1687809, 0.0.1704951 | 0.0.1724436 | lighthouse: 0.0.1687809; puppeteer-core: 0.0.1704951 |
| dot-prop | 9.0.0 | 10.2.0 | configstore: ^9.0.0 |
| emoji-regex | 10.6.0, 8.0.0 | 11.0.0 | string-width: ^10.3.0; string-width: ^8.0.0 |
| es-module-lexer | 2.3.2 | 3.0.4 | vitest: ^2.3.2 |
| escape-string-regexp | 4.0.0 | 5.0.0 | chrome-launcher: ^4.0.0 |
| execa | 9.6.1 | 10.2.0 | @stryker-mutator/core: ~9.6.0 |
| fast-uri | 3.1.9 | 4.2.3 | ajv: ^3.0.1 |
| intl-messageformat | 10.7.18 | 12.1.4 | lighthouse: ^10.5.3 |
| is-docker | 2.2.1 | 4.0.0 | is-wsl: ^2.0.0 |
| is-fullwidth-code-point | 3.0.0 | 5.1.0 | string-width: ^3.0.0 |
| is-wsl | 2.2.0 | 3.1.1 | chrome-launcher: ^2.2.0 |
| isexe | 2.0.0 | 4.0.0 | which: ^2.0.0 |
| mdn-data | 2.27.1 | 2.37.2 | css-tree: 2.27.1 |
| mutation-testing-elements | 3.8.4 | 3.9.0 | @stryker-mutator/core: 3.8.4 |
| mutation-testing-metrics | 3.8.4 | 3.9.0 | @stryker-mutator/api: 3.8.4 |
| mutation-testing-report-schema | 3.8.4 | 3.9.0 | @stryker-mutator/api: 3.8.4 |
| mute-stream | 3.0.0 | 4.0.0 | @inquirer/core: ^3.0.0 |
| nanoid | 3.3.20 | 6.0.2 | postcss: ^3.3.20 |
| open | 8.4.2 | 11.0.4 | lighthouse: ^8.4.0 |
| path-key | 3.1.1 | 4.0.0 | cross-spawn: ^3.1.0 |
| pretty-ms | 9.3.1 | 10.0.0 | execa: ^9.2.0 |
| shebang-regex | 3.0.0 | 4.0.0 | shebang-command: ^3.0.0 |
| source-map | 0.7.6 | 0.8.0 | @stryker-mutator/core: ~0.7.4 |
| string-width | 4.2.3, 7.2.0 | 8.3.0 | cliui: ^4.2.0; cliui: ^7.2.0; wrap-ansi: ^7.0.0 |
| strip-ansi | 6.0.1 | 7.2.0 | cliui: ^6.0.1 |
| type-fest | 4.41.0 | 5.10.0 | dot-prop: ^4.18.2 |
| typed-rest-client | 2.3.1 | 3.1.2 | @stryker-mutator/core: ~2.3.0 |
| undici-types | 8.9.0 | 8.12.3 | @types/node: ~8.9.0 |
| unicorn-magic | 0.3.0 | 0.4.1 | npm-run-path: ^0.3.0 |
| which | 2.0.2 | 7.0.0 | cross-spawn: ^2.0.1 |
| why-is-node-running | 3.2.1 | 3.2.3 | vitest: 3.2.1 |
| wrap-ansi | 7.0.0, 9.0.2 | 10.0.2 | cliui: ^9.0.0; cliui: ^7.0.0 |
| yargs | 17.7.3 | 18.2.0 | lighthouse: ^17.3.1 |
| yargs-parser | 21.1.1 | 22.0.0 | lighthouse: ^21.0.0 |

The Python 3.15 migration also changes the interpreter used by the informational
mutation workflow. Run that workflow on the merged commit to verify its real
Python and JavaScript runners, rather than inferring compatibility from a tool
version or a no-op changed-file mutation check. Review survivors without
inventing a score gate.
