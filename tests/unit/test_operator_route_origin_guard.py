"""C1: the two operator routes FEAT-011 adds must refuse a demonstrably
cross-origin request, using the origin-checking helper that already exists
for this exact purpose (`couchpotato.__init__._cross_origin_post`,
`couchpotato/__init__.py:767-829`) rather than a second, independently
written check or a new CSRF-token scheme (AC-SIMP-11 forbids the latter).

Reproduces the review's own evidence, executed against a real app built by
`create_app` + `TestClient`, exactly as `TestTheRouteRequiresAuthentication`
in `test_operator_candidate_listing.py` already does for authentication:

    GET  /api/<key>/renamer.operator_replace?media_id=media-1&source=incoming.mkv
      -> 200, library file overwritten
    Same URL + Origin: https://evil.example
      -> 200, library file destroyed
    POST same URL + Origin: https://evil.example
      -> 200, handler invoked

`renamer.operator_replace` permanently deletes a media file with no undo;
`renamer.operator_candidates` lists the contents of the operator's download
folder to any caller who can reach it. The task names both as needing the
guard, so both get a refusal test AND a same-origin counterweight -- a guard
that refuses everything would make the refusal tests pass for the wrong
reason, which is exactly the shape `AGENTS.md` and `CLAUDE.md` warn against.

`_cross_origin_post` only refuses when `Origin` (or, failing that,
`Referer`) is PRESENT and disagrees with `Host`/`X-Forwarded-Host` -- a
request carrying neither is passed through, because refusing on absent
evidence risks locking an operator out from behind a proxy that strips the
header. That behaviour is already proven for the logout route in
`test_session_revocation.py`; this file only proves the SAME helper is now
consulted on these two routes as well.
"""
import hashlib
import os

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes

OLD = b'existing 720p copy' * 100
NEW = b'incoming 2160p copy' * 900

API_KEY = 'testkey-operator-origin-guard'


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def _join_operator_thread(plugin, timeout=5):
    """`operatorReplaceView` backgrounds the real work on a daemon thread
    kept at `self._operator_thread` purely so a test can join it
    deterministically (see `test_replacement_operator_execution.py`).
    A refused request may never set this attribute at all, hence the
    `getattr` default rather than a plain attribute access.
    """
    thread = getattr(plugin, '_operator_thread', None)
    if thread is not None:
        thread.join(timeout=timeout)


@pytest.fixture
def guarded_world(tmp_path, monkeypatch):
    """Both new destructive routes, registered under their PRODUCTION
    route names exactly as `Renamer.__init__` registers them, against a
    real app built by `create_app` -- so a passing test here is a passing
    test against the routes the running server actually serves, not a
    stand-in.

    Combines the `world` fixture from `test_replacement_operator_execution
    .py` (the replacement machinery: a real library file, a real watch
    folder, `fireEvent` faked just enough to let a replacement actually
    complete) with the `_registered_route` fixture from
    `test_operator_candidate_listing.py` (the route wiring, `Env`, and
    settings needed for `create_app` + `TestClient` to dispatch through the
    real `/api/{route:path}` handler).
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
        'conf': {
            'from': str(watch),
            'to': str(lib),
            'default_file_action': 'move',
            'cleanup': False,
        },
        'releases': {'media-1': [existing_release]},
        'added': [],
    }

    def _fire(event, *args, **kwargs):
        if event == 'release.for_media':
            media_id = args[0] if args else kwargs.get('media_id')
            return list(state['releases'].get(media_id, []))
        if event in ('release.update_status', 'release.detach_file'):
            return True
        if event == 'release.add':
            group = args[0] if args else kwargs.get('group')
            movie_files = list((group.get('files') or {}).get('movie') or [])
            new_release = {
                '_id': 'r-new-%d' % (len(state['added']) + 1),
                'status': 'done',
                'files': {'movie': movie_files},
                'copy_id': copy_id_for_sizes(
                    [os.path.getsize(p) for p in movie_files],
                ),
                'identity_source': group.get('identity_source'),
            }
            state['added'].append(new_release)
            media_id = (group.get('media') or {}).get('_id')
            state['releases'].setdefault(media_id, []).append(new_release)
            return True
        if event == 'quality.guess':
            return {'identifier': '2160p', 'is_3d': False}
        if event == 'media.get':
            return {'_id': 'media-1', 'identifier': 'tt-media-1'}
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
    Renamer.renaming_started = False
    Renamer._warned_dead_setting = True

    addApiView('renamer.operator_replace', plugin.operatorReplaceView)
    addApiView('renamer.operator_candidates', plugin.operatorCandidatesView)
    addApiView(
        'renamer.operator_replacement_preview',
        plugin.operatorReplacementPreviewView,
    )

    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set(
        'app_dir',
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__),
        ))),
    )
    Env.set('dev', False)

    settings_data = {
        'username': '', 'password': '', 'api_key': API_KEY,
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

    yield {
        'plugin': plugin, 'dst': str(dst), 'src': str(src),
        'lib': lib, 'watch': watch,
        'old_dst_sha': _sha(dst), 'new_src_sha': _sha(src),
    }

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


def _client():
    from fastapi.testclient import TestClient
    from couchpotato import create_app

    app = create_app(api_key=API_KEY, web_base='/')
    return TestClient(app, raise_server_exceptions=False)


class TestTheOperatorReplaceRouteRefusesCrossOrigin:
    """AC-SEC-9. The single most dangerous route this branch adds: it
    permanently deletes a media file with no undo. Every probe here mirrors
    the review's own executed reproduction.
    """

    ROUTE = '/api/%s/renamer.operator_replace' % API_KEY

    def test_cross_origin_get_is_refused_and_library_untouched(self, guarded_world):
        client = _client()
        plugin = guarded_world['plugin']

        resp = client.get(
            self.ROUTE,
            params={'media_id': 'media-1', 'source': 'incoming.mkv'},
            headers={'origin': 'https://evil.example'},
        )
        _join_operator_thread(plugin)

        assert resp.status_code in (400, 403), (
            'a cross-origin GET to the destructive replacement route was '
            'not refused: got status %r, body %r' % (
                resp.status_code, resp.text,
            )
        )
        assert _sha(guarded_world['dst']) == guarded_world['old_dst_sha'], (
            'the library file was overwritten by a request whose Origin '
            'header names a different site entirely'
        )

    def test_cross_origin_post_is_refused_and_library_untouched(self, guarded_world):
        client = _client()
        plugin = guarded_world['plugin']

        resp = client.post(
            self.ROUTE,
            data={'media_id': 'media-1', 'source': 'incoming.mkv'},
            headers={'origin': 'https://evil.example'},
        )
        _join_operator_thread(plugin)

        assert resp.status_code in (400, 403), (
            'a cross-origin POST to the destructive replacement route was '
            'not refused: got status %r, body %r' % (
                resp.status_code, resp.text,
            )
        )
        assert _sha(guarded_world['dst']) == guarded_world['old_dst_sha'], (
            'the library file was overwritten by a cross-origin POST'
        )

    def test_same_origin_post_still_replaces(self, guarded_world):
        """The counterweight: the guard must not simply refuse everything.
        A same-origin request (Origin matching the app's own Host, exactly
        as `test_session_revocation.py`'s
        `test_a_same_origin_post_still_signs_out` proves for logout) must
        still be able to complete the legitimate action.
        """
        client = _client()
        plugin = guarded_world['plugin']

        resp = client.post(
            self.ROUTE,
            data={'media_id': 'media-1', 'source': 'incoming.mkv'},
            headers={'origin': 'http://testserver'},
        )
        _join_operator_thread(plugin)

        assert resp.status_code == 200, (
            'a legitimate, same-origin replacement request was refused: '
            'got status %r, body %r' % (resp.status_code, resp.text)
        )
        assert _sha(guarded_world['dst']) == guarded_world['new_src_sha'], (
            'the same-origin request did not actually replace the library '
            'file -- the guard must not pass by refusing everything'
        )


class TestTheOperatorCandidatesRouteRefusesCrossOrigin:
    """AC-SEC-9, applied to the second route the task names: the listing
    of the operator's download folder. Less destructive than a replace, but
    still a filesystem-contents disclosure that any page the operator
    visits should not be able to trigger.
    """

    ROUTE = '/api/%s/renamer.operator_candidates' % API_KEY

    def test_cross_origin_get_is_refused(self, guarded_world):
        client = _client()

        resp = client.get(self.ROUTE, headers={'origin': 'https://evil.example'})

        assert resp.status_code in (400, 403), (
            'a cross-origin GET to the candidate-listing route was not '
            'refused: got status %r, body %r' % (
                resp.status_code, resp.text,
            )
        )
        assert 'incoming.mkv' not in resp.text, (
            'the watch folder listing leaked to a cross-origin caller'
        )

    def test_same_origin_get_still_succeeds(self, guarded_world):
        client = _client()

        resp = client.get(self.ROUTE, headers={'origin': 'http://testserver'})

        assert resp.status_code == 200, (
            'a legitimate, same-origin candidate listing request was '
            'refused: got status %r, body %r' % (resp.status_code, resp.text)
        )
        data = resp.json()
        assert data.get('success') is True
        assert 'incoming.mkv' in data.get('candidates', []), (
            'the guard must not pass by refusing everything'
        )


class TestTheOperatorRoutesRefuseWhenNoOriginEvidenceIsPresent:
    """T7d item 2, round two on C1. `_cross_origin_post` returns False --
    "not cross-origin" -- when a request carries NEITHER `Origin` nor
    `Referer`, and that is the right call for the logout POST it was
    written for (`test_session_revocation.py
    ::test_a_post_with_no_origin_header_still_signs_out` pins it and must
    keep passing). It is the wrong call here.

    The comment above `ORIGIN_CHECKED_API_ROUTES`
    (`couchpotato/__init__.py:832`) claims the check "applies unchanged"
    to these two GET-reachable routes. It does not: a cross-origin GET
    sends no `Origin` header at all -- only a `fetch`/XHR does, and only
    on a request that would trigger a CORS preflight these routes don't
    require -- and `Referer` is trivially suppressed by the attacking page
    with a single `<meta name="referrer" content="no-referrer">` tag. A
    plain `<img src="…renamer.operator_replace?...">` on a page the
    operator merely has open therefore reaches the destructive route
    carrying no origin evidence whatsoever, and the POST logout route's
    fail-open reasoning about proxies does not transfer: a same-origin
    browser GET to these routes always has SOME Host to compare against
    once the client actually asks for the page, and there is no legitimate
    header-stripping-proxy story for an `<img>` tag that explains why
    absent evidence should mean "allow".

    Reproduces the review's own probe: a header-less GET returns 200 and
    the library file's hash changes.
    """

    REPLACE_ROUTE = '/api/%s/renamer.operator_replace' % API_KEY
    CANDIDATES_ROUTE = '/api/%s/renamer.operator_candidates' % API_KEY

    def test_a_header_less_get_to_operator_replace_is_refused_and_library_untouched(
        self, guarded_world,
    ):
        client = _client()
        plugin = guarded_world['plugin']

        resp = client.get(
            self.REPLACE_ROUTE,
            params={'media_id': 'media-1', 'source': 'incoming.mkv'},
        )
        _join_operator_thread(plugin)

        assert resp.status_code in (400, 403), (
            'a GET carrying neither Origin nor Referer reached the '
            'destructive replacement route: got status %r, body %r -- '
            'this is exactly what a same-site <img> tag with a '
            'no-referrer meta policy sends' % (resp.status_code, resp.text)
        )
        assert _sha(guarded_world['dst']) == guarded_world['old_dst_sha'], (
            'the library file was overwritten by a request carrying no '
            'origin evidence at all'
        )

    def test_a_header_less_get_to_operator_candidates_is_refused(
        self, guarded_world,
    ):
        client = _client()

        resp = client.get(self.CANDIDATES_ROUTE)

        assert resp.status_code in (400, 403), (
            'a GET carrying neither Origin nor Referer reached the '
            'candidate-listing route: got status %r, body %r' % (
                resp.status_code, resp.text,
            )
        )
        assert 'incoming.mkv' not in resp.text, (
            'the watch folder listing leaked to a request carrying no '
            'origin evidence at all'
        )


class TestTheOperatorReplacementPreviewRouteRefusesCrossOrigin:
    """T7d item 3, found independently by both reviewers.
    `renamer.operator_replacement_preview` (registered in this same delta,
    `main.py` around :185) discloses strictly MORE than
    `renamer.operator_candidates` -- which IS in
    `ORIGIN_CHECKED_API_ROUTES` -- yet was left out of the set: the
    destination file's basename, quality and byte size, plus the full
    candidate listing with each candidate's size. A route that is
    read-only is not therefore safe to leave open cross-origin; it is a
    filesystem-contents disclosure exactly like `operator_candidates`,
    only a strictly bigger one.
    """

    ROUTE = '/api/%s/renamer.operator_replacement_preview' % API_KEY

    def test_cross_origin_get_is_refused(self, guarded_world):
        client = _client()

        resp = client.get(
            self.ROUTE,
            params={'media_id': 'media-1'},
            headers={'origin': 'https://evil.example'},
        )

        assert resp.status_code in (400, 403), (
            'a cross-origin GET to the replacement-preview route was not '
            'refused: got status %r, body %r' % (
                resp.status_code, resp.text,
            )
        )
        assert 'incoming.mkv' not in resp.text, (
            'the preview -- destination name, quality, size and the full '
            'candidate listing -- leaked to a cross-origin caller'
        )

    def test_a_header_less_get_is_refused(self, guarded_world):
        client = _client()

        resp = client.get(self.ROUTE, params={'media_id': 'media-1'})

        assert resp.status_code in (400, 403), (
            'a GET carrying neither Origin nor Referer reached the '
            'replacement-preview route: got status %r, body %r' % (
                resp.status_code, resp.text,
            )
        )
        assert 'incoming.mkv' not in resp.text

    def test_same_origin_get_still_succeeds(self, guarded_world):
        client = _client()

        resp = client.get(
            self.ROUTE,
            params={'media_id': 'media-1'},
            headers={'origin': 'http://testserver'},
        )

        assert resp.status_code == 200, (
            'a legitimate, same-origin preview request was refused: got '
            'status %r, body %r' % (resp.status_code, resp.text)
        )
        data = resp.json()
        assert data.get('success') is True
        assert data.get('destination', {}).get('name') == 'The Thing.mkv', (
            'the guard must not pass by refusing everything'
        )


class TestEveryRegisteredOperatorRouteIsOriginChecked:
    """T7d item 3, the shape behind the finding: a hand-maintained
    `frozenset` of route-name strings (`ORIGIN_CHECKED_API_ROUTES`)
    silently omitted a route ONE COMMIT after it was written, and nothing
    in the suite noticed. This test reads the actual `addApiView(...)`
    calls out of the renamer plugin's source (not a second, independently
    maintained list of "routes that should be guarded" -- that would just
    be the same failure mode one level up) and fails the moment a new
    `renamer.operator_*` route is registered without being added to the
    set, whatever that route turns out to do.

    Deliberately scoped to `renamer.operator_*`: every route under that
    prefix has so far been either destructive or a filesystem-contents
    disclosure, which is the pattern the branch review is actually
    worried about, and widening this to every API route in the project
    would just make the test meaningless noise on unrelated routes with
    nothing to do with the operator-replacement feature.
    """

    def test_every_renamer_operator_route_appears_in_the_guarded_set(self):
        import inspect
        import re

        from couchpotato import ORIGIN_CHECKED_API_ROUTES
        from couchpotato.core.plugins.renamer import main as renamer_main

        source = inspect.getsource(renamer_main)
        registered = set(re.findall(
            r"addApiView\(\s*\n?\s*'(renamer\.operator_[a-zA-Z0-9_]+)'",
            source,
        ))

        assert registered, (
            'no renamer.operator_* addApiView(...) registrations were '
            'found by this regex -- either the plugin was refactored to '
            'register routes some other way (update the regex to match) '
            'or the fixture is broken, either of which must be fixed '
            'rather than leaving this test silently checking nothing'
        )

        missing = registered - ORIGIN_CHECKED_API_ROUTES
        assert not missing, (
            'the following renamer.operator_* routes are registered but '
            'not listed in ORIGIN_CHECKED_API_ROUTES, so a cross-origin '
            'caller reaches them with no Origin/Referer check at all: %r'
            % (sorted(missing),)
        )
