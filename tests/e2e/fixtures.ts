/**
 * Per-worker E2E isolation (T1.7).
 *
 * Playwright has no per-SPEC primitive, so this is per-WORKER: every
 * Playwright worker process gets its own CouchPotato server, on its own
 * port, against its own data dir -- seeded once at worker startup and
 * deleted at worker teardown. No spec run by one worker can observe another
 * worker's mutations, because there is no other worker's database to see.
 *
 * This replaces playwright.config.ts's old single shared `webServer` (one
 * server, port 5050, `.e2e-data`) and the `mode: 'serial'` escape hatches
 * that shared server needed on categories.spec.ts/profiles.spec.ts. Every
 * spec file now imports `test`/`expect` from HERE instead of
 * '@playwright/test' directly.
 *
 * Data-dir safety (AC-DATA-24/25/26) is NOT re-implemented here: this
 * shells out to scripts/e2e_worker_data.py's `prepare`/`cleanup` CLI, the
 * same way this file already shells out to scripts/seed_e2e_data.py and
 * CouchPotato.py itself -- one implementation of the safety rules, not a
 * second copy in JS that could quietly drift from the Python one.
 */
import { type ChildProcess, execFileSync, spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

import { test as base, expect } from '@playwright/test';

// Same interpreter-resolution order as playwright.config.ts used to apply
// to its single shared server -- see that file's history for why a bare
// `python` is never assumed.
const VENV_PYTHON = '.venv/bin/python';
const PYTHON = process.env.PYTHON || (existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3');

// Deliberately far from the app's own default (5050), so a stray dev
// instance a developer left running never collides with a worker's port.
const BASE_PORT = 5150;
const READY_TIMEOUT_MS = 60_000;
const POLL_INTERVAL_MS = 250;
// Playwright's own output directory: already gitignored, already cleaned per
// run, already where traces and failure screenshots go.
const LOG_DIR = 'test-results';

type WorkerServer = { baseURL: string };
type Exit = { code: number | null; signal: NodeJS.Signals | null };

function decode(chunk: unknown): string {
  return chunk instanceof Buffer ? chunk.toString('utf-8') : String(chunk);
}

/**
 * Poll `url` until it answers, or fail -- naming the actual cause.
 *
 * AC-QA-58: if the server process exits before it is ready, the failure
 * must say "the application under test exited" (and why), not leave every
 * downstream spec reporting a bare ERR_CONNECTION_REFUSED against a URL
 * that never had anything listening on it.
 */
async function waitForServer(getExit: () => Exit | null, url: string, getOutput: () => string): Promise<void> {
  const deadline = Date.now() + READY_TIMEOUT_MS;

  while (Date.now() < deadline) {
    const exited = getExit();
    if (exited) {
      const { code, signal } = exited;
      throw new Error(
        `the application under test exited before it became ready ` +
        `(exit code ${code}, signal ${signal}). Last output:\n${getOutput().slice(-4000)}`,
      );
    }
    try {
      const res = await fetch(url);
      // `res.ok` on the root only proves the port is bound. Measured
      // 2026-08-05: for roughly four seconds after that, the app answers
      // /partial/movies with 200 and an EMPTY grid while the seeded database
      // already holds active movies. Tests that start inside that window get
      // a fast, well-formed, wrong answer, and no client-side timeout can
      // help because the server has already replied.
      //
      // That window is what produced "no movie card in the Wanted grid",
      // intermittently, on whichever grid-dependent spec happened to run
      // first. So readiness means "serving library data", not "listening".
      if (res.ok) {
        const grid = await fetch(new URL('/partial/movies?status=active', url).href);
        if (grid.ok && (await grid.text()).includes('poster-card')) return;
      }
    } catch {
      // Not listening yet -- keep polling.
    }
    await sleep(POLL_INTERVAL_MS);
  }

  throw new Error(
    `server at ${url} did not become ready within ${READY_TIMEOUT_MS}ms. Last output:\n${getOutput().slice(-4000)}`,
  );
}

/** Stop `proc`, escalating to SIGKILL if it ignores SIGTERM. */
async function stopServer(proc: ChildProcess): Promise<void> {
  if (proc.exitCode !== null || proc.signalCode !== null) return;

  const exited = new Promise<void>((resolve) => proc.once('exit', () => resolve()));
  proc.kill('SIGTERM');

  const outcome = await Promise.race([
    exited.then(() => 'exited' as const),
    sleep(5000).then(() => 'timeout' as const),
  ]);
  if (outcome === 'timeout') {
    proc.kill('SIGKILL');
    await exited;
  }
}

export const test = base.extend<{}, { workerServer: WorkerServer }>({
  workerServer: [async ({}, use, workerInfo) => {
    // parallelIndex (not workerIndex): bounded to the actual concurrency
    // level (0..workers-1) and STABLE across a worker restart after a
    // crash, so a retried worker reserves the SAME data dir its crashed
    // predecessor had -- which is exactly the case cleanup-on-failure
    // below exists for.
    const idx = workerInfo.parallelIndex;
    const port = BASE_PORT + idx;
    const baseURL = `http://localhost:${port}`;

    let dataDir: string;
    try {
      dataDir = execFileSync(
        PYTHON, ['scripts/e2e_worker_data.py', 'prepare', String(idx)],
        { encoding: 'utf-8' },
      ).trim();
    } catch (err: unknown) {
      const stderr = (err as { stderr?: Buffer | string })?.stderr;
      throw new Error(`worker ${idx}: could not reserve a data dir -- ${stderr ? decode(stderr) : err}`);
    }

    let proc: ChildProcess | undefined;
    let output = '';
    let exited: Exit | null = null;
    try {
      // Seed BEFORE the server starts -- a failed/half-complete seed must
      // fail the worker, never start a server against an empty database
      // (same ordering and the same "no || true" contract
      // scripts/seed_e2e_data.py's own docstring establishes).
      execFileSync(PYTHON, ['scripts/seed_e2e_data.py', `--data_dir=${dataDir}`], { stdio: 'pipe' });

      proc = spawn(PYTHON, ['CouchPotato.py', `--data_dir=${dataDir}`, `--port=${port}`], {
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      proc.stdout?.on('data', (d) => { output += decode(d); });
      proc.stderr?.on('data', (d) => { output += decode(d); });
      // Persistent, not once-during-startup: a server that dies mid-run is
      // the case with no diagnosis at all today. Every subsequent spec on
      // this worker just reports ECONNREFUSED against a URL that used to
      // work, and the traceback explaining why went to a pipe nobody read.
      proc.on('exit', (code, signal) => { exited = { code, signal }; });

      await waitForServer(() => exited, `${baseURL}/`, () => output);
    } catch (err) {
      if (proc) await stopServer(proc);
      // Best-effort: a worker that failed to start still frees its data
      // dir, so a Playwright retry of this same worker slot (AC-QA-56's
      // `retries: 2`) does not immediately fail a SECOND time on
      // AC-DATA-26's "already exists" check for a reason unrelated to
      // whatever actually broke.
      try {
        execFileSync(PYTHON, ['scripts/e2e_worker_data.py', 'cleanup', String(idx)], { stdio: 'pipe' });
      } catch {
        // Cleanup failing here must not mask the original error.
      }
      throw err;
    }

    await use({ baseURL });

    // Read BEFORE stopServer, which kills the process and would otherwise
    // set this itself -- an orderly shutdown must not be reported as a crash.
    const crashed = exited;

    // Always persist the app log. Until now it lived only in a closure and
    // was dropped on the floor at teardown, so the one artefact that could
    // explain a mid-run failure was the one thing the run never kept.
    // test-results/ is Playwright's own output dir, already gitignored and
    // already where traces and screenshots land.
    let logPath = '';
    try {
      mkdirSync(LOG_DIR, { recursive: true });
      logPath = path.join(LOG_DIR, `server-w${idx}.log`);
      writeFileSync(logPath, output, 'utf-8');
    } catch {
      // Never fail teardown over a log file.
    }

    await stopServer(proc);
    execFileSync(PYTHON, ['scripts/e2e_worker_data.py', 'cleanup', String(idx)], { stdio: 'pipe' });

    // Raised last, so the data dir is released either way -- but raised, not
    // logged: a suite that goes green while the application under test died
    // half way through is reporting on tests that never ran against it.
    if (crashed) {
      throw new Error(
        `worker ${idx}: the application under test exited mid-run ` +
        `(exit code ${crashed.code}, signal ${crashed.signal}). ` +
        `Any spec that ran after that point failed against a dead server. ` +
        `Full application log: ${logPath || '(could not be written)'}\n` +
        `Last output:\n${output.slice(-4000)}`,
      );
    }
  }, { scope: 'worker', auto: true }],

  baseURL: async ({ workerServer }, use) => {
    await use(workerServer.baseURL);
  },
});

export { expect };
