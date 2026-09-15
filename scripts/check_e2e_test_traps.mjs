#!/usr/bin/env node
/** Syntax-aware Playwright false-green checks, consumed by check_test_traps.py. */

import fs from 'node:fs';
import crypto from 'node:crypto';
import * as ts from 'typescript';

const filename = process.argv[2] || 'tests/e2e/input.spec.ts';
const sourceText = fs.readFileSync(0, 'utf8');
const parsedSource = ts.createSourceFile(
  filename,
  sourceText,
  ts.ScriptTarget.Latest,
  true,
  filename.endsWith('.js') ? ts.ScriptKind.JS : ts.ScriptKind.TS,
);
const compilerOptions = { noLib: true, noResolve: true, allowJs: true };
const compilerHost = {
  getSourceFile: requested => requested === filename ? parsedSource : undefined,
  getDefaultLibFileName: () => 'lib.d.ts',
  writeFile: () => {},
  getCurrentDirectory: () => '',
  getDirectories: () => [],
  fileExists: requested => requested === filename,
  readFile: requested => requested === filename ? sourceText : undefined,
  getCanonicalFileName: name => name,
  useCaseSensitiveFileNames: () => true,
  getNewLine: () => '\n',
};
const program = ts.createProgram([filename], compilerOptions, compilerHost);
const source = program.getSourceFile(filename);
if (!source) throw new Error(`TypeScript could not load ${filename}`);
const checker = program.getTypeChecker();

const aliases = new Set();
const guardNames = new Set();
const swallowedPromises = new Set();
const swallowedResponses = new Set();
const waits = [];
const findings = [];

function symbolOf(node) {
  return node && ts.isIdentifier(node) ? checker.getSymbolAtLocation(node) : undefined;
}

function tracks(set, node) {
  const symbol = symbolOf(node);
  return Boolean(symbol && set.has(symbol));
}

function track(set, node) {
  const symbol = symbolOf(node);
  if (symbol) set.add(symbol);
}

function unwrap(node) {
  while (
    node &&
    (ts.isAwaitExpression(node) ||
      ts.isParenthesizedExpression(node) ||
      ts.isAsExpression(node) ||
      ts.isTypeAssertionExpression(node) ||
      ts.isNonNullExpression(node))
  ) {
    node = node.expression;
  }
  return node;
}

function propertyName(expression) {
  expression = unwrap(expression);
  if (ts.isPropertyAccessExpression(expression)) return expression.name.text;
  if (
    ts.isElementAccessExpression(expression) &&
    expression.argumentExpression &&
    (ts.isStringLiteral(expression.argumentExpression) ||
      ts.isNoSubstitutionTemplateLiteral(expression.argumentExpression))
  ) {
    return expression.argumentExpression.text;
  }
  return null;
}

function staticName(node) {
  return node && (ts.isIdentifier(node) || ts.isStringLiteral(node) ||
    ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : null;
}

function isNamedCall(node, name) {
  return ts.isCallExpression(node) && propertyName(node.expression) === name;
}

function isWaitTarget(expression) {
  expression = unwrap(expression);
  if (propertyName(expression) === 'waitForTimeout') return true;
  return ts.isIdentifier(expression) && tracks(aliases, expression);
}

function expressionIsWaitAlias(expression) {
  expression = unwrap(expression);
  if (isWaitTarget(expression)) return true;
  if (!ts.isCallExpression(expression) || propertyName(expression.expression) !== 'bind') {
    return false;
  }
  const target = unwrap(expression.expression).expression;
  return isWaitTarget(target);
}

function collectWaitBinding(name, expression) {
  expression = unwrap(expression);
  if (ts.isIdentifier(name) && expressionIsWaitAlias(expression)) {
    track(aliases, name);
    return;
  }
  if (ts.isObjectBindingPattern(name)) {
    for (const element of name.elements) {
      const key = element.propertyName || element.name;
      if (staticName(key) === 'waitForTimeout') {
        if (ts.isIdentifier(element.name)) track(aliases, element.name);
      }
    }
  }
  if (ts.isObjectLiteralExpression(name)) {
    for (const element of name.properties) {
      if (ts.isPropertyAssignment(element) &&
          staticName(element.name) === 'waitForTimeout' &&
          ts.isIdentifier(element.initializer)) {
        track(aliases, element.initializer);
      } else if (ts.isShorthandPropertyAssignment(element) &&
          element.name.text === 'waitForTimeout') {
        track(aliases, element.name);
      }
    }
  }
}

function isEmptyResult(node) {
  node = unwrap(node);
  if (!node) return false;
  if (node.kind === ts.SyntaxKind.NullKeyword || ts.isVoidExpression(node)) return true;
  if (ts.isIdentifier(node) && node.text === 'undefined') return true;
  if (node.kind === ts.SyntaxKind.FalseKeyword) return true;
  if (ts.isNumericLiteral(node) && Number(node.text) === 0) return true;
  if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) &&
      node.text === '') return true;
  if (ts.isBlock(node)) {
    if (node.statements.length === 0) return true;
    const finalStatement = node.statements.at(-1);
    if (ts.isReturnStatement(finalStatement)) {
      return isEmptyResult(finalStatement.expression);
    }
    // A catch block that completes normally without a final return resolves
    // to undefined even when it logs or performs other side effects.
    return !ts.isThrowStatement(finalStatement);
  }
  return false;
}

function isSwallowedWaitForResponse(expression) {
  expression = unwrap(expression);
  if (!ts.isCallExpression(expression) || propertyName(expression.expression) !== 'catch') {
    return false;
  }
  const caught = unwrap(expression.expression).expression;
  if (!isNamedCall(caught, 'waitForResponse')) return false;
  const handler = expression.arguments[0];
  return Boolean(handler && (ts.isArrowFunction(handler) || ts.isFunctionExpression(handler)) &&
    isEmptyResult(handler.body));
}

function contains(node, predicate) {
  let found = false;
  function visit(child) {
    if (found) return;
    if (predicate(child)) {
      found = true;
      return;
    }
    ts.forEachChild(child, visit);
  }
  visit(node);
  return found;
}

function containsIdentifier(node, symbol) {
  return contains(node, child => ts.isIdentifier(child) && symbolOf(child) === symbol);
}

function isRootExpectCall(child) {
  if (!ts.isCallExpression(child)) return false;
  const callee = unwrap(child.expression);
  if (ts.isIdentifier(callee)) return callee.text === 'expect';
  return ts.isPropertyAccessExpression(callee) &&
    ts.isIdentifier(unwrap(callee.expression)) &&
    unwrap(callee.expression).text === 'expect' &&
    ['poll', 'soft'].includes(callee.name.text);
}

function containsAssertion(node, responseSymbol = null) {
  return contains(node, child => {
    if (!isRootExpectCall(child)) return false;
    return responseSymbol === null ||
      child.arguments.some(argument => containsIdentifier(argument, responseSymbol));
  });
}

function containsClick(node) {
  return contains(node, child =>
    ts.isCallExpression(child) && ['click', 'dblclick'].includes(propertyName(child.expression)));
}

function containsGuardProbe(node) {
  return contains(node, child => {
    if (ts.isIdentifier(child) && tracks(guardNames, child)) return true;
    return ts.isCallExpression(child) && ['isVisible', 'count'].includes(propertyName(child.expression));
  });
}

function isNullish(node) {
  node = unwrap(node);
  return node && (node.kind === ts.SyntaxKind.NullKeyword ||
    (ts.isIdentifier(node) && node.text === 'undefined') || ts.isVoidExpression(node));
}

function guardedResponseName(expression) {
  expression = unwrap(expression);
  if (ts.isIdentifier(expression) && tracks(swallowedResponses, expression)) {
    return symbolOf(expression);
  }
  if (ts.isBinaryExpression(expression)) {
    const left = unwrap(expression.left);
    const right = unwrap(expression.right);
    const isNotEqual = [ts.SyntaxKind.ExclamationEqualsToken,
      ts.SyntaxKind.ExclamationEqualsEqualsToken].includes(expression.operatorToken.kind);
    if (isNotEqual && ts.isIdentifier(left) && tracks(swallowedResponses, left) &&
        isNullish(right)) {
      return symbolOf(left);
    }
    if (isNotEqual && ts.isIdentifier(right) && tracks(swallowedResponses, right) &&
        isNullish(left)) {
      return symbolOf(right);
    }
    if (expression.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
      return guardedResponseName(left) || guardedResponseName(right);
    }
  }
  return null;
}

function absentResponseName(expression) {
  expression = unwrap(expression);
  if (ts.isPrefixUnaryExpression(expression) &&
      expression.operator === ts.SyntaxKind.ExclamationToken) {
    const operand = unwrap(expression.operand);
    if (ts.isIdentifier(operand) && tracks(swallowedResponses, operand)) return symbolOf(operand);
  }
  if (ts.isBinaryExpression(expression)) {
    const isEqual = [ts.SyntaxKind.EqualsEqualsToken,
      ts.SyntaxKind.EqualsEqualsEqualsToken].includes(expression.operatorToken.kind);
    const left = unwrap(expression.left);
    const right = unwrap(expression.right);
    if (isEqual && ts.isIdentifier(left) && tracks(swallowedResponses, left) &&
        isNullish(right)) return symbolOf(left);
    if (isEqual && ts.isIdentifier(right) && tracks(swallowedResponses, right) &&
        isNullish(left)) return symbolOf(right);
  }
  return null;
}

function isOnlyReturn(node) {
  return ts.isReturnStatement(node) ||
    (ts.isBlock(node) && node.statements.length === 1 &&
      ts.isReturnStatement(node.statements[0]));
}

function earlyReturnSkipsAssertion(node) {
  if (!ts.isReturnStatement(node.thenStatement) || !ts.isBlock(node.parent)) return false;
  const index = node.parent.statements.indexOf(node);
  return index >= 0 &&
    node.parent.statements.slice(index + 1).some(statement => containsAssertion(statement));
}

function lineOf(node) {
  return source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
}

function lineText(line) {
  return sourceText.split(/\r?\n/)[line - 1] || '';
}

function testTitleFor(node) {
  for (let current = node; current; current = current.parent) {
    if (!ts.isCallExpression(current)) continue;
    const callee = unwrap(current.expression);
    const isTest = (ts.isIdentifier(callee) && callee.text === 'test') ||
      (ts.isPropertyAccessExpression(callee) && callee.name.text === 'test');
    if (!isTest) continue;
    const title = current.arguments[0];
    if (title && (ts.isStringLiteral(title) || ts.isNoSubstitutionTemplateLiteral(title))) {
      return title.text;
    }
  }
  return '<helper>';
}

function normalizedText(node) {
  return node ? node.getText(source).replace(/\s+/g, ' ').trim() : '';
}

function waitContext(node) {
  let statement = node;
  while (statement.parent && !ts.isStatement(statement)) statement = statement.parent;
  const parent = statement.parent;
  const siblings = parent && ts.isBlock(parent) ? [...parent.statements] : [];
  const index = siblings.indexOf(statement);
  const material = JSON.stringify({
    index,
    statement: normalizedText(statement),
    previous: index > 0 ? normalizedText(siblings[index - 1]) : '',
    next: index >= 0 && index + 1 < siblings.length ? normalizedText(siblings[index + 1]) : '',
  });
  return crypto.createHash('sha256').update(material).digest('hex').slice(0, 16);
}

function collectSwallowedBinding(name, initializer) {
  if (!ts.isIdentifier(name) || !initializer) return;
  if (ts.isAwaitExpression(initializer)) {
    const value = unwrap(initializer.expression);
    if (isSwallowedWaitForResponse(value) ||
        (ts.isIdentifier(value) && tracks(swallowedPromises, value))) {
      track(swallowedResponses, name);
    }
  } else if (isSwallowedWaitForResponse(initializer)) {
    track(swallowedPromises, name);
  }
}

function collectBindings(node) {
  if (ts.isVariableDeclaration(node) && node.initializer) {
    collectWaitBinding(node.name, node.initializer);
    if (contains(node.initializer, child =>
      ts.isCallExpression(child) && ['isVisible', 'count'].includes(propertyName(child.expression)))) {
      if (ts.isIdentifier(node.name)) track(guardNames, node.name);
    }
    collectSwallowedBinding(node.name, node.initializer);
  }
  if (ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      (ts.isIdentifier(node.left) || ts.isObjectLiteralExpression(node.left))) {
    collectWaitBinding(node.left, node.right);
    if (ts.isIdentifier(node.left) && contains(node.right, child =>
      ts.isCallExpression(child) && ['isVisible', 'count'].includes(propertyName(child.expression)))) {
      track(guardNames, node.left);
    }
    collectSwallowedBinding(node.left, node.right);
  }
  ts.forEachChild(node, collectBindings);
}

// Aliases can refer to an earlier alias, so converge before classifying calls.
for (let pass = 0; pass < 3; pass += 1) collectBindings(source);

function visit(node) {
  if (ts.isCallExpression(node) && isWaitTarget(node.expression)) {
    const line = lineOf(node);
    waits.push({
      line,
      argument: node.arguments.map(arg => arg.getText(source)).join(', ').trim(),
      test: testTitleFor(node),
      context: waitContext(node),
      sourceLine: lineText(line),
    });
  }

  if (ts.isIfStatement(node) && containsGuardProbe(node.expression)) {
    const hasExpect = containsAssertion(node.thenStatement) || earlyReturnSkipsAssertion(node);
    const hasClick = containsClick(node.thenStatement);
    const bothAssert = hasExpect && node.elseStatement && containsAssertion(node.elseStatement);
    if (!bothAssert && (hasExpect || hasClick)) {
      findings.push({
        line: lineOf(node),
        kind: hasClick && !hasExpect ? 'click-guard' : 'expect-guard',
        sourceLine: lineText(lineOf(node)),
      });
    }
  }

  const responseName = ts.isIfStatement(node) ? guardedResponseName(node.expression) : null;
  if (ts.isIfStatement(node) && responseName &&
      containsAssertion(node.thenStatement, responseName)) {
    findings.push({ line: lineOf(node), kind: 'swallowed-response', sourceLine: lineText(lineOf(node)) });
  }
  const absentName = ts.isIfStatement(node) ? absentResponseName(node.expression) : null;
  if (ts.isIfStatement(node) && absentName && isOnlyReturn(node.thenStatement) &&
      ts.isBlock(node.parent)) {
    const index = node.parent.statements.indexOf(node);
    if (index >= 0 && node.parent.statements.slice(index + 1)
      .some(statement => containsAssertion(statement, absentName))) {
      findings.push({ line: lineOf(node), kind: 'swallowed-response', sourceLine: lineText(lineOf(node)) });
    }
  }

  if (ts.isBinaryExpression(node)) {
    const operator = node.operatorToken.kind;
    const responseName = operator === ts.SyntaxKind.AmpersandAmpersandToken
      ? guardedResponseName(node.left)
      : operator === ts.SyntaxKind.BarBarToken
        ? absentResponseName(node.left)
        : null;
    if (responseName && containsAssertion(node.right, responseName)) {
      findings.push({ line: lineOf(node), kind: 'swallowed-response', sourceLine: lineText(lineOf(node)) });
    }
  }


  if (ts.isConditionalExpression(node)) {
    const presentName = guardedResponseName(node.condition);
    const absentName = absentResponseName(node.condition);
    const gatedName = presentName || absentName;
    const gatedBranch = presentName ? node.whenTrue : node.whenFalse;
    const otherBranch = presentName ? node.whenFalse : node.whenTrue;
    if (gatedName && containsAssertion(gatedBranch, gatedName) &&
        !containsAssertion(otherBranch)) {
      findings.push({ line: lineOf(node), kind: 'swallowed-response', sourceLine: lineText(lineOf(node)) });
    }
  }

  ts.forEachChild(node, visit);
}
visit(source);

process.stdout.write(JSON.stringify({ waits, findings, parseErrors: source.parseDiagnostics.length }));
