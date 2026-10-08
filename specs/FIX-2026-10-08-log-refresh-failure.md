# Visible log refresh failures

## Problem

If the first `logging.partial` request fails, both log screens can render
"No log entries found" without telling the operator that the list was not
loaded. A later failed refresh retains old entries but gives no visible
reason. Overlapping refresh responses can also update the screen out of
order.

## Acceptance criteria

1. Both log screens distinguish a valid empty response from HTTP, API,
   malformed JSON, network and invalid-shape failures. They announce a fixed,
   useful error on failure and do not show the empty state as a verified
   result.
2. A failed refresh retains already displayed entries. Keyboard users can
   activate Refresh to retry; a successful refresh clears the load warning.
3. A response or failure from an older refresh cannot overwrite a newer
   result. Each screen starts one initial load. The existing clear/refresh
   ordering and partial-clear warning remain correct.
4. Phone-width browser tests cover both screens, failure modes, retry and
   request ordering. Focused checks are load-bearing by mutation.

## Verification

Use red, green, refactor for changed behaviour. Run focused checks, the local
gate and two independent code reviews before pushing. Follow CI and cloud
review through merge, then confirm the exact merged revision in SonarQube.
