# Explain six intentionally empty hooks, 2026-10-09

## Finding

The exact clean-master scan at `049f6edd` reports six critical
`python:S1186` issues in provider, updater and directory-browser hook methods.
Each method intentionally returns `None` through `pass`, but its body does not
explain that contract. The SonarQube issue messages request a nested comment
or an implementation.

## Acceptance criteria

1. Explain the intent inside each of the six methods, based on verified call
   sites and concrete overrides. Preserve each signature and runtime behaviour.
2. Confirm that removing the six comments leaves the original production
   syntax trees exactly unchanged. Focused checks and the full repository gate
   pass, followed by two independent local reviews before push.
3. PR, CI and cloud review pass. An exact clean-master SonarQube scan closes
   the six targeted keys, introduces no new keys and passes the reporting
   quality gate. No production deployment.

## Tasks

- [x] H1 Verify hook contracts and explain the six empty bodies; state: completed
- [x] H2 Run gates and independent reviews; state: completed
- [ ] H3 PR, merge and exact-master scan; state: queued

## Conductor log

- 2026-10-09: Verified that each BaseUpdater hook is overridden by every
  concrete updater, trailer search is implemented by its concrete provider,
  provider URL construction is supplied by the providers that need it, and
  FileBrowser.getFiles has no callers in the repository.
- 2026-10-09: Added six nested comments and confirmed the four changed
  production modules have syntax trees identical to the original modules.
- 2026-10-09: `make verify-fast` and the full `make verify` gate passed,
  including 227 desktop, 24 phone-width and 126 accessibility browser tests.
  Two independent local reviews found no actionable issue.
