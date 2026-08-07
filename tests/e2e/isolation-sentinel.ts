/**
 * Rendezvous for AC-QA-50's isolation proof.
 *
 * Without a barrier the isolation-a-mutate / isolation-b-assert pair passes
 * for the wrong reason. Playwright hands one spec file to each worker and
 * runs them CONCURRENTLY, so at `--workers=2` isolation-b-assert routinely
 * reaches its "the leaked category is not visible" assertion before
 * isolation-a-mutate has created anything to leak. Nothing has been created
 * anywhere yet, so the assertion holds trivially -- a green that would
 * survive per-worker isolation being removed entirely, which is exactly the
 * incidentally-passing shape this pair exists to rule out.
 *
 * So the mutating spec publishes a sentinel once its category is confirmed
 * created, and the asserting spec refuses to assert until it has read one.
 *
 * The sentinel is keyed on `process.ppid`: every Playwright worker is forked
 * from the same runner process, so the two workers agree on the filename
 * within a run, while a leftover file from an EARLIER run (a different
 * runner pid) can never be mistaken for this one's. That matters more than
 * it looks -- a stale sentinel would put the barrier straight back where it
 * started, with isolation-b-assert satisfied by a mutation that never
 * happened this run.
 *
 * It records WHICH server mutated, too, so isolation-b-assert can tell the
 * two failure modes apart: a genuine leak, versus both specs landing on the
 * same worker (at `--workers=1` a worker's server persists across every file
 * it runs, so the mutation legitimately reaches the second spec and the pair
 * demonstrates nothing).
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

/**
 * Single definition, imported by both halves. It previously lived duplicated
 * in each spec because importing a `.spec.ts` executes its module body and
 * would re-register that file's own top-level `test()` call in the importer;
 * this module registers no tests, so it can be shared safely. It is also
 * excluded from every project's test matching by not being named `*.spec.ts`.
 */
export const ISOLATION_CATEGORY_NAME = 'AC-QA-50 Isolation Leak Probe';

export type IsolationSentinel = {
  /** Base URL of the server the category was actually created on. */
  baseURL: string;
  /** Playwright parallelIndex of the worker that created it. */
  parallelIndex: number;
};

const POLL_INTERVAL_MS = 250;

/**
 * How long isolation-b-assert waits for its partner. Generous because the
 * other worker has to start its own CouchPotato server, seed it, and drive a
 * settings form before it can publish. The isolation project raises its test
 * timeout above this in playwright.config.ts, so a missing partner surfaces
 * as the explanatory error below rather than a bare Playwright timeout.
 */
export const RENDEZVOUS_TIMEOUT_MS = 60_000;

function sentinelPath(outputDir: string): string {
  return path.join(outputDir, `isolation-mutated-${process.ppid}.json`);
}

/** Announce that the leak probe category now exists on `sentinel.baseURL`. */
export function publishMutation(outputDir: string, sentinel: IsolationSentinel): void {
  mkdirSync(outputDir, { recursive: true });
  const target = sentinelPath(outputDir);
  // Write-then-rename: the reader polls this path from another process, and
  // a half-written file that happened to parse as JSON would hand it a
  // baseURL of `undefined` rather than making it wait.
  const staging = `${target}.w${sentinel.parallelIndex}.tmp`;
  writeFileSync(staging, JSON.stringify(sentinel), 'utf-8');
  renameSync(staging, target);
}

/** Block until the mutating spec has published, or fail naming why not. */
export async function awaitMutation(outputDir: string): Promise<IsolationSentinel> {
  const target = sentinelPath(outputDir);
  const deadline = Date.now() + RENDEZVOUS_TIMEOUT_MS;

  while (Date.now() < deadline) {
    try {
      return JSON.parse(readFileSync(target, 'utf-8')) as IsolationSentinel;
    } catch {
      // Not published yet, or published but not yet renamed into place.
    }
    await sleep(POLL_INTERVAL_MS);
  }

  throw new Error(
    `isolation-a-mutate.spec.ts published nothing within ${RENDEZVOUS_TIMEOUT_MS}ms ` +
    `(expected ${target}). This spec is one half of a pair and proves nothing on ` +
    `its own -- asserting "no leaked category" before anything has been created ` +
    `passes whether isolation works or not. Run both halves, on at least two ` +
    `workers: \`npm run test:isolation\`.`,
  );
}
