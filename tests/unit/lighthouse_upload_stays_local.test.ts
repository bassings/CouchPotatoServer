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
 */
import { createRequire } from 'node:module';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const require = createRequire(import.meta.url);

/** Targets that write the report to this machine and send nothing anywhere. */
const LOCAL_ONLY_TARGETS = ['filesystem'];

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
  return require(path.join(REPO_ROOT, 'lighthouserc.js'));
}

/** What `lhci` itself will use, after merging every key shape it accepts. */
function resolvedTarget(): string | undefined {
  const { loadAndParseRcFile } = require('@lhci/utils/src/lighthouserc.js');
  // Absolute path: the loader resolves `extends` relative to the rc file, and
  // a relative path silently yields an empty config rather than throwing.
  return loadAndParseRcFile(path.join(REPO_ROOT, 'lighthouserc.js')).target;
}

function uploadBlockText(): string {
  const { readFileSync } = require('node:fs');
  const text: string = readFileSync(path.join(REPO_ROOT, 'lighthouserc.js'), 'utf8');
  return text.slice(text.indexOf('upload:'));
}

/** Only the `//` lines of the upload block: what a reader is TOLD, not what the
 *  code says. Scoping matters -- an assertion over the whole block cannot fail,
 *  because `target: 'filesystem'` and the `outputDir` key put those very words
 *  in it. That is how the first version of the comment guard here turned out to
 *  be `expect(false).toBe(false)`, and splitting it in two reproduced the same
 *  vacuity in the second half until this scoping was added. */
function uploadCommentText(): string {
  return uploadBlockText()
    .split('\n')
    .filter(line => line.trim().startsWith('//'))
    .join('\n');
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
    // `if (ciConfiguration.upload)` (@lhci/cli/src/autorun/autorun.js:143), and
    // nothing defaults it. This pins the config's SHAPE so the guard below has
    // something to check -- it is not protection against a missing default,
    // which was how an earlier version of this comment described it, wrongly.
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
    const target = resolvedTarget();
    expect(
      LOCAL_ONLY_TARGETS,
      `lighthouserc.js sets upload.target='${target}'. Anything outside ` +
        `${JSON.stringify(LOCAL_ONLY_TARGETS)} sends a report containing full-page ` +
        `screenshots of the user's media library off this machine. ` +
        `'temporary-public-storage' publishes it to a PUBLIC Google endpoint and ` +
        `prints the URL, and autorun does it even when assertions fail.`,
    ).toContain(target);
  });

  it('says where the report goes when it stays local', () => {
    const upload = config().ci.upload;
    // Via the allowlist, not a hardcoded 'filesystem': the moment a second
    // local-only target is added, hardcoding would silently stop checking
    // outputDir for it -- and outputDir is load-bearing. lhci resolves
    // `options.outputDir || ''` against the CWD (upload.js:535), so a missing
    // one dumps reports into the repository root, where .gitignore's
    // `.lighthouseci/` entry does not cover them.
    if (!LOCAL_ONLY_TARGETS.includes(upload.target)) return;
    expect(
      upload.outputDir,
      'upload.target is filesystem but no outputDir is set, so reports land ' +
        'wherever lhci defaults to and nobody knows to clean them up',
    ).toBeTruthy();
  });

  it('does not claim uploading is off, because it is not', () => {
    // The original config carried "Don't upload to Lighthouse CI server by
    // default" directly above a setting that uploaded to public storage. A
    // comment that contradicts its own code is worse than no comment: it is
    // what a reader checks instead of the value.
    //
    // The first version of THIS test could not catch that. It required the
    // block to claim no-upload AND to mention none of local/filesystem/disk --
    // but the target is written as a literal `'filesystem'` in that same block,
    // so the second half was always false and the whole assertion reduced to
    // `expect(false).toBe(false)`. Review proved it by pasting the original
    // misleading comment back above a correct target and watching it stay
    // green. Two separate claims, checked separately.
    const uploadBlock = uploadCommentText();
    expect(
      /don'?t upload|no upload|never upload|uploading is (off|disabled)/i.test(uploadBlock),
      'the upload block says uploading does not happen. It does happen -- ' +
        'reports are WRITTEN, just to this machine. Describe where they go, ' +
        'not what they avoid; a reader checks the comment instead of the value.',
    ).toBe(false);
  });

  it('cannot reach a docker image either', () => {
    // The third escape route, and the one this file's own comment denied.
    // `.gitignore` keeps reports out of the repository and `filesystem` keeps
    // them off the network -- but `Dockerfile:117` copies the whole build
    // CONTEXT, which is the filesystem rather than the git index. Review
    // measured reports inside a locally built image, with `coverage/` correctly
    // absent as a control, so it discriminates.
    //
    // Deliberately a text assertion on .dockerignore, and it is weaker than the
    // rest of this file: it checks the exclusion is DECLARED, not that docker
    // honours it, because building an image in the unit suite is out of
    // proportion. The mechanism that ends this class -- a check that no
    // gitignored artefact path survives into the build context -- is recorded
    // as T65, this being the fourth instance fixed by hand.
    const { readFileSync } = require('node:fs');
    const patterns = readFileSync(path.join(REPO_ROOT, '.dockerignore'), 'utf8')
      .split('\n')
      .map(line => line.trim())
      .filter(line => line && !line.startsWith('#'));
    expect(
      patterns,
      'the Lighthouse report directory is not excluded from the docker build ' +
        'context, so a local `docker build` bakes full-page screenshots of the ' +
        "operator's media library into the image. Add `.lighthouseci/` to " +
        '.dockerignore',
    ).toContain('.lighthouseci/');
  });

  it('tells the reader where reports actually go', () => {
    const comment = uploadCommentText();
    expect(
      comment.trim(),
      'the upload block has no explanatory comment at all. The value alone ' +
        'does not tell the next reader that this used to publish the library, ' +
        'or why it must not again',
    ).toBeTruthy();
    expect(
      /local|this machine|disk|written to/i.test(comment),
      'the upload comment never says where reports land, so nobody knows what ' +
        'to clean up or where to look. Note this checks the COMMENT, not the ' +
        'block: the code contains the word "filesystem" by construction, so an ' +
        'assertion over the whole block could not fail',
    ).toBe(true);
  });
});
