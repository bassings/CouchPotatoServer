// @vitest-environment node
/**
 * SEC-005 P3 (AC-A11Y-3, AC-DESIGN-5): the result region every Settings action button shows its answer in.
 *
 * The behaviour (the region is in the accessibility tree before the answer, its text changes once,
 * focus stays) is the E2E suite's, in tests/e2e/settings-jackett-display.spec.ts. This pins the
 * three properties of the markup that behaviour rests on, and that no later edit should trade away
 * quietly: it is a status element (an `<output>`, whose implicit role is status, or an element with
 * `role="status"`), it is never hidden with `x-show` (a live region created together with its text is
 * often not announced), and its text is bound with `x-text`, never `x-html` (the API `error` is shown
 * as text, not parsed as markup).
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const TEMPLATE = path.resolve(__dirname, '../../../couchpotato/ui/templates/partials/settings/field_types.html');

/** The opening tag of the element in the button field that binds `result`. */
function resultRegionTag(): string {
  const html = fs.readFileSync(TEMPLATE, 'utf8');
  const start = html.indexOf(`<template x-if="opt.type === 'button'">`);
  expect(start, 'the button field template was not found').toBeGreaterThanOrEqual(0);
  const block = html.slice(start, html.indexOf('</template>', start));
  const tags = block.match(/<(?:div|output|p|span)\b[^>]*>/g)?.filter((tag) => /x-(text|html)="result"/.test(tag)) ?? [];
  expect(tags, 'exactly one element shows the button result').toHaveLength(1);
  return tags[0];
}

describe('the Settings button result region', () => {
  it('is a status element: an <output>, or an element with role="status"', () => {
    const tag = resultRegionTag();
    expect(/^<output\b/.test(tag) || /\brole="status"/.test(tag), tag).toBe(true);
  });

  it('is never hidden with x-show or x-if, so it is in the page before its text arrives', () => {
    expect(resultRegionTag()).not.toMatch(/\bx-show=/);
    const html = fs.readFileSync(TEMPLATE, 'utf8');
    const start = html.indexOf(`<template x-if="opt.type === 'button'">`);
    const block = html.slice(start, html.indexOf('</template>', start));
    expect(block).not.toMatch(/x-if="[^"]*result/);
  });

  it('binds its text with x-text and never with x-html', () => {
    expect(resultRegionTag()).toMatch(/\bx-text="result"/);
    expect(resultRegionTag()).not.toMatch(/\bx-html=/);
  });

  it('is a polite live region: aria-live is exactly "polite" (not off, not assertive)', () => {
    const tag = resultRegionTag();
    expect(tag.match(/\baria-live="([^"]*)"/)?.[1], tag).toBe('polite');
  });

  it('keeps the danger and success styles', () => {
    expect(resultRegionTag()).toMatch(/text-cp-danger/);
    expect(resultRegionTag()).toMatch(/text-cp-success/);
  });
});
