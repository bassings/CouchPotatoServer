// Pure value-resolution logic for the settings panel (partials/settings/scripts.html).
// Extracted from the inline `settingsPanel()` Alpine component so it can be unit-
// and mutation-tested. The component delegates getVal / isEnabled here, keeping
// the DOM/persistence side effects (debounceSave, fetch) in the template.

/**
 * Resolve a setting's current value: an unsaved (dirty) edit wins over the
 * loaded value; missing values resolve to ''.
 * @param {{dirty?: Object, values?: Object}} state
 * @param {string} section
 * @param {string} name
 */
export function getVal(state, section, name) {
  const key = section + '.' + name;
  const dirty = state.dirty || {};
  if (key in dirty) return dirty[key];
  const values = state.values || {};
  return values[section]?.[name] ?? '';
}

/**
 * Find the "enabler" option within a settings group, if any.
 * @param {{options?: {type: string, name: string}[]}} group
 * @returns {{type: string, name: string}|null}
 */
export function findEnabler(group) {
  return (group.options || []).find(o => o.type === 'enabler') || null;
}

/**
 * Coerce a raw enabler value to a boolean using the same truthy set the UI uses.
 * @param {*} val
 * @returns {boolean}
 */
export function isEnabledValue(val) {
  return val === true || val === 'True' || val === '1' || val === 1 || val === 'true';
}

/**
 * Whether a group is enabled: groups without an enabler are always enabled;
 * otherwise the enabler's resolved value decides.
 * @param {{dirty?: Object, values?: Object}} state
 * @param {{section: string, options?: {type: string, name: string}[]}} group
 * @returns {boolean}
 */
export function isEnabled(state, group) {
  const enabler = findEnabler(group);
  if (!enabler) return true;
  return isEnabledValue(getVal(state, group.section, enabler.name));
}

// ── Removing a row from a combined field, and taking the removal back ──
// Pure, so the question "where does the row go back, and with what" is answered
// without a page. The panel (scripts.html) holds the removal and calls these.

/**
 * Take the row at `index` out of `rows`. Returns the rows that are left and the
 * removal: the index and a COPY of every cell of the row, hidden columns
 * included, so nothing later done to the rows can change what is put back.
 * @param {string[][]} rows
 * @param {number} index
 * @returns {{rows: string[][], removal: {index: number, cells: string[]}}}
 */
export function takeRow(rows, index) {
  return {
    rows: rows.filter((_, position) => position !== index),
    removal: { index, cells: [...rows[index]] },
  };
}

/**
 * Put a removed row back at its own index (the end, if fewer rows are left than
 * that). Returns new rows; the cells put back are a copy of the removal's.
 * @param {string[][]} rows
 * @param {{index: number, cells: string[]}} removal
 * @returns {string[][]}
 */
export function restoreRow(rows, removal) {
  const at = Math.min(removal.index, rows.length);
  return [...rows.slice(0, at), [...removal.cells], ...rows.slice(at)];
}

/**
 * The refusal marks after a row has returned at `index`: a mark on that row or
 * a later one now names the row one further down. Marks keep every other field.
 * @param {{row: number}[]} refusal
 * @param {number} index
 */
export function shiftMarksBack(refusal, index) {
  return refusal.map(entry => (entry.row >= index ? { ...entry, row: entry.row + 1 } : entry));
}

/** The line shown beside Undo. Names the row by number only, never by a value. */
export function rowRemovedLine(index) {
  return 'Row ' + (index + 1) + ' removed.';
}

/** What a screen reader is told once a row is removed. */
export function rowRemovedAnnouncement(index) {
  return rowRemovedLine(index) + ' Undo is available.';
}

/** What a screen reader is told once Undo has put the row back. */
export function rowRestoredAnnouncement(index) {
  return 'Row ' + (index + 1) + ' restored.';
}
