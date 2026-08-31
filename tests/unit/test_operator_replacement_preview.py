"""H9 (branch review 2026-08-31), FEAT-011's confirmation-preview lookup.

The operator confirmation for the replacement modal currently names NEITHER
the file it is about to destroy NOR the file it will install, and gives no
size on either side (`movie_detail.html:428-433`, `:479-487`). The review's
own framing: "A confirmation that says only replace with X? is not
sufficient and is the single most likely way this ships wrong." This is the
code path whose module docstring records having destroyed an irreplaceable
file TWICE.

This file pins the server-side lookup the confirmation needs, driven
server-side rather than client-guessed, per AC-DESIGN-7 and AC-QA-12:

  * `Renamer._operatorReplacementPreview(self, media_id)` -- the plugin-level
    worker. Resolves the destination the SAME way `_runOperatorReplacement`
    does (`decide_operator_replacement` over `release.for_media`), but is
    READ-ONLY: it touches no file beyond `os.path.getsize`, calls
    `replace_atomically` never, and can be safely called on every render of
    the picker. Returns:

        {
            'destination': {'name': <basename>, 'quality': <label>,
                             'size': <bytes>} or None,
            'candidates': [{'name': <basename>, 'size': <bytes>}, ...],
        }

    `destination` is `None` when there is no single completed release to
    replace (no releases at all, or an ambiguous multi-file release) -- the
    picker has nothing safe to confirm against in that case.

  * `Renamer.operatorReplacementPreviewView(self, **kwargs)` -- the
    API-facing entry point, reading only `media_id` out of `kwargs`,
    returning `{'success': True, 'destination': ..., 'candidates': ...}`.

Every assertion below is on FIXTURE-DERIVED values that differ per case
(distinct byte counts, distinct filenames), per AC-QA-12's explicit
requirement that a hardcoded string must not be able to satisfy this --
a test that only checked for the presence of the word "size" would pass
whether or not the number behind it was correct.

Basenames only, never a path: CLAUDE.md forbids a filesystem path reaching
a client, and every case here asserts the watch folder's and the library's
own directory strings do not appear anywhere in the result.
"""
import os

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes

OLD = b'existing 720p copy' * 100
NEW = b'incoming 2160p copy' * 900


@pytest.fixture
def world(tmp_path, monkeypatch):
    lib = tmp_path / 'library'
    lib.mkdir()
    dst = lib / 'The Thing.mkv'
    dst.write_bytes(OLD)

    watch = tmp_path / 'downloads'
    watch.mkdir()
    src = watch / 'incoming.mkv'
    src.write_bytes(NEW)

    existing_release = {
        '_id': 'r-old',
        'status': 'done',
        'files': {'movie': [str(dst)]},
        'copy_id': copy_id_for_sizes([len(OLD)]),
        'quality': '720p',
        'is_3d': False,
    }

    state = {
        'conf': {'from': str(watch), 'to': str(lib)},
        'releases': {'media-1': [existing_release]},
    }

    def _fire(event, *args, **kwargs):
        if event == 'release.for_media':
            media_id = args[0] if args else kwargs.get('media_id')
            return list(state['releases'].get(media_id, []))
        return None

    monkeypatch.setattr(
        'couchpotato.core.plugins.renamer.main.fireEvent', _fire,
    )

    plugin = Renamer.__new__(Renamer)
    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: state['conf'].get(key, default),
        raising=False,
    )

    return {
        'plugin': plugin, 'src': str(src), 'dst': str(dst),
        'lib': lib, 'watch': watch, 'state': state,
    }


class TestTheDestinationSideNamesTheFileAboutToBeDestroyed:
    """AC-DESIGN-5 / AC-DESIGN-7 / AC-PROD-3 / AC-QA-12. The library file's
    basename, quality label and byte size must all come from the server's
    own resolution, not be guessed or omitted.
    """

    def test_the_destination_basename_quality_and_size_are_reported(self, world):
        preview = world['plugin']._operatorReplacementPreview('media-1')

        destination = preview.get('destination')
        assert destination is not None, (
            'a single completed release exists but no destination was '
            'resolved for the confirmation'
        )
        assert destination.get('name') == 'The Thing.mkv', (
            'wrong or missing destination basename -- got %r'
            % destination.get('name')
        )
        assert destination.get('quality') == '720p', (
            'wrong or missing destination quality label -- got %r'
            % destination.get('quality')
        )
        assert destination.get('size') == len(OLD), (
            'destination size does not match the actual byte size on disk '
            '(expected %d, got %r)' % (len(OLD), destination.get('size'))
        )

    def test_a_differently_sized_and_named_destination_reports_different_values(
        self, tmp_path, monkeypatch,
    ):
        """Fixture-derived values that DIFFER from the sibling test above,
        per AC-QA-12: a hardcoded string in the implementation would pass
        one of these two tests and fail the other.
        """
        lib = tmp_path / 'library'
        lib.mkdir()
        dst = lib / 'Another Film (2019).mkv'
        big = b'a much larger 4K remux copy indeed' * 5000
        dst.write_bytes(big)

        watch = tmp_path / 'downloads'
        watch.mkdir()

        existing_release = {
            '_id': 'r-other',
            'status': 'done',
            'files': {'movie': [str(dst)]},
            'copy_id': copy_id_for_sizes([len(big)]),
            'quality': '2160p',
            'is_3d': False,
        }
        state = {
            'conf': {'from': str(watch), 'to': str(lib)},
            'releases': {'media-9': [existing_release]},
        }

        def _fire(event, *args, **kwargs):
            if event == 'release.for_media':
                media_id = args[0] if args else kwargs.get('media_id')
                return list(state['releases'].get(media_id, []))
            return None

        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.main.fireEvent', _fire,
        )
        plugin = Renamer.__new__(Renamer)
        monkeypatch.setattr(
            type(plugin), 'conf',
            lambda _self, key, default=None, **kw: state['conf'].get(key, default),
            raising=False,
        )

        preview = plugin._operatorReplacementPreview('media-9')
        destination = preview.get('destination')

        assert destination.get('name') == 'Another Film (2019).mkv'
        assert destination.get('quality') == '2160p'
        assert destination.get('size') == len(big)


class TestCandidateSidesReportEachFilesSize:
    """AC-DESIGN-5. Each candidate row must show a size the operator can
    compare against the destination's size without arithmetic -- so the
    preview must report a size per candidate, not just a bare name.
    """

    def test_each_candidate_carries_its_own_byte_size(self, world):
        second = world['watch'] / 'other-copy.mp4'
        second.write_bytes(b'z' * 4096)

        preview = world['plugin']._operatorReplacementPreview('media-1')
        candidates = {c['name']: c['size'] for c in preview.get('candidates', [])}

        assert candidates.get('incoming.mkv') == len(NEW), (
            'incoming.mkv either missing from candidates or reporting the '
            'wrong size -- got %r' % candidates
        )
        assert candidates.get('other-copy.mp4') == 4096, (
            'other-copy.mp4 either missing from candidates or reporting '
            'the wrong size -- got %r' % candidates
        )


class TestNoFilesystemPathEverReachesThePreview:
    """CLAUDE.md's security floor: no filesystem path reaching a client.
    Basenames only, on both sides of the preview.
    """

    def test_neither_the_watch_folder_nor_the_library_path_appears_anywhere(
        self, world,
    ):
        preview = world['plugin']._operatorReplacementPreview('media-1')

        rendered = repr(preview)
        assert str(world['watch']) not in rendered, (
            'the watch folder path leaked into the preview response'
        )
        assert str(world['lib']) not in rendered, (
            'the library folder path leaked into the preview response'
        )


class TestAnAmbiguousOrMissingReleaseReportsNoDestination:
    """The picker has nothing safe to confirm against when there is no
    single completed release to replace -- the preview must say so plainly
    (`destination` is `None`) rather than raising or guessing one.
    """

    def test_no_completed_release_reports_a_none_destination(self, world):
        world['state']['releases']['media-1'] = []

        preview = world['plugin']._operatorReplacementPreview('media-1')

        assert preview.get('destination') is None, (
            'a media id with no completed release reported a destination '
            'anyway -- got %r' % preview.get('destination')
        )

    def test_an_ambiguous_multi_file_release_reports_a_none_destination(self, world):
        second_dst = world['lib'] / 'The Thing - CD2.mkv'
        second_dst.write_bytes(OLD)
        world['state']['releases']['media-1'][0]['files']['movie'] = [
            world['dst'], str(second_dst),
        ]

        preview = world['plugin']._operatorReplacementPreview('media-1')

        assert preview.get('destination') is None, (
            'an ambiguous multi-file release reported a destination '
            'anyway -- the preview must not guess which file it is -- '
            'got %r' % preview.get('destination')
        )


class TestTheRouteRequiresAuthenticationAndReturnsOnlyBasenames:
    """Route-level: driven through the REAL FastAPI dispatch the production
    server uses, matching `test_operator_candidate_listing.py`'s own proof
    for the sibling route -- the auth gate lives in the dispatcher, not the
    handler, so a passing plugin-level test alone proves nothing about it.
    """

    ROUTE = 'renamer.operator_replacement_preview'
    API_KEY = 'testkey-operator-preview'

    @pytest.fixture(autouse=True)
    def _registered_route(self, tmp_path, monkeypatch):
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

        lib = tmp_path / 'library'
        lib.mkdir()
        dst = lib / 'The Thing.mkv'
        dst.write_bytes(OLD)
        watch = tmp_path / 'downloads'
        watch.mkdir()
        (watch / 'incoming.mkv').write_bytes(NEW)

        existing_release = {
            '_id': 'r-old', 'status': 'done',
            'files': {'movie': [str(dst)]},
            'copy_id': copy_id_for_sizes([len(OLD)]),
            'quality': '720p', 'is_3d': False,
        }
        state = {
            'conf': {'from': str(watch), 'to': str(lib)},
            'releases': {'media-1': [existing_release]},
        }

        def _fire(event, *args, **kwargs):
            if event == 'release.for_media':
                media_id = args[0] if args else kwargs.get('media_id')
                return list(state['releases'].get(media_id, []))
            return None

        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.main.fireEvent', _fire,
        )
        plugin = Renamer.__new__(Renamer)
        monkeypatch.setattr(
            type(plugin), 'conf',
            lambda _self, key, default=None, **kw: state['conf'].get(key, default),
            raising=False,
        )
        addApiView(self.ROUTE, plugin.operatorReplacementPreviewView)

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

        self.lib = lib
        self.watch = watch

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
        resp = client.get(
            '/api/%s' % self.ROUTE, params={'media_id': 'media-1'},
        )

        assert resp.status_code == 401
        assert 'The Thing' not in resp.text

    def test_the_correct_api_key_reaches_the_route_and_reports_basenames_only(self):
        client = self._client()
        # T7d items 2 and 3 (round two on C1): this route now refuses a
        # request carrying no Origin/Referer evidence at all -- see
        # `test_operator_route_origin_guard.py`, which owns that behaviour
        # -- so a request proving legitimate AUTH, the concern this test is
        # actually about, needs a same-origin Origin header to reach the
        # route at all.
        resp = client.get(
            '/api/%s/%s' % (self.API_KEY, self.ROUTE),
            params={'media_id': 'media-1'},
            headers={'origin': 'http://testserver'},
        )

        assert resp.status_code == 200, (
            'a request carrying the correct api_key was refused reaching '
            'the replacement preview route'
        )
        data = resp.json()
        assert data.get('success') is True

        destination = data.get('destination')
        assert destination.get('name') == 'The Thing.mkv'
        assert destination.get('quality') == '720p'
        assert destination.get('size') == len(OLD)

        candidates = {c['name']: c['size'] for c in data.get('candidates', [])}
        assert candidates.get('incoming.mkv') == len(NEW)

        assert str(self.watch) not in resp.text, (
            'the watch folder path leaked into the HTTP response'
        )
        assert str(self.lib) not in resp.text, (
            'the library folder path leaked into the HTTP response'
        )
