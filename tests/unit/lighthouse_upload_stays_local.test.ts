/**
 * `lhci autorun` must not publish rendered pages of the user's library.
 *
 * `lighthouserc.js` drives Lighthouse over `/`, `/available/`, `/add/` and
 * `/settings/` on `localhost:5050` -- which is the PRODUCTION port for this
 * project, not the dev one on 5051 -- and a Lighthouse HTML report embeds
 * full-page screenshots of everything it rendered.
 *
 * With `upload.target: 'temporary-public-storage'`, `@lhci/cli` POSTs that
 * report to
 * `https://us-central1-lighthouse-infrastructure.cloudfunctions.net/saveHtmlReport`
 * and prints the public URL it gets back. Nobody has to opt in: it is what
 * `npm run test:lighthouse` does, and `npm run test:all` runs that. `autorun`
 * performs the upload even when the assertions FAIL, so the operator is most
 * likely to trigger it at the moment they believe the run aborted.
 *
 * The payload is the user's own media library. Under this project's loss
 * ranking that is irreplaceable-tier: published to a third party, cached and
 * indexed beyond our reach, and not retractable by deleting anything locally.
 *
 * WHY AN ALLOWLIST AND NOT A DENYLIST
 *
 * The obvious guard is "target must not be temporary-public-storage". That is
 * the same defect T57 spent four review rounds removing from the test fixtures:
 * a list of known-bad names is wrong again the day the tool adds a new one, and
 * nothing announces that it did. So this asserts the target is one of the
 * values that keep the report ON THIS MACHINE. A new publishing target added
 * upstream fails this guard the day it ships, with no edit here.
 *
 * WHY THERE ARE NO GUARDS ON THE COMMENT PROSE
 *
 * Two assertions here used to check that the upload block did not claim
 * uploading was off, and did say where reports go. Both are gone, and their
 * history is the argument for not writing them again. The first reduced to
 * `expect(false).toBe(false)`. Splitting it in two reproduced the vacuity in
 * the other half. Scoping both to `//` lines fixed that, and review then got
 * through all three of `/* *\/` block comments, a trailing comment on the
 * value line, and a comment reading "Verified against http://localhost:5050/"
 * -- which says nothing about where reports go and passes because `localhost`
 * contains `local`. Meanwhile an accurate, useful comment tripped the other
 * guard as a false claim.
 *
 * Two regexes cannot pin natural language. A guard that reddens on a correct
 * comment teaches people to edit the guard, which is how the vacuous versions
 * came to be written in the first place. Prose belongs to review.
 *
 * KNOWN LIMITS, both recorded rather than implied:
 *
 * 1. This reads the configuration, so it proves what `lhci` is told to do. It
 *    does not intercept the network, so it cannot prove `@lhci/cli` honours it.
 *    Deliberate: the alternative is running Lighthouse in the unit suite.
 *
 * 2. Environment variables outrank the rc file entirely. `cli.js` calls
 *    `.env('LHCI')`, so `LHCI_TARGET=temporary-public-storage npm run
 *    test:lighthouse` publishes, and no config-reading guard can see that.
 *    Nothing in this repo or in `.github/` sets any `LHCI_*` variable, and lhci
 *    does not run in CI at all, so there is no live risk -- but a reader must
 *    not mistake this guard for one that cannot be overridden.
 *
 * 3. THE DOCKER BUILD CONTEXT ROUTE IS NOT GUARDED BY ANY TEST. `Dockerfile`'s
 *    `COPY --chown=couchpotato:couchpotato . ${APP_DIR}/` copies the whole
 *    build context, which is the filesystem, not the git index -- so a report
 *    written to `.lighthouseci/` is invisible to git and fully visible to
 *    docker unless `.dockerignore` excludes it. That exclusion exists today,
 *    `.lighthouseci/` in `.dockerignore`, and it is correct today, verified
 *    against a real `docker build`. It used to be pinned here by a hand-rolled
 *    matcher, `isExcludedFromDockerContext`, which read and evaluated
 *    `.dockerignore` itself rather than asking docker. That matcher was wrong
 *    against a real `docker build` three separate times: first for not
 *    modelling a leading `/`, then for not modelling `**`, and a third time
 *    when `!./.lighthouseci/` -- a `./`-prefixed negation -- passed the
 *    cleanup regex unmatched and left `excluded` at its previous value, a
 *    false green in exactly the case its own failure message promised to
 *    catch. Per CLAUDE.md rule 11, three failed fixes in one area means the
 *    shape is wrong rather than the next patch being closer, so the matcher
 *    and its test were removed rather than revised a fourth time. **A reader
 *    must not conclude the docker route is tested: it is closed, but
 *    unguarded.** T65 (`specs/REMEDIATION-2026-08.md`) owns writing the real
 *    guard, which asks docker's own matching rules rather than modelling them
 *    by hand -- the same lesson the git-ignore assertion below already
 *    applies, via `git check-ignore`, to the git route.
 */
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const require = createRequire(import.meta.url);

/** Targets that write the report to this machine and send nothing anywhere. */
const LOCAL_ONLY_TARGETS = ['filesystem'];

/** The rc file this repo relies on, found the way `lhci` itself finds it.
 *
 * THE DEFECT THIS REPLACES: both this function and `resolvedUpload()` used to
 * hardcode `path.join(REPO_ROOT, 'lighthouserc.js')`. `@lhci/utils`'s own
 * `RC_FILE_NAMES` ranks `.lighthouserc.cjs`, `lighthouserc.cjs` and
 * `.lighthouserc.js` ABOVE plain `lighthouserc.js`, and `findRcFile` returns
 * the first of those that exists -- so a stray `.lighthouserc.js` at the repo
 * root shadows the real config entirely. Measured: creating one at the root
 * with `target: 'temporary-public-storage'` left every assertion in this file
 * green, because the hardcoded path kept reading the config that was never
 * going to run. That is the exact class this file exists to close -- ask the
 * tool which file wins, do not hardcode an assumption about it.
 */
function findConfigFile(): string {
  // `@lhci/utils/src/lighthouserc.js`: NOTE the `src/` path. That package's
  // own package.json declares no `exports`, `files` or `main` field, so
  // `src/` is not a published API surface -- nothing stops a future
  // `@lhci/utils` release from renaming or moving this file. If that happens
  // it reddens `npm run test:unit` (a `require` failure, MODULE_NOT_FOUND)
  // rather than the optional `npm run test:lighthouse` script, which is the
  // point: pinned exactly in package.json alongside `@lhci/cli` (see F7 in
  // specs/REMEDIATION-2026-08.md) so both packages read the same build of
  // this loader, but the import path itself is still unofficial and worth a
  // reader knowing that before "fixing" a failure here by guessing a new path.
  const { findRcFile } = require('@lhci/utils/src/lighthouserc.js');
  const rcFile = findRcFile(REPO_ROOT);
  expect(
    rcFile,
    `@lhci/utils' own resolver (findRcFile) found no lighthouserc file under ` +
      `${REPO_ROOT}. Either lighthouserc.js was renamed/removed, or a ` +
      `higher-ranked name (.lighthouserc.cjs, lighthouserc.cjs, ` +
      `.lighthouserc.js -- see RC_FILE_NAMES) is shadowing it, which is the ` +
      `exact failure this resolver exists to catch rather than hide.`,
  ).toBeDefined();
  return rcFile as string;
}

function config() {
  // Loaded, not read as text: a string search would pass on a commented-out
  // line and fail on a value assembled at run time.
  //
  // NOTE for anyone mutating this file to check the guard still bites: this
  // goes through Node's CommonJS cache, NOT vite's module graph. Within one
  // process the config is read once, so `npm run test:unit:watch` will report
  // a stale result and will not even re-trigger on a change here. The gate is
  // unaffected -- `npm run test:unit` is `vitest run`, a fresh process each
  // time -- but verify mutations that way, or you will conclude the guard
  // works when it never re-read the file.
  return require(findConfigFile());
}

/** What `lhci` itself will use, after merging every key shape it accepts.
 *
 * THE RULE, because getting it half right is what this file did: assertions
 * about BEHAVIOUR read this resolver; only the shape check reads the raw
 * `ci.upload` key. An earlier revision resolved `target` here and left
 * `outputDir` reading the raw key four lines below, so the same sibling-key
 * attack simply aimed at the other value -- and that is the worse one.
 * `target` decides whether reports go on the network; `outputDir` decides
 * whether they land somewhere .gitignore and .dockerignore cover. Measured: a
 * sibling `lhci: { upload: { target: 'filesystem' } }` leaves outputDir
 * undefined, lhci resolves it against the cwd, and reports land in the
 * REPOSITORY ROOT -- committable and inside the docker build context -- with
 * all six tests green.
 *
 * Returns lhci's FLAT config: convertRcFileToYargsOptions spreads
 * wizard/assert/collect/upload/server into one object, so it is `.target` and
 * `.outputDir`, not `.upload.target`.
 *
 * Note this imports @lhci/utils, which package.json declares alongside
 * @lhci/cli. If lhci is ever removed from the project (T41 debated exactly
 * that), this becomes MODULE_NOT_FOUND rather than a clear failure -- delete
 * this file in the same change. On the `src/` import path itself, see the
 * comment in findConfigFile() above.
 */
function resolvedUpload(): {target?: string; outputDir?: string} {
  const { loadAndParseRcFile } = require('@lhci/utils/src/lighthouserc.js');
  // Absolute path via findConfigFile(): the loader resolves `extends` relative
  // to the rc file, and a relative path silently yields an empty config
  // rather than throwing. findRcFile() already returns an absolute path when
  // given one (REPO_ROOT), so this stays absolute without hardcoding it.
  return loadAndParseRcFile(findConfigFile());
}

describe('lighthouserc.js keeps Lighthouse reports off the internet', () => {
  it('is still the config we think it is', () => {
    // Guards the guard: if the shape changes, every assertion below could pass
    // vacuously against undefined.
    const ci = config()?.ci;
    expect(ci, 'lighthouserc.js has no `ci` block').toBeTruthy();
    // `.length`, not the array: `[]` is truthy in JavaScript, so the original
    // check passed on the one condition its own message named.
    expect(ci.collect?.url?.length, 'lighthouserc.js collects no URLs').toBeTruthy();
    // An absent upload block is SAFE, not dangerous: autorun only uploads
    // guarded by its `if (ciConfiguration.upload)` check in
    // `@lhci/cli/src/autorun/autorun.js` (greppable, not a line number -- see
    // .gitleaks.toml's own rule against citations that go stale on a
    // dependency bump), and nothing defaults it. This pins the config's SHAPE
    // so the guard below has something to check -- it is not protection
    // against a missing default, which was how an earlier version of this
    // comment described it, wrongly.
    expect(ci.upload, 'lighthouserc.js has no `upload` block to check').toBeTruthy();
  });

  it('uploads nowhere but this machine', () => {
    // Resolved through lhci's OWN loader, not by reading `ci.upload.target`.
    // lhci merges four sibling keys and lets later ones win -- flattenRcToConfig
    // spreads `ci`, `lhci`, `ci:client` and `ci:server`, shallowly -- so a
    // sibling `lhci: { upload: { target: 'temporary-public-storage' } }`
    // replaces the upload block wholesale. Measured: lhci then resolves
    // `temporary-public-storage` while a guard reading `ci.upload.target`
    // reports all green. Asking the tool closes that whole class, including
    // `extends` and any key shape added later, for the same reason the
    // allowlist below beats a denylist: do not hardcode a model of the tool.
    const target = resolvedUpload().target;
    // An undefined target means there is no `upload` block at all, which is
    // SAFE (see the shape test above) -- autorun only uploads
    // `if (ciConfiguration.upload)`. Without this special case the generic
    // message below told whoever deleted that block their library was being
    // published, which is false and reads as a reason to edit the guard
    // rather than restore the block it anchors on. Say what actually
    // happened instead.
    const message =
      target === undefined
        ? `lighthouserc.js has no upload.target because the upload block is ` +
          `absent entirely -- that is SAFE (autorun does not upload without ` +
          `one), but this guard needs the block present as an anchor for the ` +
          `assertions above and below it. Restore the upload block rather ` +
          `than editing this guard.`
        : `lighthouserc.js sets upload.target='${target}'. Anything outside ` +
          `${JSON.stringify(LOCAL_ONLY_TARGETS)} sends a report containing full-page ` +
          `screenshots of the user's media library off this machine. ` +
          `'temporary-public-storage' publishes it to a PUBLIC Google endpoint and ` +
          `prints the URL, and autorun does it even when assertions fail.`;
    expect(LOCAL_ONLY_TARGETS, message).toContain(target);
  });

  it('says where the report goes when it stays local', () => {
    // Resolved, not raw: see resolvedUpload(). This assertion is about
    // behaviour, so it must read what lhci will actually use.
    const upload = resolvedUpload();
    // Via the allowlist, not a hardcoded 'filesystem': the moment a second
    // local-only target is added, hardcoding would silently stop checking
    // outputDir for it -- and outputDir is load-bearing. lhci resolves a
    // missing one against the CWD via `path.resolve(process.cwd(),
    // options.outputDir || '')` in `@lhci/cli/src/upload/upload.js` (greppable
    // symbol, not a line number that moves on the next `@lhci/cli` bump), so a
    // missing one dumps reports into the repository root, where neither
    // .gitignore's nor .dockerignore's `.lighthouseci/` entry reaches them.
    if (!LOCAL_ONLY_TARGETS.includes(upload.target as string)) return;
    expect(
      upload.outputDir,
      'upload.target is filesystem but no outputDir is set, so reports land ' +
        'wherever lhci defaults to and nobody knows to clean them up',
    ).toBeTruthy();

    // THE GIT ROUTE. Until this assertion existed, deleting `.lighthouseci/`
    // from .gitignore left the whole suite green: `outputDir` being truthy
    // says nothing about whether git ignores where it points. Of the three
    // escape routes this file guards, this is the only one whose disclosure
    // cannot be retracted -- the repository is public, so a routine
    // `git add -A` after a local Lighthouse run stages full-page screenshots
    // of the operator's media library into history, forks and caches, none of
    // which a later commit can undo. gitleaks will not catch it either,
    // because screenshots are not secrets by pattern.
    //
    // Resolved to an absolute path against REPO_ROOT the way lhci resolves it
    // (see the comment above), and checked with git itself via
    // `git check-ignore -q` rather than modelled by hand -- KNOWN LIMIT 3 at
    // the top of this file is what a hand-rolled ignore matcher costs, three
    // times over, against a real `docker build`. Asking git the same way asks
    // the only oracle that cannot disagree with itself.
    //
    // MEASURED, and load-bearing: `.gitignore`'s `.lighthouseci/` entry is a
    // directory-only pattern, and `git check-ignore` can only tell a
    // directory-only pattern applies to a path that either exists on disk as
    // a directory, or is spelled with a trailing slash in the argument. The
    // first run of this suite has never produced a report yet, so the
    // directory does not exist -- passing the bare path made this assertion
    // fail against a genuinely-correct .gitignore (a false red), which is the
    // exact failure mode this file's docstring warns teaches people to edit
    // the guard. A trailing slash makes the check correct regardless of
    // whether `.lighthouseci/` has been created by a prior run.
    // RETENTION, and the reason this is an assertion rather than the comment
    // it started as. `reportFilenamePattern` decides whether a run overwrites
    // the last one or writes beside it. The lhci DEFAULT includes
    // `%%DATETIME%%`, and `collect`'s own cleanup only unlinks
    // `lhr-<digits>.json`/`.html`, names the upload step never writes -- so
    // the default accumulates every report of every run forever, in a
    // directory this same change gitignored out of `git status`, on a home
    // server, with no `clean` target anywhere in the Makefile to empty it.
    // Restoring the timestamp reads like a harmless "keep the history"
    // convenience, which is exactly why a comment asking people not to is the
    // weaker half of a rule that can be executed instead.
    expect(
      upload.reportFilenamePattern ?? '%%DATETIME%%',
      'upload.reportFilenamePattern includes %%DATETIME%% (or is unset, which ' +
        'means lhci uses its datetime-stamped default). Every run then writes ' +
        'NEW files instead of overwriting, nothing ever deletes them, and the ' +
        'directory is gitignored so nobody sees it grow. Drop %%DATETIME%%, or ' +
        'add a cleanup mechanism and change this guard deliberately.',
    ).not.toContain('%%DATETIME%%');

    const resolvedOutputDir = path.resolve(REPO_ROOT, upload.outputDir as string) + '/';
    const result = spawnSync('git', ['check-ignore', '-q', resolvedOutputDir], {
      cwd: REPO_ROOT,
    });
    expect(
      result.status,
      `git does not ignore '${resolvedOutputDir}' (upload.outputDir=` +
        `'${upload.outputDir}'). A routine 'git add -A' after a local ` +
        `Lighthouse run would commit full-page screenshots of the operator's ` +
        `media library. Check .gitignore for a missing '.lighthouseci/' entry.`,
    ).toBe(0);
  });
});
