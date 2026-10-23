# Dependency refresh, 13 October 2026

## Scope

Update the Python and Node.js packages that have newer compatible releases, and
pin both Docker build stages to the same current Python base image digest.
Keep the existing Alpine security minimums until the base image contains all
the fixed package versions.

## Acceptance criteria

- Python 3.14 resolves and installs the updated production requirements.
- `npm ci` resolves the updated lockfile and `npm audit` reports no advisories.
- Both Docker stages use the same published multi-platform digest and the
  production image builds and starts. A unit guard fails if either stage loses
  its digest or the two stages drift apart.
- The repository's full verification gate passes.

## Triage

| Dependency | Current | Available | Decision |
| --- | --- | --- | --- |
| pydantic | 2.14.0 | 2.14.1 | Update; its declared `pydantic-core==2.50.1` remains transitive. |
| filelock | 4.1.0 | 4.1.1 | Update. |
| platformdirs | 4.12.4 | 4.13.0 | Update. |
| vitest and coverage-v8 | 5.0.3 | 5.0.4 | Update both together. |
| python:3.14-alpine | Floating tag | Python 3.14.8, Alpine 3.24.2 | Pin the current multi-platform digest in both stages. |
| rarfile | 4.5 | 4.5 | Hold; 4.5 is current and the documented 5.0 config change has not been released. |

PyPI metadata, `npm outdated` after `npm ci`, and `docker buildx imagetools`
were checked on 13 October 2026. `npm audit` reported zero vulnerabilities.

The npm override pins were also checked against every package-lock path.
`qs` and `ws` resolve to their latest published versions; `vite`, `lodash-es`
and `undici` resolve within their existing ranges. The other overrides
(`tmp`, `lodash`, `basic-ftp`, `ip-address`, `path-to-regexp`, `uuid`,
`js-yaml`) are absent from the current graph. They impose no installed version
today. Their historical override policy is retained for a separate cleanup:
some are exact compatibility pins and removing them offers no current upgrade.
In particular, `basic-ftp@6.0.1` is below 6.2.3, while `path-to-regexp@0.1.13`
and `uuid@11.1.1` are below newer major releases. None is installed, so a
version-only edit to those overrides would change no shipped package.
