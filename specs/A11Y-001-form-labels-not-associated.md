# A11Y-001: form labels are not associated with their fields

**Status:** agreed
**Source:** SonarQube, 118 findings at MEDIUM or higher across
`Web:S6853`, `Web:InputWithoutLabelCheck` and `Web:S6819`.
**Owner decision:** 2026-09-05, take the accessibility slice first.

## Problem

61 `<label>` elements in `couchpotato/ui/templates/wizard.html`, and not one is
associated with a field. Measured:

    wizard.html      labels=61  with for=0   inputs=63  with aria-label=0

Every label sits visually above its input and is invisible to assistive
technology, which announces those fields as unlabelled. That includes the
security step where a new user sets their username and password, and every
download client's API key and token field. It also means clicking a label does
not focus its field, which costs every user, not only screen reader users.

This is WCAG 2.2 AA, 1.3.1 Info and Relationships, 3.3.2 Labels or
Instructions, and 4.1.2 Name, Role, Value.

## Why the existing tests do not catch it

They are not wrong; they are looking at a different thing. `axe` scans the
rendered DOM and correctly ignores hidden elements. The wizard is a multi-step
form whose later steps are `x-show`-gated, so at the moment
`tests/e2e/accessibility.a11y.spec.ts:247` scans it, most of those fields are
not visible and are never evaluated. SonarQube reads the template source and
sees all of them.

That gap is the more valuable finding than the labels themselves, and closing it
is part of this change.

## Scope

- `wizard.html`, all 61 labels and 63 inputs. **Correction (round 2 review,
  see below): only 37 of those 63 fields are reachable in the running app.**
  The rest sit inside markup that can never render.
- The stragglers elsewhere, measured: `partials/movie_cards.html` (2 labels, 0
  with `for`), `partials/settings/field_types.html` (1 of 1),
  `partials/settings/combined_basics_card.html` (1 of 1),
  `partials/settings/header.html` (1 of 1),
  `partials/settings/provider_card.html` (1 of 1),
  `partials/settings/profiles.html` (2 of 7), `partials/settings/logs_tab.html`
  (1 of 2), `logs.html` (1 of 2). **Correction: all eight were found already
  compliant when the guard below was written against them (see below) — this
  bullet lists where the guard runs, not where a diff was needed.**
- A guard that fails when a label or field is added without an association.
- An E2E scan that walks the wizard's steps rather than only its first.

## Not in scope

- `Web:S6819` (prefer a semantic tag over an ARIA role), 39 findings. A
  different defect with a different fix; it earns its own change.
- The other 829 findings at MEDIUM or higher. Sequenced separately, and the
  complexity ones are explicitly not being taken as a batch.
- Redesigning the wizard.

## Acceptance criteria

- **AC-A11Y-1:** Every interactive field in the templates listed under Scope has
  an accessible name, satisfied by ONE of: an explicit `for`/`id` pair, being
  wrapped by its `<label>`, or an `aria-label`/`aria-labelledby`. All three are
  valid; a guard that demands only the first is wrong.
- **AC-A11Y-2:** No duplicate `id` on any page. The three inputs inside `x-for`
  loops need bound ids (`:id="..."`), not static ones. A static id repeated per
  iteration is a worse defect than the one being fixed.
- **AC-A11Y-3:** Clicking a label moves focus to its field. This is the
  behaviour the fix buys and it is observable, unlike the markup itself.
- **AC-QA-4:** A guard parses the templates and fails when a field has no
  accessible name by any of the three routes in AC-A11Y-1. Proven load-bearing
  by removing one association and watching it fail.
- **AC-QA-5:** The E2E accessibility scan reaches wizard steps beyond the first.
  Proven by removing a label association on a LATER step and watching the E2E
  scan fail. **Correction (round 2 review): this held for only about one field
  in twenty.** axe's `label` rule accepts a `placeholder` as an accessible
  name, and 41 of the wizard's 63 fields carry one — so the scan only had
  teeth on the roughly one-in-twenty field with no placeholder. Fixed by
  replacing the axe-only scan with a DOM-level check
  (`assertFieldNamesAreReal` in `tests/e2e/accessibility.a11y.spec.ts`) that
  reads each visible field's actual accessible name and rejects it when that
  name is merely the placeholder axe would have accepted. Re-proven: removing
  `for="wizard-renamer-from"` (Library step, which HAS a placeholder) now
  fails; it did not before. The scan's axe rule list was also carrying two
  rule ids (`duplicate-id`, `duplicate-id-active`) that are `enabled: false`
  in the installed axe-core (4.13.0) and so could never report anything, plus
  two (`select-name`, `aria-input-field-name`) that apply to element types
  and roles this page has zero of (`<select>`; ARIA text-input-alike roles).
  All four dropped; `duplicate-id-aria`, which IS enabled, stays. A step's
  arrival is now asserted before it is scanned (heading + a known field both
  visible), and each scan asserts a measured minimum field count, so a scan
  that silently re-examines the wrong step or examines nothing fails loudly
  instead of reporting a clean run.
- **AC-SIMP-6:** No visual change. The wizard must look identical; this adds
  attributes, it does not restyle.
- **AC-A11Y-7** (round 2 review, B2): where two visible fields would
  otherwise share one accessible name (e.g. two enabled download clients'
  "Host" fields, two enabled private trackers' "Username" fields), each sits
  inside a distinct named group (`role="group"` plus `aria-label` or
  `aria-labelledby` naming the group, not the field), so assistive tech
  announces which group a field belongs to even though the visible label
  text is identical. Proven by asserting each field resolves inside its own
  differently-named group (`getByRole('group', { name: ... })`) and watching
  that assertion fail when the grouping markup is removed.
- **AC-A11Y-8** (round 2 review, B3): every icon-only button (no visible text
  content) has a non-empty accessible name. Proven with axe's `button-name`
  rule run against a scan that actually renders the button — the remove-row
  button (only visible with 2+ entries) and the directory browser's close
  button (only visible once opened) are both exercised for this, not left to
  a scan that never visits the state they render in.
- **AC-A11Y-9** (round 2 review, A4): a label names the field it is actually
  paired with, not merely *a* field. `toBeFocused()` alone cannot tell a
  correct `for`/`id` pairing from a swapped one — both move focus somewhere.
  Proven with `toHaveAccessibleName` asserting the exact expected text, and by
  swapping the Security step's `for` values and watching it fail while the
  focus-only assertion stayed green.

## Recorded debt

1. `Web:S6819`, 39 findings, ARIA roles used where a semantic element exists.
2. The remaining SonarQube backlog, sequenced and not batched.
3. Colour contrast on the Providers step's search-type hint text (light
   theme): "NZB indexers", "Torrent trackers" and "Maximum coverage" at
   2.34:1 against a 4.5:1 requirement (axe `color-contrast`, serious).
   Surfaced by AC-QA-5's extended E2E scan reaching the Providers step for
   the first time; a different defect (WCAG 1.4.3) to the one this change
   fixes, so it is recorded rather than fixed here. The wizard's later-step
   scan in `tests/e2e/accessibility.a11y.spec.ts` is scoped to
   `checkFieldNameA11y` (label/accessible-name rules only) rather than the
   full `checkA11y`, for the same reason `checkToggleA11y` already is: an
   unrelated pre-existing finding on a step must not mask the specific
   regression that step's check exists to catch.
4. `wizard.html:452`'s `<template x-if="false && formData.downloader">`
   block (26 of the file's 63 measured fields, see the round 2 correction
   below) is dead: the `false &&` short-circuits every render, and it is
   verified at runtime that zero `wizard-legacy-*` ids ever reach the DOM.
   Left in place for this change (not deleted) because it is out of scope for
   an accessibility fix; removing it is separate cleanup work.

## Round 2 correction (review, this fix cycle)

Two independent reviews of the first commit (ed2bea7c4) confirmed the shipped
wizard markup was correct — including the JavaScript-injected fields, all 63
of them, zero duplicate ids, zero dangling `for` — but found the guards this
spec's ACs describe were weaker than claimed, plus real gaps in three
templates and in this spec. The guard fixes are recorded against the ACs
above (AC-QA-5, AC-A11Y-7/8/9); the counting corrections are:

- **The "63 fields" count is real but the reachable count is 37.** Measured
  via the same `find_accessible_name_violations` parse this spec's guard
  uses: 39 fields live in `wizard.html`'s own markup (26 of them inside the
  dead block above) and 24 more are injected by `getDownloaderFields()`'s
  JS template-literal strings — 39 + 24 = 63, minus the 26 dead ones = 37
  reachable. The user-facing win this change delivers is 37 fields properly
  named, not 63.
- **The eight non-wizard Scope templates needed no diff.** Every field in
  `movie_cards.html`, `field_types.html`, `combined_basics_card.html`,
  `header.html`, `provider_card.html`, `profiles.html`, `logs_tab.html` and
  `logs.html` was already named by a wrapping `<label>` or an `aria-label`
  before this change — confirmed by running the guard against each and
  finding zero violations with no edits made. Two of them
  (`header.html`, `provider_card.html`) contain no interactive field at all,
  so their parametrised guard run asserts on an empty list; that is a
  correct, expected CLEAN result, not a gap. The original Scope bullet read
  as though a diff was needed in all eight; it was not.
