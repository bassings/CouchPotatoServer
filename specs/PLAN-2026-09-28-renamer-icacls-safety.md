# Windows renamer permission-reset safety

## Goal

Close the documented Windows-only `os.popen` command-construction gap in `MoverMixin.moveFile` (`specs/REMEDIATION-2026-08.md`, T6.5) without changing file transfer or cleanup decisions. Replace the skipped placeholder in `tests/unit/test_renamer_mover.py` with executable coverage on non-Windows CI.

## Acceptance criteria

- [ ] AC-SEC-1: The optional Windows `icacls` reset uses an argument list with no shell and treats the destination as one argument, even when its name contains shell metacharacters.
- [ ] AC-DATA-1: Reset only the moved destination, not same-prefix siblings. An ACL-reset failure remains non-fatal to an otherwise successful move, and no source or destination bytes are lost.
- [ ] AC-QA-1: Tests exercise the Windows branch on non-Windows CI without executing `icacls`, prove the unsafe pre-fix call fails, and cover the disabled/non-Windows paths and failure handling.
- [ ] AC-SEC-2: No command output, private path or credential is newly written to logs or a repository artefact.
- [ ] AC-SIMP-1: No new dependency, public signature, transfer mode or cleanup policy change.
- [ ] AC-REL-1: Focused renamer tests, the full local gate, two independent clean reviews and hosted checks pass; the main checkout remains untouched.

## Boundary

Windows `icacls` cannot run on the macOS/Alpine CI hosts. Tests must verify the exact process arguments and safety behaviour, while a live Windows invocation remains unverified.
