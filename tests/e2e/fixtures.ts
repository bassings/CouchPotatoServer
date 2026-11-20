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

import { type Page, type Route, test as base, expect } from '@playwright/test';

import { assertE2EPortAvailable, resolveE2EPort } from './port';
import {
  allowsSettingsPersistence,
  baselineGroupRows,
  changedSettings,
  COMBINE_WRITER_ANNOTATION,
  combineColumns,
  serializeSettingValue,
  SETTINGS_PERSISTENCE_ANNOTATION,
  SETTINGS_WRITE_ROUTES,
  splitGroupWrites,
} from './settings_persistence';

// Same interpreter-resolution order as playwright.config.ts used to apply
// to its single shared server -- see that file's history for why a bare
// `python` is never assumed.
const VENV_PYTHON = '.venv/bin/python';
const PYTHON = process.env.PYTHON || (existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3');

// MUST stay below the smallest project timeout in playwright.config.ts.
// Playwright applies the PROJECT timeout as the worker-fixture setup slot
// (`workerFixtureTimeout = this._project.project.timeout`), so a readiness
// budget above it is not a longer budget -- it is an unreachable branch.
// At 60_000 against a 30_000 project timeout, three of the four projects
// killed the fixture at 30s and the AC-QA-58 diagnostic below (which names
// the URL and prints the server's last output) could only ever print in the
// `isolation` project, which overrides the timeout to 120s. Everywhere else
// the developer got a bare `Fixture "workerServer" timeout ... during setup`
// with no server output -- the exact experience this fixture was written to
// eliminate -- and, because the timeout kills the fixture rather than
// raising into it, the `catch` below never ran: no log persisted, no
// stopServer, no data-dir cleanup, and a live CouchPotato.py left on the
// port to poison the next run.
//
// So this is not a budget cut. The effective budget was 30s already; this
// makes the remaining 25s spendable and the failure legible.
//
// The 5s the subtraction leaves is for everything BEFORE the poll loop:
// `e2e_worker_data.py prepare`, the synchronous `seed_e2e_data.py` (a Python
// interpreter start plus couchpotato imports), and `spawn`. That was
// arithmetic when first written; measured since, on this machine:
//
//     prepare  0.07s
//     seed     0.71s
//     total    0.78s   against 5s of headroom
//
// Roughly 6x margin, so a CI runner several times slower than this one still
// fits. If that ever stops being true the symptom is the OLD one -- a bare
// `Fixture "workerServer" timeout ... during setup` with no server output --
// so re-measure here before assuming the app is at fault.
// tests/unit/e2e_timeout_budget.test.ts pins the ordering so the two
// numbers cannot drift apart again.
const READY_TIMEOUT_MS = 25_000;
const POLL_INTERVAL_MS = 250;
// Playwright's own output directory: already gitignored, already cleaned per
// run, already where traces and failure screenshots go.
const LOG_DIR = 'test-results';

// Kept in step with scripts/seed_e2e_data.py's MOVIE_ID and with
// release_controls.spec.ts's SEEDED_MOVIE_ID. Deliberately duplicated rather
// than imported: this file must not import a .spec.ts (that re-registers its
// tests) and the seed script is Python.
const SEEDED_MOVIE_ID = 'e2e-seed-movie-001';

/**
 * `configPath` is the worker's real `config.ini`, for a test that asserts on the FILE
 * (through tests/e2e/helpers.ts' `configSha`, `configColumns` and `configView`) rather
 * than on a request body or the page's own state.
 */
type WorkerServer = { baseURL: string; apiBase: string; configPath: string };
type Exit = { code: number | null; signal: NodeJS.Signals | null };

async function loadSettingsSnapshot(
  url: string,
  stage: 'baseline' | 'after' | 'restored',
): Promise<{ values: Record<string, Record<string, unknown>> }> {
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error('HTTP failure');
    const payload = await response.json();
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)
      || payload.success === false || !payload.values
      || typeof payload.values !== 'object' || Array.isArray(payload.values)
      || Object.values(payload.values).some(
        (section) => !section || typeof section !== 'object' || Array.isArray(section),
      )) {
      throw new Error('Invalid settings payload');
    }
    return payload;
  } catch {
    // Fetch and JSON errors can include the API key, URL, or setting values.
    throw new Error(`Could not load valid E2E settings ${stage} snapshot`);
  }
}

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
        if (!grid.ok || !(await grid.text()).includes('poster-card')) {
          await sleep(POLL_INTERVAL_MS);
          continue;
        }
        // The movie-detail route pays its own cold start, and readiness that
        // only covers the grid leaves the first spec to touch /movie/<id> to
        // absorb it. Measured on the gate: release_controls.spec.ts skipped
        // one test in 1 of 3 otherwise-identical runs, waiting 15s for the
        // htmx swap to bring in #movie-releases -- a different test dropped
        // each time, with the gate reporting green. Warming it here means
        // the wait is paid once, by the harness, before any spec starts.
        const detail = await fetch(new URL(`/partial/movie/${SEEDED_MOVIE_ID}`, url).href);
        if (detail.ok && (await detail.text()).includes('movie-releases')) return;
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

/**
 * Persist a worker's captured server output, and return where it went.
 *
 * Keyed on BOTH indices. `parallelIndex` is deliberately stable across a
 * worker restart (that is why the data dir uses it), and `retries: 2` is on
 * in CI -- so keying the filename on it alone meant the retry worker's
 * teardown overwrote the log of the attempt that actually failed, on the one
 * path where the log matters. `workerIndex` increments on every restart.
 *
 * Never throws: a missing log must not turn into the reported failure.
 */
function writeServerLog(parallelIndex: number, workerIndex: number, output: string): string {
  try {
    mkdirSync(LOG_DIR, { recursive: true });
    const target = path.join(LOG_DIR, `server-p${parallelIndex}-w${workerIndex}.log`);
    writeFileSync(target, output, 'utf-8');
    return target;
  } catch {
    return '';
  }
}

/** Stop `proc`, escalating to SIGKILL if it ignores SIGTERM. */
/**
 * Servers this worker has spawned and not yet reaped.
 *
 * The ordinary paths (`catch` on a startup failure, teardown after `use`)
 * both call stopServer, so this set is normally empty by the time the worker
 * exits. This covers the worker being SIGNALLED instead -- it still runs its
 * exit handlers, and without this the spawned CouchPotato.py is reparented to
 * init, keeps port 5150 bound, and makes every later run fail on AC-DATA-26's
 * "already exists" check for a reason unrelated to whatever actually broke.
 *
 * What it does NOT cover, measured rather than assumed: killing the Playwright
 * RUNNER. `pkill -f "playwright test"` matches the runner, not its worker
 * processes, so this handler never receives a signal and the server survives.
 * Reproduced twice while working on this file -- both times the orphan then
 * poisoned the next two gate runs with "already exists", and the second time
 * it cost a wrong diagnosis before the stale run announced itself.
 *
 * Fixing that properly means the child dying with its parent, which POSIX
 * gives no portable way to do. Not attempted here: the reachable path this
 * was written for is a fixture timeout, and that one is now handled at the
 * source by keeping READY_TIMEOUT_MS under the project timeout, so the
 * fixture raises into its own `catch` and cleans up normally.
 *
 * Registering SIGINT/SIGTERM listeners normally SUPPRESSES Node's default
 * terminate, which would be a real change to local Ctrl-C behaviour. It is not
 * one here: Playwright's own worker already registers empty handlers for both
 * (`node_modules/playwright/lib/common/index.js:1977-1980`, verified), so the
 * default action is suppressed with or without this block and the runner is
 * what actually ends the worker. Checked rather than assumed, because "my
 * handler changed how Ctrl-C behaves" would be a poor thing to discover from
 * a developer rather than from the source.
 *
 * Synchronous and best-effort by necessity: an `exit` handler cannot await.
 * SIGKILL rather than SIGTERM for the same reason -- there is no time left
 * to wait for a graceful shutdown, and this only ever runs when the worker
 * is already going away.
 */
const liveServers = new Set<ChildProcess>();

for (const signal of ['exit', 'SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    for (const proc of liveServers) {
      // The liveness check is the point, not `proc.pid` being truthy. A
      // server that crashed on its own is never removed from this set --
      // `proc.on('exit')` only records it, and stopServer is what deletes,
      // which for a mid-run crash may not run for minutes. `proc.pid` stays
      // truthy after the child is reaped, so SIGKILL would then go to
      // whatever the OS has since given that number. On a self-hosted
      // developer's machine that is plausibly one of their own processes,
      // and the catch below would swallow it silently. stopServer already
      // uses exactly this test one function down.
      if (proc.exitCode !== null || proc.signalCode !== null) continue;
      try {
        if (proc.pid) process.kill(proc.pid, 'SIGKILL');
      } catch {
        // Already gone, or not ours any more. Nothing useful to do here.
      }
    }
    liveServers.clear();
  });
}

async function stopServer(proc: ChildProcess): Promise<void> {
  liveServers.delete(proc);
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

/**
 * The seedConfig values combine-group writers have used in this worker process. The
 * static check (tests/unit/e2e_seed_config_ownership.test.ts) cannot see through a helper
 * in another file, a bare annotation or a looped constant, so this is the guard for those:
 * a writer on the shared server, or on a value another writer already used, fails.
 */
const writerSeeds = new Set<string>();

function assertWriterOwnsItsSeed(annotations: readonly { type: string }[], seedConfig: string | undefined) {
  if (!annotations.some(({ type }) => type === COMBINE_WRITER_ANNOTATION)) return;
  if (!seedConfig) {
    throw new Error('A combine-group writer must run on its own seedConfig server, not the shared one.');
  }
  if (writerSeeds.has(seedConfig)) {
    throw new Error(`seedConfig ${JSON.stringify(seedConfig)} is already owned by another combine-group writer; give this test its own value.`);
  }
  writerSeeds.add(seedConfig);
}

/**
 * Fail a test that ends with a combine-group save pending on the Settings page, unless it is a
 * declared writer (it owns its server, and the changes are restored). Read from the panel's own
 * state, because the request itself is invisible (see the call site). Names the section only.
 * A page that is gone or is not the Settings page has nothing pending.
 */
async function assertNoPendingGroupSave(page: Page, annotations: Annotations) {
  if (annotations.some(({ type }) => type === COMBINE_WRITER_ANNOTATION)) return;
  const pending = await page.evaluate(() => {
    const root = document.querySelector('[x-data="settingsPanel()"]');
    const alpine = (window as any).Alpine;
    if (!root || !alpine) return [];
    const groups = alpine.$data(root).groupState || {};
    return Object.entries(groups)
      .filter(([, group]: [string, any]) => group.timer || group.queued)
      .map(([section]) => section);
  }).catch(() => [] as string[]); // closed or navigating: no page, nothing pending
  if (pending.length > 0) {
    throw new Error(
      `This test ended with a combine-group save still pending (${pending.join(', ')}). The Settings page `
      + 'sends it as the page closes, by a request no route can intercept, so it would write the real server. '
      + 'Let the save go out inside the test (advance the page clock past the debounce, then wait for the '
      + 'mocked or real response), or take the change back, or make the test a combineGroupWriter() on its own seedConfig.',
    );
  }
}

type Tally = { blocked: number; sharedGroupSaves: number };
type Annotations = readonly { type: string }[];
type Snapshot = Awaited<ReturnType<typeof loadSettingsSnapshot>>;
type Change = { section: string; name: string };

/**
 * The page's route for every settings write. A group save on the worker's SHARED server is
 * never allowed, whatever the test declares (it would change rows every later test on that
 * server starts from); any other write needs the persistence annotation.
 */
function guardRoute(tally: Tally, onSharedServer: boolean, annotations: Annotations) {
  const refuse = (route: Route, error: string) => route.fulfill({
    status: 409, contentType: 'application/json', body: JSON.stringify({ success: false, error }),
  });
  return async (route: Route) => {
    if (onSharedServer && route.request().url().includes('settings.save_group')) {
      tally.sharedGroupSaves += 1;
      await refuse(route, 'E2E group saves need the test\'s own seedConfig server');
    } else if (allowsSettingsPersistence(annotations)) {
      await route.continue();
    } else {
      // The request URL contains the API key and may contain setting values.
      tally.blocked += 1;
      await refuse(route, `E2E test did not declare ${SETTINGS_PERSISTENCE_ANNOTATION}`);
    }
  };
}

/** Fail if any combine group changed on the shared server, by whatever channel. Names no value. */
function assertNoSharedGroupChange(before: Snapshot, changed: Change[]) {
  const { groups } = splitGroupWrites(before, changed);
  if (groups.length > 0) {
    throw new Error(
      `A combine group changed on the worker's shared server (${groups.join(', ')}): `
      + 'a group save must run on the test\'s own server. Seed the test with test.use({ seedConfig }).',
    );
  }
}

/**
 * Put changed settings back and verify. A combine group is restored by ONE group save of its
 * baseline rows, never per column (a per-column restore leaves a group half-restored when one
 * request fails, and the per-column route refuses these columns from SEC-004 P6). A group the
 * save cannot reproduce (misaligned, or a column shorter than the row count) is neither
 * restored nor verified: safe only because a writer owns its server (AC-QA-10).
 */
async function restoreAndVerify(apiBase: string, settingsURL: string, before: Snapshot, changed: Change[]) {
  const { groups, perColumn } = splitGroupWrites(before, changed);
  const failures = new Set<string>();
  const restorable = groups.filter((section) => baselineGroupRows(before, section) !== null);
  for (const section of restorable) {
    if (!await restoreGroup(apiBase, section, baselineGroupRows(before, section))) failures.add(`${section} (group)`);
  }
  for (const { section, name } of perColumn) {
    if (!await restoreColumn(apiBase, section, name, before?.values?.[section]?.[name])) failures.add(`${section}.${name}`);
  }
  const columns = combineColumns(before);
  const skipped = new Set(groups
    .filter((section) => !restorable.includes(section))
    .flatMap((section) => columns[section].map((name) => `${section}.${name}`)));
  const verified = changed.filter(({ section, name }) => !skipped.has(`${section}.${name}`));
  const verificationFailed = verified.length > 0
    && await verifyRestored(settingsURL, before, verified, skipped, failures);
  if (failures.size > 0) {
    throw new Error(
      `E2E setting restoration failed or could not safely restore: ${[...failures].join(', ')}`
      + (verificationFailed ? '; snapshot verification failed' : ''),
    );
  }
}

/** Re-read and add anything still different to `failures`. True when the re-read itself failed. */
async function verifyRestored(settingsURL: string, before: Snapshot, verified: Change[], skipped: Set<string>, failures: Set<string>) {
  try {
    const restored = await loadSettingsSnapshot(settingsURL, 'restored');
    for (const { section, name } of changedSettings(before, restored)) {
      if (!skipped.has(`${section}.${name}`)) failures.add(`${section}.${name}`);
    }
    return false;
  } catch {
    for (const { section, name } of verified) failures.add(`${section}.${name}`);
    return true;
  }
}

/** The checks that fail the test itself, after everything is restored. */
function assertTeardownAudit(tally: Tally, changed: Change[], annotations: Annotations, seedConfig: string | undefined) {
  if (tally.sharedGroupSaves > 0) {
    throw new Error(
      `This test sent ${tally.sharedGroupSaves} settings.save_group request(s) to the worker's shared server, `
      + 'which is refused whatever the test declares. Seed the test onto its own server with '
      + 'test.use({ seedConfig }).',
    );
  }
  assertWriterOwnsItsSeed(annotations, seedConfig);
  if (tally.blocked > 0 || (changed.length > 0 && !allowsSettingsPersistence(annotations))) {
    throw new Error(
      `This test sent ${Math.max(tally.blocked, changed.length)} unmocked settings.save request(s) `
      + `(settings.save or settings.save_group), which would `
      + `persist into the worker database and leak into later tests. Mock settings.save, `
      + `or explicitly annotate an intentional persistence test with `
      + `{ type: '${SETTINGS_PERSISTENCE_ANNOTATION}' }.`,
    );
  }
}

/** Put one combine group back with one group save. False on any failure. */
async function restoreGroup(apiBase: string, section: string, rows: unknown): Promise<boolean> {
  try {
    const response = await fetch(`${apiBase}/settings.save_group/`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ section, rows }),
    });
    const payload = await response.json().catch(() => null);
    return response.ok && payload?.success !== false;
  } catch {
    return false;
  }
}

/** Put one setting back by its own save. False on any failure, or a masked baseline. */
async function restoreColumn(apiBase: string, section: string, name: string, value: unknown): Promise<boolean> {
  if (typeof value === 'string' && /^\*+$/.test(value)) return false;
  try {
    const body = new URLSearchParams({ section, name, value: serializeSettingValue(value) });
    const response = await fetch(`${apiBase}/settings.save/`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body,
    });
    const payload = await response.json().catch(() => null);
    return response.ok && payload?.success !== false;
  } catch {
    return false;
  }
}

/**
 * One CouchPotato server on its own port and data dir, for as long as `use` runs.
 *
 * The worker's own server is one of these, and so is the dedicated server a test gets
 * when it names a `seedConfig`: one lifecycle, so a startup failure, a mid-run crash and
 * a data-dir cleanup are handled once. `index` selects the port (BASE_PORT + index) and
 * the data dir (`e2e_worker_data.py`'s `.e2e-w<index>-data`).
 */
type ServeOptions = { index: number; workerIndex: number; seedConfig: string };

const serverLifecycle = {
  async serve({ index: idx, workerIndex, seedConfig }: ServeOptions, use: (server: WorkerServer) => Promise<void>) {
    // The worker's index is parallelIndex (not workerIndex): bounded to the actual
    // concurrency level (0..workers-1) and STABLE across a worker restart after a
    // crash, so a retried worker reserves the SAME data dir its crashed
    // predecessor had -- which is exactly the case cleanup-on-failure
    // below exists for.
    const port = resolveE2EPort(process.env.BASE_PORT, idx);
    const baseURL = `http://localhost:${port}`;

    await assertE2EPortAvailable(port, `worker ${idx}`);

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
      const seedArgs = ['scripts/seed_e2e_data.py', `--data_dir=${dataDir}`];
      if (seedConfig) seedArgs.push(`--config-fixture=${seedConfig}`);
      execFileSync(PYTHON, seedArgs, { stdio: 'pipe' });

      // --console_log is load-bearing, not noise. runner.py computes
      // `console = (debug or options.console_log) and not quiet and not
      // daemon`, so without it NO console handler is attached and every
      // log.error -- including the one naming a failed startup -- goes only
      // to <data_dir>/logs/CouchPotato.log, which the catch block below then
      // deletes. Measured: the captured output was empty for exactly the
      // failure the capture exists to explain. With it, PrivacyFilter is in
      // the chain (couchpotato/core/logger.py), so the api_key is redacted.
      proc = spawn(PYTHON, ['CouchPotato.py', `--data_dir=${dataDir}`, `--port=${port}`, '--console_log'], {
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      liveServers.add(proc);
      proc.stdout?.on('data', (d) => { output += decode(d); });
      proc.stderr?.on('data', (d) => { output += decode(d); });
      // Persistent, not once-during-startup: a server that dies mid-run is
      // the case with no diagnosis at all today. Every subsequent spec on
      // this worker just reports ECONNREFUSED against a URL that used to
      // work, and the traceback explaining why went to a pipe nobody read.
      proc.on('exit', (code, signal) => { exited = { code, signal }; });

      await waitForServer(() => exited, `${baseURL}/`, () => output);

      const rootMarkup = await fetch(`${baseURL}/`).then((response) => response.text());
      const apiBaseMatch = rootMarkup.match(/apiBase:\s*'([^']+)'/);
      if (!apiBaseMatch) {
        throw new Error(`worker ${idx}: rendered root did not expose CP.apiBase`);
      }
      await use({
        baseURL,
        apiBase: new URL(apiBaseMatch[1], baseURL).toString().replace(/\/$/, ''),
        configPath: path.resolve(dataDir, 'config.ini'),
      });
    } catch (err) {
      try {
        if (proc) await stopServer(proc);
      } catch {
        // Still save the log and release the data dir; preserve the original diagnostic.
      }
      // Persist BEFORE the cleanup below removes the data dir. The startup
      // path is the one the fixture can spend 60 seconds in, and it was the
      // one path that kept nothing.
      writeServerLog(idx, workerIndex, output);
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

    // Read BEFORE stopServer, which kills the process and would otherwise
    // set this itself -- an orderly shutdown must not be reported as a crash.
    const crashed = exited;

    // Always persist the app log. Until now it lived only in a closure and
    // was dropped on the floor at teardown, so the one artefact that could
    // explain a mid-run failure was the one thing the run never kept.
    // test-results/ is Playwright's own output dir, already gitignored and
    // already where traces and screenshots land.
    const logPath = writeServerLog(idx, workerIndex, output);

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
  },
};

/**
 * A dedicated server for a test that names a `seedConfig` starts at BASE_PORT + this
 * + the worker's parallelIndex, with the data dir of the same index, so it can never
 * collide with a worker's own server (BASE_PORT + parallelIndex) inside 5150-5200.
 */
const SEEDED_SERVER_INDEX_BASE = 20;

type TestOptions = { seedConfig: string; testServer: WorkerServer };

export const test = base.extend<{ settingsPersistenceGuard: void } & TestOptions, { workerServer: WorkerServer }>({
  workerServer: [async ({}, use, workerInfo) => {
    await serverLifecycle.serve(
      { index: workerInfo.parallelIndex, workerIndex: workerInfo.workerIndex, seedConfig: '' },
      use,
    );
  }, { scope: 'worker', auto: true }],

  // The named starting configuration (scripts/seed_e2e_data.py `--config-fixture`) this
  // test's server is seeded with BEFORE it starts, set per `describe` with
  // `test.use({ seedConfig })` (SEC-004 AC-QA-10). Empty: the worker's shared server.
  //
  // TEST-scoped, not worker-scoped as the spec's AC-QA-10 words it: Playwright refuses
  // `test.use({ seedConfig })` inside a describe for a worker-scoped option ("it forces
  // a new worker"; measured on this repo's Playwright). A test that names a fixture gets
  // its OWN server, started for that test and stopped after it, so no test can start from
  // another's saved rows. The one-writer-per-value rule is then belt and braces, kept
  // and checked statically (tests/unit/e2e_seed_config_ownership.test.ts).
  seedConfig: ['', { option: true }],

  // The server THIS test talks to: its own seeded one, or the worker's.
  testServer: async ({ seedConfig, workerServer }, use, testInfo) => {
    if (!seedConfig) {
      await use(workerServer);
      return;
    }
    await serverLifecycle.serve(
      { index: SEEDED_SERVER_INDEX_BASE + testInfo.parallelIndex, workerIndex: testInfo.workerIndex, seedConfig },
      use,
    );
  },

  baseURL: async ({ testServer }, use) => {
    await use(testServer.baseURL);
  },

  settingsPersistenceGuard: [async ({ page, testServer, seedConfig }, use, testInfo) => {
    const tally = { blocked: 0, sharedGroupSaves: 0 };
    const settingsURL = `${testServer.apiBase}/settings/`;
    const before = await loadSettingsSnapshot(settingsURL, 'baseline');

    await page.route(SETTINGS_WRITE_ROUTES, guardRoute(tally, !seedConfig, testInfo.annotations));

    await use();
    // A group save still waiting out its delay (the 500 ms debounce, or the 8 s undo window of a
    // removal) is SENT when the page closes: the Settings page flushes it on `pagehide`, as a
    // `keepalive` request, which the browser makes itself, so no Playwright route (mocks and
    // this guard included) and no request listener ever sees it. It lands on the real server.
    // So a test that is not a declared combine-group writer must not end with one pending.
    await assertNoPendingGroupSave(page, testInfo.annotations);
    // Audit only after no later browser callback can slip a save into the teardown window.
    await page.close();

    const after = await loadSettingsSnapshot(settingsURL, 'after');
    const changed = changedSettings(before, after);
    // Channel-independent: a route of the test's own, or the `request` fixture, never
    // passes through guardRoute. Restored first (the shared server must not be left
    // changed), and its error still wins over a restore failure.
    try {
      await restoreAndVerify(testServer.apiBase, settingsURL, before, changed);
    } finally {
      if (!seedConfig) assertNoSharedGroupChange(before, changed);
    }
    assertTeardownAudit(tally, changed, testInfo.annotations, seedConfig);
  }, { auto: true }],
});

export { expect };
