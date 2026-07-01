# UI-CONFORM-01 — Normalize toggle switches to the canonical size + fix wizard a11y

## Problem

The design system's canonical toggle switch is: track `w-8 h-4`, knob `w-3 h-3`,
`translate-x-4` (on) / `translate-x-0.5` (off), with `role="switch"`,
`:aria-checked`, and an `aria-label`.

- Conformant today: `couchpotato/ui/templates/partials/settings/field_types.html`,
  `partials/settings/header.html`, `partials/settings/provider_card.html` — all
  `w-8 h-4` with proper `role="switch"` + `:aria-checked` + `aria-label`.
- Non-conformant: `couchpotato/ui/templates/wizard.html` uses a larger,
  undocumented `w-10 h-5` / knob `w-4 h-4` / `translate-x-5` variant at **8 sites**
  (approx lines 158, 196, 221, 237, 260, 311, 404, 679), AND those 8 toggles are
  **missing** `role="switch"`, `:aria-checked`, and `aria-label` — a real a11y
  gap that CONFORMANCE.md requires.

Decision (approved): **normalize the wizard toggles down to the canonical size**
and add the missing a11y attributes. Extract a single reusable toggle partial to
prevent future drift.

## Fix

1. Create a reusable Jinja include partial,
   `couchpotato/ui/templates/partials/settings/toggle.html`, rendering the
   canonical toggle: track `w-8 h-4 rounded-full transition-colors shrink-0`,
   knob `block w-3 h-3 bg-white rounded-full transition-transform absolute
   top-0.5` with `:class="... ? 'translate-x-4' : 'translate-x-0.5'"`,
   `role="switch"`, `:aria-checked`, and an `aria-label`. Parameterize via
   Jinja `{% set %}` / `include with context` or macro parameters: the Alpine
   model expression, the label text, and any name/id. Match the existing markup
   in `field_types.html:210-212` as the reference implementation.
2. Refactor `wizard.html`'s 8 toggles to use the shared partial (canonical size +
   full a11y attributes). Preserve each toggle's existing Alpine `x-model` /
   state binding and label so wizard behaviour is unchanged — only size and a11y
   attributes change.
3. Optionally (nice-to-have, only if low-risk) refactor the 3 already-canonical
   toggles to use the same partial for consistency. If it risks churn, leave them
   and just note it.
4. Update the design-system docs to state the single canonical toggle size and
   that it is the only sanctioned variant: `docs/design-system/CONFORMANCE.md`
   (and `docs/design-system/README.md` if it documents the toggle). Do not invent
   a "large" variant — there is only the canonical one now.

## Acceptance criteria

- `wizard.html` contains no `w-10 h-5` / `translate-x-5` toggle markup.
- Every toggle in `couchpotato/ui/templates/**` uses `w-8 h-4` and has
  `role="switch"`, `:aria-checked`, and an `aria-label`.
- Wizard toggles still bind/toggle their settings correctly (behaviour parity).
- `ruff check .` clean; UI unit tests + existing e2e pass.

## Tests (TDD — write failing checks first)

- Add `/wizard` coverage to `tests/e2e/accessibility.a11y.spec.ts` — it currently
  visits `/`, `/available/`, `/suggestions/`, `/add/`, `/settings/` but NOT
  `/wizard`. Add a wizard page case running axe + keyboard checks so the missing
  toggle a11y attributes would be caught. (This also partially serves Phase 4.)
- Add/extend a UI unit test (Vitest or a template-render assertion) verifying the
  wizard no longer emits `w-10 h-5` toggles and that toggles carry
  `role="switch"`.
- Verify wizard toggle interaction in an existing wizard e2e/interaction spec if
  one exists; otherwise assert the rendered attributes.

## Files

- `couchpotato/ui/templates/partials/settings/toggle.html` (new)
- `couchpotato/ui/templates/wizard.html` (8 toggles)
- `docs/design-system/CONFORMANCE.md` (+ README.md if applicable)
- `tests/e2e/accessibility.a11y.spec.ts` (add /wizard)
- UI unit test for the toggle rendering
