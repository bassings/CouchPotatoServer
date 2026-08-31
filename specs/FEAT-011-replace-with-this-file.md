# FEAT-011: replace a library file with one the owner placed by hand

> Planning output of the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.

**Status:** draft
**Lenses run:** <plan-cycle to fill> · **Skipped:** <plan-cycle to fill>

## Shipped disabled (T8a, 2026-08-31)

This feature ships **off by default**, behind a new renamer setting,
`operator_replace_enabled` (`couchpotato/core/plugins/renamer/api.py`,
default `False`). This lets `feat/review-queue-and-manual-replace` carry
FEAT-010 (the review-gate) and FEAT-012 (renamer decision memory) without
also shipping a reachable path that permanently deletes a media file.

**Why.** The operator replace path has reintroduced the same
film-destroying defect three times, most recently the route minting its
own decision-time baseline rather than using the one recorded when the
operator opened the picker. Three reintroductions of the same class of
defect is the owner's explicit trigger (per `CLAUDE.md` rule 11: "after
three failed fixes, question the frame, not the fix") to stop trusting a
fourth guard and turn the feature off at the root instead.

**What "off" means here.** Not a refusal inside the handler -- a guard in
that position has now failed three times. With the setting at its
default, `Renamer.__init__` does not register `renamer.operator_replace`,
`renamer.operator_candidates` or `renamer.operator_replacement_preview`
at all, so a request for any of them reaches the same "API call doesn't
exist" answer as any other unknown route name. The movie detail page's
"Replace with this file" trigger and the modal it opens do not render
either. Nothing in this spec, its implementation, or its tests was
removed or weakened to do this -- the feature is intact and can return as
its own reviewed change once the condition below is met.

**What must be true before this is turned on.** A review specifically
scoped to the destructive path's decision-to-execution boundary --
tracing how a baseline is recorded, read back, and enforced at the moment
of the swap -- with the reviewer given the history of the first three
defects so it can check the fourth attempt against the actual pattern
those shared, not just against this spec's acceptance criteria in
isolation. Turning the setting on is a deliberate, separate change, not a
side effect of any other work on this branch.

## Problem

The owner sometimes needs to replace a library file for a reason the system
cannot express: **the copy in the library is not playable**, and a different
copy of the same film at the same quality rung is.

The prompting case, measured on production 2026-08-30. `Minions & Monsters` was
filed as a 17.0 GB Dolby Vision **Profile 5** copy, which Plex cannot play back
on the owner's clients. The owner downloaded a 20.3 GB Profile 8 / HDR10+ copy
by hand into `/downloads` and expected the renamer to file it over the top. It
did not, and it will not, for three independent reasons:

1. **`upgrade_replace` is off** in production settings, which is the master
   switch for replacing a library file. It defaults off deliberately: two
   earlier attempts at replacement each destroyed an irreplaceable file
   (`renamer/replacement.py:9-20`).
2. **A hand-placed file cannot assert which film it is.** The scanner records
   `identity_source`, and only `download_id`, `cp_tag`, `nfo` and `filename`
   are trusted to authorise replacement (`renamer/main.py:490-509`). A file
   dropped into the watch folder is identified by a fuzzy title-and-year search
   (`folder_scanner.py:474`), which is refused, because a wrong guess here does
   not misfile a download, it destroys a **different film's** library copy.
3. **Even with both of those solved it would still refuse.** Both copies are
   2160p, so `is_better` answers no and the outcome is `declined_not_better`.
   Profile 5 versus Profile 8 is a *playability* difference; the system models
   quality rungs only and has no concept of "my player cannot decode this".

Each of those three is correct on its own terms. The gap is that there is no
way for the owner, who **knows** which film it is and **knows** the current copy
does not play, to say so.

**Observed cost while there is no such mechanism.** The refusal is not
terminal: the renamer rescans, re-decides, re-refuses, and leaves the download
in place, every two minutes, indefinitely. Measured on production: 31 identical
`declined_unverified_identity` cycles in 65 minutes, running since 2026-08-28,
each one costing a TMDB lookup and a full folder rescan. The owner's 20.3 GB
file stays in `/downloads` and the logs fill with a decision already made.

This will recur on every Dolby Vision Profile 5 release.

## Not in scope

- **Teaching the upgrade logic about HDR formats and Dolby Vision profiles.**
  Considered and declined by the owner as the largest option, touching the exact
  code path that has already destroyed files twice. This spec instead gives the
  owner an explicit, deliberate action and leaves automatic replacement alone.
- **Changing `upgrade_replace`, `is_better`, or any automatic replacement
  path.** The operator action specced here is a separate entry point. Automatic
  behaviour must be byte-for-byte unchanged, and that is an acceptance
  criterion, not an aspiration.
- **Making the review queue visible.** FEAT-010.

---

## Acceptance criteria

**Design constraints the lenses must plan within**, from the incident history in
`renamer/replacement.py`:

- An **explicit operator choice of a specific film plus a specific file is
  itself the identity assertion**, and is stronger than any of the four
  automatic sources: it is a human naming both sides, not an inference. That is
  what makes bypassing `_identityIsAsserted` legitimate here and nowhere else.
- **Bypassing the quality comparison is the entire point** and must not leak
  into the automatic path.
- Everything that protects against *mechanical* failure stays: the atomic swap,
  the expected-source-size check, the destination-inside-the-library check, and
  single-video-file-per-group.
- The action is **destructive and irreversible**: it deletes an irreplaceable
  media file. It needs confirmation naming what is about to be destroyed, and
  per `CLAUDE.md` it may not move a possible loss *up* the recoverability
  ranking.

**The four open decisions, ANSWERED by the owner 2026-08-30.** These are the
contract; an implementer does not get to re-decide them.

1. **Not gated on `upgrade_replace`.** That setting governs whether the system
   replaces a library file *of its own accord*, and it is off on the owner's
   production install. Gating this action on it would ship a feature that does
   nothing on the only install it was written for, and the only way to reach it
   would be to enable the automatic replacement that destroyed an irreplaceable
   file twice. **An operator naming a specific film and a specific file is a
   different authorisation from the system deciding by itself**, and the two
   must not share a switch. `renamer.enabled` DOES still apply: with the
   renamer disabled the application does not move files at all, and this action
   is a file move.
2. **Backgrounded, with observable progress**, not synchronous in the request.
   The prompting case is a 20.3 GB copy across NAS mounts. Built to the
   existing sub-second pattern the page appears hung, the operator clicks
   again, and the per-route lock queues the retry instead of refusing it. A
   second activation while one is in flight is **refused, not queued**.
3. **The operator's source is always consumed on a verified swap**, whatever
   `default_file_action` says. The file becomes the library copy, so nothing is
   lost. This overrides the setting deliberately: on `copy` and `link` the
   original stays in the watch folder, the next scan finds it again, and the
   repeating refusal that FEAT-012 exists to end returns immediately, on
   exactly the setting values that cause it. Consumption happens only AFTER the
   swap is verified, never before.
4. **A release document is written for the placed file**, recording it as the
   film's current copy at its detected quality and marked as operator-placed.
   Without one the media is permanently `declined_no_owner`: every later
   upgrade or replacement decision refuses on those grounds, and the library
   holds a file the database cannot describe.

**A fifth decision, derived rather than asked, because it follows from the
safety requirement and eight of the nine lenses raised it as High.**

**The destination is resolved from the media's EXISTING file record, never
recomputed from the naming template.** The operator says "replace *this film's*
copy", so the file to be destroyed is the one the database already records as
that film's copy. Recomputing it from the template is what makes this
dangerous: `lens-data` executed the real template and got
`The Thing ()/The Thing.mkv` for two different films that both lack a year, so
a template-resolved destination can name a **different film's** file. That is
the precise failure the `_identityIsAsserted` guard exists to prevent, and
reintroducing it through the feature designed to bypass that guard would be the
third incident.

If the media has no recorded file to replace, the action **refuses with a named
outcome** rather than falling back to the template. Nothing to replace is not
the same as permission to guess.

### lens-security

- **AC-SEC-1:** The path that gets destroyed is never supplied by the caller: the action accepts a media identifier plus a source chosen from a server-produced listing, and resolves the destination server-side from the media and release records; a request carrying additional parameters named `destination`, `dst`, `to`, `path`, `media_folder` or `base_folder` either behaves identically to one without them or is refused, and in no case is a file named by those parameters deleted or overwritten. Proven by driving the real entry point with `destination=<tmp>/victim.mkv` present and asserting `victim.mkv` is byte-identical by sha256 before and after. (Merges AC-ARCH-4.)
- **AC-SEC-2:** The operator-chosen source is confined to the configured watch folder: it is resolved with `os.path.realpath`, re-derived server-side at confirm time rather than trusted from a path the client echoes back, and refused with a named refusal value and no filesystem write unless it lies inside `conf('from')`. Each of `../../etc/hosts`, a leading-slash absolute path, a name containing a NUL byte, and a name whose realpath leaves the folder returns that refusal. Proven the way `softchroot.chroot2abs` is proven (`couchpotato/core/softchroot.py:167-205`): refuse, never clamp, and never let the refusal message carry the path. (Merges AC-ARCH-5.)
- **AC-SEC-3:** `_destinationIsInsideTheLibrary` (`renamer/main.py:380-425`) is applied on the operator path, against `conf('to')` and against no request-supplied folder; a destination resolving outside the library root is refused with `declined_outside_library` and the file outside the root is unmodified. Proven by calling the operator entry point with a media whose resolved destination sits outside `conf('to')`, hashing that file before and after.
- **AC-SEC-4:** The operator path reaches the destructive step only through `swap.replace_atomically`, passing a non-None `expected_source_size` taken from the picker's own measurement and a `destination_identity` from `swap.identity_of`, so `refused_source_is_symlink`, `refused_destination_is_symlink`, `refused_same_file`, `refused_source_changed` and `failed_destination_changed` all stay reachable. Proven by a spy on `replace_atomically` asserting both keyword arguments are present and not None, plus one end-to-end case each for a symlinked source and a symlinked destination in which neither the link nor its target changes.
- **AC-SEC-5:** Nothing readable from the download folder can reach the operator outcome: no value parsed from a filename, folder name, `.nfo` file, `cp_tag` or torrent name causes the identity or quality bypass to apply. Proven by driving `Renamer.scan()` over a group whose `identity_source` is `search` and whose filename and NFO contain every marker string the operator path uses, asserting the outcome is still `declined_unverified_identity` and no library file is touched.
- **AC-SEC-6:** No parameter carrying the operator's authority is optional: any new parameter of `decide_replacement` or of the shared destructive sequence whose omission would relax a refusal is positional-or-keyword with no default, matching the reasoning recorded for `rank` at `replacement.py:156-159` and for `_IDENTITY_NOT_REQUESTED` at `swap.py:76-82`. Proven mechanically with `inspect.signature`: every such parameter has `default is inspect.Parameter.empty`. (Merges AC-ARCH-2; subsumed in practice by AC-SIMP-3, which forbids the parameter existing at all.)
- **AC-SEC-7:** The new route is authenticated on an install that has authentication on: its path appears in `tests/unit/test_route_auth_inventory.py` as a protected route and NOT in `PUBLIC_ROUTES`; if it is registered under `/api/` instead, a request with neither a URL key nor a matching `X-Api-Key` header returns 401 and makes no filesystem change. Proven by the existing inventory test seeing the route, plus one request-level test with a hash on the target file.
- **AC-SEC-8:** A GET never destroys anything: a GET request to the operator action's route leaves the library file byte-identical (405, or a no-op returning the confirmation view). Proven by issuing the GET against a test app and hashing the destination before and after. The reason is concrete rather than stylistic: every existing mutating call in `movie_detail.html` is a GET carrying the api_key in the URL, so that URL lands in browser history and in any reverse-proxy access log, and can be re-fired by a reload, a prefetch or an `<img src>`.
- **AC-SEC-9:** A demonstrably cross-origin request to the operator action is refused and destroys nothing, using the existing `_cross_origin_post` helper (`couchpotato/__init__.py:767-829`) rather than any new token machinery: a request carrying `Origin: https://evil.example` against the test app's `Host` refuses and the destination file is byte-identical, while a request with neither `Origin` nor `Referer` is still allowed, matching that helper's stated behaviour.
- **AC-SEC-10:** The default-install exposure is written down, not implied: because an install with no password serves every route to an unauthenticated caller (`tests/unit/test_auth_required_gate.py::TestTheDefault::test_absent_auth_required_without_a_password_stays_open` passes today), an entry naming this route, the capability it grants and the reason it is accepted is added to the residue inventory in `tests/unit/test_route_auth_inventory.py`, and a test fails if the route exists without an entry. Proven load-bearing by deleting the entry and watching that test go red.
- **AC-SEC-11:** Every log record the operator path emits at INFO or above names the media id, the release ids, the quality rungs and the sizes, and contains no filesystem path, no filename and no api_key, continuing the convention at `main.py:296-311` and `:638-660`. Proven by driving one successful operator replacement and one refusal with the source under `/home/<user>/downloads/...` and the library under a distinctive root, capturing records at INFO and above, and asserting none contains the download folder, the library root, the file's basename or `Env.setting('api_key')`. DEBUG is exempt and may carry the path. (Pairs with AC-OPS-11, which forbids the operator-facing diagnostic existing only at DEBUG.)
- **AC-SEC-12:** Filenames chosen by strangers cannot execute in the picker: candidates named `x'; alert(1); //.mkv`, `"><img src=x onerror=alert(1)>.mkv` and `</script>.mkv` render with no executable result, the name never interpolated into an inline `@click`/`onclick` attribute or a `<script>` block and appearing only as element text or in a `data-` attribute read by JS. Proven by rendering the picker partial with those three fixtures, asserting the escaped forms present and the raw `<img`, `</script>` and unescaped-apostrophe-inside-a-JS-string forms absent, plus one Playwright case asserting no dialog fires. Jinja autoescape alone does not settle this: `&#39;` decodes back to an apostrophe before the JS in an attribute is parsed.
- **AC-SEC-13:** The change collects no new personal data: if it persists any record of the action (an audit row, a marker file, a settings key), that record holds only media id, release ids, quality identifiers, byte sizes and a timestamp, holds no filesystem path and no title copied out of the library, and is removed when the media is deleted. Proven by reading the diff for new persisted fields and, where a record exists, by deleting the media and asserting the record is gone.

### lens-qa

- **AC-QA-1:** Happy path on a real filesystem: with a library file the operator names and a hand-placed source of equal or lower quality rung, the action completes and afterwards (a) the destination's sha256 equals the source's original sha256, (b) the source has been disposed of per `default_file_action`, and (c) the superseded release was set `ignored` and had the destination detached. Asserted on bytes and on recorded calls, never on a return value. Unit tier, `tmp_path`, no Docker.
- **AC-QA-2:** The quality bypass does not leak: driving `_moveRenamedFiles` with the same equal-quality incoming file used in AC-QA-1 still yields `declined_not_better` and leaves the destination byte-identical by sha256. The two tests share one fixture so they cannot drift apart.
- **AC-QA-3:** The identity bypass does not leak: the existing automatic-path refusals still pass unedited, `identity_source == 'search'` refusing and a group with no `identity_source` refusing, in both cases with the destination sha unchanged and zero `release.update_status` calls (`tests/unit/test_replacement_end_to_end.py`, classes `TestAGuessedMovieIdentityNeverAuthorisesDestruction` and `TestAGuessedIdentityCostsNothing`). An edit to either test fails this criterion unless the PR states why.
- **AC-QA-4:** The operator's identity assertion is verified server-side, not trusted from the client: a request whose destination is not listed in `files['movie']` of a release belonging to the named media is refused with a named outcome and changes nothing on disk, proven with three hostile destinations (a path belonging to a different seeded movie's release, an absolute path outside the library such as `/etc/hosts`, and a path containing `..` that resolves back inside the library), each asserting the refusal value and a sha256 of every file in the fixture library unchanged.
- **AC-QA-5:** Every mechanical pre-flight refusal fires on the operator path, each as its own case asserting a distinct named outcome constant (never a substring of a log line) and the destination byte-identical afterwards: source missing; source is a symlink; source is a broken symlink; destination missing (the action replaces, it never installs); destination is a symlink; source and destination are the same inode (the shipping `file_action = link` case); the source's size differs from the size captured at confirmation; the destination resolves outside `conf('to')`; the target release lists more than one movie file. Nine cases. (Merges AC-DATA-11.)
- **AC-QA-7:** Double submission cannot double-destroy: two operator replace requests for the same media issued from two real threads produce exactly one swap, the second returning a named refusal rather than an unhandled exception, a queued second staging attempt or a block on the per-route lock at `couchpotato/api.py:56`, with an INFO-or-above record for the refusal and no leftover `.cp-upgrade-*.part` in the fixture library. The test drives the real handler with a `stage` that blocks on an event so the overlap is genuine rather than sequential. Integration tier, real threads. (Merges AC-OPS-8.)
- **AC-QA-9:** The crash window is pinned: when the post-swap bookkeeping is prevented (`release.update_status` returns False, then separately `release.detach_file` returns False), the operator receives an explicit failure naming the affected release id, and a subsequent automatic replacement decision for that same destination refuses (the stale claimant's `copy_id` no longer matches the bytes on disk) rather than replacing against the wrong quality. (Pairs with AC-OPS-5 for the log half.)
- **AC-QA-12:** The confirmation is proven to name what is about to be destroyed: a test fails if it stops rendering both the destination file's name and byte size and the incoming file's name and byte size, and those values are asserted as coming from the supplied data (fixture values that differ per case), never matched against a hardcoded string that would pass for any file. A second case proves the destructive request cannot be issued without passing through the confirmation.
- **AC-QA-14:** The candidate listing endpoint's contract is pinned server-side: it returns only video files, excludes non-video files present in the fixture folder, is bounded (a stated cap, with the total found reported so nothing is dropped silently), and returns a named error rather than an empty list when the folder is unset or unreadable, so "empty" and "broken" are distinguishable by the caller.
- **AC-QA-15:** Hostile and degenerate input produces a structured refusal and zero filesystem writes, asserted by hashing every file in the fixture library and watch folder before and after each call: missing media id; missing or empty source; missing or empty destination identifier; a source path containing a NUL byte; a path 4096 characters long; a path with non-ASCII characters; a zero-byte source file.
- **AC-QA-16:** Each new guard has been broken and watched to fail, per `CLAUDE.md` rule 10: for at least the server-side identity verification (AC-QA-4), the quality-bypass containment (AC-QA-2 and AC-QA-3), the expected-source-size check (AC-DATA-3) and the library-containment check (AC-SEC-3), the PR records the mutation applied, the exact test that failed and its failure line, and a hash of the file before the mutation and after restoring showing it byte-identical. A guard whose mutation left the suite green fails this criterion.
- **AC-QA-17:** The duration of the staging copy is measured, not guessed: the spec records a measured staging throughput on a real file of at least 1 GB, naming the machine and whether the page cache was warm, and the implied wall-clock for the 20.3 GB production case across a NAS mount. That measurement is the evidence for the synchronous-versus-backgrounded decision, and the in-flight behaviour it implies is asserted by AC-DESIGN-9 and AC-A11Y-6.
- **AC-QA-18:** The destructive test tier stays fast enough to keep being run: `pytest tests/unit/test_replacement*.py tests/unit/test_atomic_swap.py tests/unit/test_release_owner.py -q` completes in under 10 seconds on the dev machine after this change. Measured baseline before the change: 198 tests in 0.42s.
- **AC-QA-19:** The interaction with the two existing switches is pinned in both states rather than left incidental: one test with `upgrade_replace` off and one with it on, and one with the renamer `enabled` off and one with it on, each asserting the decided behaviour (proceed, or a named refusal) on bytes, so a later change to either default cannot silently alter the operator path.

### lens-simplicity

- **AC-SIMP-1:** Excluding tests, the change modifies at most three existing files (`couchpotato/core/plugins/renamer/main.py`, `couchpotato/ui/templates/partials/movie_detail.html`, and `couchpotato/ui/__init__.py` only if a UI partial route is required), adds at most one new module under `couchpotato/core/plugins/renamer/`, and adds at most one new document under `docs/` (the recovery note required by AC-OPS-10). `git diff --stat master... -- . ':!tests'` lists no other path. (Amended at synthesis from "at most two existing files": the entry point, the listing route and the recovery note were unowned in the original table.)
- **AC-SIMP-2:** `swap.py`, `owner.py`, `scanner.py` and `api.py` under `couchpotato/core/plugins/renamer/` are byte-identical to master, and `replacement.py`'s diff adds only new module-level outcome constants, changing no function body and no signature. `git diff master... -- couchpotato/core/plugins/renamer/{swap,owner,scanner,api}.py` reports no changed lines. (Amended at synthesis: AC-ARCH-9 supplies the criterion that the operator outcome constant belongs beside its siblings in `replacement.py`.)
- **AC-SIMP-3:** No existing function gains a parameter, flag or keyword that disables one of its guards: the `def` lines of `decide_replacement` (`replacement.py`), `replace_atomically` (`swap.py`), `resolve_owning_release` (`owner.py`) and `Renamer._identityIsAsserted` (`main.py`) are unchanged from master, and the operator path contains no call to `decide_replacement`.
- **AC-SIMP-4:** No new configuration option is introduced: the diff adds no dict containing a `'name':` key inside any `config = [...]` block, and no new `self.conf(...)` key name appears that does not already exist on master.
- **AC-SIMP-5:** The operator path derives its destination from the owning release document's recorded `files['movie']` path rather than recomputing a name: the diff's new code contains no call to `fireEvent('scanner.scan', ...)`, no read of `conf('folder_name')` or `conf('file_name')`, and no call into the namer (`doReplace`, `getRenameExtras`).
- **AC-SIMP-7:** Browser coverage is added to the existing `tests/e2e/movie-detail.spec.ts` plus at most two new files, one `*.a11y.spec.ts` and one `*.mobile.spec.ts`. (Amended at synthesis from "no new file under tests/e2e/": `playwright.config.ts`'s `accessibility` and `mobile-chrome` projects match on those two suffixes, so the accessibility floor is unprovable without them.)
- **AC-SIMP-8:** The change adds at most two `addApiView(...)` calls in total, one to list candidate source files and one to perform the replacement, and no endpoint accepts a client-supplied directory or path to enumerate: the candidate list is derived server-side from `conf('from')` alone.
- **AC-SIMP-9:** The change adds no suppression, backoff, cooldown or persisted counter for repeated scan refusals: the diff adds no new `log_suppressed` call site and no new attribute on `Renamer` holding refusal state. The retry-loop cost described in the problem statement ships as a separate change (FEAT-012).

### lens-product

- **AC-PROD-1:** From a movie's detail page, an operator can put a file they placed by hand under the configured download folder into the library over the existing copy, in one flow, without first deleting the library copy, without editing settings, and with `upgrade_replace` still off. Proven by driving the real page and route with `upgrade_replace` false: the library path afterwards holds the operator's bytes.
- **AC-PROD-3:** Before anything is destroyed the operator is shown, on screen, the film title, the existing library file that will be permanently deleted (filename, quality and size), the chosen replacement (filename and size), and the fact that the deletion cannot be undone; a second, deliberate confirmation is required after that, and dismissing or cancelling it leaves both files byte-identical on disk.
- **AC-PROD-4:** The operator is never asked to nominate the destination by typing a path, and the destination the confirmation names is the one actually replaced. Where the existing library file for the chosen film cannot be named uniquely from the movie's own records, the action refuses and says so rather than choosing between candidates. Proven by driving a movie with two claimant releases on the same path and asserting the refusal, plus asserting the confirmed path equals the path replaced.
- **AC-PROD-7:** After a successful replacement the movie's detail page describes the copy that is now in the library, not the one that was destroyed: the quality and size shown for the current copy match the new file, and the movie does not fall back to the wanted list or trigger a fresh search for the same film. Proven by rendering the detail page after the swap and asserting the media status and that no search was fired.
- **AC-PROD-8:** The success measure, stated so it can be checked afterwards: the operator's file stops being unfinished business. After a successful replacement the next ordinary renamer scan over the same download folder produces no further refusal for that group, and the manual step the owner performed on 2026-08-30 (moving the file out of `/downloads` by hand) is no longer needed for the workflow to end. (Merges AC-QA-11; AC-OPS-6 is the mechanical proof across `default_file_action` values.)
- **AC-PROD-10:** The change adds no new place for the operator to learn: the whole flow lives on the movie detail page reached from the existing library and wanted lists, with no new settings page, no new top-level navigation entry and no new configuration key the operator must set for the action to work. Proven by a diff read plus a walk of the UI from the movie list.

### lens-design

- **AC-DESIGN-1:** There is exactly one entry point in the whole UI, in the Actions row of `movie_detail.html` (opened at `:140`), rendering only when the movie has a completed release (status in done/seeding/downloaded) carrying at least one movie file and absent otherwise, with `grep -rn` over `couchpotato/ui/templates/` showing no reference to the new route in `movie_cards.html`, `wanted.html` or any grid partial. The trigger reuses the existing danger button grammar verbatim (`bg-cp-danger/10 text-cp-danger hover:bg-cp-danger/15 rounded-md text-xs`, as at `:346` and `:283`), introducing no new colour token and no new class pattern, and `python scripts/check_conformance.py` stays green. (Merges AC-PROD-5.)
- **AC-DESIGN-2:** The trigger's visible label states the operator's intent in plain words, pinned by an exact-string assertion in both template and test (`getByRole('button', { name: <label>, exact: true })`), and does not read as a synonym of the neighbouring Delete or Mark Failed controls, so the three destructive-looking controls in one row stay distinguishable by label alone.
- **AC-DESIGN-3:** The picker implements five states, each with its own rendered copy and its own test: loading (the shared `animate-spin` / `text-cp-muted` pattern as at `modals.html:95-101`); empty (the design system's empty state, naming the folder that was searched as it is configured rather than a hardcoded path, and saying what to do next); populated; error, with distinct messages for folder-not-configured and folder-unreadable because those have different remedies; and capped per AC-DESIGN-4. A state present in the design and absent from the template fails this criterion. (Merges AC-OPS-13, so that "not applicable" and "broken" are distinguishable without reading the log.)
- **AC-DESIGN-4:** With at least 40 candidates present the list is bounded by the modal body grammar (a scrolling container capped at `max-h-[400px]`, per `README.md:152` and `modals.html:93`) rather than growing the dialog past the viewport, the total number of candidates found is shown, and no candidate is dropped silently: if a cap is applied, the copy states how many are not shown and how to narrow the set. Asserted by `scrollHeight > clientHeight` on the bounded container plus the count string. (The 393px half is AC-A11Y-13.)
- **AC-DESIGN-5:** Each candidate row shows the file's name and its size, and the file currently in the library is shown in the same view with its name and size in the same units and the same mono-numeric grammar the release table uses (`movie_releases.html:222-230`), so the operator can compare the two sizes without arithmetic or unit conversion. A candidate row shows no full filesystem path, and the name truncates with the full name available on hover/title, matching `movie_releases.html:206`.
- **AC-DESIGN-6:** Choosing a file never starts a replacement: the flow is two deliberate steps inside one dialog, select then confirm, with a separate click for the destructive step, and the dialog is the design system's modal (`role="dialog"` on a `bg-black/60` scrim, `bg-cp-card rounded-xl border border-white/[0.05] w-full max-w-lg`, header / scrollable body / right-aligned footer, per `README.md:152` and `modals.html:46-133`). No `window.confirm` is stacked over the open dialog: the new markup contains no `confirm(` call. No new component or pattern is introduced beyond this reuse. Proven by a grep scoped to the new markup plus an E2E that selects a file and asserts the replacement route received no request until the second control is activated.
- **AC-DESIGN-7:** The confirmation names both sides from the values the server will actually act on rather than anything the client guessed: the filename and size of the library file that will be deleted, the filename and size of the file that will take its place, a sentence stating the deleted file cannot be recovered, and a sentence stating what happens to the file the operator placed in the download folder once the replacement succeeds, matching what the code actually does. Proven by an E2E text assertion against fixture-known filenames and sizes plus a unit test that the confirmation payload comes from the server-resolved destination. (Pairs with AC-PROD-3 and AC-QA-12.)
- **AC-DESIGN-8:** Every step has a working exit that changes nothing: at the select step and again at the confirm step, footer Cancel, the header close control, Escape and a scrim click each close the dialog, with a route interceptor asserting the replacement route received zero requests and the movie detail body unchanged afterwards; from the confirm step the operator can return to the file list without closing and re-opening the dialog. After a committed replacement the UI offers no undo and no copy implies one: the rendered outcome text contains no occurrence of "undo", "revert" or "restore" referring to the deleted file. (Merges AC-QA-13.)
- **AC-DESIGN-9:** The in-flight state survives a slow operation: with the replacement route stubbed to take at least 10 seconds, the dialog stays open showing that work is in progress rather than closing into an ambiguous page, the copy tells the operator the copy can take several minutes and not to close the page, and no automatic full-page reload fires while the request is outstanding. Asserted at the 2s and 10s marks. (The re-entry guard and its exactly-one-request assertion are AC-A11Y-6, which also fixes how the control is disabled.)
- **AC-DESIGN-10:** The operator never sees an internal token: after any outcome the rendered text contains none of the substrings `declined_`, `refused_`, `failed_`, `replace_atomically` or `identity_source`, and every outcome constant this path can return (`replacement.py:44-81`, `swap.py:42-74`) has a distinct sentence saying what happened, which file is where now, and what to do next. A table-driven unit test iterates the constants and fails if any has no mapping, so adding a new constant fails the test rather than falling back to a generic message. (Merges AC-PROD-6; pairs with AC-OPS-3.)
- **AC-DESIGN-11:** After a successful replacement the page shows the new reality without a full reload, following the existing precedent: the detail body is swapped via `cpSwap` into `#movie-detail-container` (`movie_detail.html:440-453`, `:548`) and a toast reports the outcome. If the replacement committed but the refresh failed, the message says the replacement succeeded and the page could not refresh, never that it failed, mirroring `movie_detail.html:561-565`. Both branches are exercised, one with the refresh route healthy and one with it stubbed to 500.

### lens-accessibility

- **AC-A11Y-1:** The whole flow (reveal the action, choose the replacement file, confirm, and separately cancel) is operable from the movie detail page with the keyboard alone: no step requires hover or a pointer, and there is no focus trap outside a deliberate modal. An E2E test drives it using only Tab, Shift+Tab, arrow keys, Enter, Space and Escape, reaching a committed replacement against a stubbed API and, separately, a cancel, on both the chromium and mobile-chrome projects.
- **AC-A11Y-2:** Opening the picker moves focus into it deliberately: after the open interaction, `document.activeElement` is the first control inside the picker and never `document.body`. Asserted by evaluating `document.activeElement` in the browser, not inferred from the markup, because `movie_detail.html` builds these controls inside `<template x-if>`, which deletes the element that had focus (the failure already recorded at `movie_detail.html:476-493`).
- **AC-A11Y-3:** Cancelling, and pressing Escape, both close the flow, return focus to the control that opened it (asserted via `document.activeElement`), and issue no replace request (asserted by a route interceptor counting zero calls to the replace endpoint).
- **AC-A11Y-4:** After a replacement commits, focus lands on a stable, named element rather than being dropped: if the detail body is swapped in place, focus goes to the movie's `<h1>` with `tabindex="-1"`, matching `restoreToWanted()` at `movie_detail.html:554-560`; if the page is reloaded instead, the outcome is still announced in the document the user lands in, per AC-A11Y-5. `document.activeElement` is never `body` after the operation settles.
- **AC-A11Y-5:** The outcome is announced to assistive technology exactly once per action through `base.html`'s existing sr-only live regions (polite mirror at `base.html:488` for success, assertive at `:490` for a failure or refusal), and the announced text names the outcome, including the refusal reason when the server declines. The test asserts on the live region's text content and that it updates once, not on the visible toast. Because `toast()` auto-dismisses after 3000ms (`base.html:214`, `:229`), the outcome must also remain readable in the page after that timer expires, so a user who was reading something else does not lose the only record that a file was destroyed.
- **AC-A11Y-6:** While the replacement is in flight the committing control exposes `aria-busy="true"` and a polite in-progress announcement, and it stays focusable: it uses `aria-disabled`, never the `disabled` attribute, because disabling a focused element blurs it and dumps keyboard focus to `body` (the fix already applied at `movie_detail.html:235-248`). The test presses Enter on the control and asserts `document.activeElement` is still that control and `aria-busy` is `"true"`, and a re-entry guard means a second Enter starts no second destructive operation: exactly one request after two activations.
- **AC-A11Y-7:** Every control the feature adds has a non-empty accessible name identifying what it acts on rather than where it sits (the trigger, each candidate, the committing control, the cancel control); no icon-only control ships without a name and decorative SVGs carry `aria-hidden="true"`; each candidate's accessible name contains the candidate file's own name in full even when the visible label is truncated, and a `title` attribute alone does not satisfy this. Proven by `getByRole` with exact names plus an axe run with `button-name`, `link-name`, `aria-toggle-field-name`, `label` and `aria-valid-attr-value` reporting zero violations over the flow.
- **AC-A11Y-8:** The confirmation states, in text a screen reader reads, the film's title, the library file that will be destroyed, the replacement file, and that the action cannot be undone. As an in-page dialog (the mechanism this plan selects, per AC-DESIGN-6) it carries `role="dialog"`, `aria-modal="true"` and an accessible name, traps Tab within itself, closes on Escape and on scrim click, and returns focus to the trigger on close, per `docs/design-system/CONFORMANCE.md:38`. The test asserts on the dialog's text and walks the focus trap.
- **AC-A11Y-9:** No state the feature signals depends on colour alone (WCAG 1.4.1): armed, in-progress, replaced and refused are each distinguishable from text content or accessible names with all styling ignored, and the committing control is distinguishable from cancel by its name rather than by being the red one. Asserted by reading `textContent` and accessible names in the test, which sees no colour at all.
- **AC-A11Y-10:** axe-core, with the project's full tag set (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`, per `accessibility.a11y.spec.ts:16`), reports zero violations on the movie detail page in three states (action visible, picker open, confirmation open) in both themes. The dark run seeds `localStorage` `cp-theme` before `goto` and asserts `documentElement.classList.contains('light')` is false before scanning, following `accessibility.a11y.spec.ts:139-155`, because today the movie detail page is scanned in the light theme only.
- **AC-A11Y-11:** The new controls' text meets 4.5:1 and their focus indicator meets 3:1 against the surfaces they actually sit on, in both themes, at rest and on hover, with the ratios computed in the test from `getComputedStyle` rather than assumed. This is not covered by AC-A11Y-10: axe never evaluates `:hover`. Measured from the tokens, the danger styling this control will copy (`text-cp-danger` on `bg-cp-danger/10`, `hover:bg-cp-danger/15`, `base.html:73`) gives 4.47:1 in dark over `cp-card` and 4.21:1 in dark on hover over `cp-card`, both below the floor, while the same styling over `cp-bg` gives 4.87:1 and 4.59:1. Whichever surface is chosen must be shown to pass.
- **AC-A11Y-12:** Every control the feature adds shows a visible `:focus-visible` indicator meeting the design system's 2px accent ring with `outline-offset: 2px` (`docs/design-system/CONFORMANCE.md:48`) in both themes, and that ring is not clipped by an overflow or truncation container in the picker. Asserted per control by focusing it and reading computed `outline-width`, `outline-style` and `outline-color`, following `accessibility.a11y.spec.ts:443`.
- **AC-A11Y-13:** At the mobile-chrome viewport (Pixel 5, 393px) with a candidate filename of at least 60 characters, the flow introduces no horizontal document overflow (`documentElement.scrollWidth <= clientWidth`) and the dialog, every candidate row and both footer controls have bounding boxes fully inside the device width, measured against the device width rather than the current layout width, exactly as `tests/e2e/small-screen.mobile.spec.ts` already does for the restore picker. This repo has already shipped this precise bug once, a `<select>` sizing to its widest option at 441px inside a 393px viewport, and file names are far longer than profile labels. (Merges AC-DESIGN-12 and the viewport half of AC-DESIGN-4.)
- **AC-A11Y-14:** Every control the feature adds has a target of at least 24x24 CSS px at both 393px and 1280px (WCAG 2.2 AA 2.5.8), with axe's `target-size` rule reporting no violation in the picker-open and confirmation-open states, and the single control that commits the deletion is at least 44x44 CSS px, because a mis-tap on a phone destroys an irreplaceable file. Measured from bounding rects, not from class names.

### lens-data

- **AC-DATA-1:** The library path the operator action destroys is read from the release document the operator selected and verified to exist; it is never re-derived from the naming template. Proven against a real filesystem and a real SQLiteAdapter database with two media documents whose title and year render to the identical template path (measured: with an empty year, `doReplace('<namethe> (<year>)')` and `doReplace('<thename><cd>.<ext>')` both produce `The Thing ()/The Thing.mkv` for two different films), each holding its own library file at its own recorded path; after the action on film A, film B's file is byte-identical by hash and A's chosen file is the only one replaced. Plus a static assertion that the operator entry point calls neither `doReplace` nor `getRenameExtras`.
- **AC-DATA-2:** With two `done` releases for the same film at different qualities, each recording a different library path and both files present, the action destroys only the file belonging to the release named in the confirmed request, the other being byte-identical by hash afterwards. A single-release fixture does not satisfy this, and the test must be shown to fail when the lookup is mutated to "the first release for this media", with the mutation run recorded per `CLAUDE.md` rule 10.
- **AC-DATA-3:** The size the swap compares the source against is the one measured when the confirmation was produced, not one taken at execution time: a test appends bytes to the source between confirmation and execution and asserts a distinct named refusal, the destination byte-identical by hash and the source preserved, and the same test must be observed to fail when the implementation is mutated to re-stat the source at execution, which is the self-comparing form already documented at `swap.py:198` and `renamer/main.py:600-606`.
- **AC-DATA-4:** Executing the same confirmed operator action twice destroys at most one library file: the second execution returns a distinct named refusal and the file at the destination after both runs is byte-identical to the one installed by the first. This is not free by construction: measured on the real `replace_atomically`, a replay carrying the identity captured at decision time refuses with `failed_destination_changed`, while a replay whose `destination_identity` is stat'ed at execution time returns `(True,'replaced')` and destroys a second file.
- **AC-DATA-5:** Concurrency destroys at most one file: two threads executing the operator action against the same destination, and one operator action running concurrently with `renamer.scan` touching the same destination, leave exactly one complete file at the destination, never truncated, missing or mixed, with the loser refused by a named outcome and its source file intact. Proven by a threaded test against a real filesystem with staging deliberately slowed. Asserting only on the process-local `renaming_started` flag does not satisfy this, because `media_lock('renamer-scan')` is held only for the instant of the check-and-set (`renamer/main.py:86-92`). (Merges AC-QA-8.)
- **AC-DATA-6:** Every failure branch is driven, and in each the destination is byte-identical by hash and the operator's source file is present and whole: `stage` raises; `stage` completes but lands a shorter file; `getsize(staging)` raises; `os.replace` raises `PermissionError`; and the destination filesystem is full during staging (a real ENOSPC, not a mocked exception, because this feature stages tens of gigabytes into the library). No `.cp-upgrade-*.part` remains in any case where the source survived; with a consuming stage injected, the staged file is deliberately left because it is then the only complete copy. Each case is named and asserted individually. (Merges AC-QA-6.)
- **AC-DATA-7:** The old library file is destroyed only by the atomic `os.replace` and never by a prior removal or truncation: the operator entry point contains no `os.remove`, `os.unlink`, `shutil.move`, `shutil.rmtree`, `deleteFolder` or `open(dst,'w')` targeting the destination or its containing folder, proven by patching `os.replace` to raise and asserting the original survives byte-identical, plus a static assertion over the new function's source.
- **AC-DATA-8:** After a successful operator replacement against a production-shaped SQLiteAdapter database, no release document lists the destination path with a `copy_id` that disagrees with the size of the bytes now at that path, and no more than one document lists that path. Run a second time with the process killed immediately after `os.replace` and before any bookkeeping: a subsequent library scan reaches the same end state. This is not hypothetical: `release.add` keys on `<imdb>.<audio>.<quality>` (`release/main.py:265`), so an incoming copy at the same rung with different audio creates a second `done` release claiming the same path, which `resolve_owning_release` then answers `declined_ambiguous_owner`.
- **AC-DATA-9:** The action's behaviour is defined and asserted for every state in which ownership cannot be resolved: no release claims the destination; two releases claim it; the claiming release's `copy_id` does not match the bytes on disk; the claiming release has no `copy_id` at all (every document written before FEAT-009 Part A). In each case the action either refuses with a distinct named outcome leaving the destination byte-identical, or completes and leaves no document claiming that path with a `copy_id` that disagrees with disk. The four cases are enumerated in the test, and a second operator action on the same film after a successful first one still succeeds.
- **AC-DATA-10:** The identity and quality bypass cannot leak into the automatic path: with `upgrade_replace` on, a group identified via `folder_scanner`'s `movie.search` fallback still returns `declined_unverified_identity`, and an equal-rung group still returns `declined_not_better`, both asserted through a full `_moveRenamedFiles` run against a real temp filesystem with the destination byte-identical afterwards, plus a static assertion that no call site inside `_moveRenamedFiles` sets the bypass and that the bypass parameter's default is the refusing value. (Merges AC-ARCH-2.)
- **AC-DATA-12:** The operator's hand-placed source is removed or relinked only after `os.replace` has committed: for each `default_file_action` value (`move`, `copy`, `link`, `symlink_reversed`) a refused or failed replacement leaves the source byte-identical, and after a successful one every other file in the destination folder (a decoy copy of the same film under another filename, a cd2 part, a `.srt`, a `.nfo`) still exists unmodified, and the source folder is never deleted.
- **AC-DATA-13:** A killed replacement leaves no undiscoverable complete copy: after the process is killed between staging and the swap, the staged file is named `.cp-upgrade-<hex>.part` in the destination directory, its extension is not in `FileDetectorMixin.extensions['movie']` so a library scan cannot ingest it as a movie, and it is reported by name and byte size through the existing stale-staging reporting (`renamer/main.py:430-472`), which must be reachable from the operator entry point rather than only from `_moveRenamedFiles`. Proven by creating the artefact with an aged mtime and asserting the warning names the file. (Merges AC-QA-10.)

### lens-architecture

- **AC-ARCH-1:** The operator action is its own entry point and the automatic path's shape is unchanged: it is registered as a new `addApiView('renamer.<name>', ...)` in the renamer plugin, and `scanView`, `scan`, `_processGroup` and `_moveRenamedFiles` each keep their current parameter list (pinned against literals with `inspect.signature`), with `git diff` showing no new branch and no new caller-supplied argument inside `_moveRenamedFiles`'s destination-collision block (`main.py:184-322`).
- **AC-ARCH-3:** There is exactly one destructive sequence in the codebase and both entry points call it: `replace_atomically` remains the only place a library file is destroyed (no `os.replace`, `os.remove`, `os.unlink`, `shutil.move` or `moveFile` under `couchpotato/core/plugins/renamer/` takes a library destination as its target outside `swap.py`, the existing source disposal excepted), and the announce, swap, supersede-release, dispose-source ordering appears once, in a single function both paths call. The operator entry point contains no `replace_atomically` call of its own and no second copy of that ordering.
- **AC-ARCH-6:** Producing the candidate list is bounded work per candidate and costs no identity resolution: against a fixture directory of 500 files, counting stubs over `fireEvent` assert zero `scanner.scan` calls, zero `movie.search` and zero provider/TMDB calls, at most one database read for the whole listing, and at most one `stat` per candidate.
- **AC-ARCH-7:** The operator action serialises against a running scan using the mechanism already in the file, not a second one: the existing `Renamer.renaming_started` flag under `media_lock('renamer-scan')` (`main.py:85-93`, `:137-139`), with no new lock object, module-level mutex or threading primitive introduced. Two tests prove both directions: with `renaming_started` True the operator action returns a named refusal and calls `replace_atomically` zero times, and while the operator action holds the flag `scan()` returns early without processing groups.
- **AC-ARCH-8:** The `/new/` UI layer stays presentational: after the change `grep -rn "router.post|router.put|router.delete|os.listdir|os.walk|os.scandir" couchpotato/ui/` still returns nothing, the browser reaches the action through `CP.apiBase` exactly as every other action in `movie_detail.html` does, and any new GET partial route under `couchpotato/ui/` obtains its candidate data by firing a renamer event or calling the renamer API rather than reading the filesystem itself.
- **AC-ARCH-9:** The operator-initiated outcome is a named constant declared in `renamer/replacement.py` alongside the existing `DECLINED_*` values and distinct from every automatic outcome, every refusal the operator path can return is likewise a named constant from that module, and the entry point returns the outcome as a value rather than prose, with the diff introducing no bare outcome string literal at a call site or in a test. (Merges AC-PROD-2.)
- **AC-ARCH-10:** The operator path shares no in-memory decision state with the automatic scan path: a completed operator replacement leaves behind no process-level or class-level cache keyed on the affected media, source path or destination that would change the next automatic scan's decision for that media, proven by running the operator action and then a scan over the same media and asserting the scan re-evaluates.

### lens-operability

- **AC-OPS-1:** The operator action is proven reachable through the registered entry point, not by calling the method directly: an end-to-end test drives it through the same registration path the running server uses and asserts the library file was replaced, and asserts no "Event %r was fired but nothing handles it" WARNING (`couchpotato/core/event.py:183`) is emitted during the run, so an entry point that is wired but inert fails the test rather than passing silently.
- **AC-OPS-2:** Immediately before `os.replace` runs on the operator path, exactly one record is emitted at WARNING or above that names the media id, the superseded release id, both quality rungs and both byte sizes, carries an explicit operator-initiated marker textually distinguishing it from the automatic path's record (`main.py:651`), and contains no filesystem path. Asserted with caplog at WARNING, and asserted absent from the automatic path's record.
- **AC-OPS-3:** Every refusal and failure value the operator path can reach (the `declined_*` constants in `renamer/replacement.py`, the `refused_*` and `failed_*` constants in `renamer/swap.py`) is carried through to the operator-visible outcome as that named value, and no operator-path outcome is the generic body produced by `couchpotato/api.py:76` (`{'success': False, 'error': 'Failed returning results'}`); a test asserts that even an unexpected exception inside the operator handler yields a named outcome rather than that string.
- **AC-OPS-4:** Every terminal outcome tells the operator which of three states the library is in: the library file is untouched, the library file was replaced, or the library file was replaced but a follow-up step (release bookkeeping, source disposal) failed. Each of the three is reachable in tests and returns a distinct machine-readable value in the operator-visible outcome (the response, or the polled status if the action is asynchronous).
- **AC-OPS-5:** If `release.update_status` or `release.detach_file` fails or is refused after a successful operator swap, the failure is logged at WARNING or above naming the release id (mirroring `main.py:805-852`) and the failure reaches the operator-visible outcome. A test forces each of the two failures and asserts both the log record and the returned value; a test that only asserts the log record does not satisfy this.
- **AC-OPS-6:** After a successful operator replacement the repeating refusal stops: running the scheduled scan again over the same watch folder produces no further "Destination already exists, keeping it" WARNING (`main.py:315`) for that group, tested for `default_file_action = 'move'` and for at least one of `link`/`copy`, because those two leave the source in place (`main.py:676-710`) and would otherwise re-collide on every scan interval. (The operator-facing statement of the same outcome is AC-PROD-8.)
- **AC-OPS-9:** Rollback is a plain image re-tag with no data step, and this is proven rather than asserted: a test enumerates every persisted write the operator path performs and asserts the set is confined to writes the current release already makes (release status `ignored` via `release.update_status`, and `release.detach_file`), the change introducing no new persisted field, no new status value and no new settings key that the automatic replacement path reads. The spec states the rollback procedure and who performs it.
- **AC-OPS-10:** A written recovery procedure exists (in `docs/` or in this spec) naming every refusal and failure value the operator path can return and what the operator does about each, and additionally covering how to find and recover an abandoned `.cp-upgrade-*.part` and how to correct a release left claiming a replaced path. A test asserts that every constant the operator path can return appears in that document, in the style of `tests/unit/test_backup_policy_exempt_list.py`, so the list cannot drift silently. (Trimmed at synthesis to the operator path's own outcomes; a document enumerating every constant in both modules is not traceable to this spec's goal.)
- **AC-OPS-11:** No diagnostic an operator needs in order to explain a refusal or a destruction is emitted below INFO: production runs the root logger at INFO (`couchpotato/core/logger.py:419`), so a test asserts with caplog at INFO that each terminal outcome of the operator path produces at least one record at INFO or above naming the outcome. DEBUG-only detail such as paths may exist in addition, never as the sole record. (Pairs with AC-SEC-11, which forbids paths in the INFO-and-above records.)
- **AC-OPS-12:** Every filesystem deletion the operator path performs, other than the swap itself, emits a record at INFO or above naming what was deleted (the source download, and any folder cleanup) before or immediately after it happens, so no file disappears without a line in the log that ships. A test asserts a record exists for each deletion branch the path can perform.

### Vetoed at planning

**Vetoed by `lens-simplicity`, or overridden where simplicity could not veto.**

| Dropped | Raised by | Decision | Reason |
|---|---|---|---|
| `AC-SIMP-6` (native `confirm()`, no new UI file, no `role="dialog"`) | lens-simplicity | overridden | Simplicity cannot override the accessibility floor, and a native `confirm()` cannot render a candidate list at all. The design-system modal (`CONFORMANCE.md:38`) is required instead: AC-DESIGN-6 and AC-A11Y-8. |
| `AC-OPS-7` (make `_reportStaleStagingFiles` reachable from the scheduled scan with no operator action) | lens-simplicity | vetoed | Widens the automatic path this spec's "Not in scope" says must be byte-for-byte unchanged, and the gap it names pre-dates this change. Not protected: a hidden staged copy is disk waste, not irrecoverable loss. The operator-path half is retained as AC-DATA-13. Ships separately. |
| `AC-ARCH-10`, second half (a remembered FEAT-012 refusal must not survive an operator replacement) | lens-simplicity | vetoed | FEAT-012 has not landed, so the criterion is untestable in this tree. Kept as a cross-spec note instead: a completed operator replacement is an input change that must expire any remembered decision for that media. |

**Amended rather than dropped**, because the original wording made a protected
criterion unprovable: `AC-SIMP-1` (file budget widened to cover the entry point,
an optional UI partial route and the recovery note), `AC-SIMP-2` (`replacement.py`
may gain outcome constants only, so AC-ARCH-9 can put the operator outcome beside
its siblings), `AC-SIMP-7` (two new e2e files permitted, because
`playwright.config.ts` matches the accessibility and mobile projects on
`*.a11y.spec.ts` and `*.mobile.spec.ts`).

**Merged as duplicates**, substance retained under the ID named: `AC-ARCH-2` into
AC-DATA-10 and AC-SEC-6; `AC-ARCH-4` into AC-SEC-1 and AC-DATA-1; `AC-ARCH-5`
into AC-SEC-2; `AC-DATA-11` into AC-QA-5; `AC-DESIGN-12` into AC-A11Y-13;
`AC-OPS-8` into AC-QA-7; `AC-OPS-13` into AC-DESIGN-3; `AC-PROD-2` into
AC-ARCH-9; `AC-PROD-5` into AC-DESIGN-1; `AC-PROD-6` into AC-DESIGN-10;
`AC-PROD-9` into AC-DATA-10; `AC-QA-6` into AC-DATA-6; `AC-QA-8` into AC-DATA-5;
`AC-QA-10` into AC-DATA-13; `AC-QA-11` into AC-PROD-8; `AC-QA-13` into
AC-DESIGN-8 and AC-A11Y-6.

## Vetoes and trade-offs

| Item | Raised by | Decision | Rationale |
|---|---|---|---|
| Teach the upgrade path about DV profiles / HDR formats | orchestrator | declined by owner | Largest option, on the code path that destroyed files twice. An explicit operator action solves the owner's real workflow without touching automatic replacement. |
| Do nothing, handle by hand each time | orchestrator | declined by owner | Recurs on every DV Profile 5 release. |

## Risks

Ranked by recoverability. **This is the highest-risk change in the current
backlog** and should be reviewed as such.

- **Irreplaceable: it deletes a media file, by design.** A defect that picks
  the wrong destination destroys a film the owner did not choose. Two previous
  attempts at replacement did exactly this. The mitigation is that identity
  comes from an explicit operator choice rather than an inference, but a defect
  in *resolving* that choice to a path reintroduces the same failure.
- **Irreplaceable: bypassing `_identityIsAsserted` for the operator path could
  leak into the automatic path**, re-enabling the class of destruction the
  guard exists to prevent. A test must prove the automatic path still refuses a
  `search`-identified group after this change.
- **Expensive: the source file is consumed.** If the swap commits and the
  bookkeeping does not, the release record and the file on disk disagree.
  `replace_atomically` already orders this so the recoverable half loses
  (`renamer/main.py:271-291`); that ordering must be preserved.
- **Cheap: the retry loop.** Fixing it is a small, separate change with no
  destructive component and could ship first, independently.

## Affected files

| Path | Change |
|---|---|
| `couchpotato/core/plugins/renamer/replacement.py` | An operator-initiated outcome distinct from every automatic one |
| `couchpotato/core/plugins/renamer/main.py` | Entry point for the operator action; automatic path unchanged |
| `couchpotato/ui/templates/partials/movie_detail.html` | The action, its file picker, and its confirmation |
| `tests/unit/` | The automatic path still refuses; the operator path proceeds; the swap still verifies size and containment |

---

## Review cycle

*(To be filled by the review cycle.)*


## Blocking preconditions before this is ever enabled

Recorded 2026-08-31 from two independent adversarial reviews of the
shipped-disabled change. These are not nice-to-haves: each was measured,
and each must be closed and proven before `operator_replace_enabled` is
turned on for a real library.

1. **The setting is a one-way control today.** Route registration is read
   ONCE in `Renamer.__init__`; the template reads the setting fresh on
   every request. So turning the feature OFF hides the control and leaves
   the three routes live until a restart. Measured through the real
   dispatcher: after disabling via `settings.save`, a plain GET returned
   success and the library file went from 2600 to 27900 bytes, sha256
   changed. The operator sees "off" and the delete endpoint still works.
   That is the emergency-stop direction, which is the worst one to have
   broken. Deliberately NOT fixed in the shipping change, because the
   default makes it unreachable and every touch of this path during
   remediation introduced something new. **Fix shape, additive so it does
   not replace the registration gate the owner chose after three failed
   in-handler guards:** a second, independent read of the same key at the
   top of each of the three views, so a route exists only if the flag was
   on at boot AND answers only while it is still on. Until then, the
   settings description carries the restart requirement in both directions.

2. **`settings.save` is not in `ORIGIN_CHECKED_API_ROUTES`**
   (`couchpotato/__init__.py`), so the switch that arms three
   origin-checked destructive routes is itself less protected than they
   are. Measured: a request with NO Origin and NO Referer wrote
   `operator_replace_enabled = 1` and persisted it to `config.ini`. Not a
   way in today (it needs a restart AND the api_key, which a cross-origin
   caller cannot read), and pre-existing rather than introduced here, but
   this change is what made it consequential. Weigh the fix carefully: a
   header-stripping proxy would then lock the operator out of ALL
   settings, which is the same reasoning that keeps the logout route
   fail-open.

3. **There is no longer any end-to-end coverage of the real destructive
   route.** The three operator E2E specs enable the feature through the
   template gate and intercept every operator fetch themselves, which is
   correct while the feature ships off, but it means no test drives the
   real route through a real server any more. Restore that before
   enabling, or the re-enablement review will be reading code rather than
   watching behaviour.

4. **Dead CSS** at `couchpotato/ui/templates/base.html` still names
   `[data-testid="operator-replace-modal"]` outside the gate, so it ships
   on every page. Cosmetic, no behaviour, recorded so nobody rediscovers
   it and mistakes it for a leak.

`tests/unit/test_operator_route_does_not_forge_its_own_baseline.py` must
survive all of this unchanged. It pins the defect that was reintroduced
three times, and it has been independently re-proven load-bearing twice.
