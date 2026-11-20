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
  takeRow,
  restoreRow,
  shiftMarksBack,
  rowRemovedLine,
  rowRemovedAnnouncement,
  rowRestoredAnnouncement,
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

describe('taking a row out of a combined field, and putting it back', () => {
  const rows = [
    ['1', 'https://placeholder-one.invalid/api', 'placeholder-key-one', '5', 'tag-one'],
    ['0', 'https://placeholder-two.invalid/api', 'placeholder-key-two', '10', ''],
    ['1', 'https://placeholder-three.invalid/api', 'placeholder-key-three', '15', 'tag-three'],
  ];

  it('takes the row at the index and keeps every cell of it, hidden columns included', () => {
    const taken = takeRow(rows, 1);

    expect(taken.rows).toEqual([rows[0], rows[2]]);
    expect(taken.removal).toEqual({ index: 1, cells: rows[1] });
  });

  it('does not change the rows it was given, and keeps its own copy of the cells', () => {
    const before = JSON.stringify(rows);
    const taken = takeRow(rows, 0);

    taken.removal.cells[1] = 'changed afterwards';

    expect(JSON.stringify(rows)).toBe(before);
    expect(rows[0][1]).toBe('https://placeholder-one.invalid/api');
  });

  for (const index of [0, 1, 2]) {
    it(`puts row ${index + 1} back at index ${index}, every cell as it was`, () => {
      const taken = takeRow(rows, index);

      expect(restoreRow(taken.rows, taken.removal)).toEqual(rows);
    });
  }

  it('puts the row back at the end when the index is past the rows that are left', () => {
    expect(restoreRow([rows[0]], { index: 5, cells: rows[2] })).toEqual([rows[0], rows[2]]);
  });

  it('puts back a copy: editing the restored row does not touch the held removal', () => {
    const taken = takeRow(rows, 1);
    const restored = restoreRow(taken.rows, taken.removal);

    restored[1][2] = 'changed afterwards';

    expect(taken.removal.cells[2]).toBe('placeholder-key-two');
  });
});

describe('moving the refusal marks back after a row returns', () => {
  const entry = (row: number, column = 'host') => ({ row, column, reason: 'comma', message: 'unused' });

  it('moves the marks on and below the returning index down by one, and leaves the ones above alone', () => {
    const moved = shiftMarksBack([entry(0), entry(1), entry(2, 'api_key')], 1);

    expect(moved.map((mark: any) => [mark.row, mark.column])).toEqual([[0, 'host'], [2, 'host'], [3, 'api_key']]);
  });

  it('does not change the list it was given', () => {
    const marks = [entry(1)];

    shiftMarksBack(marks, 0);

    expect(marks[0].row).toBe(1);
  });
});

describe('what the removal line says and what a screen reader is told', () => {
  it('says which row went and offers nothing else', () => {
    expect(rowRemovedLine(0)).toBe('Row 1 removed.');
    expect(rowRemovedLine(2)).toBe('Row 3 removed.');
  });

  it('announces the removal with the way back, and the return plainly', () => {
    expect(rowRemovedAnnouncement(1)).toBe('Row 2 removed. Undo is available.');
    expect(rowRestoredAnnouncement(1)).toBe('Row 2 restored.');
  });
});
