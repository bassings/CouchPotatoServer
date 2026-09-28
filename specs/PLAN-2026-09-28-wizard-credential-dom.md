# Verify wizard tracker credential masking in the browser

The existing wizard guard reads template source but does not observe Alpine's
resolved input type. Render the real server-produced wizard markup in a
browser without navigating through wizard steps, then check its live fields.

## Acceptance criteria

- The browser test observes the actual Alpine-rendered private-tracker inputs
  from the wizard template, not a hand-built replacement fixture.
- Every declared tracker credential recognised by the existing static guard
  resolves to `type="password"`; tracker usernames remain `type="text"` as a
  control. This includes future `pass_key`, `user_key`, `cookie` and `auth`
  fields, not just the current `password` and `passkey` names.
- All declared trackers and credential fields are reached, so the test cannot
  pass because the Providers step, disclosure or tracker controls stayed hidden.
- Removing a credential's password declaration in the template makes the
  browser test fail for the intended rendered type; restoring it makes the
  test pass.
- The test uses no real credentials and leaves server settings unchanged.
