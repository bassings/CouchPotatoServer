# SEC-004: Multi-row settings are saved as rows, so a value can never move to another row

> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the next spec improves.

**Status:** agreed. Owner decisions 2026-11-14: "Refuse commas at save",
server-enforced and covering anything that saves settings; then D1 to D6 below
(Jackett sync in scope; warn and save on first edit for misaligned groups; the
wizard loads stored indexers; JSON transport; no stale-save protection; two
pairing gaps left as debt).
**Lenses run:** security, QA, simplicity, product, design, accessibility, data,
architecture, operability, by `/plan-cycle` on 2026-11-14 (run
`wf_ff898781-3bf`, all nine returned FINDINGS, none blocked). **Skipped:** none.
**Hand edits after the lenses ran** (no lens wrote any of these, so the review
cycle should treat them as untested wording):

- *Owner decisions D1 to D6 (2026-11-14):* the status header; the decisions
  table; AC-PROD-4; AC-DESIGN-12; AC-DATA-4 (withdrawn); the stale-save clause
  removed from AC-DATA-2; the "Vetoed at planning" row for the wizard loading
  stored rows; AC-DATA-18 (added).
- *Amendment of 2026-11-14 from a consistency review and a delivery plan*
  (decisions by the orchestrator under the owner's standing authority for
  engineering calls, unless marked owner): the fourth fact in the Problem
  section; the removal-criterion cells of the first "What this replaces" table;
  the new "Definitions" subsection; decision rows D1, D2, D3 and D5; added
  AC-SEC-11, AC-SEC-12, AC-DATA-19, AC-DATA-20 and AC-ARCH-11; edits to
  AC-SEC-7, AC-SEC-9, AC-QA-2, AC-QA-4, AC-QA-10, AC-QA-12, AC-QA-13,
  AC-SIMP-6, AC-SIMP-8, AC-SIMP-10, AC-SIMP-11, AC-PROD-4, AC-PROD-10,
  AC-DESIGN-5, AC-DESIGN-10, AC-DESIGN-12, AC-A11Y-1, AC-A11Y-6, AC-DATA-4,
  AC-DATA-10, AC-DATA-17, AC-DATA-18, AC-OPS-1 and AC-OPS-3; the "Vetoed at planning" rows
  for the encoded comma and the shared wording; the new "Delivery slices"
  section; and the entries under "Spec gaps found at review".

## Problem

Five settings groups are edited as rows but stored as parallel comma-separated
lists, one list per column, paired back up by position when read:

| Section | Columns (`combine`) | Declared in |
|---|---|---|
| `newznab` | `use`, `host`, `api_key`, `extra_score`, `custom_tag` | `couchpotato/core/media/_base/providers/nzb/newznab.py` |
| `torrentpotato` | `use`, `host`, `pass_key`, `name`, `seed_ratio`, `seed_time`, `extra_score` | `couchpotato/core/media/_base/providers/torrent/torrentpotato.py` |
| `imdb`, `itunes`, `letterboxd` automation | `automation_urls_use`, `automation_urls` | `couchpotato/core/media/movie/providers/automation/` |

Three facts make this unsafe, all confirmed in review of PRs #587 and #588:

1. **A comma inside one cell becomes a new position.** Nothing rejects or
   escapes it. For `newznab` and `torrentpotato` the cell next to a host is a
   credential (`api_key`, `pass_key`), so the text after a comma in a URL is
   treated as another indexer and is sent the NEXT row's credential. Reproduced
   on master through the real Settings page and the real `search()` loop.
2. **The page hides the damage and then makes it permanent.** `combinedField`
   (`couchpotato/ui/templates/partials/settings/scripts.html`) builds its rows
   from the longest stored list and, on any edit, re-saves every column padded
   to that length. After a reload and one unrelated edit the lists are equal
   length with hosts shifted against keys. Deleting the bogus row leaves the
   following indexer paired with the wrong key.
3. **The server cannot see rows.** Each column is saved by its own request
   (`settings.save` with `section`, `name`, `value`), debounced separately, and
   the value arrives already joined. The server cannot tell a comma inside a
   cell from a separator, and a failed request leaves the columns from
   different edits side by side. `getParams`
   (`couchpotato/core/helpers/request.py`) also URL-decodes values a second
   time, so `%2C` is stored as a comma.

`getHosts` raises when `use` is shorter than `host`, and `isEnabled` raises on
an empty or non-numeric `use`. Those crashes currently stop a search before
later rows are queried. Two attempts to turn them into "disabled" each produced
a measured case where a credential reached the wrong indexer where master had
stopped (see `docs/technical-debt.md`, "Newznab positional lists"). They are
not to be guarded until misalignment cannot be written in the first place.

A fourth fact was found after the planning cycle: **a writer the first draft
never named, and a wizard button that has been calling a route that does not
exist.**

4. **`jackettSync` writes all seven torrentpotato columns with seven separate
   per-column writes** (`torrentpotato.py:393-399`), with no comma check and
   nothing that undoes the earlier writes if a later one fails. Its live caller
   is the Settings page button: the `jackett_sync` option declares
   `button_action` `torrentpotato.jackett_sync` (`torrentpotato.py:496`), which
   `partials/settings/scripts.html:807` fetches. The wizard's "Sync Trackers
   from Jackett" does not reach it: `wizard.html:1543` requests
   `provider.torrentpotato.jackett_sync`, while the registered route is
   `torrentpotato.jackett_sync` (`torrentpotato.py:29`), and an unregistered
   route returns `API call doesn't exist` (`couchpotato/api.py:55`). The wizard
   E2E specs stub the name the wizard requests, not the registered one
   (`tests/e2e/wizard-keyboard.a11y.spec.ts:235`, `:295`, `:1111`), so the
   suite is green over a button that cannot work against a real server.
   Decision (orchestrator, 2026-11-14, under the owner's standing authority for
   engineering calls): the wizard's URL is corrected only in or after the slice
   that puts `jackettSync` behind the validated group write (P2), never before,
   because correcting it earlier would newly expose the unvalidated writer to
   the first-run screen; the E2E stubs are corrected in the same slice.

## Approach (for the planning cycle to challenge)

The owner's decision is that the server, not only the page, refuses a save
that would put a comma inside a row. Because of fact 3 that cannot be bolted
onto the existing per-column save. The proposal:

- A save of a multi-row group goes to the server **as rows**: one request
  carrying every column of the group, cell by cell.
- The server validates the whole group (every row has the same columns; no
  cell contains a comma; values are taken as sent, not decoded a second time)
  and writes all columns in one operation, or writes nothing.
- The existing per-column `settings.save` is refused for any option that
  belongs to a `combine` group, so there is one way to write these values and
  it is the validated one.
- The Settings page and the setup wizard both use it. The page shows which row
  and which field was refused, and never re-saves columns it merely padded.
- The stored format in `config.ini` does not change. This is a write-path
  change, not a migration.

## Not in scope

- Changing how indexers are stored (records instead of parallel lists). The
  owner chose against it on 2026-11-14: the migration risk sits in the
  irrecoverable tier.
- Detecting or repairing installs whose lists are already misaligned. It
  cannot be done reliably; the v3.278.0 release notes tell users to check.
- Guarding `getHosts` / `isEnabled` (and the same lookups in
  `torrentpotato.py`). A follow-up may revisit them once this has shipped and
  misalignment can no longer be written.
- The second URL-decode in `getParams` for settings outside the combined
  groups. It is recorded as debt; the new save path must not depend on it.

## What this replaces

| What goes | Owning lens | Removal criterion |
|---|---|---|
| Per-column saves of `combine` options from the Settings page and the wizard | security | AC-SEC-10, AC-QA-17 |
| `combinedField` re-saving columns it padded | data | AC-DATA-11 |
| The wizard's client-only comma check as the sole guard (`assertNewznabHasNoCommas`) | simplicity | AC-SIMP-8, AC-SIMP-12 (demoted, not deleted) |

---

## Acceptance criteria

*Written by `/plan-cycle` on 2026-11-14 from nine lens reports. The outcomes the criteria secure:*

- After this change no sequence of saves through the Settings page, the
  wizard or the settings API can leave a credential paired with a host it was
  not entered against, in any `combine` group, in a case where the save
  reported success.
- A refused save changes nothing on disk and tells the user which row and
  field to fix, without echoing a credential or a URL.
- A save that succeeds for a group is all-or-nothing across its columns.
- Existing aligned configurations read and re-save unchanged, byte for byte.
- An existing misaligned configuration is not silently "repaired" into a
  different wrong pairing by opening the page.
- Rollback is reverting the commit: the stored format is unchanged.

### Decisions these criteria encode (owner-confirmed 2026-11-14)

The lenses found the Approach undecided or self-contradictory at these points
and assumed an answer to make the criteria testable. The owner then decided
each one: D1, D2, D4 and D6 as assumed; **D3 differently** (the wizard loads
the stored indexers, overriding the simplicity veto); **D5 dropped** (no
stale-save protection; recorded as debt). The rows below state the decision as
taken, and the criteria were edited to match.

#### Definitions

*(added after the planning cycle from the consistency review; orchestrator,
2026-11-14, under the owner's standing authority for engineering calls. D2, D3
and every criterion that uses these terms use them in this sense.)*

- **Stored indexer** (Newznab): a stored row with a non-empty `host` AND a
  non-empty `api_key`. A fresh install stores six default hosts with `use` all
  `0` and empty keys: `newznab.py:293-327` declares `enabled` default `True`,
  six hosts, `use` of `0,0,0,0,0,0` and `api_key` of `,,,,,` (the consistency
  review measured `registerDefaults` on an empty config writing exactly those
  values). Those six rows are **not** stored indexers. `isEnabled`
  (`newznab.py:197`) requires a non-empty key, so a keyless row can never be
  searched. A stored row that is not a stored indexer is a *keyless row* (host,
  no key) or, where it has a key and no host, a *hostless row*; AC-DESIGN-12
  says what the wizard does with each.
- **Misaligned group** (decision D2; the consistency review's item B2): a
  group is misaligned only when the columns that pair a credential with its
  target disagree in length after trailing empty cells are ignored. The pairing
  columns are: for `newznab`, `host`, `api_key` and `use`; for `torrentpotato`,
  `host`, `pass_key`, `use` and `name`; for the automation groups, both
  columns. The other columns (`extra_score`, `custom_tag`, `seed_ratio`,
  `seed_time`) do not decide it:
  - A non-credential column that is LONGER than `host` only by cells holding
    that column's default value (or empty) is not misalignment. Today's wizard
    writes `host`, `api_key` and `use` for N rows and leaves `extra_score` and
    `custom_tag` at their six defaults (`wizard.html:1350-1352`, the three
    `saveSetting('newznab', ...)` calls), so most wizard-configured installs
    have that shape and must NOT be shown the notice. Such surplus default
    cells are not shown as rows and are truncated to the row count on the next
    successful group save.
  - A non-credential column that is SHORTER than `host` is not misalignment
    either: the reader already supplies the default for a missing cell
    (`newznab.py:150-154`), the page shows that default, and the next
    successful group save writes it.
  - A non-credential column that is longer than `host` by a cell holding a
    non-default value is treated as misaligned, because the surplus cell is
    data whose row cannot be identified.
  - A group whose stored cells are all empty gets no notice (D2).
  The row count of a group is the length of its longest pairing column after
  trailing empty cells are ignored.

| # | Question the spec left open | Answer the criteria assume | Criteria that carry it |
|---|---|---|---|
| D1 | Is torrentpotato `jackettSync` (a server-side writer of all seven torrentpotato columns, called by the wizard) in scope? | Yes. It writes through the same validated group write. Simplicity vetoed it; security and data supplied criteria showing a credential can reach the wrong host on this path, which a simplicity veto cannot override. Whether a comma in a Jackett title refuses the sync, skips that indexer or is removed from the name is left open: the criteria accept any of the three. Amended (orchestrator, 2026-11-14, under the owner's standing authority for engineering calls): "called by the wizard" was wrong when written. The live caller is the Settings page button; the wizard requests a route name that is not registered (Problem, fact 4). The wizard's URL and the E2E stubs are corrected in slice P2, with the validated write, and never earlier. | AC-SEC-9, AC-DATA-9, AC-DATA-10, AC-SIMP-3 |
| D2 | What does the page do with a group whose stored columns differ in length? | For a **misaligned group** as defined above (pairing columns only; surplus default cells in a non-credential column do not count), it shows one row per position with a persistent notice, writes nothing on load, and on the user's first edit in that group saves exactly the rows on screen. A group whose stored cells are all empty (the shipped torrentpotato defaults) gets no notice, and neither does a wizard-configured install whose `extra_score` and `custom_tag` still hold their six defaults. | AC-DESIGN-10, AC-QA-10, AC-DATA-11, AC-DATA-12, AC-A11Y-10 |
| D3 | What does the wizard send for the columns it never shows, and what happens to indexers already stored? | Owner decision: the wizard loads the Newznab **stored indexers** (as defined above) and shows them as its rows, so re-running it loses nothing. It sends all five newznab columns for every row: the stored `use`, `extra_score` and `custom_tag` for a row that was loaded, the defaults for a row added in the wizard (`use` of `1`, `extra_score` of `0`, `custom_tag` empty). Simplicity's veto of loading stored rows is overridden by the owner. Amended (orchestrator, 2026-11-14, under the owner's standing authority for engineering calls): `use` added to the kept columns, because today's wizard forces `use` to `1` for every row (`wizard.html:1348`) and would re-enable an indexer the user had switched off; keyless default rows are not stored indexers, are not shown, and are not kept when the wizard saves the group; a failed or pending read is never an empty install (AC-DATA-19); zero kept rows sends no group save (AC-DATA-20). | AC-PROD-4, AC-DESIGN-12, AC-DATA-17, AC-DATA-18, AC-DATA-19, AC-DATA-20 |
| D4 | Which transport carries the rows? | A JSON array in an `application/json` POST body, the one shape the shared parameter parser does not decode a second time. Every other shape is refused. | AC-ARCH-6, AC-QA-3, AC-SEC-2, AC-ARCH-5 |
| D5 | Is a save built from a stale read (two tabs, or a Jackett sync landing between read and save) refused? | Owner decision: no. A save built from a stale read still overwrites; no freshness token is added. Recorded as debt, as the fourth declined gap in AC-PROD-10: a save built from a stale read (a second tab, the wizard, or a Jackett sync landing between a page's read and its group save) overwrites the newer rows wholesale. Clarified (orchestrator, 2026-11-14, under the owner's standing authority for engineering calls): the exposure is narrower than master's, not unchanged. Newer rows can be lost but not mispaired, because each group save comes from one snapshot. The wizard is now a stale reader too, with a long gap between its read and its save. | AC-DATA-4 (withdrawn), AC-PROD-10 |
| D6 | Do `newznab.custom_categories` (paired by position but outside `combine`) and empty cells in automation rows (dropped by the readers before pairing) get fixed here? | No. Both are vetoed below and recorded as open debt. | AC-PROD-10, AC-QA-7 |

### What this replaces: removal criteria

| What goes | Removal criterion |
|---|---|
| Per-column saves of `combine` options from the Settings page and the wizard | AC-SEC-10, AC-QA-17 |
| `combinedField` re-saving columns it padded | AC-DATA-11 |
| The wizard's client-only comma check as the sole guard | AC-SIMP-8, AC-SIMP-12 (demoted, not deleted) |
| The seven separate per-column writes in `jackettSync` (not in the table above; found at planning) | AC-DATA-9, AC-DATA-10 |
| The per-column toast as the carrier of a combine refusal; the remove control on a single row | AC-DESIGN-7, AC-DESIGN-8 |

### Security (lens-security)

- **AC-SEC-1:** A request to the group-save route that carries no API key (no `X-Api-Key` header and no key segment in the path) returns HTTP 401 and leaves the sha256 of `config.ini` identical; the same holds for a wrong `X-Api-Key`. Proof: integration test against the real FastAPI app.
- **AC-SEC-2:** The group-save route refuses a GET request and writes nothing (sha256 of `config.ini` unchanged), so cell values never travel in a URL; with a sentinel in every cell, a Playwright request listener sees no request whose URL contains a sentinel across an add-row, edit and delete-row flow on each combine group in Settings and across wizard completion with two Newznab rows. Proof: integration test plus E2E request listener.
- **AC-SEC-3:** `settings.save` refuses every column of every registered `combine` group, the refused set being derived at runtime from the registered option declarations (the test enumerates it from the loaded config); refusal holds for POST form, POST JSON and GET query transport and for any case variant of the option name (`API_KEY`, `Host`), and on refusal the sha256 of `config.ini` is unchanged and no `setting.save.<section>.<option>` hook fires. Proof: unit test parametrised over groups, transports and case variants. *(merges the refusal clauses of AC-QA-7 and AC-DATA-10; measured on master: `name=API_KEY` writes `api_key` and returns success)*
- **AC-SEC-4:** The group-save route writes only the declared columns of the named group: a section with no combine group (`core`), a column outside the group's `combine` list (`newznab.enabled`, `newznab.custom_categories`, `password`, `auth_required`), and a column that `isOptionWritable` reports as not writable (read-only or hidden ui-meta, for example `<name>_internal_meta = ro`) each refuse the whole request with the sha256 of `config.ini` unchanged; the writability check is the same `isOptionWritable` that `settings.save` uses, not a copy. Proof: unit test. *(merges AC-ARCH-7)*
- **AC-SEC-5:** The comma check runs on the exact string that is written, after all decoding: a cell submitted as a literal `,`, as `%2C` in a form body, as `%2C` under a nested bracket key (`rows[0][host]`), or as `%2C` inside a JSON body either refuses the save or is stored so that every column of the group splits on `,` to exactly the submitted row count, and no transport ever produces a stored column with more positions than rows. Proof: unit test over each transport through `callApiHandler`.
- **AC-SEC-6:** End-to-end pairing through the real HTTP app: after saving a two-row newznab group (H1/K1, H2/K2), a save whose row-1 host is `https://h1.example,https://evil.example` is refused with the sha256 of `config.ini` unchanged, and the real newznab `search()` run against the resulting config sends K1 only to H1 and K2 only to H2 with no request to evil.example (recorded urlopen); the same test passes for torrentpotato host and pass_key. Proof: integration test driving the real search loop.
- **AC-SEC-7:** With a distinct sentinel in every cell, refused and valid alike, a refused group save returns a body that identifies the row and the column in the structured form of AC-ARCH-11(iii) and contains no sentinel, and the CouchPotato log written during the request contains no sentinel; the same holds when the write is forced to fail (`Settings.save` raising), where the view catches the failure and logs it once without cell values (AC-OPS-3). Proof: unit test grepping the response and the log file. *(merges the no-values clauses of AC-QA-2 and AC-OPS-1; amended after the planning cycle: the clause requiring the traceback log line in `callApiHandler` was removed because it contradicted the single ERROR line of AC-OPS-3, and "names the row number and the field label" became the structured refusal, from which the client composes the text under AC-DESIGN-5)*
- **AC-SEC-8:** A successful group save returns a body containing no cell value from any column (sentinel test across all columns of newznab and torrentpotato), and a per-column `settings.save` refused under AC-SEC-3 returns a body that does not contain the submitted value. Proof: unit test.
- **AC-SEC-9:** torrentpotato `jackettSync`, which the Settings page's sync button calls today and which the wizard's "Sync Trackers from Jackett" calls once its URL is corrected in the same slice (Problem, fact 4; never in an earlier slice), writes the torrentpotato group through the same validated, all-or-nothing group write: with a stubbed Jackett returning an indexer titled `A, B`, and separately an indexer URL or a `jackett_url` containing a comma, on an install with pre-existing rows, the sync either refuses with the sha256 of `config.ini` unchanged, or writes a config in which all seven columns split to the same length, every pre-existing row keeps its own host, pass_key and name, and each new pass_key sits at the position of its own host; a sync that returns success never leaves the columns unequal, and the Jackett API key is never stored against a host built from text after a comma. Proof: unit test with stubbed `getJackettIndexers`. *(merges AC-PROD-5, AC-ARCH-4 and the behaviour clause of AC-QA-15; overrides the simplicity veto of this writer, decision D1; amended after the planning cycle: the wizard does not reach this writer today, and the slice that closes this criterion also corrects `wizard.html`'s request to the registered route `torrentpotato.jackett_sync` and the three stubs in `tests/e2e/wizard-keyboard.a11y.spec.ts`, with a test that the wizard's sync request reaches the registered route)*
- **AC-SEC-10:** Removal: per-column saves of combine options from the Settings page and the wizard are gone; a Playwright request listener records zero `settings.save` requests whose `name` is a column of any combine group across adding, editing and deleting rows on every combine group in Settings and across completing the wizard with two Newznab rows, and `wizard.html` contains no `saveSetting('newznab', 'host'`, `saveSetting('newznab', 'api_key'` or `saveSetting('newznab', 'use'` call. Proof: E2E request listener plus static grep test.
- **AC-SEC-11:** Every cell in a group save must be a JSON string. A cell of any other JSON type (number, boolean, null, array, object) refuses the whole request and nothing is written (sha256 of `config.ini` and in-memory values unchanged): a list cell would otherwise be stringified into text containing a comma, after the comma check had passed it. No cell is coerced to a string. Proof: unit test, one case per type. *(added after the planning cycle from the consistency review / delivery plan; no lens wrote it)*
- **AC-SEC-12:** A cell containing a carriage return, a line feed or any other C0 control character (U+0000 to U+001F) refuses the whole request and nothing is written: a continuation line that begins with `#` or `;` is dropped by `configparser` on reload, so a cell holding a line break can lose part of its value, or of a credential, without any save reporting a failure. Proof: unit test parametrised over CR, LF, CRLF, TAB and NUL in each column kind, plus a reload round trip that writes such a value directly through the parser and shows the reloaded value differs, proving why the refusal exists. *(added after the planning cycle from the consistency review / delivery plan; no lens wrote it)*

### QA (lens-qa)

- **AC-QA-1:** Happy path for every group: for each of newznab (5 columns), torrentpotato (7 columns), imdb, itunes and letterboxd (2 columns), a group save of 3 rows with distinct placeholder values in every cell, sent through the real HTTP route to a Settings instance backed by a temporary `config.ini`, returns success; re-read from disk with a fresh parser, each column equals its cells joined in row order, and the provider's real reader (`getHosts` for newznab and torrentpotato, the enabler and URL pairing for the automation readers) returns exactly the 3 entered rows in order. Proof: integration test parametrised over all five sections.
- **AC-QA-2:** Comma refusal covers every cell: parametrised over every (section, column) pair of all five groups and over first, middle and last row positions, a cell containing a literal `,` makes the group save return `success: false` with a response that identifies the offending row and column in the structured form of AC-ARCH-11(iii) (the 0-based row as sent and the column name; the text the user reads is composed by the client under AC-DESIGN-5), the sha256 of `config.ini` unchanged, and `Settings.get` for every column of the group returning its pre-save value. Proof: integration test. *(merges AC-PROD-2 and the server half of AC-PROD-1)*
- **AC-QA-3:** Values are taken as sent: cells containing `%2C`, `%2c`, `%252C`, a literal `%41`, `+`, `&`, `=` and the strings `true` and `false`, sent as a JSON array in an `application/json` body, are stored in `config.ini` byte-identical to what was sent (read back with a fresh parser); no cell is URL-decoded a second time and none is coerced to a boolean. Proof: integration test through the real HTTP route, shown to fail when the cell values are passed through `unquote` before the write. *(merges the round-trip clauses of AC-ARCH-6, AC-DATA-6 and AC-PROD-7; reworded because every route passes through `getParams`, which leaves a JSON list untouched)*
- **AC-QA-4:** Malformed group payloads are refused with nothing written (sha256 of `config.ini` and in-memory values unchanged), each as its own test case: a row missing one column; a row with an extra column not in that section's `combine` list; a column from a different section; a `rows` value that is not a list; a row that is not an object; an unknown section; an empty row list; and a cell that is not a JSON string (AC-SEC-11 carries the per-type cases). Proof: unit test. *(the index-gap and duplicate-index cases are replaced by the bracket-key refusal in AC-ARCH-6; the non-string case was added after the planning cycle)*
- **AC-QA-6:** A successful group save performs exactly one config file write: a spy on `Settings._save` records one call per group save regardless of column count (7 for torrentpotato). Proof: unit test.
- **AC-QA-7:** Options outside a combine group still save per column: `settings.save` of `newznab.enabled`, `newznab.custom_categories`, `torrentpotato.jackett_url` and a non-combine imdb option returns success and writes the value. Proof: integration test. *(the refusal clauses are in AC-SEC-3 and the synthetic-section clause in AC-ARCH-1)*
- **AC-QA-10:** A misaligned group is saved only as the rows the user saw: starting from a fixture whose newznab `host` list has 3 entries and whose `api_key` and `use` lists have 2, editing a cell in that group saves exactly the rows on screen at save time, so `getHosts` after a reload pairs each host with the key shown beside it and never with a key from another row; by correcting or removing rows the user can reach a stored group in which every column has the same length. A fresh install's shipped torrentpotato defaults (`use` empty, `pass_key` a single comma) remain editable and savable, asserted by an E2E that adds one torrentpotato row on a clean data directory and reads it back through `getHosts`. A fixture in the wizard-configured shape (three rows of `host`, `api_key` and `use`, with `extra_score` and `custom_tag` at their six defaults) is NOT misaligned under the Definitions: it shows three rows and no notice, and its first successful group save truncates the surplus default cells to three. The misaligned starting state is written into `config.ini` by a fixture before the worker's server starts, the way `tests/e2e/fixtures.ts:307-311` already runs `scripts/seed_e2e_data.py` (which writes `config.ini`) ahead of the server; it cannot be created through the API once per-column saves are refused, and it is not seeded through per-column saves in any slice. The read through `getHosts` uses a Python helper under `tests/helpers/`. Proof: E2E. *(merges AC-PROD-6; encodes decision D2; the wizard-configured case, the fixture rule and the helper were added after the planning cycle)*
- **AC-QA-11:** Settings page against the real server, with no route stub on the save endpoint: typing a comma into row 2's Api Key cell in the newznab group shows a visible error naming row 2 and the field, whose text does not contain the typed value, and the newznab lines of `config.ini` are unchanged, read through a server-side check and not the page's own state. Proof: E2E. *(merges the page half of AC-PROD-1; the request counter is AC-SEC-10)*
- **AC-QA-12:** Row deletion and debounce interleaving on the Settings page: with 3 newznab rows A, B, C saved, each with a distinct api_key, extra_score and custom_tag, deleting row B results in one group save whose stored rows, read through `getHosts` after a reload, are exactly A and C with each row's own values; editing row C's key and then deleting row A before the debounce fires ends with stored rows B and the edited C, and no key paired with a host it was not entered against. The same deletion case holds for torrentpotato with pass_key, name, seed_ratio, seed_time and extra_score. The assertion is taken after a bounded wait for network idle, not immediately after the click. The reads through `getHosts` use the Python helper under `tests/helpers/` named in AC-QA-10, and any starting state the API can no longer produce is written by the pre-start `config.ini` fixture. Proof: E2E. *(merges AC-PROD-3; the helper and fixture sentence was added after the planning cycle)*
- **AC-QA-13:** The wizard surfaces the server's refusal independently of its client check: with `assertNewznabHasNoCommas` neutralised in the page, submitting the Providers step against the real server with a comma in a kept row does not advance the step, shows the row and field from the server's response, and leaves the newznab lines of `config.ini` unchanged, `enabled` included. To make that hold, the wizard awaits the newznab group save and issues the step's other saves (including `newznab.enabled`) only after it succeeds, so a refused group leaves every newznab line unchanged; today the step's saves are issued together (`wizard.html:1337-1353`), which would let `newznab.enabled` land beside a refused group. Proof: E2E. *(the wizard re-run case moved to AC-PROD-4; the ordering rule was added after the planning cycle)*
- **AC-QA-16:** Each server guard is proven load-bearing: removing in turn the comma check, the column-set check, the per-column refusal and the in-memory rollback makes the named test from AC-QA-2, AC-QA-4, AC-SEC-3 and AC-DATA-1 respectively fail, with each mutation confirmed applied by `git diff`, the file restored byte-identical and `__pycache__` cleared; the results are recorded in the PR. Proof: mutation run.
- **AC-QA-17:** Removal: no test in `tests/` still stubs or asserts a successful per-column `settings.save` for a combine column; the expectations in `tests/e2e/wizard-newznab-pairing.spec.ts` (the `settings.save` route stub and the host, api_key and use length assertion), `tests/e2e/wizard-provider-saves.spec.ts` (the newznab host and api_key expected saves) and `tests/e2e/wizard-newznab-comma.spec.ts` (the `newznab.api_key=` save expectations) are replaced by assertions on the group save, and `grep -rnE "newznab\.(host|api_key|use)=|\['newznab', '(host|api_key|use)'" tests/` returns nothing. Proof: static check.
- **AC-QA-18:** No performance criterion applies: no baseline for settings-save latency exists in the repo and none was measured at planning, so this change carries no performance threshold, and the single-write count in AC-QA-6 is the only cost-related assertion.

### Simplicity (lens-simplicity; checked by the orchestrator against the diff)

- **AC-SIMP-1:** No new dependency: requirements files, `pyproject.toml`, `package.json` and `package-lock.json` have an empty diff against master. Proof: `git diff --stat`.
- **AC-SIMP-2:** No new configuration setting: no option dict is added to any provider's or core's registered options, and the five `combine` declarations (`newznab.py`, `torrentpotato.py`, `imdb.py`, `itunes.py`, `letterboxd.py`) are byte-identical to master. Proof: `git diff`.
- **AC-SIMP-3:** Provider files are untouched apart from the one writer security brought into scope: `newznab.py` and the automation `imdb.py`, `itunes.py` and `letterboxd.py` have an empty diff, and the diff of `torrentpotato.py` is confined to the body of `jackettSync` (its write of the group, per AC-SEC-9 and AC-DATA-9); group membership is derived from the existing `combine` declarations at runtime, and no added line in `settings.py` or `combinedField` contains a literal `newznab`, `torrentpotato` or `automation_urls`. Proof: `git diff` plus grep of added lines. *(amended at synthesis: the lens asked for an empty diff on `torrentpotato.py`, and its own finding yields to a security criterion)*
- **AC-SIMP-4:** Exactly one new API route is registered (one added `addApiView` call in the diff); it writes one section's one combine group per request and there is no general multi-section or arbitrary-option batch save. Proof: grep of `addApiView` in the diff, with the refusal of a non-combine option tested under AC-SEC-4.
- **AC-SIMP-5:** No new source module: `git diff --diff-filter=A master -- couchpotato/` lists no file; the server logic lives in `couchpotato/core/settings.py` and the client logic in the existing `scripts.html`, `field_types.html` and `wizard.html`. Proof: the diff command.
- **AC-SIMP-6:** `getParams` behaviour is unchanged for every existing route: `couchpotato/core/helpers/request.py` has an empty diff. Proof: `git diff` of `request.py`. *(amended after the planning cycle: the alternative "or every pre-existing test of `getParams` passes" was removed because no such test exists; a grep of `tests/` for `getParams` finds only a comment at `tests/e2e/wizard-newznab-comma.spec.ts:183`)*
- **AC-SIMP-7:** `combinedField` adds no client-side comma or encoded-comma validation of its own: no added line in `scripts.html` or `field_types.html` matches `/%2c/i` or tests a cell value for a comma, and the row and field shown to the user come from the server's refusal response. Proof: grep of added lines.
- **AC-SIMP-8:** `assertNewznabHasNoCommas` in `wizard.html` is retained, keeps refusing a literal comma, still runs before any save request of the step, and is not copied into any other file. Its `%2c` clause (`/,|%2c/i`, `wizard.html:1734`) is removed in the slice where the wizard starts writing through the group save (P5), and not before: no second decode applies on that path, so `%2C` is then three legitimate stored characters (AC-QA-3, AC-DATA-6), and the function's comment (`wizard.html:1730-1732`, which says the server URL-decodes saved values a second time) is corrected in the same slice. Any other edit to it is confined to what AC-A11Y-6 needs in order to mark and focus the offending input. The assertion in `tests/e2e/wizard-newznab-comma.spec.ts` that a refused step issues no save request remains present and passing. Proof: `git diff` of the function, grep for its name across the tree, and the E2E run. *(amended at synthesis: the lens asked for an unchanged body, which yields to the accessibility floor; amended after the planning cycle: "comma rule unchanged" contradicted AC-QA-3 and AC-DATA-6 once the wizard uses the JSON transport, so the encoded-comma clause goes and the literal-comma rule stays)*
- **AC-SIMP-9:** No repair or migration path: the diff adds no `addEvent` registration, startup hook or background job in `settings.py`, and no code that rewrites stored combine columns except in response to a group-save request or a Jackett sync. Proof: grep of added lines for `addEvent`, `fireEventAsync` and `app.load`.
- **AC-SIMP-10:** Non-test files changed are a subset of: `couchpotato/core/settings.py`, `couchpotato/core/media/_base/providers/torrent/torrentpotato.py` (subject to AC-SIMP-3), `couchpotato/__init__.py` (only the method and body-type refusal that AC-SEC-2 and AC-ARCH-6 need), `couchpotato/api.py` and `couchpotato/core/helpers/request.py` (subject to AC-ARCH-5 and AC-SIMP-6), `couchpotato/ui/templates/partials/settings/scripts.html`, `couchpotato/ui/templates/partials/settings/field_types.html`, `couchpotato/ui/templates/wizard.html`, `docs/reference/API.md`, `docs/technical-debt.md` and `specs/SEC-004-combined-settings-save.md`. Test support is outside this list: a Python helper under `tests/helpers/` (the `getHosts` read-back of AC-QA-10 and AC-QA-12) and the pre-start `config.ini` fixture are test files. Proof: `git diff --name-only` filtered against the list. *(the test-support sentence was added after the planning cycle)*
- **AC-SIMP-11:** At most one new file is added under `tests/e2e/`; the Settings-page and wizard behaviour is otherwise covered by extending the existing `settings.spec.ts` and wizard specs. The Python helper under `tests/helpers/` that reads a worker's `config.ini` back through `getHosts` does not count against this budget, and neither does extending the existing seeding (`tests/e2e/fixtures.ts`, `scripts/seed_e2e_data.py`) to write a starting `config.ini` before the worker's server starts. This is a cumulative budget across the delivery slices: P3 spends the one new file. Proof: `git diff --diff-filter=A -- tests/e2e`. *(the helper, fixture and budget sentences were added after the planning cycle)*
- **AC-SIMP-12:** Removal list for this lens: nothing in the simplicity area is deleted; the wizard's client-only comma check stops being the sole guard by demotion, not deletion, because the check stays (AC-SIMP-8) and the server refusal now exists (AC-QA-13). Proof: covered by AC-SIMP-8 and AC-QA-13.

### Product (lens-product)

- **AC-PROD-4:** The wizard sends all five newznab columns for every row it writes: a row loaded from the stored indexers keeps its stored `use`, `extra_score` and `custom_tag`, and a row added in the wizard gets the documented defaults (`use` of `1`, `extra_score` of `0`, `custom_tag` empty). Loaded rows are sent unfiltered and untrimmed, except as AC-DATA-13 already specifies for the page (cells of a group the user edits are stored trimmed). Re-running the wizard over an install whose stored indexers have non-default extra_score or custom_tag and include a row with `use` of `0`, changing nothing and finishing, leaves every newznab group column byte-identical, and that row's `use` is still `0`; removing the middle of three loaded rows leaves the other two with their own host, key, use, extra_score and custom_tag, read back through `getHosts`; no saved indexer ever carries another indexer's key, use, extra_score or custom_tag. Proof: E2E over a pre-seeded `config.ini`, read back through `getHosts`. *(merges the second case of AC-QA-13; encodes owner decision D3; amended after the planning cycle: `use` added, because today's wizard forces `use` to `1` for every row (`wizard.html:1348`), and the proof changed from an integration test to E2E because the behaviour is in wizard JavaScript, which a Python integration test never runs. The byte-identical case uses a fixture holding only stored indexers; an install that also holds keyless default rows loses those rows on the wizard's save, per AC-DESIGN-12)*
- **AC-PROD-9:** Measurement: this change adds no telemetry, event or newly collected field, deliberately, because the software is self-hosted and single-operator with no analytics sink; the success signal is the property proven by the pairing criteria (AC-SEC-6, AC-SEC-9, AC-QA-10, AC-QA-12), and review fails this criterion if the diff introduces any logging or telemetry of setting values in order to measure it. Proof: review of the diff for new log or telemetry calls.
- **AC-PROD-10:** Removal of the user-facing account of the problem: the "Newznab positional lists" entry in `docs/technical-debt.md` no longer says the Settings page accepts a comma (item a) or that columns are saved by separate requests (item d), and its "Direction for the durable fix" paragraph no longer proposes work this change has done; items b (the `getHosts` and `isEnabled` guards, with the condition for revisiting them), c (the second decode for non-combined settings) and e (already-misaligned installs) are still listed as open, and the entry records as open the four gaps this spec declined: (1) `newznab.custom_categories` paired by position outside the group; (2) automation readers dropping empty cells before pairing; (3) a failed per-column save of a non-combine option staying in memory until the next save; and (4) a save built from a stale read (a second tab, the wizard, or a Jackett sync landing between a page's read and its group save) overwrites the newer rows wholesale; it cannot mispair, because each group save comes from one snapshot. Proof: docs read at review. *(merges the technical-debt clause of AC-OPS-9; the fourth gap was added after the planning cycle to carry owner decision D5, which until then was recorded only in the withdrawn AC-DATA-4)*

### Design (lens-design)

- **AC-DESIGN-1:** No new component, colour token or CSS file is introduced for the refused-save state: the inline row error reuses the validation-box classes from `partials/settings/profiles.html` (`px-3 py-2 rounded-lg bg-cp-danger/10 border border-cp-danger/20` with `text-cp-danger` text), the saving and saved signal reuses the existing `header.html` auto-save indicator, the diff contains no raw hex colour and no Tailwind `red-*` class in the touched templates, and the conformance step of `make verify` passes.
- **AC-DESIGN-2:** Settings page, refused group save: with Newznab showing three rows, a comma typed into row 2's host cell produces, after the save debounce, a danger border on that input using a cp-danger token and a single error message inside the same combined field, directly below row 2 and before row 3, with no other row marked. *(persistence is AC-A11Y-2)*
- **AC-DESIGN-3:** After a refused group save the header auto-save indicator never shows "Saved" for that save; after a successful group save it shows "Saved" exactly once per group save, not once per column; while the group request is in flight it shows "Saving…".
- **AC-DESIGN-4:** Recovery: deleting the comma from the refused cell triggers a group save, and when it succeeds the inline message and the danger border are gone and the header shows "Saved"; switching to another settings tab and back while a refusal is outstanding keeps the row marked as refused, and the refused value is not shown as if it were saved.
- **AC-DESIGN-5:** The copy for a server refusal is the same template on the Settings page and in the wizard. The client composes the text from the structured refusal of AC-ARCH-11(iii) (row index, column name, reason code), using each surface's own row noun and field label: it names the row by its 1-based on-screen position (top row is 1; "Row 2" on the Settings page, "Indexer 2" in the wizard), names the field by the label that surface shows in its column header or placeholder ("host" on the Settings page, "URL" in the wizard), and states the rule and the fix, for example "Row 2: the host cannot contain a comma. Remove it to save." and "Indexer 2: the URL cannot contain a comma. Remove it to save."; the server's `error` string is a fallback only, shown when the structured list is absent or names a reason code the client does not know; the message never contains the submitted value or any part of it, an underscore-joined option key (`api_key`, `pass_key`, `automation_urls_use`), a `section.name` pair, the word "Error:" or an HTTP status, checked by a regex against the rendered text for each of the five combine groups. *(the wizard's client-detected message keeps its existing wording under AC-SIMP-8; amended after the planning cycle: "the same sentence" became "the same template", because the server knows neither surface's row noun nor its field label, nor the on-screen row number when blank rows are filtered out)*
- **AC-DESIGN-6:** Wizard: a comma in a Newznab URL or API key produces exactly one visible error message for that attempt; the page never shows a client message and a server message together, nor a "Failed to save: " prefix stacked on another "Failed to save", the step does not advance, and the entered rows stay as typed.
- **AC-DESIGN-7:** Removal: for any option belonging to a combine group, the Settings page never shows the per-column toast `Could not save <name>: <detail>` from `scripts.html`; the inline row message from AC-DESIGN-2 is the only visible place the refusal appears, verified by triggering a comma refusal in Newznab and confirming the toast region stays empty. *(merges the Settings half of AC-A11Y-14; how the refusal is announced is AC-A11Y-3 and AC-A11Y-4)*
- **AC-DESIGN-8:** Removal: in the Settings page combined field the per-row remove control is not rendered when only one row remains, matching the wizard's `x-show="formData.newznab.entries.length > 1"`; every remove control that is rendered removes its row and triggers one group save, and no rendered remove control is a no-op. *(merges AC-A11Y-8)*
- **AC-DESIGN-9:** Empty state: a combine group with no stored values renders exactly one blank row with placeholders visible, and "+ Add" appends one blank row and sends no save request by itself. *(the zero-requests-on-load clause is AC-DATA-11)*
- **AC-DESIGN-10:** Misaligned stored config, as defined under Definitions (pairing columns of unequal length, for example `host` with 3 entries and `api_key` with 2): opening the tab shows one row per position up to the longest pairing column, with missing cells as empty inputs, and a persistent visible notice inside that group saying its rows do not line up and each should be checked; the notice is absent for an aligned group, for a group whose stored cells are all empty (the shipped torrentpotato defaults), and for a group whose only length difference is surplus default cells in a non-credential column (the wizard-configured shape: three rows of `host`, `api_key` and `use` with `extra_score` and `custom_tag` at their six defaults shows three rows and no notice); it clears once a save of that group succeeds. *(encodes decision D2; zero saves on load is AC-DATA-11; narrowed after the planning cycle to the Definitions, because the first wording would have shown the notice to most wizard-configured installs)*
- **AC-DESIGN-12:** Wizard re-entry, using the Definitions: the Providers step shows one row per stored indexer (non-empty `host` and non-empty `api_key`), in stored order, with its URL filled in and its API key shown only in the existing `type=password` input (`wizard.html:196`; never rendered as visible text and never placed in the page source outside that field's value); if there are no stored indexers it shows one blank row, which is what a fresh install with its six keyless default hosts gets. Newznab is shown enabled only if `enabled` is on AND at least one stored indexer exists, so a fresh install (where `enabled` defaults to on, `newznab.py:293`) is not presented as already configured. Keyless default rows are not shown and are not kept when the wizard saves the group. A stored row with a key and no URL (a hostless row) is either kept (loaded and sent back as stored) or refused with a message naming the row; it is never dropped silently, because it carries a credential. If the stored group is misaligned (Definitions) the wizard shows the same misaligned-group notice as the Settings page (AC-DESIGN-10) and writes nothing until the user continues past the Providers step. No copy claims the stored indexers will be replaced. Proof: E2E starting from a config with two stored indexers, one from a fresh install's defaults, one from a config with a hostless row, and one from a misaligned config. *(encodes owner decision D3; amended after the planning cycle: the stored-indexer definition, the enabled rule, the keyless and hostless rows, and "until the user edits or continues" replaced, because an edit in the wizard writes nothing)*

### Accessibility (lens-accessibility)

- **AC-A11Y-1:** When the server refuses a group save on the Settings page, every offending cell's input has `aria-invalid="true"` and an `aria-describedby` that resolves to a visible error element naming the row number and the field with the words the input's accessible name uses (for example "api key for row 2: remove the comma"), and no other input in the group is marked invalid. The marks come from the response, which lists every offending cell even though the server logs only one line per refused save (AC-OPS-1); a refusal with two offending cells marks both. Proof: E2E asserting the attributes, the IDREF resolving and the text, for a real-server refusal and for a route-intercepted response in the server's refusal shape. *(the client-detected case is dropped on the Settings page under AC-SIMP-7; the every-offending-cell sentence was added after the planning cycle)*
- **AC-A11Y-2:** The inline refusal message on the Settings page stays until the offending cell is changed and the group then saves successfully, and is never removed by a timer: 10 seconds after the refusal, with no further input, the error element is still visible and `aria-invalid` is still true. Proof: E2E with a bounded wait of at least 10 s. *(merges the persistence clauses of AC-DESIGN-2 and AC-A11Y-14)*
- **AC-A11Y-3:** Each refusal is announced exactly once: with a MutationObserver counting every text change in the settings live regions (polite, assertive and the header `role=status`) armed before the first keystroke, typing one comma into a cell and then 5 more characters, letting the debounce fire between them, puts the refusal text into the live regions exactly once and never announces "Saved"; clearing the comma and adding it again is a new refusal and is announced again, exactly once. Proof: E2E asserting after a bounded wait longer than the debounce.
- **AC-A11Y-4:** The refusal is announced through one channel only: over one refusal, the nodes matching `[aria-live]`, `[role=alert]` and `[role=status]` change to the refusal text a total of 1 time, not 2, so the inline error element carries no live role of its own if the same text is also sent to a live region. Proof: E2E mutation count.
- **AC-A11Y-5:** A refused autosave on the Settings page does not move focus: the element focused immediately before the refused save is still `document.activeElement` after the refusal is rendered, whether that was the comma cell, a different cell or the `use` switch of another row. Proof: E2E.
- **AC-A11Y-6:** In the wizard, a refused Newznab step (client-detected or server-returned) moves focus to the first offending input and leaves it there, not on body and not on Continue; that input has `aria-invalid="true"` and an `aria-describedby` error naming "Indexer N" and the field (URL or API key), the error stays on screen after the toast's dwell time has passed, and the step does not advance. The wizard maps the server's row index back to the on-screen row before it names, marks or focuses anything (or sends its rows unfiltered, so the two numbers cannot differ): today the wizard drops a row with no URL before saving (`wizard.html:1343-1345`), so the server's index can be lower than the on-screen number. Proof: E2E in `wizard-newznab-comma.spec.ts`, including a route-intercepted server refusal, and including a case with a blank row above the offending row, where the on-screen number differs from the server's row index and the error, the mark and the focus all land on the on-screen row. *(merges the wizard half of AC-A11Y-14; the row-mapping rule and its case were added after the planning cycle)*
- **AC-A11Y-7:** Removing a row from any Settings combined field never leaves focus on `body` or on a removed node, including removing the last row and removing a row so that one is left: focus goes to the Remove button now at that index, else the previous row's Remove button, else the field's Add button, the same order as the wizard's `removeIndexer`, and the removal is announced once ("Row N removed"). Proof: E2E driving Remove by keyboard on the first, middle and last rows of a 3-row Newznab field.
- **AC-A11Y-9:** An invalid cell is not marked by colour alone: the text message from AC-A11Y-1 is present whenever the invalid border or tint is present, and while the invalid input has keyboard focus its focus indicator measures at least 3:1 against the adjacent surface (measured from the parent surface for an offset outline) in both the dark and light themes. Proof: E2E contrast measurement looped over both themes.
- **AC-A11Y-10:** Inline refusal text, and the misaligned-group notice of AC-DESIGN-10, measure at least 4.5:1 against their rendered background in both the dark and light themes, on the Settings page and in the wizard. Proof: E2E computed-colour contrast measurement. *(the notice was added at synthesis under decision D2)*
- **AC-A11Y-11:** axe reports zero violations on the Settings Searchers tab with a Newznab combined field in the refused state, and on the wizard Providers step in the refused state, each in both themes; the test fails, not skips, if no element with `aria-invalid="true"` is present. Proof: axe-core in E2E with a hard precondition assertion.
- **AC-A11Y-12:** At a 320 CSS px viewport and at 200% zoom on a 1280 px viewport, in both themes, the refused Newznab field on the Settings page and the refused wizard Providers step show the full error text with no horizontal page scroll (`document.scrollingElement.scrollWidth <= clientWidth`) and the error element's bounding box inside the viewport. Proof: mobile-project E2E plus a zoom E2E. *(merges AC-DESIGN-11)*
- **AC-A11Y-13:** Every control this change adds or re-renders in a combined field has a non-empty accessible name that includes its visible text; the `use` switch, each cell input, Remove and Add keep their current names ("Enable row N", "FIELD for row N", "Remove row N", "Add row"), so `accessibility.a11y.spec.ts` and `toggle-switch-contrast.a11y.spec.ts` pass with no edit to their locators. Proof: those specs unchanged plus an accessible-name sweep over the combined field.

### Data (lens-data)

- **AC-DATA-1:** A group save whose file write fails leaves no residue in memory or on disk: with `os.replace` patched to raise during a group save of newznab, the request returns `success: false`, the sha256 of `config.ini` is unchanged, `Settings.get` returns the pre-save value for every column, and after a subsequent unrelated successful save (for example `core.port` or `newznab.enabled`) every newznab group column on disk still equals its pre-failure value. Proof: unit test against the real Settings class and a temporary `config.ini`, fault injected at `os.replace`. *(merges AC-QA-5 and the proofs of AC-ARCH-3 and AC-OPS-3; measured on master for the single-column path: the failed value lands on disk at the next unrelated save)*
- **AC-DATA-2:** Validation precedes every mutation: a group save refused for any reason (a comma in a cell, a row missing a column, an unknown column, a column that is not writable) leaves both the sha256 of `config.ini` and the in-memory value of every column unchanged, each refusal driven with the offending cell in the last column of the last row so that an implementation which sets columns as it validates fails. Proof: unit test, one case per refusal reason.
- **AC-DATA-3:** All parser writes for one group and its file write happen under one continuous hold of the lock every config file write takes (`_PASSWORD_SAVE_LOCK` today): with a second writer (an `Env.setting` write to the same section, a `settings.save` of a non-combine option, and a second group save) released by a barrier when the first group's first column has been set, the file on disk afterwards has every group column from exactly one submitted group, never a mix, no intermediate `os.replace` writes a mixed group, and the unrelated option's value is never lost. Proof: unit test with a threading barrier and an `os.replace` spy recording each written file. *(merges AC-QA-8)*
- **AC-DATA-4:** *(withdrawn by owner decision D5, 2026-11-14)* No stale-save protection is built and no freshness token exists. The exposure is narrower than master's: newer rows can be lost but not mispaired, because each group save comes from one snapshot. It is recorded in `docs/technical-debt.md` as the fourth declined gap of AC-PROD-10: a save built from a stale read (a second tab, the wizard, or a Jackett sync landing between a page's read and its group save) overwrites the newer rows wholesale. The wizard is now a stale reader with a long gap between its read and its save. The number is kept so later references do not shift.
- **AC-DATA-5:** The group payload is keyed by row and the server pairs cells exactly as sent: two rows differing only in host and key are stored with each host at the position of its own key, and a 12-row payload stores rows 10 and 11 at positions 10 and 11 (numeric order, not lexical). Proof: unit test through the real HTTP route. *(the missing-column and extra-column cases are AC-QA-4; the index-gap case is replaced by the bracket-key refusal in AC-ARCH-6)*
- **AC-DATA-6:** Stored cells survive a later edit elsewhere: after cells `a%2Cb` and `a%252Cb` are saved through the Settings page, and a key containing `%`, `+`, `&` and `=` is saved through the wizard, reloading the page and editing a different row leaves those cells byte-identical in `config.ini` and every column's cell count unchanged. Proof: E2E. *(merges AC-PROD-7; the server round-trip is AC-QA-3)*
- **AC-DATA-9:** `jackettSync` makes exactly one write of `config.ini` per successful sync (one `os.replace`, one `Settings.save` call), with its read of the existing hosts and its write inside one lock hold; a Jackett indexer title containing a comma adds no position to any column, and with `replace=True` and the write failing, the sha256 of `config.ini` is unchanged, so no new host is left paired with an old pass_key or name. Proof: unit test with stubbed `getJackettIndexers` and an `os.replace` spy and fault. *(merges AC-ARCH-9 and the single-write clause of AC-OPS-7)*
- **AC-DATA-10:** Removal: no per-column writer of a group column remains in the tree; `torrentpotato.py` contains no `self.conf` call that passes `value=` for use, host, pass_key, name, seed_ratio, seed_time or extra_score, and a test greps `couchpotato/` for `Env.setting` and `conf` writes of combine option names and finds only the group writer. The grep is section-aware: a hit counts only when the file's section owns a combine group containing that option name. A name-only grep fails on a legitimate writer, `couchpotato/core/downloaders/rtorrent_.py:295` (`self.conf('host', value = ...)`), which writes an option called `host` (declared at `rtorrent_.py:612`) in a section with no `combine` declaration. Proof: grep assertion in a unit test, which includes that rtorrent line as a must-not-match case. *(merges the grep clauses of AC-QA-15, AC-ARCH-4 and AC-OPS-7; the `settings.save` refusal is AC-SEC-3; the section-aware rule was added after the planning cycle)*
- **AC-DATA-11:** Removal: `combinedField` no longer re-saves padded columns and nothing is written on load; starting the new version on aligned and on misaligned `config.ini` fixtures, opening Settings, expanding all five groups, waiting past the debounce window and navigating away issues zero writes (no `settings.save` and no group-save request, observed by a network listener armed before page load, and the sha256 of `config.ini` unchanged), and editing one cell then issues exactly one group-save request for that group. Proof: E2E with network interception and a file hash before and after. *(merges AC-OPS-6, part 1 of AC-QA-9 and the zero-request clauses of AC-DESIGN-9 and AC-DESIGN-10)*
- **AC-DATA-12:** A stored misaligned group is never rewritten by a save outside it: with newznab stored as `host` of `a,b,c` and `api_key` of `k1,k2`, opening the page and saving an unrelated setting in another section leaves both lines byte-identical. Proof: E2E plus unit test. *(a save of the group itself is AC-QA-10)*
- **AC-DATA-13:** Aligned configurations round-trip byte for byte: for one aligned fixture per group with no whitespace around separators, including hostile shapes (empty cells, a trailing empty row, a unicode IDN host, a literal `%` in a cell, and the shipped itunes default of a URL followed by a comma with `use` of a single comma), a group save of exactly the rows the page derives leaves the whole file's sha256 identical, and a save that changes one cell changes exactly one line of `config.ini`. A fixture with a space after a separator is included and pins that its lines are untouched until the user edits that group, when the cells are stored trimmed. Proof: unit test hashing the whole file. *(merges part 2 of AC-QA-9; the whitespace scoping answers the lens's byte-for-byte finding)*
- **AC-DATA-15:** Rollback is a revert: a `config.ini` written by the group save contains exactly the same sections and option names as before the save (no version marker, token or new key persisted), is byte-identical for aligned rows to what master's per-column saves produce from the same rows in each of the five sections, and master's `getHosts` and automation readers read it to the same rows in the same order. Proof: unit test comparing option sets and bytes against a fixture produced by master's code path. *(merges AC-OPS-5)*
- **AC-DATA-16:** The page cannot lose a later edit to an earlier in-flight save: with group-save responses delayed, two edits to the same group in quick succession end with `config.ini` holding the second edit, and the page never has more than one group save in flight per group. Proof: E2E with a route delay.
- **AC-DATA-17:** The wizard writes newznab only as one group: a wizard completion with Newznab disabled leaves every newznab group column byte-identical, and with it enabled and at least one row holding a URL exactly one group-save request is sent for newznab, after which `use`, `api_key`, `extra_score` and `custom_tag` each have the same cell count as `host`. Proof: E2E with network interception and inspection of `config.ini`. *(amended after the planning cycle: "at least one row holding a URL" added, because AC-DATA-20 sends no group save when there is none)*
- **AC-DATA-18:** The wizard reads the stored Newznab rows through the same settings API read the Settings page uses (`partials/settings/scripts.html:274`, the `settings` route), never from values embedded in the wizard template at render time. That read returns combine-group credentials unmasked: only `password`-typed options are masked (`couchpotato/core/settings.py:337-338`), and the group's columns are not `password`-typed (`newznab.py:326-331`: `api_key` is declared `type: 'combined'`). This change adds NO masking of combine columns on read, because the Settings page would then save a mask over real keys. The wizard holds the key only in a `type=password` input; an untouched loaded row is saved with its stored key, proven by reading `config.ini`, not by the request body alone. Loading rows issues no save. A wizard completed with a loaded row's key left untouched and its URL edited keeps that key against the edited URL. Proof: E2E with network interception plus inspection of `config.ini`. *(added for owner decision D3; no lens wrote it, so it is a candidate spec gap for the review cycle to test hard; amended after the planning cycle: the first wording assumed the read masks these keys, which it does not)*
- **AC-DATA-19:** If the wizard's read of the stored Newznab rows has not completed successfully, the Providers step writes neither `newznab.enabled` nor the newznab group, shows a visible error saying the stored indexers could not be loaded, and does not advance; a failed or pending read is never treated as an install with no stored indexers. Proof: E2E with the settings read stubbed to fail, and stubbed to be delayed past the step, each asserting that the sha256 of `config.ini` is unchanged. *(added after the planning cycle from the consistency review / delivery plan; no lens wrote it)*
- **AC-DATA-20:** Newznab enabled with zero kept rows is defined: when no row has a URL, the wizard sends no group save and leaves the stored group untouched. It does not send an empty row list, which the server refuses (AC-QA-4), and it never wipes stored indexers by sending nothing but blanks. Proof: E2E over a `config.ini` pre-seeded with stored indexers, with network interception showing no group-save request and inspection of `config.ini` showing every newznab group column byte-identical. *(added after the planning cycle from the consistency review / delivery plan; no lens wrote it)*

### Architecture (lens-architecture)

- **AC-ARCH-1:** The map of combine groups (section to ordered column list) comes from one Settings method that reads the `combine` declarations already registered through the `settings.options` event; no production file hard-codes the list of combine sections or their columns a second time. Proof: a unit test registers a synthetic section `zz_test` whose option declares `type: 'combined'` with a `combine` list of use, host and key, and with no production code edited the group save accepts a valid `zz_test` row set and per-column `settings.save` refuses `zz_test.host`; plus a grep for section-name literals. *(merges the synthetic-section clause of AC-QA-7)*
- **AC-ARCH-2:** The per-column refusal in `settings.save` and the validation in the group save both ask the single group-membership method of AC-ARCH-1 whether an option belongs to a combine group, matching the name after `optionxform`; grep shows exactly these two call sites and no other `combine` membership test in `couchpotato/core`. Proof: code read plus grep.
- **AC-ARCH-3:** Writing a combine group is one method on Settings that validates the whole group, sets every column, calls `self.save()` once and restores the in-memory parser if validation or the write fails; the API view for the new route and `jackettSync` are thin callers of that method and repeat none of its validation. Proof: code read, with the failure behaviour proven under AC-DATA-1 and the locking under AC-DATA-3.
- **AC-ARCH-5:** The new route is registered with `addApiView` in `Settings.__init__`, next to `settings.save`, with a `docs` entry; the change adds no branch naming the route to `callApiHandler` in `api.py` or to `getParams` and `dictToList` in `request.py`, and any change to the catch-all in `couchpotato/__init__.py` is limited to refusing the wrong method or body type for a declared set of routes (AC-SEC-2, AC-ARCH-6), in the style of `ORIGIN_CHECKED_API_ROUTES`. Proof: diff read. *(amended at synthesis: the lens asked for no catch-all change, which yields to AC-SEC-2)*
- **AC-ARCH-6:** Rows reach the server as a JSON array of row objects in an `application/json` POST body, the one shape `getParams` passes through without decoding; `rows` delivered any other way (a string, a JSON text in a form field, bracket-keyed form fields such as `rows[0][host]`, or query parameters) is refused with `config.ini` unchanged. Proof: integration tests posting each refused shape. *(the byte-for-byte round-trip is AC-QA-3; replaces the index-gap cases of AC-QA-4 and AC-DATA-5; decision D4)*
- **AC-ARCH-8:** On the Settings page a combine group is one pending save keyed by the group, not one per column, and `flushPendingSaves()` also flushes pending group saves, so nothing that awaits it (such as the OAuth device-code flow) can run ahead of an unsaved group. Proof: Playwright request intercept. *(the request counts are AC-DATA-11 and AC-SEC-10)*
- **AC-ARCH-10:** No new dependency edge: `couchpotato/core/settings.py` imports nothing from `couchpotato.core.media`, `couchpotato.ui` or any provider module, and provider modules declare nothing new beyond their existing `combine` lists. Proof: import-graph grep of the diff.
- **AC-ARCH-11:** Contracts the first slice (P1) freezes, so that later slices can build in parallel against them: (i) one Settings method derives section to ordered columns from the registered options, and one membership test applies the same option-name folding the config parser uses (`optionxform`), the methods AC-ARCH-1 and AC-ARCH-2 name; (ii) the group writer accepts either rows or a builder callable that runs under the lock and returns rows, so a caller can read the existing rows and write in one continuous lock hold (needed by AC-DATA-9) without importing the module-private lock (`_PASSWORD_SAVE_LOCK`, `couchpotato/core/settings.py:28`); (iii) a refusal is returned as a structured list of `{row, column, reason}` (the 0-based row as sent, the column name, a reason code) alongside a human `error` string, lists every offending cell, and never contains a cell value in either part; (iv) the transport guard lives in the API dispatch, within the bound AC-ARCH-5 sets: the route is refused unless the request is a POST with an `application/json` body and carries no query parameters other than the API's existing cache-buster (`t`, which `couchpotato/api.py:63` removes). Proof: unit tests on each of the four. *(added after the planning cycle from the consistency review / delivery plan; no lens wrote it)*

### Operability (lens-operability)

- **AC-OPS-1:** When the server refuses a group save (a comma in a cell, rows of unequal width, an unknown or missing column), including one reached through `jackettSync`, it emits exactly one log line per refused save at WARNING or above, never DEBUG, however many cells offend: the line names the section, the first offending row index (the 0-based row as sent, the same number AC-ARCH-11(iii) returns), that cell's column name and reason class, and the count of offences, and never a value. The response still lists every offending cell. Proof: integration test that drives the real endpoint with a canary host and a canary key in two offending cells, captures the real log output, and asserts exactly one line is present at WARNING with a count of 2, and that neither canary appears anywhere in the capture. *(merges the log clause of AC-OPS-7; amended after the planning cycle: one line per save with a count, where the first wording left open one line per offending cell, and the row is the index as sent because the server cannot know the on-screen number)*
- **AC-OPS-2:** A per-column POST to `settings.save` for any option in a combine group (for example `section=newznab`, `name=host`) returns `success: false` with an error text that names the field, names the group-save route to use instead and tells the user to reload the page, not the generic "Failed returning results", and logs one WARNING naming `section.option`; this is what a browser tab loaded before the upgrade sees, and its existing `saveSingle` toast shows the text as written. Proof: integration test on the real endpoint plus a test that the old `saveSingle` toast path renders the server's error text. *(merges AC-PROD-8; the unchanged-file clause is AC-SEC-3)*
- **AC-OPS-3:** If the atomic config write raises during a group save, the view catches the exception, logs once, and returns failure: exactly one ERROR log line names the section and the exception type and contains no cell values, and the exception does not propagate to the API handler, so no second line and no traceback are logged for it. Proof: integration test with a forced write failure and log capture, asserting one line for the failure. *(the unchanged file and the later-save check are AC-DATA-1; amended after the planning cycle to settle the conflict with AC-SEC-7, which had required the API handler's traceback line)*
- **AC-OPS-4:** Cross-version safety in the rollback direction: if the group-save route returns any non-success, including the "API call doesn't exist" body from `callApiHandler` (a tab loaded on the new version talking to a rolled-back server) or an HTTP error, the Settings page and the setup wizard each show a visible error, keep the rows dirty, and never announce "Saved" or advance the wizard step. Proof: E2E with the route stubbed to return that body and to return HTTP 500.
- **AC-OPS-8:** A successful group save logs one INFO line naming the section and the row count, with no cell values. Proof: integration test reading captured log output at INFO.
- **AC-OPS-9:** `docs/reference/API.md` documents the group-save route, its request shape, its refusal response shape (row and field, no values), whether a group save fires any `setting.save` event, and that `settings.save` refuses combine options; the "Newznab positional lists" entry in `docs/technical-debt.md` names the log line of AC-OPS-1 as the place an operator finds a refused save. Proof: doc review against the built change. *(the rest of the technical-debt rewrite is AC-PROD-10; merges the docs clauses of AC-PROD-8 and AC-ARCH-5)*

### Vetoed at planning

Dropped under the simplicity veto (not traceable to the outcomes above, and
not a security, data-loss or accessibility-floor item):

| Dropped | Raised by | Reason |
|---|---|---|
| AC-DATA-7 (bring `newznab.custom_categories` into the group) | data, also product and architecture findings | Needs a `combine` declaration change and a new column in the row editor, against AC-SIMP-2 and AC-SIMP-3. The column carries no credential, and it shifts on a row delete today, so this change does not make it worse. Recorded as open debt by AC-PROD-10. Decision D6. |
| AC-DATA-8 and AC-QA-14 (refuse empty cells in automation rows, or change the readers) | data, QA | The shift happens when the automation readers drop empty cells, and readers are out of scope. A write-side rule would need the section names hard-coded, against AC-ARCH-1. No credential is involved. Recorded as open debt by AC-PROD-10. Decision D6. |
| AC-DATA-14 (page and server agree on a stored group's row count) | data | For an empty group the page must render one blank row (AC-DESIGN-9) while the reader sees none, so the criterion cannot hold as written. What it protects, that the shipped defaults stay editable and nothing is padded onto disk, is covered by AC-QA-10 and AC-DATA-11. |
| Client-side comma validation in the Settings page | simplicity finding | A second rule set that can drift from the server's. AC-SIMP-7 forbids it, and the client-detected clause of AC-A11Y-1 was removed to match. |
| The wizard loading and merging stored indexer rows | simplicity finding, design option A | **Veto overridden by the owner (D3, 2026-11-14):** the wizard loads the stored rows (AC-PROD-4, AC-DESIGN-12, AC-DATA-18). Simplicity's objection stands on the record: it enlarges the change to the first-run screen. |
| Refusing an encoded comma (`%2C`) on the Settings page (part of AC-PROD-1) | product | Contradicts "values are taken as sent": through the JSON transport `%2C` is three literal characters and is stored as typed (AC-QA-3). Amended after the planning cycle: the wizard's client check keeps refusing a literal comma, and its `%2c` clause is removed in the slice where the wizard starts writing through the group save (P5), because no second decode applies on that path; until that slice the clause stays, since the wizard still saves per column through the decoding path (AC-SIMP-8). |
| One shared wording for the wizard's client-detected message (part of AC-DESIGN-5 and AC-DESIGN-6) | design | Would rewrite the client check that AC-SIMP-8 retains. The shared template applies to the server refusal on both surfaces (AC-DESIGN-5). |
| A WARNING when a group with unequal column lengths is read | operability finding (optional) | The spec puts detecting existing misalignment out of scope. The user-visible notice of AC-DESIGN-10 covers the detectable case. |
| Rendering the automation `use` column as a toggle | design finding | Not needed for any outcome. Recorded as debt, not built here. |
| Deleting `assertNewznabHasNoCommas` (the spec's own removal row) | simplicity | Kept and demoted: it is the only thing that stops a refused wizard step from saving its other settings (AC-SIMP-8, AC-SIMP-12). |

Simplicity vetoes that did not stand:

| Veto | Overridden by | Reason |
|---|---|---|
| Exclude `jackettSync` from scope and keep `torrentpotato.py` untouched | security (AC-SEC-9), data (AC-DATA-9) | A comma in a Jackett URL, or a failure between its seven separate writes, leaves a pass_key stored against a host it was not entered for. The simplicity finding itself said a security criterion overrides it. |
| `assertNewznabHasNoCommas` body unchanged | accessibility floor (AC-A11Y-6) | Marking and focusing the offending input may need the check to report which input failed. |
| Run product and operability at planning only | not applied by this synthesis | A process recommendation for the review cycle, not a criterion. Three product and six operability criteria survive and still need a verifier at review. |

Criteria merged into another (the id is retired; the surviving criterion carries a note):

| Retired | Now covered by |
|---|---|
| AC-QA-5 | AC-DATA-1 |
| AC-QA-8 | AC-DATA-3 |
| AC-QA-9 | AC-DATA-11, AC-DATA-13 |
| AC-QA-15 | AC-SEC-9, AC-DATA-10 |
| AC-PROD-1, AC-PROD-2 | AC-QA-2, AC-QA-11 |
| AC-PROD-3 | AC-QA-12 |
| AC-PROD-5 | AC-SEC-9 |
| AC-PROD-6 | AC-QA-10, AC-DESIGN-10 |
| AC-PROD-7 | AC-QA-3, AC-DATA-6 |
| AC-PROD-8 | AC-OPS-2, AC-OPS-9 |
| AC-DESIGN-11 | AC-A11Y-12 |
| AC-A11Y-8 | AC-DESIGN-8 |
| AC-A11Y-14 | AC-DESIGN-7, AC-A11Y-2, AC-A11Y-6 |
| AC-ARCH-4, AC-ARCH-9 | AC-SEC-9, AC-DATA-9, AC-DATA-10 |
| AC-ARCH-7 | AC-SEC-4 |
| AC-OPS-5 | AC-DATA-15 |
| AC-OPS-6 | AC-DATA-11 |
| AC-OPS-7 | AC-SEC-9, AC-DATA-9, AC-DATA-10, AC-OPS-1 |

---

## Delivery slices

*(added after the planning cycle from the delivery plan; orchestrator,
2026-11-14, under the owner's standing authority for engineering calls; no
lens wrote it)*

**Rule.** Every merge to `master` publishes a beta that can be promoted, so no
slice may leave `master` worse than it was before the slice. The per-column
save keeps working until every first-party writer has moved; refusing it is
the last slice; docs never run ahead of `master`.

| Slice | Goal | Depends on | ACs closed | Hazard if promoted alone, and how the slice avoids it |
|---|---|---|---|---|
| P1 | Server: a validated, all-or-nothing group write on `Settings`, plus one JSON-only POST route. Nothing calls it yet. | none | AC-SEC-1, -4, -5, -6, -7, -11, -12; AC-QA-1, -2, -3, -4, -6; AC-DATA-1, -2, -3, -5, -13, -15; AC-ARCH-3 (second caller checked in P2), -5, -6, -11; AC-OPS-1 (Jackett clause in P2), -3, -8 | A failed write left in memory and persisted by the next unrelated save. Avoided by snapshot and restore of the columns under the lock, proven with fault injection at the file replace (AC-DATA-1). |
| P2 | Jackett sync writes its seven columns through the P1 writer in one lock hold and one file write. Indexers are fetched BEFORE the lock is taken. The wizard's sync URL and the E2E stubs are corrected here (Problem, fact 4). | P1 | AC-SEC-9, AC-DATA-9, AC-DATA-10 | Two. A network fetch made while the lock is held would stall every other settings write for as long as Jackett takes to answer; avoided by fetching first and passing the P1 writer a builder that only reads and merges under the lock (AC-ARCH-11(ii)). And correcting the wizard's URL makes the sync reachable from the first-run screen for the first time; avoided because the correction lands in the same slice as the validated write and never earlier. |
| P3 | Settings page: `combinedField` saves one group per request, writes nothing on load, shows a refusal inline, and shows the misaligned notice per the Definitions. Per-group state (rows, refusal, in-flight and queued saves) is held at panel level, so unsaved rows and a refusal survive the field being rebuilt on a tab change. | P1 | AC-QA-10, -11, -12; AC-DATA-11, -12 (unit half in P1), -16; AC-ARCH-8; AC-DESIGN-2, -3, -4, -7, -9, -10; AC-A11Y-1, -2, -3, -4, -5, -9, -13; AC-SIMP-7; and the Settings halves of AC-DESIGN-5, AC-DATA-6, AC-A11Y-10, -11, -12, AC-SEC-2, AC-SEC-10, AC-OPS-4 | The first edit on a truly misaligned group writes the rows on screen for good. Avoided by zero writes on load (AC-DATA-11) and the narrowed definition, so only a group whose pairing columns disagree is affected and the user has seen the notice first. |
| P4 | Settings row removal: no remove control on a single row; focus and announcement after a removal. | P3 | AC-DESIGN-8, AC-A11Y-7 | None identified beyond P3's: it adds no write path, and a removal is one validated group save. |
| P5 | Wizard: loads the stored indexers and saves all five Newznab columns as one group. | P1 (independent of P3) | AC-PROD-4; AC-DESIGN-5, -6, -12; AC-DATA-6, -17, -18, -19, -20; AC-QA-13; AC-A11Y-6, -10, -11, -12; AC-SEC-2, -10; AC-OPS-4; AC-SIMP-8, -12 | The highest in the change: the wizard becomes a read-then-overwrite writer of every Newznab credential. Avoided by AC-DATA-19 (a failed or pending read writes nothing) and AC-DATA-20 (zero kept rows writes nothing), and by asserting `config.ini`, not the request body. |
| P6 | Last: `settings.save` refuses combine columns (name matched after folding); test migration; debt and API docs. | P2, P3 and P5 all merged, with the AC-DATA-10 grep and the AC-SEC-10 request listener green on `master` first | AC-SEC-3, -8; AC-QA-7, -16, -17; AC-ARCH-1, -2; AC-OPS-2, -9; AC-PROD-10 | External scripts and tabs loaded before the upgrade lose per-column writes, and a missed first-party writer becomes a hard failure. Avoided by the two gates in "Depends on" and by AC-OPS-2's error text; the breaking API change goes in the release notes. |
| Final review | Whole-change constraints, checked against the cumulative diff. | all slices | AC-SIMP-1, -2, -3, -4, -5, -6, -9, -10, -11; AC-ARCH-10; AC-DESIGN-1; AC-PROD-9; AC-QA-18 | Not a merge. AC-SIMP-4 and AC-SIMP-11 are cumulative budgets: P1 spends the single new API view, P3 spends the single new file under `tests/e2e/`. Each slice's review still checks it has not broken a whole-change constraint. |

**Withdrawn:** AC-DATA-4.

**Placement check.** Every acceptance-criterion id in this file is in a slice,
in the final review, or withdrawn; none is unplaced. Three placements need a
reader's care:

- AC-SEC-2, AC-SEC-10, AC-DESIGN-5, AC-DATA-6, AC-A11Y-10, -11, -12 and
  AC-OPS-4 each have a Settings half and a wizard half. A criterion is closed
  only when both P3 and P5 have merged.
- AC-SEC-2's server half (a GET to the group-save route is refused and writes
  nothing) is built and unit-tested in P1 under AC-ARCH-11(iv); the criterion
  itself closes with its E2E request listeners in P3 and P5.
- AC-ARCH-1's proof and AC-QA-16's mutation of the per-column refusal both
  need the refusal that only P6 builds, which is why they close in P6 although
  the methods they exercise are frozen in P1 (AC-ARCH-11(i)).

## Vetoes and trade-offs

| Item | Raised by | Decision | Rationale |
|---|---|---|---|
| Store each indexer as one record | owner | declined | Settings migration for every install; irrecoverable tier |
| Check only in the page's script | owner | declined | Anything else that saves settings would bypass it |

## Spec gaps found at review

Found by the consistency review and the delivery plan on 2026-11-14, before any
code was written. Each is a gap a planning lens could have caught:

| Gap | What was missing | Lens that could have caught it | Now carried by |
|---|---|---|---|
| Read failure | Nothing said what the wizard does when its read of the stored rows fails or is still pending; an empty result would have been saved over the stored indexers. | data | AC-DATA-19 |
| Fresh-install defaults | "Stored indexers" was undefined, so a fresh install's six keyless default hosts counted as indexers and the wizard would have opened as already configured. Zero kept rows was also undefined. | product, design | Definitions, AC-DESIGN-12, AC-DATA-20 |
| `use` omitted | D3 and AC-PROD-4 kept `extra_score` and `custom_tag` for a loaded row but not `use`, so a re-run would have re-enabled every disabled indexer. | data, product | D3, AC-PROD-4 |
| Masking premise | AC-DATA-18 assumed the settings read masks combine-group keys. It masks only `password`-typed options. | security | AC-DATA-18 |
| `%2c` versus the JSON transport | AC-SIMP-8 kept the wizard's encoded-comma refusal "unchanged" while AC-QA-3 and AC-DATA-6 require `%2C` to be stored as typed through the wizard. | QA, simplicity | AC-SIMP-8 |
| Misaligned definition | "Columns of unequal length" matched the shape today's wizard writes, so most wizard-configured installs would have been shown the notice. | data, design | Definitions, D2, AC-DESIGN-10, AC-QA-10 |
| Non-string and control-character cells | No criterion refused a cell that is not a string (a list is stringified with a comma) or one holding a line break (part of the value can be dropped on reload). | security, QA | AC-SEC-11, AC-SEC-12, AC-QA-4 |
| The wizard's sync URL | D1 and AC-SEC-9 said the wizard calls `jackettSync`. It requests a route name that is not registered, and the E2E stubs stub that same name. | architecture, QA | Problem fact 4, D1, AC-SEC-9, slice P2 |
