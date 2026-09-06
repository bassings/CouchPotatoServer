"""Shared reference oracle for BUG-018's invariant tests.

`pre_bug_018_selection` is the fallback's selection before BUG-018:
`fireEvent('movie.search', ..., limit=1)`, then `movie[0]`, with nothing else
read from the result. It is a plain function of the candidate list, not
imported from production, because production is exactly what these tests
guard -- importing the (now fixed) selection would compare the fix with
itself and could never fail.

Round-two review of 0dc9e9a78 (FIX 5c): this used to be copy-pasted into
`test_scanner_search_year_disambiguation.py` and
`test_renamer_decision_memory.py`. Two copies of one reference oracle in two
files is a drift hazard -- a fix to one copy (a bug in the oracle itself, or
a change to what "pre-BUG-018" means) silently leaves the other stale. Shared
here instead.
"""


def pre_bug_018_selection(candidates):
    if not candidates:
        return None
    return candidates[0].get('imdb')
