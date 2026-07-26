# BUG-016: Default quality profiles are ordered worst-first

## Problem

A user set several movies to the built-in **Best** profile and every one of
them downloaded at 720p, even though 1080p releases were available.

This is working exactly as configured — the configuration is wrong.

`couchpotato/core/plugins/quality/main.py:544` states the ordering contract:

```python
# Note to self: a lower number means higher quality
```

Index 0 of a profile's `qualities` list is the **most preferred** quality.
`MovieSearcher.single()` iterates the list in order and breaks out of the loop
as soon as one download succeeds (`searcher.py:282`, `if self.shuttingDown()
or ret: break`), so index 0 wins whenever anything is found for it.

But `Profile.fill()` (`profile/main.py:222`) seeds:

```python
{'label': 'Best',    'qualities': ['720p', '1080p', 'brrip', 'dvdrip']}
{'label': 'HD',      'qualities': ['720p', '1080p']}
{'label': 'SD',      'qualities': ['dvdrip', 'dvdr']}
{'label': 'UHD 4K',  'qualities': ['720p', '1080p', '2160p']}
{'label': 'Prefer 3D HD', 'qualities': ['1080p', '720p', '720p', '1080p'], '3d': [True, True]}
```

`fill()` also sets `finish: True` for every entry, so the first quality
obtained also *ends* the movie — there is no later upgrade pass.

Consequences:
- **Best** means "prefer 720p, stop". 1080p is unreachable while any 720p exists.
- **UHD 4K** never fetches 2160p while any 720p exists — the profile cannot do
  the one thing its name promises.
- **SD** prefers DVD-Rip over DVD-R, inverting the canonical ranking.
- **Prefer 3D HD**'s non-3D tail (`720p`, `1080p`) is inverted; its 3D head is
  correct.

The canonical ranking is the order of `QualityPlugin.qualities`
(`quality/main.py:27-38`), best first:

    2160p > bd50 > 1080p > 720p > brrip > dvdr > dvdrip > scr > r5 > tc > ts > cam

This is inherited from upstream CouchPotato, not introduced by this fork — but
the labels have always been wrong about what the profiles do.

## Fix Required

1. Reorder the seeded defaults in `Profile.fill()` to match the canonical
   ranking, **without changing which qualities are in each set**:

   | Profile | Before | After |
   |---|---|---|
   | Best | `720p, 1080p, brrip, dvdrip` | `1080p, 720p, brrip, dvdrip` |
   | HD | `720p, 1080p` | `1080p, 720p` |
   | SD | `dvdrip, dvdr` | `dvdr, dvdrip` |
   | UHD 4K | `720p, 1080p, 2160p` | `2160p, 1080p, 720p` |
   | Prefer 3D HD | `1080p, 720p, 720p, 1080p` | `1080p, 720p, 1080p, 720p` |
   | 3D HD | `1080p, 720p` | unchanged (already correct) |

   Deliberately **not** adding 2160p to `Best`: that would silently switch
   existing users onto 20–60GB downloads. Users who want 4K have `UHD 4K`,
   which this change makes actually work.

   The `'3d'` flags for `Prefer 3D HD` are produced by `threed.pop()` and
   remain `[True, True, False, False]` — the reorder must not disturb the
   pairing of 3D flags to qualities.

2. `fill()` only runs on a fresh install, so existing databases keep the bad
   order. Add a one-time migration that repairs them.

## Migration

New `couchpotato/core/migration/fix_profile_quality_order.py`, wired into
`couchpotato/runner.py` alongside `clean_orphans` and `fix_release_quality`
(same try/except-and-log shape).

**Safety rule: only rewrite a profile whose `label` AND `qualities` list match
a known-bad seeded default exactly.** Anything the user has renamed,
reordered, or edited is left strictly alone. This is the whole safety story —
a migration that "helpfully" reorders custom profiles would destroy
deliberate user choices (e.g. someone who genuinely prefers 720p for disk
reasons).

`finish` / `wait_for` / `stop_after` / `3d` are positional siblings of
`qualities`. When a profile matches a bad default, all five lists must be
permuted with the **same** permutation, or the flags detach from their
qualities. For the seeded defaults every `finish` is `True` and every
`wait_for`/`stop_after` is `0`, so this is invisible for untouched rows — but
the migration must permute rather than assume uniform values, because a user
may have changed a flag without changing the quality order.

## Acceptance Criteria

- [ ] AC1: `Profile.fill()` seeds every default profile in canonical
      best-first order; asserted against the ordering derived from
      `QualityPlugin.qualities` rather than a hardcoded copy, so the test
      keeps working if a quality is added.
- [ ] AC2: `fill()` still produces `finish`/`wait_for`/`stop_after`/`3d` lists
      of the same length as `qualities` for every profile.
- [ ] AC3: `Prefer 3D HD` keeps 3D 1080p first, 3D 720p second, and its
      non-3D tail is 1080p then 720p.
- [ ] AC4: The migration reorders a stored profile that exactly matches a
      known-bad default, permuting `finish`/`wait_for`/`stop_after`/`3d`
      identically.
- [ ] AC5: The migration does **not** touch a profile whose `qualities` have
      been customised, whose label was renamed, or which is already in the
      correct order (idempotent — a second run is a no-op).
- [ ] AC6: The migration returns `(fixed, checked)` and survives a DB error
      without raising into startup.

## Affected Files

- `couchpotato/core/plugins/profile/main.py` — `fill()` defaults
- `couchpotato/core/migration/fix_profile_quality_order.py` — new
- `couchpotato/runner.py` — invoke migration
- `tests/unit/test_profile_defaults.py` — new (AC1–AC3)
- `tests/unit/test_fix_profile_quality_order.py` — new (AC4–AC6)

## Note for affected users

Existing movies already grabbed at 720p and marked done are **not**
retroactively upgraded by this change; the migration fixes the profile so
*future* searches prefer 1080p. To upgrade an existing movie, re-add it (or
clear its release) after the migration has run.
