# FEAT-006: Define quality profiles in a config file

> Status: **BACKLOG — not scheduled.** Owner's idea, captured while the
> problems that motivate it were fresh. Not started; the design questions
> below need answering before anyone implements it.

## Motivation

Profiles live only in the database today, seeded once by `ProfilePlugin.fill()`
and `QualityPlugin.fill()`, and editable only through the settings UI. Three
problems this session all trace back to that:

1. **BUG-016** — the seeded profiles were ordered worst-first (`Best` led with
   720p). Fixing the seeds did nothing for existing installs, so it needed a
   bespoke migration that only rewrote profiles still matching a known-bad
   default exactly. The owner's own `Best` had been edited, so the migration
   correctly skipped it and the bug persisted until it was fixed by hand.
2. **FEAT-004** — the `manual_confirmation` review gate defaults on for *new*
   profiles, but existing ones can only be changed through the UI, and the
   profile editor never exposes that field. So the documented "opt in from
   Settings → Profiles" is currently impossible.
3. A bulk profile update via the `profile.save` API silently cleared `core` on
   12 built-ins (fixed separately), because the API rebuilds a profile from
   whatever the caller sends rather than patching fields.

A file makes the whole set reviewable, diffable, versionable and editable
without a UI round-trip — and turns "change the defaults" from a migration
problem into an edit.

## The hard constraint: profile IDs are referenced

Every movie stores `profile_id` and looks it up by database id
(`media/main.py`: `db.get('id', media.get('profile_id'))`). Those ids are
generated at insert time (`_generate_id()` in `sqlite_adapter.py`), not derived
from anything stable in the profile itself.

So a naive "regenerate profiles from the file on boot" **loses every movie's
profile assignment**. Any design has to answer this. The obvious options:

- **Stable keys.** The file gives each profile a slug (`best`, `uhd-4k`), and
  a mapping table or a deterministic id derived from the slug preserves
  references across rewrites. Requires a one-time migration to attach slugs to
  existing profiles by matching label.
- **File seeds, database owns.** The file is only consulted when a profile
  does not already exist; the database stays the source of truth afterwards.
  Simplest, keeps ids stable — but does not solve problem 1, because existing
  profiles still never get updated.

These are meaningfully different products, and the second is much less useful.

## Other questions to settle first

- **Which direction wins on conflict?** If the UI can still edit profiles, the
  file and the database will diverge. Either the UI becomes read-only for
  profiles (a real UX regression), or edits are written back to the file (then
  the file is generated, and hand-edits race with the app), or the file is
  import-only.
- **Where does it live?** Beside `config.ini` in the config volume, so it
  survives container recreation and lands in the user's backups.
- **What happens to a malformed file?** It must not take the app down or leave
  a user with no profiles. Fall back to the stored profiles and log loudly.
- **What about `core`?** The flag marks a profile non-deletable in the UI. If
  profiles come from a file, "built-in" arguably stops meaning anything.
- **Format.** `config.ini` is already INI, but profiles are a list of records
  with parallel arrays (`qualities`/`finish`/`wait_for`/`stop_after`/`3d`),
  which INI models badly. YAML or JSON fits the shape; adding a YAML
  dependency for one file is a cost worth weighing.

## Scope input from review of #205

Findings raised while shipping FEAT-004/005 that this work would subsume,
recorded here so the reasoning is not lost:

- **Profile defaults are declared in two places.** `manual_confirmation: True`
  is now hardcoded independently in `build_profile_doc()`
  (`profile/main.py`) and in the inline profile insert in
  `QualityPlugin.fill()` (`quality/main.py`). Both are correct and both are
  tested, but nothing keeps them in sync — a future change to any default has
  two call sites to find by inspection. The same is true of the seeded
  *quality lists*: `DEFAULT_PROFILES` and the one-quality profiles
  `QualityPlugin.fill()` creates are separate declarations of "what profiles
  exist". A file collapses both into one source of truth, which is a
  substantial part of the value here.

- **`profile.save` rebuilds rather than patches.** It reconstructs the whole
  document from the caller's payload, so any field the caller omits reverts to
  a default. `order` and `manual_confirmation` have persisted-value fallbacks
  bolted on for exactly this reason, and `core` needed one adding after a bulk
  update cleared it on 12 built-ins. A file-driven design should not need
  per-field fallbacks, because the file *is* the declaration — but if the UI
  keeps writing profiles, this shape needs designing out rather than
  inheriting.

- **There is no supported way to change `manual_confirmation`.** The settings
  profile editor's `profileToForm`/`formToPayload` never expose it, so the
  field can only be set through the API. Whatever replaces the current editor
  needs every profile field reachable, or the same gap recurs for the next
  field added.

## Suggested scope if picked up

Smallest version that solves the motivating problems: a file that is
**authoritative**, with slug-keyed stable ids, a one-time migration mapping
existing profiles to slugs by label, the settings UI switched to read-only for
profiles with a pointer to the file, and a loud, non-fatal fallback when the
file is missing or invalid.

Explicitly out of scope for a first cut: writing the file back from the UI.

## Related

- `specs/FEAT-004-review-gate-default-on.md` — the opt-in gap this would close
- `specs/BUG-016-default-profile-quality-order.md` — the migration this would
  have made unnecessary
- `couchpotato/core/migration/fix_profile_quality_order.py` — the bespoke
  repair that exists because the seeds are not re-readable
