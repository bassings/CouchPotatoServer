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
