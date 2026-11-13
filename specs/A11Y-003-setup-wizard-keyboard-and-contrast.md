# A11Y-003: The setup wizard keeps keyboard focus, names its states, and meets contrast

> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the next spec improves.

**Status:** agreed (owner decision 2026-11-12: "Own PR, after batch 2")
**Lenses run:** accessibility, QA, simplicity, written by the orchestrator from
two review reports on PR #584 (an accessibility-lens review and an adversarial
verification run), not by a `/plan-cycle` run. **Skipped:** product and design
(no new flow, copy limited to one visually hidden string and state attributes),
architecture, data, security (no new input, route or stored value), operability
(template-only change; rollback is reverting the commit).

## Problem

The setup wizard (`couchpotato/ui/templates/wizard.html`) is the first screen a
new user meets, and it is below the project's WCAG 2.2 AA floor for keyboard,
screen-reader and low-vision users. All of these were found while reviewing
PR #584 and none was reached by a test before it:

1. **Focus is lost on every step.** Continue/Finish binds `:disabled="saving"`
   and `nextStep()` sets `saving = true`, so the button the user just pressed
   is disabled, the browser moves focus to `<body>`, and nothing restores it.
   A keyboard user restarts from the top of the page on each of five steps.
   "Sync Trackers from Jackett" has the same shape.
2. **Three hint lines fail contrast.** "NZB indexers", "Torrent trackers" and
   "Maximum coverage" on the Providers step measure 2.34:1 (light) and 3.21:1
   (dark) against 4.5:1 (`opacity-60` on 10px text).
3. **The folder picker is not a dialog.** No `role="dialog"`, `aria-modal`,
   accessible name, Escape handling or focus trap; opening it does not move
   focus into it and closing it does not return focus. The settings twin
   (`partials/settings/modals.html`) has all of these.
4. **State by colour alone.** The step indicator does not expose the current
   step; the Usenet/Torrents/Both buttons do not expose which is selected.
5. **Busy states are silent.** "Saving…", "Syncing…" and "Testing…" replace a
   button's text with no status announcement, and the Jackett sync result
   paragraph is not a live region.

## Not in scope

- Restructuring `setupWizard()` (its SonarQube complexity finding is a separate
  batch). This change adds the minimum state and handlers the criteria need.
- Any other template. `partials/settings/modals.html` is the pattern to copy,
  not a file to change.
- A screen-reader test run. None exists in this project; the PR states what
  only one could confirm.
- New copy visible to sighted users, layout, spacing or step order.

## What this replaces

| What goes | Owning lens | Removal criterion |
|---|---|---|
| `:disabled` bound to a busy flag on a focusable wizard control | accessibility | AC-A11Y-2 |
| `KNOWN_CONTRAST_DEBT` exclusion and its companion "still failing" test in `tests/e2e/wizard-icons.a11y.spec.ts` | QA | AC-QA-4 |
| The "Setup wizard accessibility gaps" entry in `docs/technical-debt.md` | QA | AC-QA-7 |

---

## Acceptance criteria

### Accessibility

- **AC-A11Y-1 (focus kept):** After activating Continue, Finish Setup, Skip,
  Back, or Sync Trackers from Jackett by keyboard, `document.activeElement` is
  never `<body>` once the action settles. When the step changes, focus lands
  on the new step's heading (made programmatically focusable, not added to the
  tab order); when the step does not change (validation or save failure, sync
  finished), focus stays on the control that was activated.
- **AC-A11Y-2 (no native disabled on a busy control):** No focusable wizard
  control binds `disabled` to a busy flag. Busy controls use
  `aria-disabled="true"` and a handler guard, as
  `partials/settings/trakt_auth.html` does, so a second activation while busy
  does nothing (one save request per activation, proven by counting requests).
  The step-indicator buttons for steps not yet reached may stay natively
  disabled: they are never the focused control when they become disabled.
- **AC-A11Y-3 (contrast):** Every text node on every wizard step meets 4.5:1
  (3:1 for large text) in both themes at 375px and 1280px, including the three
  hint lines in both the selected and unselected state of their button, with
  no axe exclusion.
- **AC-A11Y-4 (dialog):** The folder picker is exposed as a modal dialog named
  "Browse Folders". Opening it moves focus inside it; Tab and Shift+Tab cycle
  within it; Escape closes it; closing it by Escape, Cancel, the close button
  or Select returns focus to the Browse button that opened it. Behaviour
  matches the settings twin.
- **AC-A11Y-5 (current step):** Exactly one step-indicator button has
  `aria-current="step"`, and it is the current one. Each indicator button's
  accessible name includes the step's name and, for a finished step, that it
  is complete, not only "✓" or a number.
- **AC-A11Y-6 (selected source):** *(Owner decision 2026-11-13: a pick-one
  group, not three toggles.)* The Usenet/Torrents/Both buttons are a
  `role="radiogroup"` named by text already on the page (`aria-labelledby` to
  the existing question), with `role="radio"` and `aria-checked` on each
  button. Only the actual choice is checked: choosing Both checks only Both.
  `aria-pressed` is not used on them. The visual highlight is unchanged (Both
  still lights all three); that mismatch is deliberate and recorded in
  `docs/technical-debt.md`. The APG radio-group keyboard pattern applies: one
  tab stop (roving tabindex on the checked radio), Arrow keys move and choose
  with wrap, Space chooses. Their focus ring is painted and their targets are
  at least 24x24 CSS px. The Usenet and Torrent download-client buttons, which
  are true toggles shown by colour, expose `aria-pressed` bound to their real
  state.
- **AC-A11Y-7 (busy and result announced):** One persistent, visually hidden
  polite status region exists in the wizard from first render. Its text is set
  when a save, sync or connection test starts and when it finishes ("Saving…",
  then cleared or the outcome). The Jackett sync result is announced through
  it or through its own persistent live region. The region is not created or
  revealed at the moment its text changes.
- **AC-A11Y-8 (no regression):** `tests/e2e/wizard-icons.a11y.spec.ts` and the
  other wizard specs pass unchanged except where this spec removes something.
  Target sizes of every control touched stay at or above 24x24 CSS px
  (WCAG 2.5.8) and the visible focus indicator is painted on each (pixel
  check, as `logs-semantics.a11y.spec.ts` does, not a computed-style check).

### QA

- **AC-QA-1:** Each of AC-A11Y-1 to 7 has an E2E test in the accessibility
  project that fails on `master`'s template for the stated reason and passes
  after. Level: E2E.
- **AC-QA-2:** Keyboard tests drive the real keyboard (`page.keyboard`), not
  `.click()` or `.focus()`, for the action under test.
- **AC-QA-3:** No test depends on time, animation phase or network arrival
  order: saves and sync are gated with routes the test releases; no
  `waitForTimeout`, no `setTimeout` in a route handler.
- **AC-QA-4:** `KNOWN_CONTRAST_DEBT`, its `.exclude(...)` and its companion
  test are deleted, and the wizard axe scan covers every step in both themes
  at 375px with no exclusion.
- **AC-QA-5:** Each new guard is proven by mutation (break the template, see
  the named test fail, restore by file copy, hash check), with the results in
  the PR.
- **AC-QA-6:** The new specs pass `--repeat-each=5` and again under CPU load.
- **AC-QA-7:** The technical-debt entry for these gaps is removed or reduced
  to what remains unfixed, and states what no automated test can confirm.
- **AC-QA-8:** Existing behaviour is pinned before it is changed: a save
  failure still keeps the user on the step and shows the existing error; the
  wizard still issues the same saves in the same order
  (`wizard-provider-saves.spec.ts` unchanged and green).

### Simplicity (constraints)

- **AC-SIMP-1:** Product-code changes are confined to
  `couchpotato/ui/templates/wizard.html`.
- **AC-SIMP-2:** No new dependency, Alpine plugin or shared component. Focus
  trap and Escape handling copy the approach already in
  `partials/settings/modals.html` / `partials/settings/scripts.html`.
- **AC-SIMP-3:** No new visible text for sighted users. Contrast is fixed by
  changing the hint's opacity or colour token only, using existing design
  tokens (`docs/design-system/`), and conformance passes.

---

## Vetoes and trade-offs

| Item | Raised by | Decision | Rationale |
|---|---|---|---|
| Extract a shared directory-browser dialog for wizard and settings | simplicity | vetoed | Two copies is existing debt; merging them is a refactor with its own risk, not an accessibility fix |
| Move focus to the step heading on step change | accessibility | accepted | The step's content is replaced; leaving focus on a button whose meaning just changed tells a screen-reader user nothing about where they are |
| Keep native `disabled` on not-yet-reached step buttons | simplicity | accepted | They cannot hold focus at the moment they become disabled, so the focus-loss failure does not apply |

## Spec gaps found at review

- The folder dialog dropped focus to `<body>` when a folder row was opened (the keyed list removes the focused button) and when Retry was pressed (its container hides); AC-A11Y-4 only covered open and close.
- A focus callback queued on open could run after the dialog had been closed (Enter then Escape), leaving focus on `<body>`; no criterion covered a close that races the open.
- Back, Skip and the step buttons were inert but unannounced during a save; AC-A11Y-2 covered only the controls that bind `disabled`.
- Browse stayed usable during a save, so a dialog could open behind a step change and write a folder into a field that had already been saved.
- The download-client buttons are true toggles shown by colour alone; AC-A11Y-6 named only the source buttons.
- AC-A11Y-1 required step headings out of the tab order, but nothing tested it (a surviving mutation).
- `aria-pressed` was chosen for a single-choice control; a pick-one group is a radio group (owner decision 2026-11-13). A criterion naming an ARIA pattern should say whether the control is one-of-many or independent.
- AC-QA-8 required `wizard-provider-saves.spec.ts` to stay unchanged, but changing the source buttons to radios necessarily changes that spec's `getByRole('button', ...)` selector to `getByRole('radio', ...)` (one word; five other specs changed the same way).
- AC-A11Y-6 said Arrow keys move and choose with no exclusion for Alt, Control or Meta, whose arrow chords are browser shortcuts (Alt+Left is Back); the handler swallowed them until a review found it.
- AC-A11Y-2 allowed native `disabled` on not-yet-reached step buttons without saying they must not also carry `aria-disabled`; they carried `aria-disabled="false"` on a disabled control.
- No QA criterion required the folder dialog's error container to be tested in the hide direction (an empty alert box and a stray Retry over every successful listing left the suite green).
