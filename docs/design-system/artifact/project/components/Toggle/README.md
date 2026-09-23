# Toggle

The one sanctioned switch: a 32×16 track with a 12px white knob, used for every on/off setting.

## Use
- Always render via `partials/settings/toggle.html` (`toggle_click`, `toggle_model`, `toggle_label` or `toggle_label_expr`); never hand-roll it.
- Track `w-8 h-4 rounded-full`: `bg-cp-accent` on, `bg-white/[0.08]` off. Knob `w-3 h-3 bg-white`, `translate-x-4` on / `translate-x-0.5` off.
- `role="switch"`, `:aria-checked`, and an `aria-label` naming what it controls on every instance.

## Don't
Introduce a larger or smaller variant; the conformance checker fails the build on off-spec sizes.

## Accessibility note
The knob is 2.0:1 on `cp-accent`; state is carried by knob position and `aria-checked`, not colour alone.
