"""`determineMedia` must record HOW it identified a movie (FEAT-009B B4b).

The scanner has five ways to name a group. Four are assertions about this
exact release; the fifth, `movie.search`, is the best match for a title and
year parsed out of a filename, which is a guess.

While the scanner only ever ADDED files, a wrong guess mis-filed a download.
Upgrade replacement changed the consequence: the identity decides whose
releases get fetched and therefore whose library copy gets destroyed, so the
renamer refuses to replace on a searched identity.

That refusal is only as good as this field. These tests exist because
mutation testing found the gap: with the renamer's guard fully tested, making
the scanner record `search` as `nfo` changed nothing, since every renamer test
set the field by hand. The guard would have been inert in production and green
in CI -- the exact shape this project keeps producing.
"""
import pytest

from couchpotato.core.plugins.scanner.folder_scanner import FolderScannerMixin


@pytest.fixture
def scanner(monkeypatch):
    import couchpotato.core.plugins.scanner.folder_scanner as module

    plugin = FolderScannerMixin()

    # determineMedia's tail hits the database. Everything here is about the
    # provenance recorded on the way in, so the lookup is stubbed to fail and
    # fall through to the info branch.
    monkeypatch.setattr(module, 'get_db', lambda: (_ for _ in ()).throw(RuntimeError('no db')))
    monkeypatch.setattr(module, 'fireEvent', lambda *a, **k: {} if k.get('merge') else None)
    return plugin


def _group(**overrides):
    group = {
        'files': {'movie': ['/dl/Some.Movie.2001.mkv'], 'nfo': []},
        'identifiers': ['Some.Movie.2001'],
        'is_dvd': False,
    }
    group.update(overrides)
    return group


class TestEveryIdentityPathRecordsItsSource:
    def test_the_downloaders_own_imdb_id_is_an_assertion(self, scanner):
        group = _group()
        scanner.determineMedia(group, release_download={'imdb_id': 'tt0111161'})
        assert group['identity_source'] == 'download_id'

    def test_a_cp_tag_is_an_assertion(self, scanner, monkeypatch):
        monkeypatch.setattr(type(scanner), 'getCPImdb',
                            lambda _s, _f: 'tt0111161', raising=False)
        group = _group()
        scanner.determineMedia(group)
        assert group['identity_source'] == 'cp_tag'

    def test_an_nfo_is_an_assertion(self, scanner, monkeypatch):
        import couchpotato.core.plugins.scanner.folder_scanner as module
        monkeypatch.setattr(type(scanner), 'getCPImdb', lambda _s, _f: None, raising=False)
        monkeypatch.setattr(module, 'getImdb',
                            lambda path, check_inside=False: 'tt0111161' if check_inside else None)
        group = _group(files={'movie': ['/dl/a.mkv'], 'nfo': ['/dl/a.nfo']})
        scanner.determineMedia(group)
        assert group['identity_source'] == 'nfo'

    def test_an_id_in_the_filename_is_an_assertion(self, scanner, monkeypatch):
        import couchpotato.core.plugins.scanner.folder_scanner as module
        monkeypatch.setattr(type(scanner), 'getCPImdb', lambda _s, _f: None, raising=False)
        monkeypatch.setattr(module, 'getImdb',
                            lambda path, check_inside=False: None if check_inside else 'tt0111161')
        group = _group()
        scanner.determineMedia(group)
        assert group['identity_source'] == 'filename'

    def test_a_title_search_is_recorded_as_a_GUESS(self, scanner, monkeypatch):
        """The one that matters. If this ever records an asserted source, the
        renamer's refusal silently stops protecting anything."""
        import couchpotato.core.plugins.scanner.folder_scanner as module
        monkeypatch.setattr(type(scanner), 'getCPImdb', lambda _s, _f: None, raising=False)
        monkeypatch.setattr(module, 'getImdb', lambda path, check_inside=False: None)
        monkeypatch.setattr(type(scanner), 'getReleaseNameYear',
                            lambda _s, identifier, file_name=None: {'name': 'Some Movie', 'year': '2001'},
                            raising=False)
        monkeypatch.setattr(module, 'fireEvent',
                            lambda *a, **k: [{'imdb': 'tt0111161'}] if a and a[0] == 'movie.search' else None)

        group = _group()
        scanner.determineMedia(group)

        assert group['identity_source'] == 'search', (
            'a fuzzy title match was recorded as an asserted identity; the '
            "renamer's refusal now protects nothing"
        )

    def test_a_group_nothing_could_identify_records_no_source(self, scanner, monkeypatch):
        import couchpotato.core.plugins.scanner.folder_scanner as module
        monkeypatch.setattr(type(scanner), 'getCPImdb', lambda _s, _f: None, raising=False)
        monkeypatch.setattr(module, 'getImdb', lambda path, check_inside=False: None)
        monkeypatch.setattr(type(scanner), 'getReleaseNameYear',
                            lambda _s, identifier, file_name=None: {}, raising=False)

        group = _group()
        scanner.determineMedia(group)
        assert group['identity_source'] is None


class TestTheFieldIsAlwaysPresent:
    def test_it_is_written_even_when_identification_fails(self, scanner, monkeypatch):
        """The renamer refuses a group with no recorded source, so an absent
        field is safe. It is set unconditionally anyway: 'the scanner did not
        set it' and 'the scanner could not identify this' are different
        states, and only one of them means the group came from somewhere
        else."""
        import couchpotato.core.plugins.scanner.folder_scanner as module
        monkeypatch.setattr(type(scanner), 'getCPImdb', lambda _s, _f: None, raising=False)
        monkeypatch.setattr(module, 'getImdb', lambda path, check_inside=False: None)
        monkeypatch.setattr(type(scanner), 'getReleaseNameYear',
                            lambda _s, identifier, file_name=None: {}, raising=False)

        group = _group()
        scanner.determineMedia(group)
        assert 'identity_source' in group


class TestTheFilenameScanStopsAtTheFirstIdItFinds:
    """The `break` left only the inner loop and `imdb_id` was assigned on
    every pass, so the scan carried on after a hit: the next file without an
    id overwrote the answer with None, and a stray NFO carrying a DIFFERENT id
    overwrote it with that. Whichever file type was iterated last won.

    Survivable while the id only decided where a download was filed. Not now:
    `identity_source` is read as "we ASSERT which movie this is", and upgrade
    replacement uses that to authorise destroying the file at the
    destination. An id chosen by iteration order is not an assertion.
    """

    def _scanner_with(self, scanner, monkeypatch, mapping):
        import couchpotato.core.plugins.scanner.folder_scanner as module
        monkeypatch.setattr(type(scanner), 'getCPImdb', lambda _s, _f: None, raising=False)
        monkeypatch.setattr(
            module, 'getImdb',
            lambda path, check_inside=False: None if check_inside else mapping.get(path),
        )
        monkeypatch.setattr(type(scanner), 'getReleaseNameYear',
                            lambda _s, i, file_name=None: {}, raising=False)

    def test_a_later_file_without_an_id_does_not_erase_the_one_found(self, scanner, monkeypatch):
        self._scanner_with(scanner, monkeypatch, {'/dl/movie.mkv': 'tt0111161'})
        group = _group(files={
            'movie': ['/dl/movie.mkv'],
            'subtitle': ['/dl/movie.srt'],      # no id -- used to clear it
            'nfo': [],
        })

        scanner.determineMedia(group)

        assert group['identity_source'] == 'filename', (
            'the id found in the movie filename was erased by a later file '
            'with none, and the group fell through to the fuzzy search'
        )

    def test_a_stray_file_with_a_DIFFERENT_id_does_not_win(self, scanner, monkeypatch):
        """The dangerous shape: a subtitle or NFO whose name carries another
        movie's id would have decided which movie's releases get fetched, and
        therefore whose library copy is at risk."""
        seen = {}
        import couchpotato.core.plugins.scanner.folder_scanner as module

        monkeypatch.setattr(type(scanner), 'getCPImdb', lambda _s, _f: None, raising=False)
        monkeypatch.setattr(type(scanner), 'getReleaseNameYear',
                            lambda _s, i, file_name=None: {}, raising=False)

        ids = {'/dl/movie.mkv': 'tt0111161', '/dl/other.srt': 'tt9999999'}

        def _get_imdb(path, check_inside=False):
            if check_inside:
                return None
            seen.setdefault('order', []).append(path)
            return ids.get(path)

        monkeypatch.setattr(module, 'getImdb', _get_imdb)

        group = _group(files={'movie': ['/dl/movie.mkv'], 'subtitle': ['/dl/other.srt']})
        scanner.determineMedia(group)

        assert '/dl/other.srt' not in seen.get('order', []), (
            'the scan kept going after finding an id and read a file carrying '
            "a different movie's id: %r" % seen.get('order')
        )
        assert group['identity_source'] == 'filename'

    def test_no_id_anywhere_still_records_no_source(self, scanner, monkeypatch):
        self._scanner_with(scanner, monkeypatch, {})
        group = _group(files={'movie': ['/dl/movie.mkv'], 'nfo': ['/dl/a.nfo']})
        scanner.determineMedia(group)
        assert group['identity_source'] is None
