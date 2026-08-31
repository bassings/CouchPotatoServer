"""T8a: FEAT-011 (the operator replace path) ships OFF by default so this
branch can carry FEAT-010 (the review-gate) and FEAT-012 (renamer decision
memory) without shipping a reachable path that deletes a media file.

Owner decision, recorded here because it is the reason this file exists: the
operator replace path has reintroduced the same film-destroying defect three
times (see the module docstring on
`tests/unit/test_operator_route_does_not_forge_its_own_baseline.py`). Rather
than trust a fourth guard, the feature is turned off at the root: with
`operator_replace_enabled` at its default, `Renamer.__init__` must not
register the three operator API views AT ALL. Not refused, not 403'd --
simply absent from the routing table a running server builds.

Every operator test elsewhere in this tree (`test_operator_route_origin_
guard.py`, `test_operator_candidate_listing.py`, ...) registers the three
views BY HAND (`addApiView(plugin.operatorReplaceView, ...)`), specifically
to bypass whatever `Renamer.__init__` does. That makes them structurally
blind to a regression in the gating this file exists to pin, so every test
below calls the REAL `Renamer.__init__` -- the method under test -- and
drives it through `create_app()` + `TestClient`, exactly as the production
`Env`/loader path does.

Two routes are guarded, name-based, by `_cross_origin_guarded_route`
(`couchpotato/__init__.py`'s `ORIGIN_CHECKED_API_ROUTES`) BEFORE dispatch
ever reaches the `api` registry, regardless of whether the name is
registered -- a request carrying neither `Origin` nor `Referer` is refused
there on principle. Every request below carries a same-origin `Origin`
header (`http://testserver`, matching `TestClient`'s default `Host`) so it
passes that unrelated guard and reaches the real question: does an
unregistered route name reach the replacement code, or not.
"""
import hashlib
import os
import threading

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes

OLD = b'existing 720p library copy' * 100
NEW = b'incoming 2160p replacement copy' * 900

API_KEY = 'testkey-operator-feature-flag'
SAME_ORIGIN_HEADERS = {'origin': 'http://testserver'}


def _sha(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _join_operator_thread(plugin, timeout=5):
    """`operatorReplaceView` backgrounds the real work on a daemon thread
    kept at `self._operator_thread` purely so a test can join it
    deterministically. A refused/unregistered request may never set this
    attribute at all, hence the `getattr` default.
    """
    thread = getattr(plugin, '_operator_thread', None)
    if thread is not None:
        thread.join(timeout=timeout)


@pytest.fixture
def flagged_world(tmp_path, monkeypatch, request):
    """The same replacement machinery as `test_operator_route_origin_guard
    .py`'s `guarded_world`, but registers the three operator routes by
    calling the REAL `Renamer.__init__` rather than hand-registering them --
    so a passing test here is a passing test against server startup.

    `request.param` sets `operator_replace_enabled` in the faked config;
    tests that do not indirectly parametrise get whatever `Renamer.__init__`
    itself defaults `self.conf('operator_replace_enabled', ...)` to when the
    key is absent, i.e. the feature's actual shipped default, not a value
    this fixture asserts on its own authority.
    """
    from couchpotato.api import (
        api, api_locks, api_nonblock, api_docs, api_docs_missing,
    )
    from couchpotato.core.event import events
    from couchpotato.environment import Env

    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    old_events = {name: list(handlers) for name, handlers in events.items()}

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

    conf_values = {
        'from': str(watch),
        'to': str(lib),
        'default_file_action': 'move',
        'cleanup': False,
    }
    # Only set the key when this test indirectly parametrised a value --
    # leaving it absent for the default-off tests is deliberate: those
    # tests must pass because of what `Renamer.__init__` itself defaults
    # to, not because this fixture pre-decided the answer.
    if hasattr(request, 'param'):
        conf_values['operator_replace_enabled'] = request.param

    state = {
        'conf': conf_values,
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

    # The method under test: production's ACTUAL registration path.
    Renamer.__init__(plugin)

    # T7f: a replacement is only ever approved against a baseline recorded
    # when the operator opened the picker -- establish that here, exactly
    # as `test_operator_route_origin_guard.py`'s `guarded_world` does, so
    # the enabled-path tests below exercise a real replacement rather than
    # being refused by the (unrelated, and untouched) decision-time size
    # guard. This is plugin-internal state, not an HTTP call, so it
    # discloses nothing to the disabled-path tests that share this fixture.
    plugin._listOperatorCandidatesWithReason()

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
    events.clear()
    events.update(old_events)


def _client():
    from fastapi.testclient import TestClient
    from couchpotato import create_app

    app = create_app(api_key=API_KEY, web_base='/')
    return TestClient(app, raise_server_exceptions=False)


class TestOperatorReplaceIsUnreachableAtTheDefaultSetting:
    """The single most dangerous route this branch carries: it permanently
    deletes a media file with no undo. Proven the strong way: real files on
    disk, a real request through the real dispatcher, sha256 before and
    after -- a status code alone cannot tell a refusal apart from a swap
    that happened anyway.
    """

    ROUTE = '/api/%s/renamer.operator_replace' % API_KEY

    def test_default_setting_leaves_the_route_unregistered_and_library_untouched(
        self, flagged_world,
    ):
        plugin = flagged_world['plugin']
        client = _client()

        resp = client.post(
            self.ROUTE,
            data={'media_id': 'media-1', 'source': 'incoming.mkv'},
            headers=SAME_ORIGIN_HEADERS,
        )
        _join_operator_thread(plugin)

        # Whatever the real dispatcher actually does for a route name that
        # was never registered -- `callApiHandler` (couchpotato/api.py)
        # answers with 200 and {'success': False, 'error': "API call
        # doesn't exist"}, because the whole /api/{route:path} surface is
        # ONE FastAPI route that dispatches by name internally, so there is
        # no separate 404 to check for a missing API view. Assert what it
        # actually says, not an assumed status code.
        assert resp.status_code == 200, (
            'unexpected status for an unregistered route: %r, body %r'
            % (resp.status_code, resp.text)
        )
        body = resp.json()
        assert body.get('success') is False, (
            'an unregistered renamer.operator_replace answered success, '
            'body %r' % body
        )
        assert "doesn't exist" in (body.get('error') or ''), (
            'expected callApiHandler\'s "API call doesn\'t exist" answer '
            'for an unregistered route, got %r' % body
        )

        assert _sha(flagged_world['dst']) == flagged_world['old_dst_sha'], (
            'the library file changed even though operator_replace_enabled '
            'is at its default and the route should never have been '
            'reachable'
        )
        assert os.path.getsize(flagged_world['dst']) == len(OLD)

    def test_default_setting_leaves_the_route_unregistered_via_get_too(
        self, flagged_world,
    ):
        """The old route wiring accepted GET as well as POST -- confirm the
        same absence holds for a GET, not only the POST above.
        """
        plugin = flagged_world['plugin']
        client = _client()

        resp = client.get(
            self.ROUTE,
            params={'media_id': 'media-1', 'source': 'incoming.mkv'},
            headers=SAME_ORIGIN_HEADERS,
        )
        _join_operator_thread(plugin)

        assert resp.status_code == 200
        assert resp.json().get('success') is False
        assert _sha(flagged_world['dst']) == flagged_world['old_dst_sha']


class TestOperatorCandidatesIsUnreachableAtTheDefaultSetting:
    """Less destructive than replace, but still a filesystem-contents
    disclosure: the watch folder's file names must not leak through an
    unregistered route either.
    """

    ROUTE = '/api/%s/renamer.operator_candidates' % API_KEY

    def test_default_setting_leaves_the_route_unregistered_and_discloses_nothing(
        self, flagged_world,
    ):
        client = _client()

        resp = client.get(self.ROUTE, headers=SAME_ORIGIN_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body.get('success') is False
        assert "doesn't exist" in (body.get('error') or '')
        assert 'candidates' not in body
        assert 'incoming.mkv' not in resp.text, (
            'the watch folder listing leaked through an unregistered route'
        )


class TestOperatorReplacementPreviewIsUnreachableAtTheDefaultSetting:
    """Discloses strictly more than `operator_candidates` (destination
    name/quality/size plus every candidate's own size) -- same requirement.
    """

    ROUTE = '/api/%s/renamer.operator_replacement_preview' % API_KEY

    def test_default_setting_leaves_the_route_unregistered_and_discloses_nothing(
        self, flagged_world,
    ):
        client = _client()

        resp = client.get(
            self.ROUTE, params={'media_id': 'media-1'},
            headers=SAME_ORIGIN_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body.get('success') is False
        assert "doesn't exist" in (body.get('error') or '')
        assert 'destination' not in body
        assert 'candidates' not in body
        assert 'incoming.mkv' not in resp.text
        assert 'The Thing.mkv' not in resp.text


class TestOperatorReplaceStillWorksEndToEndWhenExplicitlyEnabled:
    """The counterweight the task itself calls for: 'off by default' must
    not be satisfiable by breaking the feature outright. With
    `operator_replace_enabled` explicitly True, `Renamer.__init__` must
    register all three routes and a same-origin replacement must still
    complete exactly as it does today.
    """

    @pytest.mark.parametrize('flagged_world', [True], indirect=True)
    def test_enabled_setting_registers_the_routes_and_replacement_still_completes(
        self, flagged_world,
    ):
        plugin = flagged_world['plugin']
        client = _client()

        resp = client.post(
            '/api/%s/renamer.operator_replace' % API_KEY,
            data={'media_id': 'media-1', 'source': 'incoming.mkv'},
            headers=SAME_ORIGIN_HEADERS,
        )
        _join_operator_thread(plugin)

        assert resp.status_code == 200
        assert resp.json().get('success') is True, (
            'enabling the setting must not itself break the route: got %r'
            % resp.text
        )
        assert _sha(flagged_world['dst']) == flagged_world['new_src_sha'], (
            'with the setting explicitly enabled the replacement must '
            'still actually happen -- "off by default" must not be '
            'satisfiable by breaking the feature outright'
        )

    @pytest.mark.parametrize('flagged_world', [True], indirect=True)
    def test_enabled_setting_registers_the_candidates_route(self, flagged_world):
        client = _client()

        resp = client.get(
            '/api/%s/renamer.operator_candidates' % API_KEY,
            headers=SAME_ORIGIN_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body.get('success') is True
        assert 'incoming.mkv' in body.get('candidates', [])

    @pytest.mark.parametrize('flagged_world', [True], indirect=True)
    def test_enabled_setting_registers_the_preview_route(self, flagged_world):
        client = _client()

        resp = client.get(
            '/api/%s/renamer.operator_replacement_preview' % API_KEY,
            params={'media_id': 'media-1'},
            headers=SAME_ORIGIN_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body.get('success') is True
        assert body.get('destination', {}).get('name') == 'The Thing.mkv'


class TestTheShippedSettingsDefaultIsAlsoOff:
    """The other default, and the one a real installation actually reads.

    There are TWO defaults for this setting and only one of them was
    pinned. `Renamer.__init__` falls back to False when the key is absent
    from config, and the tests above prove that: mutating it to True fails
    four of them. But the settings SCHEMA in
    `couchpotato/core/plugins/renamer/api.py` carries its own `'default'`,
    and that is the value a fresh install writes into its config file and
    the value the settings page presents. Flipping the schema default to
    True left every test in this file passing, which means the claim this
    feature ships off could be broken by a one-word edit that nothing
    caught.

    Pinned here because "ships disabled" is a promise about what an
    operator's server does after an upgrade, not about a code path's
    fallback. The feature deletes a library file with no undo, and it is
    held back precisely because that path reintroduced the same data-loss
    defect three times, so the value that decides whether it is live on a
    real machine gets a test of its own.
    """

    def test_the_schema_default_is_false(self):
        from couchpotato.core.plugins.renamer.api import config

        found = [
            option
            for section in config
            for group in section.get('groups', [])
            for option in group.get('options', [])
            if option.get('name') == 'operator_replace_enabled'
        ]

        assert len(found) == 1, (
            'expected exactly one operator_replace_enabled option in the '
            'renamer settings schema, found %d. If it moved or was '
            'duplicated, this guard stops describing reality' % len(found)
        )
        assert found[0].get('default') is False, (
            'the shipped settings default for operator_replace_enabled is '
            '%r, not False. A fresh install writes this value into its '
            'config, so this is what decides whether an operator-triggered, '
            'irreversible library deletion is reachable on a real server'
            % (found[0].get('default'),)
        )
