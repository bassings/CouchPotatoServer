/**
 * Every Playwright project is run by exactly one npm script.
 *
 * `npm run test:e2e` used to be a bare `npx playwright test`, which selects
 * ALL projects -- including `isolation`, whose two specs only demonstrate
 * anything when they land on different workers. playwright.config.ts pins
 * `workers: 1` globally, so at one worker both specs share a worker, the
 * mutation legitimately reaches the assertion, and isolation-b-assert failed
 * every run by construction. `npm test`, `npm run test:e2e` and
 * `npm run test:all` were therefore red on a completely green tree, and
 * docs/development-process.md told the reader to run one of them.
 *
 * It went unnoticed because scripts/verify.sh and ci.yml always pass
 * --project, so the gate never took the broken path.
 *
 * Naming the projects explicitly fixes that, and creates a second, quieter
 * failure mode: a new project added to playwright.config.ts is then run by
 * nothing at all. That is the same class of defect as the mobile project,
 * which matched every spec and was executed by no script until a review
 * found it -- and found a real overflow bug the first time it ran. This
 * guard closes both directions.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const REPO_ROOT = path.resolve(__dirname, '..', '..');

function read(relative: string): string {
  return readFileSync(path.join(REPO_ROOT, relative), 'utf8');
}

/** Project names declared in playwright.config.ts's `projects` array. */
function declaredProjects(): string[] {
  const source = read('playwright.config.ts');
  return [...source.matchAll(/^      name: '([^']+)',$/gm)].map((m) => m[1]);
}

/** Every `--project=<name>` across all npm scripts, with the script it came from. */
function scriptedProjects(): Map<string, string[]> {
  const pkg = JSON.parse(read('package.json')) as { scripts: Record<string, string> };
  const byProject = new Map<string, string[]>();

  for (const [name, command] of Object.entries(pkg.scripts)) {
    // `_comment:` keys document the scripts; they are not runnable and must
    // not count as coverage for a project they merely mention.
    if (name.startsWith('_comment:')) continue;
    for (const match of command.matchAll(/--project=([A-Za-z0-9-]+)/g)) {
      byProject.set(match[1], [...(byProject.get(match[1]) ?? []), name]);
    }
  }
  return byProject;
}

describe('Playwright project coverage', () => {
  it('finds the projects and the scripts at all', () => {
    // Guard the guard: both parsers are regex-based against files that are
    // free to be reformatted. If either silently stopped matching, the
    // assertions below would compare two empty sets and pass vacuously.
    expect(declaredProjects().length).toBeGreaterThanOrEqual(4);
    expect(scriptedProjects().size).toBeGreaterThanOrEqual(4);
  });

  it('runs every declared project from some npm script', () => {
    const scripted = scriptedProjects();
    const unrun = declaredProjects().filter((name) => !scripted.has(name));

    expect(
      unrun,
      `these playwright.config.ts projects are run by no npm script, so they ` +
      `are dead weight that nothing exercises: ${unrun.join(', ')}. Add them ` +
      `to test:e2e, or give them their own script the way isolation has one.`,
    ).toEqual([]);
  });

  it('names no project that playwright.config.ts does not declare', () => {
    const declared = new Set(declaredProjects());
    const dangling = [...scriptedProjects()].filter(([name]) => !declared.has(name));

    expect(
      dangling.map(([name, scripts]) => `${name} (in ${scripts.join(', ')})`),
      'an npm script selects a project that no longer exists; Playwright ' +
      'exits non-zero on an unknown --project, so this script is broken.',
    ).toEqual([]);
  });

  it('never composes --project onto an npm script that already names projects', () => {
    /*
     * Playwright UNIONS repeated --project flags. `npm run test:e2e --
     * --project=chromium` therefore does not scope test:e2e down to chromium
     * -- it ADDS chromium to the three test:e2e already names.
     *
     * That is exactly what happened the moment test:e2e stopped being a bare
     * `npx playwright test`: measured, scripts/verify.sh's "chromium" step ran
     * chromium + accessibility + mobile-chrome (158 tests, with
     * `--project=chromium` listed twice on the command line), and the two
     * steps after it re-ran two of those projects again. The gate stayed
     * green, just slower and no longer meaning what its step names said.
     *
     * The fix is that the gates call `npx playwright test --project=...`
     * directly and name exactly what each step runs. This pins it, in both
     * files, because hard rule 4 makes them mirrors of each other.
     */
    const pkg = JSON.parse(read('package.json')) as { scripts: Record<string, string> };
    const scriptsNamingProjects = new Set(
      Object.entries(pkg.scripts)
        .filter(([name, cmd]) => !name.startsWith('_comment:') && cmd.includes('--project='))
        .map(([name]) => name),
    );
    expect(scriptsNamingProjects.size).toBeGreaterThan(0);

    for (const gate of ['scripts/verify.sh', '.github/workflows/ci.yml']) {
      for (const line of read(gate).split('\n')) {
        if (line.trim().startsWith('#')) continue;
        const composed = line.match(/npm run ([\w:-]+)\s+--\s+[^\n]*--project=/);
        if (!composed) continue;
        expect(
          scriptsNamingProjects.has(composed[1]),
          `${gate} composes --project onto "npm run ${composed[1]}", which ` +
          `already names projects. Playwright unions --project flags, so this ` +
          `WIDENS the run instead of scoping it. Call npx playwright test ` +
          `--project=... directly: ${line.trim()}`,
        ).toBe(false);
      }
    }
  });

  it('keeps isolation out of test:e2e, because it cannot pass at one worker', () => {
    const scripts = scriptedProjects().get('isolation');
    expect(scripts, 'the isolation project is run by no script').toBeDefined();

    // It must be run ONLY by a script that also pins more than one worker.
    for (const name of scripts!) {
      const command = (JSON.parse(read('package.json')) as { scripts: Record<string, string> }).scripts[name];
      const workers = command.match(/--workers=(\d+)/);
      expect(
        workers && Number(workers[1]) >= 2,
        `npm script "${name}" runs the isolation project without pinning ` +
        `--workers=2 or more. At one worker isolation-b-assert fails every ` +
        `run by construction.`,
      ).toBe(true);
    }
  });
});
