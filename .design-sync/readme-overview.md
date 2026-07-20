
---

## What's in this project

A **tokens + guidelines** export of the CouchPotato design system (the modern
htmx + Alpine + Tailwind UI). It carries the design language — not functional
components — because the product UI is server-rendered, not a React library.

- `styles.css` — load this; its `@import` closure brings Inter + all `--cp-*` tokens.
- `tokens/theme.css` — surface/text tokens (dark + `.light`), plus the a11y,
  scrollbar, `fade-in`, and reduced-motion base.
- `tokens/brand.css` — brand + semantic colours as CSS variables.
- `guidelines/design-system.md` — the authoritative spec (components, icons,
  motion, a11y, migration notes).
- `guidelines/conformance.md` — conformance checklist.
- `guidelines/screenshots/` — 14 annotated reference screens (dark + 2 light).

Source of truth in the app repo: `couchpotato/ui/templates/base.html`.
