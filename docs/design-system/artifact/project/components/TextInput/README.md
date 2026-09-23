# TextInput

The settings field grammar: a label, a filled input and optional helper text or a "Learn more" disclosure.

## Use
- Input: `min-h-[44px] w-full bg-white/[0.03] border border-white/[0.06] rounded-md px-3 py-2 text-xs text-cp-text` with the `focus-visible:outline-cp-accent` ring.
- Helper text: `text-[10px] text-cp-muted mt-1.5`. Disclosure: `<details>` with the `summary` in `cp-accent-text`.
- Settings rows put label and hint left, control right, divided by `cp-hairline`.

## Field types
Ten types share this grammar (from `partials/settings/field_types.html`): string, int/float, password, dropdown, bool, directory (input + Browse → directory modal), directories (repeatable rows + "+ Add folder"), combined (multi-column rows with a Toggle), and button (async action with spinner and inline result).

## The consumer provides
A visible label tied to the input, the value, and `aria-describedby` for helper text.

## Accessibility note
The border (`cp-hairline-strong`) is well under 3:1; the field is identified by its fill and label, and focus by `cp-focus-ring`. Keep it that way rather than relying on the outline.
