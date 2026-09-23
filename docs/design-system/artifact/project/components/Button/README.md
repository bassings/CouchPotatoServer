# Button

Three variants carry every action: primary (one per view), ghost (secondary and Cancel) and danger (destructive).

## Use
- **Primary**: `bg-cp-accent text-black hover:bg-cp-accentHover rounded-lg px-4 py-2 text-xs font-semibold`. Text is `cp-on-accent` (black, 10.4:1), never `text-cp-bg`, which turns near-white in light.
- **Ghost**: `border border-cp-border text-cp-text rounded-lg px-4 py-2`, transparent, `hover:bg-white/[0.03]` (`cp-fill-hover`).
- **Danger**: `border border-cp-danger/30 text-cp-danger hover:bg-cp-danger/10 rounded-md px-2.5 py-1.5 text-xs font-medium`. On a danger tint over `cp-card` in dark, use `cp-danger-strong` text.
- Disabled: `disabled:opacity-60` (40 on danger) plus `pointer-events-none`; busy buttons swap the label ("Adding…") and show the spinner.

## The consumer provides
The label (sentence case verb), an optional leading 16px Heroicon with `aria-hidden`, and an `aria-label` when the button is icon-only.

## Don't
- Put two primaries side by side; the second is ghost.
- Remove the focus ring with `focus:outline-none` alone.
