"""Characterisation of folder-scanner helpers whose expressions were tidied.

Each test pins behaviour that is observable through the public or semi-public
helper so the underlying expression can change without changing results.
"""
import pytest

from couchpotato.core.plugins.scanner.file_detector import FileDetectorMixin
from couchpotato.core.plugins.scanner.folder_scanner import FolderScannerMixin


class _Scanner(FileDetectorMixin, FolderScannerMixin):
    def shuttingDown(self):
        return False


@pytest.fixture
def scanner():
    return _Scanner()


# ---- findYear: bracketed pattern first, bare pattern second, ASCII digits only

@pytest.mark.parametrize(('text', 'expected'), [
    ('Movie (1999)', '1999'),
    ('Movie [2005]', '2005'),
    ('Movie (1999]', '1999'),           # the two brackets are independent
    ('Movie [2005)', '2005'),
    ('Movie 2010 720p', '2010'),
    ('Movie 1900', '1900'),
    ('Movie 1999', '1999'),
    ('Movie 2000', '2000'),
    ('Movie 2099', '2099'),
    ('Movie 1899', ''),
    ('Movie 2100', ''),
    ('Movie 3012', ''),
    ('Movie 12019', '2019'),            # unanchored on purpose
    ('Movie 19999', '1999'),
    ('(1999) 2005', '1999'),            # bracketed year beats a later bare one
    ('(1999) (2005)', '2005'),          # last bracketed year wins
    ('2010 Movie (2023)', '2023'),
    ('|1999| 2005', '2005'),            # '|' is not a bracket
    (r'\1999\ 2005', '2005'),
    ('{1999} 2005', '2005'),
    (')1999( 2005', '2005'),            # closing before opening is not bracketed
    ('|1999) 2005', '2005'),            # '|' is not an opening bracket
    ('(1999| 2005', '2005'),            # '|' is not a closing bracket
    ('(1999', '1999'),                  # falls through to the bare pattern
    ('1999)', '1999'),
    ('(19)', ''),
    ('', ''),
])
def test_find_year_ascii_cases(scanner, text, expected):
    assert scanner.findYear(text) == expected


@pytest.mark.parametrize('text', [
    'Movie (\u0661\u0669\u0669\u0669)',       # Arabic-Indic 1999 in brackets
    'Movie \u0662\u0660\u0661\u0660',         # Arabic-Indic 2010 bare
    'Movie (19\u0669\u0669)',                 # ASCII prefix, Arabic-Indic tail
    'Movie 19\u0669\u0669',                   # same, bare
    'Movie [20\u0660\u0661]',
    'Movie \uff12\uff10\uff11\uff10',         # fullwidth 2010
    'Movie [\u0968\u0966\u0968\u0966]',       # Devanagari 2020 in brackets
])
def test_find_year_ignores_non_ascii_digits(scanner, text):
    assert scanner.findYear(text) == ''


def test_find_year_prefers_ascii_year_over_non_ascii_neighbour(scanner):
    assert scanner.findYear('(2005) ١٩٩٩') == '2005'


# ---- getCPImdb

@pytest.mark.parametrize(('text', 'expected'), [
    ('movie.cp(tt1234567, abc).mkv', 'tt1234567'),
    ('Movie.CP(TT7654321).mkv', 'tt7654321'),   # lower-cased before matching
    ('movie.cp(tt1).mkv', 'tt1'),
    ('movie.mkv', False),
    ('movie.cp(xx123).mkv', False),
    ('', False),
])
def test_get_cp_imdb(scanner, text, expected):
    assert scanner.getCPImdb(text) == expected


# ---- createStringIdentifier de-duplicates repeated words, keeping first order

@pytest.mark.parametrize(('path', 'expected'), [
    ('/m/Movie Movie 2023/movie movie.mkv', 'movie 2023'),
    ('/m/The Big The Movie (2021)/x.mkv', None),
])
def test_create_string_identifier_collapses_repeated_words(scanner, path, expected):
    result = scanner.createStringIdentifier(path, '/m/')
    words = result.split()
    assert len(words) == len(set(words)), result
    if expected is not None:
        assert result == expected


def test_create_string_identifier_keeps_first_occurrence_order(scanner):
    result = scanner.createStringIdentifier('/m/Zeta Alpha Zeta Beta Alpha/zeta alpha zeta beta alpha.mkv', '/m/')
    assert result == 'zeta alpha beta'


# ---- getReleaseNameYear: both early-return branches hand back cp_guess

def _stub_guess(scanner, monkeypatch, guess):
    monkeypatch.setattr(scanner, '_guess_filename_name_year', lambda _file_name: guess)


def test_release_name_year_returns_cp_guess_when_years_match_and_name_longer(scanner, monkeypatch):
    guess = {'name': 'Short', 'year': 2020}
    _stub_guess(scanner, monkeypatch, guess)

    result = scanner.getReleaseNameYear('Longer.Clean.Title.2020', 'file.2020.mkv')

    assert result['name'] == 'longer clean title'
    assert result['year'] == 2020
    assert result['other'] is guess


def test_release_name_year_returns_cp_guess_when_guess_is_empty(scanner, monkeypatch):
    guess = {}
    _stub_guess(scanner, monkeypatch, guess)

    result = scanner.getReleaseNameYear('Some.Movie.2019', 'file.mkv')

    assert result['name'] == 'some movie'
    assert result['year'] == 2019
    assert result['other'] is guess


def test_release_name_year_with_nothing_detected_returns_empty_cp_guess_plus_other(scanner, monkeypatch):
    guess = {}
    _stub_guess(scanner, monkeypatch, guess)

    result = scanner.getReleaseNameYear('NoYearHere', 'file.mkv')

    assert result == {'other': {}}
    assert result['other'] is guess


def test_release_name_year_returns_guess_when_neither_condition_holds(scanner, monkeypatch):
    guess = {'name': 'A Much Longer Guessed Name', 'year': 2020}
    _stub_guess(scanner, monkeypatch, guess)

    result = scanner.getReleaseNameYear('Short.2020', 'file.mkv')

    assert result is guess
    assert result['other']['name'] == 'short'
    assert result['other']['year'] == 2020


def test_release_name_year_returns_guess_when_years_differ(scanner, monkeypatch):
    guess = {'name': 'x', 'year': 1999}
    _stub_guess(scanner, monkeypatch, guess)

    result = scanner.getReleaseNameYear('Much.Longer.Title.2020', 'file.mkv')

    assert result is guess
    assert result['other']['year'] == 2020


# ---- sidecar grouping

def test_match_group_sidecars_attaches_each_basename_once_and_counts_ignored(scanner):
    group = {'unsorted_files': ['/m/a/Movie.mkv']}
    leftovers = {'/m/a/Movie.srt', '/m/a/Movie.ignore', '/m/a/Other.srt'}

    remaining, has_ignored = scanner._match_group_sidecars(group, leftovers)

    assert sorted(group['unsorted_files']) == ['/m/a/Movie.ignore', '/m/a/Movie.mkv', '/m/a/Movie.srt']
    assert remaining == {'/m/a/Other.srt'}
    # counted over the ORIGINAL snapshot (Movie.mkv only), not the sidecars
    # that were attached while looping
    assert has_ignored == 0


def test_match_group_sidecars_counts_ignored_extension_of_original_files(scanner):
    group = {'unsorted_files': ['/m/a/Movie.ignore']}

    _remaining, has_ignored = scanner._match_group_sidecars(group, {'/m/a/Movie.ignore.srt'})

    assert has_ignored == 1
    assert group['unsorted_files'] == ['/m/a/Movie.ignore', '/m/a/Movie.ignore.srt']


def test_group_has_ignored_extension_counts_every_ignored_file_and_leaves_group_alone(scanner):
    files = ['/m/a.mkv', '/m/a.ignore', '/m/b.lftp-pget-status', '/m/c.srt']
    group = {'unsorted_files': list(files)}

    assert scanner._group_has_ignored_extension(group) == 2
    assert group['unsorted_files'] == files


def test_group_has_ignored_extension_zero_when_clean(scanner):
    assert scanner._group_has_ignored_extension({'unsorted_files': ['/m/a.mkv']}) == 0


def test_leftovers_by_folder_reduces_the_callers_set_to_the_attached_file(scanner):
    movie_files = {'movie': {'unsorted_files': ['/m/Movie/Movie.mkv']}}
    leftovers = {'/m/Movie/extras.nfo', '/m/Movie/more.nfo'}
    path_identifiers = {'extras': ['/m/Movie/extras.nfo']}

    scanner._attach_leftovers_by_folder(movie_files, leftovers, path_identifiers, '/m/')

    assert movie_files['movie']['unsorted_files'] == ['/m/Movie/Movie.mkv', '/m/Movie/extras.nfo']
    assert path_identifiers == {}
    # existing quirk, pinned as is: `leftovers -= leftovers - {ff}` mutates the
    # caller's set in place and keeps ONLY the attached file in it
    assert leftovers == {'/m/Movie/extras.nfo'}
