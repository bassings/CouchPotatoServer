# Jackett indexer errors must not disable the Jackett host

## Observed failure

After production restart, individual Jackett TorrentPotato indexers returned HTTP 400. The shared HTTP client counted those expected indexer refusals against the Jackett hostname. After six, its 15-minute host circuit returned an empty response for the otherwise healthy indexer-list endpoint. The live endpoint recovered after the interval, and direct Jackett calls from the container succeeded. Production logs recorded 11 indexer HTTP 400 warnings and 429 host-disabled notices in the observed window.

## Acceptance criteria

1. HTTP 400 from a `/potato/` indexer on the configured Jackett origin is still reported to the caller but does not count towards disabling the shared Jackett hostname. A subsequent `/torznab/all/api?t=indexers` request on the same host succeeds after more than the normal failure threshold of such refusals.
2. Genuine server or connection failures still count towards the host circuit, and HTTP 429 still disables immediately. Other HTTP 400 responses, including an unrelated provider with a `/potato/` path, retain their current failure accounting.
3. Tests use real HTTP response objects at the transport boundary, fail before the fix, pass after it, and a deliberate mutation proves the new guard is load-bearing.
4. No settings, credentials, production state or unrelated workspace changes are modified by the code fix.
