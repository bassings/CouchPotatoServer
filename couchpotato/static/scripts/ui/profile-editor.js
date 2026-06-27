// Pure logic functions for quality-profile management.
// Extracted from the Alpine component so they can be unit- and mutation-tested.
// Imported by profiles.html and tested by tests/unit/ui/profile-editor.spec.ts.

/**
 * Map a profile API document into a reactive form state object.
 *
 * @param {Object} profile  Raw profile doc from profile.list API
 *                          { _id, label, order, core, minimum_score, qualities[],
 *                            finish[], "3d"[], wait_for[], stop_after[], hide }
 * @param {Array}  qualities  Full quality list from quality.list API
 *                            [{ identifier, label, allow_3d, ... }]
 * @returns {{ id: string, label: string, minimumScore: number, waitFor: number,
 *             stopAfter: number, types: Array }}
 */
export function profileToForm(profile, qualities) {
  const qualMap = {};
  for (const q of (qualities || [])) {
    qualMap[q.identifier] = q;
  }

  const profileQualities = profile.qualities || [];
  const finish  = profile.finish    || [];
  const threeD  = profile['3d']     || [];
  const waitFor = profile.wait_for  || [];
  const stopAft = profile.stop_after || [];

  const types = profileQualities.map((qId, i) => {
    const meta = qualMap[qId] || {};
    return {
      qualityId:    qId,
      qualityLabel: meta.label || qId,
      allow3d:      !!meta.allow_3d,
      finish:       finish[i] !== undefined ? !!finish[i] : (i === 0),
      is3d:         threeD[i] !== undefined ? !!threeD[i] : false,
    };
  });

  return {
    id:           profile._id || '',
    label:        profile.label || '',
    minimumScore: profile.minimum_score != null ? Number(profile.minimum_score) : 1,
    waitFor:      waitFor.length > 0 ? Number(waitFor[0]) : 0,
    stopAfter:    stopAft.length > 0 ? Number(stopAft[0]) : 0,
    types,
  };
}

/**
 * Convert form state into the payload expected by profile.save.
 * Returns an object ready to be serialised (JSON or URLSearchParams).
 *
 * @param {Object} formState  As returned / mutated from profileToForm
 * @param {number} currentProfileCount  Number of existing profiles; used to
 *   assign `order` for NEW profiles so they append at the end instead of all
 *   landing at the backend's default order=999 and sorting non-deterministically.
 * @returns {Object}  { id?|order, label, minimum_score, wait_for, stop_after, types[] }
 */
export function formToPayload(formState, currentProfileCount = 0) {
  // Coalesce null/undefined AND NaN (x-model.number yields NaN for a cleared
  // input) to the default, so the server never receives the string "NaN".
  const toNum = (v, dflt) => (v != null && Number.isFinite(Number(v)) ? Number(v) : dflt);
  const payload = {
    label:         formState.label,
    minimum_score: toNum(formState.minimumScore, 1),
    wait_for:      toNum(formState.waitFor, 0),
    stop_after:    toNum(formState.stopAfter, 0),
    types:         (formState.types || []).map(t => ({
      quality: t.qualityId,
      finish:  t.finish ? 1 : 0,
      '3d':    t.is3d   ? 1 : 0,
    })),
  };

  if (formState.id) {
    payload.id = formState.id;
  } else {
    payload.order = currentProfileCount;
  }

  return payload;
}

/**
 * Add a quality to the types list. No-ops if qualityId is falsy or already
 * present. Returns a NEW array — does not mutate the input.
 *
 * @param {Array}  types      Current types array
 * @param {string} qualityId  Quality identifier to add
 * @returns {Array}
 */
export function addQuality(types, qualityId) {
  if (!qualityId) return types.slice();
  const existing = types.slice();
  const alreadyPresent = existing.some(t => t.qualityId === qualityId);
  if (alreadyPresent) return existing;

  const isFirst = existing.length === 0;
  existing.push({
    qualityId,
    qualityLabel: qualityId,
    allow3d: false,
    finish:  isFirst,
    is3d:    false,
  });
  return existing;
}

/**
 * Remove the quality at the given index. Returns a NEW array.
 * If the removed item was at position 0, the new first item gets finish=true.
 *
 * @param {Array}  types  Current types array
 * @param {number} index  Zero-based index to remove
 * @returns {Array}
 */
export function removeQuality(types, index) {
  if (index < 0 || index >= types.length) return types.slice();
  const result = types.slice();
  result.splice(index, 1);
  if (index === 0 && result.length > 0) {
    result[0] = { ...result[0], finish: true };
  }
  return result;
}

/**
 * Move a quality up or down within the list. Clamps at boundaries.
 * Returns a NEW array. The first item always keeps finish=true; an item
 * displaced FROM position 0 has its finish reset to false (it was only
 * true because of the forced-first-position rule, not user choice).
 *
 * @param {Array}  types      Current types array
 * @param {number} index      Zero-based index to move
 * @param {'up'|'down'} direction
 * @returns {Array}
 */
export function moveQuality(types, index, direction) {
  const result = types.slice();
  const target = direction === 'up' ? index - 1 : index + 1;
  if (target < 0 || target >= result.length) return result;

  // Swap
  [result[target], result[index]] = [result[index], result[target]];

  // After the swap, enforce finish rules:
  //   - position 0 always has finish=true
  //   - if position 0 was vacated (an item moved away from it), reset that
  //     item's finish to false — it was forced-true by position, not by the user.
  //     After the swap, the item that came FROM position 0 is now at:
  //       - `index` when direction='up'  (old pos 0 = target=0, now at index)
  //       - `target` when direction='down' (old pos 0 = index=0, now at target)
  const displacedFromFirst =
    (direction === 'up'   && target === 0) ? index :
    (direction === 'down' && index  === 0) ? target :
    -1;

  // KNOWN LIMITATION: an item leaving position 0 always has its finish flag
  // cleared, on the assumption that finish=true there was position-forced. If a
  // user explicitly set finish=true on an item at another position and it later
  // passes through position 0, moving it away will silently clear that flag.
  // Distinguishing position-forced from user-set finish would require tracking
  // intent in form state; accepted as a minor edge case for now.
  return result.map((t, i) => {
    if (i === 0)                return { ...t, finish: true };
    if (i === displacedFromFirst) return { ...t, finish: false };
    return { ...t };
  });
}

/**
 * Validate form state. Returns { valid: boolean, errors: string[] }.
 *
 * @param {{ label?: string|null, types?: Array|null }} formState
 * @returns {{ valid: boolean, errors: string[] }}
 */
export function validateProfile(formState) {
  const errors = [];

  const label = (formState && formState.label != null) ? String(formState.label).trim() : '';
  if (!label) {
    errors.push('Profile name is required.');
  }

  const types = (formState && formState.types) ? formState.types : [];
  if (types.length === 0) {
    errors.push('At least one quality is required.');
  }

  // Numeric bounds: HTML5 min attributes only guard the browser path; this pure
  // function is the contract callers/tests rely on, so enforce them here too.
  const score = formState && formState.minimumScore;
  if (score != null && Number.isFinite(Number(score)) && Number(score) < 1) {
    errors.push('Minimum score must be at least 1.');
  }
  for (const [key, label] of [['waitFor', 'Wait (days)'], ['stopAfter', 'Keep searching (days)']]) {
    const v = formState && formState[key];
    if (v != null && Number.isFinite(Number(v)) && Number(v) < 0) {
      errors.push(label + ' cannot be negative.');
    }
  }

  return { valid: errors.length === 0, errors };
}
