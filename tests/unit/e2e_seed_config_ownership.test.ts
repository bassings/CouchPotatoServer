// @vitest-environment node
/**
 * SEC-004 AC-QA-10: a test that writes a fixture's combine group is the only test in
 * the suite that uses that `seedConfig` value.
 *
 * Why it needs a static check: each distinct `seedConfig` value gets its own worker and
 * server, and the server reads `config.ini` once at start. A second test on the same
 * value would start from the first one's saved rows, and would pass or fail by test
 * order. Nothing at run time sees that, because each test is individually green.
 *
 * A writer says so by calling `combineGroupWriter()` (tests/e2e/settings_persistence.ts),
 * which is also what lets the persistence guard allow its group save. An unannotated
 * writer fails at teardown instead, so the two checks close each other's gap.
 *
 * What static reasoning can and cannot see. It sees the marker called in a test, in a
 * helper declared in the same file (transitively), and the annotation named directly
 * (by string, by COMBINE_WRITER_ANNOTATION, or as a test option). It cannot see a helper
 * imported from another file, nor a looped template whose iterations repeat a value
 * (`for (const label of ['a', 'a'])`). Those are closed at RUN time instead, in the
 * persistence guard (tests/e2e/fixtures.ts, assertWriterOwnsItsSeed): a writer on the
 * shared server, or on a value another writer already used in the worker, fails its test.
 * That guard sees only the tests that run in one worker process, so it is a net under this
 * check, not a replacement for it.
 */
import fs from 'node:fs';
import path from 'node:path';
import * as ts from '@typescript/typescript6';
import { describe, expect, it } from 'vitest';

type Source = { name: string; text: string };
type Declared = { value: string | null; writer: boolean; where: string };

const TEST_MODIFIERS = new Set(['only', 'fail', 'fixme', 'skip', 'slow']);

function isTestUse(call: ts.CallExpression): boolean {
  const callee = call.expression;
  return ts.isPropertyAccessExpression(callee)
    && ts.isIdentifier(callee.expression) && callee.expression.text === 'test'
    && callee.name.text === 'use';
}

function isDescribe(call: ts.CallExpression): boolean {
  let callee: ts.Expression = call.expression;
  while (ts.isPropertyAccessExpression(callee)) {
    if (callee.name.text === 'describe') return true;
    callee = callee.expression;
  }
  return false;
}

/** `test('title', async () => {...})`, with or without a modifier; not `test.skip(cond)`. */
function isTestDeclaration(call: ts.CallExpression): boolean {
  const callee = call.expression;
  const named = ts.isIdentifier(callee) && callee.text === 'test';
  const modified = ts.isPropertyAccessExpression(callee)
    && ts.isIdentifier(callee.expression) && callee.expression.text === 'test'
    && TEST_MODIFIERS.has(callee.name.text);
  const [title] = call.arguments;
  const titled = !!title && (ts.isStringLiteralLike(title) || ts.isTemplateExpression(title));
  return (named || modified) && titled && call.arguments.some((arg) => ts.isFunctionLike(arg));
}

/**
 * The `seedConfig` a `test.use` sets: its text for a string literal; for a template with
 * substitutions (a loop that gives each iteration its own fixture or label) a value that
 * belongs to THAT call site alone, `siteKey` plus the template; null for anything else,
 * which the check cannot reason about and refuses.
 */
function seedConfigOf(call: ts.CallExpression, siteKey: string): string | null | undefined {
  const [options] = call.arguments;
  if (!options || !ts.isObjectLiteralExpression(options)) return undefined;
  for (const property of options.properties) {
    if (ts.isPropertyAssignment(property) && property.name.getText() === 'seedConfig') {
      const { initializer } = property;
      if (ts.isStringLiteralLike(initializer)) return initializer.text;
      return ts.isTemplateExpression(initializer) ? `${siteKey} ${initializer.getText()}` : null;
    }
  }
  return undefined;
}

const ANNOTATION_NAME = 'writesCombineGroup';

/** Does `node` mark a writer: the marker call, a call to a same-file helper that does, or the annotation itself? */
function callsWriterMarker(node: ts.Node, helpers: Set<string>): boolean {
  let found = false;
  const visit = (child: ts.Node) => {
    if (ts.isCallExpression(child) && ts.isIdentifier(child.expression)
      && (child.expression.text === 'combineGroupWriter' || helpers.has(child.expression.text))) found = true;
    if (ts.isIdentifier(child) && child.text === 'COMBINE_WRITER_ANNOTATION') found = true;
    if (ts.isStringLiteralLike(child) && child.text === ANNOTATION_NAME) found = true;
    ts.forEachChild(child, visit);
  };
  visit(node);
  return found;
}

/** Names of functions in this file that reach the marker, directly or through another such function. */
function markerHelpers(file: ts.SourceFile): Set<string> {
  const bodies = new Map<string, ts.Node>();
  const collect = (node: ts.Node) => {
    if (ts.isFunctionDeclaration(node) && node.name && node.body) bodies.set(node.name.text, node.body);
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && ts.isFunctionLike(node.initializer)) {
      bodies.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, collect);
  };
  collect(file);
  const helpers = new Set<string>();
  for (let grew = true; grew;) {
    grew = false;
    for (const [name, body] of bodies) {
      if (!helpers.has(name) && callsWriterMarker(body, helpers)) {
        helpers.add(name);
        grew = true;
      }
    }
  }
  return helpers;
}

/** Every violation of the ownership rule across `sources`, as readable lines. */
export function seedConfigOwnershipViolations(sources: Source[]): string[] {
  const violations: string[] = [];
  const byValue = new Map<string, Declared[]>();

  for (const { name, text } of sources) {
    const file = ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const where = (node: ts.Node) => `${name}:${file.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
    const helpers = markerHelpers(file);
    const describes: { node: ts.CallExpression; value: string | null }[] = [];
    const declared: { node: ts.CallExpression; writer: boolean; scopes: typeof describes }[] = [];

    const visit = (node: ts.Node, scopes: typeof describes) => {
      let inner = scopes;
      if (ts.isCallExpression(node)) {
        if (isDescribe(node)) {
          const scope = { node, value: undefined as unknown as string | null };
          inner = [...scopes, scope];
          describes.push(scope);
        } else if (isTestUse(node) && seedConfigOf(node, where(node)) !== undefined) {
          const value = seedConfigOf(node, where(node)) as string | null;
          const owner = scopes[scopes.length - 1];
          if (!owner) violations.push(`${where(node)}: seedConfig is set outside a describe, so it would apply to the whole file`);
          else if (value === null) violations.push(`${where(node)}: seedConfig must be a string literal`);
          else owner.value = value;
        } else if (isTestDeclaration(node)) {
          declared.push({ node, writer: callsWriterMarker(node, helpers), scopes });
        }
      }
      ts.forEachChild(node, (child) => visit(child, inner));
    };
    visit(file, []);

    for (const { node, writer, scopes } of declared) {
      const scope = [...scopes].reverse().find((candidate) => typeof candidate.value === 'string');
      if (!scope) {
        if (writer) violations.push(`${where(node)}: a combine-group writer runs on the shared default worker`);
        continue;
      }
      const list = byValue.get(scope.value as string) ?? [];
      list.push({ value: scope.value, writer, where: where(node) });
      byValue.set(scope.value as string, list);
    }
  }

  for (const [value, tests] of byValue) {
    if (tests.length > 1 && tests.some((entry) => entry.writer)) {
      violations.push(
        `seedConfig '${value}' is used by ${tests.length} tests (${tests.map((entry) => entry.where).join(', ')}) `
        + 'but one of them writes a combine group, so it must be the only one',
      );
    }
  }
  return violations;
}

const writer = (body = '') => `await page.goto('/'); test.info().annotations.push(...combineGroupWriter()); ${body}`;

describe('seedConfig ownership check', () => {
  it('accepts one writer alone on its own value', () => {
    const text = `test.describe('a', () => {
      test.use({ seedConfig: 'newznab_aligned#one' });
      test('writes', async ({ page }) => { ${writer()} });
    });`;
    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])).toEqual([]);
  });

  it('rejects a writer that shares its describe with another test', () => {
    const text = `test.describe('a', () => {
      test.use({ seedConfig: 'newznab_aligned#one' });
      test('writes', async ({ page }) => { ${writer()} });
      test('reads', async ({ page }) => { await page.goto('/'); });
    });`;
    const found = seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }]);

    expect(found).toHaveLength(1);
    expect(found[0]).toContain("seedConfig 'newznab_aligned#one' is used by 2 tests");
  });

  it('rejects a writer whose value is also used in another file', () => {
    const owner = `test.describe('a', () => { test.use({ seedConfig: 'x' }); test('w', async () => { ${writer()} }); });`;
    const other = `test.describe('b', () => { test.use({ seedConfig: 'x' }); test('r', async () => {}); });`;

    expect(seedConfigOwnershipViolations([
      { name: 'a.spec.ts', text: owner }, { name: 'b.spec.ts', text: other },
    ])).toHaveLength(1);
  });

  it('accepts two tests sharing a value when neither writes', () => {
    const text = `test.describe('a', () => {
      test.use({ seedConfig: 'newznab_aligned' });
      test('one', async () => {});
      test('two', async () => {});
    });`;
    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])).toEqual([]);
  });

  it('accepts two writers on different labels of the same fixture', () => {
    const text = `test.describe('a', () => {
      test.describe('first', () => { test.use({ seedConfig: 'newznab_aligned#one' }); test('w1', async () => { ${writer()} }); });
      test.describe('second', () => { test.use({ seedConfig: 'newznab_aligned#two' }); test('w2', async () => { ${writer()} }); });
    });`;
    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])).toEqual([]);
  });

  it('rejects a writer with no seedConfig, which would run on the shared worker', () => {
    const text = `test.describe('a', () => { test('w', async () => { ${writer()} }); });`;
    const found = seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }]);

    expect(found).toHaveLength(1);
    expect(found[0]).toContain('shared default worker');
  });

  it('rejects seedConfig set at the top of a file', () => {
    const text = `test.use({ seedConfig: 'x' }); test('r', async () => {});`;

    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])[0]).toContain('outside a describe');
  });

  it('sees a writer that calls the marker through a helper in the same file', () => {
    const text = `function writes(page) { test.info().annotations.push(...combineGroupWriter()); }
    test.describe('a', () => {
      test.use({ seedConfig: 'x' });
      test('w', async ({ page }) => { writes(page); });
      test('r', async () => {});
    });`;

    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])).toHaveLength(1);
  });

  it('sees a helper that reaches the marker through another helper', () => {
    const text = `const inner = () => combineGroupWriter();
    function outer() { inner(); }
    test.describe('a', () => {
      test.use({ seedConfig: 'x' });
      test('w', async () => { outer(); });
      test('r', async () => {});
    });`;

    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])).toHaveLength(1);
  });

  it('sees a test that carries only the annotation, by name, by constant or as a test option', () => {
    for (const carrier of [
      `test.info().annotations.push({ type: 'writesCombineGroup' });`,
      `test.info().annotations.push({ type: COMBINE_WRITER_ANNOTATION });`,
    ]) {
      const text = `test.describe('a', () => {
        test.use({ seedConfig: 'x' });
        test('w', async () => { ${carrier} });
        test('r', async () => {});
      });`;
      expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }]), carrier).toHaveLength(1);
    }
    const asOption = `test.describe('a', () => {
      test.use({ seedConfig: 'x' });
      test('w', { annotation: { type: 'writesCombineGroup' } }, async () => {});
      test('r', async () => {});
    });`;
    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text: asOption }])).toHaveLength(1);
  });

  it('rejects a seedConfig that is neither a string nor a template', () => {
    const text = `const name = 'x'; test.describe('a', () => { test.use({ seedConfig: name }); test('r', async () => {}); });`;

    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])[0]).toContain('string literal');
  });

  it('accepts a loop whose template gives each iteration its own value, one writer per describe', () => {
    const text = `for (const shape of ['a', 'b']) {
      test.describe(shape, () => {
        test.use({ seedConfig: \`\${shape}#edit\` });
        test('w', async () => { ${writer()} });
      });
    }`;
    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])).toEqual([]);
  });

  it('rejects a second test in a looped describe whose test writes', () => {
    const text = `for (const shape of ['a', 'b']) {
      test.describe(shape, () => {
        test.use({ seedConfig: \`\${shape}#edit\` });
        test('w', async () => { ${writer()} });
        test('r', async () => {});
      });
    }`;
    const found = seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }]);

    expect(found).toHaveLength(1);
    expect(found[0]).toContain('used by 2 tests');
  });

  it('does not count test.skip(condition) inside a test as a second test', () => {
    const text = `test.describe('a', () => {
      test.use({ seedConfig: 'x' });
      test('w', async ({ browserName }) => { test.skip(browserName === 'webkit'); ${writer()} });
    });`;
    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])).toEqual([]);
  });
});

describe('the real E2E suite', () => {
  it('gives every combine-group writer a seedConfig value of its own', () => {
    const directory = path.resolve(__dirname, '../e2e');
    const sources = fs.readdirSync(directory)
      .filter((file) => file.endsWith('.spec.ts'))
      .map((file) => ({ name: `tests/e2e/${file}`, text: fs.readFileSync(path.join(directory, file), 'utf8') }));

    expect(seedConfigOwnershipViolations(sources)).toEqual([]);
  });
});
