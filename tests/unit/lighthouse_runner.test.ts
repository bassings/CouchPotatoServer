import {access, lstat, mkdir, mkdtemp, readFile, rm, symlink, writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import {describe, expect, it, vi} from 'vitest';

import {
  POLICY,
  evaluateLhr,
  reportPaths,
  resetOutput,
  runAuditSuite,
} from '../../scripts/lighthouse-policy.mjs';

const REPO_ROOT = path.resolve(__dirname, '..', '..');

function passingLhr(finalDisplayedUrl = 'http://localhost:5050/') {
  return {
    finalDisplayedUrl,
    categories: {
      performance: {score: 0.9},
      accessibility: {score: 1},
      'best-practices': {score: 1},
      seo: {score: 1},
    },
    audits: {
      'http-status-code': {score: 1, numericValue: 200},
      'color-contrast': {score: 1},
      'image-alt': {score: 1},
      'link-name': {score: 1},
      'button-name': {score: 1},
      'first-contentful-paint': {numericValue: 1000},
      'largest-contentful-paint': {numericValue: 2000},
      'total-blocking-time': {numericValue: 100},
      'cumulative-layout-shift': {numericValue: 0.01},
    },
  };
}

describe('the direct Lighthouse policy', () => {
  it('keeps the fixed local routes, run count, and audit settings', () => {
    expect(POLICY.baseUrl).toBe('http://localhost:5050');
    expect(POLICY.runs).toBe(3);
    expect(POLICY.auditTimeoutMs).toBe(120_000);
    expect(POLICY.routes).toEqual([
      {path: '/', slug: 'home', expectedPath: '/'},
      {path: '/available/', slug: 'available', expectedPath: '/wanted?filter=available'},
      {path: '/add/', slug: 'add', expectedPath: '/add/'},
      {path: '/settings/', slug: 'settings', expectedPath: '/settings/'},
    ]);
    expect(POLICY.settings).toMatchObject({
      throttlingMethod: 'simulate',
      skipAudits: ['uses-http2', 'redirects-http'],
    });
  });

  it('preserves every explicit threshold and severity', () => {
    expect(POLICY.thresholds).toEqual([
      {kind: 'category', id: 'performance', minimum: 0.8, severity: 'warn'},
      {kind: 'category', id: 'accessibility', minimum: 0.9, severity: 'error'},
      {kind: 'category', id: 'best-practices', minimum: 0.9, severity: 'warn'},
      {kind: 'category', id: 'seo', minimum: 0.8, severity: 'warn'},
      {kind: 'audit-score', id: 'http-status-code', minimum: 1, severity: 'error'},
      {kind: 'audit-score', id: 'color-contrast', minimum: 0.9, severity: 'warn'},
      {kind: 'audit-score', id: 'image-alt', minimum: 1, severity: 'error'},
      {kind: 'audit-score', id: 'link-name', minimum: 1, severity: 'error'},
      {kind: 'audit-score', id: 'button-name', minimum: 1, severity: 'error'},
      {kind: 'audit-value', id: 'first-contentful-paint', maximum: 3000, severity: 'warn'},
      {kind: 'audit-value', id: 'largest-contentful-paint', maximum: 4000, severity: 'warn'},
      {kind: 'audit-value', id: 'total-blocking-time', maximum: 500, severity: 'warn'},
      {kind: 'audit-value', id: 'cumulative-layout-shift', maximum: 0.1, severity: 'warn'},
    ]);
  });
});

describe('threshold evaluation', () => {
  it('accepts exact boundaries', () => {
    const lhr = passingLhr();
    lhr.categories.performance.score = 0.8;
    lhr.categories.accessibility.score = 0.9;
    lhr.audits['first-contentful-paint'].numericValue = 3000;
    lhr.audits['cumulative-layout-shift'].numericValue = 0.1;
    expect(evaluateLhr(lhr, '/')).toEqual({errors: [], warnings: []});
  });

  it('separates blocking errors from visible warnings', () => {
    const lhr = passingLhr();
    lhr.categories.performance.score = 0.79;
    lhr.categories.accessibility.score = 0.89;
    lhr.audits['color-contrast'].score = 0;
    lhr.audits['button-name'].score = 0;
    const result = evaluateLhr(lhr, '/');
    expect(result.warnings.map((finding: {id: string}) => finding.id)).toEqual([
      'performance',
      'color-contrast',
    ]);
    expect(result.errors.map((finding: {id: string}) => finding.id)).toEqual([
      'accessibility',
      'button-name',
    ]);
  });

  it('blocks an HTTP error document even when its other scores pass', () => {
    const lhr = passingLhr();
    lhr.audits['http-status-code'].score = 0;
    lhr.audits['http-status-code'].numericValue = 404;
    expect(evaluateLhr(lhr, '/').errors).toContainEqual({
      id: 'http-status-code',
      actual: 0,
      expected: '>= 1',
    });
  });

  it('rejects a missing category or audit instead of silently passing', () => {
    const lhr = passingLhr();
    delete lhr.audits['image-alt'];
    expect(() => evaluateLhr(lhr, '/')).toThrow(/missing.*image-alt/i);
  });

  it('rejects runtime failures and redirects away from the fixed local origin', () => {
    const runtimeFailure = {...passingLhr(), runtimeError: {code: 'ERRORED_DOCUMENT_REQUEST'}};
    expect(() => evaluateLhr(runtimeFailure, '/')).toThrow(/runtime error/i);
    const external = passingLhr();
    external.finalDisplayedUrl = 'https://example.com/';
    expect(() => evaluateLhr(external, '/')).toThrow(/fixed local audit origin/i);
  });

  it.each(POLICY.routes)('requires $path to reach $expectedPath', ({expectedPath}) => {
    expect(evaluateLhr(passingLhr(`${POLICY.baseUrl}${expectedPath}`), expectedPath))
      .toEqual({errors: [], warnings: []});
    expect(() => evaluateLhr(
      passingLhr(`${POLICY.baseUrl}/unexpected`),
      expectedPath,
    )).toThrow(/expected page/i);
  });
});

describe('bounded local report paths', () => {
  it.each(POLICY.routes)('keeps $path reports under .lighthouseci', ({slug}) => {
    const reports = reportPaths(REPO_ROOT, slug, 1);
    for (const report of Object.values(reports)) {
      expect(path.relative(path.join(REPO_ROOT, '.lighthouseci'), report)).not.toMatch(
        /^(?:\.\.(?:[/\\]|$)|[/\\])/,
      );
    }
    expect(reports).toEqual({
      html: path.join(REPO_ROOT, '.lighthouseci', `${slug}-run-1.html`),
      json: path.join(REPO_ROOT, '.lighthouseci', `${slug}-run-1.json`),
    });
  });

  it('rejects caller-controlled path components', () => {
    expect(() => reportPaths(REPO_ROOT, '../escape', 1)).toThrow(/slug/i);
    expect(() => reportPaths(REPO_ROOT, 'home', 0)).toThrow(/run/i);
  });

  it('replaces an output-root symlink without touching its external target', async () => {
    const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'cps-lighthouse-output-'));
    const repoRoot = path.join(temporaryRoot, 'repo');
    const externalRoot = path.join(temporaryRoot, 'external');
    const outputRoot = path.join(repoRoot, '.lighthouseci');
    const sentinel = path.join(externalRoot, 'summary.json');
    try {
      await mkdir(repoRoot);
      await mkdir(externalRoot);
      await writeFile(sentinel, 'external sentinel');
      await symlink(externalRoot, outputRoot, 'dir');

      await resetOutput(repoRoot);

      expect(await readFile(sentinel, 'utf8')).toBe('external sentinel');
      const outputStat = await lstat(outputRoot);
      expect(outputStat.isDirectory()).toBe(true);
      expect(outputStat.isSymbolicLink()).toBe(false);
    } finally {
      await rm(temporaryRoot, {recursive: true, force: true});
    }
  });
});

describe('audit orchestration', () => {
  it('clears stale output before preflight without launching Chromium', async () => {
    const events: string[] = [];
    const resetOutput = vi.fn(async () => { events.push('reset'); });
    const launchBrowser = vi.fn();
    await expect(
      runAuditSuite({
        repoRoot: REPO_ROOT,
        preflight: vi.fn(async () => {
          events.push('preflight');
          throw new Error('server unavailable');
        }),
        launchBrowser,
        runLighthouse: vi.fn(),
        resetOutput,
        writeReport: vi.fn(),
        writeSummary: vi.fn(),
        log: vi.fn(),
      }),
    ).rejects.toThrow(/server unavailable/i);
    expect(events).toEqual(['reset', 'preflight']);
    expect(resetOutput).toHaveBeenCalledWith(REPO_ROOT);
    expect(launchBrowser).not.toHaveBeenCalled();
  });

  it('runs every route three times and writes both reports plus a final summary', async () => {
    const calls: string[] = [];
    const writes: string[] = [];
    const close = vi.fn(async () => undefined);
    const result = await runAuditSuite({
      repoRoot: REPO_ROOT,
      preflight: vi.fn(async () => undefined),
      launchBrowser: vi.fn(async () => ({port: 9222, close})),
      runLighthouse: vi.fn(async (url: string) => {
        calls.push(url);
        const route = POLICY.routes.find(({path: routePath}) => url === `${POLICY.baseUrl}${routePath}`);
        return {
          lhr: passingLhr(`${POLICY.baseUrl}${route?.expectedPath}`),
          report: ['<html>report</html>', '{"ok":true}'],
        };
      }),
      resetOutput: vi.fn(async () => undefined),
      writeReport: vi.fn(async (filename: string) => {
        writes.push(path.basename(filename));
      }),
      writeSummary: vi.fn(async (filename: string) => {
        writes.push(path.basename(filename));
      }),
      log: vi.fn(),
    });

    expect(calls).toEqual(
      POLICY.routes.flatMap(({path: route}) =>
        Array.from({length: POLICY.runs}, () => `${POLICY.baseUrl}${route}`),
      ),
    );
    expect(result.completed).toBe(12);
    expect(writes.filter((name) => name.endsWith('.html'))).toHaveLength(12);
    expect(
      writes.filter((name) => name.includes('-run-') && name.endsWith('.json')),
    ).toHaveLength(12);
    expect(writes.at(-1)).toBe('summary.json');
    expect(close).toHaveBeenCalledOnce();
  });

  it.each([
    ['reset output', {resetOutput: vi.fn(async () => { throw new Error('ENOSPC'); })}, /reset.*output.*ENOSPC/i],
    ['launch Chromium', {launchBrowser: vi.fn(async () => { throw new Error('EACCES'); })}, /launch Chromium.*EACCES/i],
    ['write HTML report', {writeReport: vi.fn(async () => { throw new Error('ENOSPC'); })}, /write HTML report.*home.*run 1.*ENOSPC/i],
    ['write JSON report', {writeReport: vi.fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('ENOSPC'))}, /write JSON report.*home.*run 1.*ENOSPC/i],
    ['write summary', {writeSummary: vi.fn(async () => { throw new Error('EROFS'); })}, /write.*summary.*EROFS/i],
  ])('adds context when it cannot %s', async (_stage, overrides, expected) => {
    const close = vi.fn(async () => undefined);
    const adapters = {
      repoRoot: REPO_ROOT,
      preflight: vi.fn(async () => undefined),
      launchBrowser: vi.fn(async () => ({port: 9222, close})),
      runLighthouse: vi.fn(async (url: string) => {
        const route = POLICY.routes.find(({path: routePath}) => url === `${POLICY.baseUrl}${routePath}`);
        return {
          lhr: passingLhr(`${POLICY.baseUrl}${route?.expectedPath}`),
          report: ['<html>report</html>', '{"ok":true}'],
        };
      }),
      resetOutput: vi.fn(async () => undefined),
      writeReport: vi.fn(async () => undefined),
      writeSummary: vi.fn(async () => undefined),
      log: vi.fn(),
      ...overrides,
    };
    await expect(runAuditSuite(adapters)).rejects.toThrow(expected);
  });

  it('closes the browser and never writes a success summary after a partial failure', async () => {
    const close = vi.fn(async () => undefined);
    const writeSummary = vi.fn();
    const runLighthouse = vi
      .fn()
      .mockResolvedValueOnce({
        lhr: passingLhr(),
        report: ['<html>report</html>', '{"ok":true}'],
      })
      .mockRejectedValueOnce(new Error('boom'));

    await expect(
      runAuditSuite({
        repoRoot: REPO_ROOT,
        preflight: vi.fn(async () => undefined),
        launchBrowser: vi.fn(async () => ({port: 9222, close})),
        runLighthouse,
        resetOutput: vi.fn(async () => undefined),
        writeReport: vi.fn(async () => undefined),
        writeSummary,
        log: vi.fn(),
      }),
    ).rejects.toThrow(/home.*run 2.*boom/i);

    expect(writeSummary).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
  });

  it('times out a wedged audit with route context and closes Chromium', async () => {
    vi.useFakeTimers();
    const close = vi.fn(async () => undefined);
    try {
      const audit = runAuditSuite({
        repoRoot: REPO_ROOT,
        preflight: vi.fn(async () => undefined),
        launchBrowser: vi.fn(async () => ({port: 9222, close})),
        runLighthouse: vi.fn(() => new Promise(() => undefined)),
        resetOutput: vi.fn(async () => undefined),
        writeReport: vi.fn(),
        writeSummary: vi.fn(),
        log: vi.fn(),
      });
      const rejection = expect(audit).rejects.toThrow(
        /home.*run 1.*timed out.*120000/i,
      );
      await vi.advanceTimersByTimeAsync(120_000);
      await rejection;
      expect(close).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it('rejects an incomplete report set and still closes the browser', async () => {
    const close = vi.fn(async () => undefined);
    await expect(
      runAuditSuite({
        repoRoot: REPO_ROOT,
        preflight: vi.fn(async () => undefined),
        launchBrowser: vi.fn(async () => ({port: 9222, close})),
        runLighthouse: vi.fn(async () => ({lhr: passingLhr(), report: ['html only']})),
        resetOutput: vi.fn(async () => undefined),
        writeReport: vi.fn(),
        writeSummary: vi.fn(),
        log: vi.fn(),
      }),
    ).rejects.toThrow(/incomplete result or report set/i);
    expect(close).toHaveBeenCalledOnce();
  });

  it('processes all audits, records error findings, then exits nonzero', async () => {
    const writeSummary = vi.fn(async () => undefined);
    const failed = passingLhr();
    failed.audits['image-alt'].score = 0;
    const runLighthouse = vi.fn(async (url: string) => {
      const route = POLICY.routes.find(({path: routePath}) => url === `${POLICY.baseUrl}${routePath}`);
      return {
        lhr: {...failed, finalDisplayedUrl: `${POLICY.baseUrl}${route?.expectedPath}`},
        report: ['<html>report</html>', '{"ok":true}'],
      };
    });
    await expect(
      runAuditSuite({
        repoRoot: REPO_ROOT,
        preflight: vi.fn(async () => undefined),
        launchBrowser: vi.fn(async () => ({port: 9222, close: vi.fn()})),
        runLighthouse,
        resetOutput: vi.fn(async () => undefined),
        writeReport: vi.fn(async () => undefined),
        writeSummary,
        log: vi.fn(),
      }),
    ).rejects.toThrow(/error thresholds failed.*image-alt/i);
    expect(runLighthouse).toHaveBeenCalledTimes(12);
    expect(writeSummary).toHaveBeenCalledOnce();
    expect(writeSummary.mock.calls[0][1]).toMatchObject({completed: 12});
    expect(writeSummary.mock.calls[0][1].errors).toHaveLength(12);
  });
});

describe('dependency and privacy closure', () => {
  it('removes LHCI and extract-zip from the manifest and lockfile', async () => {
    const manifest = JSON.parse(await readFile(path.join(REPO_ROOT, 'package.json'), 'utf8'));
    const lock = await readFile(path.join(REPO_ROOT, 'package-lock.json'), 'utf8');
    expect(manifest.devDependencies.lighthouse).toBe('13.5.0');
    expect(manifest.devDependencies['chrome-launcher']).toBe('1.2.1');
    expect(manifest.engines.node).toBe('>=22.19');
    expect(manifest.devDependencies['@lhci/cli']).toBeUndefined();
    expect(manifest.devDependencies['@lhci/utils']).toBeUndefined();
    expect(lock).not.toContain('node_modules/extract-zip');
    expect(lock).not.toContain('node_modules/@lhci/');
  });

  it('keeps the report directory ignored and exposes no upload configuration', async () => {
    await expect(access(path.join(REPO_ROOT, 'lighthouserc.js'))).rejects.toThrow();
    const runner = await readFile(
      path.join(REPO_ROOT, 'scripts', 'lighthouse-runner.mjs'),
      'utf8',
    );
    expect(runner).not.toMatch(/temporary-public-storage|saveHtmlReport|uploadTarget/);
    expect(runner).not.toMatch(/process\.(?:argv|env)/);
    const ignored = spawnSync('git', ['check-ignore', '-q', '.lighthouseci/'], {
      cwd: REPO_ROOT,
    });
    expect(ignored.status).toBe(0);
  });
});
