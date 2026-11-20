# SEC-005: the saved Jackett API key is only ever sent to the address it was saved for

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** draft
**Lenses run:** security, qa, simplicity, product, design, accessibility, data,
architecture, operability (the nine that ran at `/plan-cycle` on 2026-11-21) ·
**Skipped:** none

The sections above "Acceptance criteria" were hand-edited on 2026-11-21 to
match the criteria and owner decisions D3 and D4, and again the same day after
two independent reviews of the first edit (review round 1: one measured against
the code, one for buildability). Two criteria, AC-SEC-15 and AC-PROD-11, and
several amendments to existing criteria were added by hand in that round; they
are marked "[review round 1]". No lens wrote that wording, so the review cycle
should treat it as untested.

## Problem

CouchPotato stores one Jackett base URL (`torrentpotato.jackett_url`) and one
Jackett API key (`torrentpotato.jackett_api_key`). Nothing ties the two
together. `settings.save` can change `jackett_url` on its own, and the next
parameterless `torrentpotato.jackett_test` or `torrentpotato.jackett_sync`
(`couchpotato/core/media/_base/providers/torrent/torrentpotato.py`,
`_jackettCredentials`) then sends the saved key, in the query string, to the
new address. Someone who can cause that settings write can therefore redirect
the saved key to an address they control, and with the key every tracker
credential Jackett holds.

That redirect is one of two ways the key leaves, and the draft of this spec was
wrong to call it the only one. What is true today:

1. **The redirect path (this spec).** The settings read masks
   `torrentpotato.jackett_api_key` itself, so the stored key cannot be read
   back from that field. The redirect above is how a settings write becomes a
   key disclosure.
2. **The readable copy.** The Jackett sync writes the Jackett key into the
   `pass_key` of every indexer row it adds (`_jackettRowsBuilder`, "Use
   Jackett API key as passkey"), and `torrentpotato.pass_key` is a combined
   option the settings read returns unmasked. The unit test
   `test_torrentpotato_pass_key_still_leaks_and_that_is_recorded` in
   `tests/unit/test_settings_credential_masking.py` pins this. So for an
   install that has pressed Sync, a holder of the CouchPotato API key can read
   the Jackett key in one request to `GET /api/<key>/settings`. **This spec
   does not stop that** (owner decision D3).

SEC-004 closed the request-level form of the redirect (a request that supplies
its own URL must supply its own key, AC-SEC-9 there) and recorded the stored
form as open: item 5 of the "Newznab positional lists" entry in
`docs/technical-debt.md`. It is the same on every released version.

**Who this spec protects:**

- An install that has a Jackett key saved but no synced rows: the key is in the
  masked field only, so the redirect is the only way out, and the binding
  closes it.
- An actor who can cause a settings write but cannot read the response (for
  example a page or script that can send a request but not see the answer),
  on any install: the key can no longer be redirected by that write.

**Who it does not protect:** an install that has synced (the common case),
against a holder of the CouchPotato API key who can read the settings. That
actor reads the Jackett key from `pass_key` and needs no redirect. Hiding
credentials in combined rows on the settings read is the next spec (D3, and the
open debt item "Credentials in combined rows are returned unmasked by the
settings read" in `docs/technical-debt.md`).

**The Origin check does not cover `settings.save`.** The planning cycle did not
verify this; review round 1 measured it. `torrentpotato.jackett_sync` and
`torrentpotato.jackett_test` are in `ORIGIN_CHECKED_API_ROUTES`
(`couchpotato/__init__.py`, lines 913 to 922), and `settings.save` and
`settings.save_group` are not in that set. The API key, in the URL path or the
`X-Api-Key` header, is the only authentication on `/api/`; no session cookie
authenticates it. The review's measurement: a cross-origin GET to
`settings.save` carrying the API key returned 200 and wrote the value, and
without the key it returned 401. CORS stops a page reading the response, not
sending the request. `settings.save_group` is protected by its JSON-only rule
(a cross-origin `text/plain` request returned 400; that `application/json`
needs a preflight the default empty CORS list refuses was read, not measured in
a browser). So a page that knows the API key can write settings but cannot read
the response, which is exactly the actor in the second bullet above, and the
redirect is a real path for that actor.

Who is affected by the redirect: every install with a Jackett key saved. How
often it bites today: never by accident; it is an escalation path, not a
malfunction.

## If we do nothing

The redirect path stays open on every released version, as it has been since
Jackett support was added. It needs the CouchPotato API key (or a way to cause
a settings write), so nothing has been observed going wrong and nothing
changes for an install that is never attacked. The cost is that an actor with
that one capability gets the Jackett key, and through it every tracker
credential Jackett holds, without needing to read any settings. The cost of
doing the work is a narrower claim than the draft made (see D3) and a small,
visible side effect for users (D4). Item 5 of the technical-debt entry stays
open as written.

## Prerequisite (lands on `master` before any slice)

Review round 1 measured a defect on `master` that defeats the control this spec
relies on. Each option's hidden flag is stored as `<option>_internal_meta`, and
`settings.save` recognises that name case-sensitively, so a save of
`<OPTION>_INTERNAL_META` is not recognised as a flag, is accepted, and
overwrites the real flag (for example `rw` over `hidden`). Once the flag is
`rw` the binding can be re-pointed over HTTP in the same breath as the address,
and the migration marker can be blanked and the start-up step re-run. The same
works today on `core.api_key`, so it is a defect independent of SEC-005.

It is fixed first, on `master`, in its own small change, before any SEC-005
slice: `settings.save` refuses any name whose normalised form ends with
`_internal_meta`. SEC-005 does not carry that fix. It carries AC-SEC-15, which
proves the binding and the marker stay unwritable and their flags unchanged
under every variant, in P1.

## Decisions

Owner decisions D1 to D4; conductor decisions are marked as such and are not
owner decisions.

| # | Decision | Date |
|---|---|---|
| D1 | Remember which address the key belongs to (a stored binding), not "ask for the key on every sync". | 2026-11-14 |
| D2 | Upgrade: an existing install's saved key is bound to the address saved at first start after the upgrade. No user action. Accepted risk: an address tampered with before the upgrade is the one trusted. | 2026-11-18 |
| D3 | Build the address binding first, with the claim narrowed. The settings read returns the Jackett key unmasked in every synced row's `torrentpotato.pass_key`, so for an install that has synced, a holder of the CouchPotato API key can read the Jackett key in one request, and this spec does NOT stop that. This spec stops a settings change from redirecting the saved key to another address. Hiding credentials in combined rows on the settings read (Jackett rows and Newznab keys) is the NEXT spec, queued after this one and recorded as its own open debt item. AC-SEC-12 takes its form A. | 2026-11-21 |
| D4 | The standing mismatch notice at the Jackett fields stays dropped (the simplicity veto is accepted). The refusal is shown on the Sync result in Settings and in the wizard; `jackett_test` returns the same `error` to API callers, and no page calls it. Known cost: the key field still reads as saved ("Saved — type to replace") while the key cannot be used with the current address. | 2026-11-21 |
| C1 | **Conductor decision, not an owner decision.** `buttonField.execute()` in the Settings page awaits `flushPendingSaves()` before its action request, so a Sync pressed straight after the key or the address is typed goes out after that save, not before it (review round 1, R2-H1). Ruled out: accepting the race and telling the user to press Sync twice. That leaves the one-step recovery of AC-PROD-3 untrue, and AC-QA-19 could only pass by waiting for the save, which hides the very gap a user hits. Cost: one more file in the budget (AC-SIMP-6, AC-SIMP-11). | 2026-11-21 |

## Proposed shape (as amended to match the criteria)

- A stored binding for the saved key: the plain normalised saved Jackett
  address, not a fingerprint (AC-SIMP-1, AC-ARCH-5). One function produces the
  normalised form, and both the writer and the checker call it. Userinfo is
  part of the normalised form and compared exactly, and the transport's own
  parse is the reference (AC-SEC-2). `_jackettCredentials` hands the same
  normalised string to `getJackettIndexers`, so the string checked is the
  string sent. It is held in a new `torrentpotato`
  option that is not rendered in Settings (AC-ARCH-2, AC-DESIGN-1), beside a
  one-time migration marker (AC-SIMP-2, AC-SEC-8). Both live only in
  `config.ini` (AC-DATA-10).
- The binding is written only by the server, in two places: with the key, in
  the same `config.ini` write, when a non-empty `jackett_api_key` is saved
  (AC-SEC-6, AC-DATA-1, AC-ARCH-7), through a value hook on the existing
  per-option save event (a hook on that event is permitted, AC-SIMP-5); the
  generic internal write sets memory only and the caller saves once
  (AC-ARCH-4). Today a failed per-column save leaves its value in memory
  (debt gap 3), so AC-DATA-1 also asks for a rollback that does not exist yet.
  The binding is also written once at start-up for an install that
  has a key and no binding and has not yet migrated (D2, AC-SEC-8, AC-DATA-5).
  The start-up step runs synchronously, before the server accepts requests
  and before `APP_LOAD` fires (AC-OPS-3), and a failed write there does not
  stop start-up (AC-DATA-6).
- The binding cannot be written or read over HTTP: `settings.save` and
  `settings.save_group` refuse it, and the settings read omits every option
  that is not readable, for any section (AC-SEC-4, AC-SEC-5, AC-ARCH-3), and
  every spelling of the flag's own name is refused too (AC-SEC-15, the
  prerequisite above). Without this the control is decorative: whoever can
  change the address could re-point the binding in the same breath.
- Every use of the *saved* key goes through one function that checks the
  binding against the exact address it is about to be sent to, and refuses on a
  mismatch or a missing binding before any request leaves the process
  (AC-SEC-1, -2, -3, -11, AC-SIMP-4). A request that supplies its own URL and
  key is not checked (AC-SEC-9).
- The refusal is the text fixed in AC-DESIGN-5: "The saved Jackett API key
  cannot be used with this Jackett address. Check the address is your Jackett
  server, then enter the API key again and press Sync again." It asks for the
  address check first because an address change the user did not make is the
  attack this spec exists to stop (AC-PROD-11). It is the API `error` string
  for both causes, and carries neither address nor key. It is shown on the
  Sync result in Settings and in the wizard; `jackett_test` returns the same
  `error` to API callers, and no page calls it. In both themes, announced once
  (AC-A11Y-3, -4). There is no field-level or standing state at the Jackett
  fields (D4). The cost is that the key field still reads as saved while the
  key cannot be used with the current address; the user finds out when they
  press Sync.
- Recovery is one step after the address is checked: enter the key again, press
  Sync, and the key is bound to the address saved at that moment (AC-PROD-3,
  AC-DESIGN-4). The Settings Sync button first sends any pending save, so the
  press does not race the key's own save (C1, AC-SIMP-6). Setting the address
  back to the bound one also works, without re-entering the key (AC-DATA-8).

## Questions answered at planning

1. **Save order** (key before address on the Settings page). Accepted cost, not
   a combined save: that user gets the refusal and recovers by entering the key
   again. Both orders are pinned by a test. The wizard saves in order instead,
   and the Settings Sync button sends any pending save before it acts (C1).
   AC-PROD-4, AC-QA-11, AC-SIMP-7, AC-ARCH-9, AC-QA-19.
2. **Every use of the saved key.** The saved key is read in exactly one
   function, which does the check, and `jackett_test` and `jackett_sync` both
   reach it. A static (syntax-tree) test fails if any other read of that option
   appears, by any route. Stored
   TorrentPotato rows use their own `pass_key`, are not gated, and
   `_isJackettIndexerHost` keeps its own comparison. AC-SEC-11, AC-SIMP-4,
   AC-PROD-7, AC-ARCH-12.
3. **The stored rows** (can `save_group` change a synced row's host while
   keeping its stored key). **Answered by measurement at review round 1, not by
   a criterion.** Driven through the real `save_group` after a real sync,
   trying to change row 0's host to another address while keeping its stored
   key:

   | `pass_key` sent for that row | Result |
   |---|---|
   | the displayed mask (asterisks of the same length) | success; host changed, **stored key overwritten by the mask** |
   | the empty string | success; host changed, stored key gone |
   | the column left out | refused (`missing_column`) |

   A per-column `settings.save` of `host` is also refused. So `save_group`
   cannot carry the stored key to a new host unless the caller already knows
   the key: there is no second redirect path through the rows, and the stored
   rows stay out of scope and unchanged (AC-SIMP-8, AC-SEC-12). A cross-origin
   `text/plain` `save_group` returned 400; the `application/json` preflight
   was read, not measured in a browser. **Warning for the next spec:** a masked
   read plus today's `save_group` would destroy stored keys (the mask is
   written back over the key), so masking and the mask handling in
   `save_group` must ship together (AC-DATA-11).
4. **Fingerprint or plain address.** Plain address. Hashing hides nothing, as
   the address is stored in clear beside it. AC-SIMP-1.
5. **Clearing.** Clearing the key removes the binding in the same write and a
   sync then reports the existing "required" error. Clearing the address leaves
   the binding alone, so a new address with the old key is still refused.
   AC-SEC-7.
6. **Start-up binding (D2).** Runs once per install, gated by a migration
   marker written in the same save, synchronously before the server accepts
   requests; logs one INFO line with no address or key on success and one ERROR
   naming the remedy on failure. Restoring a pre-change `config.ini` binds to
   whatever address that file holds. AC-SEC-8, AC-OPS-3, AC-DATA-5, AC-DATA-6,
   AC-QA-13, AC-DATA-10, AC-OPS-8.

## Not in scope

- A redirect from the saved Jackett forwarding the key (debt item 6), unless a
  lens shows it is the same control at trivial cost.
- Updating the `pass_key` of stored indexers when the Jackett key is rotated
  (debt item 7).
- Moving the key out of the query string. That is Jackett's API.
- Binding Newznab or other providers' keys to their hosts: SEC-004 made each
  row atomic, which is the equivalent control there.
- **Hiding credentials in combined rows on the settings read** (D3): the Jackett
  key held in every synced row's `torrentpotato.pass_key`, and
  `newznab.api_key`. This is the next spec, queued after this one, and is
  recorded as an open item in `docs/technical-debt.md`. Its `save_group`
  question is already measured (question 3 above): it must ship masking and the
  mask handling together.
- **A wizard Sync with an empty key field deletes the saved Jackett key.**
  Existing behaviour on `master`, found at review round 1: `syncJackett` saves
  the URL and then the key from the form on every press, the form is never
  pre-filled, and an empty key clears the saved one. Not changed here (and it
  now also clears the binding, AC-SEC-7). Recorded in the Jackett items of the
  "Newznab positional lists" entry in `docs/technical-debt.md`.
- **The download clients** (SABnzbd, NZBGet, qBittorrent, Transmission): each
  sends saved credentials to a saved host that a settings change can re-point,
  the same shape as this spec. Raised by the architecture lens. Not every path
  was traced, so this list is a pointer, not an inventory. Needs its own spec.
- A standing mismatch notice at the Jackett fields (D4).

## What this replaces

| What goes | Owning lens | Removal criterion |
|---|---|---|
| The sentence in `_jackettCredentials`' docstring saying the saved key is not bound to the saved URL | security | AC-SEC-14 (the sentence is gone, the docstring says the key is only sent to the address it was bound to), with AC-QA-22 for the matching sentence in the module docstring of `tests/unit/test_jackett_saved_key_scope.py` |
| Debt item 5 in `docs/technical-debt.md` ("Newznab positional lists") | product | AC-PROD-9 (closed, with a pointer to the open item) |

Item 5 is closed by this change and replaced by a pointer to the open item
"Credentials in combined rows are returned unmasked by the settings read",
which carries the readable copy (D3). Until the build lands, item 5 is not
touched. Items 6 and 7 stay as they are (AC-SIMP-8).

## What a user will notice

Plain-language list for the people who run this, and for the release notes.
Items 1, 3 and 5 belong in the release notes.

1. **Moving Jackett means fetching its API key again.** After the address
   changes, the saved key is refused until it is entered again. Most people do
   not keep the key; they will open Jackett's dashboard and copy it.
2. **Order on the Settings page matters.** Change the address and let it save,
   then enter the key, then press Sync. Entering the key first and the address
   second is refused (an accepted cost, AC-PROD-4). Pressing Sync straight
   after typing is handled: the button sends any pending save first (C1). The
   wizard just works, because it saves both fields before every sync.
3. **Editing `jackett_url` by hand in `config.ini` now needs the key entered
   again in the app.** This is common in Docker setups.
4. **Running the wizard with Jackett on and the key left blank clears the saved
   key**, and now the stored address binding too. This already happened (it
   deletes the saved key today) and is not new, but it is now one more way
   into the refusal.
5. **Restoring a `config.ini` backup, or running the previous release and
   changing the address there, changes what is trusted** (AC-OPS-8, facts
   three and four).
6. Whether a merge sync after moving Jackett leaves the old rows behind as
   dead indexers: **not checked**.

---

## Acceptance criteria

Written by `/plan-cycle` on 2026-11-21 from nine lens reports (security, qa,
simplicity, product, design, accessibility, data, architecture, operability
all ran; none skipped). 74 criteria survived planning; review round 1 added two
by hand (AC-SEC-15, AC-PROD-11), so **76 criteria** stand. A trailing bracketed
note records a merge or an amendment and is not part of the criterion. Fixture
keys in every test are obvious placeholders such as `test-key-bound`, never
32-character random strings: strings shaped like real Jackett keys are what the
secret scan (`gitleaks`, a required check) flags.

**Owner decision D3 (2026-11-21):** AC-SEC-12 takes its form A. Five lenses
measured that the settings read returns the Jackett key unmasked in every
synced row's `torrentpotato.pass_key`; the spec's claim is narrowed to match,
and masking those rows is the next spec. AC-DATA-11, AC-SIMP-3, AC-SIMP-8 and
AC-SIMP-11 were conditional on that choice and are resolved to the form-A
reading below. Owner decision D4 keeps the field-level notice dropped.
Conductor decision C1 adds the flush before a Settings button action.

### Security

- **AC-SEC-1:** With key K saved while the address was A (so the binding is written for A), a `settings.save` that changes `jackett_url` to a different destination B is followed by a parameterless `torrentpotato.jackett_test` and a parameterless `torrentpotato.jackett_sync`. B is tested separately as each of: another host, another port, the other scheme, another path, and A with a userinfo prefix (`http://A@evil.example`). For every B, each route returns success false with the exact refusal text fixed in AC-DESIGN-5 (so "refused before the network" is told apart from "tried B and failed to connect"), the request recorder sees zero calls, and config.ini is byte-identical by sha256 before and after the call. (merges AC-QA-2, AC-PROD-2 and AC-OPS-2)
- **AC-SEC-2:** `_jackettCredentials` passes the shared normaliser's output to `getJackettIndexers`, which interpolates it unchanged and no longer calls `cleanHost` itself, so the string checked is the string sent. Comparison is on that base address, before `/torznab/all/api?apikey=...` is appended. The transport's own parse (`urllib3.util.parse_url` of the prepared URL) is the reference for what host and port the request reaches, and any address on which `urllib.parse` and that parser disagree about host, port or userinfo is refused. Full userinfo is part of the normalised form and is compared exactly: an address whose userinfo differs from A's, that carries userinfo when A carries none, or that lacks it when A carries some, is refused. Addresses that differ from A only by host letter case, an explicit default port or a trailing slash are treated as A and make exactly one request, to A. Any address whose base has a different scheme, hostname, port or path is refused, as is any address carrying a query or a fragment that A did not carry. [review round 1] The fixtures `http://A#@evil.example`, `http://evil.example#@A`, a trailing-dot host and an IDN host are each refused, with zero requests, when A is a plain host. (merges the comparison rule of AC-DATA-3)
- **AC-SEC-3:** A saved non-empty `jackett_api_key` with no binding present (tested after the one-time migration has run, and separately with the start-up binder never run) makes a parameterless `jackett_test` and `jackett_sync` refuse with the AC-DESIGN-5 text, with zero requests reaching the transport. A missing or empty binding fails closed, and no production code path treats it as a match. (merges AC-QA-4)
- **AC-SEC-4:** (Proved whole in P1: nothing in it needs the guard of P2a. Its last clause, "a parameterless sync behaves exactly as it did before the attempt", is the same before and after the guard, and is re-run against the guard by the AC-SEC-8 sequences in P2b.) The binding and the AC-SEC-8 migration marker cannot be created, changed, emptied or removed over HTTP. Over the real routes with the API key, `settings.save` with section `torrentpotato` and the option's exact name, its upper-case and mixed-case forms and every other spelling that ConfigParser's `optionxform` plus `strip()` folds onto the stored name, each sent with another address's binding value and with the empty string, returns success false. `settings.save_group` for `torrentpotato` with a row carrying the option as an extra column, and `settings.save_group` for any other section naming it, are refused. In every case the config.ini sha256 is unchanged, the in-memory parser holds the prior value, and after the start-up path is re-run on the resulting file a parameterless sync behaves exactly as it did before the attempt. (merges AC-QA-7, AC-QA-8 and AC-DATA-7)
- **AC-SEC-5:** The binding cannot be read over HTTP. With a binding stored for address A and `jackett_url` since set to a different address (so A can only come from the binding), the full serialised JSON body of GET `/api/<key>/settings` (options, values and combine_state) contains neither the binding option's name nor its stored value, asserted by a substring search for both strings. Marking the option `ui-meta` hidden alone does not pass, because `getValues` does not filter hidden options today. The fixture has no `torrentpotato.host` rows, A is not a substring of B, and the test first asserts that A occurs in config.ini only as the binding's value, so the search cannot fail for a reason unrelated to the binding. [review round 1] (merges AC-QA-9)
- **AC-SEC-6:** Only a successful save of a non-empty `jackett_api_key`, and the one start-up migration of AC-SEC-8, writes the binding, and on a key save it is written in the same config.ini write as the key (one `os.replace`). Each of these leaves the stored binding byte-identical in memory and on disk: a refused key save (the displayed mask of asterisks, a save when the option is not writable); a key save whose file write is faulted (an `os.replace` spy raising); any number of `settings.save` calls of `jackett_url` alone; and a `settings.save_group` of the `torrentpotato` rows. With the key bound to A and `jackett_url` since changed to B, a parameterless `jackett_sync` and `jackett_test` after each refused save are still refused with zero requests. [review round 1: the earlier list also named "a control character, a non-text value" as refused key saves. Measured on `master`: such key saves succeed today and are stored, and no criterion here creates those refusals, so they bind like any other key and are not in this list.] (merges AC-DATA-2)
- **AC-SEC-7:** Clearing. Saving `jackett_api_key` empty or blank removes the binding in the same atomic write, so the file never holds a binding with no key after that save, and a parameterless sync then returns the existing "URL and API key are required" error, not the AC-DESIGN-5 text, with no request. Saving `jackett_url` empty does not remove or change the binding, and if the address is then set to B while K is still saved, a sync is refused with zero requests. Saving a new key afterwards binds it to the address saved at that moment, and a sync then succeeds. (merges AC-DATA-9, AC-QA-17 and AC-PROD-6)
- **AC-SEC-8:** The start-up binding (owner decision D2) runs once per install. It is gated by an explicit one-time migration marker written in the same save as the binding, never by the condition "a key and no binding" alone. On an install that has already migrated with K bound to A, each of these HTTP sequences is tested: save url B; clear url then save B; save url B plus a `torrentpotato` save_group; and clear key then save url B. Each of these four is followed by the start-up path running again, once by calling it directly and once with `app.restart` called over HTTP in its place. [review round 1: the open-ended "any sequence that blanks the binding by a route a test can reach" could not fail and is replaced by the explicit pair of runs.] After every one, a parameterless sync refuses with zero requests (or reports no key, after the clear-key case), and the binding still names A or is absent. (merges AC-QA-14)
- **AC-SEC-9:** A request that supplies its own `jackett_url` together with its own `jackett_api_key` is not checked against the binding: with a mismatched binding stored, it sends exactly one request to the supplied URL carrying the supplied key. A request supplying only its own `jackett_api_key` sends that key to the saved URL. In neither case does the saved key appear in any request, and neither writes or alters the binding. The SEC-004 AC-SEC-9 refusal for a supplied URL without a key still holds, and the existing rule-(a) test functions in `tests/unit/test_jackett_saved_key_scope.py` stay green with their bodies unmodified. (merges AC-QA-16)
- **AC-SEC-10:** No value escapes on refusal. For every refusal in AC-SEC-1, AC-SEC-3 and AC-SEC-8, the HTTP response body and every log record captured at DEBUG and above contain none of: address A, address B, either hostname, key K, or the binding's stored value. Each refused request writes exactly one WARNING-level log line, which names the route and a fixed reason code (`mismatch` when the address differs from the bound one, `unbound` when no binding is stored). Proven by driving each case and reading the captured log output, not the log statement. Records are captured from the start of the refused call to its return, and asserted on `record.getMessage()` of the raw record, before any filter (`PrivacyFilter` is off in dev mode and does not redact hostnames). Fixture hostnames are distinct `.invalid` names that appear in no other log line. [review round 1] (merges AC-QA-3, AC-OPS-1 and AC-PROD-8)
- **AC-SEC-11:** Every use of the saved Jackett key passes through the check. Inside `couchpotato/`, the saved `jackett_api_key` setting is read in exactly one function, which also performs the binding check, and both `jackettTest` and `jackettSync` reach it before `getJackettIndexers` is called. A static test, an AST check on any read of that option by any route (single or double quotes, `self.conf`, `Env.setting(..., section='torrentpotato')`, or the generic `_savedJackettSetting(name)` called with a variable name), fails if any other read appears; it is proven by adding a second direct read, watching the test fail, then restoring. Mutation proof: deleting the check from that function turns the AC-SEC-1 test red. (merges AC-QA-18 and AC-ARCH-6)
- **AC-SEC-12:** The scope of the claim is narrowed (owner decision D3). The spec's Problem section, the Jackett section of `docs/reference/API.md` (AC-OPS-8) and the debt entry in `docs/technical-debt.md` say that GET `/api/<key>/settings` returns `torrentpotato.pass_key` unmasked, that every synced row carries the Jackett key there, that SEC-005 therefore does not protect the key from an API-key holder once a sync has run, and that the exposure is recorded as an open item with its condition for revisiting. None of them says that the settings read masks every copy of the key or that the redirect is the one path. [review round 1: stated positively, because `API.md` has never said otherwise and a "no longer says" clause was already satisfied.] (merges AC-PROD-10) [form A of two; form B, masking the rows in this change, was not chosen and is deleted]
- **AC-SEC-13:** Any API route this change adds is reachable only with the CouchPotato API key, is listed in `ORIGIN_CHECKED_API_ROUTES`, and refuses a request carrying no Origin or Referer. Tested with no key (401), with a cross-origin Origin (refused), and with no Origin or Referer (refused). If no route is added, as AC-SIMP-10 requires, this criterion is satisfied by the absence of one in the diff.
- **AC-SEC-14:** Removal: the sentence in the `_jackettCredentials` docstring stating that the saved key is not bound to the saved URL is gone. A grep for "does not bind the saved key" across `couchpotato/` returns no match, and the docstring instead states that the saved key is only sent to the address it was bound to. The security area replaces nothing else.
- **AC-SEC-15:** [review round 1; the prerequisite above lands first] The binding option and the migration marker stay unwritable, and their flags unchanged, after a `settings.save` of every case and whitespace variant of `<name>_internal_meta` for each of them (lower case, upper case, mixed case, with leading and trailing whitespace, with a tab), over POST form, POST JSON and GET. Each is refused (`settings.save` refuses any name whose normalised form ends with `_internal_meta`) and returns success false; in every case the config.ini sha256 is unchanged, the in-memory flag of each option is unchanged, and a following HTTP save of the binding or the marker is still refused. Proven by writing the variants first, then the binding, and watching the binding stay unwritten; the proof is broken by reverting the prerequisite's refusal and watching this test fail.

### QA

- **AC-QA-1:** Happy path, both operations (`jackettTest` and `jackettSync`, parametrised). `jackett_url` U is saved, then `jackett_api_key` K is saved through `settings.save`. A call with no parameters sends exactly one request, its host, port and path are those of U, it carries K, and Test and Sync list or store the indexers exactly as before the change. The request is observed at the transport: the Env `http_opener` request is recorded and HttpClient runs for real, with `provider.urlopen` not stubbed. (merges AC-PROD-1)
- **AC-QA-5:** Normalisation table, driven through the real HttpClient with only `http_opener` replaced. Accepted pairs: the saved URL is bound, then sync is called against an equivalent form, and the transport sees the bound host and port; the equivalent forms are scheme and host case, explicit :80 for http and :443 for https, a trailing slash, and bare `host:9117`, which `cleanHost` turns into http. Refused pairs, with no request reaching the transport: a different port, http versus https, a different path or path prefix, a sibling host, `http://<bound-host>:<port>@evil.invalid`, `http://evil.invalid\@<bound-host>:<port>`, `http://<bound-host>:<port>\@other/`, `http://other#@<bound-host>:<port>`, `http://<bound-host>:<port> @other/` and the trailing-dot host `http://<bound-host>.:<port>`. With a bound address that carries userinfo (`http://test-user:test-pass@<bound-host>:<port>`), the refused pairs include `http://test-user:test-pass@evil.invalid\@<bound-host>:<port>` (Python's `urlsplit` reads the bound host, the transport connects to `evil.invalid`), an address with other userinfo, and the same address with its userinfo removed; the same userinfo, written identically, is accepted and reaches the bound host. [review round 1] Any form the implementation accepts must be shown to reach the bound host at the transport. (merges the fixture corpus of AC-DATA-3)
- **AC-QA-11:** Save order on the Settings page, with the two fields kept as separate saves. Order A: URL U2 is saved, then key K2, then sync, which sends K2 to U2. Order B: key K2 is saved, then URL U2, then sync, which returns the AC-DESIGN-5 refusal with no request. Both orders are pinned, so the answer to spec question 1 cannot drift silently. (carries the test half of AC-PROD-4 and AC-DESIGN-7)
- **AC-QA-12:** Concurrent saves. Two threads save `jackett_url` U2 and `jackett_api_key` K2 at once, released by a barrier, over 50 iterations. In every iteration the following no-parameter sync either sends K2 to the URL the binding was computed from or is refused, and it never sends the key to any other host. The wizard's own save order is pinned separately by AC-ARCH-9. Because 50 random iterations may never hit the window, there is also one deterministic interleave: the URL save is paused, using an event hook, between the key save's read of `jackett_url` and its `save()`. [review round 1]
- **AC-QA-13:** Start-up binder (D2), invoked as a callable without booting the server. Case 1, key and URL present with no binding and no marker: the binder writes the binding, logs exactly one INFO line saying the saved Jackett key was bound to the saved address on first start after upgrade, and the next sync sends K to U. Case 2, a binding is present and the URL was changed since: running the binder again leaves config.ini byte-identical, logs nothing about the binding, and the sync is refused. Case 3, key empty: no `save()` call, config.ini byte-identical by sha256, no binding and no marker written, and nothing is logged. No log line from the binder contains the address, the key or the binding value. (merges AC-OPS-4)
- **AC-QA-15:** Legacy bytes-literal values. config.ini holds `jackett_url` and `jackett_api_key` in the `b'...'` wrapper form with no binding. After the binder runs, a no-parameter sync sends the unwrapped key to the unwrapped host. The binder and the check normalise the stored URL identically.
- **AC-QA-19:** E2E against the real server, with no `page.route` on `torrentpotato.jackett_sync` in these Settings tests (the one stubbed wizard test of AC-A11Y-4 is the only `page.route` on that route in SEC-005's tests). Seed U and K through the API, change the URL through the Settings Jackett URL field, then press Sync Indexers with no wait between the edit and the press. The Sync result shows the exact AC-DESIGN-5 refusal text and not a "Failed to connect" text. A paired test with a matching binding shows no refusal text on the Sync result, so the result is proven in both directions. The key is then re-entered and Sync is pressed with no wait between them: the sync request is observed after the `settings.save` response for the key, and the sync succeeds. [review round 1: the last two sentences of the first form of the criterion are the flush clause of C1, which lands in P1 and is proved there; the refusal-text clauses land in P3.] [the field-level mismatch state in the original wording was vetoed]
- **AC-QA-20:** Fixtures do not hollow out the guard. Existing tests that rely on the saved pair get their binding through a production writer: the start-up binder or a `settings.save` of the key. No file under `tests/` writes the binding option's name or a precomputed binding value directly into config.ini, apart from the hostile-write tests of AC-SEC-4 and AC-SEC-15, the corrupt-binding cases of AC-DATA-5, and the rollback simulations of AC-SEC-3 and AC-DATA-10, each of which writes only the option it names and says so in the test's docstring. The `world` fixture in `tests/unit/test_jackett_saved_key_scope.py` (lines 33 to 46) seeds the saved pair with no binding, so `test_no_parameters_uses_the_saved_url_with_the_saved_key` goes red when the guard lands; the fixture changes under this criterion in the same slice as the guard, and AC-SEC-9's "bodies unmodified" covers test functions, not that fixture. [review round 1]
- **AC-QA-21:** Each guard is shown to be load-bearing. Each break below is applied in turn, the named test is watched fail, and the code is restored; the diff hash of each break is recorded and `__pycache__` is cleared before each run. Breaks: remove the binding comparison (the AC-SEC-1 test fails); treat a missing binding as a match (AC-SEC-3 fails); compare by hostname with `urlparse` and nothing more (the userinfo row in AC-QA-5 fails); drop the `settings.save` refusal (AC-SEC-4 fails); drop the `_internal_meta` refusal of the prerequisite (AC-SEC-15 fails); drop the read filtering (AC-SEC-5 fails); make the binder re-bind when a binding exists (AC-QA-13 case 2 and AC-SEC-8 fail).
- **AC-QA-22:** Removal. The module docstring of `tests/unit/test_jackett_saved_key_scope.py` (lines 4-6) no longer states that someone who can call `settings.save` can change `jackett_url` alone and have the saved key sent to the new URL. A grep of `tests/` for "sends the saved key to the new URL" returns nothing, and the docstring states that a parameterless call is refused when the saved address differs from the one the key was saved for (a reworded sentence alone would pass the grep). No other test in the tree pins the unbound behaviour, so this is QA's only removal.

### Simplicity

- **AC-SIMP-1:** The binding is stored as the normalised Jackett address string itself, not a fingerprint: the diff adds no `hashlib`, `hmac` or `secrets` import and no digest call to torrentpotato.py or settings.py.
- **AC-SIMP-2:** At most two new option names are registered in the `torrentpotato` section: the binding, and the one-time migration marker AC-SEC-8 requires, both protected by the existing `ui-meta` mechanism. No other new option is added: no version marker, no toggle that disables the check, no new section. [amended: AC-SEC-8 overrides the original "no migration marker" clause]
- **AC-SIMP-3:** The diff leaves the bodies of `_refuse_per_column`, `save_group`, `_save_group` and `_registered_ui_value` in `couchpotato/core/settings.py` unchanged (owner decision D3: the combined rows are not masked here). Changes to settings.py are limited to the provider-neutral pieces other criteria require: omitting non-readable options from the settings read (AC-SEC-5, AC-ARCH-3), one internal write method that sets memory only (AC-ARCH-4), the same-write rule, lock and rollback of AC-SEC-6 and AC-DATA-1 in the save path, and any refusal AC-SEC-4 shows the existing `isOptionWritable` path does not already give. The `_internal_meta` refusal of AC-SEC-15 is the prerequisite's, already on `master`, and is not in this diff. [amended: the original froze `saveView` and `getValues`, which security and data criteria need to change]
- **AC-SIMP-4:** The check on the saved key runs in exactly one place, `_jackettCredentials`. The bodies of `jackettTest` and `jackettSync` gain no binding logic of their own. Address normalisation is a single function in torrentpotato.py, and no new module file is created under `couchpotato/`.
- **AC-SIMP-5:** The diff introduces no new event name in any `fireEvent` or `addEvent` call, with one permitted exception: a value hook on the existing per-option save event for `torrentpotato.jackett_api_key` (`setting.save.torrentpotato.jackett_api_key`, of the kind `_core.py` already registers) is not a new event name and is the one provider-side way to put the binding in the same write as the key. The binding is written from that hook and from one start-up step; no `.after` or `.committed` handler writes it. [review round 1: the earlier wording forbade the hook it needs.] [amended: the original `.after` or `.committed` handler would put the binding in a second file write, which AC-SEC-6 and AC-DATA-1 forbid]
- **AC-SIMP-6:** No file under `couchpotato/ui/templates/partials/settings/` changes except two. `scripts.html` changes only so that `buttonField.execute()` awaits `flushPendingSaves()` before its action request (decision C1). `field_types.html` changes only so that the button result region (line 160) is a persistent `role=status` element with dynamic text, as AC-A11Y-3 requires; every other button field keeps its existing E2E green. [review round 1] The refusal reaches the user as the `error` text in the existing button result region (field_types.html:160) and on the wizard's existing result line (wizard.html:1857-1862). The settings read response gains no new field that reports binding state.
- **AC-SIMP-7:** The Settings page keeps saving `jackett_url` and `jackett_api_key` as two separate requests. The settings save machinery in `partials/settings/scripts.html` (`setVal`, the debounce, the save requests) is unchanged apart from the `execute()` flush of AC-SIMP-6, and the save-order case (key typed before address) is handled by the refusal copy alone.
- **AC-SIMP-8:** Nothing outside the saved-key path of `_jackettCredentials` gains a binding: `getHosts`, `_isJackettIndexerHost`, `_searchOnHost` and the stored rows' `host` and `pass_key` handling are unchanged (owner decision D3). Debt items 6 (redirect) and 7 (rotation) remain open in `docs/technical-debt.md`.
- **AC-SIMP-9:** No new dependency: `requirements*.txt`, pyproject, package.json and package-lock.json are unchanged by the diff. (merges AC-ARCH-10)
- **AC-SIMP-10:** No new API endpoint: the number of `addApiView(` calls in torrentpotato.py and settings.py is unchanged.
- **AC-SIMP-11:** The change touches at most 9 files outside `tests/`: torrentpotato.py, settings.py, runner.py (only the one synchronous start-up call AC-OPS-3 requires), wizard.html (only to run the two Jackett saves in order, AC-ARCH-9), `partials/settings/scripts.html` (only the `execute()` flush, AC-SIMP-6), `partials/settings/field_types.html` (only the persistent result region, AC-SIMP-6), `docs/reference/API.md`, `docs/technical-debt.md`, and the spec. The `_internal_meta` refusal of the prerequisite is not in this count. [amended: runner.py added because AC-OPS-3 overrides the app-load placement; review round 1: scripts.html added by decision C1 and field_types.html by the persistent-region wording of AC-A11Y-3, taking the budget from 7 to 9.]

### Product

- **AC-PROD-3:** The user refused under AC-SEC-1 recovers in one step. They check the address (AC-PROD-11), enter the API key again with the address field untouched and press Sync with no wait after typing, and the sync succeeds against the new address (the button first sends the pending key save, decision C1). No restart, no config.ini edit and no clearing of either field is needed.
- **AC-PROD-4:** Question 1 (save order) is answered in the spec as an accepted cost, not a combined save. A user who types the key first and the address second gets the AC-SEC-1 refusal and recovers through AC-PROD-3. The spec's Owner decisions or Not in scope section records this, along with what would have to be true to revisit it (for example, the Settings page gains one save for both fields). [the key-then-address test is AC-QA-11]
- **AC-PROD-5:** Upgrade (D2) needs no user action. Take an install with a saved address, a saved key and previously synced TorrentPotato rows, but no binding, starting from a config.ini fixture without the binding option. After it starts on the new version, Test and Sync succeed against the unchanged address on first use, and a search through the previously synced indexers sends the same requests it did before the upgrade.
- **AC-PROD-7:** The binding gates only uses of the saved `jackett_api_key` (`jackett_test` and `jackett_sync` without a supplied key). Searches through stored TorrentPotato rows build identical requests before and after an address change, because they use each row's own `pass_key`, and a test proves a search against a stored Jackett row is not refused by the binding. (merges AC-OPS-9)
- **AC-PROD-9:** Removal: Jackett item 5 in the "Newznab positional lists" entry of `docs/technical-debt.md` is replaced by one line: "5. Closed by SEC-005: the saved key is only sent to the address it was saved for. The readable copy in synced rows is the separate open item "Credentials in combined rows are returned unmasked by the settings read"." Items 6 (redirect forwards the key) and 7 (pass_key not updated on key rotation) are present with their meaning unchanged, because the spec puts them out of scope. [review round 1: replaces "item 5 is gone", which left no pointer to the open exposure.]
- **AC-PROD-11:** [review round 1] After an address change the user did not make, the refusal prompts a check of the address before the key is re-entered. The text of AC-DESIGN-5 asks the user to check that the address is their Jackett server, then to enter the API key again and press Sync again, in that order (the test asserts the position of the check clause before the re-entry clause), and carries no address, so the Jackett URL field on the same card (Settings) or step (wizard) is where the user looks. Re-entering the key, with the address untouched, binds the key to whatever address is saved at that moment, which is why the check comes first. For API callers of `jackett_test` the same `error` string is returned.

### Design

- **AC-DESIGN-1:** Neither the binding nor the migration marker is ever rendered as a control. On the Settings page's TorrentPotato card, in both themes, the controls between the enable switch and the indexer rows are exactly: Jackett URL (text), Jackett API Key (password), Sync Indexers (button), the same count of inputs as before this change. No input exists whose name, label, accessible name or aria-label refers to the binding or the marker. The wizard's Jackett section also renders exactly its existing URL field, key field and Sync button. (merges AC-A11Y-7)
- **AC-DESIGN-4:** Entering the key again in the API key field and committing it (blur or Enter), after checking the address (AC-PROD-11), is the only recovery path: the next Sync Indexers press, even with no wait, then runs a sync and does not return the refusal. No "trust this address", "rebind" or "keep key" control is added anywhere, and the TorrentPotato card gains no new button. [the field-notice half of the original wording was vetoed]
- **AC-DESIGN-5:** The refusal text is exactly "The saved Jackett API key cannot be used with this Jackett address. Check the address is your Jackett server, then enter the API key again and press Sync again." and it is the API `error` string for both causes (address differs from the bound one, and no binding stored), returned by `jackett_test` to API callers as well as by `jackett_sync`. The API `error` clause closes in P2a and the display clauses in P3. The Sync result line in Settings and the wizard's Jackett result line show it verbatim in the existing danger style (`text-cp-danger`, with the base.html light-mode override), in dark and light themes. It says nothing untrue on either surface or for either cause: it does not send a user to Settings, does not claim the address changed (it asks the user to check it), and carries no address, no key and no internal word such as "binding", "fingerprint" or "normalised". [the exact wording was fixed at synthesis to satisfy this criterion and AC-A11Y-4, and replaces the copy in Proposed shape; review round 1 replaced the wording again with the address-check form of AC-PROD-11]

### Accessibility

- **AC-A11Y-3:** Pressing Sync Indexers with a mismatched or missing binding writes the refusal message into the button's result region exactly once: the `role=status` element is in the accessibility tree, not `display:none`, before the sync response arrives, and its text changes to the refusal exactly once. (Today the region is `x-show="result"` and `execute()` clears the text first, so the region leaves and re-enters the tree together with its text, the "live region created with its content" failure; the change to `field_types.html` in AC-SIMP-6 makes it persistent.) [review round 1] The message is identical to the server's refusal text. Focus stays on the Sync Indexers button and does not move to the body or anywhere else. The button is operable again by keyboard (Enter and Space) once the action ends.
- **AC-A11Y-4:** The Settings Sync Indexers button and the wizard's "Sync Trackers from Jackett" button both show the refusal. The wizard saves the URL then the key before every sync, so it reaches the refusal only if the saved pair changes between those saves and the sync. Its surface is therefore tested with a `page.route` stub on `torrentpotato.jackett_sync` that returns the refusal body, and this is the only `page.route` on that route in SEC-005's tests. With the stub, the refusal reaches the wizard's single status region through `announce()` after the existing "Syncing…" message, so a repeated refusal is announced again. No wizard code is changed for this criterion. [review round 1: replaces the earlier wording, which asked for a "cleared first" announcement the wizard already gives and for a state the real wizard cannot reach.]
- **AC-A11Y-5:** The refusal text meets 4.5:1 contrast in both light and dark themes, measured against the surface it is painted on, on the Settings Sync result and the wizard result line, following the pattern of the refused Newznab field test in `tests/e2e/settings-combined.a11y.spec.ts`. [narrowed: the field-level text and border it also covered were vetoed]
- **AC-A11Y-6:** axe reports zero violations scoped to the TorrentPotato settings card, in both themes, in two states: binding matched, and after a refused sync. The wizard's Jackett step also has zero violations after a refused sync. [narrowed: the standing mismatched-field state was vetoed]
- **AC-A11Y-8:** At a 320 CSS px viewport (the WCAG 1.4.10 equivalent of 1280px at 400% zoom, set with the `mobile-chrome` project or an explicit viewport, since Playwright cannot emulate zoom directly), the sync refusal text reflows without horizontal scrolling and without clipping or overlapping the key input or the Sync button, in both themes. [narrowed: the field-level text was vetoed]
- **AC-A11Y-9:** If the change adds any control, that control has an accessible name that matches its visible text, is reachable by Tab, meets the project's 44x44 CSS px target floor and, where it moves focus, moves it to the `jackett_api_key` input. If no control is added, this criterion is satisfied by its absence.
- **AC-A11Y-10:** Removal: this change replaces nothing in the accessibility area. No existing control or label is removed or superseded, and no live region is removed: the button result region stays, and AC-A11Y-3 makes it persistent.

### Data

- **AC-DATA-1:** Saving a non-empty `jackett_api_key` writes the key and the binding in one parser update and one atomic `save()` inside a single hold of the settings lock, and the `jackett_url` the binding is computed from is read inside that same hold. Proven by a test that forces `os.replace` to raise during a key save, gets `success: false`, asserts config.ini is byte-identical by hash, then performs an unrelated successful `settings.save` and asserts the file still holds the old key and the old binding: neither the new key nor the new binding survives in memory to be persisted by the next writer. With K1 bound to U and the URL since changed to U2, a no-parameter sync after that sequence never sends K1 to any host other than U. Today a failed per-column save leaves its value in memory (debt gap 3: `_saveView` restores memory only on the password and auth paths), so the test starts red on the key alone, whatever the binding code does. This criterion closes that for any option whose `setting.save.<section>.<option>` hook sets a companion option, by snapshotting and restoring both under `_PASSWORD_SAVE_LOCK` (the settings save lock today, which `saveView` holds only for `core.password` and `core.auth_required`), in the style of SEC-004's group-writer rollback. `saveView` takes that lock for such saves by a generic rule, never by section or option name. If the restore is made generic for every option, gap 3 is closed in `docs/technical-debt.md` by the P4 edit. [review round 1] (merges AC-QA-10 and AC-OPS-6)
- **AC-DATA-4:** The binding check and the outbound request use one read of the saved address, with no re-read between check and send. Proven by a test where the provider's `conf('jackett_url')` returns A on its first read and B on any later read: the request either goes to A or is refused, and the request recorder never sees B.
- **AC-DATA-5:** The start-up binding fires only when the AC-SEC-8 marker is absent, `jackett_api_key` is non-empty and the binding option is absent from config.ini. A binding that is present but empty, malformed or for a different address is never written at start-up. Running start-up twice on the same file, the second run calls no `save()` and config.ini is byte-identical by hash afterwards. A start-up on a file whose binding mismatches the saved address leaves it mismatched and the next parameterless sync is refused.
- **AC-DATA-6:** The start-up binding is one atomic save. When that save raises (config.ini not writable), config.ini is byte-identical to before start-up, the server still starts and serves requests, the saved key is not cleared, one ERROR line names the remedy (make config.ini writable and restart, or enter the Jackett API key again in Settings) without address or key, and also without any path: it does not interpolate the exception or its message (an `OSError` text carries the temp file's full path, which `PrivacyFilter` redacts only for a home prefix), and the test asserts the config.ini directory does not appear in it. A parameterless sync is refused as `unbound` for as long as no binding is persisted, and the next start-up that can write persists the binding. (merges AC-OPS-5)
- **AC-DATA-8:** A mismatch or missing-binding refusal is non-destructive: it writes nothing (config.ini hash unchanged), does not clear `jackett_api_key`, does not clear or rewrite the binding, and does not alter any stored torrentpotato row. Setting `jackett_url` back to the bound address makes a parameterless sync succeed, sending K to that address, without the key being entered again. (merges AC-QA-6)
- **AC-DATA-10:** The binding is stored only in config.ini, in the `torrentpotato` section beside the key, so `scripts/backup.sh` captures key and binding in one file and a restore cannot separate them. No database row, separate file or cache holds a copy. Restore cases are executed on copies: first, a pre-SEC-005 config.ini (key, no binding, no marker) binds to its own saved address at first start (D2); second, a SEC-005 config.ini whose `jackett_url` was later edited by an older release that ignores the binding is refused after re-upgrade, not silently re-bound.
- **AC-DATA-11:** This change does not mask `torrentpotato.pass_key` on read (owner decision D3), so it adds no handling of a displayed mask in `settings.save_group`: the diff leaves how `save_group` treats `pass_key` cells unchanged (AC-SIMP-3), and a test already in the tree (`test_torrentpotato_pass_key_still_leaks_and_that_is_recorded`) stays green and unmodified, which records that the cells are still returned unmasked. Checked mechanically: `git diff master...HEAD -- tests/unit/test_settings_credential_masking.py` is empty, and the four `save_group` bodies are unchanged per AC-SIMP-3. [review round 1] The masking, and the `save_group` handling a mask needs (a group save must not write a displayed mask over a stored passkey), belong to the next spec and ship together there. [form A of two; the form-B text, which made this criterion conditional on masking in this change, is deleted]
- **AC-DATA-12:** Removal: nothing in the data area is retired by this change. No table, column, option or file goes, and the change replaces no stored value.

### Architecture

- **AC-ARCH-1:** `couchpotato/core/settings.py` gains no reference to this provider: the count from `grep -ciE 'jackett|torrentpotato' couchpotato/core/settings.py` is no higher after the change than before it (1 at planning). The binding is protected by a generic option-level mechanism, not by a section or option name check in `saveView`, `save_group` or `getValues`. [amended: the original required zero matches, and the file already has one]
- **AC-ARCH-2:** The binding option and the migration marker are declared in the `config` of torrentpotato.py with the existing `'ui-meta': 'hidden'` flag, and the change adds no parallel option flag: no new key such as `server_only`, `internal` or `bound_to` is read by settings.py. `settings.save_group` for the `torrentpotato` section cannot write either, because neither is a combine column.
- **AC-ARCH-3:** `Settings.getValues` omits every registered option whose `isOptionReadable` is False, for any section. Proven by a unit test that registers a hidden option in a section that is not torrentpotato and asserts the option name is absent from `getValues()`, where today it is returned verbatim. No other option in the tree changes its `getValues` output. [AC-SEC-5 extends the same omission to the options half of the read]
- **AC-ARCH-4:** The server writes the binding through one generic Settings method taking (section, option, value) that bypasses UI writability only and still refuses `_internal_meta` options. The method sets the value in memory only and the caller saves once; unlike `clearSessionRotationPending`, it does not call `save()` itself, because a second write would break AC-SEC-6. [review round 1] No method named for Jackett or the binding is added to the Settings class, and torrentpotato.py does not touch the ConfigParser (`.p`) directly.
- **AC-ARCH-5:** Exactly one function produces the normalised Jackett address, and both the binding writer and the binding checker call it. The checker normalises the address in the form `getJackettIndexers` actually sends (after `cleanHost`, userinfo included, AC-SEC-2), so a saved address without a scheme (`jackett.local:9117`) that was bound and is then used is accepted, and `HTTP://Jackett.Local:80/` and `http://jackett.local` compare equal.
- **AC-ARCH-7:** Exactly one function writes the binding. It is reached from the value hook on the existing per-option save event of `torrentpotato.jackett_api_key` (AC-SIMP-5), so that key and binding land in the same config.ini write (AC-SEC-6), never from a `.after` handler (which fires twice, once before the save), and from the one synchronous start-up step of AC-OPS-3. `Settings._saveView` gains no provider-specific code. [amended: the original `.committed` handler and app-load handler gave way to AC-SEC-6, AC-DATA-1 and AC-OPS-3 by precedence]
- **AC-ARCH-8:** The binding state reaches the user through this provider's own API responses (the `jackett_sync` and `jackett_test` refusal), never through the generic settings read: the keys of the `Settings.view()` response are still exactly `options`, `values`, `combine_state`.
- **AC-ARCH-9:** No in-tree client saves `jackett_api_key` concurrently with `jackett_url`: the wizard's finish path (wizard.html around line 1678) awaits the `jackett_url` save before issuing the `jackett_api_key` save, as `syncJackett` already does at 1850-1851. After the wizard's provider step with a new URL and a new key entered, the key is bound to the URL entered in that step on every run, tested with the URL request deliberately delayed, and a subsequent parameterless sync is not refused. The test fails if the two saves are placed back in the same concurrent batch. (merges AC-DESIGN-6 and the wizard half of AC-QA-12)
- **AC-ARCH-11:** No premature generality: the binding helpers live in torrentpotato.py and serve this provider only, with no registry, base-class hook or declarative binding attribute for other providers. Every new function in the diff has at least one non-test caller.
- **AC-ARCH-12:** Removal: this change retires no module, helper or route in the architecture area. `_isJackettIndexerHost` keeps its own comparison deliberately, because it answers "is this row under the Jackett address" for 400 handling, not "may the key go here". Review fails this criterion if the diff leaves a function in torrentpotato.py or settings.py with no remaining caller.

### Operability

- **AC-OPS-3:** The start-up binding (D2) runs synchronously during start-up and is persisted to config.ini before the HTTP server begins accepting requests and before APP_LOAD is fired; it is not registered on an async event. A test asserting call order in the runner (the binding step precedes `_start_uvicorn_or_exit` and `fireEventAsync(APP_LOAD)`) fails if the step is moved after either.
- **AC-OPS-7:** Upgrade does not fail existing installs closed. For each saved-address shape in a fixture table (no scheme such as `localhost:9117`, a trailing slash, an upper-case host, an explicit default port, a path prefix such as `/jackett`, an IPv6 literal), running the start-up binding then a parameterless `jackett_test` reaches the outbound request stage with no refusal, and the URL the request is built from is the one the binding was computed over. Writer half: for every shape in the table, the stored binding equals the shared normaliser's output for that address (proved in P1); the sync half is proved in P2a. [review round 1]
- **AC-OPS-8:** Rollback and restore are written down in `docs/reference/API.md`, in a Jackett section this change adds for `torrentpotato.jackett_test` and `torrentpotato.jackett_sync` (`API.md` documents neither route today), which also documents the AC-DESIGN-5 refusal text and the `mismatch` and `unbound` WARNING reason codes, as four facts. One: the change adds config.ini options only and no database change, so image rollback needs no data step. Two: the previous release ignores the binding and does not expose its value in its settings read. Three: changing the Jackett address while rolled back means the saved key is refused after rolling forward until it is entered again; the same holds for an address changed while on a build that has the binding writer (P1) but not the check. Four: restoring a config.ini backup taken before this change re-arms the first-start binding of D2 to whatever address that backup holds.
- **AC-OPS-10:** Binding state never affects instance health: with the binding missing or mismatched, start-up completes, GET `/` (what the Dockerfile HEALTHCHECK requests) answers without error through the test client, and no ERROR is logged per request or per scheduled tick. The only signals are the WARNING on use of AC-SEC-10 and the Sync result text (or the `error` string for an API caller).
- **AC-OPS-11:** Nothing grows: the change adds a fixed set of config.ini option names (the binding, the migration marker and any `ui-meta` companions) and no table, cache, file or per-request log line beyond the AC-SEC-10 WARNING. Verified by diffing config.ini option names before and after start-up, a key save, and a sync.
- **AC-OPS-12:** Removal: the change retires no metric, alert, job, log line or runbook entry. The operability removal list is empty, stated and not omitted.

### Vetoed at planning

`lens-simplicity` vetoes. Each stands because no owning lens supplied a
criterion that needs the vetoed thing, and none touches security, data loss or
the accessibility floor.

- **The binding as a fingerprint (hash).** Dropped from Proposed shape; the binding is the plain normalised address (AC-SIMP-1). The address already sits in clear in `jackett_url`, so a hash hides nothing and makes a wrong normalisation invisible in config.ini. Security and architecture agreed.
- **A standing mismatch state at the Jackett fields.** Dropped: AC-DESIGN-2, AC-DESIGN-3, AC-DESIGN-9, AC-DESIGN-10, AC-A11Y-1, AC-A11Y-2, and the field-notice halves of AC-DESIGN-4, AC-DESIGN-7, AC-DESIGN-8, AC-QA-19, AC-A11Y-5, AC-A11Y-6 and AC-A11Y-8. The refusal already reaches the user on the Sync result in Settings and in the wizard, with `role=status`; `jackett_test` has no caller in any page. A field state would need the settings read to report binding state, which AC-ARCH-8 and AC-SIMP-6 rule out, plus template, E2E, design and accessibility work for the same message shown earlier. Accepted by the owner (D4, 2026-11-21). Known cost, recorded by design: the key field's placeholder still reads "Saved — type to replace" while the key cannot be used with the current address. With AC-DESIGN-10 gone, the design area replaces nothing.
- **One combined save or a new endpoint for the address and key.** Not adopted (AC-SIMP-7, AC-SIMP-10). The wizard runs its two saves in order (AC-ARCH-9) and the Settings page's key-before-address order is an accepted cost (AC-PROD-4).
- **A binding on stored rows or in `_isJackettIndexerHost`.** Not adopted (AC-SIMP-8, owner decision D3); the combined-credential read is the next spec.

Simplicity vetoes that did NOT stand, because security or data-loss criteria
outrank the veto:

- **"No new refusal or read-filter code in settings.py."** Overridden by AC-SEC-4 and AC-SEC-5. Measured by two lenses: a `ui-meta` hidden option is still returned by `getValues`, and `set()` refuses the server's own write. AC-SIMP-3 was amended.
- **"No migration marker."** Overridden by AC-SEC-8: start-up can be re-run over HTTP through `app.restart`, so "a key and no binding" alone is not a safe trigger. AC-SIMP-2 was amended.
- **"Write the binding from a `.after` or `.committed` handler."** Overridden by AC-SEC-6 and AC-DATA-1: key and binding go in one write. AC-SIMP-5 and AC-ARCH-7 were amended.

Merged without loss (the surviving criterion carries the wording): AC-QA-2,
AC-QA-3, AC-QA-4, AC-QA-6, AC-QA-7, AC-QA-8, AC-QA-9, AC-QA-10, AC-QA-14,
AC-QA-16, AC-QA-17, AC-QA-18, AC-PROD-1, AC-PROD-2, AC-PROD-6, AC-PROD-8,
AC-PROD-10, AC-DESIGN-6, AC-A11Y-7, AC-DATA-2, AC-DATA-3, AC-DATA-7,
AC-DATA-9, AC-ARCH-6, AC-ARCH-10, AC-OPS-1, AC-OPS-2, AC-OPS-4, AC-OPS-5,
AC-OPS-6, AC-OPS-9.

---

## Affected files (expected)

At most nine files outside `tests/` (AC-SIMP-11). The `_internal_meta`
refusal of the prerequisite is a separate change on `master` and is not counted.

- `couchpotato/core/media/_base/providers/torrent/torrentpotato.py` (the
  binding, its normalisation, the check in `_jackettCredentials`, the options)
- `couchpotato/core/settings.py` (omit non-readable options from the read, one
  internal write method, the same-write rule on a key save, any refusal
  AC-SEC-4 needs; the bodies in AC-SIMP-3 stay unchanged)
- `couchpotato/runner.py` (only the one synchronous start-up call, before
  `fireEventAsync(APP_LOAD)` and `_start_uvicorn_or_exit`, AC-OPS-3)
- `couchpotato/ui/templates/wizard.html` (only to run the `jackett_url` and
  `jackett_api_key` saves in order in the finish path, AC-ARCH-9; the wizard
  already announces its result through `announce()` after "Syncing…", so
  AC-A11Y-4 needs no wizard change)
- `couchpotato/ui/templates/partials/settings/scripts.html` (only
  `buttonField.execute()` awaiting `flushPendingSaves()` before its action
  request, decision C1, AC-SIMP-6)
- `couchpotato/ui/templates/partials/settings/field_types.html` (only the
  button result region at line 160 becoming a persistent `role="status"`
  element with dynamic text, AC-A11Y-3; this region is shared by every button
  field on the Settings page, so their existing E2E must stay green)
- `docs/reference/API.md` (the new Jackett section, AC-OPS-8, AC-SEC-12),
  `docs/technical-debt.md`
- this spec
- tests under `tests/unit/`, `tests/integration/`, `tests/e2e/`

**Release notes.** Items 1, 3 and 5 of "What a user will notice" belong in the
release notes for the beta that carries the guard (P2a), and again for the one
that carries the Settings and wizard display (P3).

The Sync result is the button result region at
`partials/settings/field_types.html` line 160, which renders the API `error`
text as it is; the wizard shows it on its existing result line (`wizard.html`,
`jackettSyncResult`) and announces it through `announce()`.

## Delivery slices

*(added by hand on 2026-11-21 from the surviving criteria; no lens wrote it)*

**Rule.** Every merge to `master` publishes a beta that can be promoted, so no
slice may leave `master` worse than it was before the slice. The check that
refuses a key fails closed, so it must never merge before the start-up step
that binds existing installs: otherwise an upgrade would refuse every saved
key. Docs never run ahead of `master`.

A criterion may be split by clause across slices, each part named with the
slice that proves it, as SEC-004 does (for example "AC-SEC-6 (writer clauses)"
in P1 and "AC-SEC-6 (sync clauses)" in P2b). A criterion that is not split is
listed once, whole. The `_internal_meta` prerequisite is not a slice: it lands
on `master` first, and P1 depends on it.

| Slice | Goal | Depends on | ACs closed | Hazard if promoted alone, and how the slice avoids it |
|---|---|---|---|---|
| P1 | Store and write the binding. The hidden binding and migration marker options; the single normalisation function (final in this slice); the one generic `Settings` write method (memory only), with the lock and rollback of AC-DATA-1; the settings read omits non-readable options; a non-empty key save writes key and binding in one write through the value hook; clearing the key removes the binding; the synchronous start-up binder and its `runner.py` call; the wizard awaits the URL save before the key save; `buttonField.execute()` awaits `flushPendingSaves()` (C1). Nothing reads the binding to refuse anything yet. | the `_internal_meta` prerequisite on `master` | AC-SEC-4 (whole); AC-SEC-5; AC-SEC-15; AC-SEC-6 (writer clauses); AC-SEC-7 (writer clauses); AC-SEC-8 (writer clauses); AC-QA-13 (writer clauses); AC-QA-15 (writer clause); AC-QA-19 (flush clause); AC-QA-21 (write-refusal, `_internal_meta` and read-filter breaks); AC-ARCH-2; AC-ARCH-3; AC-ARCH-4; AC-ARCH-5; AC-ARCH-7; AC-ARCH-9; AC-OPS-3; AC-OPS-7 (writer half); AC-DATA-1 (writer clauses); AC-DATA-5 (writer clauses); AC-DATA-6 (start-up clauses); AC-DATA-10 (restore case 1 and single-file storage) | The start-up step writes `config.ini` once on every upgrading install that has a Jackett key saved, an irreplaceable file. Avoided by one atomic save, a failed write that logs and lets start-up continue with the file unchanged (AC-DATA-6, whose start-up clauses are proved here, not later), and the marker so it runs once. The normaliser is final in this slice: P2a may not change its output for any address in the AC-OPS-7 table, because the binding stored here is read by the guard there. Nothing refuses yet, but an address changed on a P1-only build without re-entering the key is refused once the guard lands (AC-OPS-8, fact three). |
| P2a | The guard. `_jackettCredentials` becomes the one reader of the saved key, hands the normalised address to `getJackettIndexers`, and refuses on a mismatch or a missing binding with the AC-DESIGN-5 text as the API `error` (the `jackett_sync` and `jackett_test` routes); the one WARNING per refusal; the docstring and test-docstring removals; the existing `world` fixture gets its binding through a production writer in the same slice. | P1 merged. Any build that has the guard also has the start-up binder, because P2a is built on P1, so an install that skips versions is still bound at first start | AC-SEC-1; AC-SEC-2; AC-SEC-3; AC-SEC-9; AC-SEC-10; AC-SEC-11; AC-SEC-14; AC-QA-1; AC-QA-5; AC-QA-20; AC-QA-21 (comparison breaks); AC-QA-22; AC-PROD-7; AC-PROD-11; AC-DATA-4; AC-DATA-8; AC-OPS-7 (sync half); AC-OPS-10; AC-DESIGN-5 (API error clause) | The highest in the change: a check that fails closed locks a working install out of Sync (and out of `jackett_test` for API callers), and the existing `world` fixture goes red. Avoided by the P1 dependency, by AC-OPS-7 (every saved-address shape reaches the request stage after upgrade), by AC-QA-20 changing the fixture in this slice, and by the mutation proofs of AC-QA-21. Without P3 a user who types the key and presses Sync at once is served by the flush that P1 already carries. |
| P2b | Lifecycle proofs for the guard. No fail-closed code, so P2a never lands with less protection than `master`: clearing and re-saving, the HTTP-sequence and restart proofs, concurrent saves, the upgrade and restore cases. | P2a | AC-SEC-6 (sync clauses); AC-SEC-7 (sync clauses); AC-SEC-8 (sync clauses); AC-QA-11; AC-QA-12; AC-QA-13 (sync clauses); AC-QA-15 (sync clause); AC-QA-21 (binder break); AC-PROD-5; AC-DATA-1 (sync clause); AC-DATA-5 (sync clause); AC-DATA-6 (sync clause); AC-DATA-10 (restore case 2); AC-OPS-11 | A proof that finds a defect in P1 or P2a. Avoided only by running the proofs before either is promoted; P2b adds tests and fixes, never a new refusal. |
| P3 | The refusal where the user reads it: the Settings Sync result and the wizard's Jackett result line show the AC-DESIGN-5 text in both themes, announced once; the button result region is a persistent `role=status`; recovery by checking the address and re-entering the key; E2E and axe. | P2a | AC-QA-19 (refusal-text clauses); AC-DESIGN-1; AC-DESIGN-4; AC-DESIGN-5 (display clauses); AC-PROD-3; AC-A11Y-3; AC-A11Y-4; AC-A11Y-5; AC-A11Y-6; AC-A11Y-8 | A refusal the user cannot see or hear, and a shared result region changed for every Settings button. Avoided by the E2E against the real server with no `page.route` on the sync route in the Settings tests (AC-QA-19), the one stubbed wizard test (AC-A11Y-4), and the existing button-field E2E staying green. Without P3 the refusal shows as the raw `error` text through the existing region, acceptable for a promoted beta. |
| P4 | Last: docs, removals and the whole-change constraints, checked against the cumulative diff. The Jackett section of `docs/reference/API.md` (AC-OPS-8, AC-SEC-12) and the debt entry (item 5 replaced by a pointer, gap 3 closed if the restore is generic). | P1, P2a, P2b, P3 merged | AC-SEC-12; AC-SEC-13; AC-SIMP-1; AC-SIMP-2; AC-SIMP-3; AC-SIMP-4; AC-SIMP-5; AC-SIMP-6; AC-SIMP-7; AC-SIMP-8; AC-SIMP-9; AC-SIMP-10; AC-SIMP-11; AC-PROD-4; AC-PROD-9; AC-A11Y-9; AC-A11Y-10; AC-DATA-11; AC-DATA-12; AC-ARCH-1; AC-ARCH-8; AC-ARCH-11; AC-ARCH-12; AC-OPS-8; AC-OPS-12 | Docs claiming a control that is not on `master`. Avoided by doing them last. AC-SIMP-4, -10 and -11 are cumulative budgets; each earlier slice's review still checks it has not broken one. |

**Placement check** (re-run on 2026-11-21 against the file after review round 1;
the script parses the "ACs closed" column of the table above). 76 criteria are
defined and 76 are placed; none is unplaced and none is placed but undefined.
63 are whole in exactly one slice. 13 are split by clause, each part named and
no clause named twice: AC-SEC-6, -7, -8, AC-QA-13, -15, -19, -21, AC-DATA-1,
-5, -6, -10, AC-OPS-7 and AC-DESIGN-5. Ids touched per slice (a split
criterion counts in each slice it appears in): P1 22, P2a 19, P2b 14, P3 10,
P4 25. The script checks that the clauses are named and unique, not that the
named clause matches the criterion's text; a reader must check that.

- AC-SEC-4 is whole in P1 because nothing in it needs the guard of P2a (see its
  own note).
- AC-QA-20 is in P2a, not P2b: the `world` fixture it changes goes red the
  moment the guard lands, so the fixture must change in the same slice.
- AC-QA-19's flush clause is in P1, so the Settings page never ships a guard
  without the flush that makes recovery one step; its refusal-text clauses are
  in P3.
- AC-PROD-3 is in P3, because its recovery is the end-to-end Settings press.
- AC-A11Y-9 and AC-DESIGN-1 both say "no control is added"; AC-DESIGN-1 is
  closed with the Settings and wizard render checks in P3, AC-A11Y-9 in the
  final review.
- AC-SEC-13 ("no route is added") is satisfied by the absence of one in the
  cumulative diff, so it closes in P4. `torrentpotato.jackett_sync` and
  `torrentpotato.jackett_test` are already in `ORIGIN_CHECKED_API_ROUTES`.
- The `_internal_meta` prerequisite is outside the slices (it lands on `master`
  first); AC-SEC-15 proves it for the binding and the marker in P1.
