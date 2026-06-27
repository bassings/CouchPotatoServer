# SPEC: UI-PORT-02 — Category Management (modern UI)

## Problem
The modern htmx+Alpine+Tailwind UI (`/`) allows users to SELECT a category for a movie
but provides no way to CREATE, EDIT, DELETE, or REORDER categories. This is CRITICAL gap #2
per the migration backlog in `specs/UI-MIGRATION.md`.

## Approach
- Add a **Categories** tab to the Settings page (`settings.html`).
- All category CRUD is client-side via `fetch()` to the existing API endpoints (no backend changes).
- Pure logic extracted into `couchpotato/static/scripts/ui/category-editor.js` (ES module, tested
  with vitest + Stryker) and exported via the `couchpotato/static/scripts/ui/index.js` barrel onto
  the global `CP.ui` namespace.
- Alpine.js component `categoryEditor()` is defined as a **classic** `<script>` in
  `partials/settings/scripts.html` (same loading pattern as `profileEditor()`).
  The markup lives in `partials/settings/categories.html`.
- Tab wiring: add `'categories'` to `customPanelTabs` and `tabLabels` in `settingsPanel()`,
  and push `'categories'` to `tabOrder` in `init()`. The three guards in `header.html`
  (`!customPanelTabs.includes(activeTab)`) will automatically hide the Advanced toggle,
  Setup Wizard, and auto-save indicator on the categories tab.
- Playwright e2e spec covers load, create, edit, reorder, delete + confirm, validation, a11y.

## API Contract (from `couchpotato/core/plugins/category/main.py`)

### `GET /api/<key>/category.list/`
Response:
```json
{
  "success": true,
  "categories": [
    {
      "_id": "<string>",
      "_t": "category",
      "order": 0,
      "label": "Horror",
      "ignored": "",
      "preferred": "Blu-ray",
      "required": "",
      "destination": "/media/horror"
    }
  ]
}
```

### `POST /api/<key>/category.save/`
Params (form-encoded, flat scalars):
```
id          = "<existing _id>"   (omit for new — backend falls to db.insert on lookup failure)
label       = "Horror"
destination = "/media/horror"
ignored     = "dubbed,swesub"
preferred   = "Blu-ray,DTS"
required    = "DTS"
order       = 3                  (only sent for new; backend preserves stored order on edit)
```
Response: `{ "success": true, "category": { ...saved doc... } }`

### `POST /api/<key>/category.save_order/`
Params (**indexed** bracket keys — NOT repeated `ids[]`, NOT a JSON string):
```
ids[0] = "<id0>"
ids[1] = "<id1>"
```
The dispatcher does `dict(await request.form())` which collapses repeated keys to the last
value. Indexed keys (`ids[0]=…`) are preserved and then expanded by `getParams()`.
Note: categories have no `hidden` parameter (unlike profiles which include `hidden[i]`).

Response: `{ "success": true }`

### `POST /api/<key>/category.delete/`
Params: `id = "<id>"`
Response: `{ "success": bool, "message": "" }`

## Wire-Format Rule
Send `ids[0]=…&ids[1]=…` (indexed) for `save_order`. The E2E test for reorder-persists-
across-reload directly guards this: a repeated-key bug causes `save_order` to silently
succeed on only the last ID and the persistence assertion will fail.

## Acceptance Criteria
- [ ] Settings page shows a **Categories** tab.
- [ ] Categories tab lists all categories with name summary and reorder buttons.
- [ ] "New Category" button opens a modal; user can fill in label, preferred, ignored, required, destination.
- [ ] Edit button opens the modal pre-populated; "Save Changes" persists.
- [ ] Delete button shows a confirm dialog (role=dialog, aria-modal, Escape closes, focus trap).
- [ ] Reorder (up/down) buttons: optimistic, rolls back on failure, serialised via `isReordering`.
- [ ] Reorder persists across tab close/reopen (server round-trip verified in E2E).
- [ ] Toast notifications for save/delete success and error.
- [ ] Spinner during async operations.
- [ ] Validation: label is required; errors shown inline in the modal.
- [ ] Header "Advanced" toggle / Setup Wizard / auto-save indicator are hidden on the Categories tab.
- [ ] All interactive controls have accessible labels (WCAG 2.5.3 Label in Name).
- [ ] Heroicons outline, 24×24, stroke-width="1.5", fill="none".
- [ ] E2E spec uses data-testid="category-edit-modal" / "category-delete-dialog".
- [ ] No backend changes.

## Files Changed
- `specs/UI-PORT-02-categories.md` — this file
- `couchpotato/static/scripts/ui/category-editor.js` — pure logic module (categoryToForm, formToPayload, validateCategory)
- `couchpotato/static/scripts/ui/index.js` — barrel re-export
- `tests/unit/ui/category-editor.spec.ts` — vitest unit tests (TDD: written first)
- `couchpotato/ui/templates/partials/settings/categories.html` — categories markup
- `couchpotato/ui/templates/partials/settings/scripts.html` — `categoryEditor()` + settingsPanel() wiring
- `couchpotato/ui/templates/settings.html` — categories tab include
- `tests/e2e/categories.spec.ts` — Playwright e2e
