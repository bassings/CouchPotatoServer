// Pure logic functions for category management.
// Extracted from the Alpine component so they can be unit- and mutation-tested.
// Imported by categories.html and tested by tests/unit/ui/category-editor.spec.ts.

/**
 * Map a category API document into a reactive form state object.
 *
 * @param {Object} category  Raw category doc from category.list API
 *                           { _id, _t, order, label, ignored, preferred, required, destination }
 * @returns {{ id: string, label: string, ignored: string, preferred: string,
 *             required: string, destination: string, order: number }}
 */
export function categoryToForm(category) {
  const c = category || {};
  return {
    id:          c._id          || '',
    label:       c.label        || '',
    ignored:     c.ignored      || '',
    preferred:   c.preferred    || '',
    required:    c.required     || '',
    destination: c.destination  || '',
    order:       c.order != null ? Number(c.order) : 999,
  };
}

/**
 * Convert category form state into the payload expected by category.save.
 * Named categoryFormToPayload (not formToPayload) to avoid a barrel re-export
 * collision with profile-editor.js which exports its own formToPayload; an
 * ambiguous star-export makes both undefined on window.CP.ui.
 * Returns an object ready to be serialised as URLSearchParams.
 *
 * Trim is applied at the wire boundary so values aren't stored with surrounding
 * whitespace. `order` is only included for NEW categories (no id) so the backend
 * appends them at the end of the list instead of using its default of 999.
 *
 * @param {Object} formState           As returned / mutated from categoryToForm
 * @param {number} currentCategoryCount  Number of existing categories; used to
 *   assign `order` for NEW categories so they append at the end.
 * @returns {Object}  { id?, label, ignored, preferred, required, destination, order? }
 */
export function categoryFormToPayload(formState, currentCategoryCount = 0) {
  const trim = (v) => (v != null ? String(v).trim() : '');

  const payload = {
    label:       trim(formState && formState.label),
    ignored:     trim(formState && formState.ignored),
    preferred:   trim(formState && formState.preferred),
    required:    trim(formState && formState.required),
    destination: trim(formState && formState.destination),
  };

  if (formState && formState.id) {
    payload.id = formState.id;
  } else {
    // New category: send explicit order so it appends at the end instead of
    // landing at the backend default order=999 which sorts non-deterministically.
    payload.order = currentCategoryCount;
  }

  return payload;
}

/**
 * Validate form state. Returns { valid: boolean, errors: string[] }.
 * Currently only label is required; additional fields may be validated in future.
 *
 * @param {{ label?: string|null } | null} formState
 * @returns {{ valid: boolean, errors: string[] }}
 */
export function validateCategory(formState) {
  const errors = [];

  const label = (formState && formState.label != null) ? String(formState.label).trim() : '';
  if (!label) {
    errors.push('Category name is required.');
  }

  return { valid: errors.length === 0, errors };
}
