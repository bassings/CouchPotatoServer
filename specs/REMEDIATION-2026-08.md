# Remediation Plan: Audit 2026-08-02

Resolves every finding in the 2026-08-02 repository audit, plus the outstanding
half of FEAT-009. Sequenced into six milestone-sized PRs, each passing the full
local review gate before push.

**Baseline:** `bd4d69b8` (master, clean tree).

## Decisions taken (Scott, 2026-08-02)

1. **Auth fix shape:** add an explicit `auth_required` setting defaulting to ON
   whenever a password is set. Username becomes optional (blank = any username
   accepted). Open-on-LAN stays supported but must be chosen deliberately, and
   logs a startup warning. *Not* a hard fail-closed, so no existing install
   silently loses access on upgrade.
2. **Delivery:** milestone-sized PRs, each with the full `make verify` +
   ≥2 `code-reviewer` agent gate. Quick wins are distributed to the PR whose
   theme they match rather than batched at the end: the security-relevant ones
   are too cheap and too live to sit behind three other PRs.
3. **FEAT-009 Part B (upgrade replacement) is in scope**, as its own PR. It is
   not an audit finding, but it lives on the same destructive code path the
   audit found untested (`moveFile`), so it is sequenced behind those tests
   rather than run as an independent workstream.
4. **No schedule pressure. Do not split PR 1 to unblock later PRs.** It was
   suggested and declined (2026-08-02): PR 1's whole job is making later
   verification trustworthy, so fragmenting it to start PR 2 sooner trades away
   the thing it exists to provide. Thoroughness over sequencing speed applies
   throughout: where this plan offers a cheaper option and a more correct one,
   take the more correct one.
5. **PR 1 fixes the `moveFile` data-loss defects rather than only pinning them**
   (2026-08-03, after the planning cycle). PR 1 was scoped "no runtime behaviour
   change"; planning found three verified defects on that path that delete the
   user's download or corrupt the library. The precedence order puts
   irrecoverable loss above a self-imposed scope constraint, so they are fixed
   here, TDD: see T1.8. `AC-SIMP-1` is amended accordingly.
6. **The renamer re-entrancy lock moves ahead of PR 4** (2026-08-03). Two
   concurrent `moveFile` calls to one destination destroy a file and both return
   `True`. PR 4 adds a delete to that exact path, so shipping the delete before
   the lock turns "one download lost" into "the library copy lost too".

## Facts established before planning (verified, not assumed)

These change the work, so they are recorded here rather than left as assumptions:

- **`open()` never runs `schema.sql`**: only `create()` does
  (`sqlite_adapter.py:208-219`; the comment at `:217` states it). Any new index
  must ship with an idempotent self-upgrade call in `open()`, or it reaches
  fresh installs only and does nothing on production. This is the single
  highest-value gotcha in this plan.
- **`/getkey/` has no live consumer.** Only `couchpotato/simple_healthcheck.py:76`
  and `couchpotato/integration_test.py:156` call it; `simple_healthcheck.py` is
  referenced by nothing (the Docker HEALTHCHECK hits `/`, `Dockerfile:89`), and
  the JS client described in `specs/SEC-003-password-hashing.md` went away with
  the legacy UI. Gating it is safe; both files are dead code.
- **`db.opened` appears only at `database.py:402`** (the fossil migration): the broken compat surface is on a dead path, so deletion beats repair.
- **No `download_info` index exists** in `schema.sql`: the `release_download`
  fix needs one added, subject to the `open()` gotcha above.
- **`get_many()` defaults to `with_doc=True`** (`sqlite_adapter.py:857-858`), so
  fixing the re-fetch inside `query()` fixes all 44 `with_doc=True` call sites
  at once.
- **FEAT-009 state:** Part A shipped (`copyIdentity`/`copy_id`,
  `release/main.py:200-293,719-728`). Part B's *safety* half shipped (the
  `skipped = True` guard, `renamer/main.py:151-157`). Part B's *replacement*
  half is unimplemented: `renamer/main.py:154-157` still skips when the
  destination exists, and `remove_lower_quality_copies` is declared at
  `renamer/api.py:135` and read nowhere in the codebase.
- **`QualityPlugin.qualities` is a genuine global ordering**
  (`quality/main.py:26-38`, index 0 = 2160p → 11 = cam; "a lower number means
  higher quality"), so the ranking primitive FEAT-009 asks for exists.
  Conversely `isHigher` returns `'higher'` for any quality absent from the
  profile (`:542-548`): re-confirming the measurement that killed attempt #2.

## Process (per CLAUDE.md rules 1, 3, 4, 9, 10)

Every PR follows the same loop:

1. Delegate implementation to the `implementer` sub-agent: TDD, RED confirmed
   for the right reason before GREEN. Agents commit locally and **stop**.
2. Orchestrator validates against the repo, not the report: read the diff, run
   the command, confirm each new guard was proven load-bearing (break it, watch
   it fail, hash-verify the restore).
3. `make verify` green locally.
4. ≥2 independent `code-reviewer` agents on the branch diff, fresh context,
   different lenses. Iterate until clean; reject marginal nits with evidence.
5. Push, PR, merge. **No production deploy**: that is a separate, explicitly
   agreed step (rule 6).

---
## PR 1: M0: Safety net

> **Revised 2026-08-03 after the planning cycle.** Six lenses ran
> (security, QA, data, operability, simplicity, accessibility). Every task below
> changed. The original PR 1 would have shipped a fix that fixed nothing (T1.5),
> a fix that introduced a worse bug (T1.2), a deletion of a file that does not
> exist (T1.3), a sweep scoped 10× low (T1.4), and an `rm -rf` one directory
> from 139 MiB of git-unrecoverable data (T1.7). Full lens reports: session
> transcript, 2026-08-03.

**Goal:** put tests under the destructive paths, **stop the data loss those
tests uncovered**, make the E2E suite trustworthy, and stop the lint gate
floating.

**Why first:** PR 3 and PR 4 edit code adjacent to `moveFile` and the release
lookup: if M0 lands after, those fixes ship unguarded. And every later PR is
gated on an E2E suite currently red ~1-in-5 for unrelated reasons.

**Scope change from the original plan.** PR 1 is no longer "changes no runtime
behaviour". Planning found three verified data-loss defects in `moveFile`
(T1.8), and the precedence order puts irrecoverable loss above a self-imposed
constraint. Decided 2026-08-03: **fix them here, TDD**: tests pin the current
behaviour, the fix lands, the tests assert the new behaviour.

### T1.1: `moveFile` branch tests · M · risk: low

`plugins/renamer/`MoverMixin.moveFile``. The only existing tests monkeypatch it away
(`test_renamer_cleanup_safety.py:70`).

New `tests/unit/test_renamer_mover.py`. Real files in `tmp_path`, real `shutil`,
real `os`. **Stub only `self.conf` and `Env.getPermission`**: a test that stubs
`shutil.move` on a happy path is rejected; that is the shape that let this
function go unexecuted.

Fixtures use distinct, asserted content (`'THE DOWNLOAD'` vs `'THE LIBRARY
COPY'`) and ≥1 MiB payloads with SHA-256 comparison, so a size-only check cannot
pass a content test.

- **AC-QA-1** `move`: destination holds the source's exact bytes, source gone,
  returns `True`, mode == `Env.getPermission('file')`.
  *Break:* `shutil.move` → `shutil.copy`; the "source is gone" assertion fails.
- **AC-QA-2** `copy`: source survives byte-identical, destination is an
  **independent** file: assert `st_ino` differs. *Break:* swap `copy` for
  `link`; the inode assertion fails.
- **AC-DATA-2 / AC-QA-3** `link`: `st_ino` equal and `st_nlink == 2`. If the
  filesystem cannot hardlink the test **fails loudly**: it does not skip. A
  silent skip is how this branch stayed untested.
- **AC-QA-4** `symlink_reversed` happy path: destination is a regular file with
  the content; `old` is a symlink whose `realpath` is `dest`.
- **AC-QA-5** `use_default=True` reads `default_file_action`, `False` reads
  `file_action`. Set the two to **different** branches and assert which ran by
  observing the filesystem, not a mock's call args. *Break:* delete the
  `if use_default:` block at `:23-24`.
- **AC-DATA-3 / AC-QA-7** Failed move, **equal-size** destination: the source
  **is** unlinked, returns `True`. Docstring states the check is size-only.
  *Break:* `os.unlink(old)` at `:34` → `pass`.
- **AC-DATA-4 / AC-QA-8** Failed move, **equal size, different content**: the
  source is destroyed and the corrupt destination kept. `xfail(strict=True)`
  with reason "recovery verifies size, not content": the day a checksum is
  added this XPASSes and the suite reds, forcing acknowledgement.
- **AC-DATA-5 / AC-QA-9** Failed move, **short** destination: source survives
  byte-identical, partial destination removed, **exception propagates**.
  *Break, two directions:* `os.unlink(dest)` at `:37` → `pass`; delete `raise`
  at `:38`.
- **AC-DATA-6** Failed move where the **source no longer exists**:
  `os.unlink(dest)` is never reached and the destination keeps full content.
  This is the regression pin against "hardening" `os.path.getsize(old)` at
  `:32`: today the `FileNotFoundError` is the *only* thing preventing the
  `else` branch deleting the last copy.
- **AC-DATA-9 / AC-QA-13** `link` fallback, copy succeeds: `old` is a symlink
  resolving to `dest`, **no stray `<old>.link`**. *Break:* delete
  `os.rename(old_link, old)` at `:64`.
- **AC-DATA-10** ~~`link` fallback, copy fails part-way: source survives, a
  truncated file sits at `dest`, and a **second** call raises `Destination
  already exists`: the destination-poisoning recorded as known behaviour.~~
  **INVERTED at the second review round, 2026-08-06.** Accepting the
  poisoning was itself the planning error. `link` is the shipping default and
  its hardlink fails whenever the download directory and the library are on
  different filesystems, so this is the likeliest branch in the function to
  meet a full disk -- and the accepted outcome was a truncated file at the
  library filename that `_moveRenamedFiles` then skipped on every subsequent
  run, with the scanner attaching it to the movie. The criterion now reads:
  `link` fallback, copy fails part-way: source survives, the partial `dest`
  is **removed**, and a **second call succeeds**. *Break:* drop the
  `_discard_partial_destination` call from the fallback.
  Left visible rather than rewritten silently, because a stateless reviewer
  reading the old text would have filed the correct behaviour as a
  regression -- which is exactly the mechanism that produced the
  fix-the-instance-miss-the-class history this PR keeps hitting.
- **AC-DATA-10b** *(added at the second review round; corrected at the
  fourth, which found it mis-enumerated)* **Every branch of `moveFile` that
  writes bytes to `dest` removes a SHORT destination on failure, and never
  removes an equal-size one.** Four byte-writing branches, **three** helper
  call sites plus one inline equivalent:
  - `copy`, `symlink_reversed` and the `link` fallback each call
    `_discard_partial_destination`. *Break:* remove any one call; a distinct
    named test reds for each.
  - the default `move` branch implements the property **inline**, with
    different edge semantics (`os.path.exists` rather than `lexists`, and on
    an equal-size destination it unlinks the SOURCE and returns True). Pinned
    by `test_failed_move_with_a_short_destination_...`.

  **And no branch may use a composite `shutil` call whose non-copy half can
  fail alone.** `shutil.copy` is copyfile+copymode; `shutil.move` falls back
  to `copy2`, which is copyfile+copystat. Either one failing after the bytes
  land leaves a COMPLETE destination that the helper correctly refuses to
  remove and the `lexists` guard then blocks for ever. `copy` and the `link`
  fallback use `shutil.copyfile`; `symlink_reversed` passes
  `copy_function=shutil.copyfile`. The default `move` deliberately does not,
  because it recovers on its own and mtime preservation is worth keeping on
  the most common path.

  This criterion was written to stop a branch being missed by enumeration and
  was itself mis-enumerated twice: first claiming four call sites where three
  exist, then covering `shutil.copy` while `shutil.move` had the same shape.
  Recorded rather than quietly corrected, because that is the finding.
- **AC-QA-14** `link` with both `link()` and `symlink()` failing: degrades to a
  plain copy, both paths exist, returns `True`.
- **AC-QA-18** `os.chmod` raising is swallowed; the move still returns `True`
  and the destination is intact. Monkeypatch `os.chmod`: a permission trick is
  unreliable when the suite runs as root in Alpine.
- **AC-QA-12** Failed move with a **directory** at the destination: assert
  "raises, and the source is intact": **not the errno**. Measured
  `PermissionError` on macOS, `IsADirectoryError` on Linux; an errno assertion
  is green-on-macOS, red-on-Alpine.
- **AC-DATA-15 / AC-QA-19** The `os.name == 'nt'` branch carries an explicit
  `skipif` whose reason **cites the `os.popen` string-concatenation at
  ``moveFile`'s `os.name == 'nt'` branch (`os.popen`/`icacls`)`**, so the gap is knowingly uncovered rather than silently
  absent. (`lens-security` flagged that line as command injection reachable
  from indexer-supplied release names on Windows with `ntfs_permission`. Not
  PR 1's to fix: filed to PR 3, which already edits `renamer/`.)
- **AC-DATA-16** Hermetic: every path derives from `tmp_path`; the suite passes
  twice consecutively; `git status --porcelain --ignored` unchanged; `.config/`,
  `test_data/` and `.e2e-data*` mtimes unchanged.
- **AC-SEC-14** Every path passed to `moveFile` is asserted to be a child of
  `tmp_path`. A test for the `os.unlink(old)` branch that resolves outside the
  fixture is the one way this PR can itself destroy data.
- **AC-QA-21** `test_renamer_mover.py` runs in **< 2 s** and contains no
  `time.sleep`. Baseline to protect: 1936 unit tests / 29.0 s on CPython 3.14.6.
- **AC-DATA-17 / AC-QA-22** The whole file passes under `./scripts/test-local.sh`
  (Alpine/musl). Every measurement behind these criteria is macOS/APFS;
  hardlink, symlink and `chmod` semantics differ. An assertion that cannot hold
  on both is skipped with a reason naming the platform and syscall: never
  weakened to pass everywhere.

### T1.8: Fix the three data-loss defects in `moveFile` · M · risk: **high**: NEW

All three verified by execution during planning. TDD: the T1.1 tests pin current
behaviour first, then the fix lands, then the assertions invert.

**(a) A directory at the destination is treated as a successful move.**
``moveFile`'s destination-exists guard` tests `os.path.exists(dest) and os.path.isfile(dest)`, so a
directory does not fire the guard. Measured: the file moves *inside* it as
`dest/<original basename>`: unrenamed: `os.chmod(dest, 0o644)` at `:69` then
strips `+x` (measured `traversable: False`), and `True` is returned, so
`_moveRenamedFiles` sets `moved_any=True` and cleanup deletes the source folder.
*Fix:* test `os.path.exists(dest)` (or `lexists`) alone.

**(b) The hardlink fallback unlinks the source before the rename.**
the `link` fallback. Measured with `link()` and `os.rename` both failing: `old`
gone, stray `<old>.link` left, return `True`. *Fix:* drop `os.unlink(old)` at
`:63`, use `os.replace(old_link, old)`: atomic, never leaves `old` absent.

**(c) `symlink_reversed` swallows a failed move and returns `True`.**
the `symlink_reversed` branch. Measured: move fails, exception swallowed, symlink
then fails and is swallowed at `:50-51`, `chmod` fails and is swallowed at
`:72-73`, returns `True` with the source unmoved and nothing at the destination.
`_moveRenamedFiles:160-162` then sets `moved_any=True`, `skipped` stays `False`,
and `:174-177` calls `deleteFolder(parentdir)`: **on a full disk or a dropped
NAS mount, the completed download is deleted and nothing reaches the library.**
*Fix:* re-raise (or return falsy) when the move fails in this branch, so the
existing `skipped` guard engages.

- **AC-DATA-12 / AC-QA-17** Each fix is proven at the **caller** level, not just
  in `moveFile`: drive `Renamer._moveRenamedFiles` with `cleanup=True` against a
  real filesystem and assert the source folder is **not** deleted. The unit-level
  assertion alone is a curiosity; the caller-level one is the data-loss guard.
- **AC-DATA-8 / AC-QA-11** After (a), a directory at the destination raises and
  neither file is touched. PR 4 builds its replace-or-skip decision on this same
  guard, so it may not inherit the old behaviour quietly.
- **AC-QA-15** After (b), no stray `<old>.link` survives any failure ordering.
- Every fix is proven load-bearing by reverting it, watching the test fail, and
  confirming via `git diff` that the revert landed before restoring.

### T1.2: `correctRelease` tests + the `:419` fallback · M · risk: medium

**The fix sketched in the original plan was wrong.** Verified against a real
`SQLiteAdapter` with two quality rows:

```
db.get('quality', None, with_doc=True) -> cam      # first row, no error
db.get('quality', 'nope')              -> KeyError  # correct
```

`_query_index` treats `key is None` as "no filter", so the natural repair: `quality.get('identifier')` on a falsy `quality`: resolves `preferred_quality`
to Cam, whose `size_min`/`size_max` gates pass almost any release, in the
function that decides what gets downloaded.

**And `:419` is not the only crash on that path.** `quality.single()`
(`quality/main.py:128-142`) returns a dict with **no `custom` key**: it is
grafted on only at `searcher.py:326`: so `:429` raises `KeyError: 'custom'`
when `searcher.correct_3d` is falsy; and for an unresolvable identifier
`single()` returns `{}`, so `:433` raises on `size_min`.

- **AC-DATA-18 / AC-QA-29** When `quality` is falsy (`None`, `{}`, `False`),
  `correctRelease` returns `False` with a logged reason: it does **not**
  resolve a quality from the database.
- **AC-QA-30** The fallback path returns a verdict without raising for (a)
  `correct_3d` stubbed **falsy** and (b) an unresolvable identifier. A test that
  stubs `correct_3d` truthy passes **incidentally** and leaves two live crashes.
- **AC-DATA-19** Every accept/reject assertion uses **two** fixtures differing
  only in the key under test. A one-row fixture passes against a key-ignoring
  lookup: the defect class this repo has already shipped twice.
- **AC-QA-23/24/25** Happy path `True`; wrong quality → `False`; banned-word →
  `False`. **Assert the rejection reason via `caplog`**, not just the verdict: a bare `assert result is False` passes for any of six reasons.
- **AC-QA-26** Size gates: below `size_min` → `False`; above `size_max` →
  `False`; **`size == 0` (unknown) is not rejected**.
- **AC-QA-27** Retention: `seeders is None` and `age > retention` → `False`;
  `age == retention` **not** rejected (the `<` boundary at `:411`); a torrent is
  never retention-rejected.
- **AC-QA-28** `media['type'] != 'movie'` returns **`None`**, not `False`: `providers/base.py:361-370` does `if is_correct:` then `float(is_correct)`, so
  the distinction is load-bearing.
- **AC-SEC-13** At least one release rejected today by each of the quality,
  word and size gates is still rejected after the fix, with the reason asserted.
  `correctRelease` is the only filter between indexer-supplied metadata and a
  queued download.
- Fixtures build quality dicts the way `QualityPlugin.single()` does (static
  entry merged with a DB doc), **not** hand-rolled minimal dicts: a hand-rolled
  dict that happens to carry `custom` hides AC-QA-30.

### T1.3: Delete dead files, wire `tests/integration/` · S · risk: low

**Corrected:** the original list named `test_startup_local.py`, which is
gitignored (`.gitignore:33`) and untracked. Deleting untracked local files is
not the implementer's business. Two root files are tracked, not three.

Delete: `couchpotato/simple_healthcheck.py`, `couchpotato/integration_test.py`,
`couchpotato/environment_test.py`, root `test_migration_local.py`,
`test_sqlite_adapter.py`, `tests/e2e/test_existing_user.py`,
`test_fresh_install.py`, `test_real_data_migration.py`, `tests/e2e/__init__.py`,
`ui-prototype/index.html`, and `pytest.ini`'s now-dead
`--ignore=tests/e2e/test_real_data_migration.py`.

- **AC-QA-36** The two `tests/e2e/test_*.py` suites are **deleted, not wired**.
  Measured: 15 tests, 0.02 s, asserting that `os.makedirs` works and that fields
  exist in a JSON fixture. They import no application module, so no product
  regression can turn them red.
- **AC-QA-34** `tests/integration/` is executed by **both** `verify.sh` and
  `ci.yml`. Measured cost: 38 tests, 2.4–3.2 s. `test_duplicate_detection.py` is
  the direct regression net for the `_query_index` defects PR 3 edits.
- **AC-QA-35 / AC-DATA-22** `test_real_database.py` **moves out of the executed
  path** (decided 2026-08-03): to `tests/local/`, outside `pytest.ini`'s
  `testpaths`, with a module docstring stating it is a local-only tool requiring
  `/var/media/config_backup.zip`. Its 7 tests are gated on a 39 MB machine-local
  file that will never exist on a runner; wiring them in place would have bought
  7 permanent silent skips and let "38 integration tests now run in CI" become a
  claim that is only true on one laptop. CI gets **31 tests that can actually
  fail**, and the reported count means what it says.
  **The real backup must never be committed or uploaded as an artifact**: it
  carries live credentials, real library paths and ~849 media documents. State
  that in the docstring so the next person does not "fix" the relocation by
  supplying the fixture via a CI secret.
- **AC-DATA-23** ~~If the round-trip migration test is kept:~~ **Unconditional,
  amended at review 2026-08-06.** The conditional form had no owner and was
  still unwritten when the PR was otherwise complete: the test was kept, and
  nobody was accountable for the criterion. Running the migration **twice**
  yields the same document count, with no duplicated `_id` and no duplicated
  `media_identifiers` row (`verify()` compares only the `documents` table), and
  the source CodernityDB directory is **byte-identical afterwards**, hashed per
  file. *Break:* a plain `INSERT` in `insert_bulk`, and a stray write into the
  source from `read_codernity_docs`; each must red.
- **AC-QA-38** The new `check_test_traps.py` rule keys on the **runner
  invocations** in `verify.sh` + `ci.yml`, not on `pytest.ini`'s `testpaths`.
  `testpaths = tests` already "covers" `tests/integration` while no runner
  executes it: a rule anchored on `pytest.ini` passes today against an orphaned
  suite and is therefore vacuous. *Break:* delete the `tests/integration`
  invocation from `verify.sh`; the guard must red.
- **AC-DATA-21** The guard **reports and never removes**, and enumerates from
  `git ls-files` rather than a filesystem walk, so an untracked local scratch
  file can neither fail the gate nor be swept up by a later "fix the finding".
- **AC-QA-38b** *(added at review 2026-08-06, see spec gap 9)* The guard's
  **predicate** counts **both** pytest naming conventions, `test_*.py` and
  `*_test.py`. `pytest.ini` narrows `python_files` to the first, which is
  exactly what made the suffix form dangerous: `couchpotato/settings_test.py`,
  `couchpotato/softchroot_test.py` and `couchpotato/plugins/browser_test.py`
  were tracked, read like a live suite, and were collected by nothing. They are
  **relocated into `tests/unit/`, not deleted** — 24 of their 26 tests passed
  immediately and the other two were failing on a live defect. *Break:* remove
  the suffix branch; the predicate's own unit test must red. (Every other test
  of this rule injects `tracked_files`, so none of them exercises the predicate.)
- **AC-SEC-3** After the deletions, `docker build` produces an image where
  `ls /app/couchpotato/simple_healthcheck.py` and `ls /app/test_*.py` return "no
  such file". Verified against the built image: these five files ship in
  `:latest` today (confirmed by pulling it).
- **AC-OPS-12** Before `simple_healthcheck.py` is deleted, the **production**
  compose at `/var/lib/plexmediaserver/CouchPotato/` is grepped for
  `simple_healthcheck` and the result pasted into the PR. In-repo evidence is
  complete (no consumers; the Docker HEALTHCHECK at `Dockerfile:89` uses stdlib
  `urllib` against `/`); the prod file is the only unchecked consumer.
- **AC-SEC-5** `/getkey/` is byte-identical after this PR, and
  `grep -rn getkey` returning only `couchpotato/__init__.py` and
  `tests/unit/test_fastapi_web.py` is captured in the PR body as the standing
  evidence for PR 2's "no live consumer" premise.

### T1.4: Vacuous E2E tests: enumerate, then delete or fix · M · risk: low

**Rescoped.** The original named 2 sites and estimated S. Measured population:
**~21 tests with zero assertions outside a conditional**, across 5 files: 30 conditionals in `interactions.e2e.spec.ts` (19 of its tests assert only
`checkNoErrors`), 11 in `movie-detail.spec.ts`, 7 in `functional.e2e.spec.ts`,
5 in `settings.spec.ts`, 2 in `navigation.spec.ts`. And the named site was
wrong: `interactions.e2e.spec.ts:338` has `checkNoErrors` **outside** the
conditional. `navigation.spec.ts:75` is a true case.

Rule: **enumerate the closed list first.** For each, the choice is **delete** or
**make unconditional**: not "fix". A conditional whose precondition is
guaranteed (the seeded movie, the desktop viewport) becomes unconditional; the
rest assert both branches or go.

- **AC-SIMP-8 (decided 2026-08-03)** Two deletions, then repair the rest:
  1. **One of the two sidebar-collapse tests goes.** `navigation.spec.ts:75` and
     `interactions.e2e.spec.ts:65` assert the same behaviour. Keep
     `navigation.spec.ts:75` (made unconditional per AC-QA-39) because it is
     also the suite's only assertion of the collapse control's accessible name
     (AC-A11Y-12); delete the `interactions` one.
  2. **`functional.e2e.spec.ts` is deleted in full**: 6 tests, 7 conditionals,
     named coverage (add a movie, trailer modal, TorrentPotato test button,
     settings save) duplicated by `interactions.e2e.spec.ts` and `search.spec.ts`.
     **Precondition:** before deleting, map each of its 6 tests to the spec that
     covers the same behaviour and paste that mapping into the PR. If any test
     has no counterpart, it is repaired and kept rather than deleted: deleting
     on the assumption of duplication is how real coverage disappears.
  The remaining ~14 vacuous tests are **repaired**, not deleted. Deleting more
  aggressively was considered and rejected: without a per-test coverage check
  the saving is not worth the risk.
- **AC-QA-39 / AC-A11Y-12** `navigation.spec.ts:75-88` asserts unconditionally.
  The `chromium` project is desktop-only (`playwright.config.ts:114` ignores
  `*.mobile.spec.ts`), so the visibility guard protects nothing. That `if` also
  contains the suite's **only** assertion that the sidebar collapse control has
  an accessible name. *Break:* remove the `aria-label` from the template: the
  test must red. It cannot today.
- **AC-QA-40** `interactions.e2e.spec.ts:329` either exercises a real skip or is
  renamed. Measured cause: `mockSuggestionsCharts` (`helpers.ts:51-75`) returns a
  card with **no Skip control**, so the test burns 5 s and asserts only
  `checkNoErrors`. A test whose name promises behaviour it never touches is
  worse than no test: it closes the question.
- **AC-A11Y-7** The accessibility suite carries the same defect and is in scope:
  `accessibility.a11y.spec.ts:285-289` assigns the computed outline and never
  asserts it (so the "keyboard accessible" test says nothing about a visible
  focus indicator), and `:305` `expect(await img.getAttribute('alt')).toBeDefined()`
  **cannot fail**: verified: `expect(null).toBeDefined()` passes, and
  `getAttribute` returns `null` for a missing attribute. Assert a non-zero image
  count first, then assert the attribute is a string.
- **AC-QA-42 / AC-A11Y-3** Enforceable version (§9): a `check_test_traps.py`
  rule flagging `expect(` inside an `if (await …isVisible()/…count())` body
  under `tests/e2e/**`, with a justification-comment opt-out, proven in **both**
  directions *and* proven to fail when the opt-out is used without a
  justification. `AGENTS.md:104-106` currently asks a human lens to look for this
  every review; a rule retires that.
- **AC-QA-43** Each repaired test is proven load-bearing by removing the element
  from the template, watching it red, restoring, and hash-verifying the restore.

### T1.4b: Close the accessibility guard's own gaps · S · risk: low: NEW

Found by `lens-accessibility` while checking whether the a11y guard survives
T1.7. All are in the existing suite, all cost **zero** today (live probes of
Wanted, Available, Add, Settings, Wizard found no violations at any impact, in
either theme, and at Pixel 5 width).

- **AC-A11Y-8** `checkA11y` (`accessibility.a11y.spec.ts:37-46`) stops filtering
  by `impact === 'critical' || 'serious'` and asserts on the full WCAG-tagged
  violation list. It is the assertion for 5 of the 18 tests, and the same file
  documents the identical bug one notch tighter at `:578-591`, where an
  `impact === 'critical'` filter made the contrast test unable to fail while two
  toasts were failing 1.4.3.
- **AC-A11Y-9** `.withTags()` at `:13` gains `wcag22aa` (currently stops at
  `wcag21aa`), so 2.5.8 target-size and 2.4.11 focus-not-obscured are exercised.
  The project standard is WCAG 2.2 AA; the automated floor is currently 2.1 AA.
- **AC-A11Y-10** At least one page-level sweep runs with `cp-theme` seeded to
  `dark` via `addInitScript` **before** navigation, asserting
  `classList.contains('light') === false` so it cannot silently run in the wrong
  theme. Measured: the default with no localStorage is **light**, so every
  page-level scan today is light-only: the same blind spot that let the dark
  success toast ship at 3.30:1.
- **AC-A11Y-11** `small-screen.mobile.spec.ts:159-165` stops filtering to
  `button-name` + `target-size`, or names its ignored rule ids in an allowlist
  with a reason.

### T1.5: Pin ruff for real · S · risk: low

**Corrected: the original fix was a no-op.** Three lenses independently
concluded this. `.github/workflows/ci.yml:35` (`ruff>=0.9.0`) and `:134`
(`ruff>=0.15.16`) are unquoted shell redirections: verified by execution, the
`>` creates a file named `=0.9.0` and installs floating-latest. But
`requirements-dev.txt:8` is **also** floating (`ruff>=0.16.0`), so "pin, sourced
from `requirements-dev.txt`" relocates the problem rather than fixing it. Three
floors exist, none pinned.

- **AC-SEC-6 / AC-OPS-1 / AC-QA-44** `requirements-dev.txt` reads
  `ruff==X.Y.Z`, and both workflow lines install that exact version. Proven by
  reading `ruff --version` in the `lint` and `security-lint` job logs: the two
  must print the same version.
- **AC-SIMP-9 (amended)** T1.5 is confined to `ci.yml` (quoting + a single
  version literal), `requirements-dev.txt`, and `check_test_traps.py`. The
  `lint` job does **not** gain `pip install -r requirements-dev.txt`: that
  installs pytest/mutmut/coverage into a lint job for no benefit. **Duplicating
  one version string across two files is cheaper than any mechanism that removes
  the duplication.** No new workflow, no new job, no new script.
- **AC-OPS-5** `scripts/verify.sh` **fails** (not warns) when the locally
  installed ruff differs from the pin, printing both versions and the install
  command. Today's preflight (`:54`) only checks `import ruff`, so pinning CI
  without this creates a new "green locally, red in CI" class.
- **AC-QA-45 / AC-OPS-4 / AC-SEC-7** The new trap rule flags an unquoted
  `>=`/`>` in a workflow `pip install`, proven in **both** directions against
  the real file: `ci.yml:35`/`:134` reported; the correctly quoted
  `'pyyaml>=6.0'` at `:44` **not** reported; and a legitimate redirect
  (`echo x > file`) not reported. Regression test in
  `tests/unit/test_check_test_traps.py`.
- **AC-SEC-8** The `secrets` job is untouched: gitleaks stays at
  `zricethezav/gitleaks:v8.30.1`, config stays `.gitleaks.toml`, `--redact`
  stays, `.gitleaksignore` gains no entry.
- **AC-QA-46** No `=0.9.0` artefact was ever committed (checked). Say that in
  the PR body rather than implying a stray file exists.

### T1.6: Prod interpreter + repo hygiene · S · risk: low

- **AC-OPS-6** A unit test parses `Dockerfile`'s `FROM python:<ver>-alpine`
  (lines 10, 30) and asserts `<ver>` appears in `ci.yml`'s test matrix **and**
  equals `scripts/test-local.sh`'s default. It fails when either side is bumped
  alone. Modelled on `tests/unit/test_gitleaks_config.py`. *Break:* change the
  Dockerfile to `3.15-alpine`, watch it red, restore, `git diff` to confirm.
  This is the enforceable fix (§9): T1.6 alone fixes the instance and leaves
  the class.
- **AC-QA-47** `'3.14'` added to `ci.yml:147` and that leg is green. Local
  evidence: **1936 unit tests pass on CPython 3.14.6 in 29.0 s** and every
  requirement resolves on 3.14. Green on macOS is necessary, not sufficient: Ubuntu wheels are the residual risk.
- **AC-QA-48 / AC-OPS-7** `scripts/test-local.sh:11` moves off 3.12 to the
  production interpreter; `scripts/verify.sh:57`'s "3.10–3.13" message,
  `docs/development-process.md:506`, `README.md:7,15` and `CONTRIBUTING.md:5`
  all agree with the matrix afterwards.
- **AC-OPS-8** `fail-fast: false` retained so a 3.14-only failure is
  attributable. **No branch-protection edit is needed**: `test-summary`
  (`ci.yml:364-376`) already aggregates the matrix and is the required context.
  Say so in the PR.
- **AC-OPS-9** No CI **job** is renamed, removed or added-as-blocking. All 12
  required contexts report. If T1.7 restructures the E2E jobs, `ui-e2e-tests` /
  `accessibility` are renamed in branch protection in the same change.
- **AC-SEC-1 / AC-OPS-10** `.env` is added to `.gitignore` in the **same
  commit** that untracks it (`git check-ignore .env` exits 0 afterwards), and
  the consequence is written down: after pulling, `docker compose` no longer
  selects `docker-compose.local.yml`, so it pulls the published image and
  creates root-owned `/path/to/downloads`. One-line restore in the PR body and
  dev docs. Without the ignore entry the trap is left armed and CI can never
  catch it: the `secrets` job only sees tracked files.
- **AC-SEC-2** No history rewrite. Evidence recorded: `git log --follow -- .env`
  shows one commit, one content (`COMPOSE_FILE=docker-compose.local.yml`). A
  rewrite of `master` history is a larger risk than what it would remove.

### T1.7: E2E per-spec isolation · L · risk: **medium** (was: low)

Moved into M0 after challenge; **risk raised from low after planning**.

**Prerequisite: add `--port` to the runner** (decided 2026-08-03). `runner.py:28-41`
accepts only `--data_dir`, `--config_file`, `--debug`, `--console_log`,
`--quiet`, `--daemon`, `--pid_file`, so "a server per worker" is not expressible
today: the port comes from `config.ini`. The alternative (the seed writing a
distinct port into each data dir's `config.ini`) was rejected: it couples the
test harness to config-file internals and leaves the collision mode live for
anyone running two servers by hand.

- **AC-OPS-20** `CouchPotato.py --port N` binds N. When omitted, behaviour is
  byte-identical to today: the `config.ini` value wins, and no existing
  install changes port on upgrade. Pin both directions in a unit test.
- **AC-OPS-21** Precedence is explicit and tested: `--port` overrides
  `config.ini`; an invalid or already-bound port fails at startup **naming the
  port**, rather than falling back silently to the default. A silent fallback
  would reintroduce the shared-server coupling this task exists to remove
  (AC-QA-57) while every spec still reported green.
- **AC-SEC-16** `--port` does not change the bind address. The server binds
  whatever it binds today (`runner.py:253,258`); this argument selects a port,
  not an interface, and must not become a way to expose an instance more widely
  than `config.ini` would.
- **AC-SEC-16b** *(added at review 2026-08-06, see spec gap 10)* AC-SEC-16 was
  satisfied and the exposure happened anyway: `host` defaults to `0.0.0.0`, is
  absent from the settings list, and has no CLI surface, so a `--workers=N` run
  opens **N unauthenticated instances on the LAN**, each with a generated
  `api_key` and no password (`get_current_user` returns `True` when neither is
  set). Every per-worker server binds **loopback only**, fixed in the **seed
  script** rather than by adding `--host` — widening the CLI to fix this would
  defeat AC-SEC-16 itself. The write is idempotent and must **not** overwrite a
  `host` the operator already set.
- This is the second production change in PR 1 (with T1.8) and is reflected in
  `AC-SIMP-1`.

**Data-loss hazard: this is why the risk moved.** `CouchPotato.py:53` gates on
truthiness, so `--data_dir=` (empty) falls through to `Env.setting('data_dir')`
and then `getDataDir()`. Measured neighbours: `.config` 68 MiB (live database),
`test_data/` 71 MiB (gitignored, **git-unrecoverable**). `verify.sh:97,106,115`
already `rm -rf` sibling paths in the repo root.

- **AC-DATA-24** The run **fails loudly, before starting a server**, when a
  derived data dir is empty, is not under the designated scratch root, or whose
  basename does not begin with `.e2e`.
- **AC-DATA-25** Every `rm -rf` goes through **one guarded helper**, unit-tested
  with hostile inputs: `''`, `'/'`, `'.'`, `'..'`, `'~'`, `'.config'`,
  `'test_data'`, a path containing a space, and a **symlink pointing at
  `test_data/`**. Each refused. `scripts/backup.sh:244-301` documents this exact
  class on this repo and is the shape to copy.
- Prefer siting the dirs under `os.tmpdir()`, out of the repo root entirely.
- **AC-SEC-9** Dirs are named `.e2e-<spec>-data/`, **not** `.e2e-data-<spec>/`.
  Verified: `.gitignore:57` (`.e2e-*data/`) and `.gitleaks.toml:58`
  (`^\.e2e-[^/]*data/`) both require the name to **end** in "data". The existing
  `.e2e-data-mobile` / `.e2e-data-a11y` match neither, which is why
  **`make check-secrets` is red on master today** (3 findings, verified by
  running it). The naming choice decides whether that becomes ~30. Rename the
  two existing dirs to the same shape and delete the now-redundant hardcoded
  `.gitignore` lines. Testable: after a full run,
  `for d in .e2e-*; do git check-ignore -q "$d/config.ini" || echo LEAKABLE: $d; done`
  prints nothing **and** `make check-secrets` exits 0 with all dirs present.
- **AC-SEC-10** `.dockerignore` gains `.e2e-*`. Verified: it excludes `.config/`
  but not the E2E dirs, and `Dockerfile:72` copies the whole context, so a local
  `docker build` (the normal `docker-compose.dev.yml` path) bakes a live
  `api_key` into an image layer.
- **AC-SEC-11** `.config/config.ini` is byte-identical (sha256) after a full
  run, and no new `config.ini` with a non-empty `api_key` appears in `$HOME` or
  `/tmp`.
- **AC-QA-50** **A direct test of the property, not just a green suite.**
  Spec A mutates global singleton state (create/delete a category, mark the
  seeded movie done); spec B asserts the pristine state. Both orders, in
  parallel, pass. This fails today and is the only thing that proves isolation
  rather than luck.
- **AC-QA-50b** *(added at review 2026-08-06, see spec gap 11)* Spec B has a
  **happens-after edge on spec A**. As originally specified this was a race:
  Playwright gives each spec file to a different worker and runs them
  concurrently, so B reached its assertion before A had created anything and
  passed against an empty world — a green that would survive isolation being
  removed entirely. B must also distinguish "A ran on a different server"
  (the property under test) from "A ran on *this* server" (both halves on one
  worker, which proves nothing) and fail differently for each. *Break:* run B
  alone; it must red naming the missing partner, where it previously passed.
  Run the pair at `--workers=1`; it must red naming the misconfiguration.
- **AC-QA-52 / AC-A11Y-2** Acceptance bar: **≥10 consecutive full parallel runs
  green**, each with a freshly created data dir, driven by a script that stops
  on first red and prints the failing spec and worker assignment. Hand-counted
  runs do not qualify: n=3 and n=4 both came back green before n=5 found the
  flake (`docs/technical-debt.md:186`). **Green must be measured by test count,
  not exit code:** `0 skipped` and a passed-count equal to
  `--list` total. Measured during planning: at `--workers=4`, run 2 of 3 exited
  **0** while reporting `1 skipped, 17 passed`: the skipped test was the only
  axe scan of a filtered movie-detail page, and the seed data was present and
  identical to the passing run, so the cause was contention, not seeding.
- **AC-A11Y-1** No accessibility spec converts a missing precondition into a
  skip. `accessibility.a11y.spec.ts:142-150` asserts
  `expect(releasesLoaded, '<seed guidance>').toBe(true)`: FAIL, don't skip, the
  pattern `movie-detail.spec.ts:55` already documents. Proven by running the
  a11y project against an unseeded data dir and watching it **red**.
- **AC-A11Y-4 / AC-QA-56** A retry-pass cannot green the gate. **Decided
  2026-08-03: CI keeps `retries: 2` and adds `--fail-on-flaky-tests`** (present
  in the installed Playwright 1.62.0) to every Playwright invocation in
  `ci.yml`: the E2E, mobile and `accessibility` jobs, and in `verify.sh`.
  Dropping retries to 0 was rejected: it would red a PR on a genuine
  infrastructure blip. This keeps that resilience while making a fail-then-pass
  **red instead of flaky-green**, so AC-QA-52's ten runs stay measurable on the
  machine that matters. `accessibility` is a required check, so its exit code is
  the whole gate.
  *Prove it load-bearing:* introduce a deliberately flaky test (fails on first
  attempt, passes on retry), confirm the job reds, then remove it.
- **AC-QA-53** At least 3 of the 10 runs use a different worker count (2 / 4 /
  8). Playwright has no shuffle; worker count changes the file→worker
  assignment, which is the variable that produced the coupling. Ten runs of an
  identical schedule prove the schedule, not the isolation.
- **AC-DATA-26 / AC-QA-54** The run **fails** if a per-spec dir already exists
  at start. Precedent in-repo: `verify.sh:88-97` records a gate that flipped
  green→red purely from an inherited `.e2e-data`.
- **AC-QA-55** Parallel wall-clock ≤ the measured serial baseline of **4.0 min**
  (142 chromium tests, measured during planning; the debt doc's ~4.1 min
  corroborates). Above that, the isolation cost exceeded the parallelism gain
  and the trade is re-argued, not shipped.
- **AC-SIMP-12** If the isolated suite is not faster, `workers: 1` **stays** and
  only the isolation lands. Parallelism is a measured benefit or it is dropped.
- **AC-QA-58** The harness fails with "the application under test exited" rather
  than 30 tests reporting `ERR_CONNECTION_REFUSED`. Measured during planning:
  the server was SIGKILLed at test 112 of 142 and every downstream failure named
  a URL rather than the cause.
- **AC-QA-58b** *(added at review 2026-08-06, see spec gap 12)* The same holds
  **after** readiness, which is when the planning measurement above actually
  happened. The worker watches its server for the whole run, fails the run if it
  exits, and **retains the application log** at a named path — it previously
  lived only in a closure and was discarded at teardown, so the one artefact
  that could explain a mid-run failure was the one thing never kept. *Break:*
  kill the listening server mid-test; teardown must error naming the signal, the
  log file must exist, and the **process exit code** must be non-zero (checked
  explicitly: Playwright's summary line still reads "1 passed").
- **AC-A11Y-5** Isolation applies to the CI `accessibility` job too, which today
  starts its own server by hand (`ci.yml:345-350`, `--data_dir=.config`) and
  never reads `CP_E2E_DATA_DIR`. **`playwright.config.ts` disables `webServer`
  when `CI` is set**, so isolation implemented only there leaves CI running
  today's shared-state suite while local runs the isolated one: both green,
  testing different things (AC-OPS-15).
- **AC-OPS-15** *(text supplied at review 2026-08-06; it was cited above as
  satisfied while having no definition anywhere in this spec, which nobody can
  verify)* **The local gate and CI run the same suite the same way.** Every
  Playwright invocation in `scripts/verify.sh` has a counterpart in
  `.github/workflows/ci.yml` with the same project, the same worker count and
  the same `--fail-on-flaky-tests`, and neither file special-cases
  `process.env.CI` to change what is executed. *Break:* remove one project's
  invocation from either file; hard rule 4 says the local gate mirrors CI, and
  a divergence must be visible rather than inferred from two green ticks.
- **AC-OPS-16** A failed seed is **red, not skipped**. Today `ci.yml:252,285,342`
  swallow seed failure into `:warning:` with `continue-on-error: true`, and
  the workflow's own message says tests "will skip instead of running". Per-spec
  seeding turns one such chance into fifteen.
- **AC-OPS-17** After a completed **and** an interrupted `make verify`,
  `pgrep -f CouchPotato.py` is empty. A port already in use fails naming the
  port and the spec, not a 120 s `webServer` timeout.
- **AC-SIMP-11 (amended 2026-08-05)** Confined to `playwright.config.ts`, at
  most one new fixture file, `ci.yml`, `scripts/seed_e2e_data.py`, plus the
  AC-DATA-24/25 safety helper and its tests (`scripts/e2e_worker_data.py` +
  `tests/unit/test_e2e_worker_data.py` -- new files, since no existing file
  owns rm-rf safety), and `tests/e2e/isolation-a-mutate.spec.ts` +
  `isolation-b-assert.spec.ts` (AC-QA-50's direct proof; see AC-SIMP-6). No
  new npm dependency, no new config file. Both `test.describe.configure({
  mode: 'serial' })` lines and the ~40-line `workers: 1` rationale block
  (`playwright.config.ts:47-86`) are **deleted**, not amended: it argues for
  a decision this task reverses. `verify.sh` and `couchpotato/core/helpers/
  variable.py` (`removePyc`, see AC-SIMP-1) also touched -- not in the
  original file list, both load-bearing for T1.7 to work at all.
- **AC-SIMP (new)** Delete the `firefox` and `webkit` project entries
  (`playwright.config.ts:105-115`) as the **first** commit of T1.7. Verified
  dead: only `chromium`, `mobile-chrome` and `accessibility` are ever invoked,
  and CI installs chromium only. Deleting them shrinks the task before it starts.
- **Land T1.7 as the last commit of PR 1**, and take the ≥10-run measurement
  against a tree where only T1.7 changed. As written those runs would
  simultaneously validate three test deletions, a spec rewrite, a new matrix
  entry and a CI topology change: a red run would have seven candidate causes
  and the evidence the AC buys becomes uninterpretable. This does not split the
  PR and does not let PR 2 start sooner, so it is consistent with decision 4.
- **T1.7a (seed fixture) lands first** (decided 2026-08-05). The flake below
  blocks T1.7's acceptance bar, so the seeded movies are separated first: the
  already-`done` release moves onto its own movie, so the Wanted-page specs keep
  an active one. Test-fixture change only, no production code, which keeps PR 1
  in character. The restatus timing in `searcher.py` is the root cause but was
  rejected as the fix here: it is production code on the download path PR 3 also
  edits, and it does not belong in a test-focused PR.
- **A second flake source exists, independent of spec coupling** (found during
  T1.4, 2026-08-05). The app's own `app.load` to `searchAll` restatus pass can
  promote a seeded movie straight to `done` mid-run, which drops it out of the
  Wanted page's server-side `status=active` query. Both seeded movies carry an
  already-`done` release deliberately, for `release_controls.spec.ts`. Measured
  at roughly 1 run in 2 during T1.4. The old vacuous conditionals absorbed this
  silently forever; repairing them turned it into a loud, rare failure, which is
  the correct outcome but means **T1.7's ten green runs cannot be reached by
  isolation alone**. Fix the seed fixture or the restatus timing first, or the
  ten-run bar will be chasing a defect that per-spec data dirs cannot remove.
  This is pre-existing app behaviour, not a regression from this PR.
- **Note on implementation:** Playwright has **no per-spec primitive**. The
  natural implementation is per-**worker**, which is what
  `docs/technical-debt.md:184-186` and `playwright.config.ts:79-81` both
  actually recommend. Do not build a per-spec abstraction to satisfy a phrase in
  this spec when per-worker is what the tool supports.

### Simplicity constraints (verified by the orchestrator against the diff)

`lens-simplicity` runs at planning only; these are checked at review by reading
the diff, not by an agent.

- **AC-SIMP-1 (amended)** Under `couchpotato/`, the diff contains only:
  (a) `core/media/movie/searcher.py`: the `:419`/`:429`/`:433` fallback,
  (b) `core/plugins/renamer/mover.py`: the three T1.8 fixes,
  (c) `runner.py`: the `--port` argument only,
  (d) `core/media/_base/media/main.py` and/or `core/plugins/release/main.py`:
  the `has_releases` row-shape fix only (T1.9, added 2026-08-05),
  (e) `ui/__init__.py`: `partial_movies`'s `with_releases` default fix only
  (T1.9 follow-up, added 2026-08-05 -- was missing from this list, corrected
  here rather than left silently uncovered),
  (f) `core/helpers/variable.py`: `removePyc`'s `os.listdir` guard only
  (T1.7, added 2026-08-05 -- concurrent per-worker CouchPotato.py processes
  race on cleaning the shared `__pycache__` tree; reproduced directly with
  `--workers=3`, one worker crashed before binding a port),
  (h) `ui/templates/wanted.html`: the redundant `x-init="init()"` removal
  only (T1.7, added 2026-08-05 -- a double `init()` call double-registered
  the arrow-key handler, which T1.7's acceptance runs made deterministic
  once the seed grew from 1-2 to 3 Wanted movies; blocks the local gate
  hard rule 2 requires, so this could not be left red and deferred),
  (g) whole-file deletions of `simple_healthcheck.py`, `integration_test.py`,
  `environment_test.py`. **Any other modified file under `couchpotato/` fails.**
  *(Amended 2026-08-03: the original allowed only `searcher.py:419`. The
  precedence order puts irrecoverable data loss above the no-runtime-change
  constraint: see T1.8, and `--port` was added to scope as a T1.7
  prerequisite. Amended again 2026-08-05 for (e), (f) and (h).)*
- **AC-SIMP-2** `requirements.txt` unchanged; `package.json` dependencies and
  devDependencies unchanged. No new runtime or npm dependency.
- **AC-SIMP-3** No new configuration setting: zero additions to the settings
  lists in `core/_base/_core.py`, zero new `os.environ` / `Env.setting` reads
  under `couchpotato/`. *(One agreed exception: the `--port` CLI argument added
  as a T1.7 prerequisite. It is a command-line override, not a stored setting: it must not appear in the settings UI or be written to `config.ini`.)*
- **AC-SIMP-4** No new file under `scripts/`. Every new guard lands inside the
  existing `scripts/check_test_traps.py`.
- **AC-SIMP-5** Net-negative in tracked files: ≥10 deletions, and
  `git ls-files | wc -l` lower after than before.
- **AC-SIMP-6 (amended 2026-08-05)** New files under `tests/` limited to
  `tests/unit/test_renamer_mover.py`, `tests/unit/test_searcher_correct_release.py`,
  at most **one** Playwright fixture file, `tests/unit/test_e2e_worker_data.py`
  (the AC-DATA-25 safety helper's own tests -- "the safety helper and its
  tests" was explicit scope for T1.7), and **two** Playwright spec files,
  `tests/e2e/isolation-a-mutate.spec.ts` + `isolation-b-assert.spec.ts`
  (AC-QA-50's direct isolation proof -- "Spec A" and "Spec B" cannot be
  expressed as `describe` blocks in one file and still prove separate-worker
  scheduling; splitting them is what makes the file-naming/sort-order
  mechanism in their own header work at all). No new `conftest.py`, no new
  shared helper module for the mover tests: they instantiate the mixin
  directly, as `test_renamer_cleanup_safety.py` already does.
- **AC-SIMP-7** In every touched `tests/e2e/*.spec.ts`, zero test bodies remain
  wholly wrapped in a visibility/count conditional; the summed
  `grep -c "if (await"` is strictly lower after than before; no new such
  conditional is added.
- **AC-SIMP-13** `pytest.ini`'s `--ignore=tests/e2e/test_real_data_migration.py`
  is removed in the same diff that deletes the file. No dead reference to a
  deleted path survives (`grep -r` for each deleted filename returns only
  `specs/`).
- **AC-SIMP-14** No new file under `docs/`. `docs/technical-debt.md:149-186`
  (both E2E entries, resolved by T1.7) is deleted or collapsed to a one-line
  resolved note: a third entry is not added alongside them. Also correct
  `:118`, which claims `make check-secrets` "reports clean"; it is red.

### Vetoes and trade-offs

| Item | Raised by | Decision | Rationale |
|---|---|---|---|
| "Pin ruff sourced from `requirements-dev.txt` rather than duplicated" | simplicity (veto), security, operability | **Vetoed** | No criterion requires single-sourcing; the criterion is "CI does not install floating ruff". Duplicating one version string across two files is cheaper than a mechanism that removes it |
| Delete `test_startup_local.py` | simplicity, QA | **Vetoed** | Untracked and gitignored (`.gitignore:33`). Deleting untracked files is not the implementer's business |
| PR 1 changes no runtime behaviour | plan (original) | **Overridden** | Three verified data-loss defects in `moveFile`. Precedence #1 (irrecoverable loss) outranks a self-imposed scope constraint. See T1.8 |
| T1.4 "sweep it through" | simplicity, QA | **Rescoped** | 21 sites, not 2. Enumerate the closed list; most are deleted, not repaired |
| Wire `tests/integration/` into CI | simplicity, QA, data | **Accepted, conditioned** | Measured 38 tests / 2.4 s, no fixing required, but 7 tests skip permanently in CI. Conditioned on AC-QA-35 |
| Merge state-mutating specs into one serial file (the S-effort alternative to T1.7) | simplicity | **Rejected with evidence** | The mutating set is larger than three files: `movie-detail.spec.ts` and `small-screen.mobile.spec.ts` also mutate. Merging three leaves the coupling. Recorded so it is not re-proposed |
| mypy gate (T6.7, PR 6) | simplicity | **Veto overridden** (Scott, 2026-08-03) | Simplicity's objection stands on its own terms: no defect has been identified that mypy would have caught. Kept anyway, scoped to `core/db/*`, as a **preventive** gate: that package is the highest-consequence code in the repo and already typed, so the gate starts green and ratchets rather than migrating. Recorded as a deliberate override, not an unanswered veto |
| Fix `os.popen` injection at ``moveFile`'s `os.name == 'nt'` branch (`os.popen`/`icacls`)` | security | **Deferred to PR 3** | Windows-only, gated on `ntfs_permission`. PR 3 already edits `renamer/`. Recorded in the T1.1 skip reason so it is not silently uncovered |
| Fix `extractor.py:174` (`cleanup` passed into the `use_default` slot) | QA | **Deferred to PR 3** | Real argument-position bug coupling two unrelated settings, but not on PR 1's path |
| Move the renamer re-entrancy lock (T5.4) ahead of PR 4 | data | **Accepted** | Two concurrent moves to one destination destroy a file and both return `True`. PR 4 adds a delete to that path: shipping the delete before the lock turns "one download lost" into "the library copy lost too" |

### Spec gaps found at planning

Findings with no acceptance criterion behind them: each is a planning lens
catching something the *plan* missed, which is the signal the harness is meant
to produce:

1. **`make check-secrets` is red on master today** (3 findings, verified). Not
   caused by this PR; discovered while planning it. `docs/technical-debt.md:118`
   claims it reports clean.
2. **Five dead files ship in the published `:latest` image**: verified by
   pulling and listing.
3. **`.dockerignore` omits the E2E dirs**, so a local build bakes a live
   `api_key` into a layer.
4. **The a11y suite's alt-text assertion cannot fail** (`expect(null).toBeDefined()`
   passes), and `checkA11y` discards non-critical/serious violations: the same
   bug the file documents at `:578-591`.
5. **Every page-level axe scan runs light-theme only**; dark has no page-level
   scan at all.
6. **`CouchPotato.py` has no `--port`**, so per-worker servers are not
   expressible: a capability gap the plan assumed away.
7. **Concurrent `moveFile` calls to one destination** destroy a file and both
   report success (forced interleave; real-world reachability inferred from the
   unlocked check-then-set at `renamer/main.py:72-79`).

### Spec gaps found at review (PR 1)

Findings the review cycle raised that no `AC-` covers. Recorded because that
list is how the harness improves rather than merely runs:

8. **A repaired `has_releases` filter widens what a destructive path deletes.**
   `AC-DATA-*` covered the filter's correctness and `manage.py`'s cleanup was
   not in scope at all, so nothing asked the obvious follow-up: which *other*
   callers change behaviour when a filter that never filtered starts
   filtering. The answer was `media.delete(delete_from='all')` admitting
   `active` (upgrading) movies, in an unattended scan. **A criterion of the
   form "enumerate every caller of a predicate whose behaviour this change
   alters" belongs in the template**, not just in this spec.
9. **The orphaned-test rule was written against one of pytest's two naming
   conventions.** `AC-QA-38` specified what the rule keys *on* (runner
   invocations, not `testpaths`) and was right about it, but said nothing
   about what counts as a test file. Three `*_test.py` files under
   `couchpotato/` were invisible to it, and one was sitting on a live Python 3
   port defect (`FileBrowser.view()` calling `len()` on a `map`). A guard's
   *predicate* needs a criterion as much as its *anchor* does.
10. **Per-worker servers bind `0.0.0.0`.** `AC-SEC-16` correctly stopped
    `--port` from widening exposure, and was satisfied — while the harness it
    enabled opened N unauthenticated instances on the LAN, because the host
    comes from a setting with no CLI surface at all. The criterion guarded the
    argument that was added instead of the exposure that resulted.
11. **The isolation proof had no happens-before edge.** `AC-QA-50` asked for a
    direct proof of isolation and got two specs that Playwright runs
    concurrently, so the asserting half regularly ran first and passed against
    an empty world. A criterion asking for a proof between *parallel* actors
    has to say how they synchronise, or it specifies a race.
12. **Nothing watched the application under test after startup.** `AC-QA-58`
    covered the server exiting *before* readiness. A server dying mid-run —
    the same failure, ten seconds later — had no criterion, no diagnosis and
    no retained log.
13. **`AC-DATA-23` was written as a conditional** ("if the round-trip
    migration test is kept"). It was kept, and the criterion was still
    unwritten at review. Conditional acceptance criteria have no owner.

14. **`AC-SIMP-7` measured a proxy, and the proxy moved without the property.**
    It counted `if (await` occurrences in `tests/e2e/**` as a stand-in for "no
    test asserts nothing". The count fell 63 → 34 while roughly 13
    assertion-free tests survived, because moving one weak assertion outside
    the brace satisfies the count. What T1.4 wanted was "every touched test
    asserts a property named in its own title", which is not expressible as a
    diff-level count. The survivors are recorded in `docs/technical-debt.md`
    rather than being reported as done.
15. **A criterion can guard the implementation instead of the exposure, twice
    in a row.** `AC-SEC-16` guarded the `--port` argument while `host` did the
    widening. `AC-SEC-16b` was written to fix that and then guarded the
    `_bind_to_loopback` helper while the call site went untested: two review
    lenses independently deleted the call and watched the whole suite pass.
    The criterion shape that catches both rounds is **"the guard is proven at
    the call site that makes it load-bearing, not only at the function that
    implements it"**. Worth promoting into
    `~/.claude/templates/SPEC-TEMPLATE.md`.
16. **`AC-QA-11` asks for a caller-level proof that cannot exist.** It requires
    T1.8 fix (a) to be demonstrated through `_moveRenamedFiles`, but
    `renamer/main.py:154-157` refuses any pre-existing `dst` before `moveFile`
    is reached, so the caller can never drive the branch. Amended: fix (a) is
    proven at the unit level, and the file says so in
    `TestCallerLevelDataLossGuards`'s own comments rather than quietly renaming
    the test. (Cited by symbol, not line: the first draft of this gap cited a
    line range that three inserted tests had already shifted by ~90 lines,
    which is the failure mode section 7 warns about.)

### Spec gaps found at PR 1's second review round

17. **Three production security/correctness changes shipped with no AC.** The
    softchroot traversal refusal, the sqlite connection serialisation, and the
    `withStatus` `with_doc`/types fix are all production behaviour changes made
    in response to review findings, and none has a criterion. `AC-SEC-16b` and
    `AC-QA-38b` were written when the same thing happened earlier in this PR;
    these were not. **A review-driven production change needs an AC as much as
    a planned one does** -- otherwise the second review round has nothing to
    verify against and simply re-derives it.
18. **No criterion states "no method touching the connection is left
    unsynchronised".** The enumeration was done by hand, twice, by two
    different lenses. That is exactly the kind of property a mechanical check
    should own, and its absence is why `close()` was missed on the first pass.
19. **Uploading the application log as a public CI artefact is a new
    disclosure surface with no AC** saying what is permitted to appear in it.
    What was actually verified is narrower than the comment claimed: the app's
    own api_key is redacted in records emitted through logging handlers, while
    direct `print()` paths and credentials in URL userinfo or path segments are
    not filtered at all. There are none in the E2E environment, which is the
    only reason this is safe today.
20. **`AC-QA-43` ("each repaired test proven load-bearing") has no mechanism
    behind it, and three tests written to satisfy this PR's own review were
    incidentally passing** -- the interrupted-migration probe, the mixed
    read/write concurrency hammer, and the repaired text-filter test. Each was
    caught only because a lens ran a mutation the author had not. The criterion
    should say **who** runs the mutation and that the result is recorded, not
    just that it happened.
21. **A shared helper on the most destructive path shipped with no AC.**
    `_discard_partial_destination` has three call sites on the renamer's
    delete path and was verified only by tests written after it. Gap 17 listed
    three review-driven production changes with no criterion and missed this
    one, which is the fourth and the most dangerous. Now `AC-DATA-10b`.
22. **A criterion can be left pinning the behaviour its own fix inverted.**
    `AC-DATA-10` accepted destination-poisoning as known behaviour; round 2
    fixed the code and the test and left the criterion saying the opposite.
    The spec is what the review cycle verifies against, so a later round would
    have filed the fix as a regression. **When a review finding inverts an
    AC, amending the AC is part of the fix, not follow-up.**

**PR 1 acceptance:** `make verify` green **and `make check-secrets` green**;
every new test proven load-bearing (break, watch fail, `git diff`-confirm,
restore); the T1.8 fixes proven at the `_moveRenamedFiles` caller level; CI
green on the 3.14 matrix leg; no tracked test file outside the executed roots;
T1.1 green under `./scripts/test-local.sh` (Alpine); E2E suite green over ≥10
parallel runs measured by **test count**, at ≥3 different worker counts, with
retries disabled.

---

## PR 2: M1a: Authentication and web-surface security

**Goal:** close every finding where an unauthenticated request reaches something
it should not.

**Risk note:** this PR changes access behaviour on a live instance. Take
`./scripts/backup.sh` and note the current `config.ini` auth state *before*
deploying it. Recovery path (edit `config.ini`, restart) must be in the release
notes. Settings live in `config.ini`, not `settings.conf`.

### PR 2 planning cycle, 2026-08-06: what changed

Four lenses ran (security, QA, operability, simplicity). Every task below moved.
Three findings are **Critical** and two of them would have shipped a fix that
fixes nothing, which is the T1.5 failure repeating.

**Verified by the orchestrator, not taken from the reports:**

1. **The `auth_required` tri-state does not work.** All three lenses found it
   independently. `registerDefaults` materialises the literal `auth_required =
   None` into `config.ini`, and `Env.setting`'s own default is `''`, so the
   natural call returns falsy and auth stays off on every install, silently.
   The tri-state only round-trips via a `ValidationError` swallowed per auth
   check. **Use a plain `{'default': 0}` plus a one-shot startup migration.**
2. **A `sessions` table would brick login on every existing install.**
   `SQLiteAdapter.open()` runs no DDL, so a table in `schema.sql` reaches fresh
   installs only and the first login raises `no such table`. Store sessions as
   `documents` rows with `_t = 'session'`: zero DDL.
3. **A session lookup reaching `_query_index`'s generic branch authenticates any
   cookie.** Executed: with two session documents present,
   `db.get('session', 'TOKEN_B')` returned a **media** document, because the
   `else` branch discards the key. `release_download` is a live example of
   exactly that shape. This repo has shipped this defect twice.
4. **Passwords set through the UI or wizard are stored as unsalted MD5.**
   `_core.py:57` wires `setting.save.core.password` to `md5Password`. The
   comment at `variable.py:143` claiming "New passwords are always bcrypt" is
   false; bcrypt is reached only by the login-time upgrade, and this cohort has
   never logged in. `scripts/backup.sh` copies `config.ini`. **New task.**
5. **`auth_required` on with a blank password accepts any password** (executed:
   `POST /login/` issues a cookie for arbitrary credentials). T2.1 would create
   a state that looks protected and admits everyone.
6. **T2.6's Synology fix closes nothing.** `synology.py:110-111` strips the
   scheme and hardcodes `http://`, so `verify=False` at `:140` is unreachable
   on an http URL and removing it changes no observable behaviour.

**Vetoes accepted from `lens-simplicity`** (planning-only, so these stand unless
an owning lens supplies a criterion): the sessions table becomes an HMAC-signed
cookie with a rotating secret in the existing property store (L to S, no schema);
the SSRF private-address guard is **deleted**, not deferred, because every
default downloader points at `localhost` and Jackett is a LAN host, so the guard
would break downloads, and `belongsTo` requires a host that is a substring of a
hardcoded film-site pattern; CSP defers until PR 5 removes the Tailwind CDN;
`/getkey/` is **deleted rather than gated**.

**Scope mechanism (AC-SIMP-31).** PR 1's allowlist was the right shape and
failed because amending it was free. PR 2's may be amended **once**; a second
file leaves for a follow-up PR unless it is precedence tier 1-3 **and** already
on an allowlisted path. Countable at review.

**Highest-value single criterion**, from both security and QA: a **route
inventory test** asserting every route either carries the auth dependency or is
in an explicit public allowlist. T2.2 fixes one endpoint; this fixes the class,
and the class is how `/getkey/` came to exist.

**Before PR 2 is written**, read production's actual `username`/`password` state
into this spec. The cohort this PR protects is also the cohort that has never
typed its password, because the server never asked.

### T2.0: Make `Settings.save()` atomic · S · risk: **Critical** — NEW

Found by `lens-operability` during PR 2 planning (2026-08-06), verified by
reading the code. `core/settings.py:236-238` is:

```python
def save(self):
    with open(self.file, 'w', encoding='utf-8') as configfile:
        self.p.write(configfile)
```

Truncate-then-write, no temp file, no rename. `Env.setting(attr, value=...)`
calls it unconditionally (`environment.py:71`), and **PR 2 is what makes this
fire**: forcing a first-ever login on installs that never logged in triggers
the legacy-md5-to-bcrypt rehash at `__init__.py:277-278` and `:306-307`, each
of which rewrites the whole file.

If the process dies or the volume fills mid-write, `config.ini` is truncated:
the password, the `api_key` and every downloader and notifier credential go in
one step, and the instance restarts as a fresh public install with a new key.
`config.ini` is also the documented lock-out recovery file, so the failure
destroys the remedy along with the configuration.

Precedence tier 1 (irrecoverable loss) outranks everything else in this PR, and
the fix is roughly eight lines.

- **AC-OPS-40** Write to a temp file in the same directory, then `os.replace()`
  onto the target, so the previous file stays intact until the rename succeeds.
  A failed save logs at ERROR naming the file.
- Prove it load-bearing: interrupt the write and assert the original file is
  still complete and readable.

### T2.1: Fail-closed auth via explicit setting · M · risk: medium

> **The tri-state default sketched below does not work. Verified by execution
> 2026-08-06** (`lens-simplicity`, reproduced by the orchestrator):
> `registerDefaults` materialises the literal line `auth_required = None` into
> `config.ini` on first boot, so "unset" survives exactly one start. Reading it
> back, `get(default=None)` returns `None` but `get(default='')` returns `''`,
> and `Env.setting`'s own default **is** `''`. So the natural
> `Env.setting('auth_required', type='bool')` yields a falsy value and auth stays
> off, silently, on every install, with no failing test and no log line. The
> tri-state also only round-trips via a `ValidationError` raised and swallowed
> per auth check (`settings.py:154-155`), so adding `'none'` to the falsy list
> as a tidy-up would turn every protected install public.
>
> **Use instead**: a plain `{'default': 0, 'type': 'bool'}` plus a one-shot
> startup migration that writes `auth_required = 1` when the key is absent and a
> password is set. After the first boot the value is an explicit `0` or `1` that
> the operator can read with `grep`, which is also the documented recovery path.

`couchpotato/__init__.py:57-71` currently gates on `if username and password:`,
so a password with a blank username leaves the server fully public: verified by
executing `get_current_user`.

```python
# new setting in core/_base/_core.py, 'basics' group
{'name': 'auth_required', 'default': None, 'type': 'bool',
 'label': 'Require login',
 'description': 'Require login for the web interface. Defaults on once a '
                'password is set. Turn off only for a trusted LAN.'}
```

- Gate becomes: auth enforced when `auth_required` is on; default derives from
  `bool(password)` so existing password-only installs become protected.
- Username blank = any username accepted, rather than a master off-switch.
- Log a `WARNING` at startup when serving with auth disabled.
- Move the "Leave empty to disable authentication" copy off the **username**
  field (`_core.py:272-284`): it is on the wrong option today and is the
  proximate cause of the trap.

**Acceptance:** unit tests pin all four username/password combinations plus both
`auth_required` states: six cases. The password-only case, which returns `True`
today, must return falsy.

### T2.2: Gate `/getkey/` · S · risk: low

`couchpotato/__init__.py:265-283` has no auth dependency; with default settings
both credential clauses short-circuit true and it returns the API key that
authorises `media.delete`, `settings.save`, `directory.list` and `app.shutdown`.

Safe to gate: no live consumer (verified above). Return 401 when auth is
required and no valid credential is supplied.

**Acceptance:** unauthenticated `GET /getkey/` returns 401 on a default install;
`tests/unit/test_fastapi_web.py:266-285` updated to cover the gated behaviour.

### T2.3: Separate the session credential from the API key · L · risk: medium

`__init__.py:315` sets the cookie to the api_key itself, so `/logout` revokes
nothing, a password change revokes nothing, and the 30-day "remember me"
persists a permanent credential.

Issue a random session token stored server-side (a `sessions` table in the
existing SQLite DB, or a signed itsdangerous-style token with a rotating secret: prefer the table; it makes revocation real). Set `secure` when TLS is
configured (`runner.py:336-340`) and `samesite='lax'` explicitly rather than by
Starlette default.

**Acceptance:** logout invalidates server-side (a replayed cookie fails);
changing the password invalidates existing sessions; `secure` set under TLS.

### T2.4: QW3 + QW4: rate limiter and event-loop bcrypt · S · risk: low

- `core/rate_limit.py:51-55` exempts any request with `text/html` in `Accept`
  and no `/api/` in the path: an attacker-controlled header that uncaps
  `/login` and `/getkey`. Remove the exemption; exempt by *path prefix* only
  (static assets), which is what the adjacent `_EXEMPT_PREFIXES` check already
  does correctly.
- `login_post` and `get_key` are `async def` calling `bcrypt.checkpw` inline on
  the event loop. Wrap in `run_in_threadpool`, the pattern already used at
  `__init__.py:248` and `ui/__init__.py:167`.

**Acceptance:** a test asserts `Accept: text/html` requests to `/login` are rate
limited; a test asserts the login path does not block the loop (mirror the
existing `test_api_dispatch_concurrency.py` shape).

### T2.5: QW5 + QW6: headers and constant-time comparison · S · risk: low

- Add a security-headers middleware: `Content-Security-Policy`,
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`.
  The UI has one-click delete controls and is framable today.
- `__init__.py:148,155-158` compares the API key with `!=` / `startswith`; the
  cookie path already uses `hmac.compare_digest`. Make them match.
- Raise the minimum API key length above 4 (`_core.py:93`).

**CSP gotcha:** the templates use Alpine.js, which needs `unsafe-eval` unless the
CSP build of Alpine is used. Land the header with the E2E suite as the guard: a too-strict CSP breaks the UI silently in ways unit tests will not catch.

### T2.6: QW2 + QW7: TLS verification and log redaction · S · risk: low

- `core/downloaders/synology.py:140`: `verify=False` while POSTing
  `account`/`passwd`. Honour the global `ssl_verify` setting; this is the last
  `verify=False` in the tree.
- Extend `PrivacyFilter`'s allowlist (`core/logger.py:27`) with `token`,
  `authkey`, `torrent_pass`, `sid`, `passkey`; fix the three call sites that log
  secrets outside query-param form: `notifications/telegrambot.py:37`,
  `downloaders/synology.py:125`, and full-URL logging at `http_client.py:236`.
- Reconsider `logger.py:64-65`, which disables redaction entirely under `dev`.

**Acceptance:** a test feeds each secret shape through the filter and asserts
redaction: including the non-query-param forms, which is the gap today.

### T2.7: SSRF: userscript host matching · M · risk: low

`providers/userscript/base.py:39-47` matches hosts by substring against patterns
like `http://*.imdb.com/title/tt*` and never checks the path. Reproduced:
`a.imdb.co` → True, `a.imdb.c` → True, `a.imdb.com:9200/internal` → True.

Replace with exact host-suffix matching against a parsed allowlist, and add a
private/loopback/link-local address guard in `http_client.py` for URLs whose
origin is user- or feed-supplied.

**Acceptance:** the three strings above are rejected; a URL resolving to
`127.0.0.1` or RFC1918 space is refused with a logged reason.

**PR 2 acceptance:** all of the above green; E2E suite green (the auth change
touches every page); a manual pass against a scratch instance confirming login,
logout, remember-me and the open-instance path all behave.

---

## PR 3: M1b: Data correctness at the SQLite seam

**Goal:** every `_query_index` branch honours its key or raises; no live code
path calls an adapter method that does not exist.

### T3.1: `release_download` key matching · S · risk: low

`sqlite_adapter.py:703-711` filters only on the *existence* of `download_info`
("for now return all with download_info"). The live caller
`renamer/scanner.py:197` takes the first row and stamps its `imdb_id`, `quality`
and `release_id` onto the download; `scanner/folder_scanner.py:360-363` then uses
that `imdb_id` to decide which movie the files belong to, on a job scheduled
every minute (`renamer/main.py:46`).

- **RED first:** insert two releases with different `download_info.id`, assert
  the lookup returns only the requested one. Fails today.
- Match on the two extracted fields independently rather than reconstructing the
  `'%s-%s'` string: a downloader name containing `-` makes the split ambiguous.
- Confirm the stored type of `download_info.id`: a numeric id stored as int will
  not match a string bind, and a fixture that does not mirror production data
  will pass for the wrong reason.
- Add `idx_release_download` on
  `json_extract(data,'$.download_info.downloader')` and `…'$.download_info.id'`.

**Critical:** `open()` does not run `schema.sql` (`:208-219`). Add an idempotent
upgrade call in `open()` following `_ensure_unique_media_identifier_index`
(`:132-206`), or the index reaches fresh installs only. Prove it by opening a
copy of a pre-change database and asserting the index exists afterwards.

### T3.2: Reconcile the adapter compat surface · M · risk: medium

`db.reindex()` is called with no argument at `database.py:218,316`,
`manage.py:199`, `release/main.py:155`, but the signature is
`reindex(self, index_name)` (`:836`): a guaranteed `TypeError`. In `manage.py`
it aborts the enclosing `try` before `Env.prop(last_update_key, …)` is written,
so every full library scan logs "Failed updating library" and never records
completion.

`db.opened` (`database.py:402`) and `db._delete_id_index` (`:209`) do not exist
either. `db.opened` is on the fossil v1 migration path only (verified), so
delete that path rather than repairing it: after confirming reachability.

**Acceptance:** a library scan writes its completion timestamp (assert on
`Env.prop`); a test asserts every `db.<method>` call in `couchpotato/` resolves
to a real adapter method: the enforceable version of this class of bug, and it
would have caught all three.

### T3.3: Restore or delete orphan-release cleanup · S · risk: low

`release/main.py:117-152` reads `release.get('key')`, a CodernityDB index-row
field `_doc_from_row` never produces (`:287-292`). `db.get('id', None)` raises
`KeyError`, which misses the `except ValueError` / `except RecordDeleted`
clauses and lands in `except Exception: log.debug` at `:151-152`. Dead since the
SQLite migration, invisible above DEBUG.

Decide: restore (with a test proving an orphan is deleted) or delete. Prefer
restore: orphaned releases accrue otherwise.

### T3.4: Narrow the dangerous exception swallowing · S · risk: low

Not a campaign against all 377 `except Exception:` blocks: most are legitimate
resilience. Three specific ones:

- `database.py:130-134,177-181` return `traceback.format_exc()` bodies to API
  clients (internal path disclosure). Log server-side, return a generic error.
- `fireEvent`'s outer handler returns `None` implicitly (`event.py:266-267`),
  violating its own list contract for callers like `searcher.py:102`. Return `[]`.
- `api.py:68-70` collapses every handler failure into one generic error; the UI
  documents working around this (`ui/__init__.py:389,406`). Preserve the error
  type for logging at minimum.

**PR 3 acceptance:** the two-download fixture attributes files to the correct
movie; library scan records completion; the adapter-method-existence test passes.

---

## PR 4: FEAT-009 Part B: upgrade replacement

**Goal:** complete the deferred half of FEAT-009: an upgrade must be able to
land, without ever putting the user's library at risk.

**Why here:** it depends on PR 1's `moveFile` tests (this is the same code path)
and on PR 3, which also edits `release/main.py` and the renamer scanner. It must
not be folded into the performance PR: it is the one code path that deletes
files from the user's library and needs to be reviewed on its own.

**Status entering this PR:** two attempts were made and both withdrawn, each
because it moved a possible loss from the replaceable side (a download) to the
irreplaceable side (the library). Per CLAUDE.md rule 11, this third attempt is
reviewed as **new work, not a correction**: and it is the case that rule was
written for.

### The two withdrawn attempts (do not repeat)

1. **No quality comparison at all.** Measured: a 720p download overwrote a 2160p
   remux.
2. **Comparison via `quality.isHigher`.** That is a *search* heuristic: it
   returns `'higher'` whenever the existing quality is not a rung of the profile
   (`quality/main.py:542-548`, re-verified 2026-08-02). The default `Best`
   profile excludes 2160p, so it still authorised destroying a remux. It was
   also **inert**: the scanner-supplied `group['media']` has no `releases` key
   (`media.get` attaches it, and the scanner never calls it), so the gate always
   refused: meaning *fixing the inertness would have activated the destruction*
   on the default profile.

That last point sets the sequencing inside this PR: **the ordering must be
correct and tested before the gate is made live.** Do not fix the missing
`releases` attachment first.

### T4.1: Profile-independent quality ranking · S · risk: low

Add a ranking primitive over `QualityPlugin.qualities` (`quality/main.py:26-38`): rank by index, lower index = better. "Is this file better than what is on
disk" is a global question, not a profile question.

- New event/method, e.g. `quality.rank`, returning the index or `None` when the
  quality is unknown.
- **Unknown quality on either side ⇒ refuse to replace.** Degrade to today's
  skip-and-warn rather than guessing, matching FEAT-009 Part A's AC3 philosophy.
- Decide and pin the 3D rule: `is_3d` is not part of the global list ordering, so
  a 3D and non-3D copy at the same rung are not comparable: treat as "not
  better" and refuse.

**Acceptance:** a test table over the full `qualities` list pins the ordering,
including `bd50` above `1080p` and `brrip` below `720p`. Explicitly pin
**720p vs 2160p → not better**, the case measured to fail in attempt #1, and the
default-`Best`-profile case from attempt #2: the ranking must not consult a
profile at all, so a test that passes a profile and asserts no behaviour change
is the guard against regressing to `isHigher`.

### T4.2: Attach releases at the call site · S · risk: medium

The scanner's `group['media']` carries no `releases` key, which is why attempt
#2 was inert. Attach them where the renamer needs them.

**Do this only after T4.1 is green**: this is the change that makes the gate
live, and on the previous attempt it would have activated destruction.

**Acceptance:** a test asserts the renamer sees the media's releases; the
replacement gate is exercised rather than silently refusing (an inert gate is a
vacuous guard: CLAUDE.md §11).

### T4.3: Atomic replacement · M · risk: **high**

Replace `renamer/main.py:154-157`'s unconditional skip with: replace when
`remove_lower_quality_copies` is on **and** the incoming copy ranks strictly
better; otherwise keep the existing file and preserve the download (the safety
half already shipped).

Replacement must never be `os.remove` + move. Sequence:

1. Move the incoming file into the destination directory under a temporary name
   (same filesystem, so the later swap is atomic).
2. Verify it landed: size matches the source.
3. `os.replace(tmp, dst)`: atomic within a filesystem.
4. Only then account for the old copy.

If any step fails, the destination is untouched and the download survives.

**Gotchas:** `os.replace` is atomic only *within* a filesystem: the library and
the download directory are frequently different mounts on this project's target
deployment, so the temp file must be created in the **destination** directory,
not the source. This interacts directly with `moveFile`'s hardlink/symlink
fallback branches (the `link` fallback), which PR 1 now covers: reuse those tests
as the foundation rather than writing a parallel harness.

**Acceptance (every one is a destructive-direction test):**
- Old file is **not** removed when the new one did not land (kill the move
  mid-way and assert both the original and the download survive).
- A strictly-better copy replaces; an equal or worse copy does not.
- With `remove_lower_quality_copies` off, the existing file is untouched **and**
  the incoming file is not silently destroyed.
- `cleanup` does not delete the source folder when any file was skipped or
  failed: regression-pin the shipped safety half so this PR cannot undo it.

### T4.4: Path ownership · S · risk: medium

The spec names an open design question: which release owns a given path when two
legitimately claim it. Resolve it explicitly (`copy_id` from Part A is the
natural discriminator) and write the rule down: an ambiguous answer here is how
the wrong file gets deleted.

**PR 4 acceptance:** all of the above green; the replacement path exercised
end-to-end against a real tmp filesystem; a reviewer lens specifically on "can
this delete something irreplaceable" in addition to the standard two. Update
`specs/FEAT-009-durable-set-aside-and-upgrade-replacement.md` to retire the
`STATUS: NOT IMPLEMENTED` block once it ships.

---

## PR 5: M2: Performance

### T5.1: Kill the triple-fetch · M · risk: low

`_query_index` already returns complete documents (`:789-790`), yet
`query(with_doc=True)` discards them and re-fetches each by id (`:546-550`);
named-index `get()` does the same (`:317-323`); and `Release.forMedia` stacks a
third (`release/main.py:766-773`). Every release document is read and JSON-parsed
three times. `get_many` defaults to `with_doc=True`, so one fix covers 44 call
sites.

**Acceptance:** a test counting adapter `get` calls asserts zero additional
fetches for a `query(with_doc=True)`. Assert on the *count*, not on timing: a timing assertion is a flake generator.

### T5.2: Paginate the movie list · M · risk: low

`ui/__init__.py:291-301` calls `media.list` with no `limit_offset`, and
`media/_base/media/main.py:276-399` fetches all ids, filters with list-membership
(O(N·M)), re-iterates the full library, then fires `media.get` per movie, which
itself does four more queries. Thousands of queries per page load at 1,000 movies.

Pass a limit from the UI; convert the list-membership filters to sets.

**Open question (§6.4):** target library size decides the page size. Assume 100
per page until told otherwise.

### T5.3: Build-time Tailwind · M · risk: medium

`ui/templates/base.html:19` loads `tailwindcss-cdn.js`: 407,279 bytes, the
in-browser JIT compiler: synchronously in `<head>` before anything renders.
htmx (51KB) and Alpine (46KB) follow without `defer`. This is the project's
largest self-inflicted Core Web Vitals violation.

Replace with a built stylesheet; add `defer` to the remaining scripts. Enforce a
CSS/JS size budget in CI so it cannot regress.

**Gotcha:** the design-system conformance check (`docs/design-system/CONFORMANCE.md`,
CI-gated) and the a11y E2E suite are the guards against visual regression here: this change cannot be verified by unit tests. Compare rendered screenshots before
and after.

### T5.4: Renamer re-entrancy · S · risk: low

`renamer/main.py:22-23,72-79` uses unlocked class attributes as guards, so the
cron thread and an API thread can both pass check-then-set and run two
destructive scans concurrently. Small window, destructive landing zone. Use the
existing per-instance lock pattern (`plugins/base.py:47`).

### Deliberately **not** in this PR

- **Per-route locks (`api.py:34`)**: real throughput cost, but removing them
  assumes handler thread-safety nobody has measured. Needs a concurrency test
  first, and it is not a user-visible problem at home-server scale. Open
  question §6.7 asks whether they are deliberate; answer that before touching.
- **Dirty reads during transactions (`:236-270`)**: genuine hazard, but the fix
  (per-thread connections or read locks) is a structural change that needs its
  own PR and a failing test that demonstrates the dirty read first. Write the
  test in this PR, mark it `xfail`, fix in a follow-up.

---

## PR 6: M3: Documentation, dead code, polish

### T6.1: Outward-facing docs · S

- `README.md:5`: badge for `.github/workflows/lint.yml`, which does not exist.
  Remove.
- `:13`: "What's New in v3.0.0" on a v3.9+ project. Retitle without a version.
- `:17`: "457 tests" vs ~1,743 today. **Remove the number**, don't update it;
  it will rot again by definition (project doc rule §7).
- `:22`: "no more vendored libraries" contradicts `:25` three lines later.
- `:75`: stale tag list.

### T6.2: CONTRIBUTING rewrite · S

`CONTRIBUTING.md:23` gives the test command as bare `pytest`, which collects
integration and e2e tests without the `PYTHONPATH=libs` that
`docs/development-process.md:507-509` warns is required. It never installs
`requirements-dev.txt` and never mentions `make setup`, `make verify`, npm,
Playwright, the pre-push hook, or the rule that UI changes require E2E updates.
Point it at the existing good content.

### T6.3: Docs that contradict the code · S

- Retire or rewrite `docs/reference/GITHUB_ACTIONS.md`: its section 3 documents
  `release.yml`, which no longer exists.
- Reconcile `docs/technical-debt.md:72` ("E2E … RESOLVED") against `:149-186`,
  which establish the suite is back at `workers: 1` with ~20% flake. The later
  entries are the truth.
- Decide CHANGELOG.md's fate (stops at v3.4.0): keep current or retire with a
  pointer to GitHub release notes.

### T6.4: Dead code · M

`helpers/variable.py` unused helpers (`removeListDuplicates`, `flattenList`,
`sha256`, `toIterable`, `dictIsSubset`); the unused `natsortKey` import at
`event.py:5`; `couchpotato/lib/` (empty shell, still on `sys.path`, still
ruff-excluded); `gntp==1.0.3` (no Growl plugin exists) plus its `logger.py:184`
quiet-list entry; a `# transitive: python-dateutil` comment on the `six` pin.

**Open question §6.5:** `hadouken.py` (606 lines) and `pneumatic.py` target
defunct services: removal is trivial but users cannot be surveyed. Deferred
pending a decision.

### T6.5: Remaining low-severity security · S

`tarfile.extractall(filter='data')` (`_base/updater/main.py:373`); list-args
`subprocess.run` instead of `os.popen` (`renamer/`moveFile`'s `os.name == 'nt'` branch (`os.popen`/`icacls`)`); strip `/`, `\`
and `..` in `renamer/namer.py:63`; validate `cors_origins` against `*` with
credentials (`__init__.py:109-118`); self-host the Google Fonts references
(`templates/login.html:25-26`, `ui/templates/base.html:53-54`); double
URL-decoding at `helpers/request.py:31,42`.

### T6.6: Enforcement, not prose · S

- SHA-pin GitHub Actions (the repo already pins gitleaks by version for exactly
  this reason).
- Mirror the required `secrets` check in `verify.sh` so a tree secret fails the
  pre-push hook, not just CI.
- Document the Node minimum and the Docker prerequisite; make `make setup`
  either create `.venv` or refuse to install into ambient python, matching
  `verify.sh:39-45`.

### T6.7: mypy on `core/db/*` (Q2, narrow start) · M · risk: low

Scheduled on 2026-08-02 after challenge: the *repo-wide* gate is XL and stays
deferred, but the narrow start was already identified and there is no reason to
park it. `core/db/*` is the one package that already carries type hints
throughout, so it should pass at or near clean immediately, which makes it a
gate that starts green and ratchets, not a migration.

**`lens-simplicity` vetoed this task at planning** on the grounds that no defect
has been identified that mypy would have caught, making it "a gate looking for a
job". **Veto overridden by Scott, 2026-08-03**, with the rationale recorded: it
is preventive rather than remedial, and `core/db/*` is where a type-shaped
regression would be most expensive. The objection is fair and is kept here so
the decision is visible: if the gate produces nothing but noise across a few
PRs, that is the evidence to remove it.

Add mypy to `requirements-dev.txt`, configure it in `pyproject.toml` scoped to
`couchpotato/core/db/`, and wire it into `verify.sh` and CI alongside ruff.

**Acceptance:** the gate is green on `core/db/*` and **fails** when a wrong type
is introduced there: prove it by breaking one signature and watching CI go red
before restoring. A type gate nobody has watched fail is decoration (§11).

**Explicitly not in scope:** widening beyond `core/db/`. Each additional package
is its own decision with its own annotation cost.

---

## Deferred with rationale (not scheduled)

Revised 2026-08-02 after challenge: two rows moved into the plan (O2 → PR 1,
Q2's narrow start → PR 6), one missing rationale written (A5), one row
relabelled from "deferred" to "won't fix" (legacy deps), which is what it
always was.

| Finding | Why not now |
|---|---|
| Per-route locks (A4) | The lock is **inherited from upstream's Tornado era** (`af2876bd "Lock same api routes"`, carried through the FastAPI migration in `44224f03`): it is a decade-old guard around handlers written assuming they never run concurrently, not accidental carryover. Removing it makes ~100 legacy handlers concurrent for the first time. Cost of keeping: latency on a single-user server. Cost of removing wrongly: DB races on irreplaceable data. Answer open question §6.7 first |
| Circular-import hub (A5) | Architectural refactor with **no user-visible symptom** and a wide blast radius (~40 modules do `from couchpotato import get_db`). The repo's own history (#148) shows these re-exports break plugins *silently*, because the loader swallows `ImportError` at DEBUG. The real prerequisite is making plugin import failures loud: do that first; the imports are the second job, not the first |
| Dirty reads (P4) | Structural: the fix is per-thread connections or read locks, a redesign of connection handling in the best-engineered file in the repo. Partially scheduled: PR 5 writes the failing test and marks it `xfail`. A *demonstrated* dirty read is what tells you which fix is right, and nobody has demonstrated one |
| Broad `except Exception` (Q1, bulk) | ~377 blocks, most of them legitimate resilience: a media server *should* survive one bad file. A sweep is an enormous diff with no tests behind it. The three genuinely dangerous ones are scheduled in T3.4; the rest is a ruff `BLE` ratchet, incremental by nature |
| mypy beyond `core/db/*` (Q2, bulk) | Repo-wide is XL. The narrow start is now scheduled as T6.7; each further package is its own decision with its own annotation cost |
| Widen mutmut scope | Real value, but CI-minutes cost; decide after M2 |
| Shipped TMDB/fanart.tv keys | **Deliberate**: documented in `technical-debt.md:98-121`; removing them broke artwork once already. Do not "clean up" |

### Won't fix (a decision, not a deferral)

| Finding | Why |
|---|---|
| Legacy deps: bencodepy, putio.py, deluge-client, rtorrent-rpc (D4) | Dormant upstreams, but the code is live, working, pure-protocol, and no CVE was found. Replacing a working torrent-protocol library is pure risk with no benefit. This was mislabelled "deferred"; it is a decision to keep them |

## Sequencing and risk

```
PR1 (M0) ──▶ PR2 (M1a auth) ─────────────────┐
   │                                         ├──▶ PR5 (M2 perf) ──▶ PR6 (M3 polish)
   └────────▶ PR3 (M1b data) ──▶ PR4 (FEAT-009 Part B)
```

PR 2 and PR 3 are independent of each other and both depend on PR 1. PR 4
depends on **both** PR 1 (the `moveFile` tests are its foundation) and PR 3
(which also edits `release/main.py` and the renamer scanner). PR 5's adapter
work touches `query()`, which PR 3 also touches: land PR 3 first.

**PR 4 is the highest-risk PR in this plan** despite not being the largest. It
is the only one that deletes files from the user's library, and two prior
attempts at it were withdrawn. Give it a third reviewer with an explicit
"can this destroy something irreplaceable" lens, and do not let it ride along
with any other change.

**T5.4 (renamer re-entrancy lock) must land before PR 4**: decision 6. It is
listed under PR 5 for thematic grouping, but its dependency is PR 4, not PR 5.
Land it at the end of PR 3, or as the first commit of PR 4 before any
replacement logic. Two concurrent scans currently destroy a file while both
report success (`renamer/main.py:72-79`, unlocked check-then-set); PR 4 adds a
delete to that path.

**Production deploy is out of scope of this plan.** PR 2, PR 3 and PR 4 all
change behaviour on a live instance holding irreplaceable data. When a deploy is
agreed: `./scripts/backup.sh` first, record the current `config.ini` auth state,
promote a tested beta byte-for-byte, and keep the rollback tag to hand. Consider
letting PR 4 soak on `:beta` longer than the others: its failure mode is silent
and only visible after an upgrade actually lands.

## Finding coverage

Every audit finding maps to a PR or to the deferred table above.

| PR | Findings / work resolved |
|---|---|
| PR 1 | T1, T2, T3, T4, O1, **O2**, O5, D1 (partial), A6 |
| PR 2 | S1, S2, S3, S4, S5, S6, S7, S8, S9 (partial) |
| PR 3 | A1, A2, A3, Q1 (targeted subset) |
| PR 4 | FEAT-009 Part B (not an audit finding: deferred feature work) |
| PR 5 | P1, P2, P3, P5, P4 (failing test only, `xfail`) |
| PR 6 | C1, C2, C3, C4, D2, D3, D5, O3, O4, O6, Q3, S9 (remainder), **Q2 (narrow start)** |
| Deferred | A4, A5, P4 (fix), Q1 (bulk), Q2 (beyond `core/db/*`), mutmut scope |
| Won't fix | D4 (legacy deps: a decision, see above) |
