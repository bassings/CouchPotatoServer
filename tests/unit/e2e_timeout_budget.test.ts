/**
 * The E2E readiness budget must be spendable.
 *
 * Playwright applies the PROJECT timeout as the worker-fixture setup slot:
 *
 *   node_modules/playwright/lib/worker/workerProcessEntry.js
 *     this._fixtureRunner.workerFixtureTimeout = this._project.project.timeout;
 *
 * so a readiness budget larger than a project's timeout is not a longer
 * budget. It is a branch that project can never reach: the fixture is killed
 * at the project timeout, the fixture's own diagnostic never prints, and --
 * because a fixture timeout kills rather than raising -- its `catch` never
 * runs either, so the spawned server is orphaned and the data dir is left
 * behind to fail the NEXT run for an unrelated reason.
 *
 * That is what shipped: READY_TIMEOUT_MS was 60_000 against a global project
 * timeout of 30_000, and only the `isolation` project (which overrides to
 * 120_000) could reach it. It survived review because both numbers are
 * individually reasonable and neither file mentions the other.
 *
 * Reading the constants out of the source rather than importing them is
 * deliberate. fixtures.ts imports @playwright/test at module scope, which is
 * not loadable under vitest/jsdom, and playwright.config.ts's timeouts sit
 * inside a nested object literal. Parsing keeps this guard honest about what
 * it checks -- the shipped text -- and free of a test-only export that could
 * itself drift from the value the fixture uses.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const REPO_ROOT = path.resolve(__dirname, '..', '..');

function read(relative: string): string {
  return readFileSync(path.join(REPO_ROOT, relative), 'utf8');
}

/** Strip `_` digit separators so `25_000` and `25000` compare equal. */
function toNumber(literal: string): number {
  return Number(literal.replace(/_/g, ''));
}

function readyTimeoutMs(): number {
  const source = read('tests/e2e/fixtures.ts');
  const match = source.match(/^const READY_TIMEOUT_MS = ([0-9_]+)\s*;/m);
  expect(match, 'READY_TIMEOUT_MS declaration not found in tests/e2e/fixtures.ts').not.toBeNull();
  return toNumber(match![1]);
}

/**
 * Every timeout a project can be run under: the global default, plus each
 * per-project override. A project with no override inherits the global one,
 * so the global value must be in this list on its own account.
 */
function projectTimeouts(): number[] {
  // EVERY `timeout:` outside the `expect:` block, at any indentation, with or
  // without a trailing comment. The first version anchored on exact
  // indentation and a line ending in `,` -- so `timeout: 15_000, // firefox
  // boots slower` was invisible, and a 15s project timeout could sit below the
  // 25s readiness budget with this guard green. That is the precise defect the
  // file exists to prevent, and in a config where every line carries an
  // explanatory comment it is the likely spelling.
  //
  // `expect: { timeout: 5000 }` is excised first: it is the per-assertion
  // timeout, unrelated to worker-fixture setup, and including it would make
  // this guard demand a readiness budget under five seconds.
  const source = read('playwright.config.ts')
    // Comments first: this config explains every decision in prose, and the
    // word "timeout" appears in that prose far more often than in code.
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    .replace(/expect:\s*\{[^}]*\}/s, '');

  // The key may be quoted: `"timeout": 15000` is legal TS, and a spelling
  // invisible to BOTH the value regex and the key count below would slip
  // through unchecked -- the cross-check only helps if the two disagree.
  const all = [...source.matchAll(/^\s*["']?timeout["']?\s*:\s*([0-9_]+)\s*,?/gm)]
    .map((m) => toNumber(m[1]));
  expect(all.length, 'no `timeout:` found in playwright.config.ts').toBeGreaterThan(0);

  // Cross-check: every `timeout:` key in the code must have been READ, not
  // merely most of them. The regex above wants digits and underscores only,
  // so `timeout: 15e3`, `timeout : 15000` or a hex literal would be skipped
  // silently -- and a skipped timeout is one that can sit under the readiness
  // budget with this guard green, which is the entire failure this file
  // exists to prevent. Counting keys cannot make that mistake.
  const keys = [...source.matchAll(/["']?\btimeout\b["']?\s*:/g)].length;
  expect(
    all.length,
    `playwright.config.ts has ${keys} \`timeout:\` key(s) outside the expect ` +
    `block but only ${all.length} value(s) could be parsed: [${all.join(', ')}]. ` +
    `An unparsed timeout is unchecked, and this guard would stay green while ` +
    `a project timeout sat below the readiness budget.`,
  ).toBe(keys);

  return all;
}

describe('E2E readiness budget', () => {
  it('is smaller than every project timeout, so the fixture reports its own failure', () => {
    const ready = readyTimeoutMs();
    const timeouts = projectTimeouts();

    // Guard the guard: if the parsing silently stopped matching, this list
    // would be empty and the assertion below would vacuously pass.
    expect(timeouts.length).toBeGreaterThanOrEqual(2);

    for (const timeout of timeouts) {
      expect(
        ready,
        `READY_TIMEOUT_MS (${ready}ms) must be under every project timeout; ` +
        `found a project timeout of ${timeout}ms. Playwright kills the worker ` +
        `fixture at the project timeout, so a larger readiness budget is ` +
        `unreachable and orphans the spawned server.`,
      ).toBeLessThan(timeout);
    }
  });

  it('leaves headroom rather than sitting exactly on the smallest project timeout', () => {
    // Equality would satisfy nothing useful: the fixture and the harness
    // would race, and which error surfaces would be down to scheduling.
    const ready = readyTimeoutMs();
    const smallest = Math.min(...projectTimeouts());

    expect(smallest - ready).toBeGreaterThanOrEqual(5_000);
  });
});

/**
 * The "no save happened" E2E wait must outlive the debounce it is waiting out.
 *
 * `settings.spec.ts` proves a negative -- that focus-and-blur without typing
 * posts nothing -- which genuinely needs a bounded wait: there is no event to
 * await for something that must not occur. So it sleeps, and the sleep must be
 * longer than `debounceSave`'s timer or the assertion sees an empty array
 * because the POST has not fired YET.
 *
 * That is not hypothetical. The first version waited exactly 500ms against a
 * 500ms debounce and passed even when the focus handler was deliberately
 * mutated to save -- a guard that could not fail, for a claim whose falsehood
 * would destroy a credential on every visit to the settings page.
 *
 * Same shape as the budget above and recorded for the same reason: both
 * numbers are individually reasonable, and neither file mentions the other.
 * Whoever changes the debounce will not think to look at an E2E spec.
 */
describe('the settings debounce and the E2E wait that outlives it', () => {
  const scripts = readFileSync(
    path.join(REPO_ROOT, 'couchpotato/ui/templates/partials/settings/scripts.html'),
    'utf8',
  );
  const spec = readFileSync(
    path.join(REPO_ROOT, 'tests/e2e/settings.spec.ts'),
    'utf8',
  );

  const debounceMs = Number(
    /setTimeout\(\s*\(\)\s*=>\s*this\.saveSingle\([^)]*\)\s*,\s*(\d+)\s*\)/.exec(scripts)?.[1],
  );
  const waitMs = Number(
    /await page\.waitForTimeout\((\d+)\);/.exec(
      spec.slice(spec.indexOf('focus then blur WITHOUT typing saves nothing')),
    )?.[1],
  );

  it('finds both numbers, so this guard is not vacuous', () => {
    expect(debounceMs, 'debounceSave timer not found in scripts.html').toBeGreaterThan(0);
    expect(waitMs, 'waitForTimeout not found in the focus/blur test').toBeGreaterThan(0);
  });

  it('waits comfortably longer than the debounce', () => {
    expect(
      waitMs,
      `the E2E waits ${waitMs}ms for a save that must not happen, but ` +
        `debounceSave fires at ${debounceMs}ms. Anything less than a clear ` +
        `margin makes the test pass because the POST has not fired yet, not ` +
        `because it never will.`,
    ).toBeGreaterThanOrEqual(debounceMs * 2);
  });
});
