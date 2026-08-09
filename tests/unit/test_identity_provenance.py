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
