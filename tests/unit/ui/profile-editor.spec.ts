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
