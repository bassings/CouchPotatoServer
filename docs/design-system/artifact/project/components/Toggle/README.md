# Toggle

The one sanctioned switch: a 32×16 track with a 12px white knob, used for every on/off setting.

## Use
- Always render via `partials/settings/toggle.html` (`toggle_click`, `toggle_model`, `toggle_label` or `toggle_label_expr`); never hand-roll it.
- Track `w-8 h-4 rounded-full`, knob `w-3 h-3`, `translate-x-4` on / `translate-x-0.5` off. Colours come from `base.html` rules keyed on `[role=switch][aria-checked]`, not the Tailwind classes: `cp-switch-off` track with a white knob; `cp-switch-on` track with a `cp-switch-knob-on` knob.
- `role="switch"`, `:aria-checked`, and an `aria-label` naming what it controls on every instance.

## Don't
Introduce a larger or smaller variant; the conformance checker fails the build on off-spec sizes.

## Accessibility note
Track and knob clear 3:1 against each other and against the card and page in both themes (WCAG 1.4.11). State is carried by knob position and `aria-checked` as well as colour. Keep `role="switch"` and a string `aria-checked`: the colours depend on them.
