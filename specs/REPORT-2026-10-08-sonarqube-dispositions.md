# SonarQube delivery and open-finding dispositions, 2026-10-08

## Method

Each result below comes from an analysis of a clean `master` checkout, with
Python and JavaScript coverage uploaded. Issue counts use SonarQube's open,
unresolved issue records, not a count of lines or a filtered dashboard view.
The baseline was 685 code smells at `2b7ed668`; the final analysed code
revision is `5df3baf7d02d680346ade4e636c0bac940e30b2d`. The per-issue
snapshot was taken at `775c6b05114820b7496965a988ddffacf99f6a1a`.
SonarQube is a reporting tool for this repository, not a CI or merge gate.
An open issue remains open when the suggested edit has no demonstrated benefit
or would add risk.

The earlier investigations in
[the assessed-slices plan](PLAN-2026-09-07-sonarqube-slices.md) and
[its follow-up](PLAN-2026-09-07-post-sonarqube-followups.md) remain detailed
evidence for the rule families they cover. This report records what the October pass
actually changed and where its remaining rule families stand. No issue was
resolved or suppressed in SonarQube merely to lower a number.

## Delivered slices

| PR | Behaviour and verification | SonarQube result |
| --- | --- | --- |
| [#507](https://github.com/bassings/CouchPotatoServer/pull/507) | Shared scheduled-job identifier and isolated test state; full local gate, independent reviews, CI and cloud review | 17 records closed: one `python:S1192`, nine `python:S8997`, seven `python:S9081` |
| [#508](https://github.com/bassings/CouchPotatoServer/pull/508) | Restored process-wide `Env` state after three autouse fixtures, including after a failing test; mutation proof and independent reviews | All three `python:S9100` records closed; one `python:S8999` test-configuration warning appeared |
| [#509](https://github.com/bassings/CouchPotatoServer/pull/509) | Directory-list failures now return a fixed error without private paths; settings and setup pickers announce failure, block selection and ignore stale responses; phone and keyboard tests | No existing record closed. One `javascript:S2486` appeared on the setup catch that presents the failure. This is a static warning on handled failure, not a silent catch |
| [#510](https://github.com/bassings/CouchPotatoServer/pull/510) | Three exception assertions now require the measured `RecordDeleted` or `ValueError`; unrelated errors also propagate through reference-expression tests | All three `python:S5958` records closed |
| [#511](https://github.com/bassings/CouchPotatoServer/pull/511) | Log-clear failures return failure without logging private paths; both log screens retain entries through failed clears; server, phone and race tests | Three new static warnings; no old records closed |
| [#512](https://github.com/bassings/CouchPotatoServer/pull/512) | Failed log loads now show a retryable warning on both screens, preserve entries and ignore stale responses; browser tests cover HTTP, API, malformed, network and ordering failures | No records closed or added; the two flagged log catches remain open as handled failures |
| [#513](https://github.com/bassings/CouchPotatoServer/pull/513) | Settings now confirms the restart API accepted a request before hiding its reminder or scheduling reload, blocks conflicting repeated requests and times out a stalled request; phone and keyboard tests cover refusal and retry | One new `typescript:S2925` warning on the deliberate 250 ms observation window that proves a second request does not occur; no old record closed |

Every behavioural slice used a failing test before its fix and a deliberate
mutation that made the relevant check fail again. The final branch of each PR
passed two independent local reviews before each push. PR CI and cloud review
were followed through to merge. Automatic beta builds were authorised;
production promotion and deployment were not part of this delivery.

## Remaining findings

The exact final inventory by rule, severity and count follows this assessment.
These are dispositions for the observed code, not permission to repeat a
finding in new code.

### Complexity, duplicated literals and deliberate stubs

`python:S3776` and `javascript:S3776` identify genuinely complex code,
including the database and live setup paths. They are a useful risk map.
Breaking those functions up only to meet a score would change control flow in
high-risk code without a behavioural requirement. Keep each record open and
use focused tests when its enclosing workflow next changes. The remaining
`python:S1192` literals had no demonstrated inconsistent behaviour in this
pass; extract a shared value when a specific caller contract requires one, as
#507 did for the scheduled-job ID. `python:S1186` points to deliberately empty
base-class hooks whose implementations belong in subclasses.

`javascript:S3735` points to the intentional layout read in the Suggestions
transition. The `void` expression forces a synchronous layout flush, so
removing it can change the transition. The September follow-up measured this
call site. It stays open.

`python:S108` now points to the empty body of `with open(path, 'w')` in the
log-clear operation. Opening in write mode is the truncation operation;
the empty body closes the file. Replacing it with a second truncation call
would perform a redundant operation after the file has already been cleared,
and could change error reporting. The log-clear tests cover its success and
failure contract. Keep the warning open unless a verified simpler operation
preserves that contract.

### Compatibility and UI semantics

The naming rules `python:S100`, `python:S101`, `python:S117` and
`python:S1542` mostly point at established application APIs, plugin hooks or
local names. Renaming public call sites for syntax alone risks compatibility;
local renames can be done with the next functional edit. `python:S1172`
includes callback parameters whose signatures may be set by the caller.

The remaining `Web:S6819` role-to-element suggestions were assessed with the
actual templates in the September plan. A tag substitution alone does not
prove an accessibility improvement and can alter landmarks. The two
`Web:S7927` warnings are on buttons whose visible words, `Add` and `Up`,
already occur in their accessible names, `Add row` and `Up one folder`.
The additional visible `+` and arrow glyphs are not the button names;
`tests/e2e/accessibility.a11y.spec.ts` opens both settings controls and pins
their rendered accessible names. Keep WCAG 2.2 AA and phone-width tests as
the decision gate for any change there.

`python:S8415` asks for FastAPI response documentation, but this application
disables the served OpenAPI schema. `python:S8410` is a type-annotation style
request and changes no dependency behaviour. Neither warrants a standalone
production edit.

### Error handling and test guards

The remaining `javascript:S2486` catches were checked against their caller
flows. The new setup picker catch displays `browserError`, announces it and
blocks selection; its phone-width test exercises an HTTP failure and retry.
A separate settings-picker stale-response test injects malformed JSON. The
log screens show a warning and retain entries, and the inspected movie-detail
and profile paths notify the operator or roll back optimistic state. The Settings restart catch now retains its reminder and reports that
restart could not be confirmed when HTTP, API or network results fail or a
request stalls past its deadline. Its pending guard prevents conflicting
requests. The empty catch around
`updater.info` discards optional version
metadata while leaving settings usable; it does not report an update as
successful. A static catch warning here is not, by itself, evidence that a
core action fails silently.
`python:S2737` includes explicit rethrows and `python:S2772` redundant `pass`
statements; neither hides a measured failure in this pass.

`typescript:S2925` flags waits in tests that assert an unwanted request never
occurs. The new #513 record is on the 250 ms window after a second keyboard
activation, while the first restart response stays pending. The test counts
requests at the route and failed under a deliberate guard mutation that sent
two requests. Waiting through the observation window is deliberate: an
observable success condition cannot prove the absence of a later request.
The three `typescript:S8783` forced checkbox actions select hidden controls
for a bulk-selection logic test; visible interaction has separate coverage.
The remaining test-only `python:S8999`, `python:S9002` and `python:S9073`
suggest plugin placement, fixture choice and assertion diagnostics. The
fixture-isolation test uses the `pytester` plugin and currently passes;
moving its declaration into the shared unit `conftest.py` changes common
test setup without fixing a measured failure. Revisit these tests when their
behaviour is edited, and require mutation proof for any new guard.

The two informational `python:S1135` comments concern different questions in
`couchpotato/core/plugins/browser.py`. Line 122 asks whether a root-path check
works on Windows. The documented production image is Alpine, so keep that
question open until Windows behaviour is tested. Line 30 asks whether missing
plugin dependencies should use an `ImportError` subtype distinct from broken
plugins. `core/loader.py` catches `ImportError` and currently distinguishes
missing dependencies by message text; changing that contract needs a loader
test and an operability review. Keep that question open rather than deleting
the comment to clear a scanner count.

### Local idioms

The rest of the inventory consists of local simplification, naming, regex,
constructor and syntax suggestions. They are left open because a standalone
edit would touch working production or guard code without a demonstrated
failure. In particular, replacing `[0-9]` with `\d` under `python:S6353`
would widen matching to Unicode digits, so that is not an equivalent edit.
The September plans assess some of these families. The per-issue register
below covers the other 22 rule families against every open issue site.
Change one in the course of related work when its behaviour and callers can
be verified; do not run a mechanical sweep through scanner, renamer, database
or test-guard code.

### Per-issue local dispositions

The September plans do not assess these 103 records in 22 rule families. This
point-in-time register gives each record its own source expression, scanner
suggestion and decision. It is generated from the reduced
[exact-master issue snapshot](SONAR-2026-10-08-local-issues.json); the
[completeness test](../tests/unit/test_sonar_handoff_report.py) checks that
every snapshot issue appears exactly once and keeps its source and suggestion.
The decision states why no standalone change was made; each record stays open.

| Issue key | Rule | Site | Source at scan | Scanner suggestion | Disposition |
| --- | --- | --- | --- | --- | --- |
| `38621f0e-a929-461a-97b8-7f81d0360679` | `javascript:S1871` | `couchpotato/ui/templates/base.html:404` | <code>} else if (window.matchMedia('(prefers-color-scheme: light)').matches) {</code> | This branch's code block is the same as the block for the branch on line 398. | Hold: this UI branch shares a body with another branch; consolidate only with theme or settings browser coverage. |
| `6d516b4a-cd3f-4370-afb2-1c8cc8a34bed` | `javascript:S1871` | `couchpotato/ui/templates/partials/settings/scripts.html:316` | <code>else if (this.isEnabled(group)) this.openGroups[key] = true;</code> | This branch's code block is the same as the block for the branch on line 315. | Hold: this UI branch shares a body with another branch; consolidate only with theme or settings browser coverage. |
| `aed8c80d-3967-415f-a90e-5985f350358d` | `javascript:S6582` | `couchpotato/static/scripts/ui/category-editor.js:15` | <code>const o = (category &#124;&#124; {}).order;</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `b50c8c58-f652-47b6-9c1b-85669aab131d` | `javascript:S6582` | `couchpotato/static/scripts/ui/category-editor.js:60` | <code>label:       trim(formState &amp;&amp; formState.label),</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `c6621192-6b67-4c15-b80d-d118c28764d1` | `javascript:S6582` | `couchpotato/static/scripts/ui/category-editor.js:61` | <code>ignored:     trim(formState &amp;&amp; formState.ignored),</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `f6f8fba8-a3a7-4791-8eff-0aa711d0d554` | `javascript:S6582` | `couchpotato/static/scripts/ui/category-editor.js:62` | <code>preferred:   trim(formState &amp;&amp; formState.preferred),</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `8df96e0d-4e29-4d7e-b110-c6464f9ba6a8` | `javascript:S6582` | `couchpotato/static/scripts/ui/category-editor.js:63` | <code>required:    trim(formState &amp;&amp; formState.required),</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `c5ef13cf-7053-4c9e-ae85-a9680dfb940b` | `javascript:S6582` | `couchpotato/static/scripts/ui/category-editor.js:64` | <code>destination: trim(formState &amp;&amp; formState.destination),</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `846d1320-8f29-446b-a18c-42bb902b626a` | `javascript:S6582` | `couchpotato/static/scripts/ui/category-editor.js:71` | <code>if (formState &amp;&amp; formState.id != null &amp;&amp; formState.id !== '') {</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `b5500ab7-0fb0-41e4-a718-c14b5515c3e0` | `javascript:S6582` | `couchpotato/static/scripts/ui/category-editor.js:92` | <code>const label = (formState &amp;&amp; formState.label != null) ? String(formState.label).trim() : '';</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `01bc9d71-5a9b-4255-9ee4-6f7a0bef624b` | `javascript:S6582` | `couchpotato/static/scripts/ui/profile-editor.js:182` | <code>const label = (formState &amp;&amp; formState.label != null) ? String(formState.label).trim() : '';</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `3e882afd-9cd4-40df-9693-7be562647f87` | `javascript:S6582` | `couchpotato/static/scripts/ui/profile-editor.js:187` | <code>const types = (formState &amp;&amp; formState.types) ? formState.types : [];</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `bc1fa4db-e2a3-42dd-a0c8-0081c744cb6f` | `javascript:S6582` | `couchpotato/static/scripts/ui/profile-editor.js:194` | <code>const score = formState &amp;&amp; formState.minimumScore;</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `6fc5cee7-124b-450e-85b1-26e5b1a7e9dd` | `javascript:S6582` | `couchpotato/static/scripts/ui/profile-editor.js:199` | <code>const v = formState &amp;&amp; formState[key];</code> | Prefer using an optional chain expression instead, as it's more concise and easier to read. | Hold: optional chaining can differ from this guard for falsy values; check the editor input contract before rewriting. |
| `b3be9669-a0bd-41f5-8656-bf2933c3d3aa` | `javascript:S7750` | `scripts/check_e2e_test_traps.mjs:421` | <code>testids = candidates.filter(binding =&gt; binding.line &lt;= lineOf(node)).at(-1)?.testids;</code> | Prefer `.findLast(…)` over `.filter(…).at(-1)`. | Hold: changing the E2E trap guard traversal needs mutation proof that prohibited tests are still rejected. |
| `5c08974d-b322-49cb-881c-45e6356d7ca2` | `javascript:S7760` | `couchpotato/static/scripts/ui/settings-help.js:20` | <code>apiDesc = apiDesc &#124;&#124; '';</code> | Prefer default parameters over reassignment. | Hold: a default parameter only covers undefined, while this assignment covers all falsy inputs; check callers first. |
| `59adde2e-3cba-4817-a43e-3d865d4cefec` | `javascript:S7765` | `couchpotato/static/scripts/ui/log-parser.js:21` | <code>return LINE_TERMINATORS.some(character =&gt; value.indexOf(character, start) &gt;= 0);</code> | Use `.includes()`, rather than `.indexOf()`, when checking for existence. | Hold: includes would be a local membership idiom change with no measured parser defect; keep for a tested parser edit. |
| `351e510a-ce8b-43a9-93b9-edd03d9c4d7f` | `javascript:S7770` | `couchpotato/ui/templates/wizard.html:1204` | <code>const hosts = this.formData.newznab.entries.map(e =&gt; e.host).filter(h =&gt; h).join(',');</code> | arrow function is equivalent to `Boolean`. Use `Boolean` directly. | Hold: replacing this wizard predicate with Boolean is cosmetic; cover the wizard values in a related edit. |
| `c836483e-7817-4e49-b435-86a635792ced` | `javascript:S7770` | `couchpotato/ui/templates/wizard.html:1205` | <code>const keys = this.formData.newznab.entries.map(e =&gt; e.api_key).filter(k =&gt; k).join(',');</code> | arrow function is equivalent to `Boolean`. Use `Boolean` directly. | Hold: replacing this wizard predicate with Boolean is cosmetic; cover the wizard values in a related edit. |
| `ff3445b3-2ffa-43ea-a435-df97358f75f7` | `javascript:S7778` | `couchpotato/ui/templates/wizard.html:1208` | <code>saves.push(this.saveSetting('newznab', 'api_key', keys));</code> | Do not call `Array#push()` multiple times. | Hold: combining wizard push calls has no measured benefit; verify save ordering during a related wizard edit. |
| `d673a1f7-e2ef-49bf-9ba5-c35201421b87` | `javascript:S7778` | `couchpotato/ui/templates/wizard.html:1209` | <code>saves.push(this.saveSetting('newznab', 'use', use));</code> | Do not call `Array#push()` multiple times. | Hold: combining wizard push calls has no measured benefit; verify save ordering during a related wizard edit. |
| `a3a20f6d-107f-41c8-af38-487e502847ae` | `javascript:S7778` | `couchpotato/ui/templates/wizard.html:1218` | <code>saves.push(this.saveSetting('yts', 'enabled', this.formData.yts.enabled ? '1' : '0'));</code> | Do not call `Array#push()` multiple times. | Hold: combining wizard push calls has no measured benefit; verify save ordering during a related wizard edit. |
| `6ca84370-4846-46ed-b9a7-34dbf6a3a24e` | `javascript:S7778` | `couchpotato/ui/templates/wizard.html:1219` | <code>saves.push(this.saveSetting('torrentpotato', 'enabled', this.formData.torrentpotato.enabled ? '1' : '0'));</code> | Do not call `Array#push()` multiple times. | Hold: combining wizard push calls has no measured benefit; verify save ordering during a related wizard edit. |
| `76dd774e-2edd-4ceb-8673-f29be8d014b1` | `javascript:S7778` | `couchpotato/ui/templates/wizard.html:1222` | <code>saves.push(this.saveSetting('torrentpotato', 'jackett_api_key', this.formData.torrentpotato.jackett_api_key));</code> | Do not call `Array#push()` multiple times. | Hold: combining wizard push calls has no measured benefit; verify save ordering during a related wizard edit. |
| `02ddd55e-3354-4f88-bae7-35b8f44344b6` | `javascript:S7786` | `scripts/lighthouse-policy.mjs:37` | <code>throw new Error(`Lighthouse result is missing ${label}`);</code> | `new Error()` is too unspecific for a type check. Use `new TypeError()` instead. | Hold: changing Error to TypeError changes the observable failure class; check policy callers and tests first. |
| `6b88630d-2016-4a4b-8493-a5f5fb9c9bbf` | `javascript:S7786` | `scripts/lighthouse-policy.mjs:110` | <code>throw new Error('Lighthouse returned malformed HTML or JSON report data');</code> | `new Error()` is too unspecific for a type check. Use `new TypeError()` instead. | Hold: changing Error to TypeError changes the observable failure class; check policy callers and tests first. |
| `2ff00e8b-b886-41a3-acd7-dba0b8a9e3c4` | `python:S1940` | `couchpotato/core/downloaders/deluge.py:150` | <code>if not 'hash' in torrent:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `61ae71eb-cb23-4ec0-b9bd-a3edbafa73b3` | `python:S1940` | `couchpotato/core/downloaders/transmission.py:163` | <code>if torrent.get('isStalled') and not torrent['percentDone'] == 1 and self.conf('stalled_as_failed'):</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `851cb272-64d7-404b-a274-89a7423e7993` | `python:S1940` | `couchpotato/core/downloaders/utorrent.py:223` | <code>if not status == 'busy':</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `f1b65a1e-a3c3-4714-bf46-c19ea1854407` | `python:S1940` | `couchpotato/core/downloaders/utorrent.py:369` | <code>settings_dict[setting[0]] = int(setting[2] if not setting[2].strip() == '' else '0')</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `59d26ab1-fa0d-41bd-b5c8-beff3658c570` | `python:S1940` | `couchpotato/core/helpers/variable.py:322` | <code>if not '://' in host and protocol:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `4f579f55-c069-4a97-8b98-5000658a1245` | `python:S1940` | `couchpotato/core/media/_base/providers/torrent/passthepopcorn.py:45` | <code>if not 'Movies' in res:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `8f44dc74-5c8f-4a43-bb96-f7753a54da92` | `python:S1940` | `couchpotato/core/media/_base/providers/torrent/passthepopcorn.py:52` | <code>if not 'Torrents' in ptpmovie:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `d8ce87bc-f6fd-480b-a0d9-4c36f0971dea` | `python:S1940` | `couchpotato/core/media/_base/providers/torrent/passthepopcorn.py:105` | <code>if not quality in self.post_search_filters:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `77daec18-ef9b-40e4-b790-a4ee72233b30` | `python:S1940` | `couchpotato/core/media/_base/providers/torrent/passthepopcorn.py:118` | <code>if not field in torrent:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `db8ef468-1091-4be4-a017-a49a3e8dbf6f` | `python:S1940` | `couchpotato/core/media/movie/providers/automation/bluray.py:63` | <code>if not name.find('/') == -1:  # make sure it is not a double movie release</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `2a6229c9-288b-4af2-b65c-3f36e81ab2bc` | `python:S1940` | `couchpotato/core/media/movie/providers/automation/bluray.py:94` | <code>if not name.find('/') == -1:  # make sure it is not a double movie release</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `bfdcfd91-35fd-48fc-954a-a9edd46787b3` | `python:S1940` | `couchpotato/core/media/movie/providers/automation/bluray.py:126` | <code>if not name.find('/') == -1: # make sure it is not a double movie release</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `4b10be03-f674-434e-81c4-f7dc2c5075a6` | `python:S1940` | `couchpotato/core/media/movie/providers/trailer/hdtrailers.py:125` | <code>if 'trailer' in trtext and not 'clip' in trtext and provider in trtext and not '3d' in trtext:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `b2dc367a-8039-4444-b812-489786839ee1` | `python:S1940` | `couchpotato/core/media/movie/providers/trailer/hdtrailers.py:125` | <code>if 'trailer' in trtext and not 'clip' in trtext and provider in trtext and not '3d' in trtext:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `ee498592-b441-4f50-9260-ff5f61edc850` | `python:S1940` | `couchpotato/core/media/movie/providers/userscript/allocine.py:18` | <code>if not 'fichefilm_gen_cfilm' in url:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `b152dd84-3e3d-4aeb-871c-4f636780e0b3` | `python:S1940` | `couchpotato/core/notifications/base.py:32` | <code>if not listener in self.dont_listen_to:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `fd9fa7a7-c53b-41b8-ae3a-0478f56e0cfb` | `python:S1940` | `couchpotato/core/notifications/telegrambot.py:50` | <code>if not response.status_code == 200:</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `9d246645-e0a2-4746-8f96-596f9d8336cf` | `python:S1940` | `couchpotato/core/plugins/base.py:237` | <code>use_cache = not len(kwargs.get('data', {})) &gt; 0 and not kwargs.get('files')</code> | Use the opposite operator ("&lt;=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `9b1af628-79d2-4de7-8a09-f5302b674def` | `python:S1940` | `couchpotato/core/plugins/renamer/cleanup.py:64` | <code>tag_files.extend([sp(os.path.join(root, name)) for name in names if not os.path.splitext(name)[1] == '.ignore'])</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `420417dd-ae17-416f-8df6-aa21987d9e2f` | `python:S1940` | `couchpotato/core/plugins/renamer/cleanup.py:96` | <code>tag_files.extend([sp(os.path.join(root, name)) for name in names if not os.path.splitext(name)[1] == '.ignore'])</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `c069a673-7c32-4b65-a3e1-cd5ce63751e2` | `python:S1940` | `couchpotato/core/plugins/renamer/scanner.py:130` | <code>if self.conf('file_action') != 'move' and not rel.get('status') == 'seeding' and self.statusInfoComplete(release_download):</code> | Use the opposite operator ("!=") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `72b7b10f-48dc-41fc-8a9e-d7f370caed6a` | `python:S1940` | `couchpotato/core/plugins/scanner/folder_scanner.py:839` | <code>if not word in out:</code> | Use the opposite operator ("not in") instead. | Hold: inverting this comparison is a syntax edit with no measured defect; verify the enclosing workflow if changed. |
| `fa246006-d49c-478b-ad9d-9b1077d1a9e7` | `python:S3626` | `couchpotato/core/_base/downloader/main.py:102` | <code>return</code> | Remove this redundant return. | Hold: removing this terminator has no measured defect; check the enclosing return or loop contract before editing. |
| `c9dd4dd9-7502-4add-b1bb-d81148439cae` | `python:S3626` | `couchpotato/core/_base/downloader/main.py:116` | <code>return</code> | Remove this redundant return. | Hold: removing this terminator has no measured defect; check the enclosing return or loop contract before editing. |
| `14d6ec6c-a76a-4d98-be8a-f8059b5293ae` | `python:S3626` | `couchpotato/core/media/_base/providers/base.py:270` | <code>return</code> | Remove this redundant return. | Hold: removing this terminator has no measured defect; check the enclosing return or loop contract before editing. |
| `3ec539e6-6483-44ec-b599-c3d85aaed0a2` | `python:S3626` | `couchpotato/core/media/_base/providers/nzb/newznab.py:74` | <code>continue</code> | Remove this redundant continue. | Hold: removing this terminator has no measured defect; check the enclosing return or loop contract before editing. |
| `fee67ded-da6e-4024-a2b8-05ac583d6f3e` | `python:S3626` | `couchpotato/core/media/_base/providers/torrent/yts.py:61` | <code>return</code> | Remove this redundant return. | Hold: removing this terminator has no measured defect; check the enclosing return or loop contract before editing. |
| `695b2e19-4a30-4847-a01b-0f9ebeec5f50` | `python:S3626` | `couchpotato/core/media/_base/providers/userscript/base.py:50` | <code>return</code> | Remove this redundant return. | Hold: removing this terminator has no measured defect; check the enclosing return or loop contract before editing. |
| `8fb522e9-6015-4015-afd0-6fd9e04b8b06` | `python:S3626` | `couchpotato/core/plugins/renamer/main.py:1390` | <code>return</code> | Remove this redundant return. | Hold: removing this terminator has no measured defect; check the enclosing return or loop contract before editing. |
| `1446a02c-12e0-43fc-a0fc-27b27fbdb352` | `python:S5713` | `couchpotato/core/cache.py:160` | <code>except (TypeError, ValueError, binascii.Error):</code> | Remove this redundant Exception class; it derives from another which is already caught. | Hold: a named exception is covered by another caught class; changing the handler needs its failure tests. |
| `3b2eb2e0-a932-418c-b6f0-8e7105ba766b` | `python:S5713` | `couchpotato/core/database.py:245` | <code>except (json.JSONDecodeError, ValueError):</code> | Remove this redundant Exception class; it derives from another which is already caught. | Hold: a named exception is covered by another caught class; changing the handler needs its failure tests. |
| `2c1df597-5974-4225-93fe-6fcf307b7a67` | `python:S5713` | `couchpotato/core/notifications/emby.py:34` | <code>except (OSError, urllib.error.URLError):</code> | Remove this redundant Exception class; it derives from another which is already caught. | Hold: a named exception is covered by another caught class; changing the handler needs its failure tests. |
| `f301326d-2607-4201-a5c0-695f8a023082` | `python:S5713` | `couchpotato/core/notifications/emby.py:59` | <code>except (OSError, urllib.error.URLError):</code> | Remove this redundant Exception class; it derives from another which is already caught. | Hold: a named exception is covered by another caught class; changing the handler needs its failure tests. |
| `7e2e8531-600d-4a71-91bf-74ea5de4b01a` | `python:S5713` | `couchpotato/core/settings.py:601` | <code>except (json.JSONDecodeError, ValueError):</code> | Remove this redundant Exception class; it derives from another which is already caught. | Hold: a named exception is covered by another caught class; changing the handler needs its failure tests. |
| `24b04335-17f2-466f-8205-e101a855e7aa` | `python:S5713` | `scripts/sonar_scan.py:370` | <code>except (URLError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:</code> | Remove this redundant Exception class; it derives from another which is already caught. | Hold: a named exception is covered by another caught class; changing the handler needs its failure tests. |
| `ffb995b1-3924-4b64-addb-fb4286a2434e` | `python:S5713` | `scripts/sonar_scan.py:370` | <code>except (URLError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:</code> | Remove this redundant Exception class; it derives from another which is already caught. | Hold: a named exception is covered by another caught class; changing the handler needs its failure tests. |
| `98c2e908-b93a-4cc8-aced-9e8cd8b6b23c` | `python:S5843` | `scripts/check_test_traps.py:1526` | <code>r"""(?:^&#124;\s)([A-Za-z_:][-A-Za-z0-9_:.]*)(?:\s*=\s*("[^"]*"&#124;'[^']*'&#124;[^\s"'=&lt;&gt;`]+))?"""</code> | Simplify this regular expression to reduce its complexity from 24 to the 20 allowed. | Hold: shortening this test-trap regex needs mutation proof that its prohibited patterns remain caught. |
| `19a5edd4-cab0-4204-8d30-2fa38bcf2f82` | `python:S6353` | `couchpotato/core/helpers/request.py:58` | <code>alphanum_key = lambda key: [convert(c) for c in re.split('([0-9]+)', key)]</code> | Use concise character class syntax '\d' instead of '[0-9]'. | Hold: replacing ASCII [0-9] with Unicode-aware \d can widen accepted input; keep the present matching contract. |
| `0f67c1e1-2624-420c-952d-512323e39248` | `python:S6353` | `couchpotato/core/plugins/scanner/folder_scanner.py:867` | <code>matches = re.findall(r'(\(&#124;\[)(?P&lt;year&gt;19[0-9]{2}&#124;20[0-9]{2})(\]&#124;\))', text)</code> | Use concise character class syntax '\d' instead of '[0-9]'. | Hold: replacing ASCII [0-9] with Unicode-aware \d can widen accepted input; keep the present matching contract. |
| `db9c4da2-def6-448c-bf58-d15fa8f3c432` | `python:S6353` | `couchpotato/core/plugins/scanner/folder_scanner.py:867` | <code>matches = re.findall(r'(\(&#124;\[)(?P&lt;year&gt;19[0-9]{2}&#124;20[0-9]{2})(\]&#124;\))', text)</code> | Use concise character class syntax '\d' instead of '[0-9]'. | Hold: replacing ASCII [0-9] with Unicode-aware \d can widen accepted input; keep the present matching contract. |
| `dbb24ca1-d583-4187-a1b5-d5e9673ffe92` | `python:S6353` | `couchpotato/core/plugins/scanner/folder_scanner.py:871` | <code>matches = re.findall('(?P&lt;year&gt;19[0-9]{2}&#124;20[0-9]{2})', text)</code> | Use concise character class syntax '\d' instead of '[0-9]'. | Hold: replacing ASCII [0-9] with Unicode-aware \d can widen accepted input; keep the present matching contract. |
| `f6f6a2a0-f589-4c95-8a85-f27b531fffa9` | `python:S6353` | `couchpotato/core/plugins/scanner/folder_scanner.py:871` | <code>matches = re.findall('(?P&lt;year&gt;19[0-9]{2}&#124;20[0-9]{2})', text)</code> | Use concise character class syntax '\d' instead of '[0-9]'. | Hold: replacing ASCII [0-9] with Unicode-aware \d can widen accepted input; keep the present matching contract. |
| `702538a7-1213-4dce-a42d-bff87409678b` | `python:S6353` | `couchpotato/core/plugins/score/scores.py:219` | <code>year = re.findall('(?P&lt;year&gt;19[0-9]{2}&#124;20[0-9]{2})', name)</code> | Use concise character class syntax '\d' instead of '[0-9]'. | Hold: replacing ASCII [0-9] with Unicode-aware \d can widen accepted input; keep the present matching contract. |
| `d70ea6e0-d71f-4f09-864b-6eb43eb06902` | `python:S6353` | `couchpotato/core/plugins/score/scores.py:219` | <code>year = re.findall('(?P&lt;year&gt;19[0-9]{2}&#124;20[0-9]{2})', name)</code> | Use concise character class syntax '\d' instead of '[0-9]'. | Hold: replacing ASCII [0-9] with Unicode-aware \d can widen accepted input; keep the present matching contract. |
| `0ee5c2f7-3f29-4c59-a2ec-24f51a2120f0` | `python:S6353` | `scripts/e2e_worker_data.py:132` | <code>if not re.fullmatch(r'[0-9]+', str(worker_index)):</code> | Use concise character class syntax '\d' instead of '[0-9]'. | Hold: replacing ASCII [0-9] with Unicode-aware \d can widen accepted input; keep the present matching contract. |
| `12daa82f-ffdc-4bb7-a9db-885e10b2cb37` | `python:S6659` | `couchpotato/__init__.py:1709` | <code>if url[:3] != 'api':</code> | Use `not` and `startswith` here. | Hold: check this caller’s type and boundary behaviour before applying the scanner’s specific prefix or suffix suggestion. |
| `e325dfca-2007-4523-99ca-b2e72794cd49` | `python:S6659` | `couchpotato/core/loader.py:53` | <code>if plugin.get('name', '')[:2] == '__':</code> | Use `startswith` here. | Hold: check this caller’s type and boundary behaviour before applying the scanner’s specific prefix or suffix suggestion. |
| `4d9b65d3-5053-4e7d-83c5-418b7c1245cb` | `python:S6659` | `couchpotato/core/media/_base/providers/torrent/base.py:24` | <code>if url[:4] == 'http':</code> | Use `startswith` here. | Hold: check this caller’s type and boundary behaviour before applying the scanner’s specific prefix or suffix suggestion. |
| `a97af5bc-9d1d-4c84-aecf-cadee2f8ecc3` | `python:S6659` | `couchpotato/core/media/_base/providers/torrent/passthepopcorn.py:144` | <code>if txt[:2] == "&amp;#":</code> | Use `startswith` here. | Hold: check this caller’s type and boundary behaviour before applying the scanner’s specific prefix or suffix suggestion. |
| `b2a7f9ee-a8ce-43c8-a3af-caeca11b0c84` | `python:S6659` | `couchpotato/core/media/_base/providers/torrent/passthepopcorn.py:147` | <code>if txt[:3] == "&amp;#x":</code> | Use `startswith` here. | Hold: check this caller’s type and boundary behaviour before applying the scanner’s specific prefix or suffix suggestion. |
| `9b668e1c-5b2f-42a0-b698-a15df5397fce` | `python:S6659` | `couchpotato/core/plugins/browser.py:119` | <code>elif parent != '/' and parent[-2:] != ':\\':</code> | Use `not` and `endswith` here. | Hold: check this caller’s type and boundary behaviour before applying the scanner’s specific prefix or suffix suggestion. |
| `dd808c46-ccb6-4ba6-b3ef-602528ffb793` | `python:S7492` | `couchpotato/core/helpers/variable.py:455` | <code>return all([k in b and b[k] == v for k, v in a.items()])</code> | Unpack this comprehension expression | Hold: unpacking this comprehension offers no measured helper fix; test the mapping contract when edited. |
| `b87cce84-aab7-46a8-8162-699be0440213` | `python:S7494` | `couchpotato/core/media/movie/providers/info/themoviedb.py:312` | <code>movie_data = dict((k, v) for k, v in movie_data.items() if v)</code> | Replace dict constructor call with a dictionary comprehension. | Hold: a dict comprehension is a syntax change only; verify resulting keys and values when this function changes. |
| `5a70d989-dd40-4973-9cd2-0e90a14e86fe` | `python:S7494` | `couchpotato/core/media/movie/providers/info/themoviedb.py:355` | <code>params = dict((k, v) for k, v in params.items() if v)</code> | Replace dict constructor call with a dictionary comprehension. | Hold: a dict comprehension is a syntax change only; verify resulting keys and values when this function changes. |
| `463ea0e9-afd2-48df-a220-3aa8bbd6fba6` | `python:S7494` | `couchpotato/core/plugins/release/main.py:358` | <code>release['files'] = dict((k, [toUnicode(x) for x in v]) for k, v in group['files'].items() if v)</code> | Replace dict constructor call with a dictionary comprehension. | Hold: a dict comprehension is a syntax change only; verify resulting keys and values when this function changes. |
| `c92a4759-852c-4426-a17c-31e74d41b945` | `python:S7494` | `scripts/sonar_scan.py:327` | <code>fields = dict(</code> | Replace dict constructor call with a dictionary comprehension. | Hold: a dict comprehension is a syntax change only; verify resulting keys and values when this function changes. |
| `6abe0fd1-df69-4f5f-8687-284a01c5c3e9` | `python:S7496` | `couchpotato/core/media/_base/media/main.py:319` | <code>all_media_ids = all_media_ids.union(set([x['_id'] for x in db.get_many('media_by_type', media_type)]))</code> | Replace this set constructor call by a set literal. | Hold: set literal syntax offers no measured fix; verify registration or matching results when this function changes. |
| `ae026640-b811-4984-9993-8194005f2f4a` | `python:S7496` | `couchpotato/core/media/_base/media/main.py:321` | <code>all_media_ids = set([x['_id'] for x in db.all('media')])</code> | Replace this set constructor call by a set literal. | Hold: set literal syntax offers no measured fix; verify registration or matching results when this function changes. |
| `d1ed6a10-bd86-4134-b3bf-9d572c8589ca` | `python:S7496` | `couchpotato/core/media/_base/media/main.py:494` | <code>all_media_ids = all_media_ids.union(set([x['_id'] for x in db.get_many('media_by_type', media_type)]))</code> | Replace this set constructor call by a set literal. | Hold: set literal syntax offers no measured fix; verify registration or matching results when this function changes. |
| `be6d0ad9-dc4f-4a60-af13-e174bf777f95` | `python:S7496` | `couchpotato/core/media/_base/media/main.py:496` | <code>all_media_ids = set([x['_id'] for x in db.all('media')])</code> | Replace this set constructor call by a set literal. | Hold: set literal syntax offers no measured fix; verify registration or matching results when this function changes. |
| `75491346-410d-4c84-bce0-9913fdea0342` | `python:S7496` | `couchpotato/core/plugins/scanner/file_detector.py:72` | <code>if list(set(file_name.lower().split(os.path.sep)) &amp; set(['video_ts', 'audio_ts'])):</code> | Replace this set constructor call by a set literal. | Hold: set literal syntax offers no measured fix; verify registration or matching results when this function changes. |
| `ad4e7f2d-ce30-47cd-aafa-44353d50683f` | `python:S7496` | `couchpotato/core/plugins/scanner/folder_scanner.py:240` | <code>found_files = set([item for item in leftovers if wo_ext in item])</code> | Replace this set constructor call by a set literal. | Hold: set literal syntax offers no measured fix; verify registration or matching results when this function changes. |
| `391b9fa8-9464-4355-a837-95a47e8cd3f1` | `python:S7496` | `couchpotato/core/plugins/scanner/folder_scanner.py:290` | <code>leftovers -= leftovers - set([ff])</code> | Replace this set constructor call by a set literal. | Hold: set literal syntax offers no measured fix; verify registration or matching results when this function changes. |
| `0b893ace-f7b9-4123-9068-57cc5a139c9d` | `python:S7498` | `couchpotato/core/notifications/discord.py:35` | <code>r = requests.post(self.conf('webhook_url'), data=json.dumps(dict(content=message, username=self.conf('bot_name'), avatar_url=self.conf('avatar_url'), tts=self.conf('discord_tts'))), headers=headers, timeout=_REQUEST_TIMEOUT)</code> | Replace this constructor call with a literal. | Hold: literal syntax offers no measured fix; verify notification payload or migration output when edited. |
| `509bf59c-361e-4287-bd0b-3c48a9c9a24c` | `python:S7498` | `scripts/migrate_codernity_to_sqlite.py:187` | <code>props = dict(</code> | Replace this constructor call with a literal. | Hold: literal syntax offers no measured fix; verify notification payload or migration output when edited. |
| `0dfb75c4-b058-4a9a-a73e-6a035a104342` | `python:S7500` | `couchpotato/core/http_client.py:287` | <code>data_keys = [x for x in data.keys()] if isinstance(data, dict) else 'with data'</code> | Replace this comprehension with passing the iterable to the collection constructor call | Hold: passing the iterable to list offers no measured fix; verify the resulting request or search data when edited. |
| `dd8caa14-0708-499d-be43-52e9bedc3386` | `python:S7500` | `couchpotato/core/media/movie/searcher.py:436` | <code>log.info2('Wrong: %s, looking for %s, found %s', nzb['name'], quality['label'], [x for x in contains_other] if contains_other else 'no quality')</code> | Replace this comprehension with passing the iterable to the collection constructor call | Hold: passing the iterable to list offers no measured fix; verify the resulting request or search data when edited. |
| `c6a721bb-126d-410a-8c00-04a31bb2a28d` | `python:S7504` | `couchpotato/core/media/_base/searcher/main.py:80` | <code>for useless_provider in list(set(provider_protocols) - set(download_protocols)):</code> | Remove this unnecessary `list()` call on an already iterable object. | Hold: this loop only logs members of a set difference; list is unnecessary but has no measured cost. |
| `d06f82ca-7224-401d-a26c-a324de58d723` | `python:S7504` | `couchpotato/core/plugins/renamer/extractor.py:342` | <code>for leftoverfile in list(files):</code> | Remove this unnecessary `list()` call on an already iterable object. | Hold: this loop removes files while iterating, so list preserves the original iteration set. |
| `b1e40ed2-fe02-4fce-b344-b268c46ed902` | `python:S7504` | `couchpotato/core/plugins/scanner/folder_scanner.py:237` | <code>for file_path in list(group['unsorted_files']):</code> | Remove this unnecessary `list()` call on an already iterable object. | Hold: this loop extends unsorted_files while iterating, so list preserves the original iteration set. |
| `d5e4c6d5-fb37-4fda-aeea-919db5d2b66a` | `python:S7504` | `couchpotato/core/plugins/scanner/folder_scanner.py:249` | <code>for file_path in list(group['unsorted_files']):</code> | Remove this unnecessary `list()` call on an already iterable object. | Hold: this loop counts extensions without changing unsorted_files; list is unnecessary but has no measured cost. |
| `02471170-ab03-4157-ba7d-8dcce54490a8` | `python:S7504` | `scripts/git_env.py:68` | <code>for key in list(env):</code> | Remove this unnecessary `list()` call on an already iterable object. | Hold: this loop removes entries from env while iterating, so list preserves the original key set. |
| `0eb6c891-1b01-4e61-890e-c028a3b8c57f` | `python:S7504` | `scripts/sonar_scan.py:93` | <code>for name in list(env):</code> | Remove this unnecessary `list()` call on an already iterable object. | Hold: this loop removes entries from env while iterating, so list preserves the original key set. |
| `45a28d11-148a-4f64-9bef-70a2b2848f84` | `python:S7508` | `couchpotato/core/media/movie/providers/info/themoviedb.py:318` | <code>all_titles = sorted(list(itertools.chain.from_iterable(movie_titles)))</code> | Remove this redundant call. | Hold: removing this nested conversion offers no measured fix; verify input type and ordering when edited. |
| `d91b1886-3064-4d5c-97ed-4157931206d0` | `python:S7508` | `couchpotato/core/plugins/renamer/cleanup.py:29` | <code>tag_files = [sorted(list(group['files']['movie']))[0]]</code> | Remove this redundant call. | Hold: removing this nested conversion offers no measured fix; verify input type and ordering when edited. |
| `7c7968bd-80e6-4c33-b8a4-e325207b1bd0` | `python:S7508` | `couchpotato/core/plugins/renamer/cleanup.py:52` | <code>tag_files = [sorted(list(group['files']['movie']))[0]]</code> | Remove this redundant call. | Hold: removing this nested conversion offers no measured fix; verify input type and ordering when edited. |
| `4e938c86-f797-4566-ba51-eb346131361d` | `python:S7632` | `scripts/seed_e2e_data.py:862` | <code>except Exception as exc:  # noqa: BLE001 -- report and exit non-zero, don't traceback-spam CI</code> | Fix the syntax of this issue suppression comment. | Hold: Ruff accepts this noqa comment; change suppression syntax only with lint and test-guard verification. |

## Final measured state

The clean `master` checkout and SonarQube scanner both identified revision
`5df3baf7d02d680346ade4e636c0bac940e30b2d`. Coverage reports were
uploaded and coverage measured **64.8%**, so this is not a missing-coverage
result. The open issue response held **668 code smells** across 59 rules,
with **zero bugs, vulnerabilities and security hotspots**. Compared with
the 685-smell baseline, the net change is 17 fewer open records. The issue-key
trail across the first five code PRs accounts for 23 closed records and five new
records; #512 changed neither set, and #513 added one `typescript:S2925`
record without closing an old one. PR #514's report guard briefly added one
`python:S9073` record; [#515](https://github.com/bassings/CouchPotatoServer/pull/515)
closed that exact key without adding another. The final open issue keys match
the `775c6b051` snapshot exactly. No issue was suppressed.

The informational quality gate is **green** at this revision. Its previous
new-violation failure at the intermediate report merge closed with #515; the
earlier new-code duplication failure is also absent. CI, independent local
reviews and cloud reviews passed before merge. The automatic beta builds
passed under the authorised release channel; production was not promoted or
deployed.

## Complete open-rule inventory

The disposition names correspond to the assessment sections above.
"Local idiom, next related edit" includes the regex and syntax cautions
called out there; it is not a recommendation to apply every suggested edit.
This table was generated from the `775c6b051` open-issue response. A key-by-key
comparison found the final `5df3baf7d` response identical, so its counts also
reconcile with the final analysed revision.

| Rule | Severity | Open | Disposition |
| --- | --- | ---: | --- |
| `Web:S6819` | major | 33 | UI semantics or API documentation |
| `Web:S7927` | major | 2 | UI semantics or API documentation |
| `javascript:S1871` | major | 2 | Local idiom, next related edit |
| `javascript:S2486` | minor | 13 | Handled failure |
| `javascript:S3358` | major | 4 | Local idiom, next related edit |
| `javascript:S3735` | critical | 1 | Complexity or intentional construct |
| `javascript:S3776` | critical | 8 | Complexity or intentional construct |
| `javascript:S6582` | minor | 12 | Local idiom, next related edit |
| `javascript:S7750` | minor | 1 | Local idiom, next related edit |
| `javascript:S7760` | major | 1 | Local idiom, next related edit |
| `javascript:S7765` | minor | 1 | Local idiom, next related edit |
| `javascript:S7770` | minor | 2 | Local idiom, next related edit |
| `javascript:S7778` | minor | 5 | Local idiom, next related edit |
| `javascript:S7786` | minor | 2 | Local idiom, next related edit |
| `python:S100` | minor | 139 | Compatibility or public naming |
| `python:S101` | minor | 4 | Compatibility or public naming |
| `python:S1066` | major | 3 | Local idiom, next related edit |
| `python:S108` | major | 1 | Complexity or intentional construct |
| `python:S1110` | major | 12 | Local idiom, next related edit |
| `python:S112` | major | 2 | Local idiom, next related edit |
| `python:S1135` | info | 2 | Platform or loader TODO |
| `python:S117` | minor | 22 | Compatibility or public naming |
| `python:S1172` | major | 9 | Compatibility or public naming |
| `python:S1186` | critical | 6 | Complexity or intentional construct |
| `python:S1192` | critical | 39 | Complexity or intentional construct |
| `python:S125` | major | 1 | Local idiom, next related edit |
| `python:S1542` | major | 74 | Compatibility or public naming |
| `python:S1854` | major | 1 | Local idiom, next related edit |
| `python:S1871` | major | 5 | Local idiom, next related edit |
| `python:S1940` | minor | 22 | Local idiom, next related edit |
| `python:S2737` | minor | 2 | Handled failure |
| `python:S2772` | minor | 2 | Handled failure |
| `python:S3457` | major | 2 | Local idiom, next related edit |
| `python:S3626` | minor | 7 | Local idiom, next related edit |
| `python:S3776` | critical | 137 | Complexity or intentional construct |
| `python:S5713` | minor | 7 | Local idiom, next related edit |
| `python:S5806` | major | 13 | Local idiom, next related edit |
| `python:S5843` | major | 1 | Local idiom, next related edit |
| `python:S6035` | major | 2 | Local idiom, next related edit |
| `python:S6353` | minor | 8 | Local idiom, next related edit |
| `python:S6395` | major | 1 | Local idiom, next related edit |
| `python:S6659` | minor | 6 | Local idiom, next related edit |
| `python:S7492` | minor | 1 | Local idiom, next related edit |
| `python:S7494` | minor | 4 | Local idiom, next related edit |
| `python:S7496` | minor | 7 | Local idiom, next related edit |
| `python:S7498` | minor | 2 | Local idiom, next related edit |
| `python:S7500` | minor | 2 | Local idiom, next related edit |
| `python:S7504` | minor | 6 | Local idiom, next related edit |
| `python:S7508` | minor | 3 | Local idiom, next related edit |
| `python:S7632` | major | 1 | Local idiom, next related edit |
| `python:S8410` | minor | 1 | UI semantics or API documentation |
| `python:S8415` | major | 3 | UI semantics or API documentation |
| `python:S8513` | major | 1 | Local idiom, next related edit |
| `python:S8517` | major | 2 | Local idiom, next related edit |
| `python:S8999` | major | 1 | Test guard or fixture style |
| `python:S9002` | major | 3 | Test guard or fixture style |
| `python:S9073` | major | 7 | Test guard or fixture style |
| `typescript:S2925` | major | 4 | Test guard or fixture style |
| `typescript:S8783` | major | 3 | Test guard or fixture style |

Inventory: 668 issues across 59 rule/severity pairs.
