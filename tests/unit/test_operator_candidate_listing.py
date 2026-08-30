"""The CANDIDATE LISTING route of FEAT-011: what files can the operator pick?

`_resolveOperatorSource` (`renamer/main.py`, AC-SEC-2) already confines an
operator-supplied SOURCE NAME to `conf('from')`, refusing anything whose
`os.path.realpath` lands outside it, and that confinement is mutation-proven
by `test_replacement_operator_execution.py`. This module tests the layer that
PRODUCES the names the operator picks from in the first place: a listing
route the movie detail picker (`movie_detail.html`, commit 2a405d67) will
call to populate itself.

This file pins five non-negotiable properties, each its own test:

  1. Names only -- never an absolute path. An absolute path in the response
     is both a privacy leak (a filesystem path reaching a client) and an
     invitation for the client to hand one straight back as `source`.
  2. It REUSES `_resolveOperatorSource` rather than a second copy of the
     confinement rule. Proven by making that method refuse everything and
     watching the listing go empty despite real files on disk -- if the
     listing carried its own, separate check, this mock would have no
     effect and the test would fail to catch a second, weaker copy.
  3. A symlink under `conf('from')` whose target resolves OUTSIDE
     `conf('from')` is not offered, using a REAL symlink rather than a
     mocked one, because `_resolveOperatorSource`'s refusal path is itself
     real filesystem resolution (`os.path.realpath`) and a mock could pass
     for the wrong reason.
  4. The route requires authentication like every other view. Driven
     through the real FastAPI dispatch (`TestClient` against the app the
     production server builds), not asserted against the bare handler,
     because the auth gate lives in the dispatcher, not the handler.
  5. One candidate that cannot be stat'd does not blank the whole list. A
     production watch folder holds files an operator does not fully
     control (an in-progress download, a permission oddity over a
     network mount); one bad entry must not hide every good one.

**The contract this file establishes, because none of it exists yet:**

  * `Renamer._listOperatorCandidates(self)` -- the plugin-level worker.
    Reads `conf('from')`, lists its immediate regular-file entries, keeps
    only the ones `self._resolveOperatorSource(name)` does not refuse, and
    returns a plain list of bare names (str). It performs at most one
    `os.path.isfile`-shaped check per entry and swallows an `OSError` from
    that check by excluding the entry rather than raising.
  * `Renamer.operatorCandidatesView(self, **kwargs)` -- the API-facing
    entry point, registered as `renamer.operator_candidates`. Reads
    nothing from `kwargs` (AC-SIMP-8: no client-supplied directory) and
    returns `{'success': True, 'candidates': [...]}`.

Driven against a real filesystem throughout, exactly as
`test_replacement_operator_execution.py` does for the execution layer -- a
return value can be right for the wrong reason, a file on disk cannot.
"""
import os

import pytest

from couchpotato.core.plugins.renamer.main import Renamer


@pytest.fixture
def plugin_with_watch(tmp_path, monkeypatch):
    """A `Renamer` instance (via `__new__`, matching the rest of the
    renamer test suite -- `__init__` registers events and API routes as a
    side effect nothing here needs) with `conf('from')` pointed at a real
    tmp_path folder.
    """
    watch = tmp_path / 'downloads'
    watch.mkdir()

    conf_values = {'from': str(watch)}

    plugin = Renamer.__new__(Renamer)
    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: conf_values.get(key, default),
        raising=False,
    )

    return plugin, watch


class TestCandidateNamesAreNeverPaths:
    """Property 1. An absolute path in the response is a privacy leak and
    lets the client echo a path straight back as `source`.
    """

    def test_returned_entries_are_bare_names_not_paths(self, plugin_with_watch):
        plugin, watch = plugin_with_watch
        (watch / 'Minions.and.Monsters.2160p.mkv').write_bytes(b'x' * 10)
        (watch / 'another-file.mp4').write_bytes(b'y' * 10)

        candidates = plugin._listOperatorCandidates()

        assert set(candidates) == {
            'Minions.and.Monsters.2160p.mkv', 'another-file.mp4',
        }
        for name in candidates:
            assert name == os.path.basename(name), (
                'candidate %r carries path structure, not a bare name' % name
            )
            assert not os.path.isabs(name), (
                'candidate %r is an absolute path' % name
            )
            assert str(watch) not in name, (
                'candidate %r leaks the configured watch-folder path' % name
            )


class TestTheListingReusesTheProvenConfinement:
    """Property 2. `_resolveOperatorSource` is the ALREADY mutation-proven
    confinement (AC-SEC-2). If the listing route is genuinely built on it
    rather than a second, independently-written check, making that method
    refuse everything must empty the listing even though the files are
    real and present on disk.
    """

    def test_a_blanket_refusal_from_resolve_operator_source_empties_the_list(
        self, plugin_with_watch, monkeypatch,
    ):
        plugin, watch = plugin_with_watch
        (watch / 'a.mkv').write_bytes(b'x' * 10)
        (watch / 'b.mkv').write_bytes(b'y' * 10)

        monkeypatch.setattr(
            type(plugin), '_resolveOperatorSource', lambda self, name: None,
        )

        candidates = plugin._listOperatorCandidates()

        assert candidates == [], (
            'the listing returned candidates even though the proven '
            'confinement helper refused every one of them -- it is not '
            'actually being consulted, which means a second, weaker check '
            'exists somewhere in the listing path'
        )


class TestAnEscapingSymlinkIsNeverOffered:
    """Property 3. A REAL symlink, not a mocked refusal, because this is
    exactly the shape `_resolveOperatorSource` is proven against
    (`test_replacement_operator_execution.py`) and the listing route must
    inherit that proof rather than merely gesture at it.
    """

    def test_a_symlink_resolving_outside_the_watch_folder_is_excluded(
        self, plugin_with_watch,
    ):
        plugin, watch = plugin_with_watch
        tmp_path = watch.parent

        outside = tmp_path / 'outside'
        outside.mkdir()
        outside_target = outside / 'secret-elsewhere.mkv'
        outside_target.write_bytes(b'z' * 10)

        (watch / 'legit.mkv').write_bytes(b'x' * 10)
        escaping_link = watch / 'escaping-link.mkv'
        escaping_link.symlink_to(outside_target)

        # Sanity: the symlink really does resolve outside the watch folder,
        # otherwise this test would pass for the wrong reason.
        assert not os.path.realpath(str(escaping_link)).startswith(
            os.path.realpath(str(watch)) + os.sep,
        )

        candidates = plugin._listOperatorCandidates()

        assert 'legit.mkv' in candidates
        assert 'escaping-link.mkv' not in candidates, (
            'a symlink whose target resolves outside conf(\'from\') was '
            'offered as a candidate'
        )


class TestOneUnstattableCandidateDoesNotBlankTheList:
    """Property 5. A permission error, or any other OSError, on ONE entry
    while inspecting it must exclude that entry, not abort the whole
    listing -- a production watch folder holds files the operator does not
    fully control.
    """

    def test_an_oserror_on_one_candidate_still_returns_the_others(
        self, plugin_with_watch, monkeypatch,
    ):
        plugin, watch = plugin_with_watch
        (watch / 'good-one.mkv').write_bytes(b'x' * 10)
        (watch / 'poisoned.mkv').write_bytes(b'y' * 10)
        (watch / 'good-two.mkv').write_bytes(b'z' * 10)

        poisoned_path = str(watch / 'poisoned.mkv')
        real_isfile = os.path.isfile

        def flaky_isfile(path):
            if path == poisoned_path:
                raise PermissionError('permission denied: %s' % path)
            return real_isfile(path)

        monkeypatch.setattr(os.path, 'isfile', flaky_isfile)

        candidates = plugin._listOperatorCandidates()

        assert 'good-one.mkv' in candidates
        assert 'good-two.mkv' in candidates, (
            'a PermissionError raised while inspecting ONE candidate blanked '
            'entries that were never touched'
        )
        assert 'poisoned.mkv' not in candidates


class TestTheRouteRequiresAuthentication:
    """Property 4. Driven through the REAL FastAPI dispatch the production
    server uses (`create_app` + `TestClient`), not against the bare
    handler, because the auth gate this route must honour lives in the
    dispatcher (`couchpotato/__init__.py`'s `api_header_auth_handler`), the
    same gate every other `addApiView` route goes through.
    """

    ROUTE = 'renamer.operator_candidates'
    API_KEY = 'testkey-operator-candidates'

    @pytest.fixture(autouse=True)
    def _registered_route(self, tmp_path, monkeypatch):
        """Register the REAL bound method under its production route name,
        mirroring exactly the `addApiView(...)` call `Renamer.__init__`
        will make -- so a passing test here is a passing test against the
        route the running server actually serves, not a stand-in.
        """
        from couchpotato.api import (
            api, api_locks, api_nonblock, api_docs, api_docs_missing,
            addApiView,
        )
        from couchpotato.environment import Env

        old_api = dict(api)
        old_locks = dict(api_locks)
        old_nonblock = dict(api_nonblock)
        old_docs = dict(api_docs)
        old_missing = list(api_docs_missing)

        watch = tmp_path / 'downloads'
        watch.mkdir()
        (watch / 'candidate.mkv').write_bytes(b'x' * 10)
        conf_values = {'from': str(watch)}

        plugin = Renamer.__new__(Renamer)
        monkeypatch.setattr(
            type(plugin), 'conf',
            lambda _self, key, default=None, **kw: conf_values.get(key, default),
            raising=False,
        )
        addApiView(self.ROUTE, plugin.operatorCandidatesView)

        Env.set('web_base', '/')
        Env.set('api_base', '/api/%s/' % self.API_KEY)
        Env.set('static_path', '/static/')
        Env.set(
            'app_dir',
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__),
            ))),
        )
        Env.set('dev', False)

        settings_data = {
            'username': '', 'password': '', 'api_key': self.API_KEY,
            'dark_theme': False, 'rate_limit_max': 0, 'rate_limit_window': 60,
            'cors_origins': '',
        }

        def mock_setting(key=None, *args, **kwargs):
            if 'value' in kwargs:
                settings_data[key] = kwargs['value']
                return
            if key in settings_data:
                return settings_data[key]
            return kwargs.get('default', '')

        monkeypatch.setattr(Env, 'setting', staticmethod(mock_setting))

        yield

        api.clear()
        api.update(old_api)
        api_locks.clear()
        api_locks.update(old_locks)
        api_nonblock.clear()
        api_nonblock.update(old_nonblock)
        api_docs.clear()
        api_docs.update(old_docs)
        api_docs_missing.clear()
        api_docs_missing.extend(old_missing)

    def _client(self):
        from fastapi.testclient import TestClient
        from couchpotato import create_app

        app = create_app(api_key=self.API_KEY, web_base='/')
        return TestClient(app, raise_server_exceptions=False)

    def test_no_api_key_at_all_is_refused(self):
        client = self._client()
        resp = client.get('/api/%s' % self.ROUTE)

        assert resp.status_code == 401
        body = resp.text
        assert 'candidate.mkv' not in body, (
            'candidate data leaked to an unauthenticated request'
        )

    def test_wrong_api_key_is_refused(self):
        client = self._client()
        resp = client.get(
            '/api/%s' % self.ROUTE, headers={'X-Api-Key': 'not-the-real-key'},
        )

        assert resp.status_code == 401
        assert 'candidate.mkv' not in resp.text

    def test_the_correct_api_key_reaches_the_route(self):
        client = self._client()
        resp = client.get(
            '/api/%s/%s' % (self.API_KEY, self.ROUTE),
        )

        assert resp.status_code == 200, (
            'a request carrying the correct api_key was refused reaching '
            'the candidate listing route'
        )
        data = resp.json()
        assert data.get('success') is True
        assert 'candidate.mkv' in data.get('candidates', [])


class TestOnlyMovieExtensionsAreOffered:
    """H10 (branch review 2026-08-31). `_listOperatorCandidates` currently
    offers every regular file `_resolveOperatorSource` does not refuse, with
    no extension filter at all -- so an operator's fat-fingered click on a
    stray `.srt`, `.nfo`, `.txt` or `.part` file sitting in the same watch
    folder destroys the library copy and installs junk in its place. The
    fix filters to `FileDetectorMixin.extensions['movie']`, the same list
    the scanner already uses to recognise a film.
    """

    def test_non_movie_extensions_are_excluded_movie_extensions_are_kept(
        self, plugin_with_watch,
    ):
        plugin, watch = plugin_with_watch
        (watch / 'Minions.and.Monsters.mkv').write_bytes(b'x' * 10)
        (watch / 'Minions.and.Monsters.en.srt').write_bytes(b'subs' * 10)
        (watch / 'Minions.and.Monsters.nfo').write_bytes(b'info' * 10)
        (watch / 'Minions.and.Monsters.mkv.part').write_bytes(b'partial' * 10)
        (watch / 'readme.txt').write_bytes(b'notes' * 10)

        candidates = plugin._listOperatorCandidates()

        assert candidates == ['Minions.and.Monsters.mkv'], (
            'the listing offered a non-video file as a replacement '
            'candidate -- got %r' % candidates
        )


class TestTheListingIsCappedWithATotalReported:
    """H10. An unbounded listing has no stated limit, and nothing tells the
    caller whether the response is the whole folder or a truncated slice of
    it. The fix applies a stated cap to the returned names while separately
    reporting the true total found, so nothing is dropped silently.
    """

    def test_more_candidates_than_the_cap_are_truncated_with_the_true_total_reported(
        self, plugin_with_watch, monkeypatch,
    ):
        plugin, watch = plugin_with_watch
        monkeypatch.setattr(Renamer, 'OPERATOR_CANDIDATE_LIST_CAP', 3, raising=False)

        for i in range(7):
            (watch / ('movie-%d.mkv' % i)).write_bytes(b'x' * 10)

        response = plugin.operatorCandidatesView()

        assert response.get('success') is True
        assert len(response.get('candidates', [])) == 3, (
            'the candidate listing was not capped at the stated limit -- '
            'got %r' % response.get('candidates')
        )
        assert response.get('total_found') == 7, (
            'the response did not report the TRUE total of 7 matching '
            'files found before the cap was applied -- got %r'
            % response.get('total_found')
        )


class TestTheEmptyResultCarriesANamedReason:
    """H10. `_listOperatorCandidates` currently returns a bare `[]` for
    four completely different situations: not configured, the folder is
    missing, the folder cannot be read, and the folder is genuinely empty.
    The modal has separate states for these, per AC-DESIGN-3, but the
    server currently throws the distinction away at `except OSError: return
    []`. The fix returns a NAMED reason so the caller can tell "nothing
    here" apart from "I could not look".
    """

    def test_an_unconfigured_folder_reports_not_configured(self, tmp_path, monkeypatch):
        plugin = Renamer.__new__(Renamer)
        monkeypatch.setattr(
            type(plugin), 'conf',
            lambda _self, key, default=None, **kw: {'from': ''}.get(key, default),
            raising=False,
        )

        response = plugin.operatorCandidatesView()

        assert response.get('candidates') == []
        assert response.get('reason') == 'not_configured', (
            'an unconfigured watch folder did not report the '
            '"not_configured" reason -- got %r' % response.get('reason')
        )

    def test_a_missing_folder_reports_folder_missing(self, tmp_path, monkeypatch):
        missing = tmp_path / 'this-folder-does-not-exist'
        plugin = Renamer.__new__(Renamer)
        monkeypatch.setattr(
            type(plugin), 'conf',
            lambda _self, key, default=None, **kw: {'from': str(missing)}.get(key, default),
            raising=False,
        )

        response = plugin.operatorCandidatesView()

        assert response.get('candidates') == []
        assert response.get('reason') == 'folder_missing', (
            'a configured but non-existent watch folder did not report '
            'the "folder_missing" reason -- got %r' % response.get('reason')
        )

    def test_an_unreadable_folder_reports_folder_unreadable_not_empty(
        self, plugin_with_watch, monkeypatch,
    ):
        plugin, watch = plugin_with_watch
        (watch / 'a-real-file.mkv').write_bytes(b'x' * 10)

        def _flaky_listdir(path):
            raise PermissionError('permission denied: %s' % path)

        monkeypatch.setattr(os, 'listdir', _flaky_listdir)

        response = plugin.operatorCandidatesView()

        assert response.get('candidates') == []
        assert response.get('reason') == 'folder_unreadable', (
            'a watch folder that raised PermissionError on listdir was not '
            'distinguished from an ordinary empty folder -- got %r'
            % response.get('reason')
        )

    def test_a_genuinely_empty_folder_reports_empty_not_unreadable(
        self, plugin_with_watch,
    ):
        plugin, _watch = plugin_with_watch

        response = plugin.operatorCandidatesView()

        assert response.get('candidates') == []
        assert response.get('reason') == 'empty', (
            'a real, readable, genuinely empty watch folder was not '
            'reported as "empty" -- got %r' % response.get('reason')
        )

    def test_a_populated_folder_reports_the_ok_reason(self, plugin_with_watch):
        plugin, watch = plugin_with_watch
        (watch / 'a-real-file.mkv').write_bytes(b'x' * 10)

        response = plugin.operatorCandidatesView()

        assert response.get('candidates') == ['a-real-file.mkv']
        assert response.get('reason') == 'ok', (
            'a populated, successful listing did not report the "ok" '
            'reason -- got %r' % response.get('reason')
        )
