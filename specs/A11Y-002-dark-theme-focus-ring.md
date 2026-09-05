# A11Y-002: the default theme paints its focus ring transparent

**Status:** agreed
**Source:** found by `lens-accessibility` while reviewing A11Y-001; pre-existing,
not introduced by that change.
**Severity:** WCAG 2.2 AA, 1.4.11 Non-text Contrast, in the DEFAULT theme,
across the whole application.

## Problem

`couchpotato/ui/templates/base.html:193` sets the focus ring:

    :focus-visible { outline: 2px solid #35c5f4; outline-offset: 2px; }

Tailwind's `focus:outline-none` utility compiles to
`.focus\:outline-none:focus { outline: 2px solid transparent }`. Its specificity
is 0,2,0 against the base rule's 0,1,0, so on any element carrying that utility
the outline is painted TRANSPARENT rather than removed. `:focus-visible` still
matches; only the colour is gone.

The light theme escapes by accident. `base.html:202` adds
`:root.light :focus-visible { outline-color: #0e7490 }` at 0,3,0, which wins the
colour back. There is no `:root.dark` equivalent, and dark is the default:
`base.html:2` is `<html lang="en" class="dark">`.

Measured:

    :root.light rules in base.html : 18
    :root.dark  rules in base.html : 0
    focus:outline-none occurrences : 100, across 17 templates

A reviewer measured the result in a real browser on `#wizard-username`:

    dark  : computed outline `solid 2px rgba(0, 0, 0, 0)`; the only focus
            signal is a border shift measuring 1.63:1
    light : computed outline `solid 2px rgb(14, 116, 144)`; passes

So in the theme the application ships with, a keyboard user has effectively no
focus indicator anywhere. 1.4.11 requires 3:1.

## Why nothing caught it

The comment at `base.html:194-201` reasons correctly that `#35c5f4` measures
9.40:1 on the dark background. It is never painted. This is the "watching the
wrapper, not the capability" shape: an automated check that asserts an outline
is PRESENT passes, because it is present and invisible.

## Scope

One rule mirroring the light one, plus a guard that fails when the ring is not
actually painted in either theme.

## Not in scope

- Removing the 100 `focus:outline-none` utilities. They are deliberate: the
  design replaces the default browser ring with its own treatment. The bug is
  the missing dark override, not the utility.
- Any other contrast finding.

## Acceptance criteria

- **AC-A11Y-1:** On a focused element carrying `focus:outline-none`, the
  computed `outline-color` is NOT transparent, in BOTH themes. Asserting the
  outline exists is not enough: it already exists and fails.
- **AC-A11Y-2:** The painted ring measures at least 3:1 against the background
  it sits on, in both themes. Compute it, do not assert a hex value, because a
  future palette change must fail this.
- **AC-QA-3:** The guard fails when the `:root.dark` rule is removed. Proven by
  removing it and watching it fail, then restoring.
- **AC-SIMP-4:** One CSS rule. If the diff grows past that plus its test,
  something else is being fixed and belongs in its own change.
