# design-sync notes — CouchPotato

## What this sync is (and isn't)

CouchPotatoServer is a **server-rendered htmx + Alpine.js + Tailwind** app
(Jinja2 templates under `couchpotato/ui/`). It is **not** a React component
library: no `*.jsx`/`*.tsx`, no Storybook, no compiled component `dist/`. The
only `package.json` is the test harness (`couchpotato-ui-tests`).

So the standard `/design-sync` converter (which bundles a compiled component
`dist/` into `_ds_bundle.js`) does not apply. This is an **off-script, tokens +
guidelines only** sync, done by the user's explicit choice. The Claude Design
project carries the design *language* — tokens, brand colours, and the spec —
but **no functional components**. Anyone building in that project makes their own
components and styles them with these tokens/idiom.

## Layout produced (ds-bundle/, gitignored build output)

- `styles.css` — entry; its `@import` closure = Inter font + `tokens/theme.css`
  + `tokens/brand.css`. Rendered designs receive only this closure.
- `tokens/theme.css` — copied from `docs/design-system/theme.css` (surface/text
  `--cp-*` vars for dark + `.light`, plus a11y / scrollbar / fade-in / motion base).
- `tokens/brand.css` — authored; materialises the brand + semantic colours that
  live in the app's `tailwind.config` (`colors.cp.*`) as `var(--cp-*)` so designs
  can use them without the Tailwind config.
- `guidelines/design-system.md` + `guidelines/conformance.md` — copied from
  `docs/design-system/{README,CONFORMANCE}.md` (authoritative spec + checklist).
- `guidelines/screenshots/*.png` — 14 reference screens from `docs/design-system/`.
- `README.md` — `.design-sync/conventions.md` (the header) + `readme-overview.md`.
- `_ds_needs_recompile` — upload sentinel.
- **No** `_ds_bundle.js` / `components/` / `_vendor/` / `_ds_sync.json`. The
  anchor is intentionally omitted (no components to hash), so every re-sync
  rebuilds and re-uploads in full — correct for this shape.

## Re-sync recipe

1. `sh .design-sync/build.sh` — rebuilds `ds-bundle/` from `docs/design-system/`
   + the authored sources in `.design-sync/` (`styles.css`, `brand.css`,
   `conventions.md`, `readme-overview.md`).
2. Upload `ds-bundle/` into project `37a6c3fc-d40d-426c-ac6c-696d8902a252`
   (`config.json`) via the DesignSync tool: `finalize_plan` (writes
   `tokens/** guidelines/** styles.css README.md _ds_needs_recompile`), then
   `write_files` sentinel → content → sentinel re-arm. No `_ds_sync.json`.

## If the product ever ships real React components

Then a true converter sync becomes possible — switch `shape` away from
`tokens-only`, point the converter at the component `dist/`, and the bundle would
carry functional `window.<globalName>.*` components instead of tokens alone.
