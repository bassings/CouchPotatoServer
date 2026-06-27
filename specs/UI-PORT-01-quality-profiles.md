# SPEC: UI-PORT-01 — Quality Profile Management (modern UI)

## Problem
The modern htmx+Alpine+Tailwind UI (`/`) has no quality-profile management screen.
The legacy UI (`/old/`) exposed this via `profile.js` and `quality.js` (MooTools classes).
Users cannot create, edit, reorder, or delete profiles from the new UI, which is a **critical gap**
per the migration backlog in `specs/UI-MIGRATION.md`.

## Approach
- Add a **Profiles** tab to the Settings page (`settings.html`).
- All profile CRUD is client-side via `fetch()` to the existing API endpoints (no backend changes).
- Pure logic extracted into `couchpotato/static/scripts/ui/profile-editor.js` (ES module, tested
  with vitest + Stryker) and exported via the `couchpotato/static/scripts/ui/index.js` barrel onto
  the global `CP.ui` namespace.
- Alpine.js component `profileEditor()` is defined as a **classic** `<script>` in
  `partials/settings/scripts.html` (same loading pattern as `settingsPanel()`/`logsPanel()`, so it
  is synchronously available when Alpine scans `x-data` — a deferred `type="module"` script would
  race Alpine init and leave the panel uninitialised). The markup lives in
  `partials/settings/profiles.html`, whose panel mirrors the **logs tab** visibility mechanism:
  `x-show="activeTab === 'profiles'"` + `x-data` on the same element, lazy `init()` via
  `$watch('$root.activeTab', …)`.
- Playwright e2e spec covers the full create → edit → reorder → delete flow with condition-based
  waits and self-cleanup.

## API Contract (discovered from `couchpotato/core/plugins/profile/main.py` and `quality/main.py`)

### `GET /api/<key>/profile.list/`
Response:
```json
{
  "success": true,
  "list": [
    {
      "_id": "<string>",
      "_t": "profile",
      "label": "<string>",
      "order": 0,
      "core": false,
      "minimum_score": 1,
      "hide": false,
      "qualities":  ["720p", "1080p"],
      "wait_for":   [0, 0],
      "stop_after": [0, 0],
      "finish":     [true, false],
      "3d":         [false, false]
    }
  ]
}
```

### `GET /api/<key>/quality.list/`
Response:
```json
{
  "success": true,
  "list": [
    {
      "identifier": "720p",
      "label": "720p",
      "hd": true,
      "allow_3d": true,
      "size": [3000, 10000],
      "size_min": 3000,
      "size_max": 10000,
      "order": 3
    }
  ]
}
```

### `POST /api/<key>/profile.save/`
Params (form-encoded):
```
id            = "<existing _id>"   (omit to create new)
label         = "My Profile"
order         = 999
minimum_score = 1
wait_for      = 0
stop_after    = 0
types         = JSON array of { quality, finish, "3d" }
```
The backend iterates `kwargs.get("types", [])`, reading `.quality`, `.finish`, `.3d` per entry.
`wait_for` and `stop_after` are top-level params (single values applied to all entries).
`finish` and `3d` are per-type. The first type always gets `finish=True` regardless of submitted value.

Response: `{ "success": true, "profile": { ...saved doc... } }`

### `POST /api/<key>/profile.save_order/`
Params (form-encoded, **indexed** bracket keys — NOT repeated `ids[]`):
```
ids[0]    = "<id1>",  ids[1]    = "<id2>", ...
hidden[0] = 0,        hidden[1] = 1, ...    (0 = visible, 1 = hidden)
```
Use indexed keys because the dispatcher does `dict(await request.form())`,
which collapses repeated keys (`ids[]`) to the last value; `getParams()` then
expands the indexed keys back into ordered lists. Repeated keys would silently
send a single id and break every reorder. (Same rule applies to `profile.save`
`types[i][quality|finish|3d]`.)

Response: `{ "success": true }`

### `POST /api/<key>/profile.delete/`
Params: `id = "<id>"`
Response: `{ "success": true, "message": "" }`

## Acceptance Criteria
- [ ] Settings page shows a "Profiles" tab.
- [ ] Profiles tab lists all profiles with name, quality chips, and finish flags.
- [ ] "New Profile" opens a modal; user can name it and add qualities.
- [ ] Edit button opens the same modal pre-populated; changes save on "Save".
- [ ] Delete button shows a confirm dialog (role=dialog, aria-modal, Escape closes, focus trap).
- [ ] Qualities within a profile are reorderable by up/down keyboard buttons.
- [ ] First quality in a profile always has `finish=true` (enforced in UI).
- [ ] Toast notifications for save/delete success and error.
- [ ] Spinner during async operations.
- [ ] All interactive controls have accessible labels.
- [ ] E2E spec covers: load list, create, edit, reorder quality, delete with confirm.
- [ ] No backend changes.

## Files Changed
- `specs/UI-PORT-01-quality-profiles.md` — this file
- `couchpotato/static/scripts/ui/profile-editor.js` — pure logic module
- `couchpotato/static/scripts/ui/index.js` — barrel re-export (exposes logic on `CP.ui`)
- `tests/unit/ui/profile-editor.spec.ts` — vitest unit tests (TDD: written first)
- `couchpotato/ui/templates/partials/settings/profiles.html` — profiles markup (template only)
- `couchpotato/ui/templates/partials/settings/scripts.html` — `profileEditor()` classic component + guarded tab registration
- `couchpotato/ui/templates/settings.html` — Profiles tab wired in (panel owns its own `x-show`)
- `couchpotato/ui/__init__.py` — `/partial/settings/profiles` route
- `tests/e2e/profiles.spec.ts` — Playwright e2e
