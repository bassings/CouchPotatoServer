# Truthful log clearing

## Problem

The server reports success when a log file cannot be cleared, and logs the
private log path with a traceback. Both log screens discard displayed entries
after any resolved fetch, even an HTTP or API failure.

## Acceptance criteria

1. Clearing all existing logs succeeds, including an already empty log set.
   Any file clear failure returns a fixed failure response. The server still
   attempts the remaining files and does not log a private path or traceback.
2. Both log screens retain displayed entries after HTTP, API, malformed JSON
   or network failures and announce a useful error. They clear entries only
   after confirmed success.
3. Phone-width and keyboard browser tests exercise failure and later success
   in both screens.

## Verification

Use red, green, refactor and mutation proof for the server and both clients.
Run the relevant gate and two independent reviews before pushing.
