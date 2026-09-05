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

- `wizard.html`, all 61 labels and 63 inputs.
- The stragglers elsewhere, measured: `partials/movie_cards.html` (2 labels, 0
  with `for`), `partials/settings/field_types.html` (1 of 1),
  `partials/settings/combined_basics_card.html` (1 of 1),
  `partials/settings/header.html` (1 of 1),
  `partials/settings/provider_card.html` (1 of 1),
  `partials/settings/profiles.html` (2 of 7), `partials/settings/logs_tab.html`
  (1 of 2), `logs.html` (1 of 2).
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
  scan fail, which it currently would not.
- **AC-SIMP-6:** No visual change. The wizard must look identical; this adds
  attributes, it does not restyle.

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
