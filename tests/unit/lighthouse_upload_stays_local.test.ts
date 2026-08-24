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
 * KNOWN LIMIT: this reads the configuration, so it proves what `lhci` is told
 * to do. It does not intercept the network, so it cannot prove `@lhci/cli`
 * honours it. That is a deliberate scope choice -- the alternative is running
 * Lighthouse in the unit suite -- and it is recorded rather than implied.
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
  return require(path.join(REPO_ROOT, 'lighthouserc.js'));
}

describe('lighthouserc.js keeps Lighthouse reports off the internet', () => {
  it('is still the config we think it is', () => {
    // Guards the guard: if the shape changes, every assertion below could pass
    // vacuously against undefined.
    const ci = config()?.ci;
    expect(ci, 'lighthouserc.js has no `ci` block').toBeTruthy();
    expect(ci.collect?.url, 'lighthouserc.js collects no URLs').toBeTruthy();
    expect(ci.upload, 'lighthouserc.js has no `upload` block, so lhci uses its own default').toBeTruthy();
  });

  it('uploads nowhere but this machine', () => {
    const target = config().ci.upload.target;
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
    if (upload.target !== 'filesystem') return;
    expect(
      upload.outputDir,
      'upload.target is filesystem but no outputDir is set, so reports land ' +
        'wherever lhci defaults to and nobody knows to clean them up',
    ).toBeTruthy();
  });

  it('does not leave a comment claiming the opposite of what it does', () => {
    // The original config carried "Don't upload to Lighthouse CI server by
    // default" directly above a setting that uploaded to public storage. A
    // comment that contradicts its own code is worse than no comment: it is
    // what a reader checks instead of the value.
    const { readFileSync } = require('node:fs');
    const text: string = readFileSync(path.join(REPO_ROOT, 'lighthouserc.js'), 'utf8');
    const uploadBlock = text.slice(text.indexOf('upload:'));
    const target = config().ci.upload.target;
    if (!LOCAL_ONLY_TARGETS.includes(target)) return; // the value test already failed
    expect(
      /don'?t upload|no upload|never upload/i.test(uploadBlock) &&
        !/local|filesystem|this machine|disk/i.test(uploadBlock),
      'the upload block claims uploading is off without saying where reports ' +
        'actually go. Say what it does, not what it avoids.',
    ).toBe(false);
  });
});
