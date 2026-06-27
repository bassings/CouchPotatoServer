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
- [ ] `/old/*` returns a redirect to `/`; no page is served from the legacy stack.
- [ ] All 18 audited features are available in the new UI, each with unit + e2e (+ axe) coverage.
- [ ] Legacy assets removed: `views`/`addView`, `clientscript.py`, `static/style/*.scss`,
      non-vendor MooTools `static/scripts/*`, the legacy icon font, old server templates.
- [ ] New UI passes `docs/design-system/CONFORMANCE.md` (tokens, Heroicons, components, a11y).
- [ ] No references to `/old` or the legacy stack remain in code or docs.
