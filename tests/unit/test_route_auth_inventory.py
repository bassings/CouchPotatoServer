"""Every route is either authenticated or explicitly, deliberately public.

The spec calls this PR's highest-value single criterion, and `/getkey/` is why:
it exists because a route was once added without anyone having to state, at the
time, whether it needed auth. Fixing one endpoint fixes one endpoint. This
fixes the class, by making "public" something you have to write down in a list
a test reads.

**Read this before changing the walker.** FastAPI 0.140 does NOT flatten an
included router into `app.routes`. It leaves a single
`fastapi.routing._IncludedRouter` object there, whose routes live on
`.original_router.routes`. So a naive `for r in app.routes` sees 14 routes and
**zero** with `require_auth`, because every UI route is nested one level down --
and "zero routes are protected" reads like a catastrophic security finding
while being purely an artefact of the walk. That false alarm was produced twice
while writing this file. `test_the_inventory_actually_sees_the_application`
below exists to make it impossible to ship a third time.

Measured on the current tree: 80 APIRoutes, 33 distinct protected paths, 11
distinct public ones.
"""
import os

import pytest
from fastapi.routing import APIRoute

from couchpotato.environment import Env


#: Routes that MUST be reachable without a session, each with its reason.
#:
#: Adding an entry here is the point of the file: a small, deliberate,
#: reviewed act. Adding a route and never thinking about auth is not.
#: The inline reasons mirror `ORPHAN_ALLOWLIST` in
#: `scripts/check_test_traps.py` and `.gitleaksignore`'s comment requirement --
#: a bare path in a set tells the next reader nothing about whether it is
#: still meant to be there.
PUBLIC_ROUTES = {
    '/login': 'the login form itself; requiring a session to log in cannot work',
    '/login/': 'trailing-slash variant of the above',
    '/logout': 'must work from an expired or broken session, which is exactly when it is used',
    '/logout/': 'trailing-slash variant of the above',
    '/robots.txt': 'crawler directive, carries no data',
    '/api/{route:path}': 'authenticated by api_key inside callApiHandler, not by session. '
                         'A session dependency here would break every script and the userscript.',
    '/getkey': 'PRE-EXISTING, and slated for deletion later in this PR (AC-SEC-5). Listed so '
               'the inventory is honest about what ships today rather than passing by '
               'omission; this entry goes when the route does.',
    '/getkey/': 'trailing-slash variant of the above',
    '/old': 'legacy UI redirect; retirement tracked in specs/UI-MIGRATION.md',
    '/old/': 'trailing-slash variant of the above',
    '/old/{route:path}': 'legacy UI catch-all; see above',
}


@pytest.fixture
def app(tmp_path):
    """The real application, built the way the other web tests build it."""
    Env.set('app_dir', os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    Env.set('data_dir', str(tmp_path))
    Env.set('web_base', '/')
    Env.set('api_base', '/api/testkey123/')
    Env.set('static_path', '/static/')
    Env.set('dev', False)

    from couchpotato import create_app
    return create_app('testkey123', '/')


def _walk(routes):
    """Every APIRoute reachable from `routes`, descending into included routers.

    `_IncludedRouter` (FastAPI >= 0.140) is the case that matters: it is a
    single entry in `app.routes` standing in for a whole router, and its
    routes hang off `.original_router`. Miss it and this file measures 14
    routes instead of 80, all of them apparently unauthenticated.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        original = getattr(route, 'original_router', None)
        if original is not None:
            yield from _walk(getattr(original, 'routes', []) or [])
        elif getattr(route, 'routes', None):
            yield from _walk(route.routes)


#: Non-APIRoute entries that are allowed to exist, with the reason each is safe.
#:
#: `_walk` only yields APIRoute, so anything else -- a Mount, a WebSocket, a
#: plain starlette Route, a sub-application -- was structurally INVISIBLE to
#: every assertion in this file. That is not a theoretical hole: FastAPI mounts
#: `/openapi.json` as a plain `Route`, and it was served 200 to an
#: unauthenticated caller on an instance where `/wanted/` 302'd to the login
#: page, while this file passed green. The spec calls this test the PR's
#: highest-value criterion because it "fixes the class"; a filter that can only
#: see one route class does not.
NON_API_ROUTES = {
    '/static': 'StaticFiles mount: the UI assets, no data and no user content. '
               'Served before auth deliberately -- the login page needs its CSS.',
}


def _walk_all(routes):
    """EVERY route reachable from `routes`, whatever its class.

    Deliberately not filtered to APIRoute: the point is to see the ones the
    other walk cannot.
    """
    for route in routes:
        original = getattr(route, 'original_router', None)
        if original is not None:
            yield from _walk_all(getattr(original, 'routes', []) or [])
            continue
        yield route
        if getattr(route, 'routes', None):
            yield from _walk_all(route.routes)


def test_every_non_apiroute_is_accounted_for(app):
    """Close the class, not the instance.

    `/openapi.json` is now disabled at source (`openapi_url=None` in
    `create_app`), so the fix for the reported instance is not here. This is
    the guard that makes the NEXT one visible: add a Mount, a WebSocket or a
    sub-application and it must be justified in NON_API_ROUTES rather than
    shipping public and green.
    """
    from fastapi.routing import APIRoute as _APIRoute

    strays = sorted({
        '%s  (%s)' % (getattr(r, 'path', '?'), type(r).__name__)
        for r in _walk_all(app.routes)
        if not isinstance(r, _APIRoute)
        and getattr(r, 'path', None) not in NON_API_ROUTES
    })

    assert not strays, (
        'routes that are not APIRoute and not in NON_API_ROUTES:\n  %s\n\n'
        'Every assertion in this file filters on `isinstance(route, APIRoute)`, '
        'so these are invisible to all of them -- they can be wide open while '
        'the file passes. Either remove the route, protect it, or add it to '
        'NON_API_ROUTES with the reason it is safe.' % '\n  '.join(strays)
    )


def test_the_openapi_schema_is_not_served(app):
    """The reported instance, pinned so it cannot come back.

    `docs_url=None, redoc_url=None` turns off the two doc UIs and leaves the
    SCHEMA they render still served. Measured before the fix: 200, 26,655
    bytes, all 77 paths, on an instance requiring a login for `/wanted/`.
    """
    paths = {getattr(r, 'path', None) for r in _walk_all(app.routes)}
    assert '/openapi.json' not in paths, (
        'the OpenAPI schema route is back. It hands an unauthenticated caller '
        'a complete machine-readable map of every endpoint; pass '
        'openapi_url=None to FastAPI() in create_app.'
    )
    assert app.openapi_url is None


def _dependency_names(route) -> set:
    dependant = getattr(route, 'dependant', None)
    return {
        getattr(d.call, '__name__', '')
        for d in (getattr(dependant, 'dependencies', []) or [])
        if getattr(d, 'call', None) is not None
    }


def test_the_inventory_actually_sees_the_application(app):
    """Guard the guard.

    Every assertion below is of the form "no route is unprotected", which an
    empty or half-walked app satisfies trivially. Two separate harness
    mistakes produced exactly that during development -- an `Env` too crude
    for `create_app` to finish, and a walker that did not descend into
    `_IncludedRouter`. Both reported zero protected routes.
    """
    routes = list(_walk(app.routes))
    assert len(routes) >= 60, (
        'only %d APIRoutes found. The walk is not reaching the included '
        'routers, so every assertion below would pass vacuously.' % len(routes)
    )

    paths = {r.path for r in routes}
    assert '/wanted/' in paths, (
        'the UI routes are not being walked, so this inventory is measuring an '
        'app nobody serves'
    )

    protected = {r.path for r in routes if 'require_auth' in _dependency_names(r)}
    assert len(protected) >= 20, (
        'only %d protected paths found; the dependency is not being read '
        'correctly' % len(protected)
    )


def test_every_route_is_authenticated_or_explicitly_public(app):
    unlisted = sorted({
        r.path for r in _walk(app.routes)
        if 'require_auth' not in _dependency_names(r) and r.path not in PUBLIC_ROUTES
    })

    assert not unlisted, (
        'these routes require no session and are not in PUBLIC_ROUTES:\n  %s\n\n'
        'Either add the auth dependency, or add the path to PUBLIC_ROUTES WITH '
        'the reason it is safe. `/getkey/` exists because that decision was '
        'never written down anywhere.' % '\n  '.join(unlisted)
    )


def test_the_allowlist_has_no_entries_for_routes_that_no_longer_exist(app):
    """A stale entry silently pre-approves a future route that reuses the path."""
    live = {r.path for r in _walk(app.routes)}
    stale = sorted(p for p in PUBLIC_ROUTES if p not in live)

    assert not stale, (
        'PUBLIC_ROUTES names paths the app no longer serves: %s. Remove them, '
        'or a later route reusing one of these paths is public before anyone '
        'reviews it.' % stale
    )


def test_every_allowlist_entry_carries_a_reason():
    empty = sorted(p for p, reason in PUBLIC_ROUTES.items() if not reason.strip())
    assert not empty, 'PUBLIC_ROUTES entries with no stated reason: %s' % empty
