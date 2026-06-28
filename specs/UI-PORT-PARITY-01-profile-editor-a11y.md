# UI-PORT-PARITY-01 — profileEditor() a11y + robustness parity with categoryEditor

## Problem
The category-management port (PR #138) hardened `categoryEditor()` through 19
review rounds, adding a11y and robustness behaviours that its template/blueprint
`profileEditor()` (PR #137) never received. The two components now diverge: the
newer one is correct, the older one carries the gaps. Tracked in the
`profile-editor-a11y-parity-debt` memory note.

All changes below are in the **Alpine component** in
`couchpotato/ui/templates/partials/settings/scripts.html` (the `profileEditor()`
factory) and its template `partials/settings/profiles.html` — NOT in the pure
`profile-editor.js` module (that's TEST-001).

## Fix — port the post-#137 refinements (use #138's commits as the line-by-line blueprint)
Do a systematic `categoryEditor ↔ profileEditor` diff first, then apply the deltas:

1. **WCAG 2.4.3 focus-return** — capture `document.activeElement` on `openNew`/
   `openEdit`/`confirmDelete`; restore on `closeModal`/`cancelDelete` (isConnected-
   guarded). After a confirmed delete, land focus on the "New Profile" button
   (`x-ref`), and pass `skipFocusReturn` from `doDelete` to avoid double-focus.
2. **Focus trap** — selector must include `textarea` and `a[href]`; broaden
   `trapDeleteFocus` to the full focusable set.
3. **Shared `_trapFocusIn(open, refKey, event)` helper** — extract the now-FOUR
   near-identical focus-trap copies into one shared helper used by BOTH editors
   (the cross-component refactor deferred in #138 rounds 9–10). This is the
   consolidation that retires the duplication for good.
4. **`moveProfile` reorder-race** — add the `_reloadGen` generation guard so a
   concurrent `saveProfile()+reload()` during a failing reorder can't clobber the
   fresh list with a stale snapshot. Disable Edit/Delete/move buttons during an
   in-flight save/reorder (`:disabled` adds `|| saving` / `|| isReordering`).
5. **Error toasts** — `:role`/`:aria-live` bind to `alert`/`assertive` for error
   toasts, `status`/`polite` for success.
6. **Optimistic delete + ghost-row guard** — filter the deleted row from
   `this.profiles` before `reload()` so a failed reload can't leave a ghost row
   with live buttons.
7. **Diagnostics** — `load()` and reorder error messages include `e.message`.
8. **Reset latches in `finally`** — `saving`/`deleting` reset in `finally` blocks.

## Acceptance criteria
- [ ] `profileEditor()` behaviourally matches `categoryEditor()` for all of the above.
- [ ] `_trapFocusIn` is defined once and used by both editors; no duplicated trap loops.
- [ ] `tests/e2e/profiles.spec.ts` gains coverage for: focus-return (modal close,
      cancel-delete, post-delete), reorder-failure rollback, save/delete failure
      paths, and load-failure error state — mirroring `categories.spec.ts`.
- [ ] Local gate green: `ruff` n/a (JS), full `tests/unit/ui/` + `profiles`/
      `categories` e2e pass with `--workers=1`.
- [ ] Clears the `profile-editor-a11y-parity-debt` note.

## Files
- `couchpotato/ui/templates/partials/settings/scripts.html` — `profileEditor()` + shared helper.
- `couchpotato/ui/templates/partials/settings/profiles.html` — `x-ref`s, `:disabled`, toast bindings.
- `tests/e2e/profiles.spec.ts` — parity e2e coverage.
- `specs/UI-PORT-PARITY-01-profile-editor-a11y.md` — this file.

## Notes
Depends on TEST-001 only for ordering convenience (do the cheap pure-test PR
first). The categoryEditor implementation is the reference; prefer mirroring its
exact patterns (incl. the Alpine reactive-proxy `_reloadGen` approach over
identity comparison — see #138 round-3).
