"""Guards SonarQube python:S5332 (clear-text HTTP) across CouchPotato's
third-party provider and notification code.

Two different fixes apply here, and using the wrong one in the wrong place
recreates a real bug rather than clearing a lint finding:

  * Userscript `includes` patterns
    (`couchpotato/core/media/movie/providers/userscript/*.py`) are
    Greasemonkey match patterns, not requests CouchPotato makes. They decide
    whether the "add to CouchPotato" button shows on the page a user is
    actually browsing. `belongsTo()`
    (`couchpotato/core/media/_base/providers/userscript/base.py`) does a
    substring test of the URL's hostname against each pattern, so pinning a
    pattern to `https://` would still work for the user's browser but is
    needlessly narrow, and the plain `http://`-only form already matches
    nothing once a site redirects everything to HTTPS -- a real broken
    feature, not just a finding. The fix is the scheme-agnostic `*://` form
    nine sibling providers already use, which matches either scheme.
  * Everywhere else, the URL is one CouchPotato itself requests, writes into
    a file, or puts in a notification. There the fix is a straight
    `http://` -> `https://` scheme change.

A handful of other `http://` URLs are deliberate -- torrent tracker announce
URLs that do not serve HTTPS, LAN endpoints for the user's own devices, a
`requests` scheme-registration call, an XML namespace identifier -- and are
recorded in DELIBERATE_CLEAR_TEXT_URLS below rather than fixed. That list
also guards against itself going stale: if the pinned line ever disappears
(the code changed shape, the URL was fixed anyway), its assertion fails
rather than silently protecting nothing.
"""
import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

USERSCRIPT_PACKAGE = "couchpotato.core.media.movie.providers.userscript"
USERSCRIPT_DIR = REPO_ROOT / "couchpotato/core/media/movie/providers/userscript"


def _userscript_provider_classes():
    """Import every provider module under userscript/ and return its Provider class.

    Imports and reads the live `includes` class attribute rather than
    regexing the source file: a source regex passes for the wrong reason the
    moment a provider builds its includes list dynamically (e.g. from a
    shared constant, or programmatically), because at that point the literal
    string 'http://' may never appear in the file at all while the resulting
    pattern still does the wrong thing at runtime.
    """
    providers = []
    for module_info in pkgutil.iter_modules([str(USERSCRIPT_DIR)]):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{USERSCRIPT_PACKAGE}.{module_info.name}")
        autoload = getattr(module, "autoload", None)
        assert autoload, (
            f"{module_info.name}.py has no module-level `autoload` -- cannot "
            f"find its provider class"
        )
        cls = getattr(module, autoload, None)
        assert cls is not None, (
            f"{module_info.name}.py: autoload names {autoload!r}, which is "
            f"not defined in the module"
        )
        providers.append((module_info.name, cls))
    assert providers, "no userscript provider modules were discovered -- check USERSCRIPT_DIR"
    return providers


USERSCRIPT_PROVIDERS = _userscript_provider_classes()


@pytest.mark.parametrize(
    "module_name,provider_cls",
    USERSCRIPT_PROVIDERS,
    ids=[name for name, _ in USERSCRIPT_PROVIDERS],
)
def test_userscript_includes_are_scheme_agnostic(module_name, provider_cls):
    """Every userscript provider's `includes` patterns must use `*://`.

    Not `https://`: these are Greasemonkey match patterns evaluated by the
    user's browser against whatever scheme the page it's actually on uses,
    not a URL CouchPotato fetches. `*://` matches both.
    """
    includes = provider_cls.includes
    assert includes, f"{module_name}.py: {provider_cls.__name__}.includes is empty"

    for pattern in includes:
        assert "http://" not in pattern and "https://" not in pattern, (
            f"{module_name}.py: includes pattern {pattern!r} is scheme-pinned "
            f"-- use the scheme-agnostic '*://' form instead (see imdb.py, "
            f"letterboxd.py, trakt.py and other siblings in the same "
            f"directory for the shape)"
        )


def _string_literals(path):
    """Every string literal in a module, as (lineno, value) pairs.

    AST-based, not a source regex: a URL quoted inside a comment or an
    unrelated docstring cannot masquerade as a fixed (or unfixed) literal,
    and this reads correctly regardless of whether the URL is a class
    attribute, a dict value, or a string built inline inside a method body
    ahead of `%`/`.format()` interpolation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


# Fix B: URLs CouchPotato itself requests, writes to a file, or emits in a
# notification. Each entry names the file and the third-party host whose
# literal must have moved from http:// to https://. fanarttv.py matters most
# among these: its URL carries the user's own `?api_key=` query parameter, so
# leaving it clear-text sends that key over the wire in plain text on every
# request.
FIXED_CLEAR_TEXT_URLS = [
    ("couchpotato/core/media/movie/providers/automation/bluray.py", "www.blu-ray.com"),
    ("couchpotato/core/media/movie/providers/automation/imdb.py", "www.imdb.com"),
    ("couchpotato/core/media/movie/providers/automation/letterboxd.py", "letterboxd.com"),
    ("couchpotato/core/media/movie/providers/trailer/hdtrailers.py", "www.hd-trailers.net"),
    ("couchpotato/core/media/movie/providers/metadata/xbmc.py", "www.imdb.com"),
    ("couchpotato/core/notifications/pushover.py", "www.imdb.com"),
    ("couchpotato/core/notifications/telegrambot.py", "www.imdb.com"),
    ("couchpotato/core/notifications/telegrambot.py", "telegram.me"),
    ("couchpotato/core/media/movie/providers/info/fanarttv.py", "webservice.fanart.tv"),
    ("couchpotato/core/media/movie/providers/userscript/youteather.py", "www.youtheater.com"),
]


@pytest.mark.parametrize(
    "relpath,host",
    FIXED_CLEAR_TEXT_URLS,
    ids=[f"{relpath}::{host}" for relpath, host in FIXED_CLEAR_TEXT_URLS],
)
def test_fixed_url_uses_https(relpath, host):
    path = REPO_ROOT / relpath
    literals = _string_literals(path)

    clear_text = [(lineno, value) for lineno, value in literals if f"http://{host}" in value]
    assert not clear_text, (
        f"{relpath}: clear-text http://{host} literal(s) remain (python:S5332): "
        f"{clear_text}"
    )

    # Not just "no http:// left" -- that would also pass if the literal were
    # deleted outright, which is not the fix. Require the https:// form to
    # actually be present, so the test cannot pass vacuously.
    secure = [(lineno, value) for lineno, value in literals if f"https://{host}" in value]
    assert secure, (
        f"{relpath}: no https://{host} literal found -- expected the "
        f"http:// literal to be promoted to https://, not removed"
    )


# Deliberate exceptions: SonarQube accepts these findings; they stay
# clear-text on purpose. Each entry pins the exact source line so the test
# fails the moment the exception goes stale -- the line changed shape, or
# the URL was fixed anyway -- rather than silently guarding nothing.
DELIBERATE_CLEAR_TEXT_URLS = [
    (
        "couchpotato/core/_base/downloader/main.py",
        "'http://tracker.istole.it/announce'",
        "BitTorrent tracker announce URL; measured, does not answer on 443",
    ),
    (
        "couchpotato/core/_base/downloader/main.py",
        "'http://tracker.publicbt.com/announce'",
        "BitTorrent tracker announce URL; measured, does not answer on 443",
    ),
    (
        "couchpotato/core/_base/downloader/main.py",
        "'http://tracker.ccc.de/announce'",
        "BitTorrent tracker announce URL; measured, does not answer on 443",
    ),
    (
        "couchpotato/core/_base/downloader/main.py",
        "'http://exodus.desync.com/announce'",
        "BitTorrent tracker announce URL; measured, does not answer on 443",
    ),
    (
        "couchpotato/core/_base/downloader/main.py",
        "'http://exodus.desync.com:6969/announce'",
        "BitTorrent tracker announce URL; measured, does not answer on 443",
    ),
    (
        "couchpotato/core/_base/downloader/main.py",
        "'http://tracker.publichd.eu/announce'",
        "BitTorrent tracker announce URL; no longer resolves at all",
    ),
    (
        "couchpotato/core/_base/downloader/main.py",
        "'http://tracker.openbittorrent.com/announce'",
        "BitTorrent tracker announce URL; no longer resolves at all",
    ),
    (
        "couchpotato/core/notifications/plex/client.py",
        "url = 'http://%s:%s/xbmcCmds/xbmcHttp/?%s' % (",
        "LAN endpoint for the user's own Plex/XBMC host, not a third party",
    ),
    (
        "couchpotato/core/notifications/plex/client.py",
        "url = 'http://%s:%s/jsonrpc' % (",
        "LAN endpoint for the user's own Plex/XBMC host, not a third party",
    ),
    (
        "couchpotato/core/notifications/xbmc.py",
        "server = 'http://%s/xbmcCmds/' % host",
        "LAN endpoint for the user's own XBMC host, not a third party",
    ),
    (
        "couchpotato/core/notifications/xbmc.py",
        "server = 'http://%s/jsonrpc' % host",
        "LAN endpoint for the user's own XBMC host, not a third party",
    ),
    (
        "couchpotato/core/downloaders/utorrent.py",
        "self.url = 'http://' + str(host) + ':' + str(port) + '/gui/'",
        "LAN endpoint for the user's own uTorrent host, not a third party",
    ),
    (
        "couchpotato/core/downloaders/putio/main.py",
        "pre = 'http://'",
        "LAN callback host; already conditionally upgrades to https:// when "
        "the user enables it (self.conf('https'))",
    ),
    (
        "couchpotato/core/http_client.py",
        "session.mount('http://', adapter)",
        "a requests scheme-registration call, not a URL -- both schemes must "
        "be mounted for outgoing requests of either kind to work",
    ),
    (
        "couchpotato/core/http_client.py",
        'return {"http": f"http://{loc}", "https": f"https://{loc}"}',
        "proxy config dict correctly offers both schemes; the local var name "
        "is `loc`, not a hard-coded third-party host",
    ),
    (
        "couchpotato/core/helpers/variable.py",
        "for prefix in ('https://', 'http://'):",
        "strips either scheme prefix off an arbitrary caller-supplied host; "
        "not a URL CouchPotato requests",
    ),
    (
        "couchpotato/core/helpers/variable.py",
        ">>> cleanHost(\"localhost:80\", ssl=False)\n    'http://localhost:80/'",
        "doctest example output for a local test host, not a real request",
    ),
    (
        "couchpotato/core/media/movie/providers/automation/itunes.py",
        "namespace_im = 'http://itunes.apple.com/rss'",
        "an XML namespace identifier, not a URL -- feed parsing breaks if "
        "this is changed, since XML namespace URIs are opaque strings that "
        "must match the feed exactly",
    ),
]


@pytest.mark.parametrize(
    "relpath,pinned_line,reason",
    DELIBERATE_CLEAR_TEXT_URLS,
    ids=[f"{relpath}::{i}" for i, (relpath, _, _) in enumerate(DELIBERATE_CLEAR_TEXT_URLS)],
)
def test_deliberate_clear_text_exception_is_not_stale(relpath, pinned_line, reason):
    assert reason, f"{relpath}: exception has no reason recorded"
    path = REPO_ROOT / relpath
    assert path.is_file(), (
        f"{relpath} no longer exists -- remove this stale allow-list entry "
        f"(reason on file: {reason})"
    )
    text = path.read_text(encoding="utf-8")
    assert pinned_line in text, (
        f"{relpath}: the pinned exception line {pinned_line!r} is no longer "
        f"present -- either the clear-text URL was already fixed (drop this "
        f"allow-list entry) or the code changed shape (re-pin it). Reason on "
        f"file: {reason}"
    )
