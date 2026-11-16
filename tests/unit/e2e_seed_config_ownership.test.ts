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

function seedConfigOf(call: ts.CallExpression): string | null | undefined {
  const [options] = call.arguments;
  if (!options || !ts.isObjectLiteralExpression(options)) return undefined;
  for (const property of options.properties) {
    if (ts.isPropertyAssignment(property) && property.name.getText() === 'seedConfig') {
      return ts.isStringLiteralLike(property.initializer) ? property.initializer.text : null;
    }
  }
  return undefined;
}

function callsWriterMarker(node: ts.Node): boolean {
  let found = false;
  const visit = (child: ts.Node) => {
    if (ts.isCallExpression(child) && ts.isIdentifier(child.expression)
      && child.expression.text === 'combineGroupWriter') found = true;
    ts.forEachChild(child, visit);
  };
  visit(node);
  return found;
}

/** Every violation of the ownership rule across `sources`, as readable lines. */
export function seedConfigOwnershipViolations(sources: Source[]): string[] {
  const violations: string[] = [];
  const byValue = new Map<string, Declared[]>();

  for (const { name, text } of sources) {
    const file = ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const where = (node: ts.Node) => `${name}:${file.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
    const describes: { node: ts.CallExpression; value: string | null }[] = [];
    const declared: { node: ts.CallExpression; writer: boolean; scopes: typeof describes }[] = [];

    const visit = (node: ts.Node, scopes: typeof describes) => {
      let inner = scopes;
      if (ts.isCallExpression(node)) {
        if (isDescribe(node)) {
          const scope = { node, value: undefined as unknown as string | null };
          inner = [...scopes, scope];
          describes.push(scope);
        } else if (isTestUse(node) && seedConfigOf(node) !== undefined) {
          const value = seedConfigOf(node) as string | null;
          const owner = scopes[scopes.length - 1];
          if (!owner) violations.push(`${where(node)}: seedConfig is set outside a describe, so it would apply to the whole file`);
          else if (value === null) violations.push(`${where(node)}: seedConfig must be a string literal`);
          else owner.value = value;
        } else if (isTestDeclaration(node)) {
          declared.push({ node, writer: callsWriterMarker(node), scopes });
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

  it('rejects a seedConfig that is not a string literal', () => {
    const text = `const name = 'x'; test.describe('a', () => { test.use({ seedConfig: name }); test('r', async () => {}); });`;

    expect(seedConfigOwnershipViolations([{ name: 'a.spec.ts', text }])[0]).toContain('string literal');
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
