/**
 * Unit tests for the profile-editor pure logic module.
 * Written FIRST (TDD) before the implementation — tests describe the contract.
 * The module is exercised by vitest and Stryker mutation testing.
 */
import { describe, it, expect } from 'vitest';
import {
  profileToForm,
  formToPayload,
  addQuality,
  removeQuality,
  moveQuality,
  validateProfile,
} from '../../../couchpotato/static/scripts/ui/profile-editor.js';

// ─── Fixtures ────────────────────────────────────────────────────────────────

const QUALITIES = [
  { identifier: '720p',  label: '720p',   allow_3d: true },
  { identifier: '1080p', label: '1080p',  allow_3d: true },
  { identifier: 'dvdrip',label: 'DVD-Rip',allow_3d: false },
];

const PROFILE_DOC = {
  _id: 'abc123',
  label: 'HD',
  order: 1,
  core: false,
  minimum_score: 1,
  qualities:  ['720p', '1080p'],
  finish:     [true,   false],
  '3d':       [false,  false],
  wait_for:   [0, 0],
  stop_after: [0, 0],
};

// ─── profileToForm ────────────────────────────────────────────────────────────

describe('profileToForm', () => {
  it('maps profile fields into form state', () => {
    const form = profileToForm(PROFILE_DOC, QUALITIES);
    expect(form.id).toBe('abc123');
    expect(form.label).toBe('HD');
    expect(form.minimumScore).toBe(1);
    expect(form.waitFor).toBe(0);
    expect(form.stopAfter).toBe(0);
  });

  it('builds types array from parallel arrays', () => {
    const form = profileToForm(PROFILE_DOC, QUALITIES);
    expect(form.types).toHaveLength(2);
    expect(form.types[0]).toMatchObject({ qualityId: '720p', finish: true,  is3d: false });
    expect(form.types[1]).toMatchObject({ qualityId: '1080p', finish: false, is3d: false });
  });

  it('enriches types with quality metadata', () => {
    const form = profileToForm(PROFILE_DOC, QUALITIES);
    expect(form.types[0].qualityLabel).toBe('720p');
    expect(form.types[0].allow3d).toBe(true);
    expect(form.types[2]).toBeUndefined();
  });

  it('handles unknown quality identifier gracefully', () => {
    const doc = { ...PROFILE_DOC, qualities: ['unknown-q'], finish: [true], '3d': [false] };
    const form = profileToForm(doc, QUALITIES);
    expect(form.types[0].qualityId).toBe('unknown-q');
    expect(form.types[0].qualityLabel).toBe('unknown-q');
    expect(form.types[0].allow3d).toBe(false);
  });

  it('handles missing 3d array (defaults to false)', () => {
    const doc = { ...PROFILE_DOC };
    delete doc['3d'];
    const form = profileToForm(doc, QUALITIES);
    expect(form.types[0].is3d).toBe(false);
    expect(form.types[1].is3d).toBe(false);
  });

  it('handles empty qualities array', () => {
    const doc = { ...PROFILE_DOC, qualities: [], finish: [], '3d': [], wait_for: [], stop_after: [] };
    const form = profileToForm(doc, QUALITIES);
    expect(form.types).toHaveLength(0);
  });

  it('returns waitFor=0 when wait_for array is empty', () => {
    const doc = { ...PROFILE_DOC, wait_for: [], stop_after: [] };
    const form = profileToForm(doc, QUALITIES);
    expect(form.waitFor).toBe(0);
    expect(form.stopAfter).toBe(0);
  });

  it('reads waitFor from first element of wait_for array', () => {
    const doc = { ...PROFILE_DOC, wait_for: [3, 3], stop_after: [7, 7] };
    const form = profileToForm(doc, QUALITIES);
    expect(form.waitFor).toBe(3);
    expect(form.stopAfter).toBe(7);
  });
});

// ─── formToPayload ────────────────────────────────────────────────────────────

describe('formToPayload', () => {
  it('builds correct save payload from form state', () => {
    const form = profileToForm(PROFILE_DOC, QUALITIES);
    const payload = formToPayload(form);
    expect(payload.id).toBe('abc123');
    expect(payload.label).toBe('HD');
    expect(payload.minimum_score).toBe(1);
    expect(payload.wait_for).toBe(0);
    expect(payload.stop_after).toBe(0);
    expect(payload.types).toHaveLength(2);
  });

  it('maps types with integer finish and 3d flags', () => {
    const form = profileToForm(PROFILE_DOC, QUALITIES);
    const payload = formToPayload(form);
    expect(payload.types[0]).toMatchObject({ quality: '720p',  finish: 1, '3d': 0 });
    expect(payload.types[1]).toMatchObject({ quality: '1080p', finish: 0, '3d': 0 });
  });

  it('omits id when not present (new profile)', () => {
    const form = { ...profileToForm(PROFILE_DOC, QUALITIES), id: '' };
    const payload = formToPayload(form);
    expect(payload.id).toBeUndefined();
  });

  it('omits id when null', () => {
    const form = { ...profileToForm(PROFILE_DOC, QUALITIES), id: null };
    const payload = formToPayload(form);
    expect(payload.id).toBeUndefined();
  });

  it('round-trips a profile with 3D qualities', () => {
    const doc = { ...PROFILE_DOC, '3d': [true, false] };
    const form = profileToForm(doc, QUALITIES);
    const payload = formToPayload(form);
    expect(payload.types[0]['3d']).toBe(1);
    expect(payload.types[1]['3d']).toBe(0);
  });

  it('assigns order = current profile count for a NEW profile (not backend default 999)', () => {
    const form = { ...profileToForm(PROFILE_DOC, QUALITIES), id: '' };
    const payload = formToPayload(form, 7);
    expect(payload.order).toBe(7);
  });

  it('does NOT set order when editing an existing profile (backend preserves stored order)', () => {
    const form = profileToForm(PROFILE_DOC, QUALITIES); // has id
    const payload = formToPayload(form, 7);
    expect(payload.order).toBeUndefined();
  });

  it('defaults order to 0 for a new profile when count is omitted', () => {
    const form = { ...profileToForm(PROFILE_DOC, QUALITIES), id: '' };
    const payload = formToPayload(form);
    expect(payload.order).toBe(0);
  });

  it('trims leading/trailing whitespace from the label at the wire boundary', () => {
    const form = { ...profileToForm(PROFILE_DOC, QUALITIES), label: '  HD  ' };
    const payload = formToPayload(form);
    expect(payload.label).toBe('HD');
  });

  it('coalesces NaN numeric fields (cleared x-model.number) to defaults, never "NaN"', () => {
    const form = { ...profileToForm(PROFILE_DOC, QUALITIES), waitFor: NaN, stopAfter: NaN, minimumScore: NaN };
    const payload = formToPayload(form);
    expect(payload.wait_for).toBe(0);
    expect(payload.stop_after).toBe(0);
    expect(payload.minimum_score).toBe(1);
    expect(Number.isNaN(payload.wait_for)).toBe(false);
  });
});

// ─── addQuality ───────────────────────────────────────────────────────────────

describe('addQuality', () => {
  it('appends a new quality', () => {
    const types = [{ qualityId: '720p', finish: true, is3d: false }];
    const result = addQuality(types, '1080p');
    expect(result).toHaveLength(2);
    expect(result[1].qualityId).toBe('1080p');
    expect(result[1].finish).toBe(false);
    expect(result[1].is3d).toBe(false);
  });

  it('falls back to the raw identifier for label and allow3d=false when no meta is given', () => {
    const result = addQuality([], 'brrip');
    expect(result[0].qualityLabel).toBe('brrip');
    expect(result[0].allow3d).toBe(false);
  });

  it('derives qualityLabel and allow3d from the passed quality metadata (pure, no caller patch)', () => {
    const result = addQuality([], 'brrip', { label: 'Blu-Ray Rip', allow_3d: true });
    expect(result[0].qualityLabel).toBe('Blu-Ray Rip');
    expect(result[0].allow3d).toBe(true);
  });

  it('does not add a duplicate quality', () => {
    const types = [{ qualityId: '720p', finish: true, is3d: false }];
    const result = addQuality(types, '720p');
    expect(result).toHaveLength(1);
  });

  it('does not mutate the input array', () => {
    const types = [{ qualityId: '720p', finish: true, is3d: false }];
    addQuality(types, '1080p');
    expect(types).toHaveLength(1);
  });

  it('first quality always gets finish=true', () => {
    const types = [];
    const result = addQuality(types, '720p');
    expect(result[0].finish).toBe(true);
  });

  it('subsequent qualities get finish=false', () => {
    const types = [{ qualityId: '720p', finish: true, is3d: false }];
    const result = addQuality(types, '1080p');
    expect(result[1].finish).toBe(false);
  });

  it('rejects empty string qualityId', () => {
    const types = [];
    const result = addQuality(types, '');
    expect(result).toHaveLength(0);
  });

  it('rejects null qualityId', () => {
    const types = [];
    const result = addQuality(types, null);
    expect(result).toHaveLength(0);
  });
});

// ─── removeQuality ────────────────────────────────────────────────────────────

describe('removeQuality', () => {
  const types = [
    { qualityId: '720p',  finish: true,  is3d: false },
    { qualityId: '1080p', finish: false, is3d: false },
    { qualityId: 'dvdrip',finish: false, is3d: false },
  ];

  it('removes the item at the given index', () => {
    const result = removeQuality(types, 1);
    expect(result).toHaveLength(2);
    expect(result[0].qualityId).toBe('720p');
    expect(result[1].qualityId).toBe('dvdrip');
  });

  it('removes the first item', () => {
    const result = removeQuality(types, 0);
    expect(result[0].qualityId).toBe('1080p');
  });

  it('removes the last item', () => {
    const result = removeQuality(types, 2);
    expect(result).toHaveLength(2);
    expect(result[1].qualityId).toBe('1080p');
  });

  it('does not mutate the input array', () => {
    removeQuality(types, 0);
    expect(types).toHaveLength(3);
  });

  it('returns same array for out-of-range index', () => {
    const result = removeQuality(types, 99);
    expect(result).toHaveLength(3);
  });

  it('returns same array for negative index (guards the < 0 branch)', () => {
    const result = removeQuality(types, -1);
    expect(result).toHaveLength(3);
    expect(result[0].qualityId).toBe(types[0].qualityId);
  });

  it('returns empty array when removing the only element', () => {
    const single = [{ qualityId: '720p', finish: true, is3d: false }];
    const result = removeQuality(single, 0);
    expect(result).toHaveLength(0);
  });

  it('promotes new first item to finish=true after removal of index 0', () => {
    const result = removeQuality(types, 0);
    expect(result[0].finish).toBe(true);
  });
});

// ─── moveQuality ─────────────────────────────────────────────────────────────

describe('moveQuality', () => {
  const types = [
    { qualityId: '2160p', finish: true,  is3d: false },
    { qualityId: '1080p', finish: false, is3d: false },
    { qualityId: '720p',  finish: false, is3d: false },
  ];

  it('moves an item up', () => {
    const result = moveQuality(types, 1, 'up');
    expect(result[0].qualityId).toBe('1080p');
    expect(result[1].qualityId).toBe('2160p');
    expect(result[2].qualityId).toBe('720p');
  });

  it('moves an item down', () => {
    const result = moveQuality(types, 1, 'down');
    expect(result[0].qualityId).toBe('2160p');
    expect(result[1].qualityId).toBe('720p');
    expect(result[2].qualityId).toBe('1080p');
  });

  it('clamps at the top — moving index 0 up is a no-op', () => {
    const result = moveQuality(types, 0, 'up');
    expect(result[0].qualityId).toBe('2160p');
  });

  it('clamps at the bottom — moving last item down is a no-op', () => {
    const result = moveQuality(types, 2, 'down');
    expect(result[2].qualityId).toBe('720p');
  });

  it('does not mutate the input array', () => {
    moveQuality(types, 1, 'up');
    expect(types[0].qualityId).toBe('2160p');
  });

  it('preserves finish=true on position 0 after move-up brings new item to front', () => {
    const result = moveQuality(types, 1, 'up');
    expect(result[0].finish).toBe(true);
    expect(result[1].finish).toBe(false);
  });

  it('moving index 0 DOWN resets the displaced first item finish=false and promotes the new first', () => {
    // down-path of displacedFromFirst: old index-0 item lands at index 1 and
    // must lose its position-forced finish=true; new first item gets finish=true.
    const result = moveQuality(types, 0, 'down');
    expect(result[0].qualityId).toBe('1080p'); // new first
    expect(result[0].finish).toBe(true);
    expect(result[1].qualityId).toBe('2160p'); // displaced old-first
    expect(result[1].finish).toBe(false);
  });

  it('KNOWN LIMITATION: a user-set finish=true is cleared once the item leaves position 0', () => {
    // Start: A(forced finish), B(user-set finish), C. Moving A down promotes B
    // to position 0 (finish stays true — now position-forced). Moving B back
    // down then clears its finish, even though the user had set it. Documented
    // and accepted; this test guards the behaviour so a refactor must be explicit.
    const withUserFinish = [
      { qualityId: 'A', finish: true,  is3d: false },
      { qualityId: 'B', finish: true,  is3d: false },
      { qualityId: 'C', finish: false, is3d: false },
    ];
    const step1 = moveQuality(withUserFinish, 0, 'down'); // [B, A, C]
    expect(step1[0].qualityId).toBe('B');
    expect(step1[0].finish).toBe(true);  // position-forced at index 0
    const step2 = moveQuality(step1, 0, 'down'); // [A, B, C]
    expect(step2[1].qualityId).toBe('B');
    expect(step2[1].finish).toBe(false); // user-set finish silently cleared
  });
});

// ─── validateProfile ─────────────────────────────────────────────────────────

describe('validateProfile', () => {
  const validForm = {
    label: 'Best',
    types: [
      { qualityId: '720p',  finish: true, is3d: false },
      { qualityId: '1080p', finish: false, is3d: false },
    ],
  };

  it('returns valid for a correct form', () => {
    const r = validateProfile(validForm);
    expect(r.valid).toBe(true);
    expect(r.errors).toHaveLength(0);
  });

  it('rejects empty label', () => {
    const r = validateProfile({ ...validForm, label: '' });
    expect(r.valid).toBe(false);
    expect(r.errors.some(e => e.includes('name'))).toBe(true);
  });

  it('rejects whitespace-only label', () => {
    const r = validateProfile({ ...validForm, label: '   ' });
    expect(r.valid).toBe(false);
    expect(r.errors.some(e => e.includes('name'))).toBe(true);
  });

  it('rejects zero qualities', () => {
    const r = validateProfile({ ...validForm, types: [] });
    expect(r.valid).toBe(false);
    expect(r.errors.some(e => e.includes('quality') || e.includes('least'))).toBe(true);
  });

  it('accepts exactly one quality', () => {
    const r = validateProfile({ ...validForm, types: [{ qualityId: '720p', finish: true, is3d: false }] });
    expect(r.valid).toBe(true);
  });

  it('rejects minimumScore below 1', () => {
    const r = validateProfile({ ...validForm, minimumScore: 0 });
    expect(r.valid).toBe(false);
    expect(r.errors.some(e => e.includes('Minimum score'))).toBe(true);
  });

  it('accepts minimumScore of exactly 1', () => {
    const r = validateProfile({ ...validForm, minimumScore: 1 });
    expect(r.valid).toBe(true);
  });

  it('rejects negative waitFor and stopAfter', () => {
    const r = validateProfile({ ...validForm, waitFor: -5, stopAfter: -1 });
    expect(r.valid).toBe(false);
    expect(r.errors.some(e => e.includes('Wait'))).toBe(true);
    expect(r.errors.some(e => e.includes('Keep searching'))).toBe(true);
  });

  it('ignores numeric bounds when fields are absent (backwards compatible)', () => {
    const r = validateProfile(validForm); // no numeric fields
    expect(r.valid).toBe(true);
  });

  it('accumulates multiple errors', () => {
    const r = validateProfile({ label: '', types: [] });
    expect(r.errors.length).toBeGreaterThanOrEqual(2);
  });

  it('returns errors array on missing label and missing types', () => {
    const r = validateProfile({ label: null, types: null });
    expect(r.valid).toBe(false);
    expect(r.errors.length).toBeGreaterThanOrEqual(2);
  });
});

// ─── Mutation hardening: defaulting & boundary branches ────────────────────────
// These tests pin the nullish/positional/coalescing branches that the happy-path
// suite leaves unexercised, so Stryker mutants on them are killed rather than
// silently surviving. Mirrors the boundary tests that took category-editor.js to
// 100% mutation.

describe('profileToForm — defaulting branches (mutation hardening)', () => {
  it('defaults types to empty when profile.qualities is missing', () => {
    const doc = { ...PROFILE_DOC };
    delete doc.qualities;
    const form = profileToForm(doc, QUALITIES);
    expect(form.types).toHaveLength(0);
  });

  it('defaults finish positionally (first=true, rest=false) when finish array is empty', () => {
    const doc = { ...PROFILE_DOC, qualities: ['720p', '1080p'], finish: [] };
    const form = profileToForm(doc, QUALITIES);
    expect(form.types[0].finish).toBe(true);
    expect(form.types[1].finish).toBe(false);
  });

  it('honours explicit finish flags over the positional default', () => {
    // First quality finish=false, second finish=true — the inverse of the
    // positional default — so a mutant that ignores the array (or flips the
    // i===0 default) produces a visibly different result.
    const doc = { ...PROFILE_DOC, qualities: ['720p', '1080p'], finish: [false, true] };
    const form = profileToForm(doc, QUALITIES);
    expect(form.types[0].finish).toBe(false);
    expect(form.types[1].finish).toBe(true);
  });

  it("defaults id to '' when _id is missing", () => {
    const doc = { ...PROFILE_DOC };
    delete doc._id;
    const form = profileToForm(doc, QUALITIES);
    expect(form.id).toBe('');
  });

  it("defaults label to '' when label is missing", () => {
    const doc = { ...PROFILE_DOC };
    delete doc.label;
    const form = profileToForm(doc, QUALITIES);
    expect(form.label).toBe('');
  });

  it('defaults waitFor to 0 (never NaN) when wait_for is missing', () => {
    const doc = { ...PROFILE_DOC };
    delete doc.wait_for;
    const form = profileToForm(doc, QUALITIES);
    expect(form.waitFor).toBe(0);
    expect(Number.isNaN(form.waitFor)).toBe(false);
  });

  it('defaults stopAfter to 0 (never NaN) when stop_after is missing', () => {
    const doc = { ...PROFILE_DOC };
    delete doc.stop_after;
    const form = profileToForm(doc, QUALITIES);
    expect(form.stopAfter).toBe(0);
    expect(Number.isNaN(form.stopAfter)).toBe(false);
  });

  it('defaults minimumScore to 1 when minimum_score is missing', () => {
    const doc = { ...PROFILE_DOC };
    delete doc.minimum_score;
    const form = profileToForm(doc, QUALITIES);
    expect(form.minimumScore).toBe(1);
  });

  it('defaults minimumScore to 1 when minimum_score is null', () => {
    const doc = { ...PROFILE_DOC, minimum_score: null };
    const form = profileToForm(doc, QUALITIES);
    expect(form.minimumScore).toBe(1);
  });

  it('preserves a minimum_score of exactly 0 (not coerced to the default 1)', () => {
    const doc = { ...PROFILE_DOC, minimum_score: 0 };
    const form = profileToForm(doc, QUALITIES);
    expect(form.minimumScore).toBe(0);
  });

  it('reads an explicit, non-default minimum_score', () => {
    const doc = { ...PROFILE_DOC, minimum_score: 50 };
    const form = profileToForm(doc, QUALITIES);
    expect(form.minimumScore).toBe(50);
  });

  it('tolerates a null quality-list argument (labels fall back to the identifier)', () => {
    // Exercises the `qualities || []` guard with a falsy quality list: the
    // metadata map is empty, so every type label falls back to its identifier.
    const form = profileToForm(PROFILE_DOC, null);
    expect(form.types).toHaveLength(2);
    expect(form.types[0].qualityLabel).toBe('720p');
    expect(form.types[0].allow3d).toBe(false);
  });

  it('treats an entirely absent finish field like an empty one (positional default)', () => {
    // Exercises the `profile.finish || []` guard when the field is undefined,
    // not merely an empty array.
    const doc = { ...PROFILE_DOC, qualities: ['720p', '1080p'] };
    delete doc.finish;
    const form = profileToForm(doc, QUALITIES);
    expect(form.types[0].finish).toBe(true);
    expect(form.types[1].finish).toBe(false);
  });
});

describe('formToPayload — toNum & defaulting branches (mutation hardening)', () => {
  const baseForm = () => profileToForm(PROFILE_DOC, QUALITIES);

  it('passes through valid, non-default numeric fields unchanged', () => {
    const form = { ...baseForm(), minimumScore: 8, waitFor: 5, stopAfter: 10 };
    const payload = formToPayload(form);
    expect(payload.minimum_score).toBe(8);
    expect(payload.wait_for).toBe(5);
    expect(payload.stop_after).toBe(10);
  });

  it('coalesces null numeric fields to their defaults (1 / 0 / 0)', () => {
    const form = { ...baseForm(), minimumScore: null, waitFor: null, stopAfter: null };
    const payload = formToPayload(form);
    expect(payload.minimum_score).toBe(1);
    expect(payload.wait_for).toBe(0);
    expect(payload.stop_after).toBe(0);
  });

  it('coalesces undefined numeric fields to their defaults (1 / 0 / 0)', () => {
    const form = { ...baseForm(), minimumScore: undefined, waitFor: undefined, stopAfter: undefined };
    const payload = formToPayload(form);
    expect(payload.minimum_score).toBe(1);
    expect(payload.wait_for).toBe(0);
    expect(payload.stop_after).toBe(0);
  });

  it("coalesces a null label to '' at the wire boundary", () => {
    const form = { ...baseForm(), label: null };
    const payload = formToPayload(form);
    expect(payload.label).toBe('');
  });

  it("coalesces an undefined label to '' at the wire boundary", () => {
    const form = { ...baseForm(), label: undefined };
    const payload = formToPayload(form);
    expect(payload.label).toBe('');
  });

  it('defaults types to an empty array when formState.types is missing', () => {
    const form = { ...baseForm(), types: undefined };
    const payload = formToPayload(form);
    expect(payload.types).toHaveLength(0);
  });
});

describe('addQuality — fresh-array no-op (mutation hardening)', () => {
  it('returns a NEW array (copy), not the same reference, for an empty qualityId', () => {
    const types = [{ qualityId: '720p', finish: true, is3d: false }];
    const result = addQuality(types, '');
    expect(result).not.toBe(types);
    expect(result).toEqual(types);
  });

  it('returns a NEW array (copy), not the same reference, for a null qualityId', () => {
    const types = [{ qualityId: '720p', finish: true, is3d: false }];
    const result = addQuality(types, null);
    expect(result).not.toBe(types);
  });
});

describe('removeQuality — boundary & promotion branches (mutation hardening)', () => {
  const types = [
    { qualityId: '720p',  finish: true,  is3d: false },
    { qualityId: '1080p', finish: false, is3d: false },
    { qualityId: 'dvdrip',finish: false, is3d: false },
  ];

  it('returns a NEW array (copy) for an out-of-range index, not the same reference', () => {
    const result = removeQuality(types, 99);
    expect(result).not.toBe(types);
    expect(result).toEqual(types);
  });

  it('returns a NEW array (copy) for a negative index, not the same reference', () => {
    const result = removeQuality(types, -1);
    expect(result).not.toBe(types);
  });

  it('does NOT promote finish when removing a non-first item', () => {
    // The promotion is gated on index===0. Removing index 1 must leave the
    // (already-false) first item's finish untouched, killing a mutant that
    // promotes unconditionally.
    const t = [
      { qualityId: 'a', finish: false, is3d: false },
      { qualityId: 'b', finish: false, is3d: false },
    ];
    const result = removeQuality(t, 1);
    expect(result[0].finish).toBe(false);
  });
});

describe('moveQuality — finish-reset branches (mutation hardening)', () => {
  const allFinish = () => [
    { qualityId: 'A', finish: true, is3d: false },
    { qualityId: 'B', finish: true, is3d: false },
    { qualityId: 'C', finish: true, is3d: false },
    { qualityId: 'D', finish: true, is3d: false },
  ];

  it('moving a middle item UP (not to/through position 0) leaves every finish flag untouched', () => {
    // displacedFromFirst must be -1 here: no item leaves position 0, so a mutant
    // that mis-computes it wrongly clears a finish flag and is caught.
    const result = moveQuality(allFinish(), 2, 'up'); // [A, C, B, D]
    expect(result.map(t => t.qualityId)).toEqual(['A', 'C', 'B', 'D']);
    expect(result.every(t => t.finish === true)).toBe(true);
  });

  it('moving a middle item DOWN (not from position 0) leaves every finish flag untouched', () => {
    const result = moveQuality(allFinish(), 1, 'down'); // [A, C, B, D]
    expect(result.map(t => t.qualityId)).toEqual(['A', 'C', 'B', 'D']);
    expect(result.every(t => t.finish === true)).toBe(true);
  });
});

describe('validateProfile — numeric-bound branches (mutation hardening)', () => {
  const validForm = {
    label: 'Best',
    types: [{ qualityId: '720p', finish: true, is3d: false }],
  };

  it('accepts a minimumScore well above the minimum (the guard is AND-ed, not OR-ed)', () => {
    const r = validateProfile({ ...validForm, minimumScore: 50 });
    expect(r.valid).toBe(true);
    expect(r.errors.some(e => e.includes('Minimum score'))).toBe(false);
  });

  it('does not flag minimum score when minimumScore is null (guard short-circuits)', () => {
    const r = validateProfile({ ...validForm, minimumScore: null });
    expect(r.valid).toBe(true);
    expect(r.errors.some(e => e.includes('Minimum score'))).toBe(false);
  });

  it('accepts waitFor and stopAfter of exactly 0 (boundary: 0 is not negative)', () => {
    const r = validateProfile({ ...validForm, waitFor: 0, stopAfter: 0 });
    expect(r.valid).toBe(true);
    expect(r.errors.some(e => e.includes('cannot be negative'))).toBe(false);
  });

  it('accepts positive waitFor and stopAfter', () => {
    const r = validateProfile({ ...validForm, waitFor: 7, stopAfter: 30 });
    expect(r.valid).toBe(true);
  });

  it('ignores non-finite numeric bounds (e.g. -Infinity) rather than flagging them', () => {
    // The Number.isFinite guard means a non-finite value is simply not validated;
    // a mutant that drops the guard would (wrongly) flag -Infinity as negative.
    const r = validateProfile({ ...validForm, waitFor: -Infinity, stopAfter: -Infinity });
    expect(r.valid).toBe(true);
    expect(r.errors.some(e => e.includes('cannot be negative'))).toBe(false);
  });

  it('the negative-bound error names the offending field AND the reason', () => {
    const r = validateProfile({ ...validForm, waitFor: -5, stopAfter: -2 });
    expect(r.errors.some(e => e.includes('Wait (days) cannot be negative.'))).toBe(true);
    expect(r.errors.some(e => e.includes('Keep searching (days) cannot be negative.'))).toBe(true);
  });
});
