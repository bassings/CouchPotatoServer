# RENAMER-EVENT-CHAIN — Post-processing chain (subtitles, trailers, notifications, metadata, release completion) is dead

## Verdict

**LARGE reconstruction, not a minimal wiring fix.** Two `fireEvent()` calls are
missing, but the `group` payload those events must carry, and the
release-completion state transition that depends on them, were never rebuilt
after the Python-3 migration split. Restoring the events without restoring
their payload/state-machine dependencies would fire broken events (listeners
crashing on missing keys, e.g. `KeyError: 'destination_dir'`) or silently
no-op (e.g. `release.add` never called → releases never reach `status: done`).
This needs its own carefully-scoped, TDD'd project — see "Recommended plan"
below for a phased approach that still keeps it boundable.

## 1. What the current renamer actually does

`couchpotato/core/plugins/renamer/main.py` (~234 lines) + its mixins
(`scanner.py` 219, `mover.py` 86, `namer.py` 79, `extractor.py` 325 — grew with
the atomic-extract/stray-sweep hardening after the split, `cleanup.py` 141)
genuinely **do** move/rename files on disk today — this is
not just a status-tracking stub:

- `Renamer.scan()` (`main.py:63-105`) calls `fireEvent('scanner.scan', ...)`
  (handled by `couchpotato/core/plugins/scanner/folder_scanner.py`) to detect
  release groups in the "from" folder, then calls `_processGroup()` per group.
- `_processGroup()` (`main.py:107-230`) builds `replacements` from
  `group['media']['info']` and `group['meta_data']`, renders folder/file names
  via `NamerMixin.doReplace`, creates the destination directory
  (`main.py:200-209`), and **actually moves each file** via
  `self.moveFile(src, dst, use_default=True)` (`main.py:221`, implemented in
  `mover.py:16` — does `shutil.move`/hardlink/symlink per `file_action` config).
  It then deletes the emptied source folder if `cleanup` is configured
  (`main.py:227-230`, `cleanup.py:108` `deleteFolder`).
- `checkSnatched()` (`scanner.py:17-176`) polls download clients via
  `download.status`, updates release status (`release.update_status` →
  `snatched`/`seeding`/`missing`/`failed`/`downloaded`), and for
  completed/seeding-complete releases calls `self.scan(release_download=...)`
  (`scanner.py:158`) — i.e. it drives the real move above.

**What is genuinely absent**, confirmed by `git grep -n
"fireEvent('renamer\.\(before\|after\)'" -- '*.py'` returning **zero hits**
anywhere in the tree:

1. No `fireEvent('renamer.before', group)` before the move — subtitles never
   get a chance to attach to `group['before_rename']` pre-move.
2. No `fireEvent('renamer.after', message=..., group=..., in_order=True)`
   after the move — trailers, all notification providers, metadata (.nfo)
   generation, and `manage.py`'s post-rename library re-scan never fire.
3. **No release-status finalization at all.** `_processGroup` never calls
   `release.add` or `release.update_status(..., status='done')` after a
   successful move. `_processGroup`'s own `release_download` parameter
   (`main.py:107`, threaded in from `scan()` at `main.py:63,97`) is accepted
   but **never read inside the method body** —
   `grep -n "release_download" couchpotato/core/plugins/renamer/main.py`
   shows it only in the signature/docstring/call-site, never used to look up
   or update anything. Confirmed no `release.add`/`release.update_status` call
   anywhere in `renamer/main.py` or `renamer/cleanup.py`.

Net effect beyond the previously-known dead listeners: files really do get
renamed and moved into the library folder, but **the release document that
tracks that download never transitions to `status: done`**. It's stuck at
whatever `checkSnatched` last set it to (`downloaded` or `snatched`), so the
movie never reaches its final "have it" library state via this path, and the
dashboard "recently downloaded" marking (`mark_as_recent` in the old code,
see §2) never happens either.

## 2. Git archaeology — when the rename() event/state logic was dropped

```
git log -S "renamer.after" --oneline --all   # shows 1e558994 as the drop point
git log -S "renamer.before" --oneline --all  # same
```

Commit **`1e558994` "refactor: split renamer.py into package module"**
(2026-02-09, parent `e05cd45a`) deleted the monolithic
`couchpotato/core/plugins/renamer.py` (**1566 lines**, confirmed via
`git show --stat 1e558994`) and replaced it with the current package
(**864 lines total** across `__init__.py`, `api.py`, `cleanup.py`,
`extractor.py`, `mover.py`, `namer.py`, `scanner.py` — the sum matches the
commit's own accounting: "8 files changed, 864 insertions(+), 1566
deletions(-)"). The commit message says "All 208 tests pass" — there was
evidently no test exercising the dropped ~700 lines, so nothing caught the
loss. **This was a lossy refactor, not a lossless split**: roughly 700 lines
of logic were dropped rather than relocated, including:

- The `fireEvent('renamer.before', group)` call (old `renamer.py:312`, present
  in `1e558994^:couchpotato/core/plugins/renamer.py`).
- The `fireEvent('renamer.after', message=download_message, group=group,
  in_order=True)` call (old `renamer.py:684`) with the exact `download_message`
  format: `'Downloaded %s (%s%s)' % (media_title, quality_label, ' 3D' if 3d
  else '')` (old `renamer.py:682`).
- The whole per-file naming/replacement + rename/move loop that built the
  `group` payload keys listeners depend on: `group['before_rename']`,
  `group['renamed_files']`, `group['destination_dir']`, `group['filename']`
  (see §3 — none of these are set anywhere in the current tree; confirmed by
  grepping `couchpotato/core/plugins/renamer/*.py` and
  `couchpotato/core/plugins/scanner/*.py` for each key).
- **The release-quality-comparison and completion state machine** (old
  `renamer.py:507-566`): for each existing release on the media
  (`fireEvent('release.for_media', ...)`), compare quality
  (`quality.ishigher`) against the new download — remove lower-quality
  existing copies, cancel the rename if a same-or-better release is already
  `done` (fires `movie.renaming.canceled`), or mark the existing release
  `status: downloaded` and populate `group['release_download']`
  (old `renamer.py:552-556`, `561-565`) so `manage.py`'s `renamer.after`
  listener can read it (see §3, `manage.py:35-38`).
- The final `release.add(group=group, update_id=...)` call is *not* directly
  in old `renamer.py` either — it's fired from `manage.py`'s `after_rename`
  listener (`manage.py:35-38`, still present and correct in current tree),
  which is itself only reachable via `renamer.after`. `release.add`
  (`couchpotato/core/plugins/release/main.py:136-195`, unchanged, still wired
  via `addEvent('release.add', self.add)` at line 51) is what sets
  `release['status'] = 'done'` (lines 160, 175) and fires
  `media.restatus(..., allowed_restatus=['done'])` (line 195). **This is the
  only code path in the entire codebase that finalizes a release to `done`
  after download** — and it has been unreachable since `1e558994` because its
  trigger (`renamer.after`) never fires.

Later commits (`c653f7f0` "fix: Complete renamer _processGroup
implementation", `9cb79ba2`, `117e5192`, `5f6db763`, `0648e774`, `3bbaa144`)
rebuilt a **new, simpler** `_processGroup` that restores the move-files
behavior but never restored the events or the release-status finalization —
i.e. two independent people/passes fixed "does scanning/moving work" without
re-threading "does the post-processing chain fire," and nobody has yet
noticed because CI has no end-to-end test that asserts a release reaches
`status: done`.

## 3. Payload contract each listener expects

All confirmed by reading the actual listener code (paths below), not
inferred.

### `renamer.before(group)` — one positional arg, called pre-move

| Listener | File:line | Reads from `group` |
|---|---|---|
| `Subtitle.searchSingle` | `couchpotato/core/plugins/subtitle.py:22,26-45` | `group['subtitle_language']` (dict, populated by `folder_scanner.py:259`), `group['files']['movie']`, `group['files']['subtitle']` (appends), `group['before_rename']` (appends downloaded subtitle paths — **must exist as a list before this fires**) |

### `renamer.after(message=None, group=None)` — kwargs, fired `in_order=True` (sequential, not concurrent — ordering matters, see priorities below)

| Listener | File:line | Reads from `group` / `message` |
|---|---|---|
| `Trailer.searchSingle` | `couchpotato/core/plugins/trailer.py:16-42` | `group['files']['trailer']`, `getTitle(group)`, `group['filename']`, `group['destination_dir']`, `group['renamed_files']` (appends trailer file path) |
| `manage.py after_rename` | `couchpotato/core/plugins/manage.py:35-38`, priority **110** (runs after default-priority listeners) | `group['destination_dir']`, `group['renamed_files']`, `group['release_download']` — passes all three into `scanFilesToLibrary(folder=, files=, release_download=)` (`manage.py:264-276`), which re-scans the destination and calls `fireEvent('release.add', group=group, update_id=release_download.get('release_id'))` — **this is the call that sets `release.status = 'done'`** |
| `MovieMetaData.create` | `couchpotato/core/media/movie/providers/metadata/base.py:21-60,93-95` (`create` at line 21, `getRootName` at line 93) | `group['media']['_id']` (re-fetches via `movie.update`), `getRootName(group)` = `os.path.join(group['destination_dir'], group['filename'])`, appends to `group['renamed_files']` |
| Notification base (`Notification.createNotifyHandler`) | `couchpotato/core/notifications/base.py:19,33-40` | passes `group` through as `data` to `notify(message=, data=, listener=)` |
| `plex/main.py addToLibrary` | `couchpotato/core/notifications/plex/main.py:24,26-30` | ignores payload, just triggers `self.server.refresh()` |
| `synoindex.py addToLibrary` | `couchpotato/core/notifications/synoindex.py:22,24-38` | `group['destination_dir']` (arg to `synoindex -A <dir>`) |
| `script.py runScript` | `couchpotato/core/notifications/script.py:24,26-40` | `group['destination_dir']` (passed as argv to the user's script) |
| `xbmc.py` (`listen_to`) | `couchpotato/core/notifications/xbmc.py:22,44-53` | `data['destination_dir']` to trigger `VideoLibrary.Scan` |
| `trakt.py`, `homey.py`, `core/main.py` (`listen_to`) | various | `getIdentifier(data)` / `getTitle(data)` off the passed `group` |

**Every one of `destination_dir`, `filename`, `renamed_files`,
`before_rename`, `release_download` on `group` is currently never set
anywhere** in `couchpotato/core/plugins/renamer/*.py` or
`couchpotato/core/plugins/scanner/*.py` (confirmed by grep across both
directories) — these were populated inline in the deleted `rename()` logic.
`_processGroup` today builds an equivalent local `rename_files` dict
(`main.py:172-191`, `src -> dst`) but never writes any of the above keys back
onto `group`, and never keeps a `release_download` reference beyond the
unused parameter.

## 4. Risk assessment

Firing `renamer.after` for real users on upgrade will, in one pass, newly
activate:

- **Notifications** (XBMC/Kodi, Plex, Synoindex, script, Homey, Trakt, core
  UI notification, and any third-party notifier not audited here) — for every
  release currently sitting in the DB with an "unfinished" status
  (`snatched`/`seeding`/`downloaded`) whose files already got moved by the
  post-refactor `_processGroup` (this has been happening silently since
  `1e558994` — meaning some users may have **years** of already-moved files
  whose releases never got finalized). If the fix re-scans on next
  `checkSnatched`/`scan()` cycle and treats them as fresh completions, it will
  send a burst of duplicate/backlog notifications and trigger `VideoLibrary.Scan`
  / Plex library refresh storms for content the user already has and has
  likely already seen show up in Plex/Kodi via their own filesystem watchers.
- **Metadata writes** (`.nfo`, poster/fanart/banner files) — `MovieMetaData.create`
  will attempt to write files into `destination_dir` for every affected group;
  if `destination_dir`/`filename` aren't populated correctly the write targets
  will be wrong paths (potential `FileNotFoundError` or, worse, writes to an
  unintended directory if a bug produces a bad path) — this is real filesystem
  I/O against user media libraries, not sandboxed.
- **Release-status transition to `done`** — this is actually *wanted*
  behavior (it's the missing piece that makes the library "know" a movie is
  finished), but the first run after the fix ships will process a backlog of
  every release stuck in a non-`done` status, not just newly-downloaded ones —
  amplifying all of the above by however large that backlog is per install.
- **Duplicate-detection/lower-quality-removal logic is currently entirely
  absent** — the old code's quality-comparison block (§2) that skips
  re-processing when an equal-or-better release is already `done`, or removes
  superseded lower-quality files, does not exist in the current
  `_processGroup`. Restoring `renamer.after` without restoring at least the
  "don't reprocess if already done" guard risks re-firing the whole
  notification/metadata chain on every scan cycle for the same release, or
  worse, acting on stale/duplicate release docs.

**Required guards before shipping any version of this:**
1. Only fire `renamer.after` once per group per actual move (not on every
   `scan()` invocation that re-detects the same folder) — gate on whether
   `rename_files` was non-empty **and** the move loop actually succeeded for
   at least one file, and idempotency: once a release is `done`, `scanner.scan`
   /`checkSnatched` must not re-select it (verify `release.with_status` filters
   in `scanner.py:27` already exclude `done` — they do: it queries
   `['snatched', 'seeding', 'missing']` only, so this should self-limit going
   forward, but confirm no *other* path — e.g. `base_folder` manual rescans
   via the `renamer.scan` API view, `main.py:27-34` — can re-target an
   already-`done` release's leftover folder).
2. A migration/backfill consideration: decide whether releases that were
   already silently moved pre-fix (see above) should be swept into `done`
   directly (no re-notify) via a one-time maintenance pass, rather than being
   picked up by the normal `checkSnatched`/`scan` cycle and re-triggering the
   full notification/metadata chain as if freshly downloaded. This needs an
   explicit decision — it's a data/UX question, not just code.
3. Feature-flag or staged rollout: given the blast radius (real notifications,
   real file writes, real library rescans against user Plex/Kodi instances at
   `homemedia.maeewing.com`), consider gating the new event-firing behind a
   conf flag defaulting off for at least one release, or restrict initial
   rollout to fresh downloads only (i.e., explicitly skip firing for releases
   whose status was already `downloaded`/`seeding` at upgrade time — only fire
   for ones that transition through the *new* code path from here on).

## 5. Recommended plan

This is genuinely two nested problems: (a) restore `renamer.before`/`renamer.after`
with a correct payload, and (b) restore the release-completion state machine
that `renamer.after`'s primary listener (`manage.py` → `release.add`) depends
on to be meaningful. Neither is safe alone: (a) without (b) fires
notifications/metadata for releases that never reach `done` (repeats forever);
(b) without (a) is unreachable. Recommend a phased project, each phase
TDD'd and reviewed independently per `docs/development-process.md`'s Path to Production (full flow):

**Phase 0 — Test harness first (prerequisite for everything else).**
Write an integration test that drives `Renamer.scan()` end-to-end against a
`tmp_path` fixture: seed a fake "from" folder with a movie file, a fake
release doc with `status: snatched`/`download_info`, run `scan()`, and assert
(a) the file actually moved (already true today — this test should pass
immediately and acts as a regression guard for the current, working, move
behavior) and (b) currently-failing assertions that `renamer.before`/
`renamer.after` fired with the documented payload keys and that the release
doc reached `status: done`. This test should **fail** on current master in
exactly the way this investigation predicts — use it as the acceptance
contract for the rest of the phases.

**Phase 1 — Populate the `group` payload in `_processGroup`.**
Add `group['destination_dir']` (folder from the rendered path),
`group['filename']` (base filename, no extension, of the primary renamed
file), `group['before_rename'] = []` (set before any pre-move hook runs),
`group['renamed_files']` (list of actual destination paths, built from the
existing `rename_files` dict as files are moved — `main.py:172-224` already
has all the data, it's just not written back onto `group`), and thread
`release_download` from the (currently-unused) parameter onto
`group['release_download']`. No event firing yet — just make the payload
shape correct and covered by unit tests reading it back.

**Phase 2 — Fire `renamer.before`.**
Insert `fireEvent('renamer.before', group)` right after
`group['before_rename'] = []` is set and before the extraction/move logic
begins (mirroring old `renamer.py:310-312` — before renaming so subtitle
downloads land in `before_rename` and get moved alongside the movie file).
Verify `Subtitle.searchSingle` runs without `KeyError` against a real `group`
built by Phase 1 (add a subtitle-specific test using a monkeypatched/disabled
subliminal call, or gate on `self.isDisabled()` returning True in test config
to exercise only the guard clause safely).

**Phase 3 — Restore minimal release-completion + `renamer.after`.**
This is the highest-risk phase. At minimum:
- Add the "already `done` at equal-or-better quality" guard (a trimmed-down
  version of old `renamer.py:507-544`'s quality comparison, using
  `fireEvent('release.for_media', ...)` and `quality.ishigher` — both events
  still exist and are wired, confirmed via
  `grep -rn "addEvent('release.for_media'\|addEvent('quality.ishigher'" couchpotato/`)
  before doing the move, so re-scans don't reprocess/re-notify indefinitely.
- Build `download_message` in the documented format and fire
  `fireEvent('renamer.after', message=download_message, group=group,
  in_order=True)` after a successful move, wrapped in the same
  try/except-log pattern as old `renamer.py:683-686` (a failing listener must
  not abort the loop over other groups).
- Confirm `manage.py`'s `after_rename` (priority 110) fires `release.add`
  correctly and the release reaches `status: done` in the Phase-0 test.

**Phase 4 — Backlog/migration decision + guarded rollout.**
Decide explicitly (with Scott) whether to (a) let the normal `checkSnatched`
cycle sweep any pre-existing `snatched`/`seeding`/`downloaded` releases
through the newly-completed chain (accepting a one-time notification/rescan
burst proportional to backlog size), or (b) write a one-time maintenance
script that silently flips already-moved releases to `done` without firing
notifications, then only apply the new event-firing behavior going forward.
Given the production instance (`homemedia.maeewing.com`) has almost certainly
accumulated a backlog since `1e558994` (2026-02-09), **(b) is very likely the
safer default** — verify by checking the production DB for release counts by
status before deciding (`sqlite3 .../couchpotato.db "select status, count(*)
from release group by status"` against a backup, never the live file).

**Phase 5 — E2E/UI check.**
Per `docs/development-process.md`'s "E2E tests" section, check whether any `tests/e2e/*.spec.ts` assert on
release/notification state that this change touches (unlikely, since this is
backend-only, but the dashboard "recently downloaded" UI reads release status
and could newly show items) — confirm and update if so.

Each phase should land as its own PR through the full Path to Production gate
(local review → push → cloud `claude-review` → merge), not as one giant
change — the risk profile (real file I/O, real notifications, real user
libraries) justifies incremental, independently-revertable steps.

## Files referenced

- `couchpotato/core/plugins/renamer/main.py` (`_processGroup`, `scan`,
  `release_download` dead parameter)
- `couchpotato/core/plugins/renamer/scanner.py` (`checkSnatched`,
  `release.with_status` filter)
- `couchpotato/core/plugins/renamer/mover.py` (`moveFile` — real move/link
  logic, unaffected)
- `couchpotato/core/plugins/renamer/cleanup.py` (`tagRelease`, `deleteFolder`)
- `couchpotato/core/plugins/scanner/folder_scanner.py` (`group['media']`,
  `group['files']`, `group['identifier']`, `group['subtitle_language']`
  population — confirmed does NOT set `destination_dir`/`filename`/
  `renamed_files`/`before_rename`/`release_download`)
- `couchpotato/core/plugins/subtitle.py` (`renamer.before` listener)
- `couchpotato/core/plugins/trailer.py` (`renamer.after` listener)
- `couchpotato/core/plugins/manage.py:35-38,264-276` (`renamer.after`
  listener → `release.add`)
- `couchpotato/core/plugins/release/main.py:136-195` (`release.add` — sets
  `status: done`, fires `media.restatus`)
- `couchpotato/core/media/movie/providers/metadata/base.py` (`renamer.after`
  listener, `getRootName`)
- `couchpotato/core/notifications/{base,core/main,plex/main,synoindex,script,
  xbmc,trakt,homey}.py` (`renamer.after` listeners)
- Historical reference (deleted, recovered via git for this investigation):
  `1e558994^:couchpotato/core/plugins/renamer.py` — `git show
  1e558994^:couchpotato/core/plugins/renamer.py` to view in full.
