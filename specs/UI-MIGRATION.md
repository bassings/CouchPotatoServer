# SPEC: Retire the legacy `/old` UI; fully adopt the modern design system

> **Lifecycle: active**
> **Legacy runtime: retired; `/old/*`: redirect-only.**

> **Status: active parity backlog; legacy runtime retired.** Historical port
> and cleanup specs retain implementation evidence but must identify themselves
> as completed records rather than current work orders.

## Problem
The modern htmx+Alpine+Tailwind UI (`couchpotato/ui/`) is served at `/`. The
former MooTools+SCSS UI is no longer served: `/old/*` redirects to `/`, and its
`views` registry, ClientScript bundler, templates, bundles and plugin static
assets have been removed. The remaining work is feature parity and full design
system conformance in the one shipped UI.

The original read-only parity audit found 18 user-facing gaps (4 critical, 7
high, 7 medium). That list is the audit baseline, not a claim that every item
is still open: quality profiles, categories, add-by-URL and Trakt device
authorisation have since shipped with browser coverage. The remaining items
stay explicit below until their own port work closes them.

## Approach (decided)
1. **Redirect** `/old/* → /` immediately. Retain the audited backlog and git
   history as the porting reference; do not keep an unserved runtime tree.
2. **Port all 18 gaps** into the new UI — one TDD'd PR each, in priority order.
3. **Delete** each legacy layer once its production boundary is proven
   unreachable and every behavior is either replaced or explicitly retained
   in the parity backlog. A structural test prevents the retired plugin static
   tree from returning.
4. **Conform** the new UI to `docs/design-system/README.md` per `docs/design-system/CONFORMANCE.md`.

## Coding standards (every PR)
Security · Accessibility (axe-clean) · Supportability · Maintainability · **TDD**
(failing test first). No new framework / CSS-in-JS / component library. Pure logic
extracted into tested `couchpotato/static/scripts/ui/` modules. Each PR must pass the
9 required CI checks + Claude review before merge.

## Original migration backlog (audit baseline and port order)
Completed highlights: quality-profile management · category management ·
userscript add-via-URL · Trakt device authorisation.

Critical: search-all-wanted + progress.
High: per-movie category · watch toggle · re-add (ignore-previous) · home dashboard · suggestion "mark seen" · release table Size/Provider/Try-next · Put.io OAuth.
Medium: quick library scan · manual folder scan · log pagination · notification center · per-movie files view · update-install button · DB-management page.

## Acceptance criteria
- [x] `/old/*` returns a redirect to `/`; no page is served from the legacy stack.
- [ ] All 18 audited features are available in the new UI, each with unit + e2e (+ axe) coverage.
- [x] Legacy assets **fully retired** (Gap 1 closed). UI-CLEANUP-01 (see
      `specs/UI-CLEANUP-01-retire-legacy-assets.md`) removed `views`/`addView`
      and the unreachable view functions (`apiDocs()`, `databaseManage()`,
      `manifest()`, the legacy `robots()`), the raw SCSS sources
      (`static/style/*.scss` except the then-still-served `combined.min.css`),
      the 9 orphaned plugin `*.scss` files, non-vendor MooTools raw sources
      (`mootools*.js`, `dynamics.js`, `fastclick.js`, `history.js`,
      `Array.stableSort.js`, `requestAnimationFrame.js`, `couchpotato.js`,
      `api.js`, `page.js`, `block.js`, `page/`, `block/`, `library/`), and the
      dead server templates `api.html`/`database.html`. It deliberately kept
      one live chain: `couchpotato/core/_base/clientscript.py`, its 4 compiled
      bundles (`combined.min.css`, `combined.vendor.min.js`,
      `combined.base.min.js`, `combined.plugins.min.js`), the icon font + Open
      Sans + Lobster binaries under `static/fonts/**`, `couchpotato/templates/
      index.html`, and `couchpotato.index()` — because `Userscript.iFrame`
      (`couchpotato/core/plugins/userscript/main.py`) called `index()` directly.

      UI-CLEANUP-02 (see `specs/UI-CLEANUP-02-retire-userscript-embed.md`)
      investigated that chain and found the embed it served was **already
      broken and unused**: the `userscript` API view returned `index()`'s HTML
      through the generic API dispatch, which JSON-encodes `str` results, so
      `GET /api/<key>/userscript` responded `application/json` with escaped
      HTML rather than a renderable iframe — the embed never actually worked
      post-migration. The working resolver (`userscript.add_via_url` /
      `getViaUrl`) is independent of that chain and is ported into the new UI
      by UI-PORT-03. UI-CLEANUP-02 therefore deleted the whole kept chain:
      `Userscript.iFrame`/`getUserScript`/`bookmark`/`getIncludes` and their
      `addApiView` registrations, `couchpotato.index()`, `couchpotato/
      templates/index.html`, `couchpotato/core/_base/clientscript.py`, all 4
      compiled `combined.*` bundles, `static/fonts/**`, and the legacy
      `userscript.js`/`bookmark.js_tmpl`/`template.js_tmpl` assets those
      methods rendered. `userscript.add_via_url` remains registered and
      callable. The legacy asset layer is now fully retired — no
      `clientscript`/`combined.*`/`index.html`/`static/fonts` references
      remain in live code.

      Sonar T14 completed the boundary cleanup by deleting all 20 files under
      `couchpotato/core/**/static`. FastAPI has no mount for that tree, the
      loader skips `static` packages, and no current template or build step
      referenced the files. `tests/unit/test_no_legacy_core_static_assets.py`
      now guards the whole retired class instead of preserving dead files as
      a porting reference.
- [ ] New UI passes `docs/design-system/CONFORMANCE.md` (tokens, Heroicons, components, a11y).
- [x] No live code or current guidance treats `/old` or the legacy stack as an
      available interface. The redirect, its tests and explicitly completed
      historical implementation records may name it.
