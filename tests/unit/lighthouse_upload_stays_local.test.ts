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
 * this file in the same change.
 */
function resolvedUpload(): {target?: string; outputDir?: string} {
  const { loadAndParseRcFile } = require('@lhci/utils/src/lighthouserc.js');
  // Absolute path: the loader resolves `extends` relative to the rc file, and
  // a relative path silently yields an empty config rather than throwing.
  return loadAndParseRcFile(path.join(REPO_ROOT, 'lighthouserc.js'));
}

/** Docker's ignore semantics, not a string search: last matching pattern wins,
 *  and `!` re-includes.
 *
 *  This is a SUBSET of docker's matcher, and the important property is that it
 *  KNOWS where the subset ends. An earlier version claimed to be a subset while
 *  answering confidently outside it, which is worse than either being complete
 *  or refusing. Review measured six disagreements with a real `docker build`,
 *  from one root cause -- an unmodelled leading `/` and an unmodelled `**` --
 *  and the direction that matters is the negation one: a pattern this could not
 *  parse simply failed to match, leaving `excluded` at its previous value, so
 *  an unrecognised `!` re-include read as "nothing re-included". A FALSE GREEN,
 *  in precisely the case the guard's own failure message promises to catch.
 *  `!/.lighthouseci/` is not exotic; it is how someone would re-include reports
 *  for a perf job.
 *
 *  So: leading `/` is handled, `**` is handled in every position, and anything
 *  still outside the subset THROWS rather than guessing. Extend it or use T65,
 *  but do not let it answer quietly. */
function isExcludedFromDockerContext(relPath: string): boolean {
  const { readFileSync } = require('node:fs');
  const patterns: string[] = readFileSync(path.join(REPO_ROOT, '.dockerignore'), 'utf8')
    .split('\n')
    .map((line: string) => line.trim())
    .filter((line: string) => line && !line.startsWith('#'));

  const escape = (segment: string) =>
    segment
      .replace(/[.+^${}()|[\]\\]/g, '\\$&')
      .replace(/\*/g, '[^/]*')
      .replace(/\?/g, '[^/]');

  const STAR2 = '@@DOUBLESTAR@@';

  const matches = (pattern: string) => {
    if (pattern.includes('[')) {
      throw new Error(
        '.dockerignore pattern ' + JSON.stringify(pattern) + ' uses a ' +
          'character class, which this matcher does not model. Extend it, or ' +
          'move this check to the general mechanism recorded as T65 -- do not ' +
          'let it answer outside its subset.',
      );
    }
    // A leading `/` anchors to the context root, which this regex already is.
    const cleaned = pattern.replace(/^\/+/, '').replace(/\/+$/, '');
    if (cleaned === '') return true;

    const source = cleaned
      .split('/')
      .map(segment => (segment === '**' ? STAR2 : escape(segment)))
      .join('/')
      // `**/x` -> optional leading dirs; `x/**` -> everything beneath; bare `**`
      .split(STAR2 + '/').join('(?:.*/)?')
      .split('/' + STAR2).join('(?:/.*)?')
      .split(STAR2).join('.*');

    // A directory entry also excludes everything beneath it.
    return new RegExp('^' + source + '(?:/.*)?$').test(relPath);
  };

  let excluded = false;
  for (const raw of patterns) {
    const negated = raw.startsWith('!');
    if (matches(negated ? raw.slice(1) : raw)) excluded = !negated;
  }
  return excluded;
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
    const target = resolvedUpload().target;
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
    // Resolved, not raw: see resolvedUpload(). This assertion is about
    // behaviour, so it must read what lhci will actually use.
    const upload = resolvedUpload();
    // Via the allowlist, not a hardcoded 'filesystem': the moment a second
    // local-only target is added, hardcoding would silently stop checking
    // outputDir for it -- and outputDir is load-bearing. lhci resolves
    // `options.outputDir || ''` against the CWD (upload.js:535), so a missing
    // one dumps reports into the repository root, where neither .gitignore's
    // nor .dockerignore's `.lighthouseci/` entry reaches them.
    if (!LOCAL_ONLY_TARGETS.includes(upload.target as string)) return;
    expect(
      upload.outputDir,
      'upload.target is filesystem but no outputDir is set, so reports land ' +
        'wherever lhci defaults to and nobody knows to clean them up',
    ).toBeTruthy();
  });

  it('cannot reach a docker image either', () => {
    // The third escape route, and one an earlier comment in this file denied.
    // `.gitignore` keeps reports out of the repository and `filesystem` keeps
    // them off the network -- but `Dockerfile:117` copies the whole build
    // CONTEXT, which is the filesystem rather than the git index. Review
    // measured reports inside a locally built image, with `coverage/`
    // correctly absent as a control, so the measurement discriminates.
    //
    // This EVALUATES .dockerignore rather than searching it for a string. The
    // string version was wrong in BOTH directions, each proved with a real
    // docker build: a later `!.lighthouseci/` negation left the reports in the
    // image while the guard passed, and the equally valid spellings
    // `.lighthouseci` and `**/.lighthouseci` failed the guard while docker
    // excluded them correctly. The false red matters as much as the false
    // green -- a guard that reddens on a working config teaches people to edit
    // the guard, which is how the vacuous assertions this file has already
    // shed came to be written.
    expect(
      isExcludedFromDockerContext('.lighthouseci/report.html'),
      'a Lighthouse report is NOT excluded from the docker build context, so ' +
        'a local `docker build` bakes full-page screenshots of the media ' +
        'library into the image. Check .dockerignore for a missing ' +
        '`.lighthouseci/` entry, or a later `!` negation that re-includes it',
    ).toBe(true);
  });
});
