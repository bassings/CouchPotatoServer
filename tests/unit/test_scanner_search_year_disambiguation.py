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

import pytest

import couchpotato.core.plugins.scanner.folder_scanner as folder_scanner_module
from couchpotato.core.plugins.scanner.folder_scanner import FolderScannerMixin

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
    """
    calls = []

    def _fire(event, *args, **kwargs):
        if event == 'movie.search':
            calls.append(kwargs)
            return list(results_by_query.get(kwargs.get('q'), []))
        return None

    monkeypatch.setattr(folder_scanner_module, 'fireEvent', _fire)
    return calls


def _stub_name_year(monkeypatch, scanner_instance, name_year):
    monkeypatch.setattr(
        type(scanner_instance), 'getReleaseNameYear',
        lambda _s, identifier, file_name=None: dict(name_year),
        raising=False,
    )


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
]


class TestTheYearMatchWinsOverPosition:
    """AC-DATA-1 and AC-QA-5 (the same assertion serves both: restoring
    take-the-first -- i.e. reverting the fix -- makes every case here fail
    on the Mulan case exactly as AC-QA-5 requires).

    RED today: the production fallback calls `movie.search(..., limit=1)`
    and takes `movie[0]` unconditionally, so it returns the WRONG (first)
    candidate for every one of these measured cases.
    """

    @pytest.mark.parametrize('name_year, candidates, expected_imdb', MEASURED_CASES)
    def test_candidate_matching_the_parsed_year_wins_even_when_listed_second(
        self, scanner, monkeypatch, name_year, candidates, expected_imdb,
    ):
        search_q = '%(name)s %(year)s' % name_year
        _stub_search(monkeypatch, {search_q: candidates})
        _stub_name_year(monkeypatch, scanner, name_year)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == expected_imdb, (
            'expected the candidate whose year matches the parsed year %r '
            'to win regardless of position, got %r from candidates %r -- '
            'this is the exact merge BUG-018 measured in production' % (
                name_year['year'], result.get('identifier'), candidates,
            )
        )

    def test_a_one_year_provider_discrepancy_still_matches(self, scanner, monkeypatch):
        """Hazard 1: `getReleaseNameYear` parses a year from the filename,
        and a provider's release year can legitimately differ from that by
        one (region release dates, festival vs. wide release). Tolerance
        of exactly 1 is used -- not 0, which would treat every honestly
        off-by-one provider year as a non-match and always fall back to
        the first result; not more than 1, which starts risking exactly
        the remake collisions this bug is about (the closest two of the
        four measured remake pairs are still 7 years apart)."""
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [
            {'imdb': 'ttOLD', 'year': 1998},
            {'imdb': 'ttNEW', 'year': 2019},  # one year off the parsed 2020
        ]
        search_q = '%(name)s %(year)s' % name_year
        _stub_search(monkeypatch, {search_q: candidates})
        _stub_name_year(monkeypatch, scanner, name_year)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == 'ttNEW', (
            'a candidate one year off the parsed year should still count '
            'as a match ahead of an unrelated candidate decades away; got '
            '%r' % result.get('identifier')
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


class TestNoMatchFallsBackToTheFirstCandidate:
    """AC-DATA-2, the safety property that replaced the withdrawn refusal
    design. A candidate list where NOTHING matches the parsed year must
    still yield the first candidate, exactly as the current code does --
    never None. This is expected to hold both before and after the fix (the
    current code already always takes the first result); its job is to
    catch a FUTURE regression back toward refusal, not to be RED today.
    """

    def test_takes_the_first_candidate_when_no_year_matches(self, scanner, monkeypatch):
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [{'imdb': 'ttAAA', 'year': 1999}, {'imdb': 'ttBBB', 'year': 1950}]
        search_q = '%(name)s %(year)s' % name_year
        _stub_search(monkeypatch, {search_q: candidates})
        _stub_name_year(monkeypatch, scanner, name_year)

        result = scanner.determineMedia(_group())

        assert result.get('identifier') == 'ttAAA', (
            'must return the FIRST candidate exactly as the pre-BUG-018 '
            'code did when no candidate matches the parsed year -- '
            'refusing to guess here is the data-loss design BUG-018 '
            'withdrew, since a refused file is invisible to '
            'manage.updateLibrary\'s "still present" check and would be '
            'deleted on the next scan'
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


class TestAMismatchedGuessIsLoggedAtWarning:
    """AC-OPS-4. Taking the first candidate when nothing matches must be
    visible to the operator: a bad guess this way is not destructive (the
    renamer refuses to replace on a searched identity), but it is silent
    today. RED today: the current code logs nothing but a debug line with
    the identifier string, naming neither the parsed year nor the years on
    offer.
    """

    def test_warns_with_filename_parsed_year_and_offered_years(
        self, scanner, monkeypatch, caplog,
    ):
        name_year = {'name': 'Some Movie', 'year': 2020}
        candidates = [{'imdb': 'ttAAA', 'year': 1999}, {'imdb': 'ttBBB', 'year': 1950}]
        search_q = '%(name)s %(year)s' % name_year
        _stub_search(monkeypatch, {search_q: candidates})
        _stub_name_year(monkeypatch, scanner, name_year)

        with caplog.at_level(logging.WARNING):
            scanner.determineMedia(_group(filename=DEFAULT_FILENAME))

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            DEFAULT_FILENAME in w and '2020' in w and '1999' in w and '1950' in w
            for w in warnings
        ), (
            'expected a warning naming the filename, the parsed year (2020) '
            'and the years offered (1999, 1950) when a mismatched guess was '
            'taken; got warnings: %r' % warnings
        )

    def test_a_matching_candidate_does_not_warn(self, scanner, monkeypatch, caplog):
        """Negative control: the warning is for bad guesses specifically,
        not for every successful search -- otherwise AC-OPS-4 would be
        satisfied by warning unconditionally, which teaches operators to
        ignore it."""
        name_year = {'name': 'Mulan', 'year': 2020}
        candidates = [{'imdb': 'tt0120762', 'year': 1998}, {'imdb': 'tt3480796', 'year': 2020}]
        search_q = '%(name)s %(year)s' % name_year
        _stub_search(monkeypatch, {search_q: candidates})
        _stub_name_year(monkeypatch, scanner, name_year)

        with caplog.at_level(logging.WARNING):
            scanner.determineMedia(_group())

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [], (
            'a matching candidate was found (tt3480796, year 2020) yet a '
            'warning fired anyway: %r' % warnings
        )


def _pre_bug_018_selection(candidates):
    """Reference implementation of the fallback's selection before
    BUG-018: `fireEvent('movie.search', ..., limit=1)`, then `movie[0]`,
    with nothing else read from the result. Kept as a plain function of the
    candidate list -- not imported from production -- because production is
    exactly what AC-QA-6 is guarding: importing the (now fixed) selection
    would compare the fix with itself and could never fail.
    """
    if not candidates:
        return None
    return candidates[0].get('imdb')


class TestTheInvariantNeverFewerIdentifiersThanBefore:
    """AC-QA-6. Drives BOTH the reference pre-BUG-018 selection and the real,
    changed `determineMedia` against the same candidate lists, and asserts
    that wherever the old selection found an id, the new code finds one too
    -- not necessarily the SAME one, which is the entire point of AC-DATA-1.

    Covers the four measured cases plus the three edge shapes the spec
    names explicitly: a candidate missing its year field, a candidate whose
    year is explicitly `None`, and an empty result set. A fifth case (the
    parsed year itself being unknown) is proven separately below, since
    there the OLD selection is not "call search and take movie[0]" at all
    -- no search happens on either side of the fix, so there is nothing to
    drive through `_pre_bug_018_selection`.
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
    ]

    @pytest.mark.parametrize('candidates', CANDIDATE_CASES)
    def test_an_id_the_old_code_found_is_still_found(self, scanner, monkeypatch, candidates):
        name_year = {'name': 'Some Movie', 'year': 2020}
        search_q = '%(name)s %(year)s' % name_year
        _stub_search(monkeypatch, {search_q: candidates})
        _stub_name_year(monkeypatch, scanner, name_year)

        pre = _pre_bug_018_selection(candidates)
        assert pre is not None, (
            'test setup error: the reference selection found nothing in %r '
            'to compare against' % candidates
        )

        result = scanner.determineMedia(_group())
        post = result.get('identifier')

        assert post is not None, (
            'the pre-BUG-018 selection returned %r for candidates %r, but '
            'the changed code returned no identifier at all. This is the '
            'exact data-loss shape BUG-018\'s withdrawn first design '
            'built: manage.updateLibrary treats "no identifier" as "movie '
            'gone" and deletes it on the next scan.' % (pre, candidates)
        )

    def test_empty_results_produce_no_identifier_on_either_side(self, scanner, monkeypatch):
        """Not a regression -- included so the parametrized cases above are
        not vacuously satisfied only because every fixture happens to be
        non-empty. The pre-BUG-018 selection also returns nothing when the
        provider returns nothing, so both sides agreeing on None here is
        correct, not a violation of the invariant."""
        name_year = {'name': 'Some Movie', 'year': 2020}
        search_q = '%(name)s %(year)s' % name_year
        _stub_search(monkeypatch, {search_q: []})
        _stub_name_year(monkeypatch, scanner, name_year)

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
