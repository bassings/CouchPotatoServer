# BUG-018: the scanner files every remake under the original

**Status:** agreed, REDESIGNED 2026-09-06 after the first design was shown to be
dangerous
**Severity:** wrong data, recoverable. No file is touched; the library record is
wrong.

## What happens

Seven media records in production hold files from two distinct films. The
second film therefore has no record of its own: CouchPotato believes it already
owns it, so it never appears and is never searched for.

    Harry Potter Deathly Hallows Part 1  <- Part 1 (2010) and Part 2 (2011)
    Hunger Games Mockingjay Part 1       <- Part 1 (2014) and Part 2 (2015)
    The Lion King                        <- Lion King (2019) and Lion (2016)
    Beetlejuice                          <- 1988, Beetlejuice 2 (2024), and one more
    Aladdin                              <- 1992 and 2019
    Mulan                                <- 1998 and 2020
    Mean Girls                           <- 2004 and 2024

## Root cause

`couchpotato/core/plugins/scanner/folder_scanner.py`, `determineMedia`, fifth
fallback. It builds a query containing the year, asks for ONE result, and takes
it. The provider does not rank on year. Measured against the live provider:

    "Mulan 2020"      -> 0. Mulan 1998          1. Mulan 2020
    "Aladdin 2019"    -> 0. Aladdin 1992        1. Aladdin 2019
    "Mean Girls 2024" -> 0. Mean Girls 2004     1. Mean Girls 2024
    "Lion King 2019"  -> 0. The Lion King 1994  1. The Lion King 2019

The correct film is position 1 every time. `limit=1` guarantees it is never
seen. The parsed year is already in hand and already in the query; it is simply
never used to choose between results.

## Why the FIRST design was withdrawn, and this matters more than the fix

The first version of this spec said: when the year is known and no candidate
matches it, REFUSE to identify the file, on the reasoning that an unidentified
file is visible as missing while a wrongly identified one is invisible.

That reasoning is correct in isolation and catastrophic in this system.

`manage.updateLibrary` deletes every terminal movie absent from the scan result,
with `delete_from='all'`: the media document, every release document, the
library entry, watch state, tags, profile and review state. It infers "this
movie is gone" from "this scan did not find it". A refused file produces no
identifier, so it is absent from `added_identifiers`, so a film owned ONLY as a
remake, a 2024 Mean Girls with no 2004 copy, would be deleted outright by the
next nightly scan.

The implementation built the refusal exactly as specified. It was caught by
`tests/unit/test_renamer_decision_memory.py::TestFolderScannerIsUntouched`,
which freezes this module against master precisely because it feeds that
cleanup. The freeze did its job: it is a stop-and-think device, and the thinking
changed the design.

## The invariant this change must preserve

**The scan must never produce fewer identifiers than it does today.** This
change may only alter WHICH identifier the fallback returns, never WHETHER one
is returned. Any design that can return None where the current code returns an
id is a data-loss design in this system, regardless of how correct it looks in
isolation.

## Scope

The fifth fallback in `determineMedia` only, plus the freeze test, which must be
replaced by a guard on the invariant above rather than deleted.

## Not in scope

- The first four identification routes. They are assertions and are fine.
- The cleanup in `manage.updateLibrary`. It is already hardened once
  (`library_fully_scanned`) and rewriting its inference is its own change.
- Splitting the seven merged records. Deliberately after this.
- The two sequel cases. Round-one review of 0dc9e9a78 partly establishes
  the cause (see Recorded debt item 1) but stops short of confirming it
  against the actual production data.

## Acceptance criteria

- **AC-DATA-1:** When the parsed year is known and a candidate's year matches
  within tolerance, that candidate is chosen even when it is not first. Proven
  with the four measured cases, driven through the real function.
- **AC-DATA-2 (REPLACES the withdrawn refusal):** When the parsed year is known
  and NO candidate matches, the fallback returns the FIRST candidate, exactly as
  today. It must never return None in a case where the current code returns an
  id. This is the safety property; it is not negotiable and it is the reason the
  first design was withdrawn.
- **AC-DATA-3:** When the parsed year is unknown, behaviour is unchanged.
- **AC-OPS-4:** Choosing a candidate whose year disagrees with the parsed year
  is logged at warning level with the filename, the parsed year and the years
  offered. The operator can then see a bad guess without the guess being
  destructive.
- **AC-QA-5:** A guard fails if the fallback takes a candidate whose year
  disagrees when a matching one was available. Proven by restoring the
  take-the-first behaviour and watching it fail on the Mulan case.
- **AC-QA-6:** A guard proves the invariant directly: for every input where the
  pre-change code produced an identifier, the changed code also produces one.
  Drive both, do not reason about it.
- **AC-QA-7:** `TestFolderScannerIsUntouched` is replaced, not deleted. The
  freeze was a proxy for "this module must not reduce the scan result"; the
  replacement must assert that property, and must fail if a change reintroduces
  a path returning None where an id was returned before.
- **AC-SIMP-8:** Confined to that one fallback and its guard. The other four
  routes are untouched.

## Recorded debt

1. The two sequel merges (Deathly Hallows Part 1/2, Mockingjay Part 1/2) are
   PARTLY explained, not fully established. Round-one review of 0dc9e9a78
   found `pickSearchYearMatch` returned the first candidate within
   `SEARCH_YEAR_TOLERANCE`, not the closest one -- so if a search ever
   returned both parts of a duology (a gap of 1 year, inside tolerance)
   with the wrong part listed first, the wrong part would win. Fixed as
   part of this round (score by closest year diff, ties keep the
   earlier-listed candidate). Not fully established as THE cause, because
   the actual candidate order the provider returned for these two specific
   folders was never captured before the merge happened.
2. Five films are on disk with no record; two return nothing from the provider.
3. `manage.updateLibrary`'s "absent means deleted" inference remains a
   single-point data-loss risk, mitigated but not removed.
4. Round-one review asked whether a NARROWED freeze -- covering `scan()`
   and identification routes one to four, where `TestFolderScannerIsUntouched`
   protected something and `TestFolderScannerNeverReducesTheScanResult` has
   no reach -- was worth restoring, since BUG-018 needed no change there at
   all. Decided NOT to add one: a hash/diff freeze over any region is the
   same proxy AC-QA-7 retired, just drawn smaller, and it fails the same
   way -- the day a legitimate change touches that region, whoever hits it
   either updates the recorded hash without reading why it exists (ceremony)
   or is genuinely blocked by something that was never actually at risk.
   Routes one to four are assertions (an id claimed by the download, a CP
   tag, an NFO, an id in the filename), not guesses, so what actually wants
   protecting is "an id claimed this way is still trusted, and this loop's
   iteration-order bugs (see the comment above the filename-in-files route)
   don't come back" -- both already have their own targeted tests
   (`test_identity_provenance.py` and this module's own history). A new
   test asserting each route still resolves known-good input to its known
   id would be more honest protection than a freeze, but building it is new
   test infrastructure for code this bug did not touch, and is left for
   whoever next has reason to change one of those four routes rather than
   built speculatively here.
