/**
 * Unit tests for the category-editor pure logic module.
 * Written FIRST (TDD) before the implementation — tests describe the contract.
 * The module is exercised by vitest and Stryker mutation testing.
 */
import { describe, it, expect } from 'vitest';
import {
  categoryToForm,
  categoryFormToPayload,
  validateCategory,
} from '../../../couchpotato/static/scripts/ui/category-editor.js';

// ─── Fixtures ────────────────────────────────────────────────────────────────

const CATEGORY_DOC = {
  _id: 'cat001',
  _t: 'category',
  order: 2,
  label: 'Horror',
  ignored: 'dubbed,swesub',
  preferred: 'Blu-ray,DTS',
  required: 'DTS',
  destination: '/media/horror',
};

// ─── categoryToForm ───────────────────────────────────────────────────────────

describe('categoryToForm', () => {
  it('maps all category fields into form state', () => {
    const form = categoryToForm(CATEGORY_DOC);
    expect(form.id).toBe('cat001');
    expect(form.label).toBe('Horror');
    expect(form.ignored).toBe('dubbed,swesub');
    expect(form.preferred).toBe('Blu-ray,DTS');
    expect(form.required).toBe('DTS');
    expect(form.destination).toBe('/media/horror');
  });

  it('preserves order from the document', () => {
    const form = categoryToForm(CATEGORY_DOC);
    expect(form.order).toBe(2);
  });

  it('defaults missing string fields to empty string', () => {
    const doc = { _id: 'x', label: 'Test' };
    const form = categoryToForm(doc);
    expect(form.ignored).toBe('');
    expect(form.preferred).toBe('');
    expect(form.required).toBe('');
    expect(form.destination).toBe('');
  });

  it('defaults id to empty string when _id is missing', () => {
    const doc = { label: 'Test' };
    const form = categoryToForm(doc);
    expect(form.id).toBe('');
  });

  it('defaults order to 999 when order is missing', () => {
    const doc = { _id: 'x', label: 'Test' };
    const form = categoryToForm(doc);
    expect(form.order).toBe(999);
  });

  it('preserves order=0 (not treated as missing)', () => {
    const doc = { ...CATEGORY_DOC, order: 0 };
    const form = categoryToForm(doc);
    expect(form.order).toBe(0);
  });

  it('defaults order to 999 when order is null', () => {
    const doc = { ...CATEGORY_DOC, order: null };
    const form = categoryToForm(doc);
    expect(form.order).toBe(999);
  });

  it('handles completely empty document', () => {
    const form = categoryToForm({});
    expect(form.id).toBe('');
    expect(form.label).toBe('');
    expect(form.ignored).toBe('');
    expect(form.preferred).toBe('');
    expect(form.required).toBe('');
    expect(form.destination).toBe('');
    expect(form.order).toBe(999);
  });

  it('handles null input gracefully', () => {
    const form = categoryToForm(null);
    expect(form.id).toBe('');
    expect(form.label).toBe('');
    expect(form.order).toBe(999);
  });

  it('handles undefined input gracefully', () => {
    const form = categoryToForm(undefined);
    expect(form.id).toBe('');
    expect(form.label).toBe('');
    expect(form.order).toBe(999);
  });
});

// ─── formToPayload ────────────────────────────────────────────────────────────

describe('categoryFormToPayload', () => {
  it('builds correct save payload from form state', () => {
    const form = categoryToForm(CATEGORY_DOC);
    const payload = categoryFormToPayload(form);
    expect(payload.id).toBe('cat001');
    expect(payload.label).toBe('Horror');
    expect(payload.ignored).toBe('dubbed,swesub');
    expect(payload.preferred).toBe('Blu-ray,DTS');
    expect(payload.required).toBe('DTS');
    expect(payload.destination).toBe('/media/horror');
  });

  it('trims leading/trailing whitespace from label', () => {
    const form = { ...categoryToForm(CATEGORY_DOC), label: '  Horror  ' };
    const payload = categoryFormToPayload(form);
    expect(payload.label).toBe('Horror');
  });

  it('trims whitespace from all string fields', () => {
    const form = {
      ...categoryToForm(CATEGORY_DOC),
      label: '  Horror  ',
      ignored: '  dubbed  ',
      preferred: '  Blu-ray  ',
      required: '  DTS  ',
      destination: '  /media/horror  ',
    };
    const payload = categoryFormToPayload(form);
    expect(payload.label).toBe('Horror');
    expect(payload.ignored).toBe('dubbed');
    expect(payload.preferred).toBe('Blu-ray');
    expect(payload.required).toBe('DTS');
    expect(payload.destination).toBe('/media/horror');
  });

  it('omits id when form id is empty string (new category)', () => {
    const form = { ...categoryToForm(CATEGORY_DOC), id: '' };
    const payload = categoryFormToPayload(form);
    expect(payload.id).toBeUndefined();
  });

  it('omits id when form id is null (new category)', () => {
    const form = { ...categoryToForm(CATEGORY_DOC), id: null };
    const payload = categoryFormToPayload(form);
    expect(payload.id).toBeUndefined();
  });

  it('omits id when form id is undefined (new category)', () => {
    const form = { ...categoryToForm(CATEGORY_DOC), id: undefined };
    const payload = categoryFormToPayload(form);
    expect(payload.id).toBeUndefined();
    expect(payload.order).toBeDefined();
  });

  it('treats a non-empty id (incl. numeric 0) as an edit, not a new category', () => {
    // Guards the "edit vs new" invariant: not a bare truthy check, so a
    // hypothetical numeric id=0 routes as an edit (id sent, no order).
    const payload = categoryFormToPayload({ ...categoryToForm(CATEGORY_DOC), id: 0 });
    expect(payload.id).toBe(0);
    expect(payload.order).toBeUndefined();
  });

  it('assigns order = currentCount for a NEW category (not backend default 999)', () => {
    const form = { ...categoryToForm(CATEGORY_DOC), id: '' };
    const payload = categoryFormToPayload(form, 5);
    expect(payload.order).toBe(5);
  });

  it('defaults order to 0 for a new category when count is omitted', () => {
    const form = { ...categoryToForm(CATEGORY_DOC), id: '' };
    const payload = categoryFormToPayload(form);
    expect(payload.order).toBe(0);
  });

  it('does NOT set order when editing an existing category (backend preserves stored order)', () => {
    const form = categoryToForm(CATEGORY_DOC); // has id
    const payload = categoryFormToPayload(form, 5);
    expect(payload.order).toBeUndefined();
  });

  it('coalesces empty string fields to empty string (not undefined)', () => {
    const form = { id: '', label: 'Test', ignored: '', preferred: '', required: '', destination: '' };
    const payload = categoryFormToPayload(form);
    expect(payload.ignored).toBe('');
    expect(payload.preferred).toBe('');
    expect(payload.required).toBe('');
    expect(payload.destination).toBe('');
  });

  it('returns a safe empty payload for null formState', () => {
    const payload = categoryFormToPayload(null, 0);
    expect(payload.label).toBe('');
    expect(payload.id).toBeUndefined();
    expect(payload.order).toBe(0);
  });

  it('returns a safe empty payload for undefined formState', () => {
    const payload = categoryFormToPayload(undefined, 3);
    expect(payload.label).toBe('');
    expect(payload.id).toBeUndefined();
    expect(payload.order).toBe(3);
  });
});

// ─── validateCategory ─────────────────────────────────────────────────────────

describe('validateCategory', () => {
  const validForm = {
    id: '',
    label: 'Horror',
    ignored: '',
    preferred: '',
    required: '',
    destination: '',
  };

  it('returns valid for a correctly filled form', () => {
    const r = validateCategory(validForm);
    expect(r.valid).toBe(true);
    expect(r.errors).toHaveLength(0);
  });

  it('rejects empty label', () => {
    const r = validateCategory({ ...validForm, label: '' });
    expect(r.valid).toBe(false);
    expect(r.errors.some(e => e.toLowerCase().includes('name') || e.toLowerCase().includes('label'))).toBe(true);
  });

  it('rejects whitespace-only label', () => {
    const r = validateCategory({ ...validForm, label: '   ' });
    expect(r.valid).toBe(false);
    expect(r.errors.length).toBeGreaterThan(0);
  });

  it('rejects null label', () => {
    const r = validateCategory({ ...validForm, label: null });
    expect(r.valid).toBe(false);
  });

  it('rejects missing label entirely', () => {
    const r = validateCategory({ id: '', ignored: '', preferred: '', required: '', destination: '' });
    expect(r.valid).toBe(false);
  });

  it('accepts label with leading/trailing whitespace (trim is the payload responsibility)', () => {
    // Validation trims to check emptiness, but a label like " Horror " passes —
    // trimming for storage is formToPayload's job.
    const r = validateCategory({ ...validForm, label: '  Horror  ' });
    expect(r.valid).toBe(true);
  });

  it('does not require any of the optional fields', () => {
    const r = validateCategory({ label: 'Test' });
    expect(r.valid).toBe(true);
  });

  it('returns errors array on null/undefined formState', () => {
    const r = validateCategory(null);
    expect(r.valid).toBe(false);
    expect(r.errors.length).toBeGreaterThan(0);
  });

  it('returns errors array on empty object', () => {
    const r = validateCategory({});
    expect(r.valid).toBe(false);
  });

  it('accumulates multiple errors (future-proof: only label required now, but returns array)', () => {
    const r = validateCategory({ label: '' });
    expect(Array.isArray(r.errors)).toBe(true);
    expect(r.errors.length).toBeGreaterThan(0); // at minimum the label error must be present
  });
});
