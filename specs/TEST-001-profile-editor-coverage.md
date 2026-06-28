# TEST-001 — profile-editor.js to 100% branch + mutation

## Problem
`category-editor.js` (PR #138) is at **100% statements / branch / functions / lines**
and **100% Stryker mutation** (87/87 mutants killed). Its older sibling
`profile-editor.js` (PR #137) lags: **89.4% branch** coverage, with uncovered
branches at lines **34, 40–42, 66–70**. The 54 existing unit tests cover the
happy paths but leave defaulting/coalescing branches unexercised, so a mutant
that breaks them survives silently.

This is a **tests-only** gap: the production logic in `profile-editor.js` already
handles these cases correctly — it is simply not pinned by assertions.

## Uncovered branches (from `vitest --coverage`)
- **L34** `finish[i] !== undefined ? !!finish[i] : (i === 0)` — the `i === 0`
  default (first quality auto-finishes) and the explicit-`finish[i]` path.
- **L40–42** `profile._id || ''`, `profile.label || ''`,
  `minimum_score != null ? Number(...) : 1` — the nullish/missing fallbacks.
- **L66–70** `formToPayload`'s `toNum` defaults (`null`, `undefined`, and the
  `NaN`-from-cleared-`x-model.number` path) for `minimumScore`/`waitFor`/
  `stopAfter`, and `label ?? ''`.

## Fix
Add unit tests to `tests/unit/ui/profile-editor.spec.ts` exercising each branch
above — mirroring the boundary tests added for `category-editor.js`:
- `profileToForm` with: missing `finish` array (→ first quality finishes, rest
  don't); explicit `finish[i]` true/false; missing `_id`/`label`; `minimum_score`
  null vs present vs `0`.
- `formToPayload` with: `minimumScore`/`waitFor`/`stopAfter` as `null`,
  `undefined`, `NaN`, and a valid number; `label` null/undefined (→ `''`).
- No production code change.

## Acceptance criteria
- [x] All real (non-equivalent) Stryker mutants killed; score raised from **80.40% → 96.80%**.
- [x] 0 surviving *killable* mutants and 0 *no-coverage* mutants — the 8 remaining
      survivors are **provably equivalent** (see below) and cannot be killed by any
      test without editing the production source (forbidden by this spec).
- [x] All existing `profile-editor.spec.ts` tests still pass; full `tests/unit/ui/` green
      (165 tests across 5 files).
- [x] No change to `couchpotato/static/scripts/ui/profile-editor.js`.

## Equivalent mutants (cannot be killed — documented per the spec contract)

A mutant is *equivalent* when the mutated program is observationally identical to
the original for **every** input, so no assertion can distinguish them. Killing
these would require editing `profile-editor.js` (e.g. a `// Stryker disable`
comment), which this tests-only task forbids. Each was confirmed by exhaustive
case analysis; the final Stryker run shows exactly these 8 and no others.

1. **L18:33 `ArrayDeclaration` — `for (const q of (qualities || []))` → `(... || ["Stryker was here"])`.**
   Only reachable when `qualities` is falsy. The injected element is the *string*
   `"Stryker was here"`; its `.identifier`, `.label`, `.allow_3d` are all
   `undefined`, so it adds the entry `qualMap["undefined"] = "<string>"`, which is
   never read as an object — `meta.label`/`meta.allow_3d` are `undefined` for a
   string. `qualMap` is internal; output is unchanged.

2. **L23:40 `ArrayDeclaration` — `profile.finish || []` → `... || ["Stryker was here"]`.**
   Only reachable when `finish` is falsy. The injected array defines index 0 only,
   where `!!"Stryker was here" === true`; the original positional default at index 0
   is `i === 0 === true`. Both branches yield `true` at index 0, and every other
   index is `undefined` in both. Identical output.

3. **L35:21 `ConditionalExpression` — `threeD[i] !== undefined ? !!threeD[i] : false` → `true ? !!threeD[i] : false`.**
   The ternary's *else* value is the literal `false`, and `!!threeD[i]` when
   `threeD[i] === undefined` is also `false`. So `true ? !!threeD[i] : false`
   ≡ the original for all `i`. (Contrast L34, whose else-branch is `i === 0`, not a
   constant — that one is killable and is killed.)

4. **L120:20 `ConditionalExpression` — `index >= types.length` → `false`** and
5. **L120:20 `EqualityOperator` — `index >= types.length` → `index > types.length`.**
   Both differ from the original only when `index >= length` (resp. `index === length`).
   In every such case the body runs `result.splice(index, 1)`, which removes nothing
   for an out-of-range start, and the `index === 0` promotion cannot fire (a non-empty
   array has `index !== 0`; an empty array yields `[]` either way). The returned value
   is always a fresh copy with identical contents — indistinguishable from the early
   `return types.slice()`.

6. **L156:6 `ConditionalExpression` — `(direction === 'up' && target === 0)` → `(true && target === 0)`.**
   `target === 0` is only ever reachable via the up-branch (`target = index - 1 = 0`);
   the down-branch sets `target = index + 1 >= 1`. So `target === 0` already implies
   `direction === 'up'`, making the dropped `direction === 'up' &&` redundant.

7. **L157:6 `ConditionalExpression` — `(direction === 'down' && index === 0)` → `(true && index === 0)`.**
   `index === 0` with `direction === 'up'` always early-returns at the
   `if (target < 0 ...) return result;` guard (`target = -1`), so this ternary is only
   evaluated when `direction === 'down'`. The dropped `direction === 'down' &&` is
   therefore redundant in all reachable states.

8. **L200:9 `ConditionalExpression` — `v != null && Number.isFinite(Number(v)) && Number(v) < 0` → `true && Number.isFinite(Number(v)) && Number(v) < 0`.**
   Dropping the `v != null` guard changes behaviour only when `v == null` *and*
   `Number.isFinite(Number(v)) && Number(v) < 0`. But `Number(null) === 0` (finite,
   not `< 0`) and `Number(undefined) === NaN` (not finite), so the two guards can
   never disagree. Identical output. (The neighbouring mutants that drop *both*
   guards, or flip the comparison, **are** killable and are killed — e.g. via the
   `-Infinity` and `waitFor === 0` boundary tests.)

## Files
- `tests/unit/ui/profile-editor.spec.ts` — +32 branch/boundary/identity tests
  (54 → 86) targeting every killable survivor and no-coverage mutant.
- `specs/TEST-001-profile-editor-coverage.md` — this file.
