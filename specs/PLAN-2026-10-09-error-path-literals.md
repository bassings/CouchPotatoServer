# SonarQube error-path and seed output literals, 2026-10-09

## Finding

The exact clean-master scan at `049f6edd` leaves five critical
`python:S1192` repeated literals in low-coverage paths: the E2E seeder's
"already present" result, Synology and Kodi response logs, and profile and
category failure logs. Each repeated value is stable output text, but a
constant extraction would put uncovered lines into SonarQube's new-code
coverage calculation. Behaviour tests for the actual output and failure paths
are needed to keep the reporting gate green.

## Acceptance criteria

1. Share the five exact values within their original modules. Preserve all
   output text, log level, log argument order and external request behaviour.
2. Add focused characterisation tests for relevant output and failure paths
   before the extraction. Prove the tests fail on deliberate wrong-value
   mutations and pass after restoration. Inlining the constants must produce
   syntax trees identical to the original modules.
3. A fresh full-suite coverage report covers at least 80% of changed
   executable production lines. Focused checks, the full repository gate and
   two independent local reviews pass before push.
4. PR, CI and cloud review pass. An exact clean-master SonarQube scan closes
   the five targeted keys, introduces no new keys and passes the reporting
   quality gate. No production deployment.

## Tasks

- [x] E1 Characterise the five output and failure paths with load-bearing tests; state: completed
- [x] E2 Extract exact literals and verify syntax trees and coverage; state: completed
- [ ] E3 Complete gates, reviews, PR, merge and exact-master scan; state: building

## Conductor log

- 2026-10-09: Selected the five remaining low-coverage critical Python
  repeated literals after the seven covered values and two renamer marker
  values were split into safer batches. These five concern output and error
  handling rather than normal media movement.
- 2026-10-09: Baseline characterisation passed before extraction. After
  extraction, focused tests and Ruff passed; inlining the five constants
  produced syntax trees identical to the original files. Five deliberate
  wrong-value mutations each failed the relevant assertion and passed after
  restoration. Fresh full-suite coverage passed 4,929 Python tests and
  covered 22 of 24 changed executable production lines (91.7%).
