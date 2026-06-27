/**
 * Unit tests for the extracted settings value-resolution logic, imported from
 * the REAL module that partials/settings/scripts.html delegates to.
 */
import { describe, it, expect } from 'vitest';
import {
  getVal,
  findEnabler,
  isEnabledValue,
  isEnabled,
} from '../../../couchpotato/static/scripts/ui/settings-values.js';

describe('getVal', () => {
  it('returns a dirty (unsaved) edit over the saved value', () => {
    const state = { dirty: { 'core.username': 'edited' }, values: { core: { username: 'saved' } } };
    expect(getVal(state, 'core', 'username')).toBe('edited');
  });

  it('falls back to the saved value when not dirty', () => {
    const state = { dirty: {}, values: { core: { username: 'saved' } } };
    expect(getVal(state, 'core', 'username')).toBe('saved');
  });

  it('returns "" for a missing value or section', () => {
    expect(getVal({ dirty: {}, values: {} }, 'core', 'username')).toBe('');
    expect(getVal({ dirty: {}, values: { core: {} } }, 'core', 'missing')).toBe('');
  });

  it('tolerates absent dirty/values objects', () => {
    expect(getVal({}, 'core', 'username')).toBe('');
  });

  it('preserves a dirty value even when it is falsy', () => {
    const state = { dirty: { 'core.flag': false }, values: { core: { flag: true } } };
    expect(getVal(state, 'core', 'flag')).toBe(false);
  });
});

describe('findEnabler', () => {
  it('finds the enabler option', () => {
    const group = { options: [{ type: 'string', name: 'a' }, { type: 'enabler', name: 'enabled' }] };
    expect(findEnabler(group)).toEqual({ type: 'enabler', name: 'enabled' });
  });

  it('returns null when there is no enabler or no options', () => {
    expect(findEnabler({ options: [{ type: 'string', name: 'a' }] })).toBeNull();
    expect(findEnabler({})).toBeNull();
  });
});

describe('isEnabledValue', () => {
  it.each([true, 'True', '1', 1, 'true'])('treats %p as enabled', (v) => {
    expect(isEnabledValue(v)).toBe(true);
  });

  it.each([false, 'False', '0', 0, '', undefined, null, 'no'])('treats %p as disabled', (v) => {
    expect(isEnabledValue(v)).toBe(false);
  });
});

describe('isEnabled', () => {
  const group = {
    section: 'test',
    options: [{ type: 'enabler', name: 'enabled' }, { type: 'string', name: 'other' }],
  };

  it('is enabled when a group has no enabler', () => {
    expect(isEnabled({ dirty: {}, values: {} }, { section: 'g', options: [{ type: 'string', name: 'x' }] })).toBe(true);
  });

  it('reflects the enabler value, dirty taking precedence', () => {
    expect(isEnabled({ dirty: {}, values: {} }, group)).toBe(false);
    expect(isEnabled({ dirty: {}, values: { test: { enabled: true } } }, group)).toBe(true);
    expect(isEnabled({ dirty: {}, values: { test: { enabled: '1' } } }, group)).toBe(true);
    expect(isEnabled({ dirty: { 'test.enabled': false }, values: { test: { enabled: true } } }, group)).toBe(false);
  });
});
