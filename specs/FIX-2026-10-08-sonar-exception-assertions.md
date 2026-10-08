# Specific exception assertions for migration and release-name tests

## Problem

Three `pytest.raises(Exception)` assertions can pass when an unrelated error
replaces the expected failure. Two guard vendored database deletion behaviour
used by migration tests; the third guards release-name parsing.

## Acceptance criteria

1. The two deleted-record tests require CodernityDB's `RecordDeleted` error.
2. The release-name equivalence test requires `ValueError` when no bracketed
   group exists.
3. Each narrower assertion is shown to fail when its call raises an unrelated
   exception. Focused and repository checks remain green.
