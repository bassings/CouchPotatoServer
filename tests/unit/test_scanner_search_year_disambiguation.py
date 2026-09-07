"""BUG-018: the scanner's fifth identification fallback files every remake
under the original.

`determineMedia`'s fifth fallback (`folder_scanner.py`) parses a title and
year out of a filename, asks `movie.search` for candidates, and today takes
whichever candidate comes back FIRST -- the search event was called with
`limit=1`, so nothing else was ever considered. The provider does not rank on
year, and measured against the live provider the correct film was in second
place every time:

    "Mulan 2020"      -> 0. Mulan 1998          1. Mulan 2020
    "Aladdin 2019"    -> 0. Aladdin 1992        1. Aladdin 2019
    "Mean Girls 2024" -> 0. Mean Girls 2004     1. Mean Girls 2024
    "Lion King 2019"  -> 0. The Lion King 1994  1. The Lion King 2019

`manage.updateLibrary` deletes any 'done' movie absent from the scan result,
so filing a remake under the original merges two films into one library
record and the second is never searched for again.

The invariant this suite exists to protect (BUG-018's own redesign, after a
first attempt built the wrong fix): the change may only alter WHICH
identifier the fallback returns, never WHETHER one is returned. A design
that refuses to guess when no year matches sounds safer in isolation and is
catastrophic here -- an unidentified file is invisible to
`manage.updateLibrary`'s "still present" check, so a film owned ONLY as a
remake would be deleted outright by the next scan. AC-DATA-2 and AC-QA-6
below exist specifically to keep that door shut.

Stubbing pattern follows `test_identity_provenance.py`: `get_db` is made to
raise so `determineMedia` falls through to its except branch and returns
`{'identifier': imdb_id, ...}`, which lets these tests read the chosen id
straight off the return value rather than reaching into a real database.
`fireEvent` is replaced outright (not wrapped) for the same reason that file
gives: production events are never touched, only the two this fallback
actually calls (`movie.search`, and `movie.info` on the fallback tail).
"""
import logging
import os

import pytest

import couchpotato.core.plugins.scanner.folder_scanner as folder_scanner_module
from couchpotato.core.plugins.scanner.folder_scanner import FolderScannerMixin
from tests.unit.bug018_selection_helper import pre_bug_018_selection as _pre_bug_018_selection

DEFAULT_FILENAME = '/dl/Some.Movie.2020.mkv'
DEFAULT_IDENTIFIER = 'Some Movie 2020'


@pytest.fixture
def scanner(monkeypatch):
    plugin = FolderScannerMixin()

    # The tail of determineMedia hits the database once an id is chosen.
    # Every test here is about WHICH id gets chosen, so the lookup is made
    # to fail and fall through to the info branch, exactly as
    # test_identity_provenance.py does.
    monkeypatch.setattr(
        folder_scanner_module, 'get_db',
        lambda: (_ for _ in ()).throw(RuntimeError('no db in this test')),
    )
    # The four assertion-based routes ahead of the search fallback must all
    # miss, or these tests would be pinning the wrong code path.
    monkeypatch.setattr(type(plugin), 'getCPImdb', lambda _s, _f: None, raising=False)
    monkeypatch.setattr(folder_scanner_module, 'getImdb', lambda path, check_inside=False: None)
    return plugin


def _group(identifiers=None, filename=DEFAULT_FILENAME, is_dvd=False):
    return {
        'files': {'movie': [filename], 'nfo': []},
        'identifiers': identifiers if identifiers is not None else [DEFAULT_IDENTIFIER],
        'is_dvd': is_dvd,
    }


def _stub_search(monkeypatch, results_by_query):
    """Replaces `fireEvent` with one that answers `movie.search` calls from
    `results_by_query` (query string -> candidate list) and returns `[]`
    for any query not listed, matching a provider that found nothing.
    Every call is recorded so tests can assert on how many searches fired
    and with which queries -- needed for the hazard-3 fallback-to-`other`
    cases below.

    Round-two review of 0dc9e9a78 (FIX 2): the real provider truncates to
    `limit`. This stub used to ignore `limit` entirely and hand back the
    whole configured list regardless -- which meant setting
    `SEARCH_YEAR_DISAMBIGUATION_LIMIT` back to 1 (a full revert of the fix
    in production, since a limit of 1 means the provider itself never
    returns a second candidate for the year preference to choose between)
    left the ENTIRE suite green, because no fixture here ever depended on
    getting more than one result back. Honouring `limit` here makes every
    case that relies on seeing a second candidate genuinely depend on the
    limit the production code asks for.
    """
    calls = []

    def _fire(event, *args, **kwargs):
        if event == 'movie.search':
            calls.append(kwargs)
            results = list(results_by_query.get(kwargs.get('q'), []))
            limit = kwargs.get('limit')
            if limit is not None:
                results = results[:limit]
            return results
        return None

    monkeypatch.setattr(folder_scanner_module, 'fireEvent', _fire)
    return calls


def _stub_name_year(monkeypatch, scanner_instance, name_year):
    monkeypatch.setattr(
        type(scanner_instance), 'getReleaseNameYear',
        lambda _s, identifier, file_name=None: dict(name_year),
        raising=False,
    )


# There are TWO `movie.search` call sites in the fallback: the primary
# query, always tried first, and a second one built from `name_year['other']`
# -- reached only when the primary query returns nothing. FIX 5 (round-one
# review of 0dc9e9a78): a candidate list can violate the safety invariant at
# EITHER site, and until now only one ad-hoc test
# (`test_the_second_other_search_gets_the_same_year_preference`, kept below
# for the call-ORDER assertion it makes) drove the `other` site at all, and
# it checked year preference only, not the "never fewer identifiers" safety
# property. `_stub_for_site` lets every test below run unchanged against
# either site.
SEARCH_SITES = ['primary', 'other']


def _stub_for_site(monkeypatch, scanner_instance, site, name_year, candidates):
    """Wires `candidates` to be returned from whichever call site `site`
    names, and stubs `getReleaseNameYear` to match. For `'other'`, the
    primary query is made to return nothing (its own distinct query string,
    so the fallback still reaches the `other` query) and `candidates` are
    returned only from the `other` query -- the fallback's own
    `parsed_year` for that branch is `name_year['other']['year']`, so
    `name_year` here is treated as the `other` payload rather than the
    primary one.
    """
    if site == 'primary':
        search_q = '%(name)s %(year)s' % name_year
        _stub_search(monkeypatch, {search_q: candidates})
        _stub_name_year(monkeypatch, scanner_instance, name_year)
        return
    if site == 'other':
        primary = dict(name_year)
        # A distinct name so the primary and `other` queries never collide
        # -- the fallback only tries `other` when the primary query string
        # differs AND the primary search came back empty.
        primary['name'] = name_year['name'] + ' Primary Only'
        primary_q = '%(name)s %(year)s' % primary
        other_q = '%(name)s %(year)s' % name_year
        assert primary_q != other_q, 'test setup error: primary and other queries collided'
        _stub_search(monkeypatch, {primary_q: [], other_q: candidates})
        combined = dict(primary)
        combined['other'] = dict(name_year)
        _stub_name_year(monkeypatch, scanner_instance, combined)
        return
    raise ValueError('unknown site %r' % site)


# The four production cases from the spec, each as (name_year, candidates,
# expected_imdb) -- candidates are given in the buggy provider order (wrong
# film first), so a test asserting `expected_imdb` fails today and passes
# once the fallback prefers the year match over position.
MEASURED_CASES = [
    pytest.param(
        {'name': 'Mulan', 'year': 2020},
        [{'imdb': 'tt0120762', 'year': 1998}, {'imdb': 'tt3480796', 'year': 2020}],
        'tt3480796',
        id='mulan_2020_over_1998_remake',
    ),
    pytest.param(
        {'name': 'Aladdin', 'year': 2019},
        [{'imdb': 'tt0103639', 'year': 1992}, {'imdb': 'tt6139732', 'year': 2019}],
        'tt6139732',
        id='aladdin_2019_over_1992_remake',
    ),
    pytest.param(
        {'name': 'Mean Girls', 'year': 2024},
        [{'imdb': 'tt0377092', 'year': 2004}, {'imdb': 'tt6791350', 'year': 2024}],
        'tt6791350',
        id='mean_girls_2024_over_2004_remake',
    ),
    pytest.param(
        {'name': 'Lion King', 'year': 2019},
        [{'imdb': 'tt0110357', 'year': 1994}, {'imdb': 'tt6105098', 'year': 2019}],
        'tt6105098',
        id='lion_king_2019_over_1994_remake',
    ),
    # Round-two review of BUG-018 (FIX 4): every case above puts the
    # correct film no deeper than second place, so `SEARCH_YEAR_DISAMBIGUATION_LIMIT`
    # could be lowered all the way to 2 and this suite would not notice --
    # the constant's own comment claims headroom for candidates further
    # down the list, and nothing was pinning that claim. Here the correct
    # film sits fourth (index 3), behind three decoys that all carry the
    # wrong year, so a limit below 4 truncates it out of the candidate list
    # before the year preference ever sees it.
    pytest.param(
        {'name': 'Some Buried Sequel', 'year': 2020},
        [
            {'imdb': 'ttDECOY1', 'year': 2001},
            {'imdb': 'ttDECOY2', 'year': 2005},
            {'imdb': 'ttDECOY3', 'year': 2010},
            {'imdb': 'ttCORRECT', 'year': 2020},
            {'imdb': 'ttDECOY4', 'year': 2015},
        ],
        'ttCORRECT',
        id='correct_film_buried_at_fourth_position',
    ),
]


class TestTheYearMatchWinsOverPosition:
    """AC-DATA-1 and AC-QA-5 (the same assertion serves both: restoring
    take-the-first -- i.e. reverting the fix -- makes every case here fail
    on the Mulan case exactly as AC-QA-5 requires).

    RED today: the production fallback calls `movie.search(..., limit=1)`
    and takes `movie[0]` unconditionally, so it returns the WRONG (first)
    candidate for every one of these measured cases.

    FIX 5: parametrized over `SEARCH_SITES` so both `movie.search` call
    sites the fallback owns -- the primary query and the `name_year['other']`
    query -- are driven through the same assertions, not just the primary
    one.
    """

    @pytest.mark.parametrize('site', SEARCH_SITES)
    @pytest.mark.parametrize('name_year, candidates, expected_imdb', MEASURED_CASES)
    def test_candidate_matching_the_parsed_year_wins_even_when_listed_second(
        self, scanner, monkeypatch, site, name_year, candidates, expected_imdb,
    ):
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == expected_imdb, (
            'expected the candidate whose year matches the parsed year %r '
            'to win regardless of position, got %r from candidates %r at '
            'the %s call site -- this is the exact merge BUG-018 measured '
            'in production' % (
                name_year['year'], result.get('identifier'), candidates, site,
            )
        )

    @pytest.mark.parametrize('site', SEARCH_SITES)
    def test_a_one_year_provider_discrepancy_still_matches(self, scanner, monkeypatch, site):
        """Hazard 1: `getReleaseNameYear` parses a year from the filename,
        and a provider's release year can legitimately differ from that by
        one (region release dates, festival vs. wide release). Tolerance
        of exactly 1 is used -- not 0, which would treat every honestly
        off-by-one provider year as a non-match and always fall back to
        the first result; not more than 1, which starts risking exactly
        the remake collisions this bug is about (measured against the
        spec's own seven merged records, the closest of the four remake
        pairs is 20 years apart -- the binding constraint is the
        consecutive-year SEQUEL pairs, at a gap of 1)."""
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [
            {'imdb': 'ttOLD', 'year': 1998},
            {'imdb': 'ttNEW', 'year': 2019},  # one year off the parsed 2020
        ]
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == 'ttNEW', (
            'a candidate one year off the parsed year should still count '
            'as a match ahead of an unrelated candidate decades away; got '
            '%r at the %s call site' % (result.get('identifier'), site)
        )

    def test_the_second_other_search_gets_the_same_year_preference(
        self, scanner, monkeypatch,
    ):
        """Hazard 3: there are TWO search call sites in this fallback -- the
        primary query, and a second one built from
        `name_year['other']` when the primary returns nothing. Both must
        apply the same year preference or the fix only half-covers the
        defect."""
        primary = {'name': 'Mulan', 'year': 2020}
        other = {'name': 'Mulan the Movie', 'year': 2020}
        name_year = dict(primary)
        name_year['other'] = other

        primary_q = '%(name)s %(year)s' % primary
        other_q = '%(name)s %(year)s' % other
        candidates = [{'imdb': 'tt0120762', 'year': 1998}, {'imdb': 'tt3480796', 'year': 2020}]

        calls = _stub_search(monkeypatch, {primary_q: [], other_q: candidates})
        _stub_name_year(monkeypatch, scanner, name_year)

        result = scanner.determineMedia(_group())

        assert [c.get('q') for c in calls] == [primary_q, other_q], (
            'setup: the primary query must return empty so the fallback '
            'reaches the "other" query at all, got queries %r' % (
                [c.get('q') for c in calls],
            )
        )
        assert result.get('identifier') == 'tt3480796', (
            'the second ("other") search took the wrong candidate too: '
            'got %r' % result.get('identifier')
        )


class TestFirstWithinToleranceWinsOverAnExactMatchListedSecond:
    """FIX 1, round two of BUG-018's review (reverts round one's own FIX 3).

    Round one changed the selection from "first candidate within
    `SEARCH_YEAR_TOLERANCE`" to "closest candidate within tolerance", to try
    to close the two consecutive-year sequel merges recorded as debt (see
    the spec's Recorded debt item 1: Deathly Hallows Part 1/2, Mockingjay
    Part 1/2, a gap of exactly 1). Measured live against the real provider,
    that traded a smaller bug for a bigger one: `SEARCH_YEAR_DISAMBIGUATION_LIMIT`'s
    query sends `year=<parsed year>`, so the result set is routinely stuffed
    with candidates carrying the EXACT parsed year -- and an honest
    one-year discrepancy between a filename and its provider record is
    exactly the case `SEARCH_YEAR_TOLERANCE` exists to absorb, not a rare
    edge. Three cases measured live 2026-09-06 (a December release ripped
    the following January carries the following year in its filename,
    which is common):

        search "Wicked 2025"     -> 0. Wicked (2024) CORRECT   1. Wicked: For Good (2025)
        search "Nosferatu 2025"  -> 0. Nosferatu (2024) CORRECT 1. Nosferatu (2025)
        search "Anora 2025"      -> 0. Anora (2024) CORRECT     1. Anora: Stripped Down (2025)

    Under closest-wins the exact-year decoy at position 1 beats the correct
    film at position 0 in all three -- the tolerance is defeated in exactly
    the case it was added for. Reverted to first-within-tolerance, which
    gets all three right, at the acknowledged cost that the two
    consecutive-year sequel merges closest-wins was meant to fix stay
    UNFIXED whenever the provider lists the earlier part first. RED against
    round one's closest-wins: each case here has an EXACT match listed
    SECOND, which closest-wins would prefer over the off-by-one candidate
    listed first.
    """

    @pytest.mark.parametrize('site', SEARCH_SITES)
    @pytest.mark.parametrize('name_year, candidates, expected_imdb', [
        pytest.param(
            {'name': 'Wicked', 'year': 2025},
            [
                {'imdb': 'ttWICKED2024', 'year': 2024},  # correct, one year off, listed first
                {'imdb': 'ttWICKED2025', 'year': 2025},  # decoy, exact parsed year
            ],
            'ttWICKED2024',
            id='wicked_2024_correct_over_2025_exact_year_decoy',
        ),
        pytest.param(
            {'name': 'Nosferatu', 'year': 2025},
            [
                {'imdb': 'ttNOSFERATU2024', 'year': 2024},
                {'imdb': 'ttNOSFERATU2025', 'year': 2025},
            ],
            'ttNOSFERATU2024',
            id='nosferatu_2024_correct_over_2025_exact_year_decoy',
        ),
        pytest.param(
            {'name': 'Anora', 'year': 2025},
            [
                {'imdb': 'ttANORA2024', 'year': 2024},
                {'imdb': 'ttANORA2025', 'year': 2025},
            ],
            'ttANORA2024',
            id='anora_2024_correct_over_2025_exact_year_decoy',
        ),
    ])
    def test_the_correct_off_by_one_film_beats_an_exact_year_decoy_listed_second(
        self, scanner, monkeypatch, site, name_year, candidates, expected_imdb,
    ):
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == expected_imdb, (
            'the correct film, one year off the parsed year and listed '
            'FIRST, lost to an exact-parsed-year decoy listed second -- got '
            '%r at the %s call site. This is closest-wins coming back: it '
            'defeats SEARCH_YEAR_TOLERANCE in exactly the case it exists '
            'for.' % (result.get('identifier'), site)
        )

    @pytest.mark.parametrize('site', SEARCH_SITES)
    def test_an_off_by_one_candidate_wins_over_an_exact_match_listed_second(
        self, scanner, monkeypatch, site,
    ):
        """The general case behind the three measured ones above: ANY
        off-by-one candidate listed before an exact match must win, not
        just the three named productions -- first-within-tolerance, not
        closest-within-tolerance."""
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [
            {'imdb': 'ttOFFBYONE', 'year': 2019},
            {'imdb': 'ttEXACT', 'year': 2020},
        ]
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == 'ttOFFBYONE', (
            'an off-by-one candidate listed FIRST lost to an exact year '
            'match listed second -- got %r at the %s call site. '
            'First-within-tolerance must take the first in-tolerance '
            'candidate, not the closest one.' % (result.get('identifier'), site)
        )

    @pytest.mark.parametrize('site', SEARCH_SITES)
    def test_a_tie_in_year_distance_keeps_the_earlier_listed_candidate(
        self, scanner, monkeypatch, site,
    ):
        """Two candidates equally close to the parsed year (here, both an
        exact match) must resolve to the earlier-listed one -- true of
        first-within-tolerance by construction, since it returns as soon as
        it finds an in-tolerance candidate and never looks further."""
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [
            {'imdb': 'ttFIRST', 'year': 2020},
            {'imdb': 'ttSECOND', 'year': 2020},
        ]
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == 'ttFIRST', (
            'two equally-close candidates should keep the earlier-listed '
            'one -- got %r at the %s call site' % (result.get('identifier'), site)
        )


class TestTheSequelMergesStayUnfixed:
    """Recorded debt item 1 (spec): the two consecutive-year sequel pairs
    (Deathly Hallows Part 1/2, Mockingjay Part 1/2) that motivated round
    one's closest-wins attempt are NOT fixed by reverting to
    first-within-tolerance.

    Round-two review of BUG-018 suggested this read better as
    `xfail(strict=True)` with the assertion written as the DESIRED answer,
    so the accepted debt shows up in every run's summary line (as an
    xfail) instead of hiding among the passes, and still fails loudly
    (XPASS, which `strict=True` turns into a suite failure) the day someone
    fixes it -- taken here, since the repo already uses the idiom four
    times (`test_renamer_mover.py`, `test_operator_route_does_not_forge_its_own_baseline.py`)
    and it gives this specific debt item better visibility for the same
    assertion, with no change in what is actually verified.

    This is expected behaviour, not a regression: AC-DATA-2's safety
    property (never fewer identifiers than before) still holds -- the group
    IS identified, just as the wrong half of the duology, exactly as the
    pre-BUG-018 code would also have done had it seen Part 1 listed first.
    """

    @pytest.mark.xfail(strict=True, reason=(
        "BUG-018 spec, recorded debt item 1: first-within-tolerance still "
        "files Part 2 under Part 1's identifier when the provider lists "
        "Part 1 first (an honest off-by-one on the correct film is "
        "indistinguishable from an exact-year decoy for the wrong one -- "
        "see the spec for why closest-wins was tried and reverted). "
        "strict=True: if this now XPASSes, the sequel-merge case has been "
        "fixed and the spec's debt item 1 should be closed, not just this "
        "test updated."
    ))
    def test_deathly_hallows_part_2_resolves_to_its_own_identifier_when_listed_first(
        self, scanner, monkeypatch,
    ):
        name_year = {'name': 'Harry Potter Deathly Hallows Part 2', 'year': 2011}
        candidates = [
            {'imdb': 'ttHP1', 'year': 2010},  # Part 1, one year off, listed first
            {'imdb': 'ttHP2', 'year': 2011},  # Part 2, the exact match
        ]
        _stub_for_site(monkeypatch, scanner, 'primary', name_year, candidates)

        result = scanner.determineMedia(_group())

        # Written as the DESIRED answer, not today's actual one (ttHP1).
        assert result.get('identifier') == 'ttHP2', (
            'Part 2 should resolve to its own identifier even when the '
            'provider lists Part 1 first -- got %r. This is the accepted, '
            'currently-unfixed limitation from the spec\'s debt item 1' % (
                result.get('identifier'),
            )
        )


class TestNoMatchFallsBackToTheFirstCandidate:
    """AC-DATA-2, the safety property that replaced the withdrawn refusal
    design. A candidate list where NOTHING matches the parsed year must
    still yield the first candidate, exactly as the current code does --
    never None. This is expected to hold both before and after the fix (the
    current code already always takes the first result); its job is to
    catch a FUTURE regression back toward refusal, not to be RED today.

    FIX 5: parametrized over both call sites, per `SEARCH_SITES`.
    """

    @pytest.mark.parametrize('site', SEARCH_SITES)
    def test_takes_the_first_candidate_when_no_year_matches(self, scanner, monkeypatch, site):
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [{'imdb': 'ttAAA', 'year': 1999}, {'imdb': 'ttBBB', 'year': 1950}]
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == 'ttAAA', (
            'must return the FIRST candidate exactly as the pre-BUG-018 '
            'code did when no candidate matches the parsed year at the %s '
            'call site -- refusing to guess here is the data-loss design '
            'BUG-018 withdrew, since a refused file is invisible to '
            'manage.updateLibrary\'s "still present" check and would be '
            'deleted on the next scan' % site
        )


class TestAMalformedSearchResultDoesNotAbortIdentification:
    """FIX 2 (round-one review of 0dc9e9a78). The fifth fallback was the
    only one of the five identification routes with no exception guard
    around its search: `candidate.get('year')` sat ABOVE the `try`, and the
    warning's `[c.get('year') for c in candidates]` had no guard either. Not
    reachable with the single shipped search provider today (it always
    returns dicts) -- reachable the moment a second provider is registered,
    or a provider bug returns something unexpected. Left unguarded, this
    raises out of `determineMedia`, out of `scan()`, mid-directory:
    `fireEvent` swallows it, but `added_identifiers` is then left PARTIAL
    and non-empty, so `manage.updateLibrary`'s cleanup runs against a
    truncated scan and deletes every 'done' movie the scan had not reached
    yet.
    """

    def test_a_non_dict_candidate_among_dict_candidates_is_skipped_not_fatal(
        self, scanner, monkeypatch,
    ):
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = ['a malformed string result', {'imdb': 'ttGOOD', 'year': 2020}]
        _stub_for_site(monkeypatch, scanner, 'primary', name_year, candidates)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == 'ttGOOD', (
            'a non-dict entry among otherwise-good candidates must not '
            'prevent the good one from being chosen -- got %r' % result.get('identifier')
        )

    def test_a_non_list_search_result_does_not_raise_and_moves_on(
        self, scanner, monkeypatch,
    ):
        """The search event itself misbehaving (returns something with no
        `len()`) must not raise out of `determineMedia` -- it must be
        treated as this identifier failing to resolve, exactly like a
        provider returning nothing."""
        def _fire(event, *args, **kwargs):
            if event == 'movie.search':
                return 42  # not list-like: len(42) raises TypeError
            return None

        monkeypatch.setattr(folder_scanner_module, 'fireEvent', _fire)
        _stub_name_year(monkeypatch, scanner, {'name': 'Some Movie', 'year': 2020})

        result = scanner.determineMedia(_group())  # must not raise

        assert result == {}, (
            'a malformed (non-list) search result should leave this '
            'identifier unresolved, not raise -- got %r' % result
        )

    def test_a_later_identifier_still_resolves_after_an_earlier_one_raises(
        self, scanner, monkeypatch,
    ):
        """The scan-level stakes: `group['identifiers']` can hold several
        candidate strings, tried in order until one resolves. A malformed
        result for the FIRST identifier must not stop the loop from trying
        the second -- an uncaught exception here would raise out of
        `determineMedia` entirely, leaving the group unidentified even
        though a later identifier could have resolved it."""
        calls = []

        def _fire(event, *args, **kwargs):
            if event == 'movie.search':
                calls.append(kwargs.get('q'))
                if kwargs.get('q') == 'Bad Movie 2020':
                    return 42  # malformed: raises inside determineMedia
                if kwargs.get('q') == 'Good Movie 2020':
                    return [{'imdb': 'ttGOOD', 'year': 2020}]
            return []

        monkeypatch.setattr(folder_scanner_module, 'fireEvent', _fire)

        name_years = {
            'Bad Movie Identifier': {'name': 'Bad Movie', 'year': 2020},
            'Good Movie Identifier': {'name': 'Good Movie', 'year': 2020},
        }
        monkeypatch.setattr(
            type(scanner), 'getReleaseNameYear',
            lambda _s, identifier, file_name=None: dict(name_years[identifier]),
            raising=False,
        )

        group = _group(identifiers=['Bad Movie Identifier', 'Good Movie Identifier'])
        result = scanner.determineMedia(group)

        assert calls == ['Bad Movie 2020', 'Good Movie 2020'], (
            'setup: expected both identifiers to be tried in order, got %r' % calls
        )
        assert result.get('identifier') == 'ttGOOD', (
            'the first identifier\'s malformed search result stopped the '
            'loop from trying the second, resolvable one -- got %r' % result.get('identifier')
        )


class TestAMalformedFilenameDuringTheWarningDoesNotStarveIdentification:
    """FIX 4a (round-two review of 0dc9e9a78). `pickSearchYearMatch`'s
    mismatched-guess warning calls `os.path.basename(filename)`, which
    raises TypeError for a `filename` that is not str/bytes/os.PathLike.
    That call sat OUTSIDE any guard of its own and INSIDE the caller's
    `except Exception:` (determineMedia's own search try/except, added by
    FIX 2 of round one specifically to stop a raise here from being fatal)
    -- so a malformed filename reaching the warning aborted identification
    for this identifier entirely: the withdrawn design's data-loss
    behaviour, reintroduced from the one branch built to prevent it.
    """

    def test_a_non_string_filename_does_not_abort_identification(
        self, scanner, monkeypatch,
    ):
        name_year = {'name': 'Some Movie', 'year': 2020}
        # No candidate matches the parsed year, so the fallback reaches the
        # warning branch, which is where `os.path.basename` is called.
        candidates = [{'imdb': 'ttAAA', 'year': 1999}, {'imdb': 'ttBBB', 'year': 1950}]
        _stub_for_site(monkeypatch, scanner, 'primary', name_year, candidates)

        group = _group(filename=12345)  # not str/bytes/PathLike

        result = scanner.determineMedia(group)  # must not raise

        assert result.get('identifier') == 'ttAAA', (
            'a non-string filename reaching the mismatched-guess warning '
            'aborted identification instead of falling back to the first '
            'candidate -- got %r' % result.get('identifier')
        )

    def test_a_non_string_filename_is_never_logged_verbatim(
        self, scanner, monkeypatch, caplog,
    ):
        """Round-two review of BUG-018 (FIX 5): the comment three lines
        below the `except TypeError:` branch promises a basename only,
        citing this project's no-private-paths-in-logs floor -- but the
        branch itself fell back to `filename` unchanged, so a non-string
        filename that happens to BE or CONTAIN a private path (a list, for
        instance, is not str/bytes/PathLike either) was logged raw at
        WARNING. Only reachable with a non-string filename, which cannot
        happen today, but the guard should not defeat the promise it sits
        next to."""
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [{'imdb': 'ttAAA', 'year': 1999}, {'imdb': 'ttBBB', 'year': 1950}]
        _stub_for_site(monkeypatch, scanner, 'primary', name_year, candidates)

        hostile_filename = ['/home/realuser/private/Some.Movie.2020.mkv']
        group = _group(filename=hostile_filename)

        with caplog.at_level(logging.WARNING):
            scanner.determineMedia(group)

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, 'setup: expected the mismatched-guess warning to fire'
        for message in warnings:
            assert 'realuser' not in message, (
                'the raw non-string filename value leaked into a WARNING log '
                'line -- got %r' % message
            )
            assert 'private' not in message, (
                'the raw non-string filename value leaked into a WARNING log '
                'line -- got %r' % message
            )
            assert 'list' in message, (
                'expected the type name ("list") to stand in for the '
                'unloggable filename -- got %r' % message
            )


class TestAHostileCandidateGetIsSkippedNotFatal:
    """FIX 4b (round-two review of 0dc9e9a78). `_imdb`/`_year` inside
    `pickSearchYearMatch` used to catch only `AttributeError`. The comment
    above the function already justifies the guard as covering "the moment
    a second provider is registered" -- a claim broader than one specific
    exception type. A candidate whose `.get` raises something else (a
    malformed provider payload, or any object with a broken `.get`) must
    be skipped like any other malformed candidate, not propagate out of
    `pickSearchYearMatch` and starve identification for a group where a
    perfectly good candidate was sitting right next to it.
    """

    def test_a_candidate_whose_get_raises_a_non_attributeerror_is_skipped(
        self, scanner, monkeypatch,
    ):
        class _HostileCandidate(dict):
            def get(self, *args, **kwargs):
                raise ValueError('malformed provider payload')

        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [_HostileCandidate(imdb='ttBAD', year=2020), {'imdb': 'ttGOOD', 'year': 2020}]
        _stub_for_site(monkeypatch, scanner, 'primary', name_year, candidates)

        result = scanner.determineMedia(_group())  # must not raise

        assert result.get('identifier') == 'ttGOOD', (
            'a candidate whose .get() raised ValueError (not AttributeError) '
            'propagated out of pickSearchYearMatch instead of being '
            'skipped, starving identification even though a good candidate '
            'was available -- got %r' % result.get('identifier')
        )


class TestUnknownParsedYearBehaviourIsUnchanged:
    """AC-DATA-3. When `getReleaseNameYear` cannot parse a year at all, the
    fallback's `if name_year.get('name') and name_year.get('year'):` guard
    already stops it from searching -- this is unrelated to the fix and
    must stay unrelated to it."""

    def test_no_search_fires_and_no_identifier_is_produced(self, scanner, monkeypatch):
        calls = _stub_search(monkeypatch, {})
        _stub_name_year(monkeypatch, scanner, {'name': 'Some Movie'})  # no 'year' key

        result = scanner.determineMedia(_group())

        assert calls == [], 'a search fired even though no year was parsed'
        assert result == {}
        assert scanner  # keep the fixture referenced for readability


class TestSearchTypePinnedRegardlessOfLimit:
    """FIX 6 (round-one review of 0dc9e9a78). `TheMovieDb.search` derives
    `search_type` from `limit` unless it is pinned explicitly -- and
    `search_type` is part of the request URL, therefore the cache key.
    Raising `SEARCH_YEAR_DISAMBIGUATION_LIMIT` from 1 to 5 (BUG-018's own
    fix) would otherwise silently key this fallback's cache entries
    differently to every other `limit=1` caller (see
    `test_providers.py::TestTheMovieDbProvider` and the round-two-corrected
    docstring on `TheMovieDb.search` for why this is the ONLY benefit --
    `search_type` was measured live to have no effect on which results TMDB
    v3 returns or in what order). `search_type='phrase'` must reach
    `fireEvent` on both call sites regardless of the limit, so raising or
    lowering the limit later can never repeat this.

    Round-two review of 0dc9e9a78 (FIX 2): also asserts `limit` itself
    reaches `fireEvent` as something greater than 1 -- there were
    previously two tests here asserting `search_type` arrives and NONE
    asserting `limit` does, which is how setting
    `SEARCH_YEAR_DISAMBIGUATION_LIMIT` back to 1 (a full revert of the
    production fix) passed the entire suite: nothing checked that the
    fallback actually asked the provider for more than one candidate.
    """

    def test_the_primary_search_pins_search_type_to_phrase(self, scanner, monkeypatch):
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [{'imdb': 'ttAAA', 'year': 2020}]
        calls = _stub_search(monkeypatch, {'%(name)s %(year)s' % name_year: candidates})
        _stub_name_year(monkeypatch, scanner, name_year)

        scanner.determineMedia(_group())

        assert calls, 'setup: the primary search never fired'
        assert calls[0].get('search_type') == 'phrase', (
            'the primary movie.search call did not pin search_type to '
            '"phrase" -- got %r. Without this, raising '
            'SEARCH_YEAR_DISAMBIGUATION_LIMIT above 1 silently changes the '
            'cache key TMDB is queried under.' % calls[0].get('search_type')
        )
        assert calls[0].get('limit', 1) > 1, (
            'the primary movie.search call asked for only %r result(s), so '
            'SEARCH_YEAR_DISAMBIGUATION_LIMIT has been reverted to 1 (or '
            'never raised) -- the year-disambiguation fallback has nothing '
            'to disambiguate between when the provider can only ever return '
            'a single candidate, which is exactly the shape of the bug '
            'BUG-018 fixed' % calls[0].get('limit')
        )

    def test_the_other_search_also_pins_search_type_to_phrase(self, scanner, monkeypatch):
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [{'imdb': 'ttAAA', 'year': 2020}]
        _stub_for_site(monkeypatch, scanner, 'other', name_year, candidates)
        # `_stub_for_site('other', ...)` replaces `fireEvent` again, so
        # re-wrap it here to also record the calls it makes.
        calls = []
        real_fire = folder_scanner_module.fireEvent

        def _recording_fire(event, *args, **kwargs):
            if event == 'movie.search':
                calls.append(kwargs)
            return real_fire(event, *args, **kwargs)

        monkeypatch.setattr(folder_scanner_module, 'fireEvent', _recording_fire)

        scanner.determineMedia(_group())

        assert len(calls) == 2, (
            'setup: expected exactly two movie.search calls (primary then '
            'other), got %r' % calls
        )
        assert calls[1].get('search_type') == 'phrase', (
            'the "other" movie.search call did not pin search_type to '
            '"phrase" -- got %r' % calls[1].get('search_type')
        )
        assert calls[1].get('limit', 1) > 1, (
            'the "other" movie.search call asked for only %r result(s), so '
            'SEARCH_YEAR_DISAMBIGUATION_LIMIT has been reverted to 1 (or '
            'never raised) -- same defect as the primary search, one call '
            'site later' % calls[1].get('limit')
        )


class TestAMismatchedGuessIsLoggedAtWarning:
    """AC-OPS-4. Taking the first candidate when nothing matches must be
    visible to the operator: a bad guess this way is not destructive (the
    renamer refuses to replace on a searched identity), but it is silent
    today. RED today: the current code logs nothing but a debug line with
    the identifier string, naming neither the parsed year nor the years on
    offer.

    FIX 7 (round-one review of 0dc9e9a78): the filename is logged as a
    BASENAME, not the full path -- this is the one line in the fallback
    that reaches WARNING, and the project's security floor is no private
    filesystem paths in logs. The basename still lets an operator find the
    release; the download folder structure around it does not.

    FIX 5: parametrized over both call sites, per `SEARCH_SITES`.
    """

    @pytest.mark.parametrize('site', SEARCH_SITES)
    def test_warns_with_filename_parsed_year_and_offered_years(
        self, scanner, monkeypatch, caplog, site,
    ):
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [{'imdb': 'ttAAA', 'year': 1999}, {'imdb': 'ttBBB', 'year': 1950}]
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        with caplog.at_level(logging.WARNING):
            scanner.determineMedia(_group(filename=DEFAULT_FILENAME))

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        basename = os.path.basename(DEFAULT_FILENAME)
        assert any(
            basename in w and '2020' in w and '1999' in w and '1950' in w
            for w in warnings
        ), (
            'expected a warning naming the filename\'s basename, the parsed '
            'year (2020) and the years offered (1999, 1950) when a '
            'mismatched guess was taken at the %s call site; got warnings: '
            '%r' % (site, warnings)
        )
        assert not any(os.path.dirname(DEFAULT_FILENAME) in w for w in warnings), (
            'the warning still carries the download folder path (%r) -- '
            'FIX 7 redacts the directory, keeping only the basename, so '
            'this must never appear: %r' % (os.path.dirname(DEFAULT_FILENAME), warnings)
        )

    @pytest.mark.parametrize('site', SEARCH_SITES)
    def test_a_matching_candidate_does_not_warn(self, scanner, monkeypatch, caplog, site):
        """Negative control: the warning is for bad guesses specifically,
        not for every successful search -- otherwise AC-OPS-4 would be
        satisfied by warning unconditionally, which teaches operators to
        ignore it."""
        name_year = {'name': 'Mulan', 'year': 2020}
        candidates = [{'imdb': 'tt0120762', 'year': 1998}, {'imdb': 'tt3480796', 'year': 2020}]
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        with caplog.at_level(logging.WARNING):
            scanner.determineMedia(_group())

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [], (
            'a matching candidate was found (tt3480796, year 2020) at the '
            '%s call site yet a warning fired anyway: %r' % (site, warnings)
        )


class TestTheInvariantNeverFewerIdentifiersThanBefore:
    """AC-QA-6. Drives BOTH the reference pre-BUG-018 selection and the real,
    changed `determineMedia` against the same candidate lists, and asserts
    that wherever the old selection found an id, the new code finds one too
    -- not necessarily the SAME one, which is the entire point of AC-DATA-1.

    Covers the four measured cases, the three edge shapes the spec names
    explicitly (a candidate missing its year field, a candidate whose year
    is explicitly `None`, and an empty result set), and three more added by
    round-one review of 0dc9e9a78 (FIX 1 / FIX 5): a YEAR-MATCHING candidate
    that carries no id at all, an empty id, or an explicit `imdb: None`.
    Every one of the original three fixtures in the freeze this class
    replaces (`TestFolderScannerNeverReducesTheScanResult`,
    `test_renamer_decision_memory.py`) carried an `imdb` key on every
    candidate, so none of them could ever have caught FIX 1's defect -- a
    year match with no id STARVING `imdb_id` even though an older,
    id-bearing candidate was sitting right next to it in the same list. A
    fifth case (the parsed year itself being unknown) is proven separately
    below, since there the OLD selection is not "call search and take
    movie[0]" at all -- no search happens on either side of the fix, so
    there is nothing to drive through `_pre_bug_018_selection`.

    FIX 5: also parametrized over both `movie.search` call sites, per
    `SEARCH_SITES` -- previously only the primary site was driven here.
    """

    CANDIDATE_CASES = [
        pytest.param(
            [{'imdb': 'tt0120762', 'year': 1998}, {'imdb': 'tt3480796', 'year': 2020}],
            id='mulan_remake_pair',
        ),
        pytest.param(
            [{'imdb': 'tt0103639', 'year': 1992}, {'imdb': 'tt6139732', 'year': 2019}],
            id='aladdin_remake_pair',
        ),
        pytest.param(
            [{'imdb': 'tt0377092', 'year': 2004}, {'imdb': 'tt6791350', 'year': 2024}],
            id='mean_girls_remake_pair',
        ),
        pytest.param(
            [{'imdb': 'tt0110357', 'year': 1994}, {'imdb': 'tt6105098', 'year': 2019}],
            id='lion_king_remake_pair',
        ),
        pytest.param(
            [{'imdb': 'ttONLY', 'year': 1975}],
            id='single_candidate_year_does_not_match',
        ),
        pytest.param(
            [{'imdb': 'ttNOYEARFIELD'}],
            id='no_year_candidate_missing_key_entirely',
        ),
        pytest.param(
            [{'imdb': 'ttNULLYEAR', 'year': None}],
            id='null_year_candidate_explicit_none',
        ),
        pytest.param(
            [{'imdb': 'ttOLD', 'year': 1998}, {'year': 2020}],
            id='year_match_missing_imdb_key_entirely',
        ),
        pytest.param(
            [{'imdb': 'ttOLD', 'year': 1998}, {'imdb': '', 'year': 2020}],
            id='year_match_empty_imdb',
        ),
        pytest.param(
            [{'imdb': 'ttOLD', 'year': 1998}, {'imdb': None, 'year': 2020}],
            id='year_match_imdb_explicitly_none',
        ),
    ]

    @pytest.mark.parametrize('site', SEARCH_SITES)
    @pytest.mark.parametrize('candidates', CANDIDATE_CASES)
    def test_an_id_the_old_code_found_is_still_found(self, scanner, monkeypatch, candidates, site):
        name_year = {'name': 'Some Movie', 'year': 2020}
        _stub_for_site(monkeypatch, scanner, site, name_year, candidates)

        pre = _pre_bug_018_selection(candidates)
        assert pre is not None, (
            'test setup error: the reference selection found nothing in %r '
            'to compare against' % candidates
        )

        result = scanner.determineMedia(_group())
        post = result.get('identifier')

        assert post is not None, (
            'the pre-BUG-018 selection returned %r for candidates %r at '
            'the %s call site, but the changed code returned no identifier '
            'at all. This is the exact data-loss shape BUG-018\'s withdrawn '
            'first design built: manage.updateLibrary treats "no '
            'identifier" as "movie gone" and deletes it on the next scan.'
            % (pre, candidates, site)
        )

    @pytest.mark.parametrize('site', SEARCH_SITES)
    def test_empty_results_produce_no_identifier_on_either_side(self, scanner, monkeypatch, site):
        """Not a regression -- included so the parametrized cases above are
        not vacuously satisfied only because every fixture happens to be
        non-empty. The pre-BUG-018 selection also returns nothing when the
        provider returns nothing, so both sides agreeing on None here is
        correct, not a violation of the invariant."""
        name_year = {'name': 'Some Movie', 'year': 2020}
        _stub_for_site(monkeypatch, scanner, site, name_year, [])

        assert _pre_bug_018_selection([]) is None

        result = scanner.determineMedia(_group())
        assert result == {}

    def test_an_unknown_parsed_year_produces_no_identifier_on_either_side(
        self, scanner, monkeypatch,
    ):
        """The parsed-year-unknown edge case named in AC-QA-6. Neither the
        old nor the new code ever calls `movie.search` here (the fallback's
        own `if name_year.get('year'):` guard stops both), so there is
        nothing for `_pre_bug_018_selection` to be given -- the invariant
        holds trivially by construction, and this test exists to make that
        explicit rather than silently uncovered."""
        calls = _stub_search(monkeypatch, {})
        _stub_name_year(monkeypatch, scanner, {'name': 'Some Movie'})

        result = scanner.determineMedia(_group())

        assert calls == [], 'a search fired despite no parsed year -- both sides should skip it'
        assert result == {}
