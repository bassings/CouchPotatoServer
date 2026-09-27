# Renamer failed-move recovery must verify bytes before deleting the source

## Goal

Close the strict expected-failure case in `test_renamer_mover.py`: a failed
cross-device move can leave a destination with the same size but different
bytes, and the current recovery deletes the only good source on size alone.
This data-loss correction takes priority over the `moveFile` complexity smell.

## Acceptance criteria

- [ ] AC-DATA-1: After a failed move, an equal-size destination with different
  content never causes source deletion; both files remain available and the
  move reports failure.
- [ ] AC-DATA-2: A genuinely complete matching copy may still complete the
  move recovery. A shorter partial destination is renamed to a unique,
  non-media quarantine name, freeing the library path without deleting the
  last remaining bytes. At most one recovery copy is retained per destination;
  while it exists, a later transfer is refused before writing any bytes.
  An operator can inspect and clear the artefact before retry. If the source
  vanishes or the destination is a symlink or hardlink to the source, recovery
  must not delete the source.
- [ ] AC-REL-1: Verification reads files in bounded memory and treats a read
  or comparison failure as uncertainty, never as proof that source deletion
  is safe. A quarantine failure retains the destination in place. Recovery
  warnings identify the artefact without logging media titles or file paths.
- [ ] AC-QA-1: Convert the strict expected-failure test into a red regression;
  cover matching, mismatching, read-error, shared-inode, source-disappearance,
  repeated-failure and warning-privacy cases with real files, and prove the
  guards are load-bearing with deliberate failing mutations.
- [ ] AC-SIMP-1: Preserve transfer-mode selection, public signatures and
  permission handling. Do not add a dependency or refactor unrelated branches.
- [ ] AC-DELIVERY-1: Focused tests, the full gate, two fresh independent clean
  local reviews and hosted checks pass; then merge and analyse exact master.

## Boundary

No test can make the comparison and the later unlink one atomic filesystem
operation. The correction must fail closed when either file cannot be read;
the residual concurrent-modification window remains an operational limit.
