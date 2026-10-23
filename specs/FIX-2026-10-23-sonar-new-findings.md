# New SonarQube findings, 23 October 2026

## Scope

Resolve the 23 records first observed by the exact-master analysis of `7adb683fca0d4f1a99faaa92b00030d89bbdc422`, using focused corrections or verified dispositions. Preserve the shared checkout. Production promotion and deployment are excluded. This follows the delivery pattern in `specs/PLAN-2026-09-28-settings-value-boundary.md`.

## Acceptance criteria

- AC-SEC-1: Cache errors and installation failures do not log private request URLs or error payloads; API requests remain outside service-worker caches.
- AC-QA-1: Cache writes remain attached to the fetch event lifetime, and storage failures do not replace successful online responses. Unit tests fail before the fix and under deliberate regressions.
- AC-QA-2: Installation and activation await their asynchronous work; navigation retains its cache and offline fallbacks, including unavailable storage.
- AC-A11Y-1: Provider disclosure works with native keyboard activation, reports expanded state, keeps its enable switch separate, and remains usable in both themes and at phone width.
- AC-A11Y-2: The mobile menu closes with Escape and retains native navigation semantics and pointer dismissal.
- AC-DATA-1: Prefix/suffix checks and legacy migration iteration preserve data selection, ordering and destructive-operation boundaries.
- AC-OPS-1: Lighthouse runs remain sequential so measurements do not compete for one browser. Report writes finish before progressing, and failure cleanup is retained.
- AC-ARCH-1: No dependency or framework is introduced; service-worker response delivery remains independent of optional cache persistence.
- AC-PROD-1: Image-load failure fallback remains intact; the image error event is not misrepresented as a user interaction.
- AC-DESIGN-1: Provider controls retain existing card hierarchy, visible focus and viewport containment.
- AC-VERIFY-1: All 23 keys have a source-backed disposition; local verification, independent review, CI and cloud review pass before merge. A fresh exact-master analysis confirms corrections and reports any replacement findings.
- AC-SIMP-1: Retain serial benchmark loops rather than disguising necessary sequential work to satisfy a scanner.

## Finding inventory

| Issue key | Location | Rule | Intended disposition |
|---|---|---|
| `0aad248d-907b-4fbe-8060-8e995673a90b` | `couchpotato/ui/templates/partials/movie_cards.html:51` | `Web:S6847` | False positive: image load-error fallback, backed by existing exact-source and browser tests |
| `e72a7239-d7ec-4d92-93de-a90c90b9750c` | `tests/unit/test_http_client_log_privacy.py:112` | `python:S5778` | Correct source and verify |
| `51788e2b-91f6-4fdb-b57c-188ec35d8245` | `tests/unit/test_providers.py:1013` | `python:S9073` | Correct source and verify |
| `ea5ab732-3301-4382-aa8e-3c997e3d8cb9` | `couchpotato/core/http_client.py:318` | `python:S1110` | Correct source and verify |
| `cdf8bac4-ace4-439d-bb90-2d24f109b08f` | `scripts/lighthouse-policy.mjs:161` | `javascript:S9382` | Accept intentional serial benchmark/report work, backed by sequencing tests |
| `4a2894e0-086d-45a1-8086-406c66cc3d8f` | `scripts/lighthouse-policy.mjs:185` | `javascript:S9382` | Accept intentional serial benchmark/report work, backed by sequencing tests |
| `7eef11a3-e8bf-40f2-be76-fb2b52a01126` | `scripts/lighthouse-policy.mjs:187` | `javascript:S9382` | Accept intentional serial benchmark/report work, backed by sequencing tests |
| `69cc353c-c22c-4730-8e97-9c09584ae07c` | `scripts/migrate_codernity_to_sqlite.py:149` | `python:S9409` | Correct source and verify |
| `98a6f98d-415e-4e7f-aa29-8245a7707422` | `couchpotato/static/sw.js:112` | `javascript:S9381` | Correct source and verify |
| `f97a991c-68e0-493c-99e3-8d10c8ad4b22` | `couchpotato/static/sw.js:30` | `javascript:S9381` | Correct source and verify |
| `c150c92b-7ed8-4ec4-87c8-9c6332f71de3` | `couchpotato/static/sw.js:79` | `javascript:S9381` | Correct source and verify |
| `d60deff8-f04e-4c85-b994-fb0b14c01647` | `couchpotato/static/sw.js:83` | `javascript:S9383` | Correct source and verify |
| `f7d1ff0a-f110-41b3-a98d-729b0218fd95` | `couchpotato/static/sw.js:83` | `javascript:S9381` | Correct source and verify |
| `36e690ad-e1f2-4d1f-914e-55c95d9bc839` | `couchpotato/static/sw.js:84` | `javascript:S9383` | Correct source and verify |
| `17f73561-dcb1-4525-bc06-9f95c965488b` | `couchpotato/static/sw.js:101` | `javascript:S9381` | Correct source and verify |
| `3901e9de-217d-4c50-9c91-186b4343ad92` | `couchpotato/static/sw.js:101` | `javascript:S9383` | Correct source and verify |
| `4bbd07e4-8de5-446e-9023-c76a97f7e188` | `couchpotato/static/sw.js:102` | `javascript:S9383` | Correct source and verify |
| `39657448-d807-44b9-beca-ffbe022cd81b` | `couchpotato/static/sw.js:109` | `javascript:S9381` | Correct source and verify |
| `4c598098-ad7a-4b02-9de9-75ab35dd732f` | `couchpotato/ui/templates/partials/settings/provider_card.html:7` | `Web:MouseEventWithoutKeyboardEquivalentCheck` | Correct source and verify |
| `374f619a-22fc-4ec5-b2cb-cd3b3b9f93ad` | `couchpotato/ui/templates/base.html:550` | `Web:MouseEventWithoutKeyboardEquivalentCheck` | Correct source and verify |
| `9a04e9b7-af30-4c6e-9f5a-3ededd268daf` | `couchpotato/core/database.py:395` | `python:S6659` | Correct source and verify |
| `cfc9ca36-b980-4f58-b86d-ba93c36f92b0` | `couchpotato/core/media/_base/media/index.py:142` | `python:S6659` | Correct source and verify |
| `8d6a016e-ef18-4125-b1a1-7fe78db77f46` | `couchpotato/core/media/_base/media/index.py:172` | `python:S6659` | Correct source and verify |

## Delivery notes

- The four intentional or false-positive dispositions require explicit authorisation before using the SonarQube administrator credential. No rule or gate will be disabled.
- The shared checkout contains a separate valuable movie-edit fix. Its four Python contracts all fail on current master for the intended conflict, missing-ID and false-success behaviours. Its delivery scope is being clarified with Scott.

## Measured local evidence

- Service-worker tests: five behavioural failures and one unhandled rejection on the original source; all 15 pass after correction.
- Provider disclosure and mobile Escape contracts fail before implementation. Five final browser cases pass across both themes and 393/1280 px widths, including focus return from inside navigation.
- Existing poster browser contracts pass for successful and failed image loads. Its exact source inventory already records the same `Web:S6847` site as previously adjudicated issue `fe776ece-7d5f-4f9b-a70f-16871444e5bb`; the newly reported key is a duplicate source warning.
- Focused Python checks: 185 passed, including all integration tests. Focused service-worker and Lighthouse checks: 48 passed.
- Deliberate removal of fetch lifetime registration, awaiting cache writes, report write ordering, single-audit execution, image fallback handling, disclosure action and Escape action each fails the relevant tests. Every source is restored byte-identically and the focused checks pass again.
- The first cache-write mutation survived an insufficient microtask-only wait. The lifetime contract now yields a complete event-loop turn before checking premature completion; repeating that mutation fails both static and navigation cases.
- `make mutation-changed BASE=origin/master` confirms these changed paths are outside the configured mutmut/Stryker scopes. Explicit probes above cover the new behaviour without widening or weakening those scopes.
- Ruff, test-trap and template conformance checks pass. Full gate and independent review are the next delivery steps.

- Independent security review found that JSON serialisation hid `Error.message` in two privacy assertions. Both now use one console-formatting helper. Separate raw-error logging mutations fail, and restoration passes all 15 worker tests.
