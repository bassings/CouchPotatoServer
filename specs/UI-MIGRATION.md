# SPEC: Retire the legacy `/old` UI; fully adopt the modern design system

## Problem
Two UIs ship today: the modern htmx+Alpine+Tailwind UI (`couchpotato/ui/`, served
at `/`) and the legacy MooTools+SCSS UI (served at `/old/` via the `views` dict and
`clientscript.py`). The legacy stack is unmaintained, carries ~1.5 MB of MooTools/SCSS
and a custom icon font, and duplicates functionality. We are moving to a single,
design-system-conformant UI.

A read-only parity audit found the new UI is **not yet feature-complete** vs `/old`:
18 user-facing gaps (4 critical, 7 high, 7 medium). See the migration backlog below.

## Approach (decided)
1. **Redirect** `/old/* → /` immediately (legacy code stays in-repo as porting reference).
2. **Port all 18 gaps** into the new UI — one TDD'd PR each, in priority order.
3. **Delete** all legacy code/assets once the ports land.
4. **Conform** the new UI to `docs/design-system/README.md` per `docs/design-system/CONFORMANCE.md`.

## Coding standards (every PR)
Security · Accessibility (axe-clean) · Supportability · Maintainability · **TDD**
(failing test first). No new framework / CSS-in-JS / component library. Pure logic
extracted into tested `couchpotato/static/scripts/ui/` modules. Each PR must pass the
9 required CI checks + Claude review before merge.

## Migration backlog (port order)
Critical: quality-profile mgmt · category mgmt · userscript add-via-URL · search-all-wanted + progress.
High: per-movie category · watch toggle · re-add (ignore-previous) · home dashboard · suggestion "mark seen" · release table Size/Provider/Try-next · Trakt+Put.io OAuth.
Medium: quick library scan · manual folder scan · log pagination · notification center · per-movie files view · update-install button · DB-management page.

## Acceptance criteria
- [x] `/old/*` returns a redirect to `/`; no page is served from the legacy stack.
- [ ] All 18 audited features are available in the new UI, each with unit + e2e (+ axe) coverage.
- [x] Legacy assets **mostly** removed (UI-CLEANUP-01, see
      `specs/UI-CLEANUP-01-retire-legacy-assets.md`): `views`/`addView` and the
      unreachable view functions (`apiDocs()`, `databaseManage()`, `manifest()`,
      the legacy `robots()`), the raw SCSS sources (`static/style/*.scss` except
      the compiled `combined.min.css`), the 9 orphaned plugin
      `*.scss` files, non-vendor MooTools raw sources
      (`mootools*.js`, `dynamics.js`, `fastclick.js`, `history.js`,
      `Array.stableSort.js`, `requestAnimationFrame.js`, `couchpotato.js`,
      `api.js`, `page.js`, `block.js`, `page/`, `block/`, `library/`), and the
      dead server templates `api.html`/`database.html` are all deleted.
      **One live chain found during that cleanup and deliberately kept**
      (deleting it would regress a live feature): `couchpotato/core/_base/
      clientscript.py`, its 4 compiled bundles (`combined.min.css`,
      `combined.vendor.min.js`, `combined.base.min.js`,
      `combined.plugins.min.js`), the icon font + Open Sans + Lobster binaries
      under `static/fonts/**` (still `@font-face`-referenced by the served
      `combined.min.css`), `couchpotato/templates/index.html`, and
      `couchpotato.index()` are all still live — `Userscript.iFrame`
      (`couchpotato/core/plugins/userscript/main.py`, the `userscript` API view
      used by the bookmarklet/add-via-URL embed flow) calls `index()` directly,
      which renders `index.html`, which in turn depends on
      `clientscript.get_styles`/`get_scripts`. Retiring this last piece
      requires porting or removing that iFrame call site first — tracked as the
      follow-up UI-CLEANUP-02, gated on the userscript add-via-URL port.
      **Caveat for UI-CLEANUP-02:** the `userscript` API view returns `index()`'s
      HTML through the generic API dispatch, which JSON-encodes `str` results —
      so `GET /api/<key>/userscript` currently responds `application/json` with
      escaped HTML, i.e. the iframe embed may not actually render today (behaviour
      pre-dates this cleanup; only the HTTP 200 was verified, not the rendered
      output). UI-CLEANUP-02 should first establish whether the add-via-URL embed
      is still used/working: if it is already broken or unused, the whole kept
      chain can simply be deleted; if it is to be kept, it should be ported to the
      new UI and served with a real `text/html` response.
- [ ] New UI passes `docs/design-system/CONFORMANCE.md` (tokens, Heroicons, components, a11y).
- [ ] No references to `/old` or the legacy stack remain in code or docs.
