# REG-003: P0 Security + Observability Hardening

Five independent findings from a code review. Each is fixed with the smallest
correct diff and a TDD regression test.

## 1. Global TLS validation disabled (CRITICAL)

### Problem
`couchpotato/core/_base/_core.py` (in `Core.__init__`) globally monkeypatches
the stdlib default HTTPS context:

```python
try:
    if sys.version_info >= (2, 7, 9):
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    log.debug('Failed setting default ssl context: %s', traceback.format_exc())
```

This disables certificate validation (no hostname check, no CA verification)
for **every** `urllib`/`http.client`-based HTTPS call made anywhere in the
process for the lifetime of the app — not just CouchPotato's own requests.
It's a leftover Python-2.7.9 workaround (the version guard is dead code on
Python 3.10+, which is the supported floor per `CLAUDE.md`). A
man-in-the-middle can intercept any HTTPS call CouchPotato or a library it
loads makes (provider APIs, notifications, update checks, etc.) and the app
will not notice.

Grepped the tree for anything relying on unverified requests specifically:
no call site depends on this monkeypatch. The bundled `HttpClient` /
`requests`-based helpers use `requests`, which does its own verification
independent of the stdlib default context; nothing exercises
`urllib.request.urlopen` against a self-signed/legacy host that needed this
patch.

### Fix
Delete the monkeypatch entirely (`couchpotato/core/_base/_core.py`). No
call site needs an unverified context, so there is nothing to scope down.

### Test
`tests/unit/test_core_ssl_context.py` — after importing
`couchpotato.core._base._core`, `ssl._create_default_https_context()` must
have `verify_mode == ssl.CERT_REQUIRED` and `check_hostname is True` (i.e. the
stdlib default, unmodified).

## 2. Symlink-following scanner (CRITICAL)

### Problem
`couchpotato/core/plugins/scanner/folder_scanner.py` (`FolderScannerMixin.scan`)
walked the release folder with `os.walk(folder, followlinks=True)`. A
malicious/corrupt release containing a symlink to a large host file (e.g.
`/etc/shadow`, a Docker socket, another user's media library) gets treated as
a normal scannable movie file. Once picked up, the renamer will move/rename/
delete the file the symlink points at — i.e. the *real* target outside the
scanned folder — not just the symlink itself.

**Important finding during TDD:** `followlinks` only controls whether
`os.walk` *recurses into symlinked directories*; it has no effect on whether
a symlink to a *regular file* appears in `os.walk`'s `files` list — that
happens regardless of `followlinks`. Verified locally:

```python
os.symlink(secret_file, os.path.join(scan_dir, 'link.mkv'))
# os.walk(scan_dir, followlinks=True)  -> lists link.mkv
# os.walk(scan_dir, followlinks=False) -> lists link.mkv  (same!)
```

So "just drop `followlinks=True`" alone does **not** close the hole for the
attack as described (a symlink to a file, not a directory) — it only reduces
the *separate* risk of recursing into a symlinked subdirectory that points
outside the scanned tree.

### Fix (chosen: realpath containment, not just dropping `followlinks`)
Kept `followlinks=True` (so folder-level symlinked media libraries — a
common home-media-server pattern — keep working), but added a containment
check: for every file yielded by the walk, resolve its real path with
`os.path.realpath()` and skip it if that real path does not resolve inside
`os.path.realpath(folder)`. This closes the actual vulnerability (a symlink —
file or directory — that escapes the scanned folder is never handed to the
rest of the scan/rename pipeline) while still supporting the case where the
*whole* scanned folder itself is a symlink/mountpoint (its realpath is
computed once and used as the containment boundary, so everything genuinely
inside it still passes).

Trade-off documented: a subdirectory *inside* the scanned folder that is
itself a symlink to a location outside the scanned tree is now excluded from
scanning. Given the CRITICAL severity (arbitrary host file corruption via
rename/delete), this is the correct default; anyone with that specific setup
should point the library entry directly at the storage location instead of
symlinking a subtree in.

### Test
`tests/unit/test_scanner_modules.py::TestSymlinkContainment` — a symlink
created inside a `tmp_path` scan folder pointing at a file created *outside*
that folder is not returned as a scannable file by `scan()`.

### PR #151 review follow-up (MEDIUM): prune escaping dirs before recursion
Cloud review noted that per-file containment runs *after*
`os.walk(followlinks=True)` has already recursed into an escaping symlinked
*subdirectory* — so the escape target (an NFS mount, `/proc`, another
library) still gets fully walked at scan time (perf/DoS), and, since
`followlinks=True` has no loop detection, a dir-symlink chain could be
followed to the OS symlink limit. Fix: prune in place inside the walk loop —
`dirs[:] = [d for d in dirs if self._isWithinFolder(os.path.join(root, d),
real_folder)]` — so os.walk never descends into an escaping symlinked dir.
The "whole scanned folder is itself a symlink" case still works (its own
realpath is the containment boundary); the per-file check is kept as
belt-and-braces for *file* symlinks. Tests:
`test_escaping_symlinked_dir_is_not_descended_into` (spies on `os.walk` and
asserts the escape target is never yielded as a visited root — the stronger
claim per-file filtering alone does not provide) and
`test_self_looping_symlink_terminates`.

> Note: this closes the *scan-time* symlink exposure. A residual
> time-of-check/time-of-use gap at *move/rename* time (a path validated here
> could be swapped for a symlink before the renamer acts on it) is out of
> scope for this package and routed to the renamer package by the
> orchestrator.

## 3. API key leaked to logs (HIGH)

### Problem
`couchpotato/runner.py` calls `uvicorn.run(...)` without `access_log=False`.
CouchPotato's API auth is URL-based (`api_key` embedded in the request path,
per `CLAUDE.md`'s "Known Technical Debt"), so uvicorn's default access log
writes every request path — including the api_key — to stdout, which lands
in `docker logs` in the shipped container.

### Fix
Extracted the uvicorn invocation into a small, directly-testable
`_run_uvicorn(application, config, debug)` helper in `couchpotato/runner.py`
and added `access_log=False` to the `uvicorn.run(...)` call. This keeps the
change minimal while making it possible to unit test the server invocation
without standing up the full `runCouchPotato` startup pipeline (DB, plugin
loader, etc.), which has no existing test seam.

### Test
`tests/unit/test_runner_uvicorn.py` — patches `uvicorn.run`, calls
`_run_uvicorn(...)`, and asserts it was called with `access_log=False`.

### Trade-off / follow-up (noted, not implemented here)
`access_log=False` disables uvicorn's request access log **entirely** — not
just the api_key portion of it. That removes the per-request line
(method/path/status/latency) that can be useful for debugging and basic
traffic visibility. The correct long-term fix is redacted request logging
(a custom access-log formatter / logging middleware that strips the
`api_key` path segment and query param but still emits the request line, or
moving API auth off the URL entirely). That is deliberately **out of scope**
for this P0 hardening pass and is tracked as a **separate follow-up** — the
immediate priority is stopping the secret from leaking, and turning the
access log off is the smallest change that does so. Do not re-enable
`access_log` without the redaction layer in place.

## 4. `info2` log level invisible in production (HIGH)

### Problem
`couchpotato/core/logger.py` defines `INFO2 = 19`, which is *below*
`logging.INFO` (20). The root logger defaults to `INFO` in
non-debug/production mode (`setup_logging(debug=False)`), so any
`log.info2(...)` call — used for release-rejection reasons and provider
circuit-breaker trips — is silently dropped by the standard level filter
before it ever reaches a handler.

### Fix
Changed `INFO2` from `19` to `21` (between `INFO`=20 and `WARNING`=30), so it
is visible at the default production level. Kept
`logging.addLevelName(INFO2, 'INFO')` as-is (unchanged registration behavior
— the display name stays `INFO` intentionally, matching the pre-existing
`ColorFormatter` mapping which already keyed off the `INFO2` constant rather
than the literal number, so no other code needed to change).

Checked for any code that relies on `info2` being *below* `info` (e.g. a
level comparison or a "DEBUG < INFO2 < INFO" invariant) — found none;
`ColorFormatter.COLORS` and the level-name registration both reference the
`INFO2` symbol, not the literal `19`, so they pick up the new value
automatically.

### Test
`tests/unit/test_logging.py::TestSetupLogging::test_info2_visible_in_production_level`
— configures logging via `setup_logging(debug=False)` (production level) and
asserts a `log.info2(...)` record is emitted to a handler (previously
swallowed at level 19 < 20).

## 5. `PrivacyFilter` never applied (HIGH)

### Problem
`couchpotato/core/logger.py::setup_logging` attaches `PrivacyFilter` to the
**root logger** via `logger.addFilter(...)`. Per stdlib `logging` semantics,
filters attached to a `Logger` (as opposed to a `Handler`) only run for
records *originated* by that logger — they are **not** re-applied to records
that arrive via propagation from a child logger. `CPLog` always logs through
a named child logger (`logging.getLogger(context)`), so in practice every
record CouchPotato ever logs propagates up to the root logger and is emitted
by the root's handlers *without* ever passing through the root logger's own
filter list. Net effect: API keys/passkeys embedded in logged URLs are never
redacted in production.

### Fix
Moved the `PrivacyFilter` from the root **logger** to each root **handler**
(`console_handler` and `file_handler`) in `setup_logging`. Handler-level
filters run for every record the handler emits regardless of which logger in
the hierarchy the record originated from, which is what's needed here.

### Test
`tests/unit/test_logging.py::TestSetupLogging::test_privacy_filter_applied_via_child_logger`
— configures logging via `setup_logging`, logs through a *named child*
`CPLog` logger with an `api_key=SECRET` message, and asserts the secret does
not appear in the handler's emitted output (captured via a `StringIO`-backed
`StreamHandler` swapped in for the test).

## 6. Py2 `im_self` remnant disabled graceful shutdown (MED, reliability)

### Problem
`couchpotato/core/event.py::addEvent`'s `createHandle` closure detects
whether an event handler is a bound method (so it can call
`parent.beforeCall(handler)` / `parent.afterCall(handler)` on the owning
`Plugin` instance) via `hasattr(handler, 'im_self')`. `im_self` was the
Python 2 attribute name for a bound method's instance; Python 3 uses
`__self__`. `hasattr(handler, 'im_self')` is therefore always `False` on
Python 3, so `beforeCall`/`afterCall` never fire for any plugin event
handler. This means `Plugin._running` (populated by `beforeCall` via
`isRunning(...)`) never gets entries, so
`Core.initShutdown`'s wait loop —
`fireEvent('plugin.running', merge=True)` — always reports nothing running
and shutdown/restart never actually waits for in-flight plugin work to
finish before tearing down.

### Fix
Changed `hasattr(handler, 'im_self')` to `hasattr(handler, '__self__')` in
`couchpotato/core/event.py`.

### Review follow-up (BLOCKER found in local review): isRunning self-count
Re-enabling `beforeCall`/`afterCall` surfaced a latent self-referential bug.
Every `Plugin` registers `addEvent('plugin.running', self.isRunning)` in
`registerPlugin`. When `Core.initShutdown` fires `plugin.running`, the
call-tracking wrapper would record the `isRunning` bookkeeping handler
itself as "running" (append `"<Class>.isRunning"` to `_running`) and then
`isRunning()` returns a snapshot that includes that just-added entry.
Result: `fireEvent('plugin.running', merge=True)` is **never** empty, none
of the reported `*.isRunning` entries are in `Core.ignore_restart`, so the
shutdown/restart wait loop always burns its hard 30s timeout — a mandatory
30s hang on every UI restart, auto-update restart, and post-migration
restart (where before the `im_self` fix it was an instant no-op).

Fix: exempt query/bookkeeping handlers from call-tracking. Added a
`Plugin._call_tracking_exempt = frozenset({'isRunning'})` set and a guard in
`Plugin.beforeCall`/`afterCall` that returns early when
`handler.__name__` is in it. Placed in `base.py` (not `event.py`) because
the exemption is *Plugin domain knowledge* — the generic event dispatcher
shouldn't know that `isRunning` is special — and expressed as a named set
rather than an inline magic string so future exempt handlers are added in
one obvious place. Grepped for other event handlers that read `_running`:
`isRunning` is the only reader (the only method that both queries `_running`
and is registered as an event handler), so a targeted exemption is
sufficient; no other handler has the self-counting problem.

### Test
- `tests/unit/test_event_system.py::TestBeforeAfterCall` — registers a bound
  method (`work`, a normal handler) of a `Plugin` instance as an event
  handler, observes state *during* the call, and asserts `_running` contains
  the handler's key during the call and is cleared afterward (proves
  before/afterCall genuinely fire).
- `tests/unit/test_event_system.py::TestPluginRunningAggregation` — exercises
  the real `plugin.running` aggregation the way `initShutdown` uses it:
  registers two actual `Plugin` subclasses and asserts
  `fireEvent('plugin.running', merge=True)` is `[]` when nothing is running,
  and reports *only* a genuinely in-flight handler when one plugin's
  `_running` is non-empty. Fails on the blocked code
  (`['PluginA.isRunning', 'PluginB.isRunning']`), passes after the exemption.

### PR #151 review follow-up (HIGH): afterCall must run on handler exception
Cloud review found a second door to the same shutdown-hang failure mode.
`createHandle` marks the handler running via `beforeCall`, then calls
`runHandler`, which **re-raises** handler exceptions by design. `afterCall`
only ran on the success path, so any tracked handler that raised leaked its
`beforeCall` entry in `Plugin._running` permanently — after that,
`fireEvent('plugin.running', merge=True)` never returns `[]` again and
`Core.initShutdown` hangs on its hard 30s timeout for the rest of the
process life. The `isRunning` exemption does **not** cover this (any *other*
handler raising leaks). Fix: wrap the call so `afterCall` always runs —
`try: h = runHandler(...) finally: afterCall (if present)` — keeping the
outer `except Exception` swallow so one bad handler still doesn't kill the
whole `fireEvent` dispatch. Tests
(`tests/unit/test_event_system.py::TestAfterCallOnHandlerException`): a real
`Plugin` handler that raises leaves `_running` empty afterward AND
`fireEvent('plugin.running', merge=True)` returns `[]`. Both fail without the
`finally`.

## CLAUDE.md "Known Technical Debt" lines this makes stale

(Orchestrator updates `CLAUDE.md` centrally — noting here for that pass.)

- `API auth via URL key only, no rate limiting` — still true structurally,
  but the specific consequence "the api_key leaks into `docker logs` via
  uvicorn's access log" (item 3) and "logged URLs are never redacted" (item
  5) are now fixed; the line itself should probably be kept (auth mechanism
  unchanged) but could gain a footnote that log exposure of the key is now
  mitigated.
- No existing debt line covers the TLS monkeypatch, the scanner symlink
  issue, the `info2` level bug, or the `im_self` shutdown bug — these were
  undocumented defects, not listed debt, so no existing bullet needs
  removal; the orchestrator may want to note the fixes in a "Recently Fixed"
  section instead.

## Acceptance Criteria

- [ ] All 6 fixes above implemented with a failing-then-passing regression test
- [ ] `.venv/bin/python -m pytest tests/unit/ -q` — fully green
- [ ] `.venv/bin/ruff check .` — clean
- [ ] No changes under `libs/`, `couchpotato/lib/`, or to CodernityDB
- [ ] Commit message: `fix(security,logging): P0 hardening — TLS, symlink scan, key-in-logs, log visibility, shutdown wait (REG-003)`
