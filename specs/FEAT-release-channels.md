# FEAT: Separate beta and production release channels

## Problem

`ghcr.io/bassings/couchpotatoserver:latest` is currently written by TWO
workflows — `docker.yml` (on every push to `master` **and** on `v*` tags) and
`docker-publish.yml` (on `v*` tags). Consequences:

1. Any merge to `master` overwrites `:latest`, so a production `docker compose
   pull` on `:latest` can pick up *unreleased* master code.
2. On a `master` push, `docker.yml` stamps the image `CP_VERSION` from the
   *nearest existing tag*, so that image reports the previous release's version
   while containing newer code — a mislabelled image.
3. On a tag both workflows build the same commit and race for `:latest`,
   producing two different digests for one release.

There is no opt-in beta channel: users cannot choose to run pre-release builds
without also being exposed to whatever last landed on master.

## Goal

Two fully separate channels:

- **Beta channel** — every push to `master` publishes a new beta build. Opt-in
  only: it never touches `:latest`.
- **Production channel** — a manual action promotes the *current beta image*
  (the exact bytes) to production and publishes it to `:latest` for all
  default users.

## Decisions (owner-approved 2026-07-20)

- **Beta versioning: minor bump per commit.** Every `master` push increments
  the minor version and publishes `vX.(minor+1).0-beta.1` as a GitHub
  **prerelease**. The bump is computed from the highest minor across **all**
  existing tags (stable *and* beta), so each build is strictly higher than the
  last: `3.10.0-beta.1` → next commit → `3.11.0-beta.1` → `3.12.0-beta.1`. The
  beta suffix is **always `.1`**; minor numbers climb quickly by design (as
  chosen). A workflow re-run on an unchanged HEAD simply bumps the minor
  again — a harmless "wasted" minor, never a collision.
- **Release trigger: manual button** (`workflow_dispatch`). Promotion re-tags
  the current beta's multi-arch digest — **no rebuild** — so production ships
  the exact bytes that were tested in beta.

## Channel model

| Trigger | Git tag / Release | Baked `CP_VERSION` | GHCR tags written | GitHub Release | Writes `:latest`? |
|---|---|---|---|---|---|
| Push to `master` | `vX.Y.0-beta.1` (minor bump) | `X.Y.0` (**base**, no `-beta`) | `:beta`, `:X.Y.0-beta.1`, `:sha-<short>` | prerelease | **No** |
| "Release to Prod" button | `vX.Y.0` (drop `-beta`) | *(re-tag, unchanged)* | `:latest`, `:X.Y.0`, `:X.Y`, `:X` | stable | **Yes** |

### Baked version vs. tag identity (critical)

The image's internal `version.py` (`CP_VERSION` build-arg) is baked with the
**base** version `X.Y.0` — WITHOUT the `-beta.N` suffix. The full `-beta.N`
identity lives only on the git tag, the GitHub prerelease, and the immutable
`:X.Y.0-beta.1` Docker tag. Rationale:

- Promotion re-tags the beta image byte-for-byte, so the promoted prod image
  must already carry a clean version string. If `-beta.1` were baked in, the
  promoted `:latest` image would report `3.10.0-beta.1`, and
  `DockerUpdater._parseVersion` returns `None` for any `-beta` string when
  `include_beta` is off — a stable user on a promoted image would silently
  stop being notified of updates. Baking the base avoids this with **no
  updater code change and no rebuild**.
- Each beta has a unique base (minor bumps every commit: `3.10.0`, `3.11.0`,
  …), so the baked base is unambiguous per beta build.
- Verified against the updater logic: a `:beta` user (`include_beta=True`)
  running baked `3.10.0` sees prerelease `v3.10.0-beta.1` → equal → up to
  date; after the next commit sees `v3.11.0-beta.1` → update. A `:latest`
  user (`include_beta=False`) running promoted `3.10.0` sees stable release
  `v3.10.0` → equal. All correct.

- `:beta` always points at the newest beta build (opt-in testers pin their
  compose to `:beta`).
- `:latest` is written **only** by the promotion action, so it is always a
  stable, released image.
- Promotion re-tags the existing beta digest via
  `docker buildx imagetools create` — it does not run `build-push-action`.

## Why this satisfies the requirements

1. **Betas are opt-in / `:latest` is never a beta.** `:latest` has a single
   writer (the promotion action). A `master` commit only ever writes `:beta*`.
   A tester opts in by (a) pointing compose at `:beta` and (b) enabling the
   existing `updater.include_beta` toggle for update notifications. A default
   `:latest` user who enables `include_beta` is only *notified* of betas (the
   updater never mutates the container), never served one.
2. **Every commit bumps at least a minor on beta.** The version-compute step
   takes the highest minor across all existing tags and adds one.
3. **Beta → prod is byte-identical.** Promotion re-tags the tested digest; no
   second build.

The app-side updater already supports this split and needs **no code change**:
`DockerUpdater.check()` queries `/releases/latest` (which GitHub excludes
prereleases from) when `include_beta` is off, and `/releases?per_page=10`
(includes prereleases) when on; `_parseVersion` already returns `None` for
`-beta` tags unless `include_beta` is set. See
`couchpotato/core/_base/updater/main.py`.

## Component 1 — `scripts/release/next_beta_version.py`

Pure, unit-testable version arithmetic (the only real logic; workflows are
YAML glue that call it).

**Contract:** given the list of existing tags (read from `git tag` or passed
on argv/stdin for tests), print the next beta version string (no leading `v`)
to stdout, e.g. `3.10.0-beta.1`.

**Algorithm (minor bump per commit — every build is strictly higher):**
1. Parse every tag matching `v?MAJOR.MINOR.PATCH(-beta.N)?`; ignore
   non-conforming tags.
2. `max_major` = highest MAJOR across all parsed tags.
3. Among tags with `MAJOR == max_major`, `max_minor` = highest MINOR across
   **all** such tags — stable *and* beta. (A beta already occupies its minor,
   so the next build must go past it. This is what makes every commit strictly
   higher than the last and is the reason "wasted" minors on a re-run are
   acceptable, per the chosen model.)
4. `next = (max_major, max_minor + 1, 0)`; suffix always `-beta.1`.
5. If no conforming tags exist at all, emit `0.1.0-beta.1`.

**Acceptance criteria (tests):**
- AC1: tags `[v3.9.1]` → `3.10.0-beta.1`.
- AC2: tags `[v3.9.0, v3.9.0-beta.1, v3.9.1]` → `3.10.0-beta.1` (lower-minor
  stable/beta don't change the bump).
- AC3: tags `[v3.9.1, v3.10.0-beta.1]` → `3.11.0-beta.1` (an existing beta
  advances the target — every commit is a new minor).
- AC4: chain `[v3.9.1, v3.10.0-beta.1, v3.11.0-beta.1]` → `3.12.0-beta.1`
  (successive commits keep climbing).
- AC5: a patch release is respected — `[v3.8.1, v3.9.1]` → `3.10.0-beta.1`
  (bump the max minor, not max patch).
- AC6: mixed/garbage tags are ignored — `[foo, v3.9.1, nightly]` →
  `3.10.0-beta.1`.
- AC7: empty tag list → `0.1.0-beta.1`.
- AC8: multi-major — `[v3.9.1, v4.0.0]` → `4.1.0-beta.1` (bump within the
  highest major only).
- AC9: the emitted string has no leading `v` and a single trailing newline.
- AC10: a lone beta with no stable — `[v3.10.0-beta.1]` → `3.11.0-beta.1`.
- AC11: a stable already at the bumped minor — `[v3.9.1, v3.10.0]` →
  `3.11.0-beta.1` (never emit a version that collides with an existing tag).

## Component 2 — `docker.yml` (reworked into the beta builder)

- Trigger: `push: branches: [master]`, `paths-ignore: ['**.md', 'docs/**']`.
  **Remove** the `tags: ['v*']` trigger.
- Steps: build + smoke-test (keep the existing test step), compute the beta
  version via the script (full form `X.Y.0-beta.1`; base form `X.Y.0`), then
  push to GHCR the tags `:beta` (moving), `:X.Y.0-beta.1` (immutable),
  `:sha-<short>` with build-arg `CP_VERSION=X.Y.0` (**base**, no suffix).
- Do **not** push `:latest` or `:develop` anywhere.
- Create the git tag `vX.Y.0-beta.1` and a GitHub **prerelease** of the same
  name with an auto-generated changelog since the previous tag, via
  `softprops/action-gh-release` using `GITHUB_TOKEN` (tags created by the
  default token do not trigger further `push:`-tag workflow runs, so there is
  no recursion even before `release.yml`/`docker-publish.yml` are removed).
- Docker Hub push: keep behind the existing `HAS_DOCKER_CREDS` guard, but
  target `:beta` there too (never `:latest`).

## Component 3 — `release-to-prod.yml` (new)

- Trigger: `workflow_dispatch` only. Optional input `beta_tag` (default: the
  newest `:beta-*` / newest prerelease) so a specific beta can be promoted.
- Resolve the beta image digest to promote and the base version (strip
  `-beta.N`).
- Re-tag WITHOUT rebuild:
  `docker buildx imagetools create \
     --tag ghcr.io/…:latest --tag …:X.Y.0 --tag …:X.Y --tag …:X \
     ghcr.io/…@<digest>`.
- Create a **stable** GitHub Release `vX.Y.0` (drop `-beta`) with a changelog.
- Guard: fail if the resolved base version already exists as a stable tag
  (don't silently re-promote / overwrite a shipped release).

## Component 4 — retire `docker-publish.yml` AND `release.yml`

Delete **both**. Together with `docker.yml` they are the three current writers
of `:latest`. In the new model:

- `docker-publish.yml` (tag-triggered rebuild → semver + `:latest`) is fully
  replaced by promotion (re-tag, no rebuild).
- `release.yml` (tag-triggered: source archives + GitHub Release + another
  rebuild → `:latest`) is replaced by `release-to-prod.yml`. The source
  archive (tar.gz/zip) attachment for source installers is **moved into**
  `release-to-prod.yml` for stable releases only (betas are Docker-only), so
  exactly one workflow creates each Release: `docker.yml` for prereleases,
  `release-to-prod.yml` for stable.

After this change, `:latest` has exactly one writer: `release-to-prod.yml`.

## Component 5 — docs

- `docs/development-process.md`: replace the "Release & production deployment"
  section with the two-channel flow (beta auto on merge; manual promote to
  prod; prod deploy still `docker compose pull` on `:latest`, now stable-only).
- `CLAUDE.md`: update the versioning rule (Hard rule #6) to the new model.
- Document the `:beta` opt-in for testers (compose tag + `include_beta`).
- Prod compose (`/var/lib/plexmediaserver/CouchPotato/docker-compose.yml`)
  stays on `:latest` — no prod change required, and none is made as part of
  this PR.

## Out of scope

- Major-version bumps remain manual (floor is minor; a major bump is a
  deliberate hand-cut tag).
- Auto-deploy to prod on promotion (kept manual/SSH per current process).
- Pinning prod compose to a semver tag (possible follow-up; not needed once
  `:latest` is stable-only).

## Verification

- Unit: `pytest tests/unit/test_next_beta_version.py -q` green (AC1–AC9).
- `ruff check .` clean.
- Workflow YAML validated (actionlint if available; otherwise a schema/lint
  pass) and dry-reasoned against the channel table above.
- No change to `couchpotato/**` runtime code; updater behaviour unchanged.
