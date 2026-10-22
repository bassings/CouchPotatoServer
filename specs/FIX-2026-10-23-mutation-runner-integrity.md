# Restore truthful mutation checks, 23 October 2026

## Problem and scope

While verifying the dependency refresh's Python 3.15 mutation workflow, the
previous successful nightly run 39717215772 showed its Python runner aborting
with BadTestExecutionCommandsException, followed by a nonexistent `mutmut html`
command. Blanket `|| true` handlers hide both failures. The JS report records
41 killed and 688 surviving mutants, despite the configuration's historical
96% claim. Investigate whether real tests observe activated mutations before
classifying those survivors as coverage gaps.

Fix runner and test-harness integration within the current configured mutation
scope. Keep scores informational, preserve the complete normal application gate
and avoid unrelated application changes or arbitrary score thresholds. Exemplar:
`specs/MAINT-2026-10-23-dependencies.md` and existing mutation guard tests.

## Acceptance criteria

- AC-QA-3: Reproduce the real Python runner failure and identify its actual
  collection/execution cause. Correct the runner/configuration so a targeted
  known mutation executes real covering tests on Python 3.15.1. Preserve the
  configured source mutation scope and justify test selection by coverage.
- AC-QA-4: Prove a real JS mutation in the scoped UI logic is activated and
  rejected by the covering test. Correct shared runner integration failures
  and prove failure/restoration rather than listing individual survivors or
  adding a score gate.
- AC-OPS-2: Infrastructure, collection, execution and report-generation errors
  fail the workflow visibly. Genuine surviving mutants remain informational.
  Use supported installed tool commands and upload actual diagnostic/results
  artefacts. Preserve input injection protection and least permissions.
- AC-SEC-3: Changes do not expose credentials, host paths or data, execute
  untrusted dispatch text as shell code, broaden production dependencies, or
  alter runtime authentication or application state handling.
- AC-SIMP-2: Keep one scoped runner/integration mechanism per actual failure
  class. Prefer supported tool configuration/API, with a deterministic guard
  for any necessary adapter. Avoid speculative abstractions.

## Verification

Use red, green, refactor and real mutation/failure/restore proof. Run the actual
runners on a bounded known mutation while developing, then run configured
mutation suites on the final source and review survivor categories. Do not
mistake a zero workflow exit for proof the capability ran. The final delivery
includes the repository full gate, independent clean-agent review, hosted CI,
actual mutation workflow and the release process already authorised.

## Measured causes

- Python: mutmut's generated sandbox omitted application support files, so
  collection failed while importing `couchpotato.core.logger`. The configured
  deprecated test directory selected repository guards against generated code;
  its documented `runner` setting was inert. Preserve the adapter mutation
  scope and explicitly select its actual covering tests with supported settings.
- JavaScript: a bounded movie-filter run recorded 70 survivors with no tests
  completed for covered mutants. The installed Stryker Vitest runner joins test
  names with spaces, while Vitest 5 matches names joined by ` > `. This matches
  [upstream issue 6210](https://github.com/stryker-mutator/stryker-js/issues/6210).
  A supported command-runner trial with the same source and covering tests
  killed 68 of 71 mutations; the remaining three require ordinary survivor
  triage. Avoid a private dependency patch or a production dependency change.
