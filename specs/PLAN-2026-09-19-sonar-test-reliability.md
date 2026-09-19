# Sonar test reliability findings

## Goal

Resolve the remaining critical Python and TypeScript test-reliability findings
without changing application behavior or weakening failure detection.

## Acceptance criteria

- [x] AC-QA-1: The concurrent `isRunning()` test records reader exceptions and
  non-list results through the shared error channel; its owner thread remains
  the pytest failure boundary.
- [x] AC-QA-2: The test signals all workers to stop and fails if any worker is
  still alive after the bounded joins.
- [x] AC-QA-3: Deliberately returning a tuple from read-mode `isRunning()` makes
  the focused concurrency test fail through the recorded-error path; preventing
  shutdown makes it fail through the liveness assertion; both restore green.
- [x] AC-QA-4: `categoryToForm` documents its intentional ID contract as
  `string | number`; numeric zero remains an edit ID while empty, null, and
  undefined states remain new-category states.
- [x] AC-QA-5: The focused Python and Vitest suites, repository fast gate, and
  required independent reviews are clean.
- [x] AC-REL-1: Exact-master Sonar closes issue
  `bf52926a-676a-4d51-9a9d-164d7e059222` (`python:S5779`) as fixed.
- [x] AC-REL-2: Exact-master Sonar closes issue
  `0ffb6f0c-2ee4-487d-a163-4a06888b46f6` (`typescript:S5845`) as fixed.
- [x] AC-SEC-1: No production lock behavior, exception suppression, logging,
  authorization, persistence, or network behavior changes.
- [x] AC-SIMP-1: Scope is limited to one concurrency test, one JSDoc union, and
  this evidence record; no new helper, dependency, or static-check framework.

## TDD note

Both runtime behaviors were already correct at baseline: the focused Python
test and all 39 category-editor tests passed. The red evidence is the two exact
open Sonar findings. Load-bearing behavioral evidence is supplied by deliberate
mutations rather than claiming a naturally failing runtime test.
