# Recover password-change session revocation after a crash

Changing the login password must revoke sessions even if the process stops
after committing the password but before rotating the signing secret. The
current in-memory callback intent cannot survive that boundary. This closes
remediation T21 without changing the existing no-auth/no-secret behaviour.

## Acceptance criteria

- The password and a rotation-pending marker land in the same atomic settings
  save. A failure before the file replacement persists neither and does not
  rotate the signing secret; it also rolls back in-memory changes so an
  unrelated later save cannot commit the failed password attempt. If the file
  was replaced before `save()` raised,
  the running process must instead block old cookies, as the password may
  already be committed. If the value hook cannot freshly prepare both a
  bcrypt hash and the marker, the password save is refused rather than storing
  plaintext or accepting a stale marker from an older attempt. A missing hook
  also refuses, including on a config without a pre-existing `[core]` section.
- A successful non-empty password change rotates the signing secret after
  commit and clears the marker. A repeated callback or ordinary settings save
  does not rotate it again.
- Two concurrent password saves cannot interleave their commit, rotation and
  marker-clear steps. An older callback must never clear a newer committed
  password's revocation intent.
- If the process stops after the settings save but before rotation, startup
  sees the persisted marker and rotates before serving authenticated requests.
  Failure to rotate leaves the marker for a later retry, logs an actionable,
  path-free error and stops startup rather than accepting old sessions.
- If rotation fails while the current process is still serving, the pending
  marker blocks verification of old cookies and prevents a new cookie being
  signed with the old secret. Login remains unavailable until revocation is
  completed; the operator receives an actionable, path-free error.
- A stop after rotation but before clearing the marker may cause one extra
  revocation on restart, never reuse the old secret. Clearing the marker is
  persisted, even when UI metadata marks the internal option read-only, so
  normal restarts do not sign users out repeatedly. A silently refused or
  unpersisted clear is reported as a failure.
- Password clearing, first boot without authentication, and unrelated
  settings writes do not create or rotate a session secret.
- Tests execute the real settings-file and SQLite-property boundaries,
  including the crash window and failure paths. A deliberate removal of
  startup reconciliation makes the crash test fail, then restoration passes.

Existing context: `specs/REMEDIATION-2026-08.md` T21 and
`tests/unit/test_password_rotation_after_commit.py`.
