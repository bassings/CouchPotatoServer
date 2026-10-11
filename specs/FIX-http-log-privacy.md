# HTTP client log privacy

Issue: [#543](https://github.com/bassings/CouchPotatoServer/issues/543).

## Problem

`HttpClient.request` and the Jackett provider log full outbound URLs when a
request starts and when it fails. The production log for an indexer HTTP 500
included an internal service address and a film search term. The shared
`PrivacyFilter` masked a credential query value but cannot know which
arbitrary query fields contain personal data. The provider also forwards
request exception text into Jackett test and sync API errors.

## Acceptance criteria

1. Request-start, Jackett HTTP 400, other HTTP failure, transport failure,
   cache fallback and circuit-open logs omit the outbound host, path, query
   and exception text while retaining the method, HTTP status or failure
   class needed to diagnose them.
2. The actual configured handler filter and formatter emit none of a
   synthetic internal host, film title or passkey on those paths.
3. The request itself and its failure counting remain unchanged. An indexer
   HTTP 500 still lets the provider try its next configured indexer.
4. The regression tests fail when a full URL is deliberately restored to
   the request-start, failure or cache-fallback log.
5. Jackett listing, search errors and test/sync failure logs omit the private
   host, path, query and exception text. A failed Jackett API request returns
   a useful error class without disclosing the URL or API key.
6. The provider settings test reports each indexer by its configured position
   and safe status, including when earlier rows are disabled, without
   forwarding the hostname, remote error text or exception text into its API
   response.
