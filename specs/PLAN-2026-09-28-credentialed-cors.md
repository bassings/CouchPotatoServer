# Credentialled CORS origin guard

## Risk

The server enables credentialled CORS. When `cors_origins` includes `*`, the
installed middleware reflects an arbitrary request origin and permits browser
credentials. A mixed list containing `*` is equally permissive.

## Acceptance criteria

1. An unset origin list continues to emit no cross-origin permission.
2. A configured `*`, alone or in a mixed list, never grants a credentialled
   request or preflight from an unlisted origin.
3. Explicitly listed origins continue to work in a mixed list, including
   credentialled requests and preflight.
4. Tests use the real application and middleware and fail if wildcard filtering
   is removed.
5. No configured origin or private network detail is logged by this guard.

Keep the change to origin parsing and its integration tests. This does not
alter the existing route-level cross-origin protection or authentication.
