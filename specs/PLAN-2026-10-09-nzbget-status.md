# NZBGet status estimate, 2026-10-09

## Finding

The critical `python:S3776` issue in `NZBGet.getAllDownloadStatus` covers a
status path that currently leaves `timeleft` as `-1` for an active download.
The code reads `DownloadRate` from a `listgroups` item, but NZBGet documents
that field on `status`, in bytes per second. It also uses bitwise XOR (`^`)
where conversion from MiB to bytes needs exponentiation. The broad local
exception handler hides both errors. The relevant API references are
[status](https://nzbget.com/documentation/api/status/) and
[listgroups](https://nzbget.com/documentation/api/listgroups/).

## Acceptance criteria

1. An active, unpaused group with 10 MiB remaining and a 1 MiB/s status rate
   reports `0:00:10`; a group response need not include `DownloadRate`.
   Both the legacy `DownloadRate` and the documented `DownloadRateLo/Hi`
   response shape work, including a nonzero high word.
2. Paused, inactive and zero-rate groups retain the unknown `-1` estimate.
   The deprecated `Download2Paused` field may be absent.
3. Queue and history status records keep their existing mapping. Focused
   tests fail before the fix, pass after it and fail under a deliberate
   conversion mutation.
4. Complete the local gate, independent review, PR, CI, merge and clean-master
   SonarQube confirmation after PR #517 merges. No production deployment.

## Tasks

- [x] S1 Add failing API-shaped status and boundary tests.
- [x] S2 Fix the estimate and pass local verification.
- [x] S3 Complete review, PR, CI, merge and SonarQube confirmation. — state: merged

## Conductor log

- 2026-10-09: Inspected the critical NZBGet status function while PR #517 entered CI. The official API documents group remaining size in MiB and global download rate in bytes per second; the present code reads rate from the wrong response and uses XOR, then swallows the resulting errors.
- 2026-10-09: The API-shaped active-download test failed with `-1` before the fix, while inactive, paused and zero-rate boundaries passed. Reading the global status rate and converting MiB to bytes made all eight focused status cases pass. Extracted group, post-queue and history mapping into small methods to address the critical complexity finding; 41 focused status, connection and release-lookup tests pass. A deliberate XOR mutation made the active estimate test fail, then restoration passed.
- 2026-10-09: The full local gate passed: 4,831 Python unit, 42 integration, 311 UI unit, 225 desktop, 24 phone-width and 126 accessibility browser tests. Working-tree secret scan passed. Two independent reviews found no material defect. PR #517 merged and its exact-master scan is running; this branch will be rebased onto that merge before delivery.
- 2026-10-09: PR #517's exact-master scan closed seven critical issue keys with no new keys, leaving this function's `python:S3776` open. The status API marks `DownloadRate` deprecated in favour of split low/high fields. Two new tests failed when the legacy field was absent; the estimator now reconstructs the 64-bit rate and all 43 focused tests pass. Changing the high-word shift to zero made the high-rate test fail, then restoration passed. The full gate and final local review will be repeated after this compatibility addition.
- 2026-10-09: The revised full gate passed: 4,833 Python unit, 42 integration, 311 UI unit, 225 desktop, 24 phone-width and 126 accessibility browser tests. Two fresh independent reviews of the code and plan diffs found no material issue. PR #517's beta and post-merge CI passed; this branch is ready for its final pre-push review after the task status update.
- 2026-10-09: PR #518 merged as `880b5398` after CI and cloud reviews passed. Its exact clean-master SonarQube analysis closed the targeted `python:S3776` issue with no new issue keys: 661 to 660 open smells, 184 to 183 critical; coverage 65.2%, with zero bugs, vulnerabilities or hotspots. Post-merge CI, CodeQL and the automatic beta build passed. No production deployment occurred.
