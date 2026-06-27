# Design System Conformance Checklist

Derived from [`README.md`](./README.md) (the source of truth). Every new-UI page
and partial must satisfy these. Each conformance PR should tick the relevant
boxes and add tests (vitest unit for extracted logic, Playwright e2e, axe a11y).

## Tokens & theme
Exact values live in [`README.md`](./README.md) (source of truth) — this checklist
deliberately does not repeat hex values, so it can't drift out of sync.
- [ ] Tailwind `cp.*` colors match the README config exactly (accent, hover, and the fixed success/warning/danger).
- [ ] CSS custom properties match the README dark/light table: **`:root` holds the DARK values (the default)** and **`:root.light` holds the LIGHT values** — not inverted.
- [ ] Light-mode `.text-cp-accent` contrast override is present (the AA value in the README tokens section).
- [ ] Translucent layers invert correctly in light mode (`white/[0.0x]` → black-based, per README).
- [ ] Theme toggle flips `.light` on `<html>`, persists `localStorage['cp-theme']`, respects `prefers-color-scheme` on first load.

## Typography
- [ ] Single family **Inter** (300/400/500/600/700); no Open Sans / Lobster.
- [ ] Global `letter-spacing: -0.01em`; headings `tracking-tight`; hero `-0.03em`.
- [ ] Scale used as specified (hero `text-5xl/600`, h2 `text-3xl/600`, body `text-sm–base`, labels `text-[13px]/500`, captions `text-xs`/`text-[10px]`).

## Iconography
- [ ] All icons are inline **Heroicons (outline)**, 24×24, `stroke-width="1.5"`, `stroke="currentColor"`, `fill="none"`.
- [ ] No legacy icon-font glyphs remain (map per README table). Decorative icons get `aria-hidden="true"`.
- [ ] `sunglasses` / `coffee` drawn fresh as 24×24 stroke-1.5 to match.

## Components
- [ ] **Buttons** — primary / ghost / danger variants with hover + focus states.
- [ ] **Inputs** — the 10 field types (`string`, `int`/`float`, `password`, `dropdown`, `bool`, `directory`, `directories`, `combined`, `button`) follow the field grammar; helper text + `<details>` learn-more.
- [ ] **Toggle switch** — `role="switch"` + `:aria-checked`, correct track/knob classes.
- [ ] **Status & quality badges** — pill classes per status (wanted/done/snatched/quality).
- [ ] **Toasts** — Alpine `toast(msg,type,duration)` queue, `aria-live="polite"`, auto-dismiss + manual close.
- [ ] **Poster card** — structure, lazy img + gradient fallback, badges, hover checkbox + refresh, hover glow.
- [ ] **Release table** — header/data row styles, mono numerics, seed color by health.
- [ ] **Modals** — `role="dialog" aria-modal="true"`, scrim, header/body/footer; Escape closes, scrim-click dismisses, Tab trapped; restart banner; directory browser.

## States
- [ ] Spinner (`animate-spin`), skeleton (pulse), empty (icon + message), error (`exclamation-triangle` + message), htmx indicator.

## Motion
- [ ] `fade-in` for swapped content; 150ms hover / 200ms fade / 300ms sidebar.
- [ ] `prefers-reduced-motion: reduce` collapses animation to ~0ms.

## Accessibility (axe-clean)
- [ ] `:focus-visible` → `2px solid` accent ring + `outline-offset: 2px` (accent value per README); suppressed on mouse.
- [ ] Skip link ("Skip to main content"), first tab stop, off-screen until focused.
- [ ] `aria-current` on active nav; `aria-label` on every icon-only button; `aria-hidden` on decorative SVGs.
- [ ] `role` + `aria-live` on toasts/status; `aria-modal` + focus trap on dialogs; `sr-only` for hidden labels.

## Coding standards (every PR)
- **Security:** no secrets/XSS (`x-html` only on trusted/escaped content), input validation preserved.
- **Accessibility:** axe suite green; keyboard reachable.
- **Supportability/Maintainability:** pure logic extracted into tested `couchpotato/static/scripts/ui/` modules; no new framework/CSS-in-JS/component lib.
- **TDD:** failing test first → implement → green; principal-dev standard.
