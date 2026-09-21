import path from 'node:path';
import {mkdir, rm} from 'node:fs/promises';

export const POLICY = Object.freeze({
  baseUrl: 'http://localhost:5050',
  runs: 3,
  auditTimeoutMs: 120_000,
  routes: Object.freeze([
    Object.freeze({path: '/', slug: 'home', expectedPath: '/'}),
    Object.freeze({path: '/available/', slug: 'available', expectedPath: '/wanted?filter=available'}),
    Object.freeze({path: '/add/', slug: 'add', expectedPath: '/add/'}),
    Object.freeze({path: '/settings/', slug: 'settings', expectedPath: '/settings/'}),
  ]),
  settings: Object.freeze({
    throttlingMethod: 'simulate',
    skipAudits: Object.freeze(['uses-http2', 'redirects-http']),
  }),
  thresholds: Object.freeze([
    Object.freeze({kind: 'category', id: 'performance', minimum: 0.8, severity: 'warn'}),
    Object.freeze({kind: 'category', id: 'accessibility', minimum: 0.9, severity: 'error'}),
    Object.freeze({kind: 'category', id: 'best-practices', minimum: 0.9, severity: 'warn'}),
    Object.freeze({kind: 'category', id: 'seo', minimum: 0.8, severity: 'warn'}),
    Object.freeze({kind: 'audit-score', id: 'http-status-code', minimum: 1, severity: 'error'}),
    Object.freeze({kind: 'audit-score', id: 'color-contrast', minimum: 0.9, severity: 'warn'}),
    Object.freeze({kind: 'audit-score', id: 'image-alt', minimum: 1, severity: 'error'}),
    Object.freeze({kind: 'audit-score', id: 'link-name', minimum: 1, severity: 'error'}),
    Object.freeze({kind: 'audit-score', id: 'button-name', minimum: 1, severity: 'error'}),
    Object.freeze({kind: 'audit-value', id: 'first-contentful-paint', maximum: 3000, severity: 'warn'}),
    Object.freeze({kind: 'audit-value', id: 'largest-contentful-paint', maximum: 4000, severity: 'warn'}),
    Object.freeze({kind: 'audit-value', id: 'total-blocking-time', maximum: 500, severity: 'warn'}),
    Object.freeze({kind: 'audit-value', id: 'cumulative-layout-shift', maximum: 0.1, severity: 'warn'}),
  ]),
});

function requireFinite(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Lighthouse result is missing ${label}`);
  }
  return value;
}

export function evaluateLhr(lhr, expectedPath) {
  if (!lhr || typeof lhr !== 'object') throw new Error('Lighthouse returned no result');
  if (lhr.runtimeError) throw new Error('Lighthouse reported a page runtime error');
  let displayedUrl;
  try {
    displayedUrl = new URL(lhr.finalDisplayedUrl);
  } catch (error) {
    throw new Error('Lighthouse result has no valid final URL', {cause: error});
  }
  if (displayedUrl.origin !== POLICY.baseUrl) {
    throw new Error('Lighthouse left the fixed local audit origin');
  }
  if (`${displayedUrl.pathname}${displayedUrl.search}` !== expectedPath) {
    throw new Error(`Lighthouse did not reach the expected page ${expectedPath}`);
  }
  const findings = {errors: [], warnings: []};
  for (const threshold of POLICY.thresholds) {
    let actual;
    let failed;
    let expected;
    if (threshold.kind === 'category') {
      actual = requireFinite(lhr.categories?.[threshold.id]?.score, `category ${threshold.id}`);
      failed = actual < threshold.minimum;
      expected = `>= ${threshold.minimum}`;
    } else if (threshold.kind === 'audit-score') {
      actual = requireFinite(lhr.audits?.[threshold.id]?.score, `audit ${threshold.id}`);
      failed = actual < threshold.minimum;
      expected = `>= ${threshold.minimum}`;
    } else {
      actual = requireFinite(lhr.audits?.[threshold.id]?.numericValue, `audit ${threshold.id}`);
      failed = actual > threshold.maximum;
      expected = `<= ${threshold.maximum}`;
    }
    if (failed) {
      const bucket = threshold.severity === 'error' ? findings.errors : findings.warnings;
      bucket.push({id: threshold.id, actual, expected});
    }
  }
  return findings;
}

export function reportPaths(repoRoot, slug, runNumber) {
  if (!POLICY.routes.some((route) => route.slug === slug)) {
    throw new Error(`Unknown report slug: ${slug}`);
  }
  if (!Number.isInteger(runNumber) || runNumber < 1 || runNumber > POLICY.runs) {
    throw new Error(`Invalid Lighthouse run number: ${runNumber}`);
  }
  const outputRoot = path.join(repoRoot, '.lighthouseci');
  const stem = `${slug}-run-${runNumber}`;
  return {
    html: path.join(outputRoot, `${stem}.html`),
    json: path.join(outputRoot, `${stem}.json`),
  };
}

export async function resetOutput(repoRoot) {
  const outputRoot = path.join(repoRoot, '.lighthouseci');
  await rm(outputRoot, {recursive: true, force: true});
  await mkdir(outputRoot, {recursive: true, mode: 0o700});
}

function validateReports(result) {
  if (!result?.lhr || !Array.isArray(result.report) || result.report.length !== 2) {
    throw new Error('Lighthouse returned an incomplete result or report set');
  }
  const [html, json] = result.report;
  if (typeof html !== 'string' || typeof json !== 'string') {
    throw new Error('Lighthouse returned malformed HTML or JSON report data');
  }
  return {lhr: result.lhr, html, json};
}

async function runStage(label, operation) {
  try {
    return await operation();
  } catch (error) {
    throw new Error(`${label} failed: ${error.message}`, {cause: error});
  }
}

async function runWithDeadline(operation, timeoutMs) {
  let timeout;
  try {
    return await Promise.race([
      Promise.resolve().then(operation),
      new Promise((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error(`timed out after ${timeoutMs} ms`)),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
}

export async function runAuditSuite({
  repoRoot,
  preflight,
  launchBrowser,
  runLighthouse,
  resetOutput,
  writeReport,
  writeSummary,
  log = console.log,
}) {
  await runStage('Reset Lighthouse output', () => resetOutput(repoRoot));
  await runStage('Server preflight', preflight);
  const browser = await runStage('Launch Chromium', launchBrowser);
  const summary = {completed: 0, warnings: [], errors: [], reports: []};
  let primaryError;
  try {
    for (const route of POLICY.routes) {
      for (let runNumber = 1; runNumber <= POLICY.runs; runNumber += 1) {
        const url = `${POLICY.baseUrl}${route.path}`;
        let rawResult;
        try {
          rawResult = await runWithDeadline(
            () => runLighthouse(url, browser.port),
            POLICY.auditTimeoutMs,
          );
        } catch (error) {
          throw new Error(
            `Lighthouse failed for ${route.slug} run ${runNumber}: ${error.message}`,
            {cause: error},
          );
        }
        let lhr;
        let html;
        let json;
        let findings;
        try {
          ({lhr, html, json} = validateReports(rawResult));
          findings = evaluateLhr(lhr, route.expectedPath);
        } catch (error) {
          throw new Error(
            `Lighthouse result failed for ${route.slug} run ${runNumber}: ${error.message}`,
            {cause: error},
          );
        }
        const reports = reportPaths(repoRoot, route.slug, runNumber);
        await runStage(`Write HTML report for ${route.slug} run ${runNumber}`, () =>
          writeReport(reports.html, html));
        await runStage(`Write JSON report for ${route.slug} run ${runNumber}`, () =>
          writeReport(reports.json, json));
        summary.completed += 1;
        summary.warnings.push(...findings.warnings.map((item) => ({...item, route: route.path, run: runNumber})));
        summary.errors.push(...findings.errors.map((item) => ({...item, route: route.path, run: runNumber})));
        summary.reports.push({route: route.path, run: runNumber, html: path.basename(reports.html), json: path.basename(reports.json)});
      }
    }
    const expected = POLICY.routes.length * POLICY.runs;
    if (summary.completed !== expected) {
      throw new Error(`Lighthouse completed ${summary.completed} of ${expected} required audits`);
    }
    await runStage('Write Lighthouse summary', () =>
      writeSummary(path.join(repoRoot, '.lighthouseci', 'summary.json'), summary));
    if (summary.errors.length > 0) {
      const details = summary.errors
        .map((error) => `${error.route} run ${error.run}: ${error.id} ${error.actual} (${error.expected})`)
        .join('; ');
      primaryError = new Error(`Lighthouse error thresholds failed: ${details}`);
    }
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    try {
      await browser.close();
    } catch (error) {
      if (!primaryError) {
        primaryError = new Error('Chromium cleanup failed after Lighthouse completed', {cause: error});
      } else {
        log('WARN Chromium cleanup failed after an earlier Lighthouse failure');
      }
    }
  }

  for (const warning of summary.warnings) {
    log(`WARN ${warning.route} run ${warning.run}: ${warning.id} ${warning.actual} (expected ${warning.expected})`);
  }
  if (primaryError) throw primaryError;
  log(`Lighthouse completed 12 audits; reports are in .lighthouseci/`);
  return summary;
}
