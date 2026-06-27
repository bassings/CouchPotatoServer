/**
 * Unit tests for the extracted settings description builder, imported from the
 * REAL module that partials/settings/scripts.html delegates to (DEF-003 area).
 */
import { describe, it, expect } from 'vitest';
import { buildDescription } from '../../../couchpotato/static/scripts/ui/settings-help.js';

describe('buildDescription', () => {
  it('returns the API description when there is no help entry', () => {
    expect(buildDescription(null, 'api text')).toBe('api text');
    expect(buildDescription(undefined, 'api text')).toBe('api text');
  });

  it('returns "" when there is neither help nor description', () => {
    expect(buildDescription(null, undefined)).toBe('');
  });

  it('prefers the help description over the API description', () => {
    expect(buildDescription({ description: 'help text' }, 'api text')).toBe('help text');
  });

  it('falls back to the API description when help.description is empty', () => {
    expect(buildDescription({ description: '' }, 'api text')).toBe('api text');
  });

  it('appends whenToChange, defaultNote and tip when present', () => {
    const html = buildDescription(
      { description: 'base', whenToChange: 'rarely', defaultNote: 'def', tip: 'careful' },
      'api'
    );
    expect(html).toContain('base');
    expect(html).toContain('When to change:</span> rarely');
    expect(html).toContain('💡 def');
    expect(html).toContain('Tip:</span> careful');
  });

  it('omits sections that are absent', () => {
    const html = buildDescription({ description: 'base', tip: 'only tip' }, 'api');
    expect(html).toContain('base');
    expect(html).not.toContain('When to change');
    expect(html).not.toContain('💡');
    expect(html).toContain('Tip:</span> only tip');
  });
});
