# CouchPotato Design System — conventions

This is a **tokens + guidelines** reference, not a component bundle. The real
CouchPotato UI is server-rendered **htmx + Alpine.js + Tailwind** (Jinja2
templates), so there are no importable React components here. Build your own
components, but style them **strictly** with the tokens and idiom below so they
match the product. The authoritative spec is `guidelines/design-system.md`.

## Setup & theming
- No provider component. The look comes entirely from `styles.css`'s `@import`
  closure: the **Inter** typeface, the theme tokens (`tokens/theme.css`), and the
  brand colours (`tokens/brand.css`). Load `styles.css` and you have everything.
- **Dark is the default.** Add `class="light"` on the root (`<html>`) to switch;
  the same `--cp-*` token names resolve to light values. Persist to
  `localStorage['cp-theme']`. Never hard-code hex — read the tokens, so both
  themes work for free.

## Styling idiom — CSS custom-property tokens (+ Tailwind `cp.*` classes)
Style with `var(--cp-*)` tokens directly. In the app these are also exposed as
Tailwind utilities (`bg-cp-card`, `text-cp-muted`, …) via `tailwind.config`; if
your runtime lacks that config, use the `var(--cp-*)` values — same colours.

| Token (`var(--cp-…)`) | Tailwind class | Role |
|---|---|---|
| `--cp-bg` | `bg-cp-bg` | app background (darkest layer) |
| `--cp-surface` | `bg-cp-surface` | inset surfaces, inputs |
| `--cp-card` | `bg-cp-card` | card surface (lightest layer) |
| `--cp-border` | `border-cp-border` | dividers, borders |
| `--cp-text` | `text-cp-text` | primary text |
| `--cp-muted` | `text-cp-muted` | secondary text |
| `--cp-accent` | `bg-cp-accent` | brand cyan `#35c5f4` (hover `--cp-accent-hover`) |
| `--cp-accent-text` | `text-cp-accent` | accent **as text** (auto-darkens to `#0e7490` in light for AA) |
| `--cp-success` / `--cp-warning` / `--cp-danger` | `*-cp-success/warning/danger` | semantic, fixed in both themes |

Depth = three near-black layers `bg → surface → card` + translucent borders
(`white/[0.0x]` in dark, auto-inverted to black in light). Radii: `rounded-md`
inputs, **`rounded-lg` buttons & toasts**, `rounded-xl` modals/cards. Icons are
**Heroicons outline**, 24×24, `stroke-width="1.5"`, `fill="none"` — no icon font.
Motion is restrained: 150ms hover, 200ms `fade-in`, 300ms sidebar; honour
`prefers-reduced-motion`.

## Where the truth lives (read before styling)
- `styles.css` + `tokens/theme.css` + `tokens/brand.css` — every token value.
- `guidelines/design-system.md` — **authoritative**: components (buttons, inputs,
  toggles, badges, toasts, poster cards, tables, modals, states), iconography,
  motion, accessibility.
- `guidelines/conformance.md` — conformance checklist. `guidelines/screenshots/`
  — annotated visual reference (dark + two light screens).

## Idiomatic snippet (token-styled)
```html
<!-- Primary button -->
<button class="rounded-lg px-4 py-2 text-sm font-semibold"
        style="background:var(--cp-accent);color:var(--cp-bg)">Add movie</button>

<!-- Card on the app background -->
<div style="background:var(--cp-card);border:1px solid var(--cp-border)"
     class="rounded-xl p-4">
  <h3 class="text-sm font-semibold" style="color:var(--cp-text)">Wanted</h3>
  <p class="text-xs" style="color:var(--cp-muted)">3 movies searching…</p>
  <span class="px-1.5 py-0.5 rounded text-[9px] font-medium"
        style="background:color-mix(in srgb,var(--cp-success) 20%,transparent);color:var(--cp-success)">done</span>
</div>
```

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
