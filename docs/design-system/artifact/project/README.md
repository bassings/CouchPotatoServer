CouchPotato is a self-hosted movie library and download manager. The UI is quiet, near-black chrome around bright poster art, with one cyan accent that means "act here". It runs on someone's home server and is used at a glance, so every screen favours legibility, calm and keyboard access over decoration.

The live implementation is Jinja2 + htmx 2 + Alpine 3 + Tailwind (CDN) with the `cp.*` colour tokens. Build new screens with those utilities and the tokens below; never introduce another framework, CSS-in-JS or a component library.

## Content fundamentals

- Write in plain, short sentence case: "Add Movie", "Search for releases", "Mark failed". Title Case only for navigation labels (Wanted, Library, Suggestions, Collections, Add Movie, Settings).
- Address the user as "you" sparingly; most copy is a label or a verb. Toasts state what happened: "Movie added to wanted list", "Search started", "Failed to add movie".
- Empty states are one line, friendly, never cute: "No movies found", "No results found", "No notifications (yet)", "Empty folder".
- Status words are lowercase in badges: `wanted`, `done`, `snatched`, `downloaded / review`.
- No emoji anywhere in the product UI.

## Visual foundations

### Colour

- Dark is the default theme; light is switched by `class="light"` on `<html>` and persisted to `localStorage['cp-theme']`, respecting `prefers-color-scheme` on first load.
- Depth is three layers: `cp-bg` (page) → `cp-surface` (insets, inputs, poster placeholders) → `cp-card` (cards, modals). Cards are flat. Separate with `cp-hairline` / `cp-hairline-strong`, never with drop shadows.
- `cp-accent` is the only brand colour. Use it as a fill (primary button, toggle on, info toast, skip link) with `cp-on-accent` text, which is always black. Use `cp-accent-text` whenever cyan is text or a link: raw `#35c5f4` fails AA on light surfaces (2.0:1).
- Status colours are semantic only: `cp-success` done/downloaded, `cp-warning` snatched/review/restart, `cp-danger` destructive and errors. As text use the `-text` variants, which darken to Tailwind 700 shades in light. A badge sitting over poster artwork or the `from-black/90` gradient keeps the bright base colour (class `on-dark`), and one directly on artwork is solid `cp-warning` with black text.
- Toasts use `cp-toast-success` / `cp-toast-error` fills with `cp-toast-fg`, and `cp-accent` + black for info, in both themes.
- Floating chrome (sidebar, top bar, bottom nav) is `cp-chrome` with a strong backdrop blur. Dialogs sit on `cp-scrim`.

### Type

- One family: **Inter** from Google Fonts, weights 300/400/500/600/700. Mono (`font-mono`, the system stack) is only for numerics in the release table and filesystem paths.
- Global tracking `-0.01em` on everything; titles tighten to `-0.025em` (`h2`), the hero to `-0.03em`.
- Body copy is light (300). Labels are `label` (13px/500). Most controls are `caption` (12px). Helper text and years are `micro` (10px) in `cp-muted`. Badges are `badge` (9px/500).

### Spacing, radius, layout

- Tailwind's 4px scale. Controls are `space-3` × `space-2` (px-3 py-2); primary buttons `space-4` × `space-2`; cards pad `space-2.5`.
- Radius steps by size: `radius-sm` nav items and badges, `radius-md` inputs and poster cards, `radius-lg` buttons and toasts, `radius-xl` modals. Only the toggle is fully round (`radius-full`).
- Desktop sidebar is `sidebar-width`, collapsing to `sidebar-collapsed`. Below `lg` it becomes a `topbar-height` top bar plus a bottom nav. Settings inputs keep `target-min` height.

### Motion

Restrained and fast: 150ms colour/hover transitions, a 200ms `fade-in` (opacity 0→1, translateY 4px→0, ease-out) for htmx-swapped content, 200ms poster glow, 300ms sidebar collapse. `prefers-reduced-motion: reduce` collapses every animation and transition to ~0ms. Spinners are the only looping motion.

### States

- Hover: `cp-fill-hover` on ghost/nav, `cp-accent-hover` on primary, `cp-poster-hover` border plus `poster-glow` on poster cards.
- Focus: `:focus-visible` draws a 2px solid `cp-focus-ring` outline at 2px offset; suppressed for mouse focus. Never remove it with `focus:outline-none` alone.
- Disabled: 40–60% opacity plus `pointer-events: none`.
- Loading: the shared spinner (`animate-spin`, `cp-accent-text` or `cp-muted`), `cp-border` skeleton blocks with pulse, and `.htmx-indicator` hidden until `.htmx-request`.
- Error: `exclamation-triangle` in `cp-danger-text` plus a one-line message.

## Iconography

- **Heroicons, outline**, inline SVG only: 24×24 viewBox, `stroke-width="1.5"`, `stroke="currentColor"`, `fill="none"`, rendered at `w-4 h-4` in nav and `w-3.5`–`w-5` in controls. No icon font.
- Decorative icons get `aria-hidden="true"`; every icon-only button gets an `aria-label`.
- Nav uses: signal (Wanted), presentation-chart-line (Library), star (Suggestions), a four-tile grid (Collections), plus (Add Movie), cog-6-tooth (Settings).
- The two legacy glyphs with no Heroicon (sunglasses, coffee) are drawn fresh as 24×24 stroke-1.5 paths.

## Logos

- The mark is the red couch with the green download arrow (`assets/Logos/couch.png`). It is full-colour raster: show it at 28px (`w-7 h-7`, `radius-sm`) next to the wordmark "CouchPotato" set in Inter 600 at 14px, `-0.025em` tracking. Never recolour it, and never let its red or green leak into the UI palette.
- `icon-512.png` is the PWA/app icon; `safari.svg` is the single-ink pinned-tab mask (see the Logos group notes).
- There is no separate wordmark file: the name is always live Inter text.

## Accessibility (WCAG 2.2 AA, enforced by Playwright + axe in both themes)

- A skip link "Skip to main content" is the first tab stop, off-screen until focused (`cp-accent` fill, `cp-on-accent` text, `radius-lg`).
- `aria-current="page"` on the active nav item; `role="switch"` + `aria-checked` + `aria-label` on toggles; `role="dialog" aria-modal="true"` with Escape, scrim click and a focus trap on modals.
- Toast nodes are `aria-hidden`; announcements go through two persistent `sr-only` live regions (polite, and assertive for errors), cleared then set so repeated messages are re-announced.
- Known source gaps kept exact: `cp-border` is 1.17:1 on `cp-bg` and input borders (`cp-hairline-strong`) are fainter still, so a field's boundary relies on its fill and label, not its outline. The toggle's white knob on `cp-accent` is 2.0:1; the switch state is carried by knob position and `aria-checked`.

## Not synced

- Source docs `docs/design-system/README.md` lag `base.html` in three places, and this system follows the code: primary buttons use black text (`cp-on-accent`), not `cp-bg`; light theme darkens status text (`cp-*-text`) and the focus ring (`cp-focus-ring`).
- Previews are static renditions styled by `components/bundle.css`, a hand-written transcription of the Tailwind classes used in the templates; there is no JS component library to bundle.
- Heroicons path data and the 30-glyph legacy mapping stay in the repo's design-system README; not copied as icon assets.
- Inter is hosted by Google Fonts, so no font files are stored here.
