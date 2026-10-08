# SonarQube delivery and open-finding dispositions, 2026-10-08

## Method

Each result below comes from an analysis of a clean `master` checkout, with
Python and JavaScript coverage uploaded. Issue counts use SonarQube's open,
unresolved issue records, not a count of lines or a filtered dashboard view.
The baseline was 685 code smells at `2b7ed668`; the final analysis is
`775c6b05114820b7496965a988ddffacf99f6a1a`. SonarQube is a reporting
tool for this repository, not a CI or merge gate. An open issue remains open
when the suggested edit has no demonstrated benefit or would add risk.

The earlier per-site investigations in
[the assessed-slices plan](PLAN-2026-09-07-sonarqube-slices.md) and
[its follow-up](PLAN-2026-09-07-post-sonarqube-followups.md) remain the detailed
evidence for inherited findings. This report records what the October pass
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
blocks selection; its phone-width tests exercise HTTP and malformed-response
failures. The log screens show a warning and retain entries, and the inspected
movie-detail and profile paths notify the operator or roll back optimistic
state. The Settings restart catch now retains its reminder and reports that
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

The two informational `python:S1135` comments ask for Windows path checks in
the directory browser. The documented production image is Alpine; keep those
questions visible until Windows support is tested, rather than deleting the
comments to clear a scanner count.

### Local idioms

The rest of the inventory consists of local simplification, naming, regex,
constructor and syntax suggestions. They are left open because a standalone
edit would touch working production or guard code without a demonstrated
failure. In particular, replacing `[0-9]` with `\d` under `python:S6353`
would widen matching to Unicode digits, so that is not an equivalent edit.
The September plans record the prior per-site assessments of these families.
Change one in the course of related work when its behaviour and callers can
be verified; do not run a mechanical sweep through scanner, renamer, database
or test-guard code.

## Final measured state

The clean `master` checkout and SonarQube scanner both identified revision
`775c6b05114820b7496965a988ddffacf99f6a1a`. Coverage reports were
uploaded and coverage measured **64.8%**, so this is not a missing-coverage
result. The open issue response held **668 code smells** across 59 rules,
with **zero bugs, vulnerabilities and security hotspots**. Compared with
the 685-smell baseline, the net change is 17 fewer open records. The issue-key
trail across the first five code PRs accounts for 23 closed records and five new
records; #512 changed neither set, and #513 added one `typescript:S2925`
record without closing an old one. No issue was suppressed.

The informational quality gate is **red for one new violation**, the
`typescript:S2925` observation window described above. The previous
new-code duplication failure is no longer present at this revision. CI,
independent local reviews and cloud reviews passed before merge. The
automatic beta build passed under the authorised release channel; production
was not promoted or deployed.

## Complete open-rule inventory

The disposition names correspond to the assessment sections above.
"Local idiom, next related edit" includes the regex and syntax cautions
called out there; it is not a recommendation to apply every suggested edit.
This table is generated from the same open-issue response as the final totals,
so its counts reconcile with that revision rather than an earlier snapshot.

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
| `python:S1135` | info | 2 | Platform TODO |
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
