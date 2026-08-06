/**
 * Every Playwright project is run by a real gate, and no command widens itself.
 *
 * Two defects live here, both measured on this branch:
 *
 * 1. `npm run test:e2e` used to be a bare `npx playwright test`, which selects
 *    ALL projects -- including `isolation`, whose two specs only demonstrate
 *    anything on different workers. playwright.config.ts pins `workers: 1`, so
 *    isolation-b-assert failed every run by construction and `npm test`,
 *    `test:e2e` and `test:all` were red on a completely green tree.
 *
 * 2. Naming projects in `test:e2e` then broke the gates the other way, because
 *    Playwright UNIONS repeated `--project` flags. `npm run test:e2e --
 *    --project=chromium` does not scope the run down, it ADDS chromium to the
 *    three already named: measured, verify.sh's "chromium" step ran 158 tests
 *    across three projects and the steps after it re-ran two of them.
 *
 * The first version of this guard read `package.json` and nothing else, and
 * two reviewers showed it could not fail on either defect: reverting test:e2e
 * to the bare form passed, and a project run by no gate at all passed. It
 * measured an artefact the gates had stopped using. So it now reads the
 * COMMANDS -- in the gates that run them and the docs that teach them.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const REPO_ROOT = path.resolve(__dirname, '..', '..');

/** The two files that actually decide what runs. Hard rule 2 makes them mirrors. */
const GATES = ['scripts/verify.sh', '.github/workflows/ci.yml'];

/** Everywhere else a reader could copy a Playwright command from. */
const DOCS = ['Makefile', 'AGENTS.md', 'docs/development-process.md'];

function read(relative: string): string {
  return readFileSync(path.join(REPO_ROOT, relative), 'utf8');
}

/**
 * Logical lines: backslash continuations joined first.
 *
 * verify.sh wraps exactly these invocations with `\`. A per-line scan let the
 * composed form hide by moving `--project=` onto the next physical line --
 * measured, that spelling passed the first version of this guard.
 */
function logicalLines(source: string): string[] {
  return source.replace(/\\\n\s*/g, ' ').split('\n');
}

interface Invocation { file: string; line: string; projects: string[] }

/**
 * Every `playwright test` COMMAND in `files`, with the projects it selects.
 *
 * Comments and prose are skipped, not stripped. Stripping them made the guard
 * flag its own explanatory comments -- verify.sh's block explaining why the
 * composed form is wrong contains that form verbatim, which is exactly the
 * `echo "hint: add set -o pipefail"` false-positive class this repo has
 * already been bitten by twice. In Markdown only fenced code counts, so prose
 * naming a command is not read as running one.
 */
function codeLines(file: string): string[] {
  const markdown = file.endsWith('.md');
  const out: string[] = [];
  let inFence = false;

  for (const line of logicalLines(read(file))) {
    if (markdown && /^\s*```/.test(line)) { inFence = !inFence; continue; }
    if (markdown && !inFence) continue;
    if (!markdown && /^\s*#/.test(line)) continue;
    out.push(line);
  }
  return out;
}

function invocations(files: string[]): Invocation[] {
  const found: Invocation[] = [];
  for (const file of files) {
    for (const line of codeLines(file)) {
      if (!/playwright\s+test\b/.test(line)) continue;
      if (/playwright\s+install\b/.test(line)) continue;
      found.push({
        file,
        line: line.trim(),
        projects: [...line.matchAll(/--project=([A-Za-z0-9_-]+)/g)].map((m) => m[1]),
      });
    }
  }
  return found;
}

/** Source with `//` and block comments removed, so braces in prose do not count. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

/**
 * How many project object literals the `projects: [...]` array actually holds.
 *
 * The cross-check that makes `declaredProjects()` honest. That function is a
 * regex over `name:`, so a project spelled in any way it does not anticipate
 * is not reported as a problem -- it simply vanishes, and every check built on
 * it passes while covering one project fewer. Measured, three ordinary
 * spellings did exactly that: a backtick-quoted name, a `name` with no
 * trailing comma, and a whole project written on one line. The first also
 * carried a 15_000ms timeout, under the 25_000ms readiness budget, with all
 * eight tests green.
 *
 * Counting literals cannot make the same mistake, because it does not care
 * how the name is written.
 */
function projectLiteralCount(): number {
  const source = stripComments(read('playwright.config.ts'));
  const start = source.indexOf('projects:');
  expect(start, 'no `projects:` array found in playwright.config.ts').toBeGreaterThan(-1);

  let bracket = 0;
  let brace = 0;
  let count = 0;
  for (let i = source.indexOf('[', start); i < source.length; i += 1) {
    const c = source[i];
    if (c === '[') bracket += 1;
    else if (c === ']') { bracket -= 1; if (bracket === 0) break; }
    else if (c === '{') { if (bracket === 1 && brace === 0) count += 1; brace += 1; }
    else if (c === '}') brace -= 1;
  }
  return count;
}

function declaredProjects(): string[] {
  // Quote-agnostic and comment-tolerant: `name: "firefox", // slow` must be
  // seen. The first version anchored on `^      name: '…',$`, so a trailing
  // comment or a reformat made a project invisible and the guard silently
  // stopped covering it.
  //
  // stripComments FIRST, and for the same reason projectLiteralCount does it:
  // the two must read the SAME text or their counts cannot be compared. When
  // this one read the raw source, block-commenting a project out -- an
  // ordinary thing to do while chasing a flake -- counted as a name but not
  // as a literal, so the cross-check below fired on a correct config and told
  // the reader to go looking for an unreadable project name that did not
  // exist. A blocking gate crying wolf, which is what this file's own
  // sibling rule warns teaches people to bypass it.
  //
  // The key may be quoted (`"name": 'x'`); JSON-ish spellings are legal TS.
  const source = stripComments(read('playwright.config.ts'));
  return [...source.matchAll(/^\s*["']?name["']?\s*:\s*['"`]([^'"`]+)['"`]\s*,/gm)].map((m) => m[1]);
}

describe('Playwright project coverage', () => {
  it('finds the projects and the commands at all', () => {
    // Guard the guard. Both parsers are regexes over files free to be
    // reformatted; if either stopped matching, everything below would compare
    // empty sets and pass vacuously.
    expect(declaredProjects().length, 'no projects parsed out of playwright.config.ts')
      .toBeGreaterThanOrEqual(4);
    // The floor above only binds when an EXISTING project is reformatted. A
    // newly ADDED project the regex cannot read leaves the count unchanged
    // and every check below silently covers one project fewer. This is what
    // makes an addition visible.
    expect(
      declaredProjects().length,
      `playwright.config.ts declares ${projectLiteralCount()} project object(s) ` +
      `but only ${declaredProjects().length} name(s) could be read: ` +
      `[${declaredProjects().join(', ')}]. A project whose name this parser ` +
      `cannot see is covered by nothing, and nothing else here would notice.`,
    ).toBe(projectLiteralCount());
    expect(invocations(GATES).length, 'no playwright commands found in the gates')
      .toBeGreaterThanOrEqual(4);
  });

  it('runs every declared project from a real gate', () => {
    const runByGates = new Set(invocations(GATES).flatMap((i) => i.projects));
    const unrun = declaredProjects().filter((name) => !runByGates.has(name));

    expect(
      unrun,
      `these playwright.config.ts projects are run by NO gate, so nothing ` +
      `exercises them: ${unrun.join(', ')}. That is the mobile-chrome defect ` +
      `again -- it matched every spec and was executed by no command until a ` +
      `review found it, and found a real overflow bug the first time it ran.`,
    ).toEqual([]);
  });

  it('names no project that playwright.config.ts does not declare', () => {
    const declared = new Set(declaredProjects());
    const dangling = [...GATES, ...DOCS].flatMap((f) =>
      invocations([f]).flatMap((i) => i.projects.filter((p) => !declared.has(p)).map((p) => `${p} in ${f}`)),
    );

    expect(
      dangling,
      'a command selects a project that no longer exists; Playwright exits ' +
      'non-zero on an unknown --project, so that command is broken.',
    ).toEqual([]);
  });

  it('never runs playwright without naming a project', () => {
    // A bare `npx playwright test` selects EVERY project, isolation included,
    // and isolation cannot pass at the pinned workers: 1. This is defect (1)
    // in the header, and the first version of this guard could not see it,
    // because it only looked at explicit --project= flags in package.json.
    const bare = [...invocations([...GATES, ...DOCS]), ...packageScriptInvocations()]
      .filter((i) => i.projects.length === 0);

    expect(
      bare.map((i) => `${i.file}: ${i.line}`),
      'a bare `playwright test` selects every project, including `isolation`, ' +
      'which fails by construction at workers: 1.',
    ).toEqual([]);
  });

  it('never composes --project onto a script that already names projects', () => {
    // Defect (2). Playwright unions --project, so this widens rather than
    // scopes. Checked in the docs too, because AGENTS.md is the rubric
    // reviewers apply and the Makefile is a documented entry point -- both
    // still carried the composed form after the gates were fixed.
    const pkg = JSON.parse(read('package.json')) as { scripts: Record<string, string> };
    const namesProjects = new Set(
      Object.entries(pkg.scripts)
        .filter(([n, cmd]) => !n.startsWith('_comment:') && cmd.includes('--project='))
        .map(([n]) => n),
    );
    expect(namesProjects.size).toBeGreaterThan(0);

    const offenders: string[] = [];
    for (const file of [...GATES, ...DOCS]) {
      for (const line of codeLines(file)) {
        const composed = line.match(/npm run ([\w:-]+)\s+--\s+.*--project=/);
        if (composed && namesProjects.has(composed[1])) {
          offenders.push(`${file}: ${line.trim()}`);
        }
      }
    }

    expect(
      offenders,
      'composing --project onto an npm script that already names projects ' +
      'WIDENS the run. Call `npx playwright test --project=...` directly.',
    ).toEqual([]);
  });

  it('runs the isolation project only with two or more workers', () => {
    for (const inv of [...invocations([...GATES, ...DOCS]), ...packageScriptInvocations()]) {
      if (!inv.projects.includes('isolation')) continue;
      const workers = inv.line.match(/--workers=(\d+)/);
      expect(
        workers != null && Number(workers[1]) >= 2,
        `${inv.file} runs the isolation project without --workers=2 or more. ` +
        `At one worker both specs share a worker, the mutation legitimately ` +
        `reaches the assertion, and it fails every run: ${inv.line}`,
      ).toBe(true);
    }
  });
});

/** npm scripts, shaped like gate invocations so the same checks apply. */
function packageScriptInvocations(): Invocation[] {
  const pkg = JSON.parse(read('package.json')) as { scripts: Record<string, string> };
  return Object.entries(pkg.scripts)
    .filter(([name, cmd]) => !name.startsWith('_comment:') && /playwright\s+test\b/.test(cmd))
    .map(([name, cmd]) => ({
      file: `package.json (${name})`,
      line: cmd,
      projects: [...cmd.matchAll(/--project=([A-Za-z0-9_-]+)/g)].map((m) => m[1]),
    }));
}
