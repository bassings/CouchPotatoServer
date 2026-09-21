#!/usr/bin/env node

import {constants as fsConstants} from 'node:fs';
import {access, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {chromium} from '@playwright/test';
import * as chromeLauncher from 'chrome-launcher';
import lighthouse from 'lighthouse';

import {POLICY, resetOutput, runAuditSuite} from './lighthouse-policy.mjs';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

async function preflight() {
  let response;
  try {
    response = await fetch(`${POLICY.baseUrl}/`, {
      redirect: 'manual',
      signal: AbortSignal.timeout(5000),
    });
  } catch (error) {
    throw new Error(
      `CouchPotato is not reachable at ${POLICY.baseUrl}; start the local server before running Lighthouse`,
      {cause: error},
    );
  }
  if (response.status >= 500) {
    throw new Error(
      `CouchPotato at ${POLICY.baseUrl} returned HTTP ${response.status}; fix the server before running Lighthouse`,
    );
  }
}

async function launchBrowser() {
  const chromePath = chromium.executablePath();
  try {
    await access(chromePath, fsConstants.X_OK);
  } catch (error) {
    throw new Error(
      'Playwright Chromium is not installed; run `npx playwright install chromium`',
      {cause: error},
    );
  }
  const chrome = await chromeLauncher.launch({
    chromePath,
    chromeFlags: ['--headless=new', '--disable-gpu'],
    logLevel: 'silent',
  });
  return {port: chrome.port, close: () => chrome.kill()};
}

async function runLighthouse(url, port) {
  return lighthouse(url, {
    port,
    output: ['html', 'json'],
    logLevel: 'error',
    throttlingMethod: POLICY.settings.throttlingMethod,
    skipAudits: [...POLICY.settings.skipAudits],
  });
}

async function writeReport(filename, contents) {
  await writeFile(filename, contents, {encoding: 'utf8', mode: 0o600});
}

async function writeSummary(filename, summary) {
  await writeFile(filename, `${JSON.stringify(summary, null, 2)}\n`, {
    encoding: 'utf8',
    mode: 0o600,
  });
}

try {
  await runAuditSuite({
    repoRoot: REPO_ROOT,
    preflight,
    launchBrowser,
    runLighthouse,
    resetOutput,
    writeReport,
    writeSummary,
  });
} catch (error) {
  console.error(`Lighthouse failed: ${error.message}`);
  process.exitCode = 1;
}
