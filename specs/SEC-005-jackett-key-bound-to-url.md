# SEC-005: the saved Jackett API key is only ever sent to the address it was saved for

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** draft
**Lenses run:** none yet (draft for `/plan-cycle`) · **Skipped:** none yet

## Problem

CouchPotato stores one Jackett base URL (`torrentpotato.jackett_url`) and one
Jackett API key (`torrentpotato.jackett_api_key`). Nothing ties the two
together. `settings.save` can change `jackett_url` on its own, and the next
parameterless `torrentpotato.jackett_test` or `torrentpotato.jackett_sync`
(`couchpotato/core/media/_base/providers/torrent/torrentpotato.py`,
`_jackettCredentials`) then sends the saved key, in the query string, to the
new address. The settings read masks the key, so this is the one path by which
someone who holds the CouchPotato API key (or a page that can drive a logged-in
browser) can turn "may change settings" into "has the Jackett key", and with it
every tracker credential Jackett holds.

SEC-004 closed the request-level form of this (a request that supplies its own
URL must supply its own key, AC-SEC-9 there) and recorded this stored form as
open: item 5 of the "Newznab positional lists" entry in
`docs/technical-debt.md`. It is the same on every released version.

Who is affected: every install with a Jackett key saved. How often it bites
today: never by accident; it is an escalation path, not a malfunction.

## Owner decisions already made

| # | Decision | Date |
|---|---|---|
| D1 | Remember which address the key belongs to (a stored binding), not "ask for the key on every sync". | 2026-11-14 |
| D2 | Upgrade: an existing install's saved key is bound to the address saved at first start after the upgrade. No user action. Accepted risk: an address tampered with before the upgrade is the one trusted. | 2026-11-18 |

## Proposed shape (for the lenses to challenge)

- A stored binding for the saved key: a fingerprint of the normalised saved
  Jackett address (scheme, lower-cased host, port with the scheme default made
  explicit, path without a trailing slash), held in a new `torrentpotato`
  option that is not rendered in Settings.
- The binding is written only by the server, in two places: when a non-empty
  `jackett_api_key` is saved (bound to the address saved at that moment), and
  once at start-up for an install that has a key and no binding (D2).
- The binding cannot be written or usefully read over HTTP: `settings.save`
  and `settings.save_group` refuse it, and the settings read does not return
  it. Without this the control is decorative: whoever can change the address
  could re-point the binding in the same breath.
- Every use of the *saved* key checks the binding against the address it is
  about to be sent to and refuses on a mismatch or a missing binding, before
  any request leaves the process. The refusal tells the user what to do
  ("The Jackett address changed since the API key was saved. Enter the API key
  again in Settings.") and carries neither address nor key.
- The Settings page shows that state where the user will look: at the Jackett
  fields and on the Sync button's result, in both themes, announced once.

## Questions the planning cycle must answer

1. **Save order.** The Settings page saves `jackett_url` and `jackett_api_key`
   as separate debounced requests. A user who moves Jackett and types the new
   address and then the key is bound correctly; one who types the key first and
   the address second ends with a mismatch and must enter the key again. Is
   that acceptable with clear copy, or do the two fields need one save?
2. **Every use of the saved key.** `jackett_test`, `jackett_sync`, and anything
   else: `_isJackettIndexerHost` reads the saved address; stored TorrentPotato
   rows carry the Jackett key as `pass_key` beside their own host. Enumerate
   them; say which are in scope.
3. **The stored rows.** A synced indexer row stores the Jackett key as its
   `pass_key` next to a host under the Jackett address. Can `settings.save_group`
   change such a row's host while keeping its stored key (for example by
   sending back the masked value)? If yes, that is the same escalation by
   another door and belongs in scope.
4. **Fingerprint or plain address.** Does hashing buy anything, given the
   address is already stored in clear beside it?
5. **Clearing.** What happens to the binding when the key is cleared, and when
   the address is cleared.
6. **Start-up binding (D2).** Exactly when it runs, that it runs once, what it
   logs (no address, no key), and what a restore of an older `config.ini` does.

## Not in scope

- A redirect from the saved Jackett forwarding the key (debt item 6), unless a
  lens shows it is the same control at trivial cost.
- Updating the `pass_key` of stored indexers when the Jackett key is rotated
  (debt item 7).
- Moving the key out of the query string. That is Jackett's API.
- Binding Newznab or other providers' keys to their hosts: SEC-004 made each
  row atomic, which is the equivalent control there.

## What this replaces

| What goes | Owning lens | Removal criterion |
|---|---|---|
| The sentence in `_jackettCredentials`' docstring saying the saved key is not bound to the saved URL | security | to be written |
| Debt item 5 in `docs/technical-debt.md` ("Newznab positional lists") | product | to be written |

---

## Acceptance criteria

*To be written by `/plan-cycle`.*

---

## Affected files (expected)

- `couchpotato/core/media/_base/providers/torrent/torrentpotato.py`
- `couchpotato/core/settings.py` (refusal and read-masking of the binding option)
- `couchpotato/ui/templates/partials/settings/` (the mismatch state)
- `docs/reference/API.md`, `docs/technical-debt.md`
- tests under `tests/unit/`, `tests/integration/`, `tests/e2e/`
