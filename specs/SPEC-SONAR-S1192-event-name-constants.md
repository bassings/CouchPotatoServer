# SPEC: T5, python:S1192 duplicated string literals (72 findings)

## Problem

SonarQube reports 72 `python:S1192` findings, 57 distinct literals, ALL in live
production Python (zero in tests). They are not one thing, and the rule's
generic remedy ("define a constant") is right for some and actively harmful for
others. This spec records the split and fixes only the half that earns it.

## The split, measured from the scan

**24 of the 57 distinct literals are event names** (dotted lowercase, passed to
`addEvent` / `fireEvent` / `fireEventAsync`):

    app.load, app.restart, app.shutdown, couchpotato.db, library.query,
    library.related, library.tree, manage.update, media.get, media.restatus,
    media.types, media.with_status, movie.update, notify.frontend,
    profile.default, release.add, release.for_media, release.manual_download,
    release.update_status, release.with_status, renamer.scan,
    scanner.name_year, searcher.protocols, updater.check

These are the ones worth fixing, and not for tidiness. Event wiring in this
codebase fails SILENTLY: a mistyped name in `addEvent` registers a listener
nothing ever calls, and a mistyped name in `fireEvent` calls nothing. Neither
raises. This has already happened twice in this repository:

  - `renamer.before` / `renamer.after` are never fired, so subtitles, trailers,
    notifications and metadata are all silently dead despite correct plugin
    code.
  - `app.test` has FOUR listeners (`quality/main.py:75`,
    `userscript/main.py:23`, `file.py:39`,
    `providers/torrent/thepiratebay.py:44`) and zero fire sites anywhere in the
    repository. Verified by grepping the literal across all Python, JS and HTML,
    with the method first validated against `app.load`, which correctly found
    its single fire site at `runner.py:627`.

A named constant turns a typo from silence into an immediate `ImportError` or
`AttributeError` at load time.

**The remaining 33 literals are rejected, in four groups:**

1. **API schema descriptions** ('Media ID', 'The id of the media',
   'array or csv', 'int (comma separated)',
   'ID of the release object in release-table'). These sit inline in route
   documentation blocks. Replacing them with constant names makes the schema
   harder to read at the point it is defined, which is the opposite of the
   rule's intent.
2. **Generic format strings** ('Failed: %s', 'Response: %s', 'Protocol Error: %s').
   Too generic to share. A single constant would couple unrelated call sites
   so that changing one message silently changes others.
3. **An embedded truth table.** `file.py:230-243` (`doSubfolderTest`) is a unit
   test living in production code, and the repetition of '/test/sub/folder' and
   '/CapItaLs/Are/OK' IS the table: each row pairs specific inputs with an
   expected result. Extracting constants would destroy it. The real finding
   here is that this test ships in the production image and, being registered on
   the orphaned `app.test`, has never run in the FastAPI era. Recorded as debt,
   not fixed by this task.
4. **Single-file user-facing messages** ('Successfully connected to NZBGet',
   'NZBGet is not responding...', 'Database busy, please retry'). Each is
   duplicated within one file, where the duplication is legible and local.
   Marginal at best; not worth touching the downloader error paths for.

## Acceptance criteria

- AC-1: A single module defines a named constant for each of the 24 event
  names. No event name string literal remains at any `addEvent`,
  `fireEvent` or `fireEventAsync` call site for those 24 events.
- AC-2: A test asserts each constant's VALUE equals the exact original literal.
  This is the guard that the refactor was behaviour-neutral; it must fail if
  any constant's string is altered.
- AC-3: The full unit suite passes with an unchanged pass/skip/xfail count.
  A changed count means an event was rewired, not renamed.
- AC-4: No production behaviour changes. The diff substitutes names for
  identical strings and does nothing else.
- AC-5: The 33 rejected literals are left OPEN in SonarQube, not dismissed,
  with the reasons above recorded in the plan file.

## Explicitly out of scope, recorded as follow-up T10

A guard that asserts every `addEvent` name has at least one matching
`fireEvent` name, which would have caught both `renamer.before/after` and
`app.test`. It is the higher-value change and this task makes it easy (the
constants become the enumeration), but it is a new guard with its own design
questions, notably how to allowlist deliberately-dormant events without the
allowlist becoming a rubber stamp. It does not belong inside a
literal-extraction task.

## Files most affected

`couchpotato/core/media/_base/media/main.py` (14), `movie/searcher.py` (6),
`db/sqlite_adapter.py` (5), `downloaders/nzbget.py` (5),
`plugins/release/main.py` (4), and the destructive paths `plugins/manage.py` (3)
and `plugins/renamer/main.py` (2). The renamer and manage changes must be
reviewed as carefully as any change to those files, even though they are
mechanical.
