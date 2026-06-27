# Handoff: CouchPotato Design System (v3 / htmx UI)

## Overview
This package documents the **canonical design system for the modern CouchPotato web UI** — the htmx + Alpine + Tailwind interface under `couchpotato/ui/`. It defines colour, typography, spacing, iconography, components, motion, and accessibility so the modern UI can be built/extended consistently and the legacy MooTools UI (`/old/`, `couchpotato/static/style/*.scss`) can be retired.

The system was **extracted directly from the existing codebase** (`couchpotato/ui/templates/base.html` and the `partials/`), so most tokens below already exist in the app. Treat this README as the source of truth when adding new screens or refactoring old ones.

## About the Design Files
The `*.dc.html` files in this bundle are **static design-canvas exports** — raw reference snapshots and a data source (notably the `iconGroups` SVG path data). They are **not** production code to copy verbatim, and **not** standalone browsable pages: they were authored against a design-tool runtime (`support.js`) that is **not** part of this handoff, so the `{{ … }}` template bindings will not render. **This `README.md` is the authoritative spec;** use the `.dc.html` only as raw reference/data.

### Precedence when sources disagree
Where a `.dc.html` export diverges from this README or the live `couchpotato/ui/templates/base.html`, **base.html + this README win.** Known divergences in the exports:
- **Poster-card hover:** production (dark) is `border-color: rgba(53,197,244,0.15)` + `box-shadow: …rgba(53,197,244,0.06)` (see Surfaces below and `base.html`), *not* the brighter values shown in the export.
- **Ghost button:** transparent by default (`hover:bg-white/[0.03]`, per Components below), *not* the opaque `bg-cp-surface` fill an export caption may show.

Your target environment already exists: **Jinja2 templates + htmx 2 + Alpine 3 + Tailwind (CDN) + Inter**. Recreate anything from these references using that stack and the conventions already in `couchpotato/ui/templates/` — Tailwind utility classes, Alpine `x-data` components, htmx attributes, and the `cp.*` colour tokens. Do not introduce a new framework, CSS-in-JS, or a component library.

## Fidelity
**High-fidelity.** Colours, type, spacing, radii, and states are final and exact. Match them precisely; they mirror values already in `base.html`.

---

## Design Tokens

### Tailwind config (already in `base.html` — keep as-is)
```js
tailwind.config = {
  darkMode: 'class',
  theme: { extend: {
    fontFamily: { sans: ['Inter', 'sans-serif'] },
    colors: { cp: {
      bg: 'var(--cp-bg)', card: 'var(--cp-card)', surface: 'var(--cp-surface)',
      border: 'var(--cp-border)', text: 'var(--cp-text)', muted: 'var(--cp-muted)',
      accent: '#35c5f4', accentHover: '#4dd4ff',
      success: '#3ddc84', warning: '#e5a00d', danger: '#f04848', blue: '#35c5f4',
    } }
  } }
}
```

### Theme variables (CSS custom properties on `:root` / `:root.light`)
Dark is the default; `<html class="light">` switches the theme. Persist the choice to `localStorage['cp-theme']`.

| Token | Role | Dark | Light |
|---|---|---|---|
| `--cp-bg` | app background | `#0d0d0d` | `#f5f5f7` |
| `--cp-surface` | inset / inputs | `#111113` | `#fafafa` |
| `--cp-card` | card surface | `#161618` | `#ffffff` |
| `--cp-border` | dividers, borders | `#1e1e22` | `#e0e0e4` |
| `--cp-text` | primary text | `#e0e0e4` | `#1a1a1a` |
| `--cp-muted` | secondary text | `#9b9ba8` | `#666666` |

**Accent (brand):** `#35c5f4` cyan. Hover `#4dd4ff`.
**Accent-as-text contrast rule:** cyan text fails AA on light tints, so in light mode `.text-cp-accent` is overridden to **`#0e7490`** (same hue, sufficient contrast). Keep this override.

**Semantic (fixed across themes):** success `#3ddc84` · warning `#e5a00d` · danger `#f04848`.

**Translucent layers** (borders/fills, used heavily as `white/[0.0x]` in dark): in light mode invert to black-based — e.g. `border-white/[0.04]` → `rgba(0,0,0,0.08)`, `bg-white/[0.03]` → `rgba(0,0,0,0.04)`. These overrides already exist in `base.html`.

### Typography
- **Family:** `Inter` (Google Fonts, weights 300/400/500/600/700). Single family — no secondary face. (The legacy Open Sans + Lobster pairing is retired.)
- **Global tracking:** `letter-spacing: -0.01em` on `*`; headings tighten further (`tracking-tight`, ~`-0.02em`; hero `-0.03em`).
- **Scale (as used):** hero `text-5xl/600`, section h2 `text-3xl/600`, body `text-sm–base/300`, labels `text-[13px]/500`, captions `text-xs`/`text-[10px]` muted, mono captions in JetBrains Mono (docs only — app uses Inter).

### Spacing & radius
- **Spacing:** Tailwind 4px scale. Common: `gap-2`(8) `gap-3`(12) `p-2.5`(10) `p-4`(16) `px-3 py-2` for controls.
- **Radius:** `rounded`(4px) nav items · `rounded-md`(6px) inputs · `rounded-lg`(8px) **buttons** and toasts · `rounded-xl`(12px) modals/cards. (Buttons are `rounded-lg`, per Components below.)
- **Layout:** sidebar `w-56` (224px), collapses to `w-16` (64px); mobile top bar `h-12`, bottom nav.

### Surfaces & elevation
Depth = three near-black layers (`bg` → `surface` → `card`) + translucent borders. Floating chrome (sidebar, top bar) uses `bg-black/80 backdrop-blur-xl` (light: `bg-white/85`). Cards sit flat; only the poster card gets an accent border + glow on hover (transition `0.2s`). Exact values (from `base.html`):

| | `border-color` | `box-shadow` glow |
|---|---|---|
| **Dark** (`.poster-card:hover`) | `rgba(53,197,244,0.15)` | `0 0 20px rgba(53,197,244,0.06)` |
| **Light** (`:root.light .poster-card:hover`) | `rgba(53,197,244,0.3)` | `0 0 20px rgba(53,197,244,0.1)` |

---

## Iconography
The app uses **Heroicons (outline)** inline as SVG — 24×24, `stroke-width="1.5"`, `stroke="currentColor"`, `fill="none"`, decorative ones get `aria-hidden="true"`. No icon font.

The legacy UI's 30-glyph icon font maps to these Heroicons. When porting old screens, swap each glyph for its equivalent:

| Legacy glyph | Heroicon (outline) |
|---|---|
| `icon-home` | home |
| `icon-movie` | film |
| `icon-search` | magnifying-glass |
| `icon-settings` | cog-6-tooth |
| `icon-menu` | bars-3 |
| `icon-handle` | bars-2 |
| `icon-dots` | ellipsis-horizontal |
| `icon-dropdown` | chevron-down |
| `icon-left-arrow` | arrow-left |
| `icon-plus` | plus |
| `icon-download` | arrow-down-tray |
| `icon-refresh` | arrow-path |
| `icon-redo` | arrow-uturn-right |
| `icon-delete` | trash |
| `icon-cancel` | x-mark |
| `icon-ok` | check |
| `icon-play` | play |
| `icon-eye` | eye |
| `icon-donate` | heart |
| `icon-notifications` | bell |
| `icon-info` | information-circle |
| `icon-error` | exclamation-triangle |
| `icon-thumb` | squares-2x2 (grid view) |
| `icon-list` | list-bullet |
| `icon-filter` | funnel |
| `icon-star` / `star-empty` / `star-half` | star (outline; fill with accent; half via 50% linear-gradient fill) |
| `icon-emo-cry` | face-frown (empty states) |
| `icon-emo-sunglasses` | custom sunglasses glyph in the same line style (no exact Heroicon; `face-smile` only as a rough placeholder) |
| `icon-emo-coffee` | custom coffee-cup glyph in the same line style |

The two glyphs with no Heroicon (`sunglasses`, `coffee`) should be drawn fresh as 24×24 / stroke-1.5 paths to match. Exact path data for every icon is in the reference file's `iconGroups` array.

---

## Components

All examples use existing Tailwind/`cp.*` tokens. Hover/focus states are required.

### Buttons
- **Primary:** `bg-cp-accent text-cp-bg rounded-lg px-4 py-2 text-sm font-semibold hover:bg-cp-accentHover`
- **Ghost (secondary):** `border border-cp-border text-cp-text rounded-lg px-4 py-2 hover:bg-white/[0.03]`
- **Danger:** `border border-cp-danger/30 text-cp-danger hover:bg-cp-danger/10`

### Inputs (settings field grammar)
`w-full bg-white/[0.03] border border-white/[0.06] rounded-md px-3 py-2 text-xs focus:outline-none focus:border-cp-accent/30`. Helper text `text-[10px] text-cp-muted mt-1.5`. Optional `<details>` "Learn more" disclosure (`summary` in `text-cp-accent`).

**10 field types** (from `partials/settings/field_types.html`): `string` · `int`/`float` (number) · `password` · `dropdown` (select) · `bool` (checkbox, `text-cp-accent` accent) · `directory` (input + Browse button → folder modal) · `directories` (repeatable rows with remove + "+ Add folder") · `combined` (multi-column rows: a `use` toggle switch + text inputs, headers, "+ Add") · `button` (async action: spinner + inline success/error result).

**Toggle switch:** `w-8 h-4 rounded-full` track (`bg-cp-accent` on / `bg-white/[0.08]` off), `role="switch" :aria-checked`, knob `w-3 h-3 bg-white` translating `translate-x-4` / `translate-x-0.5`.

**Settings row layout:** label + hint on the left, control right-aligned; rows divided by `border-white/[0.04]`.

### Status & quality badges
Pill `px-1.5 py-0.5 rounded text-[9px] font-medium`: wanted `bg-cp-blue/20 text-cp-blue` · done `bg-cp-success/20 text-cp-success` · snatched `bg-cp-warning/20 text-cp-warning` · quality `bg-white/10 text-white/80 backdrop-blur-sm`.

### Toasts
Global Alpine `toast(msg, type, duration)` queue, top-right, `aria-live="polite"`. `bg-green-600`/`bg-red-600`/`bg-cp-accent text-cp-bg` for success/error/info. Auto-dismiss (default 3000ms) + manual close.

### Poster card (`partials/movie_cards.html`)
`poster-card rounded-md overflow-hidden bg-cp-card border border-white/[0.05] group`. `aspect-[2/3]` poster with lazy `<img>` + gradient fallback; status badge top-right, quality badge over a bottom `from-black/90` gradient; title `text-xs font-medium truncate`, year `text-[10px] text-cp-muted`. Hover reveals a bulk-select checkbox (top-left) and a refresh button (bottom-right). Hover glow on `.poster-card`.

### Release table
Header row `font-medium text-xs text-cp-muted border-b border-cp-border`; data rows `border-white/[0.04]`, numerics (size/seeds) in mono; seed colour by health (success / muted / warning).

### Modals & overlays (`partials/settings/modals.html`)
`role="dialog" aria-modal="true"` on a `bg-black/60` scrim, centered, `bg-cp-card rounded-xl border border-white/[0.05] w-full max-w-lg`. **Header** (title + close X) / **scrollable body** (`max-h-[80vh]` or `max-h-[400px]`) / **footer** (right-aligned Cancel + primary). Required behaviours: Escape closes, scrim-click dismisses, Tab is trapped within. Also: **restart banner** (`bg-cp-warning/20 border-cp-warning/30`, fixed bottom-center) and the **directory browser** modal (Up button + mono path + folder list).

### States
- **Spinner:** shared SVG circle, `animate-spin`, `text-cp-accent` / `text-cp-muted`.
- **Skeleton:** `bg-cp-border` blocks, pulse animation, while posters load.
- **Empty:** centered muted icon + message ("No movies found", "No results found", "No notifications (yet)", "Empty folder").
- **Error:** `exclamation-triangle` in `text-cp-danger` + message.
- **htmx indicator:** `.htmx-indicator` hidden until `.htmx-request`.

---

## Interactions & Behaviour
- **Theme toggle:** toggles `.light` on `<html>`, persists `localStorage['cp-theme']`, respects `prefers-color-scheme` on first load.
- **Sidebar:** collapsible (`w-56`↔`w-16`, 300ms); active link gets `bg-cp-accent/10 text-cp-accent` + `aria-current="page"`.
- **htmx:** content swaps in place; global `htmx:afterRequest` listener fires toasts for `movie.add`, `media.delete`, `movie.searcher.single`, `movie.refresh`.
- **Search → add:** result card opens a movie-info modal; profile `<select>` lazy-loads via `hx-get`; Add button shows adding/added state.

## Motion
Restrained and fast. `fade-in` (opacity 0→1, translateY 4px→0, 0.2s ease-out) for swapped content. Transitions: **150ms** colour/hover, **200ms** fades, **300ms** sidebar collapse. Honour `prefers-reduced-motion: reduce` — collapse all animation/scroll to ~0ms (already in `base.html`).

## Accessibility
Built-in, with a Playwright + axe suite. Rules every component follows:
- `:focus-visible` → `2px solid #35c5f4`, `outline-offset: 2px`; suppress on mouse (`:focus:not(:focus-visible)`).
- **Skip link** ("Skip to main content") — off-screen until focused, first tab stop.
- `aria-current` on active nav; `aria-label` on every icon-only button; `aria-hidden` on decorative SVGs.
- `role` + `aria-live` on toasts/status regions; `aria-modal` + focus trap on dialogs; `sr-only` for visually-hidden labels.
- Light-mode accent contrast override (`#0e7490`) — see tokens.

## Migration: legacy → modern
**Carry over:** poster grid + status badges, release table, quality profiles, star ratings (half-star), dark/light theming concept.
**Leave behind:** Lobster wordmark, Open Sans, the `#ac0000` red accent, the custom icon font, and the MooTools + Uniform + ripple stack (replaced by htmx + Alpine + inline Heroicons).

## Files
- `theme.css` — **ready-to-paste theme.** All `:root` / `:root.light` variables, the light-mode contrast + translucent overrides, scrollbars, `fade-in`, htmx indicator, and the full a11y/reduced-motion base. Values are verified against `base.html` (including the correct poster-card hover: dark `0.15`/`0.06`, light `0.3`/`0.1`). Load it after the Tailwind CDN + `tailwind.config`.
- `screenshots/` — annotated PNGs of each section (dark), plus `13-colour-light.png` and `14-forms-light.png` for the light theme: `01-overview` · `02-colour` · `03-typography` · `04-icons` · `05-components` · `06-forms` · `07-modals` · `08-states` · `09-surfaces` · `10-motion` · `11-accessibility` · `12-migration`.
- `couchpotato-design-system.dc.html` — static design-canvas export (tokens, components, and the **icon path data** in its `iconGroups` array). Reference/data only — not a browsable page (see "About the Design Files"); this README is authoritative.
- `couchpotato-design-system-classic.dc.html` — the legacy red/Open Sans/Lobster system, for reference only (being retired).

### Source files in the repo to align with
- `couchpotato/ui/templates/base.html` — Tailwind config, CSS variables, sidebar/chrome, toasts, theme toggle, a11y scaffolding.
- `couchpotato/ui/templates/partials/settings/field_types.html` — the 10 form field types.
- `couchpotato/ui/templates/partials/settings/modals.html` — dialog, restart banner, directory browser.
- `couchpotato/ui/templates/partials/movie_cards.html` · `couchpotato/ui/templates/partials/search_results.html` — poster cards & states.
