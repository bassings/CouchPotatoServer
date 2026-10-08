# Truthful Settings restart feedback

## Problem

The Settings restart control reports success, hides the restart reminder and
schedules a reload whenever `fetch` resolves. An HTTP failure or an API
refusal also resolves `fetch`, so an operator can be told the app is restarting
when it is not. The `app.restart` handler returns the JSON string
`"restarting"` on acceptance, and can return `false` when shutdown is already
under way.

## Acceptance criteria

1. Settings reports "Restarting…", hides the restart reminder and schedules
   reload only after an HTTP-successful response with the exact accepted
   restart result.
2. An HTTP error, API refusal, malformed or unexpected response, or network
   failure leaves the reminder visible, shows an announced failure and does not
   schedule reload. The message is fixed and does not expose a response body.
3. Phone-width browser tests exercise the real Settings control and the
   production response shapes, including keyboard activation and retry. A
   second activation while a request is pending sends no second request and
   the control announces its busy state without losing keyboard focus.
4. The focused check fails before the fix and under a deliberate mutation,
   then passes after restoration. Run the full local gate and two independent
   reviews before pushing; follow PR checks and review through merge, then
   re-analyse exact `master` in SonarQube.
