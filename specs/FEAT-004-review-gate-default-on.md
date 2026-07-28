# FEAT-004: The "Downloaded / review" gate defaults ON

## Problem

`specs/DOWNLOADED-REVIEW-WORKFLOW.md` opens by rejecting auto-done:

> Supersedes the open question in `specs/RENAMER-EVENT-CHAIN.md` about whether
> to auto-mark releases `done` — the answer is **no; introduce a review gate**.

The gate shipped in v3.9.0 as a per-profile `manual_confirmation` toggle, but
defaulting **off** "so existing/legacy profiles keep today's auto-upgrade-to-done
behavior unchanged" (`profile/main.py`).

The result: on a production install, all 18 profiles had it unset, so every
completed download went straight to `done`. The owner's report:

> the design is that it should never automatically move to done, often the
> downloaded grabs something it shouldn't I need to review it

So the compatibility default inverted the intended design, and nothing
surfaced it — a user who never opens profile settings never learns the gate
exists.

## Fix Required

1. **Seeded profiles** (`DEFAULT_PROFILES` via `build_profile_doc`) get
   `manual_confirmation: True`, so a fresh install has the gate on.
2. **New profiles** created through `Profile.save()` default to on: the
   insert-path default changes from `0` to `1`.
3. **The edit path is unchanged.** `save()` already falls back to the
   *persisted* value when the key is omitted
   (`1 if p.get('manual_confirmation') else 0`), which is what keeps the live
   profile editor from resetting the flag on every save. That fallback must
   keep reading the stored value, not the new default — otherwise editing any
   existing profile silently switches its gate on.

## Deliberately NOT doing

**No migration flipping existing profiles.** Turning the gate on changes what
happens to every future download on that profile, and doing it silently to
installs that have been running for months is the same class of surprise this
spec is fixing — just in the other direction. Existing users opt in from
Settings → Profiles.

The distinction that matters: (1) and (2) change what a *new* profile does,
which nobody has come to rely on. A migration changes what an *existing* one
does.

## Acceptance Criteria

- [ ] AC1: every profile in `DEFAULT_PROFILES` expands with
      `manual_confirmation` true.
- [ ] AC2: `Profile.save()` with no `manual_confirmation` key creates a NEW
      profile with it on.
- [ ] AC3: `Profile.save()` on an EXISTING profile that has it off, with the
      key omitted, leaves it off — the persisted value still wins over the
      new default.
- [ ] AC4: the same, with it on, leaves it on.
- [ ] AC5: an explicit `manual_confirmation=0` still turns it off, on both
      the create and edit paths.

## Affected Files

- `couchpotato/core/plugins/profile/main.py`
- `tests/unit/test_profile_defaults.py`
- `tests/unit/test_review_gate_default.py` — new
