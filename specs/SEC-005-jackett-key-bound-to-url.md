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
match the criteria and owner decisions D3, D4 and D6, after four independent
reviews. Owner decision D7 (2026-11-22) was added by hand after P2 merged, with
three criteria (AC-PROD-12, AC-QA-23, AC-A11Y-11) that no lens wrote; the P3
review round 1 (2026-11-22) then rewrote D7's scope and added D8, D9, C2 and two
criteria (AC-PROD-13, AC-QA-24), also by hand. The criteria were amended by hand in those rounds (marked "[review
round 1]", "[re-check ...]" and "[D6]"), two were added (AC-SEC-15, AC-PROD-11),
and **owner decision D6 retired three criteria** (AC-SEC-8, AC-OPS-3,
AC-DATA-5) and rewrote several others. No lens wrote that wording, so the review
cycle should treat it as untested.

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
  on any install: the key can no longer be redirected by that write, except through
  the outbound proxy settings, for a Jackett on plain http; see gap (j).
  [Amended 2026-11-22, P2 review round 2.]

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
doing the work is a narrower claim than the draft made (see D3), a small,
visible side effect for users (D4), and, after the upgrade, one re-entry of the
key at the next Sync (D6). Item 5 of the technical-debt entry stays open as
written.

## Prerequisite (lands on `master` before any slice)

Review round 1 measured a defect on `master` that defeats the control this spec
relies on. Each option's hidden flag is stored as `<option>_internal_meta`, and
`settings.save` recognises that name case-sensitively, so a save of
`<OPTION>_INTERNAL_META` is not recognised as a flag, is accepted, and
overwrites the real flag (for example `rw` over `hidden`). Once the flag is
`rw` the binding can be re-pointed over HTTP in the same breath as the address.
The same works today on `core.api_key`, so it is a defect independent of
SEC-005.

It is fixed first, on `master`, in its own small change (merged as #612, `b95325142`), before
any SEC-005 slice. As built, `Settings.isOptionMeta` recognises a flag name in
any case and with surrounding whitespace, and `settings.save` refuses such a
name for every section with the error "An option flag cannot be changed through
settings.save. Nothing was saved." Spellings with leading or trailing
whitespace were already refused on `master` by the unsafe-name rule. Since that
fix the flag refusal is checked before the unsafe-name rule, so the
whitespace variants now receive the flag error; AC-SEC-15's revert proof is
unaffected, because on a revert those rows fall back to the unsafe-name
refusal. SEC-005 does not carry that fix. It carries AC-SEC-15, which proves the
binding stays unwritable and its flag unchanged under every variant, in P1.

A second prerequisite was found by the cloud review of this spec and measured
on `master`: `settings.save` passed the caller's spelling of an option name
through, the parser folds the name, and the value hook was dispatched under
the caller's spelling, so a save of `JACKETT_API_KEY` stored the key and ran
no hook. With the writer of this spec that would replace the key and keep the
earlier key's binding. It is fixed on `master` in its own change (merged as
#615, `41e36d007`): `settings.save` handles an option under its registered
name whatever case the caller sends. AC-SEC-6 carries the proof for the key, in P1.

## Decisions

Owner decisions D1 to D9; conductor decisions are marked as such and are not
owner decisions.

| # | Decision | Date |
|---|---|---|
| D1 | Remember which address the key belongs to (a stored binding), not "ask for the key on every sync". | 2026-11-14 |
| D2 | **Superseded by D6.** Upgrade: an existing install's saved key is bound to the address saved at first start after the upgrade. No user action. Accepted risk: an address tampered with before the upgrade is the one trusted. | 2026-11-18 |
| D3 | Build the address binding first, with the claim narrowed. The settings read returns the Jackett key unmasked in every synced row's `torrentpotato.pass_key`, so for an install that has synced, a holder of the CouchPotato API key can read the Jackett key in one request, and this spec does NOT stop that. This spec stops a settings change from redirecting the saved key to another address. [P2 review round 3: see gap (j) for the outbound-proxy exception on plain http] Hiding credentials in combined rows on the settings read (Jackett rows and Newznab keys) is the NEXT spec, queued after this one and recorded as its own open debt item. AC-SEC-12 takes its form A. | 2026-11-21 |
| D4 | The standing mismatch notice at the Jackett fields stays dropped (the simplicity veto is accepted). The refusal is shown on the Sync result in Settings and in the wizard; `jackett_test` returns the same `error` to API callers, and no page calls it. Known cost: the key field still reads as saved ("Saved — type to replace") while the key cannot be used with the current address. | 2026-11-21 |
| D6 | **The automatic start-up binding is dropped, and with it the migration marker and any change to `couchpotato/runner.py`.** Why: the fourth review measured that the start-up binder as specified could never fire on a real install (`registerDefaults` writes every declared option as an empty value before any start-up step can run), which would have locked every upgraded install out when the guard shipped, and it was the third High finding in four rounds to come from the start-up step and its marker. Why it is cheap to drop: only `_jackettCredentials` reads the saved key, and only `torrentpotato.jackett_sync` and `torrentpotato.jackett_test` use it; searches and downloads use each stored row's own `pass_key` and are unaffected. The design: one new option only, the binding (the plain normalised address); empty and absent are one state, "unbound", by value; a non-empty key save writes the key and the binding in one write (an empty binding when the saved address cannot be normalised); an empty key save clears the binding in the same write; an address save never touches the binding; every use of the saved key is refused unless the binding is non-empty and equals the normalised address about to be used. **Accepted cost:** an existing install has a key and no binding, so its first parameterless Sync (or API `jackett_test`) after the guard ships is refused once with the AC-DESIGN-5 text; the user checks the address and enters the key again, which binds it. Searches and downloads continue with no action. The wizard re-saves address then key before every sync, so it binds as it goes. Restoring an older `config.ini`, or rolling back and forward, leaves the key unbound until it is entered again. [Narrowed by the cloud review of the spec, 2026-11-21: see AC-DATA-10's third case and known limit.] Everything fails closed, and nothing is ever bound without the user entering the key. [Amended by the owner at the P1 review, 2026-11-21: one start-up step is allowed after all, the clear of AC-SEC-16. It empties a binding value that config.ini held before this release first ran; it binds nothing, needs no marker of its own and does not touch `couchpotato/runner.py`. See "Spec gaps found at review", gap (f).] | 2026-11-21 |
| C1 | **Conductor decision, not an owner decision.** `buttonField.execute()` in the Settings page awaits a flush of the pending single-option saves of its own section before its action request, so a Sync pressed straight after the key or the address is typed goes out after that save, not before it (review round 1, R2-H1). It flushes no other section and no combine group, so an 8-second Undo window pending in another section survives (re-check round 1, M-A: a panel-wide flush would commit, for example, a removed Newznab row and its key at once). Ruled out: accepting the race and telling the user to press Sync twice. That leaves the one-step recovery of AC-PROD-3 untrue, and AC-QA-19 could only pass by waiting for the save, which hides the very gap a user hits. Extended the same day (re-check round 1, H-B): a refused action (success false) also re-reads the section, as `endAction` does after a success, so the fields show the saved values and "check the address" shows the address the server holds. Ruled out for that: narrowing AC-PROD-11 to "only reliable on a freshly loaded page" with "reload Settings first" in the copy. A protection that depends on the user reloading the page is one they will not apply. Cost: one more file in the budget (AC-SIMP-6, AC-SIMP-11), and one extra settings read after a refused action. Both changes are inside `scripts.html`. Under D6 they ship in P1, **before** the guard (P2), because every existing install meets the refusal once at upgrade. **Closed after the PR #617 review** (it was first recorded as a known gap, re-check round 2, N-6): `saveSingle` removes its pending entry before it sends, so a save whose request had already left when Sync was pressed was invisible to the flush. For the key that only meant a refusal shown once; for the ADDRESS it meant the key could arrive first and the server's binding hook would bind the new key to the old address, persistently. Every single-option save of a section now joins one per-section chain, so a section's saves are sent one at a time in the order they started, and the flush awaits the chain: an in-flight save of the section is awaited before the section's pending saves and the action go out. A refused or failed save does not break the chain, and the chain is dropped once it settles. The wait is bounded, not the request: the next save of the section, and the flush, wait for the save ahead of them to be answered or for 10 seconds (`SAVE_WAIT_DEADLINE_MS`) after that save was SENT, whichever comes first, then go ahead. The clock starts when a request is sent, never while it is queued, so the one-at-a-time order holds at every step; worst case for N saves queued behind stalled ones, the last is sent after N x 10 seconds and the button finishes one deadline after that. The unanswered request is not aborted, because it may still succeed on the server, and its timer is cleared when the save is answered first. **Consequence, accepted [superseded by D7 for the Sync of the same press: the button no longer sends the action after a save of its own section that did not land, so the sentences below about "the Sync of the same press" describe what P1 and P2 shipped and what P3 closes; a LATER press after a deadline is unchanged]:** after a deadline a later save CAN go out ahead of an earlier one that has been sent and not answered, so a key can then be bound to the old address. If the address save later lands, the next Sync is refused and the key is entered again; until it does, or if it never does, the key is bound to and used with the address the server still holds, including by the Sync of the same press (the rows that Sync writes then carry the new key as `pass_key` against the old hosts until a later sync). `master` can already do this, because its two saves are independent; this change narrows the window to a request that has been unanswered for 10 seconds. The key is only ever sent to the address the SERVER held when the key was saved, which after a deadline can be the address from before the edit. The same bound applies to the panel-wide `flushPendingSaves` that the Trakt Start button awaits: it now stops waiting 10 seconds after a save was sent (on `master` an unanswered save left that button waiting for ever), so after a deadline Trakt can be asked for a device code before the credential save has landed. [Closed in P3, 2026-11-22: the panel-wide flush now awaits the section chains too; recorded as conductor decision C2, not as part of D7.] Ruled out: waiting without a deadline, because one request that never answers would then hold every later save of the section, and the button, until the page is reloaded (on `master` it blocked only itself). Other sections and combine groups are untouched. | 2026-11-21 |
| D7 | **In Settings, an action button must not run on top of a save of its own section that did not land.** Today `buttonField.execute()` flushes the section's pending single-option saves and then sends the action even when (i) one of those saves was refused or failed, or (ii) one was still unanswered when its 10-second wait ended; the wizard already stops in case (i). Decision: **stop, in the display slice** (P3). Ruled out: a separate PR (it would ship the Settings Sync with the gap for another beta, and P3 already changes this component), and leaving it (the Sync of that press could bind a key to the address the server still holds and send the key there). **Scope, as amended at P3 review round 1 (2026-11-22):** the owner's words were "did not land". The first build narrowed that to saves "pending or in flight at the press", which was the conductor's wording and not the owner's; it missed the common sequence (the address save refused and ANSWERED, a toast shown, then the key typed and Sync pressed: the key save landed, the server bound the new key to the OLD address, and Sync went there and said "Synced"), and it let a second press run on stale values while the fields still showed the typed text. The rule is now AC-PROD-12: every unsaved single-option value of the button's own section is sent again at the press, and the action is sent only if all of them land. Supersedes: the "Consequence, accepted" of C1 for the Sync of the same press; gap (b); and the "mitigated, not closed" wording of gap (h), which is closed for a press made while a value of the section is unsaved. What D7 does not close is stated in gaps (b), (h) and (s). [P3 review round 3, 2026-11-22: the save bookkeeping behind D7 (the unsaved-value tracking, the batch stop, the open saves and the tickets that decide when a landing clears a value) is guarded by a seeded, model-based randomised test, `tests/unit/ui/settings-save-model.spec.ts`, with seven invariants and a long-soak mode (`docs/development-process.md`); it found, and the code now fixes, that a press held back by an overlapping press's saves (possible only with two buttons in one section, which Settings does not have today) reported a refusal when the cause was an unanswered save: a save that is not sent now resolves to the outcome that stopped its batch. Limit, in plain words (N3): when two saves of one option are both outstanding after a deadline and their answers arrive in the opposite order to the order the server applied them, the page shows the older value as saved while the server holds the newer; this is inside AC-PROD-12's recorded late-overwrite limit, and the page cannot detect it. **Agreed fallback** if this code needs another fix: replace the bookkeeping with the simpler design the reviewer proposed. Unsaved is computed as "the page's value differs from the last accepted value"; a press cancels the timers, drains the chain, sends the differing values in order and stops at the first that does not land. That deletes `saveTickets`, `stillLatest`, `dirtyOpts`, `lastOf`, `openSaves`, the batch object and the carried outcome.] See AC-PROD-12, AC-QA-23, AC-A11Y-11. | 2026-11-22 |
| C2 | **Conductor decision, not an owner decision (P3 review round 1).** The panel-wide `flushPendingSaves`, which the Trakt Start button awaits, did not await the section chains, so a save whose request had already left but not returned was invisible to it (the same defect C1 closed for the section flush). It now awaits the chains too, with the same bounded wait. This is a change to the Trakt Start button's behaviour (it now waits, for at most 10 seconds per save, for a save already sent), made so that the Trakt device-code request is not asked for before the credential save it depends on has been answered. It is not part of D7: the Trakt Start button is a separate component (`traktAuth`, not `buttonField`) and AC-PROD-12's stop does not apply to it. | 2026-11-22 |
| D8 | **The key refusal is reworded** (AC-DESIGN-5). New text, for both causes and both routes: "Check the Jackett URL is right, then copy the API key from your Jackett dashboard, paste it above and press Sync. This is needed once after this update, or after the URL changes." Why (recorded by the owner's reviewer): the old text read as if the address had been tampered with, never said it was a one-off, and never said where the key is; the costly reaction was regenerating the key in Jackett, which breaks searches on rows already imported. The text still puts the address check before the key re-entry (AC-PROD-11). Clause re-check, each against the new text: AC-PROD-11 order (satisfied; the test markers are now "Check the Jackett URL" before "copy the API key"); "does not send a user to Settings" (satisfied); "does not claim the address changed" (satisfied: it asks for a check, and names the URL change only as a condition); "carries no address, no key, no internal word" (satisfied); "paste it above" on the Settings card and on the wizard step (true on both: the key field is above the button). **Two clauses are only partly satisfied and the text was NOT altered, per the owner's decision; they are gap (r).** | 2026-11-22 |
| D9 | **A key Jackett rejects says so.** New fixed text: "Jackett did not accept the API key. Copy it again from your Jackett dashboard." Returned as the API `error` by `torrentpotato.jackett_test` and `torrentpotato.jackett_sync` when (i) the Jackett request is answered with HTTP 401 (today the HTTP client raises and the user sees "Failed to connect to Jackett: HTTPError"), or (ii) the reply contains an `<error>` element, root or nested, whose `code` attribute is exactly "100" (Jackett's invalid-API-key code). Every other error keeps its text. Only the status code and the `code` attribute are read; nothing else from the reply, and never the exception's text (it carries the request URL, which carries the key), is returned or logged. **Neither trigger was observed against a real Jackett: both come from Jackett's documented behaviour as recalled by reviewers.** See AC-PROD-13, AC-QA-24 and gap (q). | 2026-11-22 |

## Proposed shape (as amended to match the criteria)

- **One stored value.** The binding is the plain normalised saved Jackett
  address, not a fingerprint (AC-SIMP-1, AC-ARCH-5), in one new `torrentpotato`
  option that is not rendered in Settings (AC-ARCH-2, AC-DESIGN-1) and lives
  only in `config.ini` (AC-DATA-10). There is no migration marker and no
  start-up binding (D6); the one start-up step is the clear of AC-SEC-16, which
  only ever empties a value. One function produces the normalised form and never
  raises (for an address either parser rejects it returns no value); the writer
  and the checker both call it. Userinfo is part of the normalised form and
  compared exactly, and the transport's own parse is the reference (AC-SEC-2).
  `_jackettCredentials` hands the same normalised string to
  `getJackettIndexers`, so the string checked is the string sent.
- **Empty and absent are one state, "unbound", by value.** `registerDefaults`
  writes every option declared in a provider's `config` as an empty value on
  the first start and the loader saves it (measured at re-check round 3, on
  `loader.run()` and `setDefault`). So an empty binding on disk after any start
  is expected and harmless, and no criterion may rely on the option being
  absent (AC-QA-13).
- **Written only by a key save.** A non-empty `jackett_api_key` save writes the
  key and the binding in one `config.ini` write: the normalised saved address,
  or an empty binding when the saved address cannot be normalised (AC-SEC-6,
  AC-DATA-1, AC-DATA-6, AC-ARCH-7). An empty key save clears the binding in the
  same write (AC-SEC-7). An address save never touches the binding. The
  mechanism is a value hook on the existing per-option save event (permitted,
  AC-SIMP-5); the generic internal write sets memory only and the caller saves
  once (AC-ARCH-4). The hook must not raise for any value the route accepts,
  because `fireEvent` would swallow it and the key would save with no binding
  (AC-SEC-6). Today a failed per-column save leaves its value in memory (debt
  gap 3), so AC-DATA-1 also asks for a rollback that does not exist yet.
- **Not writable or readable over HTTP.** `settings.save` and
  `settings.save_group` refuse the binding, the settings read omits every
  option that is not readable, for any section (AC-SEC-4, AC-SEC-5, AC-ARCH-3),
  and every spelling of the flag's own name is refused too (AC-SEC-15, the
  prerequisite above). Without this the control is decorative: whoever can
  change the address could re-point the binding in the same breath.
- **Every use of the saved key is guarded.** One function checks that the
  binding is non-empty and equals the normalised address about to be used, and
  refuses otherwise before any request leaves the process (AC-SEC-1, -2, -3,
  -11, AC-SIMP-4). Unbound and mismatch give the same user-facing refusal and
  distinct WARNING reason codes (`unbound`, `mismatch`, AC-SEC-10). A request
  that supplies its own URL and key is not checked (AC-SEC-9).
- **Rows a sync writes are built from the address as the user saved it.**
  [Amended 2026-11-22, P2 review round 1.] The check and the request use the
  normalised address (the string checked is the string sent, AC-SEC-2), but the
  rows a sync writes are built from the saved address after `cleanHost`, from the
  same single read that was normalised and checked, exactly as a sync built them
  before the guard (a request that supplies its own URL builds them from that
  URL). [Amended 2026-11-22, P2 review round 2: from the saved address's cleaned text, that is the text the normaliser is given (stripped, wrapper removed), and where that is not ASCII from the normalised form, so that a row can never name a host other than the one the key was bound to, AC-SEC-17.] Why: AC-QA-1 requires Sync to store the indexers exactly as before, the
  merge dedups on exact host strings and `_isJackettIndexerHost` compares exact
  strings, and both are frozen by AC-SIMP-8. Building rows from the normalised
  form duplicated every row on the first merge Sync of an install whose saved
  address had a capital letter or an explicit default port.
- **The refusal** is the text fixed in AC-DESIGN-5 (reworded by owner decision
  D8, 2026-11-22): "Check the Jackett URL is right, then copy the API key from
  your Jackett dashboard, paste it above and press Sync. This is needed once
  after this update, or after the URL changes." It asks for the
  address check first because an address change the user did not make is the
  attack this spec exists to stop (AC-PROD-11). It is the API `error` string
  for both causes, and carries neither address nor key. It is shown on the
  Sync result in Settings and in the wizard; `jackett_test` returns the same
  `error` to API callers, and no page calls it. In both themes, announced once
  (AC-A11Y-3, -4). There is no field-level or standing state at the Jackett
  fields (D4). The cost is that the key field still reads as saved while the
  key cannot be used with the current address; the user finds out when they
  press Sync.
- **Recovery is one step after the address is checked:** enter the key again,
  press Sync, and the key is bound to the address saved at that moment
  (AC-PROD-3, AC-DESIGN-4). The Settings Sync button first sends its own
  section's pending saves, so the press does not race the key's own save, and
  a refused press re-reads the section so the address field shows the address
  the server holds (C1, AC-SIMP-6, AC-PROD-11). Setting the address back to the
  bound one also works, without re-entering the key (AC-DATA-8).
- **Upgrade (D6).** An existing install has a key and no binding, so its first
  Sync after the guard ships is refused once; the user checks the address and
  enters the key, which binds it. Searches and downloads are unaffected
  (AC-PROD-5). The wizard saves address then key before every sync, so it binds
  as it goes (AC-ARCH-9). Restoring an older `config.ini` leaves the key unbound until it
  is entered again; rolling back and forward with nothing changed keeps the
  binding as it was, and a key replaced on the previous release keeps the
  earlier key's binding until it is entered again (AC-DATA-10, AC-OPS-8). Nothing is ever bound without the user entering the key. A binding value that config.ini already held before the upgrade is emptied at the first start (AC-SEC-16), so both statements hold for it too.

## Questions answered at planning

1. **Save order** (key before address on the Settings page). Accepted cost, not
   a combined save: that user gets the refusal and recovers by entering the key
   again. Both orders are pinned by a test. The wizard saves in order instead,
   and the Settings Sync button sends its own section's pending saves before it acts (C1).
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
   sync then reports the existing "required" error. Clearing the address, or
   any address save, leaves the binding alone, so a new address with the old
   key is still refused. AC-SEC-7.
6. **Start-up binding.** **Dropped by D6.** There is no start-up binding, no
   marker and no `runner.py` change. (The P1 review added one start-up step that
   binds nothing: the clear of AC-SEC-16.) An upgraded install is unbound until the
   user enters the key once at its next Sync; nothing is bound automatically.
   AC-QA-13, AC-PROD-5, AC-DATA-10, AC-OPS-8.

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
  now also clears the binding, AC-SEC-7). Recorded as item 10 of the "Newznab
  positional lists" entry in `docs/technical-debt.md`.
- **The download clients** (SABnzbd, NZBGet, qBittorrent, Transmission): each
  sends saved credentials to a saved host that a settings change can re-point,
  the same shape as this spec. Raised by the architecture lens. Not every path
  was traced, so this list is a pointer, not an inventory. Needs its own spec.
- A standing mismatch notice at the Jackett fields (D4).
- Binding an existing install's key automatically at upgrade (D2, dropped by D6).

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
Items 1, 2, 4, 6, 8 and 9 belong in the release notes (item 10 is an edge case, not for them).

1. **After upgrading, the first Sync asks you to check the address and enter the
   Jackett API key once.** Nothing is bound automatically (D6). Searches and
   downloads are unaffected, because they use each indexer's own stored key.
2. **Moving Jackett means fetching its API key again.** After the address
   changes, the saved key is refused until it is entered again. Most people do
   not keep the key; they will open Jackett's dashboard and copy it.
3. **Order on the Settings page matters.** Change the address and let it save,
   then enter the key, then press Sync. Entering the key first and the address
   second is refused (an accepted cost, AC-PROD-4). Pressing Sync straight
   after typing is handled: the button sends its own section's pending saves
   first, and a refused press re-reads the page's fields (C1). A save of the
   section whose request is already in flight when Sync is pressed is awaited
   too, so the key is not sent ahead of an address typed just before it, for up
   to 10 seconds after that address was sent: a request that never answers is
   not waited for longer, and the saves behind it then go ahead. If that
   happens a key can still be bound to the old address. If the address save
   later lands, the next Sync is refused and the key is entered again; until
   it does, or if it never does, the key is bound to and used with the address
   the server still holds, including by the Sync of the same press. `master`
   can already do this, because its two saves are independent; this change
   narrows the window to a request unanswered for 10 seconds. Leaving the page
   while an earlier save of the section is unanswered drops the later save
   queued behind it (before this change both had been sent); the window is
   one save's round trip, plus one deadline for each save queued ahead of it,
   and for the key it fails closed (unbound, refused at the next sync). Saves still on their 500 ms
   timer were already lost on leaving. The wizard just works,
   because it saves both fields before every sync.
4. **Editing `jackett_url` by hand in `config.ini` now needs the key entered
   again in the app.** This is common in Docker setups.
5. **Running the wizard with Jackett on and the key left blank clears the saved
   key**, and now the stored address binding too. This already happened (it
   deletes the saved key today) and is not new, but it is now one more way
   into the refusal.
6. **Restoring an older `config.ini` backup, or running the previous release
   and changing the address there, leaves the key unbound or mismatched** until
   it is entered again. Rolling back and forward with nothing changed leaves
   the key bound to the same address. A key replaced while running the
   previous release keeps the earlier key's address binding; enter the key
   again after upgrading (AC-OPS-8).
7. Whether a merge sync after moving Jackett leaves the old rows behind as
   dead indexers: **not checked**.
8. **A Settings action button no longer runs when a change of yours has not
   saved** (owner decision D7). When you press Sync Indexers (or any other
   action button in Settings), the button first saves every value in its own
   section that the server does not have yet: what you have just typed, and
   anything the server refused or did not answer earlier. It says "Saving…"
   while it does. If one of them does not save, nothing after it is saved and
   the button does not run; it says "Sync Indexers did not run because a change
   above did not save. Fix it if needed, then press Sync Indexers to save and
   run again." (or, if the server has not answered after 10 seconds, "Sync
   Indexers did not run: your changes have not finished saving. If this happens
   again, check CouchPotato is still running."). Pressing the button again tries
   the unsaved values again, so it is the retry. If you do not want a refused
   value, change the field to one that saves, or reload the page (an unsaved
   value lives only in the open page). Before this, the button ran anyway, and a
   Sync could use a key saved for one address against another. What is still
   possible: a value the server never answered may land later, so a later press
   can send it a second time (harmless), and if you changed that field in the
   meantime the late first request could overwrite the newer value (the same
   as on the previous release). A field hidden by the Advanced toggle still
   blocks the button while it holds an unsaved value; show it, or reload. The
   Trakt Start button is not a Settings action button of this kind and is not
   stopped, but it now waits, for at most 10 seconds per save, for a save that
   has already been sent before it asks Trakt for a device code (conductor
   decision C2).
9. **A key Jackett does not accept now says so** (owner decision D9). If Jackett
   answers the key with HTTP 401, or with its invalid-key error, Sync says
   "Jackett did not accept the API key. Copy it again from your Jackett
   dashboard." instead of "Failed to connect to Jackett: HTTPError". Neither
   answer has been seen from a real Jackett yet; both are Jackett's documented
   behaviour as recalled. A 401 from something else in front of Jackett (for
   example a reverse proxy asking for a password) reads the same way, and
   copying the key again will not fix that. Repeated wrong keys no longer stop
   Sync: until 2026-11-22 six in a row against a Jackett reached by name stopped
   Sync, and searches through that Jackett, for 15 minutes; a rejected key
   (HTTP 401) no longer counts towards that cut-off (owner decision 2026-11-22,
   gap (q)).
10. **Order of saving at a press:** the button saves the unsaved values in the
   order each first became unsaved, and a value you retype keeps its place. If
   the key was refused earlier, then you typed the address, then retyped the
   key, the key is saved first (the server binds it to the address it still
   holds) and the address second; the Sync that follows is then refused with the
   "Check the Jackett URL" text, so nothing goes to the wrong place, and the key
   is entered again.

---

## Acceptance criteria

Written by `/plan-cycle` on 2026-11-21 from nine lens reports (security, qa,
simplicity, product, design, accessibility, data, architecture, operability
all ran; none skipped). 74 criteria survived planning; review round 1 added two
by hand (AC-SEC-15, AC-PROD-11), making 76. **Owner decision D6 retired three**
(AC-SEC-8, AC-OPS-3, AC-DATA-5), each left as a one-line stub so ids are not
reused, so 73 stood, and the P1 review added one by hand (AC-SEC-16), so 74 stood, and the P2 review added one by hand (AC-SEC-17), so 75 stood, and owner decision D7 added three by hand (AC-PROD-12, AC-QA-23, AC-A11Y-11), so 78 stood, and decision D9 added two (AC-PROD-13, AC-QA-24), so **80 live criteria** stand: security 16, qa 12, simplicity 11,
product 8, design 3, accessibility 8, data 7, architecture 10, operability 5.
A trailing bracketed note records a merge or an amendment and is not part of
the criterion. Fixture keys in every test are obvious placeholders such as
`test-key-bound`, never 32-character random strings: strings shaped like real
Jackett keys are what the secret scan (`gitleaks`, a required check) flags.

**Owner decision D3 (2026-11-21):** AC-SEC-12 takes its form A. Five lenses
measured that the settings read returns the Jackett key unmasked in every
synced row's `torrentpotato.pass_key`; the spec's claim is narrowed to match,
and masking those rows is the next spec. AC-DATA-11, AC-SIMP-3, AC-SIMP-8 and
AC-SIMP-11 were conditional on that choice and are resolved to the form-A
reading below. Owner decision D4 keeps the field-level notice dropped.
Conductor decision C1 adds the flush before a Settings button action. Owner
decision D6 drops the start-up binding. Owner decision D7 (2026-11-22) makes a
Settings button stop when a save of its own section did not land.

**Retired by D6 (2026-11-21):** AC-SEC-8, AC-OPS-3, AC-DATA-5 (wholly), and the
start-up, marker or binder clauses removed from AC-SEC-3, AC-SEC-4, AC-SEC-6,
AC-SEC-7, AC-SEC-10, AC-SEC-15, AC-QA-13, AC-QA-15, AC-QA-20, AC-QA-21,
AC-SIMP-2, AC-SIMP-3, AC-SIMP-5, AC-SIMP-11, AC-PROD-5, AC-DESIGN-1,
AC-DATA-1, AC-DATA-6, AC-DATA-10, AC-ARCH-2, AC-ARCH-5, AC-ARCH-7, AC-OPS-7,
AC-OPS-8 and AC-OPS-11. Findings of the third re-check that fall away with the
start-up step: M4 (a start-up exception is non-fatal), L1 (the marker after a
key clear) and L2 ("no path inside the app" in AC-DATA-5).

### Security

- **AC-SEC-1:** With key K saved while the address was A (so the binding is written for A by the key save), a `settings.save` that changes `jackett_url` to a different destination B is followed by a parameterless `torrentpotato.jackett_test` and a parameterless `torrentpotato.jackett_sync`. B is tested separately as each of: another host, another port, the other scheme, another path, and A with a userinfo prefix (`http://A@evil.example`). For every B, each route returns success false with the exact refusal text fixed in AC-DESIGN-5 (so "refused before the network" is told apart from "tried B and failed to connect"), the request recorder sees zero calls, and config.ini is byte-identical by sha256 before and after the call. (merges AC-QA-2, AC-PROD-2 and AC-OPS-2)
- **AC-SEC-2:** `_jackettCredentials` passes the shared normaliser's output to `getJackettIndexers`, which interpolates it unchanged and no longer calls `cleanHost` itself, so the string checked is the string sent. Comparison is on that base address, before `/torznab/all/api?apikey=...` is appended. The transport's own parse (`urllib3.util.parse_url` of the prepared URL) is the reference for what host and port the request reaches, and any address on which `urllib.parse` and that parser disagree about host, port or userinfo is refused. Full userinfo is part of the normalised form and is compared exactly: an address whose userinfo differs from A's, that carries userinfo when A carries none, or that lacks it when A carries some, is refused. Addresses that differ from A only by host letter case, an explicit default port or a trailing slash are treated as A and make exactly one request, to A. Any address whose base has a different scheme, hostname, port or path is refused, as is any address carrying a query or a fragment that A did not carry. [review round 1] The fixtures `http://A#@evil.example`, `http://evil.example#@A`, a trailing-dot host and an IDN host are each refused, with zero requests, when A is a plain host. (merges the comparison rule of AC-DATA-3)
- **AC-SEC-3:** A saved non-empty `jackett_api_key` with an empty or absent binding (an unbound key: a pre-upgrade file, the same file after `registerDefaults` has written the option empty, or a binding cleared by editing the file) makes a parameterless `jackett_test` and `jackett_sync` refuse with the AC-DESIGN-5 text, with zero requests reaching the transport. An absent or empty binding fails closed, and no production code path treats it as a match, including a binding that is empty because the saved address could not be normalised. A saved key that is empty after stripping whitespace counts as no key and gets the AC-SEC-7 "URL and API key are required" error, not this refusal; the guard therefore strips the saved key before deciding (on `master` only a supplied key is stripped, and a key saved as spaces stays in memory as spaces until restart). A falsy non-text submission (JSON `0`, `false`, `null`, `[]`) is held in memory as that object until restart and on disk as its text; it may be read as no key before the restart and as a key after it, and in both a parameterless request sends nothing unless the binding matches. (merges AC-QA-4) [D6; readiness check round 4]
- **AC-SEC-4:** (Proved whole in P1: nothing in it needs the guard of P2.) The binding cannot be created, changed, emptied or removed over HTTP. Over the real routes with the API key, `settings.save` with section `torrentpotato` and the option's exact name, its upper-case and mixed-case forms and every other spelling that ConfigParser's `optionxform` plus `strip()` folds onto the stored name, each sent with another address's binding value and with the empty string, returns success false. `settings.save_group` for `torrentpotato` with a row carrying the option as an extra column, and `settings.save_group` for any other section naming it, are refused. In every case the config.ini sha256 is unchanged and the in-memory parser holds the prior value. (merges AC-QA-7, AC-QA-8 and AC-DATA-7) [D6: the marker and the "start-up path re-run" clause are gone]
- **AC-SEC-5:** The binding cannot be read over HTTP. With a binding stored for address A and `jackett_url` since set to a different address (so A can only come from the binding), the full serialised JSON body of GET `/api/<key>/settings` (options, values and combine_state) contains neither the binding option's name nor its stored value, asserted by a substring search for both strings. Marking the option `ui-meta` hidden alone does not pass, because `getValues` does not filter hidden options today. The fixture has no `torrentpotato.host` rows, A is not a substring of B, and the test first asserts that A occurs in config.ini only as the binding's value, so the search cannot fail for a reason unrelated to the binding. [review round 1] (merges AC-QA-9)
- **AC-SEC-6:** Only a successful save of a non-empty `jackett_api_key` writes a non-empty binding, and it is written in the same config.ini write as the key (one `os.replace`): the normalised saved address, or an empty binding when the saved address cannot be normalised (AC-DATA-6). (Writer clauses, P1) `fireEvent` logs and discards a value hook's exception and the save then stores the submitted key, so the hook must not raise for any value the route accepts: the save is made under the registered name and again under upper-case and mixed-case spellings (`JACKETT_API_KEY`, `Jackett_Api_Key`), through the real route, and the binding is rewritten in each (with the key bound to A and the address since changed to B, a key save under any spelling leaves the binding B, never A; reverting the second prerequisite makes these rows fail); a parametrised key save of plain text, a control character, a non-text value and a blank value finds, for each non-empty one, the key and the binding in the file after the one write, and for the blank value the key and the binding empty. The stored binding is byte-identical in memory and on disk after: a refused key save (the displayed mask of asterisks, a save when the option is not writable); a key save whose file write is faulted (an `os.replace` spy raising); any number of `settings.save` calls of `jackett_url` alone; and a `settings.save_group` of the `torrentpotato` rows. (Sync clauses, P2) With the key bound to A and `jackett_url` since changed to B, a parameterless `jackett_sync` and `jackett_test` after each refused save are still refused with zero requests. [review round 1: the earlier list also named "a control character, a non-text value" as refused key saves. Measured on `master`: such key saves succeed today and are stored, and no criterion here creates those refusals, so they bind like any other key.] (merges AC-DATA-2) [D6: marker and start-up migration removed; the hook clause is re-check round 3, M1]
- **AC-SEC-7:** Clearing. (Writer clauses, P1) Saving `jackett_api_key` empty or blank clears the binding in the same atomic write, so the file never holds a binding with no key after that save; saving `jackett_url` empty, or any address save, does not remove or change the binding; saving a new key afterwards binds it to the address saved at that moment. (Sync clauses, P2) After the key is cleared, a parameterless sync returns the existing "URL and API key are required" error, not the AC-DESIGN-5 text, with no request; if the address is set to B while K is still saved, a sync is refused with zero requests; and after a new key is saved, a sync succeeds. (merges AC-DATA-9, AC-QA-17 and AC-PROD-6)
- **AC-SEC-8:** retired by D6 (2026-11-21): start-up binding and marker dropped.
- **AC-SEC-9:** A request that supplies its own `jackett_url` together with its own `jackett_api_key` is not checked against the binding: with a mismatched binding stored, and again with the binding empty (every upgraded install after its first start, AC-ARCH-2: reached through `registerDefaults`) and with it absent (a config.ini fixture without the option), neither written directly (AC-QA-20), it sends exactly one request to the supplied URL carrying the supplied key. A request supplying only its own `jackett_api_key` sends that key to the saved URL; the key-alone case is run in the same three binding states. In neither case does the saved key appear in any request, and neither writes or alters the binding. The SEC-004 AC-SEC-9 refusal for a supplied URL without a key still holds, and the existing rule-(a) test functions in `tests/unit/test_jackett_saved_key_scope.py` stay green with their bodies unmodified. (merges AC-QA-16)
- **AC-SEC-10:** No value escapes on refusal. For every refusal in AC-SEC-1 and AC-SEC-3, the HTTP response body and every log record captured at DEBUG and above contain none of: address A, address B, either hostname, key K, or the binding's stored value. Each refused request writes exactly one WARNING-level log line, which names the route and a fixed reason code (`mismatch` when the binding is non-empty and the address differs from it, `unbound` when the binding is empty or absent). Proven by driving each case and reading the captured log output, not the log statement. Records are captured from the start of the refused call to its return, and asserted on `record.getMessage()` of the raw record, before any filter (`PrivacyFilter` is off in dev mode and does not redact hostnames). Fixture hostnames are distinct `.invalid` names that appear in no other log line. [review round 1] (merges AC-QA-3, AC-OPS-1 and AC-PROD-8)
- **AC-SEC-11:** Every use of the saved Jackett key passes through the check. Inside `couchpotato/`, the saved `jackett_api_key` setting is read in exactly one function, which also performs the binding check, and both `jackettTest` and `jackettSync` reach it before `getJackettIndexers` is called. A static test, an AST check on any read of that option by any route (single or double quotes, `self.conf`, `Env.setting(..., section='torrentpotato')`, or the generic `_savedJackettSetting(name)` called with a variable name), fails if any other read appears; it is proven by adding a second direct read, watching the test fail, then restoring. Mutation proof: deleting the check from that function turns the AC-SEC-1 test red. (merges AC-QA-18 and AC-ARCH-6)
- **AC-SEC-12:** The scope of the claim is narrowed (owner decision D3). The spec's Problem section, the Jackett section of `docs/reference/API.md` (AC-OPS-8) and the debt entry in `docs/technical-debt.md` say that GET `/api/<key>/settings` returns `torrentpotato.pass_key` unmasked, that every synced row carries the Jackett key there, that SEC-005 therefore does not protect the key from an API-key holder once a sync has run, and that the exposure is recorded as an open item with its condition for revisiting. None of them says that the settings read masks every copy of the key or that the redirect is the one path. [review round 1: stated positively, because `API.md` has never said otherwise and a "no longer says" clause was already satisfied.] (merges AC-PROD-10) [form A of two; form B, masking the rows in this change, was not chosen and is deleted] [Note, 2026-11-22, P2 review round 2: every place AC-SEC-12 names that says the key cannot be redirected by a settings write must carry the same qualifier as the Problem section, "except through the outbound proxy settings, for a Jackett on plain http; see gap (j)". This is accuracy only, not more than AC-SEC-12 already requires of P4.]
- **AC-SEC-13:** Any API route this change adds is reachable only with the CouchPotato API key, is listed in `ORIGIN_CHECKED_API_ROUTES`, and refuses a request carrying no Origin or Referer. Tested with no key (401), with a cross-origin Origin (refused), and with no Origin or Referer (refused). If no route is added, as AC-SIMP-10 requires, this criterion is satisfied by the absence of one in the diff.
- **AC-SEC-14:** Removal: the sentence in the `_jackettCredentials` docstring stating that the saved key is not bound to the saved URL is gone. A grep for "does not bind the saved key" across `couchpotato/` returns no match, and the docstring instead states that the saved key is only sent to the address it was bound to. The security area replaces nothing else.
- **AC-SEC-15:** [review round 1; the prerequisite above lands first] The binding option stays unwritable, and its flag unchanged, after a `settings.save` of every case and whitespace variant of `<name>_internal_meta` for it (lower case, upper case, mixed case, with leading and trailing whitespace, with a tab), each sent with the value `rw`, the value that would make the option writable, over POST form, POST JSON and GET. Each is refused (`settings.save` refuses any name whose normalised form ends with `_internal_meta`) and returns success false. The whitespace and tab variants are refused today by the unsafe-name rule and stay as regression rows; the revert proof is carried by the case variants (upper and mixed case), and the test names which rows go red under it. [re-check round 1] In every case the config.ini sha256 is unchanged, the in-memory flag of the option is unchanged, and a following HTTP save of the binding is still refused. Proven by writing the variants first, then the binding, and watching the binding stay unwritten; the proof is broken by reverting the prerequisite's refusal and watching this test fail. [D6: the marker is gone]
- **AC-SEC-16:** [added at the P1 review, 2026-11-21, owner decision; see gap (f)] (P1) A binding value that config.ini held before this release first ran is never trusted. When `registerDefaults` declares the access flag of a non-readable (`hidden`) option and config.ini as loaded holds a value for that option but no flag for it, the option's value is set to empty in that same pass, before any request is served; when the flag is already present the value is left exactly as it is. The rule is generic and lives in `couchpotato/core/settings.py` with no Jackett name in it; the binding is the only `hidden` option in the tree. It is not a binder: it never writes a non-empty value, and nothing else runs at start-up. Tests drive the real `registerDefaults` over real config files: (a) a file from before this release holding a key, an address and a planted `jackett_key_binding` (and the same with the address equal to the planted value) loads with an empty binding in memory, and the file holds an empty binding after the next save of any option; (b) a file written by this release with a bound key loads twice in a row with the binding unchanged; (c) a restored pre-release backup holding a planted binding is emptied again; (d) rolling back and forward with nothing changed keeps the binding (AC-DATA-10's third case), because the older release leaves the flag in the file; (e) the clear is logged once at INFO naming the section and option only, never a value, and a start with nothing to clear logs nothing; (f) the clear never raises and never blocks start-up. Mutations that must each turn a named test red: the clear removed; the clear made unconditional (case (b) fails); the clear run when the flag is present with a different value. Known limit, accepted and recorded in `docs/reference/API.md` (P4): a planter who also plants the flag itself, which releases before #612 accept under a case-variant name, defeats the clear; that planter holds settings write on a release where the Jackett key can be taken directly. Second known limit, by construction: the rule cannot tell a planted value from one a user entered while the option was declared with no `ui-meta` at all, so a later change that marks such an existing option `hidden` would empty it on every upgraded install (an option that was `rw` or `ro` already has its flag in the file and is safe). A test fails when any `hidden` option other than the binding is declared in the tree, and its message says to migrate the value (shipping the flag a release earlier protects only installs that ran that release; measured at review). Third: a clear that fails is logged at WARNING and is not retried at a later start, because the flag is declared regardless (an undeclared flag would leave the option writable, which is worse); no input was found that makes it fail.
- **AC-SEC-17:** [added at P2 review round 2: a review finding with no criterion behind it; it pins what the guard already intends and relaxes nothing; owner to be told] (P2) For each saved address the normaliser accepts and that equals the binding, every row a sync writes resolves, by `urllib3.util.parse_url` of the URL `http_client.request` prepares, to the same scheme, host and port as the binding. Fixtures include a Kelvin-sign host and trailing U+00A0 and U+3000 (also U+0085, a leading space, and the bytes wrapper followed by a space). Rows are built from the text the normaliser was given, cleaned as a sync always did, and the normalised address stands in when that is not ASCII. Tests: `test_AC_SEC_17_every_row_a_sync_writes_resolves_to_the_host_the_key_was_bound_to` (six rows) and `test_a_request_with_its_own_key_and_no_url_writes_rows_by_the_formula_master_used` in `tests/integration/test_jackett_sync_rows_and_lock.py`. Breaks: drop the ASCII fallback (the Kelvin row fails); build from the raw saved address (the whitespace rows fail).

### QA

- **AC-QA-1:** Happy path, both operations (`jackettTest` and `jackettSync`, parametrised). `jackett_url` U is saved, then `jackett_api_key` K is saved through `settings.save`. A call with no parameters sends exactly one request, its host, port and path are those of U, it carries K, and Test and Sync list or store the indexers exactly as before the change. The request is observed at the transport: the Env `http_opener` request is recorded and HttpClient runs for real, with `provider.urlopen` not stubbed. (merges AC-PROD-1)
- **AC-QA-5:** Normalisation table, driven through the real HttpClient with only `http_opener` replaced. Accepted pairs: the saved URL is bound, then sync is called against an equivalent form, and the transport sees the bound host and port; the equivalent forms are scheme and host case, explicit :80 for http and :443 for https, a trailing slash, and bare `host:9117`, which `cleanHost` turns into http. Refused pairs, with no request reaching the transport: a different port, http versus https, a different path or path prefix, a sibling host, `http://<bound-host>:<port>@evil.invalid`, `http://evil.invalid\@<bound-host>:<port>`, `http://<bound-host>:<port>\@other/`, `http://other#@<bound-host>:<port>`, `http://<bound-host>:<port> @other/` and the trailing-dot host `http://<bound-host>.:<port>`. With a bound address that carries userinfo (`http://test-user:test-pass@<bound-host>:<port>`), the refused pairs include `http://test-user:test-pass@evil.invalid\@<bound-host>:<port>` (Python's `urlsplit` reads the bound host, the transport connects to `evil.invalid`), an address with other userinfo, and the same address with its userinfo removed; the same userinfo, written identically, is accepted and reaches the bound host. [review round 1] Any form the implementation accepts must be shown to reach the bound host at the transport. (merges the fixture corpus of AC-DATA-3)
- **AC-QA-11:** Save order on the Settings page, with the two fields kept as separate saves. Order A: URL U2 is saved, then key K2, then sync, which sends K2 to U2. Order B: key K2 is saved, then URL U2, then sync, which returns the AC-DESIGN-5 refusal with no request. Both orders are pinned, so the answer to spec question 1 cannot drift silently. (carries the test half of AC-PROD-4 and AC-DESIGN-7)
- **AC-QA-12:** Concurrent saves. Two threads save `jackett_url` U2 and `jackett_api_key` K2 at once, released by a barrier, over 50 iterations. In every iteration the following no-parameter sync either sends K2 to the URL the binding was computed from or is refused, and it never sends the key to any other host. The wizard's own save order is pinned separately by AC-ARCH-9. Once AC-DATA-1's lock exists, an address save cannot interleave between the key save's read of `jackett_url` and its `save()`, so the deterministic test proves the lock instead: the key save is paused, using an event hook, after its read of `jackett_url` and before its `save()`; a `jackett_url` save of U2 started meanwhile does not complete until the key save has finished (it blocks on the same lock); and the following sync sends K2 to the address the binding was computed from, or is refused. [review round 1; reworded at re-check round 3, because the earlier interleave cannot happen once the lock exists: `set()` takes the same RLock]
- **AC-QA-13:** Upgrade cases, by value (D6). Each starts with an empty or absent binding, and empty and absent are one state, "unbound": (a) a pre-upgrade config.ini with a key and no binding option; (b) the same file after `registerDefaults` for the real torrentpotato `config` has been applied and saved, as `loader.run()` does on every start, which writes the binding as an empty value; (c) key absent; (d) key present with an unparseable address (the fixtures of AC-DATA-6). (Writer clauses, P1) In each, no binding is created by start-up or by registration (read by value: empty after the load), and after a key save the binding is the literal expected string written in the test (empty for (d)), never the normaliser's output compared with itself. (Sync clauses, P2) In each of (a), (b) and (d), a parameterless sync is refused as `unbound` with zero requests before the key save; in (c) it returns the AC-SEC-7 "URL and API key are required" error with no request (no key is not an unbound key, AC-SEC-3). After the key save it proceeds for (a), (b) and (c) and is still refused as `unbound` for (d). No log line contains the address, the key or the binding value. (merges AC-OPS-4) [D6: replaces the start-up binder cases]
- **AC-QA-15:** Legacy bytes-literal values. config.ini holds `jackett_url` and `jackett_api_key` in the `b'...'` wrapper form with no binding. (Writer clause, P1) After a key save through `settings.save`, the stored binding equals the literal expected string written in the test for the unwrapped URL and carries no `b'` prefix. (Sync clause, P2) A no-parameter sync then sends the unwrapped key to the unwrapped host, and before the key save it is refused as `unbound`. The writer and the check normalise the stored URL identically. [re-check round 1; D6]
- **AC-QA-19:** E2E against the real server, with no `page.route` on `torrentpotato.jackett_sync` in these Settings tests (the wizard tests of AC-A11Y-4 are the only users of a `page.route` on that route in SEC-005's tests, all through one helper; a stub of the SAVE route is allowed, for example to have the server's refusal of an address save reproduced). Seed U and K through the API (U is a non-routable address such as `http://seeded-jackett.invalid:9117`, so a flush regression cannot send K to a real host), change the URL through the Settings Jackett URL field, then press Sync Indexers with no wait between the edit and the press. The Sync result shows the exact AC-DESIGN-5 refusal text and not a "Failed to connect" text. A paired test with a matching binding shows no refusal text on the Sync result, so the result is proven in both directions. The key is then re-entered and Sync is pressed with no wait between them: the sync request is observed after the `settings.save` response for the key, and its answer is not the "URL and API key are required" error (success against a Jackett is AC-PROD-3's, in P3, which adds a local fake Jackett under `tests/e2e/`). In P1, where no binding refusal exists, U2 in the flush test is the loopback address with no listener `http://127.0.0.1:9`, so the sync answers "Failed to connect to Jackett" and nothing leaves the machine. The flush covers only the pending single-option saves of the button's own section: with a row removed in another section (its 8-second Undo window pending), pressing Sync leaves that removal unsent and its Undo available (proved by an E2E). A refused sync re-reads the section: with the page loaded at address A and the address changed to B through the API, not the page, the refused press leaves the Jackett URL field showing B (this is the proof of the AC-SIMP-6 re-read clause, and lands in P1 with the flush). [Clauses: flush clause (P1): the key re-entry ordering sentence, the loopback sentence, the own-section/Undo sentence and the re-read sentence. Refusal-text clauses (P3): the exact-text sentence and the paired matching-binding sentence.] [the field-level mismatch state in the original wording was vetoed]
- **AC-QA-20:** Fixtures do not hollow out the guard. Existing tests that rely on the saved pair get their binding through a production writer: a `settings.save` of the key. No file under `tests/` writes the binding option's name or a precomputed binding value directly into config.ini, apart from the hostile-write tests of AC-SEC-4 and AC-SEC-15, and the file-edit simulations of AC-SEC-3 and AC-DATA-10 (an older release's edit, a restored file), each of which writes only the option it names and says so in the test's docstring. The `world` fixture in `tests/unit/test_jackett_saved_key_scope.py` (lines 33 to 46) seeds the saved pair with no binding, so `test_no_parameters_uses_the_saved_url_with_the_saved_key` goes red when the guard lands; the fixture changes under this criterion in the same slice as the guard, and AC-SEC-9's "bodies unmodified" covers test functions, not that fixture. [review round 1; D6]
- **AC-QA-21:** Each guard is shown to be load-bearing. Each break below is applied in turn, the named test is watched fail, and the code is restored; the diff hash of each break is recorded and `__pycache__` is cleared before each run. Breaks, P1: remove `'ui-meta': 'hidden'` from the binding's declaration (AC-SEC-4 fails); drop the `_internal_meta` refusal of the prerequisite (AC-SEC-15 fails); drop the read filtering (AC-SEC-5 fails); make the normaliser raise on an unparseable address (AC-OPS-7's unparseable rows fail); make the key-save hook raise (AC-SEC-6's hook clause fails, the key saving with no binding). Breaks, P2: remove the binding comparison (the AC-SEC-1 test fails); treat an empty or absent binding as a match (AC-SEC-3 fails); compare by hostname with `urlparse` and nothing more (the userinfo row in AC-QA-5 fails). [D6: the binder and marker breaks are retired]
- **AC-QA-22:** Removal. The module docstring of `tests/unit/test_jackett_saved_key_scope.py` (lines 4-6) no longer states that someone who can call `settings.save` can change `jackett_url` alone and have the saved key sent to the new URL. A grep of `tests/` for "sends the saved key to the new URL" returns nothing, and the docstring states that a parameterless call is refused when the saved address differs from the one the key was saved for (a reworded sentence alone would pass the grep). No other test in the tree pins the unbound behaviour, so this is QA's only removal.
- **AC-QA-23:** [owner decision D7; P3; rewritten at P3 review round 1] AC-PROD-12 is proven in the `scripts.html` unit harness (`tests/unit/ui/settings-group-save.spec.ts`) for: a refused save (success false), an HTTP error, a rejected fetch, a save in flight at the press that is then refused, a save unanswered at the deadline (fake timers, the constant stays 10000), a successful save (the action IS sent, exactly once, after the save), two values where the first is refused (the second is not sent, the action is not sent, both stay unsaved), a refusal answered and toasted BEFORE the press followed by a key typed and Sync (the address is sent again, the key is not sent, no action), a second press with nothing changed (the refused value IS re-sent and the action still does not run), the user correcting the address (both save in order, the action runs once, nothing is left unsaved), a refused value in ANOTHER section (does not block, is not sent), a dirty combine row in the same section (not a single-option value: no per-column save, does not block), a refusal that arrives while the press is awaiting its own group's flush (counts: the open saves are taken before the first await), outside a press a key saved on its own behind a refused address followed by a press (the address is sent again first, no action), a value whose save had no answer (stays unsaved: the next press sends it again and stops again), a press with nothing pending (the action is sent), a stop after an earlier success (danger state), the label and its "Execute" fallback, "Saving…" while waiting, a failed request clearing the header's saving state, and the save-failure toast naming the option by its label; also that the panel-wide `flushPendingSaves` awaits a save already sent (`saveChains`). And on the real server by E2E (`tests/e2e/settings-jackett-display.spec.ts`): the key save refused by the server (the displayed mask) and Sync shows the text and again on Enter (the refused value is re-sent, refused again), with no sync request started by the page and none reaching the fake Jackett; the address save refused and answered (a stub of the SAVE route only, never the sync route), then the key typed and Sync pressed twice: zero requests at the fake Jackett, the key never sent, and the config's key and binding unchanged; and the unanswered case with the held clock. Requests are recorded when the page starts them and read once the press has ended (the button operable again), not at the instant the text appears. The existing unit tests that pinned the old behaviour (the action, or the key, sent after a refused, failed or unanswered save) are changed to the new one and listed in the commit.
- **AC-QA-24:** [owner decision D9; P3] AC-PROD-13 is proven through the real routes with only the HTTP session replaced (`tests/integration/test_jackett_key_rejected.py` and `tests/integration/test_jackett_error_reply.py`): 401 gives the new text for both routes, with the request URL, the key and the address absent from the response and every log record (the replaced session raises an `HTTPError` whose own text carries the URL, as `requests` does), and nothing written; `<error code="100">` at the root and nested give it; `<error code="201">` and an error with no code give the old text; a code that is not exactly "100" gives the old text; a hostile `code` (markup, CRLF, 5000 characters) is never in the response or the log; 400, 403, 404, 429, 500, 502 and 503 and a connection error keep their text. By one E2E on the real server (`tests/e2e/settings-jackett-display.spec.ts`), the fake Jackett (`tests/e2e/fake-jackett.ts`) answering a wrong key with an `<error code="100">` document at HTTP 200 (the shape the code recognises from the earlier root-error fix, chosen because it is the one Jackett's documentation is recalled to use; the 401 form is covered through the routes above) and a wrong key re-entered in Settings showing the new text in the result region.

### Simplicity

- **AC-SIMP-1:** The binding is stored as the normalised Jackett address string itself, not a fingerprint: the diff adds no `hashlib`, `hmac` or `secrets` import and no digest call to torrentpotato.py or settings.py.
- **AC-SIMP-2:** Exactly one new option name is registered in the `torrentpotato` section: the binding, protected by the existing `ui-meta` mechanism. No other new option is added: no migration marker, no version marker, no toggle that disables the check, no new section. [D6: the original "no migration marker" sense is restored; the simplicity veto that AC-SEC-8 overrode now stands]
- **AC-SIMP-3:** The diff leaves the bodies of `_refuse_per_column`, `save_group`, `_save_group` and `_registered_ui_value` in `couchpotato/core/settings.py` unchanged (owner decision D3: the combined rows are not masked here). Changes to settings.py are limited to four provider-neutral pieces: omitting non-readable options from the settings read (AC-SEC-5, AC-ARCH-3); one internal write method that sets memory only (AC-ARCH-4); the lock and rollback of AC-DATA-1 in the save path, applied by a generic rule; and the clear of AC-SEC-16 in `registerDefaults` [fourth piece added with AC-SEC-16 at the P1 review, 2026-11-21]. A refusal AC-SEC-4 needs that the existing `isOptionWritable` path does not already give is a spec bug to be raised at review, not a permitted change. The `_internal_meta` refusal of AC-SEC-15 is the prerequisite's, already on `master`, and is not in this diff. [amended: the original froze `saveView` and `getValues`, which security and data criteria need to change; D6 shrinks the list]
- **AC-SIMP-4:** The check on the saved key runs in exactly one place, `_jackettCredentials`. The bodies of `jackettTest` and `jackettSync` gain no binding logic of their own. Address normalisation is a single function in torrentpotato.py, and no new module file is created under `couchpotato/`.
- **AC-SIMP-5:** The diff introduces no new event name in any `fireEvent` or `addEvent` call, with one permitted exception: a value hook on the existing per-option save event for `torrentpotato.jackett_api_key` (`setting.save.torrentpotato.jackett_api_key`, of the kind `_core.py` already registers) is not a new event name and is the one provider-side way to put the binding in the same write as the key. The binding is written only from that hook; no `.after` or `.committed` handler writes it. [review round 1: the earlier wording forbade the hook it needs.] [amended: the original `.after` or `.committed` handler would put the binding in a second file write, which AC-SEC-6 and AC-DATA-1 forbid; D6: no start-up step]
- **AC-SIMP-6:** No file under `couchpotato/ui/templates/partials/settings/` changes except two. `scripts.html` changes only so that (decision C1, as amended after the PR #617 review: the saves of one section also go through one per-section chain, with a bounded wait, see AC-SIMP-7) `buttonField.execute()` awaits a flush of the pending single-option saves of its own section (the `pendingSaves` entries whose section is the button's) before its action request; it flushes no other section and no combine group, which `flushGroupFor` already handles for its own section; a row removal pending in another section keeps its Undo window, proved by an E2E; and, when the action answers success false, `execute()` re-reads the section as `endAction` does after a success (for a section with a combine group, by ending the action as may-have-written; a button in a section without one is unchanged); a failed re-read leaves the rows locked as stale, as after a success, and the `endAction` docstring says so; so the fields show the saved values (decision C1). The existing E2E in `tests/e2e/settings.spec.ts` whose title says an action that answers success false "unlocks at once with the rows as they were" (about line 1686; the reviewer's reading, not run) is renamed in the slice that adds the re-read (P1), because the re-read makes its title untrue; its assertions are kept. `field_types.html` changes so that the button result region (line 160) is a persistent `role=status` element with dynamic text, as AC-A11Y-3 requires, and, from D7, so that the busy button says "Saving…" (see the bracket below); every other button field keeps its existing E2E green. [D7, 2026-11-22, as amended at P3 review round 2 to the scope as built, which supersedes the first D7 sentence ("pending or in flight at the press") and the closing "Nothing else in `scripts.html` changes": `scripts.html` also changes so that (a) the page records which section and option each unsaved value belongs to (`dirtyOpts`, beside `dirty`); (b) `execute()` takes the section's saves in flight before its first await and, at the press, sends again every unsaved single-option value of its own section in the order each first became unsaved, and does not send the action unless all of them land (AC-PROD-12); (c) a press's saves form a batch that stops at the first one that does not land, so the values behind it are not sent (`sendInTurn`, `trackOpenSave`); (d) each single-option save reports how it ended, and the chain's links carry their key and value; (e) the save-failure toast names the option by its label; (f) the button says "Saving…" while it waits on saves; (g) the not-run texts name the button by its label; and (h) the panel-wide `flushPendingSaves` also awaits the section chains (conductor decision C2). `field_types.html` changes for the persistent result region (an `<output>`) and for the "Saving…" accessible name and visible text. Everything else in both files is unchanged.] [review round 1] The refusal reaches the user as the `error` text in the existing button result region (field_types.html:160) and on the wizard's existing result line (wizard.html:1857-1862). The settings read response gains no new field that reports binding state.
- **AC-SIMP-7:** The Settings page keeps saving `jackett_url` and `jackett_api_key` as two separate requests. The settings save machinery in `partials/settings/scripts.html` (`setVal`, the debounce, the save requests) is unchanged apart from the changes AC-SIMP-6 allows, and the save-order case (key typed before address) is handled by the refusal copy alone. [amended after the PR #617 review: the per-section save chain of decision C1, with its bounded wait (`SAVE_WAIT_DEADLINE_MS`), is the one further change to `saveSingle`.] [D7: `sendSingleSave` and the chain's link also report how the save ended (saved, refused or failed, unanswered at the deadline), which the button reads; what is sent, when and in what order is unchanged.]
- **AC-SIMP-8:** Nothing outside the saved-key path of `_jackettCredentials` gains a binding: `getHosts`, `_isJackettIndexerHost`, `_searchOnHost` and the stored rows' `host` and `pass_key` handling are unchanged (owner decision D3). Debt items 6 (redirect) and 7 (rotation) remain open in `docs/technical-debt.md`.
- **AC-SIMP-9:** No new dependency: `requirements*.txt`, pyproject, package.json and package-lock.json are unchanged by the diff. (merges AC-ARCH-10)
- **AC-SIMP-10:** No new API endpoint: the number of `addApiView(` calls in torrentpotato.py and settings.py is unchanged.
- **AC-SIMP-11:** The change touches at most 8 files outside `tests/`: torrentpotato.py, settings.py, wizard.html (only to run the two Jackett saves in order, AC-ARCH-9), `partials/settings/scripts.html` (only the `execute()` own-section flush, the re-read on a success-false answer and, added after the PR #617 review, the per-section save chain with its wait deadline of decision C1, and, added by D7, the stop of AC-PROD-12 with the unsaved-value tracking, the batch stop, the outcome each save reports, the toast label and the "Saving…" phase, AC-SIMP-6 [amended 2026-11-22, P3 review round 2: this replaces "only the stop of AC-PROD-12 with the outcome each save reports"]), `partials/settings/field_types.html` (the persistent result region and the "Saving…" accessible name and text, AC-SIMP-6; first touched in P3 [amended 2026-11-22, P3 review round 2: this replaces "only the persistent result region"]), `docs/reference/API.md`, `docs/technical-debt.md`, and the spec. `couchpotato/runner.py` is not touched. The `_internal_meta` refusal of the prerequisite is not in this count. [amended: review round 1: scripts.html added by decision C1 and field_types.html by the persistent-region wording of AC-A11Y-3; D6: runner.py dropped with the start-up step, 9 to 8]

### Product

- **AC-PROD-3:** The user refused under AC-SEC-1 (or at upgrade, D6) recovers in one step. They check the address (AC-PROD-11), enter the API key again with the address field untouched and press Sync with no wait after typing, and the sync succeeds against the new address (the button first sends the pending key save, decision C1). No restart, no config.ini edit and no clearing of either field is needed.
- **AC-PROD-4:** Question 1 (save order) is answered in the spec as an accepted cost, not a combined save. A user who types the key first and the address second gets the AC-SEC-1 refusal and recovers through AC-PROD-3. The spec's Owner decisions or Not in scope section records this, along with what would have to be true to revisit it (for example, the Settings page gains one save for both fields). [the key-then-address test is AC-QA-11]
- **AC-PROD-5:** Upgrade (D6) leaves searches and downloads alone. Take an install with a saved address, a saved key and previously synced TorrentPotato rows, but no binding, starting from a config.ini fixture without the binding option and after `registerDefaults` has written it empty. After it starts on the new version, with no user action, a search through a stored TorrentPotato row still sends that row's own `pass_key` to that row's host with no refusal: the named observation is the search-request observation, the `http_opener` request recorder seeing exactly one request whose URL is the stored row's `host` and whose query carries that row's `pass_key`, and its answer is the row's normal answer. On the same install `jackett_sync` is refused once as `unbound`, which proves that only Sync is affected. [D6: replaces "Test and Sync succeed on first use"]
- **AC-PROD-7:** The binding gates only uses of the saved `jackett_api_key` (`jackett_test` and `jackett_sync` without a supplied key). Searches through stored TorrentPotato rows build identical requests before and after an address change, because they use each row's own `pass_key`, and a test proves a search against a stored Jackett row is not refused by the binding. (merges AC-OPS-9)
- **AC-PROD-9:** Removal: Jackett item 5 in the "Newznab positional lists" entry of `docs/technical-debt.md` is replaced by one line: "5. Closed by SEC-005: the saved key is only sent to the address it was saved for. The readable copy in synced rows is the separate open item "Credentials in combined rows are returned unmasked by the settings read"." [P2 review round 3: see gap (j) for the outbound-proxy exception on plain http] Items 6 (redirect forwards the key) and 7 (pass_key not updated on key rotation) are present with their meaning unchanged, because the spec puts them out of scope. [review round 1: replaces "item 5 is gone", which left no pointer to the open exposure.]
- **AC-PROD-11:** [review round 1] After an address change the user did not make, the refusal prompts a check of the address before the key is re-entered. The text of AC-DESIGN-5 asks the user to check that the Jackett URL is right, then to copy the API key from the Jackett dashboard, paste it above and press Sync [reworded by D8, 2026-11-22; P3 review round 2: this replaces "check that the address is their Jackett server, then to enter the API key again and press Sync again"], in that order (the test asserts the position of the check clause before the re-entry clause; since D8 the markers are "Check the Jackett URL" before "copy the API key"), and carries no address, so the Jackett URL field on the same card (Settings) or step (wizard) is where the user looks. Re-entering the key, with the address untouched, binds the key to whatever address is saved at that moment, which is why the check comes first. For API callers of `jackett_test` the same `error` string is returned. Proven by an E2E that loads Settings with A, changes the address to B through the API (not the page), presses Sync, and asserts the Jackett URL field then shows B (the refused action re-reads the section, AC-SIMP-6). The E2E lands in P1 with the re-read it proves; the copy that depends on it ships in P2. In P1, where no binding refusal exists, K is seeded and B is a loopback address with no listener (`http://127.0.0.1:9`), so the sync answers "Failed to connect to Jackett" and nothing leaves the machine. From P2 the same press meets the AC-DESIGN-5 refusal. The assertion is on the field, not the text, so the test is unchanged across slices, and it fails on `master`. [re-check round 1; re-check round 2, N-2]

- **AC-PROD-12:** [owner decision D7, 2026-11-22; P3; scope rewritten at P3 review round 1] At a press of a Settings action button, every single-option value of the button's own section that the page holds as unsaved is sent again as part of the flush, one at a time in the order each first became unsaved (a retyped value keeps its place, gap (s)), together with the section's pending saves and its saves in flight (a save already in flight is awaited, not sent twice), and the action request is sent only if ALL of them land. "Unsaved" means typed in the page and not yet accepted by the server (the page's `dirty` entries): a value whose save was refused, failed or got no answer stays unsaved until a save is accepted, so a refusal from before the press blocks the action until the value saves or the user changes the field to a value that saves (or reloads the page, which drops the page's unsaved values). Once one value does not land (refused, failed, or unanswered at the end of its wait of `SAVE_WAIT_DEADLINE_MS`, 10 seconds from the send), the values behind it in the section are NOT sent in that flush (a key must not be saved behind a refused address, or the server binds it to the old address), and they stay unsaved for the next press; outside a press, ordinary field edits keep saving independently as before, and a later press re-sends the still-unsaved address first. The section's saves in flight are taken before the press's first await, so one answered "refused" while the button waits for its own combine group still counts. Exact texts, with `<Button>` the button's own label as the page shows it (`button_text`, "Sync Indexers" for Jackett; "Execute" when it has none), rendered as text: refused or failed (an answer of success false, an HTTP error, or a request that rejects): "<Button> did not run because a change above did not save. Fix it if needed, then press <Button> to save and run again."; unanswered at the end of the wait: "<Button> did not run: your changes have not finished saving. If this happens again, check CouchPotato is still running." Neither carries a field value, an address or a key. When both causes are present the first text is shown (a refused save is certain, an unanswered one is not). While the press waits on saves the button says "Saving…" (and its accessible name "Saving… <Button>"), not "Running…". Saves of other sections are not considered, and a combine row in the same section is not a single-option value (it is saved as rows by its own flush before this one, C1; its refusal stops the press with the existing "Fix the rows marked in this section first" text). The page is not re-read in this case (the action was not sent, and the fields keep what the user typed). **Limits that remain, in plain words:** a value whose save was never answered may still land on the server after the press stopped, so a later press can send the same value a second time (harmless), and if the user changed that field in the meantime the late first request can overwrite the newer value (the same as on the previous release); a value typed after a press began is sent by the next press; an unsaved value in a field the user cannot see (hidden by the Advanced toggle, or on another tab) blocks the button until it is shown and fixed, or the page is reloaded. The Trakt Start button is not a `buttonField` and is not affected by the stop (conductor decision C2 covers the flush it awaits).

- **AC-PROD-13:** [owner decision D9, 2026-11-22; P3] A key Jackett does not accept says so. `torrentpotato.jackett_test` and `torrentpotato.jackett_sync` return the API `error` "Jackett did not accept the API key. Copy it again from your Jackett dashboard." when (i) the request to Jackett is answered with HTTP 401, or (ii) the reply contains an `<error>` element, at the root or nested, whose `code` attribute is exactly "100" (compared as the literal string: "100 ", " 100", "1000", "0100" and Arabic-Indic digits are not). Every other status (400, 403, 404, 429, 500, 502, 503) and every other error (another code, no code) keeps its text ("Failed to connect to Jackett: HTTPError", "Jackett returned an error response"). Only the status code and the `code` attribute are read: nothing else from the reply, and never the exception's own text (it carries the request URL and so the key), reaches the response or any log record at any level; nothing is written. Neither trigger was observed against a real Jackett (gap (q)).

### Design

- **AC-DESIGN-1:** The binding is never rendered as a control. On the Settings page's TorrentPotato card, in both themes, the controls between the enable switch and the indexer rows are exactly: Jackett URL (text), Jackett API Key (password), Sync Indexers (button), the same count of inputs as before this change. No input exists whose name, label, accessible name or aria-label refers to the binding. The wizard's Jackett section also renders exactly its existing URL field, key field and Sync button. (merges AC-A11Y-7) [D6: the marker is gone]
- **AC-DESIGN-4:** Entering the key again in the API key field and committing it (blur or Enter), after checking the address (AC-PROD-11), is the only recovery path: the next Sync Indexers press, even with no wait, then runs a sync and does not return the refusal. No "trust this address", "rebind" or "keep key" control is added anywhere, and the TorrentPotato card gains no new button. [the field-notice half of the original wording was vetoed]
- **AC-DESIGN-5:** The refusal text is exactly "Check the Jackett URL is right, then copy the API key from your Jackett dashboard, paste it above and press Sync. This is needed once after this update, or after the URL changes." [Reworded by owner decision D8, 2026-11-22; the text before was "The saved Jackett API key cannot be used with this Jackett address. Check the address is your Jackett server, then enter the API key again and press Sync again."; the clause re-check is in D8 and gap (r).] and it is the API `error` string for both causes (address differs from the bound one, and no binding stored), returned by `jackett_test` to API callers as well as by `jackett_sync`. The API `error` clause closes in P2 and the display clauses in P3. The Sync result line in Settings and the wizard's Jackett result line show it verbatim in the existing danger style (`text-cp-danger`, with the base.html light-mode override), in dark and light themes. It says nothing untrue on either surface or for either cause (but see gap (r)): it does not send a user to Settings, does not claim the address changed (it asks the user to check it), and carries no address, no key and no internal word such as "binding", "fingerprint" or "normalised". [the exact wording was fixed at synthesis to satisfy this criterion and AC-A11Y-4, and replaces the copy in Proposed shape; review round 1 replaced the wording again with the address-check form of AC-PROD-11; D8 replaced it a third time]

### Accessibility

- **AC-A11Y-3:** Pressing Sync Indexers with a mismatched or missing binding writes the refusal message into the button's result region exactly once: the `role=status` element is in the accessibility tree, not `display:none`, before the sync response arrives, and its text changes to the refusal exactly once. (Today the region is `x-show="result"` and `execute()` clears the text first, so the region leaves and re-enters the tree together with its text, the "live region created with its content" failure; the change to `field_types.html` in AC-SIMP-6 makes it persistent.) [Built in P3 as an `<output>` element, whose implicit role is status, with an explicit `aria-live="polite"`: the analyser's rule Web:S6819 asks for the tag over the ARIA role, and the wizard's and the logs' regions are `<output>` too. Tests find it by its role.] [review round 1] The message is identical to the server's refusal text. Focus stays on the Sync Indexers button and does not move to the body or anywhere else. The button is operable again by keyboard (Enter and Space) once the action ends.
- **AC-A11Y-4:** The Settings Sync Indexers button and the wizard's "Sync Trackers from Jackett" button both show the refusal. The wizard saves the URL then the key before every sync, so it reaches the refusal only if the saved pair changes between those saves and the sync. Its surface is therefore tested with a `page.route` stub on `torrentpotato.jackett_sync` that returns the refusal body, and this is the only `page.route` on that route in SEC-005's tests: it is used only by wizard tests (a display test, an accessibility test and a phone-width test), all through ONE helper (`stubWizardSyncRefusal` in `tests/e2e/jackett-sync-page.ts`). With the stub, the refusal reaches the wizard's single status region through `announce()` after the existing "Syncing…" message, so a repeated refusal is announced again. The wizard halves of AC-A11Y-5 and AC-A11Y-6 are asserted in that same test. No wizard code is changed for this criterion. [review round 1: replaces the earlier wording, which asked for a "cleared first" announcement the wizard already gives and for a state the real wizard cannot reach.]
- **AC-A11Y-5:** The refusal text meets 4.5:1 contrast in both light and dark themes, measured against the surface it is painted on, on the Settings Sync result and the wizard result line, following the pattern of the refused Newznab field test in `tests/e2e/settings-combined.a11y.spec.ts`. [narrowed: the field-level text and border it also covered were vetoed]
- **AC-A11Y-6:** axe reports zero violations scoped to the TorrentPotato settings card, in both themes, in two states: binding matched, and after a refused sync. The wizard's Jackett step also has zero violations after a refused sync. [narrowed: the standing mismatched-field state was vetoed]
- **AC-A11Y-8:** At a 320 CSS px viewport (the WCAG 1.4.10 equivalent of 1280px at 400% zoom, set with the `mobile-chrome` project or an explicit viewport, since Playwright cannot emulate zoom directly), the sync refusal text reflows without horizontal scrolling and without clipping or overlapping the key input or the Sync button, in both themes. [narrowed: the field-level text was vetoed]
- **AC-A11Y-9:** If the change adds any control, that control has an accessible name that matches its visible text, is reachable by Tab, meets the project's 44x44 CSS px target floor and, where it moves focus, moves it to the `jackett_api_key` input. If no control is added, this criterion is satisfied by its absence.
- **AC-A11Y-10:** Removal: this change replaces nothing in the accessibility area. No existing control or label is removed or superseded, and no live region is removed: the button result region stays, and AC-A11Y-3 makes it persistent.
- **AC-A11Y-11:** [owner decision D7; P3; texts reworded at P3 review round 1] Both AC-PROD-12 texts are shown in the same persistent status region and in the same danger style as the refusal (including when an earlier press had succeeded, so the region carried the success style), announced once, at least 4.5:1 in both themes measured against the surface they are painted on, not conveyed by colour alone (the text says what happened), and visible at 320 CSS px without horizontal scroll or clipping, for both texts. Focus stays on the button, which keeps `aria-disabled="true"` (never `disabled`) while the press waits and is operable again by keyboard (Enter) when it ends; Enter after each text presses it again. A refused press announces, in full and no more: the rows-locked message, the result, and the toast's alert (the unanswered press: the rows-locked message and the result).

### Data

- **AC-DATA-1:** Saving a non-empty `jackett_api_key` writes the key and the binding in one parser update and one atomic `save()` inside a single hold of the settings lock, and the `jackett_url` the binding is computed from is read inside that same hold. (Writer clauses, P1) Proven by a test that forces `os.replace` to raise during a key save, gets `success: false`, asserts config.ini is byte-identical by hash, then performs an unrelated successful `settings.save` and asserts the file still holds the old key and the old binding: neither the new key nor the new binding survives in memory to be persisted by the next writer. Today a failed per-column save leaves its value in memory (debt gap 3: `_saveView` restores memory only on the password and auth paths), so the test starts red on the key alone, whatever the binding code does. This criterion closes that for any option whose `setting.save.<section>.<option>` hook sets a companion option, by snapshotting and restoring both under `_PASSWORD_SAVE_LOCK` (the settings save lock today, which `saveView` holds only for `core.password` and `core.auth_required`), in the style of SEC-004's group-writer rollback. `saveView` takes that lock for such saves by a generic rule, never by section or option name. If the restore is made generic for every option, gap 3 is closed in `docs/technical-debt.md` by the P4 edit. (Sync clause, P2) With K1 bound to U and the URL since changed to U2, a no-parameter sync after that sequence never sends K1 to any host other than U. [review round 1] (merges AC-QA-10 and AC-OPS-6) [D6: the marker is gone]
- **AC-DATA-4:** The binding check and the outbound request use one read of the saved address, with no re-read between check and send. Proven by a test where the provider's `conf('jackett_url')` returns A on its first read and B on any later read: the request either goes to A or is refused, and the request recorder never sees B.
- **AC-DATA-5:** retired by D6 (2026-11-21): start-up binding rules, no start-up.
- **AC-DATA-6:** A saved address that cannot be normalised (fixtures `localhost:99999`, `http://h:abc`, `http://[::1`, and a host containing a tab; measured after `cleanHost` adds the scheme to the first (raw, neither parser raises on it): `urllib3.util.parse_url` raises on all four, and `urllib.parse` on the first three (`urlsplit` itself only for `http://[::1`; for the other two, reading `.port` raises; it drops a tab and parses the fourth), and `cleanHost` accepts them) never blocks or breaks a key save. (Writer clause, P1) A key save with such an address saved succeeds, stores the key, and leaves the binding empty (removing any earlier one) in the same write; the normaliser never raises, so the value hook never raises. (Sync clauses, P2) A parameterless sync is then refused as `unbound` with zero requests until the address is corrected and the key is entered again. [D6: the start-up save, its ERROR line and the no-path clause are retired with the start-up step; re-check round 1, H-A]
- **AC-DATA-8:** A mismatch or missing-binding refusal is non-destructive: it writes nothing (config.ini hash unchanged), does not clear `jackett_api_key`, does not clear or rewrite the binding, and does not alter any stored torrentpotato row. Setting `jackett_url` back to the bound address makes a parameterless sync succeed, sending K to that address, without the key being entered again. (merges AC-QA-6)
- **AC-DATA-10:** The binding is stored only in config.ini, in the `torrentpotato` section beside the key, so `scripts/backup.sh` captures key and binding in one file and a restore cannot separate them. No database row, separate file or cache holds a copy. (Single-file storage, P1: the clause above.) (Restore and rollback cases, P2) The following are executed on copies and nothing is bound automatically in any of them: first, a pre-SEC-005 config.ini (key, no binding option) restored after SEC-005 is installed is unbound and its Sync is refused until the key is entered again (there is no start-up binding to re-arm); second, a SEC-005 config.ini whose `jackett_url` was later edited by an older release that ignores the binding is refused after re-upgrade (mismatch), not silently re-bound; third, rolling back and forward with no settings changed on the older release leaves the binding as it was (a bound key stays bound to the same address, which is correct), and never creates or re-points one. Known limit, recorded in `docs/reference/API.md` (AC-OPS-8) and not closed here: an older release does not maintain the binding, so a key replaced while running an older release keeps the earlier key's binding; after re-upgrade the saved key can be sent only to the address the earlier key was bound to, an address this install once trusted with a Jackett key, and never to a new one. Entering the key again on the upgraded release re-binds it. [D6: replaces the start-up restore case; cloud review of the spec]
- **AC-DATA-11:** This change does not mask `torrentpotato.pass_key` on read (owner decision D3), so it adds no handling of a displayed mask in `settings.save_group`: the diff leaves how `save_group` treats `pass_key` cells unchanged (AC-SIMP-3), and a test already in the tree (`test_torrentpotato_pass_key_still_leaks_and_that_is_recorded`) stays green and unmodified, which records that the cells are still returned unmasked. Checked mechanically: `git diff master...HEAD -- tests/unit/test_settings_credential_masking.py` is empty, and the four `save_group` bodies are unchanged per AC-SIMP-3. [review round 1] The masking, and the `save_group` handling a mask needs (a group save must not write a displayed mask over a stored passkey), belong to the next spec and ship together there. [form A of two; the form-B text, which made this criterion conditional on masking in this change, is deleted]
- **AC-DATA-12:** Removal: nothing in the data area is retired by this change. No table, column, option or file goes, and the change replaces no stored value.

### Architecture

- **AC-ARCH-1:** `couchpotato/core/settings.py` gains no reference to this provider: the count from `grep -ciE 'jackett|torrentpotato' couchpotato/core/settings.py` is no higher after the change than before it (1 at planning). The binding is protected by a generic option-level mechanism, not by a section or option name check in `saveView`, `save_group` or `getValues`. [amended: the original required zero matches, and the file already has one]
- **AC-ARCH-2:** The binding option is declared in the `config` of torrentpotato.py with the existing `'ui-meta': 'hidden'` flag, and the change adds no parallel option flag: no new key such as `server_only`, `internal` or `bound_to` is read by settings.py. `settings.save_group` for the `torrentpotato` section cannot write it, because it is not a combine column. Declaring it makes `registerDefaults` write it as an empty value on the first start, which is the "unbound" state (AC-QA-13). [D6: the marker is gone]
- **AC-ARCH-3:** `Settings.getValues` omits every registered option whose `isOptionReadable` is False, for any section. Proven by a unit test that registers a hidden option in a section that is not torrentpotato and asserts the option name is absent from `getValues()`, where today it is returned verbatim. No other option in the tree changes its `getValues` output. [AC-SEC-5 extends the same omission to the options half of the read]
- **AC-ARCH-4:** The server writes the binding through one generic Settings method taking (section, option, value) that bypasses UI writability only and still refuses `_internal_meta` options. The method sets the value in memory only and the caller saves once; unlike `clearSessionRotationPending`, it does not call `save()` itself, because a second write would break AC-SEC-6. [review round 1] No method named for Jackett or the binding is added to the Settings class, and torrentpotato.py does not touch the ConfigParser (`.p`) directly.
- **AC-ARCH-5:** (Normaliser clauses, P1) Exactly one function produces the normalised Jackett address, and the binding writer calls it. It produces the literal expected strings written in the AC-OPS-7 table (never compared with itself); `HTTP://Jackett.Local:80/` and `http://jackett.local` give the same string, and a saved address without a scheme (`jackett.local:9117`) is normalised in the form `getJackettIndexers` actually sends (after `cleanHost`, userinfo included, AC-SEC-2). It never raises: for an address either parser rejects it returns no value. (Checker clauses, P2) The binding checker calls the same function, accepts a bound address that is then used in an equivalent form, and treats a no-value result or an empty binding as `unbound`. [re-check round 1, H-A and round 3, M2: the checker half cannot be proved before the checker exists]
- **AC-ARCH-7:** Exactly one function writes the binding. It is reached from the value hook on the existing per-option save event of `torrentpotato.jackett_api_key` (AC-SIMP-5), so that key and binding land in the same config.ini write (AC-SEC-6), never from a `.after` handler (which fires twice, once before the save). `Settings._saveView` gains no provider-specific code. [amended: the original `.committed` handler gave way to AC-SEC-6 and AC-DATA-1 by precedence; D6: no start-up step]
- **AC-ARCH-8:** The binding state reaches the user through this provider's own API responses (the `jackett_sync` and `jackett_test` refusal), never through the generic settings read: the keys of the `Settings.view()` response are still exactly `options`, `values`, `combine_state`.
- **AC-ARCH-9:** No in-tree client saves `jackett_api_key` concurrently with `jackett_url`: the wizard's finish path (wizard.html around line 1678) awaits the `jackett_url` save before issuing the `jackett_api_key` save, as `syncJackett` already does at 1850-1851. (Ordering clause, P1) After the wizard's provider step with a new URL and a new key entered, the key is bound to the URL entered in that step on every run (the stored binding is the literal expected string for that URL), tested with the URL request deliberately delayed; the test fails if the two saves are placed back in the same concurrent batch. (Not-refused clause, P2) A subsequent parameterless sync is not refused; this can only fail once the guard exists. (merges AC-DESIGN-6 and the wizard half of AC-QA-12)
- **AC-ARCH-11:** No premature generality: the binding helpers live in torrentpotato.py and serve this provider only, with no registry, base-class hook or declarative binding attribute for other providers. Every new function in the diff has at least one non-test caller.
- **AC-ARCH-12:** Removal: this change retires no module, helper or route in the architecture area. `_isJackettIndexerHost` keeps its own comparison deliberately, because it answers "is this row under the Jackett address" for 400 handling, not "may the key go here". Review fails this criterion if the diff leaves a function in torrentpotato.py or settings.py with no remaining caller.

### Operability

- **AC-OPS-3:** retired by D6 (2026-11-21): no start-up step, no runner change. [The one start-up step added later is AC-SEC-16's clear; still no runner change.]
- **AC-OPS-7:** Normaliser table. For each saved-address shape in a fixture table (no scheme such as `localhost:9117`, a trailing slash, an upper-case host, an explicit default port, a path prefix such as `/jackett`, an IPv6 literal, an address with userinfo such as `http://test-user:test-pass@host:9117`, and a `b'...'`-wrapped value), the normaliser's output equals a literal expected string written in the test's table for that shape, not computed by calling the normaliser, and a key save over that address stores that literal as the binding (proved in P1). The unparseable shapes of AC-DATA-6 are in the table with the opposite expectation: no value, and an empty binding. [review round 1; re-check round 1: userinfo, wrapper and unparseable rows added; D6: the table is the normaliser table only, there is no start-up binding to run]
- **AC-OPS-8:** Rollback and restore are written down in `docs/reference/API.md`, in a Jackett section this change adds for `torrentpotato.jackett_test` and `torrentpotato.jackett_sync` (`API.md` documents neither route today), which also documents the AC-DESIGN-5 refusal text and the `mismatch` and `unbound` WARNING reason codes, as five facts under D6. One: the change adds one config.ini option only and no database change, so image rollback needs no data step. Two: the previous release ignores the binding and does not expose its value in its settings read. Three: rolling back and forward with no settings changed leaves a bound key bound to the same address; after restoring an older config.ini backup, or after changing the Jackett address while on a build that has the binding writer (P1) but not the check or while on the previous release, the saved key is unbound or mismatched and is refused until it is entered again; nothing re-binds it automatically. Four: after the upgrade every existing install's first Sync (or API `jackett_test`) is refused once and asks for the key to be entered once; searches and downloads are unaffected. Five: the previous release does not maintain the binding, so a key replaced while running it keeps the earlier key's binding; after re-upgrade enter the key again (AC-DATA-10's known limit). [D6: replaces the first-start binding facts; cloud review of the spec]
- **AC-OPS-10:** Binding state never affects instance health: with the binding missing or mismatched, start-up completes, GET `/` (what the Dockerfile HEALTHCHECK requests) answers without error through the test client, and no ERROR is logged per request or per scheduled tick. The only signals are the WARNING on use of AC-SEC-10 and the Sync result text (or the `error` string for an API caller).
- **AC-OPS-11:** Nothing grows: the change adds one config.ini option name (the binding) and no table, cache, file or per-request log line beyond the AC-SEC-10 WARNING. Verified by diffing config.ini option names before and after a start-up, a key save, and a sync. [D6: the marker is gone]
- **AC-OPS-12:** Removal: the change retires no metric, alert, job, log line or runbook entry. The operability removal list is empty, stated and not omitted.

### Vetoed at planning

`lens-simplicity` vetoes. Each stands because no owning lens supplied a
criterion that needs the vetoed thing, and none touches security, data loss or
the accessibility floor.

- **The binding as a fingerprint (hash).** Dropped from Proposed shape; the binding is the plain normalised address (AC-SIMP-1). The address already sits in clear in `jackett_url`, so a hash hides nothing and makes a wrong normalisation invisible in config.ini. Security and architecture agreed.
- **A standing mismatch state at the Jackett fields.** Dropped: AC-DESIGN-2, AC-DESIGN-3, AC-DESIGN-9, AC-DESIGN-10, AC-A11Y-1, AC-A11Y-2, and the field-notice halves of AC-DESIGN-4, AC-DESIGN-7, AC-DESIGN-8, AC-QA-19, AC-A11Y-5, AC-A11Y-6 and AC-A11Y-8. The refusal already reaches the user on the Sync result in Settings and in the wizard, with `role=status`; `jackett_test` has no caller in any page. A field state would need the settings read to report binding state, which AC-ARCH-8 and AC-SIMP-6 rule out, plus template, E2E, design and accessibility work for the same message shown earlier. Accepted by the owner (D4, 2026-11-21). Known cost, recorded by design: the key field's placeholder still reads "Saved — type to replace" while the key cannot be used with the current address. With AC-DESIGN-10 gone, the design area replaces nothing.
- **One combined save or a new endpoint for the address and key.** Not adopted (AC-SIMP-7, AC-SIMP-10). The wizard runs its two saves in order (AC-ARCH-9) and the Settings page's key-before-address order is an accepted cost (AC-PROD-4).
- **A binding on stored rows or in `_isJackettIndexerHost`.** Not adopted (AC-SIMP-8, owner decision D3); the combined-credential read is the next spec.
- **A migration marker.** The simplicity veto now stands: owner decision D6 drops the start-up binding that the marker gated (it overrode this veto at planning, AC-SEC-8, now retired), and AC-SIMP-2 returns to "no migration marker".

Simplicity vetoes that did NOT stand, because security or data-loss criteria
outrank the veto:

- **"No new refusal or read-filter code in settings.py."** Overridden by AC-SEC-4 and AC-SEC-5. Measured by two lenses: a `ui-meta` hidden option is still returned by `getValues`, and `set()` refuses the server's own write. AC-SIMP-3 was amended.
- **"Write the binding from a `.after` or `.committed` handler."** Overridden by AC-SEC-6 and AC-DATA-1: key and binding go in one write. AC-SIMP-5 and AC-ARCH-7 were amended.

Merged without loss (the surviving criterion carries the wording): AC-QA-2,
AC-QA-3, AC-QA-4, AC-QA-6, AC-QA-7, AC-QA-8, AC-QA-9, AC-QA-10, AC-QA-14,
AC-QA-16, AC-QA-17, AC-QA-18, AC-PROD-1, AC-PROD-2, AC-PROD-6, AC-PROD-8,
AC-PROD-10, AC-DESIGN-6, AC-A11Y-7, AC-DATA-2, AC-DATA-3, AC-DATA-7,
AC-DATA-9, AC-ARCH-6, AC-ARCH-10, AC-OPS-1, AC-OPS-2, AC-OPS-4, AC-OPS-5,
AC-OPS-6, AC-OPS-9. (AC-QA-14 and AC-OPS-4 were merged into criteria that D6
has since retired or rewritten; their wording lives in AC-QA-13 and AC-SEC-7.)

---

## Affected files (expected)

At most eight files outside `tests/` (AC-SIMP-11). The `_internal_meta`
refusal of the prerequisite is a separate change on `master` and is not counted.
`couchpotato/runner.py` is not touched (D6).

- `couchpotato/core/media/_base/providers/torrent/torrentpotato.py` (the
  binding, its normalisation, the value hook, the check in
  `_jackettCredentials`, the option)
- `couchpotato/core/settings.py` (omit non-readable options from the read, one
  internal write method that sets memory only, the lock and rollback of
  AC-DATA-1, the clear of AC-SEC-16; the bodies in AC-SIMP-3 stay unchanged)
- `couchpotato/ui/templates/wizard.html` (only to run the `jackett_url` and
  `jackett_api_key` saves in order in the finish path, AC-ARCH-9; the wizard
  already announces its result through `announce()` after "Syncing…", so
  AC-A11Y-4 needs no wizard change)
- `couchpotato/ui/templates/partials/settings/scripts.html` (only
  `buttonField.execute()` awaiting a flush of its own section's pending
  single-option saves before its action request, and re-reading the section
  when the action answers success false, decision C1, AC-SIMP-6; and, from D7,
  not sending the action when a save of its own section did not land, AC-PROD-12)
- `couchpotato/ui/templates/partials/settings/field_types.html` (only the
  button result region at line 160 becoming a persistent `role="status"`
  element with dynamic text, AC-A11Y-3; this region is shared by every button
  field on the Settings page, so their existing E2E must stay green)
- `docs/reference/API.md` (the new Jackett section, AC-OPS-8, AC-SEC-12),
  `docs/technical-debt.md`
- this spec
- tests under `tests/unit/`, `tests/integration/`, `tests/e2e/`, including a
  new local fake Jackett fixture file under `tests/e2e/` added in P3 (none
  exists today; AC-PROD-3, AC-QA-19), and the rename of the existing
  `tests/e2e/settings.spec.ts` test named in AC-SIMP-6. Tests are outside the
  AC-SIMP-11 budget.

**Release notes.** Items 1, 2, 4, 6, 8 and 9 of "What a user will notice" belong in
the release notes for the beta that carries the guard (P2), and again for the
one that carries the Settings and wizard display (P3).

The Sync result is the button result region at
`partials/settings/field_types.html` line 160, which renders the API `error`
text as it is; the wizard shows it on its existing result line (`wizard.html`,
`jackettSyncResult`) and announces it through `announce()`.

## Delivery slices

*(added by hand on 2026-11-21 from the surviving criteria and rewritten for D6;
no lens wrote it)*

**Rule.** Every merge to `master` publishes a beta that can be promoted, so no
slice may leave `master` worse than it was before the slice. Nothing that fails
closed ships before what makes it safe: the guard (P2) is preceded by the
writer that gives users a binding to enter the key into, and by the Settings
button changes that make the recovery one step (the own-section flush and the
re-read after a refused action, C1). The final refusal text ships in the guard
slice, no later than the guard. Docs never run ahead of `master`.

**Why four slices.** D6 removed the start-up step, the marker and the lifecycle
proofs that needed their own slice, so the earlier five (P1, P2a, P2b, P3, P4)
become four. P1 is not fail-closed and is safe alone. P2 is the one fail-closed
change and cannot be split without shipping a guard that is untested or a proof
with nothing to prove. P3 is display and accessibility polish that is not needed
for safety (the refusal already reaches the user through the existing region),
so it can follow. P4 is docs and whole-change budgets. Four, not three, because
folding P3 into P2 makes the guard slice the largest in the change for no
safety gain.

A criterion may be split by clause across slices, each part named with the
slice that proves it, as SEC-004 does (for example "AC-SEC-6 (writer clauses)"
in P1 and "AC-SEC-6 (sync clauses)" in P2). A criterion that is not split is
listed once, whole. Retired criteria are in no slice. The `_internal_meta`
prerequisite is not a slice: it lands on `master` first, and P1 depends on it.

| Slice | Goal | Depends on | ACs closed | Hazard if promoted alone, and how the slice avoids it |
|---|---|---|---|---|
| P1 | Store the binding and make recovery smooth. The hidden binding option; the single normalisation function (it never raises: an unparseable address returns no value); the one generic `Settings` write method (memory only) with the lock and rollback of AC-DATA-1; the settings read omits non-readable options; a non-empty key save writes key and binding in one write through the value hook (empty binding when the address cannot be normalised); an empty key save clears the binding; the wizard awaits the URL save before the key save; `buttonField.execute()` awaits a flush of its own section's pending single-option saves and re-reads the section on a refused action (C1); the existing E2E named in AC-SIMP-6 is renamed. A binding value the file held before this release first ran is emptied once at start (AC-SEC-16). Nothing reads the binding to refuse anything yet, and nothing is bound at start-up. | the `_internal_meta` prerequisite on `master` | AC-SEC-4; AC-SEC-5; AC-SEC-15; AC-SEC-16; AC-SEC-6 (writer clauses); AC-SEC-7 (writer clauses); AC-QA-13 (writer clauses); AC-QA-15 (writer clause); AC-QA-19 (flush clause); AC-QA-21 (P1 breaks); AC-PROD-11 (re-read E2E); AC-ARCH-2; AC-ARCH-3; AC-ARCH-4; AC-ARCH-5 (normaliser clauses); AC-ARCH-7; AC-ARCH-9 (ordering clause); AC-OPS-7; AC-DATA-1 (writer clauses); AC-DATA-6 (writer clause); AC-DATA-10 (single-file storage) | Every key save now writes a second value, and `registerDefaults` writes the option as an empty value on every install's first start. Avoided by one atomic write, a hook that never raises (a mistyped saved address must never block a key save, AC-ARCH-5, AC-DATA-6, AC-SEC-6), and by nothing reading the binding yet, so a wrong or empty binding costs nothing in this slice. The flush is narrowed to the button's own section so a removal's Undo window in another section is not cut short (C1). The normaliser is final in this slice: P2 may not change its output for any shape in the AC-OPS-7 table, because the binding stored here is read by the guard there. Accepted: an address changed on a P1-only build without re-entering the key is refused once the guard lands (AC-OPS-8, fact three). |
| P2 | The guard. `_jackettCredentials` becomes the one reader of the saved key, hands the normalised address to `getJackettIndexers`, and refuses unless the binding is non-empty and equals it, with the AC-DESIGN-5 text as the API `error` (the `jackett_sync` and `jackett_test` routes) and the `unbound` and `mismatch` WARNING reason codes; the docstring and test-docstring removals; the existing `world` fixture gets its binding through a production writer in the same slice. [Amended 2026-11-22, P2 review round 1: the rows a sync writes come from the saved address as saved, see Proposed shape; the guard's three reads of address, key and binding happen in one hold of the settings lock.] | P1 merged | AC-SEC-1; AC-SEC-2; AC-SEC-3; AC-SEC-6 (sync clauses); AC-SEC-7 (sync clauses); AC-SEC-9; AC-SEC-10; AC-SEC-11; AC-SEC-14; AC-SEC-17; AC-QA-1; AC-QA-5; AC-QA-11; AC-QA-12; AC-QA-13 (sync clauses); AC-QA-15 (sync clause); AC-QA-20; AC-QA-21 (P2 breaks); AC-QA-22; AC-PROD-5; AC-PROD-7; AC-PROD-11 (copy clauses); AC-DATA-1 (sync clause); AC-DATA-4; AC-DATA-6 (sync clauses); AC-DATA-8; AC-DATA-10 (restore and rollback cases); AC-DESIGN-5 (API error clause); AC-ARCH-5 (checker clauses); AC-ARCH-9 (not-refused clause); AC-OPS-10; AC-OPS-11 | **Accepted cost (D6):** when the guard ships, every existing install's saved key is unbound, and its next Sync (or API `jackett_test`) is refused once with the AC-DESIGN-5 text; the user checks the address and enters the key, which binds it. Searches and downloads continue with no action (AC-PROD-5). The recovery is smooth because P1 already carries the own-section flush and the re-read, and the final refusal text ships here, in the guard slice. Also: the guard locks a working install out of Sync until the key is entered, and the existing `world` fixture goes red. Avoided by the P1 dependency, by AC-QA-20 changing the fixture in this slice, by the upgrade proofs AC-QA-13, AC-QA-15 and AC-PROD-5 landing with the lock rather than a beta later, and by the mutation proofs of AC-QA-21. The largest slice. |
| P3 | The refusal where the user reads it: the Settings Sync result and the wizard's Jackett result line show the AC-DESIGN-5 text in both themes, announced once; the button result region is a persistent `role=status`; recovery by checking the address and re-entering the key; E2E and axe. | P2 | AC-QA-19 (refusal-text clauses); AC-DESIGN-1; AC-DESIGN-4; AC-DESIGN-5 (display clauses); AC-PROD-3; AC-PROD-12; AC-PROD-13; AC-QA-23; AC-QA-24; AC-A11Y-3; AC-A11Y-4; AC-A11Y-5; AC-A11Y-6; AC-A11Y-8; AC-A11Y-11 | A refusal the user cannot see or hear, and a shared result region changed for every Settings button. Avoided by the E2E against the real server with no `page.route` on the sync route in the Settings tests (AC-QA-19), the one stubbed wizard test (AC-A11Y-4), and the existing button-field E2E staying green. Until P3 the refusal shows as the raw `error` text through the existing region, acceptable for a promoted beta. P3 adds a local fake Jackett fixture under `tests/e2e/` (none exists today), which AC-PROD-3 and the success half of AC-QA-19 need. [D7: P3 also carries the stop of AC-PROD-12, which closes the same-press cases of gaps (b) and (h) in Settings; its hazard is a button that now refuses to run, avoided by the unit cases of AC-QA-23 (including the press with nothing pending and the successful save, so a working Sync is never stopped) and the E2E in which the server refuses the save.] |
| P4 | Last: docs, removals and the whole-change constraints, checked against the cumulative diff. The Jackett section of `docs/reference/API.md` (AC-OPS-8, AC-SEC-12) and the debt entry (item 5 replaced by a pointer, gap 3 closed if the restore is generic). | P1, P2, P3 merged | AC-SEC-12; AC-SEC-13; AC-SIMP-1; AC-SIMP-2; AC-SIMP-3; AC-SIMP-4; AC-SIMP-5; AC-SIMP-6; AC-SIMP-7; AC-SIMP-8; AC-SIMP-9; AC-SIMP-10; AC-SIMP-11; AC-PROD-4; AC-PROD-9; AC-A11Y-9; AC-A11Y-10; AC-DATA-11; AC-DATA-12; AC-ARCH-1; AC-ARCH-8; AC-ARCH-11; AC-ARCH-12; AC-OPS-8; AC-OPS-12 | Docs claiming a control that is not on `master`. Avoided by doing them last. AC-SIMP-4, -10 and -11 are cumulative budgets; each earlier slice's review still checks it has not broken one. |

**Placement check** (run on 2026-11-21 against the file after owner decision D6;
the script parses the "ACs closed" column of the table above and counts live
criteria only, excluding the three retired stubs; 74 at that date, 75 with AC-SEC-17, which is placed in P2, 78 with AC-PROD-12, AC-QA-23 and AC-A11Y-11, which are placed in P3, 80 with AC-PROD-13 and AC-QA-24, also placed in P3). 74 live criteria were defined
and 74 were placed; none is unplaced, none is placed but undefined, and no
retired stub is placed. The script's own output is in the report that came with
this edit and is not reproduced here. The script checks that the clauses are
named and unique, not that the named clause matches the criterion's text; a
reader must check that.

- AC-SEC-4 is whole in P1 because nothing in it needs the guard of P2 (see its
  own note).
- AC-QA-13's sync clauses, AC-QA-15's sync clause and AC-PROD-5 are in P2, with
  the guard, because every merge publishes a beta and the proofs that upgraders
  keep working (searches) and are asked once (Sync) must land with the lock.
- AC-QA-20 is in P2: the `world` fixture it changes goes red the moment the
  guard lands, so the fixture must change in the same slice. Its rule that no
  test writes the binding directly (outside the named exceptions) already
  binds the tests written in P1.
- AC-QA-12 is whole in P2: its lock proof is a writer property but is observed
  through a sync.
- AC-QA-19's flush clause is in P1, before the guard, so the Settings page never
  ships a guard without the flush that makes recovery one step; its
  refusal-text clauses are in P3.
- AC-PROD-3 is in P3, because its recovery is the end-to-end Settings press.
- AC-PROD-13 and AC-QA-24 (owner decision D9) are in P3, whole: the key-rejected
  text is shown through the same result region as the refusal, and its server
  change (`torrentpotato.py` only) is small.
- AC-PROD-12, AC-QA-23 and AC-A11Y-11 (owner decision D7) are in P3, whole: the
  stop is a change to the same component and the same result region as the
  display work, and its texts are shown through the region P3 makes persistent.
- AC-A11Y-9 and AC-DESIGN-1 both say "no control is added"; AC-DESIGN-1 is
  closed with the Settings and wizard render checks in P3, AC-A11Y-9 in the
  final review.
- AC-SEC-13 ("no route is added") is satisfied by the absence of one in the
  cumulative diff, so it closes in P4. `torrentpotato.jackett_sync` and
  `torrentpotato.jackett_test` are already in `ORIGIN_CHECKED_API_ROUTES`.
- The `_internal_meta` prerequisite is outside the slices (it lands on `master`
  first); AC-SEC-15 proves it for the binding in P1.

---

## Spec gaps found at review

Found while building P1 and at its first review round (2026-11-21). No criterion
text was changed; each is a gap a planning lens could have caught.

| Gap | What was missing | Lens that could have caught it | Now carried by |
|---|---|---|---|
| (a) Normaliser edge cases | The treatment of a query, a fragment (even an empty one), an internationalised (IDN) host, and whitespace inside the address (surrounding whitespace is trimmed), control characters or a backslash was unspecified. Decided at build: such an address has no normal form, so a key saved over it gets an empty binding. A host written in non-ASCII characters therefore cannot be bound, with one exception found at the P2 review round 2: U+212A (the Kelvin sign) is lower-cased by `urlsplit` to ASCII `k`, so a host written with it binds as ASCII, and rows are then built from the normalised form (AC-SEC-17); the same host written in its punycode (`xn--`) form can. P4's `docs/reference/API.md` known limits must say so and give that workaround. **Extended 2026-11-22, P2 review round 3 (owner decision pending; to be carried into the P4 known limits and the release notes):** an address with non-ASCII characters in its PATH or USERINFO (for example `http://h:9117/jackétt`, `http://üser:pw@h:9117`) synced on `master` and is now unbound for good: the two parsers disagree on it (urllib3 percent-encodes, `urlsplit` does not), so every Sync and Test is refused and entering the key again does not help. Workaround, measured: save the percent-encoded address; it binds, and the first merge sync then adds one copy of each existing row. Also, a Kelvin-sign host gets one duplicate row on the first merge sync after upgrade (same host, same key). | security, architecture | AC-ARCH-5, AC-OPS-7 (tests in `tests/unit/test_jackett_address_normaliser.py`) |
| (b) Flush after a refused save | The Settings flush carries on to the next save, and to the action, after a refused own-section save (`saveSingle` never throws), whereas the wizard stops. P2 must list it as an accepted gap or close it. **Accepted in P2, owner decision pending on a Settings follow-up:** the guard does not change this behaviour. After a refused own-section save the Settings button still goes on to the action, which the guard then refuses or allows on the server's own state, so nothing is sent that the binding does not permit; what a user usually sees is the refusal of the action, not of the save. [Corrected 2026-11-22, P2 review round 1: that is not true when the ADDRESS save is refused or fails and the key save succeeds. The key is then bound to the address the server still holds and Sync goes there, with nothing refused. Pointer in `docs/technical-debt.md`, item 11 of the Newznab positional lists entry.] **Closed by owner decision D7, as amended at P3 review round 1, 2026-11-22 (P3):** at a press the Settings button sends again every unsaved single-option value of its own section (a refused or failed value stays unsaved), in the order typed, sends nothing behind one that did not land, and runs the action only if all of them land (AC-PROD-12). What remains, in plain words: outside a press the fields still save independently, so a key saved on its own behind a refused address is bound to the old address on the server (the key is bound to the address the server holds when it is saved); a later press then re-sends the still-unsaved address first, is refused or stopped, and never runs a Sync on that mismatch, so the key sits bound to the old address until the user fixes the address and the key saves again. An unsaved value the user cannot see (hidden by the Advanced toggle, or on another tab) blocks the button until it is shown and fixed, or the page is reloaded. | qa, product | AC-SIMP-6, AC-SIMP-7, decision C1, AC-PROD-12, AC-QA-23 |
| (c) Falsy non-text key | A falsy non-text key value (JSON `0`, `false`, `null`, `[]`) stores an empty binding, because it is read as no key until a restart. The criteria only said nothing is sent. | data | AC-SEC-3, AC-SEC-6 |
| (d) Wizard on a failed address save | The wizard no longer sends the key save when the address save fails (AC-ARCH-9 asked only for the order). | product | AC-ARCH-9 |
| (e) Re-read scope | The read after a refused action applies to any button in a section with a combine group. Today there is exactly one such button option in the tree. | architecture | AC-SIMP-6 |
| (f) A binding planted before the upgrade | On a release without the binding option, `settings.save` accepts `torrentpotato.jackett_key_binding` (in any case) as an ordinary option name, and `registerDefaults` keeps an existing value, so a value planted there survived the upgrade, hidden from the settings read, and read as a binding nobody entered a key for. Measured at the P1 review against `master` and the first P1 build. Left alone it would have switched the P2 guard off for that install until the next key save, suppressed the once-only refusal that makes the user check the address (D6, AC-PROD-11) when the address had also been changed, and come back with any pre-upgrade backup. AC-QA-13, AC-SEC-3, AC-DATA-10's first restore case and AC-OPS-8 fact four all assumed a pre-upgrade file is unbound. **Owner decision, 2026-11-21:** first "accept and record", then, on the fuller description above, **clear it once at the first start**. Closed by AC-SEC-16, which makes those assumptions true; its own known limit (a planted flag) is recorded there. | security | AC-SEC-16; D6 as amended |
| (g) What a generic start-up clear does to other options | AC-SEC-16 as first written would also have emptied a declared non-empty default on a fresh install (caught by an existing test at build; the rule clears only a value the file already held), and it empties a user-entered value if an option with no `ui-meta` is later marked `hidden` (measured at review). The next spec, hiding credentials in combined rows, must not reach for `ui-meta: hidden` on an existing credential without migrating the value; shipping the flag a release earlier protects only installs that ran that release. | data, architecture | AC-SEC-16 (second known limit and its guard test) |
| (h) A save already in flight at Sync | The PR #617 review found that `saveSingle` drops its pending entry as it sends, so the flush could not see an address save whose request had left but not returned: the key save could arrive first and the binding hook would bind the new key to the OLD address, persistently. Not only the shown-once refusal that decision C1 had recorded as a known gap. Mitigated after P1: a per-section save chain that the flush awaits, with a wait bounded to 10 seconds from the send of the save ahead (decision C1). After that deadline a later save can go out ahead of a sent-but-unanswered earlier one, so a key can still be bound to the old address. If the address save later lands, the next Sync is refused and the key is entered again; until it does, or if it never does, the key is bound to and used with the address the server still holds, including by the Sync of the same press (the rows that Sync writes then carry the new key as `pass_key` against the old hosts until a later sync). `master` can already do this, because its two saves are independent; this change narrows the window to a request that has been unanswered for 10 seconds. The key is only ever sent to the address the SERVER held when the key was saved. The panel-wide flush that the Trakt Start button awaits is bounded the same way now (on `master` it waited for ever on an unanswered save); see C1. **Closed for a press made while a value of the section is unsaved by owner decision D7, as amended at P3 review round 1, 2026-11-22 (P3):** an unanswered save leaves its value unsaved, so the button does not send the action, says the changes have not finished saving, and the next press sends the value again and stops again if there is still no answer (AC-PROD-12). Not closed, in plain words: a request the server never answered may still land later, so the same value can reach the server twice (harmless), and if the user changed that field in the meantime the late request can overwrite the newer value (unverified; the same kind as on `master`, where saves were independent); a later save outside a press can still go out ahead of an unanswered earlier one after its deadline, so a key can then be bound to the old address, and if the address save then lands the next Sync is refused and the key is entered again. The panel-wide flush now awaits the section chains (conductor decision C2). | qa, security | AC-SIMP-6, AC-SIMP-7, decision C1, AC-PROD-12 |
| (i) Leaving the page behind an unanswered save | The per-section chain means that leaving the page while an earlier save of the section is unanswered drops the later save queued behind it; before the chain both had been sent. Found at the round 1 review of the fix for (h). The window is one save's round trip, plus one wait deadline for each save queued ahead of it. It fails closed for the key (unbound, refused at the next sync, AC-PROD-3), and saves still on their 500 ms timer were already lost on leaving. Recorded, not fixed. | qa, data | decision C1 |
| (j) Outbound proxy settings | `core.use_proxy` and `core.proxy_server` are ordinary writable options, so a settings write can route an http Jackett request, key included, through a host the writer chose. Pre-existing; affects every credential sent over http; not closed by this spec. Found at the P2 review, 2026-11-22. **Owner decision pending.** The final wording of the mandated debt line of AC-PROD-9 ("the saved key is only sent to the address it was saved for") is the owner's to settle before P4. | security | none |
| (k) Redirects | Not a new finding: redirects forwarding the key are debt item 6 in `docs/technical-debt.md` and the first "Not in scope" bullet. The key travels only when the redirect's `Location` keeps the query. Pre-existing; not closed by this spec. Pointer recorded at the P2 review, 2026-11-22 (round 2). **Owner decision pending.** | security | none |
| (l) A Jackett error reply with `<error>` as its root | `getJackettIndexers` looks for `root.find('.//error')`, which skips the root element, so a reply whose root is `<error>` reads as success with zero indexers. Pre-existing; matters more once every upgraded user re-enters the key. Found at the P2 review, 2026-11-22. Closed on 2026-11-22 by owner decision, in `fix/jackett-root-error-reply`: a reply whose root is `<error>` now answers the same failure as a nested one (`{"success": false, "error": "Jackett returned an error response"}`, one ERROR log line, no text from the reply), and a genuine empty `<indexers/>` still reads as an empty list. What is proven is only this: a reply whose root is `<error>` and that arrives with a success status used to read as success with zero indexers, and is now an error. The status a real Jackett uses for a wrong key was not measured; if it is 401, the HTTP client raises first and the user already saw "Failed to connect to Jackett" with or without this change. [Superseded 2026-11-22 (P3 review round 2): since D9 an HTTP 401 reads "Jackett did not accept the API key. Copy it again from your Jackett dashboard.", and so does an `<error code="100">` reply; see gap (q).] | qa | none |
| (m) What AC-OPS-11 counts | The criterion says the change adds one option name; the file gains the binding and its access flag (`jackett_key_binding_internal_meta`), which `registerDefaults` writes for every option that declares one. Read as "one option name and its access flag" (2026-11-22, P2 review round 1; the criterion's substance is unchanged, and the P2 test asserts exactly those two). | operability | AC-OPS-11 |
| (n) Leaving the Settings tab while a press waits | Leaving the Searchers tab while a press is waiting on saves rebuilds the button with an empty result region, so the stop text the user never saw is lost (the toast remains). Informational, not fixed. Found at P3 review round 1. | accessibility | AC-A11Y-11 |
| (o) The Settings action button's size | The Sync Indexers button is about 32 px tall at phone width: above WCAG 2.2's 2.5.8 minimum of 24 px, below the project's 44 px house floor. It predates this change and is not touched here. **Owner decision (2026-11-22): recorded, fix later**; pointer in `docs/technical-debt.md`. | design, accessibility | none |
| (p) Text spacing on the result region | WCAG 1.4.12 (text spacing) is not tested for the result region or the wizard's result line. | accessibility | none |
| (q) What D9 rests on, and what repeated mistyping does | Neither D9 trigger (HTTP 401; an `<error code="100">` reply) was observed against a real Jackett: both come from Jackett's documented behaviour as recalled by reviewers. The fake Jackett answers a wrong key with the `<error code="100">` document at HTTP 200. **A 401 used to count towards the HTTP client's per-host failure count (measured before the fix):** for a non-local host (any host name, including a Docker service name such as `jackett`, and any public address; loopback and RFC 1918 addresses are exempt) the sixth failed request disables the host for 15 minutes, and from the seventh attempt Sync answers "No response from Jackett" with no request made. The disabled host key is `host:port`, so searches through the same Jackett address are also refused for those 15 minutes. **Owner decision, 2026-11-22: a rejected key (HTTP 401) must stop counting towards that cut-off. Fixed, in its own small PR after this branch: a 401 no longer counts towards the per-host cut-off for every caller, neither adding to the count nor clearing it, and 403, 429, 5xx and connection errors are unchanged.** Also, an HTTP 401 that is not Jackett's (for example basic authentication on a reverse proxy in front of it) is reported as the key being rejected, which is untrue and which re-copying the key does not fix; accepted with D9 and recorded. | operability, qa | AC-PROD-13, AC-QA-24 |
| (r) D8 text against its clauses | **Accepted by the owner, 2026-11-22: the D8 text stays exactly as it is.** Two clauses of AC-DESIGN-5 are only partly satisfied by it: (1) "says nothing untrue for either cause": "needed once after this update, or after the URL changes" is untrue for a key that is unbound for another reason (a restored older `config.ini`, or the wizard run with the key left blank, which clears the saved key); (2) for an API caller of `jackett_test`, "paste it above and press Sync" refers to a page the caller is not on (the spec already returned the same string to API callers; no page calls `jackett_test`). The wizard's button is labelled "Sync Trackers from Jackett", so "press Sync" is a short form there. | product | AC-DESIGN-5 |
| (s) The order a press saves in | "In the order typed" in AC-PROD-12 is the order each value FIRST became unsaved: a retyped value keeps its place. Example: the key is refused and stays unsaved, then the address is typed, then the key is retyped; the press sends the key first (the server binds it to the old address), then the address, and the Sync that follows is refused with the D8 text, so nothing goes to the wrong place. Moving a retyped value to the end is a two-line change and was NOT made: it would make the order the true typing order but would put a corrected address behind a key typed after the first attempt (the common recovery), which is worse. Pinned by a unit case. Found at P3 review round 2. | qa, security | AC-PROD-12 |
