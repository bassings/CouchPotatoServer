# BUG-018: the scanner files every remake under the original

**Status:** agreed
**Reported:** 2026-09-06, found while auditing library-to-disk mismatches
**Severity:** wrong data, recoverable. No file is touched; the library record is
wrong.

## What happens

Seven media records in the production library hold files from more than one
film. Measured:

    records holding files from more than one folder : 9
      same year, so a genuine duplicate copy        : 2
      DIFFERENT years, so distinct films merged     : 7

The seven:

    Harry Potter Deathly Hallows Part 1  <- Part 1 (2010) and Part 2 (2011)
    Hunger Games Mockingjay Part 1       <- Part 1 (2014) and Part 2 (2015)
    The Lion King                        <- Lion King (2019) and Lion (2016)
    Beetlejuice                          <- 1988, Beetlejuice 2 (2024), and one more
    Aladdin                              <- 1992 and 2019
    Mulan                                <- 1998 and 2020
    Mean Girls                           <- 2004 and 2024

The consequence is not a wrong file playing. It is that the second film has no
library record: CouchPotato believes it already owns it, so it never appears and
is never searched for. The original is the record that survives, so a user
looking for their 1994 Lion King finds a record pointing at the 2019 remake.

## Root cause

`couchpotato/core/plugins/scanner/folder_scanner.py`, `determineMedia`, has five
identification routes. The first four are assertions: an imdb id from the
download, a CP tag, an NFO, an id in the filename. The fifth is a fuzzy search
and the module's own docstring calls it a guess, which is why the renamer
refuses to delete a destination file on a `search` identity.

That fifth route, at roughly line 459:

    name_year = self.getReleaseNameYear(...)
    if name_year.get('name') and name_year.get('year'):
        search_q = '%(name)s %(year)s' % name_year
        movie = fireEvent('movie.search', q=search_q, merge=True, limit=1)
        ...
        if len(movie) > 0:
            imdb_id = movie[0].get('imdb')

It builds a query containing the year, asks for exactly ONE result, and takes
it. The search does not rank on year, so a remake's query returns the original
first.

Measured against the live provider:

    search "Mulan 2020"       -> 0. Mulan 1998        1. Mulan 2020
    search "Aladdin 2019"     -> 0. Aladdin 1992      1. Aladdin 2019
    search "Mean Girls 2024"  -> 0. Mean Girls 2004   1. Mean Girls 2024
    search "Lion King 2019"   -> 0. The Lion King 1994  1. The Lion King 2019

**The correct film is position 1 in every case.** The parsed year is already in
hand and already in the query; it is simply never used to choose between the
results. `limit=1` guarantees the right answer is never even seen.

Sequels are not affected the same way: "Beetlejuice 2 2024" and "Hunger Games
Mockingjay Part 2 2015" both return the correct film first. The seven merged
records include two sequel cases that arrived by a different route, so fixing
this will not by itself explain those two.

## Scope

The fifth fallback in `determineMedia` only. Raise the result limit, choose the
candidate whose year matches the parsed year, and refuse rather than guess when
none does.

## Not in scope

- The first four identification routes. They are assertions and they are fine.
- Splitting the seven existing records. Separate, and deliberately AFTER this,
  because a cleanup before the fix would be re-merged by the next daily scan.
- The two sequel cases, whose cause is not established.
- Ranking or scoring beyond the year.

## Acceptance criteria

- **AC-DATA-1:** When the parsed year is known and a candidate's year matches
  it, that candidate is chosen, even when it is not first. Proven with the four
  measured cases above, driven through the real function.
- **AC-DATA-2:** When the parsed year is known and NO candidate matches it, the
  scanner refuses to identify the file rather than taking the first result. A
  wrong record is worse than an unidentified file, because an unidentified file
  is visible as missing while a wrong one is invisible.
- **AC-DATA-3:** When the parsed year is unknown, behaviour is unchanged. This
  fix must not make previously identifiable files unidentifiable.
- **AC-OPS-4:** A refusal under AC-DATA-2 is logged with the filename, the
  parsed year, and the years that were offered, so an operator can see why a
  file was skipped. A silent skip reproduces the invisibility this bug is about.
- **AC-QA-5:** A guard fails if the fallback takes a candidate whose year
  disagrees with the parsed year. Proven by restoring the `limit=1`
  take-the-first behaviour and watching it fail on the Mulan case.
- **AC-SIMP-6:** Confined to that one fallback block. The other four routes are
  untouched.

## Recorded debt

1. The two sequel merges (Deathly Hallows, Mockingjay) have a different and
   unestablished cause.
2. Five films are on disk with no record at all; two of them return nothing from
   the provider and may not be addable by lookup.
