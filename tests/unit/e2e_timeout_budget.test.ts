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
  const source = read('playwright.config.ts').replace(/expect:\s*\{[^}]*\}/s, '');

  const all = [...source.matchAll(/^\s*timeout:\s*([0-9_]+)\s*,?/gm)].map((m) => toNumber(m[1]));
  expect(all.length, 'no `timeout:` found in playwright.config.ts').toBeGreaterThan(0);

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
