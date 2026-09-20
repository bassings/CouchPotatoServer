"""Guards SonarQube python:S5332 (clear-text HTTP) across `couchpotato/`.

Two different fixes apply here, and using the wrong one in the wrong place
recreates a real bug rather than clearing a lint finding:

  * Userscript `includes` patterns
    (`couchpotato/core/media/movie/providers/userscript/*.py`) move to the
    scheme-agnostic `*://` form nine sibling providers already use. This is
    NOT because it fixes a live Greasemonkey feature -- it does not. The
    userscript embed was retired in UI-CLEANUP-02
    (`specs/UI-CLEANUP-02-retire-userscript-embed.md`), which removed the
    only caller that ever turned `includes` into a `.user.js` `@include`/
    `@match` line; nothing generates one today. `couchpotato/core/event.py`
    records `userscript.get_includes` itself as "Dead by design... the
    userscript embed was retired... These [handlers] are the residue." The
    only LIVE consumer of `includes` is `belongsTo()`
    (`couchpotato/core/media/_base/providers/userscript/base.py`), which does
    a substring test of the URL's hostname against each pattern and never
    looks at the scheme at all. So `*://` is behaviour-neutral today: it
    matches the sibling providers' existing shape and removes the clear-text
    literal, nothing more. Per CLAUDE.md, assert only what the repo proves --
    an earlier version of this docstring claimed the change also fixed a
    broken "add to CouchPotato" button; that was wrong, and event.py is the
    evidence.
  * Everywhere else, the URL is one CouchPotato itself requests, writes into
    a file, or puts in a notification, and the fix is a straight
    `http://` -> `https://` scheme change. `fanarttv.py` is the sharpest
    example: by default that URL carries the SHIPPED PUBLIC application key
    (see the comment on `FanartTV.ak`), and only carries a user's own key if
    they configure one in Settings -- either way, that key crossed the wire
    in clear text before this fix.

A number of other `http://` literals are deliberate: torrent tracker
announce URLs that do not serve HTTPS, LAN endpoints and localhost defaults
for the user's own devices/services, a `requests` scheme-registration call,
an intentional proxy-hop scheme (see the comment in `http_client.py`
directly), and XML namespace identifiers. ALLOWLIST below is the single
place all of them are recorded, each with the reason it stays clear-text.

Design, and why it changed from a first version of this file that hand-
enumerated two separate lists (one of files-to-fix, one of files-to-allow):
a hand list only pins what someone remembered to write down. It missed three
real S5332 instances of the exact class it otherwise fixed (discord.py,
slack.py, itunes.py's settings description) precisely because nothing forced
completeness. This version instead SWEEPS every `.py` file under
`couchpotato/` for `http://` literals and asserts the swept set is EQUAL to
ALLOWLIST -- so an unlisted clear-text URL fails the moment it is written,
anywhere in the tree, not only in a file someone thought to add to a list.

Identity is (file, literal value), not (file, line number, value): line
numbers drift as unrelated code around them changes, which would make the
allow-list brittle for no security benefit. Where the same literal value
recurs at more than one call site in the same file for the same underlying
reason (e.g. `http_client.py`'s bare `'http://'` used both to register the
request-session scheme handler and to build the deliberately-http proxy
URL), one entry's reason covers all of them; that is stated inline wherever
it applies.

Two known limits of the sweep, both stated rather than hidden:

  * It only walks `couchpotato/`, not `tests/`, `libs/`, or `scripts/` --
    those are not the provider/notification surface this guard exists for,
    and sweeping test fixtures would just be noise.
  * String-literal concatenation (`'http://' + HOST`) is folded when both
    sides are literal constants directly in the expression, so the swept
    LITERAL set cannot be defeated by that simple split. It does NOT resolve
    a `Name` reference to a constant defined elsewhere (e.g.
    `API_HOST = 'host'` then `'http://' + API_HOST`) -- that is a materially
    harder, whole-module dataflow problem, and this sweep does not attempt
    it. Measured directly (mutate `fanarttv.py` to exactly that shape, see
    this change's commit message): the sweep still fails in that case, but
    only because `ast.walk` visits the bare `'http://'` Constant as its own
    node regardless of what it is concatenated with, so it shows up as an
    unlisted (file, `'http://'`) pair -- a real catch, but a useless failure
    message, since it cannot say which host went clear-text. For the small
    set of URLs that are genuinely high-value (the ones fixed here that
    carry a value worth protecting, `fanarttv.py` most of all),
    FIXED_URL_ATTRIBUTES below gives the precise version of that same
    failure by importing the module and reading the LIVE, already-resolved
    attribute value instead of the source text -- Python itself has already
    done any concatenation or Name resolution by the time the class body
    finishes executing, so no split or indirection can defeat it, and the
    failure message names the exact resolved URL.
    `test_sweep_folds_simple_split_literal_concatenation` proves the sweep's
    direct-literal folding against a synthetic fixture; the mutation proof
    for `FanartTV.urls['api']` in this change's commit message additionally
    proves both checks together against the real `NAME = 'host'` indirection
    shape a reviewer demonstrated defeats plain source scanning.
"""
import ast
import importlib
import pkgutil
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Part 1: userscript `includes` patterns must be scheme-agnostic.
# ---------------------------------------------------------------------------

USERSCRIPT_PACKAGE = "couchpotato.core.media.movie.providers.userscript"
USERSCRIPT_DIR = REPO_ROOT / "couchpotato/core/media/movie/providers/userscript"

# A file quietly vanishing from this directory (renamed, moved, `mv`'d out by
# accident) would otherwise just parametrize fewer test cases -- pytest
# reports that as "42 passed" with nothing red. Pin the expected count so a
# missing provider fails loudly instead of disappearing.
EXPECTED_USERSCRIPT_PROVIDER_COUNT = 15


def _userscript_provider_classes():
    """Import every provider module under userscript/ and return its Provider class.

    Imports and reads the live `includes` class attribute rather than
    regexing the source file: a source regex passes for the wrong reason the
    moment a provider builds its includes list dynamically, because at that
    point the literal string 'http://' may never appear in the file at all
    while the resulting pattern still does the wrong thing at runtime.
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
    return providers


USERSCRIPT_PROVIDERS = _userscript_provider_classes()


def test_userscript_provider_count_is_not_silently_reduced():
    """A vanished provider module must fail loudly, not just parametrize less.

    Proven: `mv criticker.py /tmp` previously produced "42 passed" instead of
    a failure, because pytest simply ran one fewer parametrized case.
    """
    names = sorted(name for name, _ in USERSCRIPT_PROVIDERS)
    assert len(USERSCRIPT_PROVIDERS) == EXPECTED_USERSCRIPT_PROVIDER_COUNT, (
        f"expected {EXPECTED_USERSCRIPT_PROVIDER_COUNT} userscript provider "
        f"modules under {USERSCRIPT_DIR}, found {len(USERSCRIPT_PROVIDERS)}: "
        f"{names}. If a provider was deliberately added or removed, update "
        f"EXPECTED_USERSCRIPT_PROVIDER_COUNT; if not, something vanished."
    )


@pytest.mark.parametrize(
    "module_name,provider_cls",
    USERSCRIPT_PROVIDERS,
    ids=[name for name, _ in USERSCRIPT_PROVIDERS],
)
def test_userscript_includes_are_scheme_agnostic(module_name, provider_cls):
    """Every userscript provider's `includes` patterns must use `*://`.

    Not `https://`: `belongsTo()` (the only live consumer, see module
    docstring) substring-matches the hostname and is scheme-blind, and
    `*://` is the form nine sibling providers already use.
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


# ---------------------------------------------------------------------------
# Part 2: the whole-tree sweep for clear-text http:// literals.
# ---------------------------------------------------------------------------

SWEEP_ROOT = REPO_ROOT / "couchpotato"


def _docstring_constant_ids(tree):
    """id() of every Constant node that IS a docstring (module/class/def).

    A docstring is prose or a doctest example, never a live request, and a
    raw `ast.Constant` walk cannot otherwise tell the two apart -- which is
    exactly how the previous version of this file's "still present" check
    could have been satisfied by commenting-out-equivalent prose. Excluded
    here so neither direction of the guard can be fooled by one.
    """
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _fold_string(node):
    """Best-effort constant-fold a string expression, or None if it cannot be.

    Handles a bare string literal and `+`-concatenation of two foldable
    sides (the exact shape `'http://' + 'host.example.com'`). Deliberately
    does NOT resolve `Name` references -- see the module docstring for why,
    and FIXED_URL_ATTRIBUTES for how the URLs that actually need that
    guarantee get it, via live import instead of source analysis.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _fold_string(node.left)
        right = _fold_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _clear_text_http_literals(tree, doc_ids):
    """Every folded string value in `tree` containing 'http://', minus docstrings."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) in doc_ids:
            continue
        value = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            value = _fold_string(node)
        if value and "http://" in value:
            found.add(value)
    return found


def _sweep():
    """Walk every .py file under couchpotato/, returning {(relpath, value)}."""
    found = set()
    files_scanned = 0
    for path in sorted(SWEEP_ROOT.rglob("*.py")):
        files_scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        doc_ids = _docstring_constant_ids(tree)
        relpath = str(path.relative_to(REPO_ROOT))
        for value in _clear_text_http_literals(tree, doc_ids):
            found.add((relpath, value))
    # A near-empty scan almost certainly means SWEEP_ROOT is wrong, not that
    # the codebase is small -- fail loudly rather than pass vacuously.
    assert files_scanned >= 200, (
        f"only scanned {files_scanned} .py files under {SWEEP_ROOT} -- "
        f"expected 200+; check SWEEP_ROOT is pointed at the right directory"
    )
    return found


# Every literal here is deliberate. Reasons cover ALL call sites in that file
# sharing the exact literal value (see module docstring on why identity is
# (file, value) rather than (file, line, value)).
ALLOWLIST = {
    # --- BitTorrent tracker announce URLs: not HTTP requests CouchPotato
    # --- makes to a service, but literal values baked into .torrent-style
    # --- announce lists. None of these answer on 443.
    (
        "couchpotato/core/_base/downloader/main.py",
        "http://tracker.istole.it/announce",
    ): "BitTorrent tracker announce URL; measured, does not answer on 443",
    (
        "couchpotato/core/_base/downloader/main.py",
        "http://tracker.publicbt.com/announce",
    ): "BitTorrent tracker announce URL; measured, does not answer on 443",
    (
        "couchpotato/core/_base/downloader/main.py",
        "http://tracker.ccc.de/announce",
    ): "BitTorrent tracker announce URL; measured, does not answer on 443",
    (
        "couchpotato/core/_base/downloader/main.py",
        "http://exodus.desync.com/announce",
    ): "BitTorrent tracker announce URL; measured, does not answer on 443",
    (
        "couchpotato/core/_base/downloader/main.py",
        "http://exodus.desync.com:6969/announce",
    ): "BitTorrent tracker announce URL; measured, does not answer on 443",
    (
        "couchpotato/core/_base/downloader/main.py",
        "http://tracker.publichd.eu/announce",
    ): "BitTorrent tracker announce URL; no longer resolves at all",
    (
        "couchpotato/core/_base/downloader/main.py",
        "http://tracker.openbittorrent.com/announce",
    ): "BitTorrent tracker announce URL; no longer resolves at all",

    # --- LAN endpoints for the user's OWN devices/services: not a third
    # --- party, so there is nothing here for TLS to protect against an
    # --- on-path attacker that a local network doesn't already expose.
    (
        "couchpotato/core/notifications/plex/client.py",
        "http://%s:%s/xbmcCmds/xbmcHttp/?%s",
    ): "LAN endpoint for the user's own Plex/XBMC host, not a third party",
    (
        "couchpotato/core/notifications/plex/client.py",
        "http://%s:%s/jsonrpc",
    ): "LAN endpoint for the user's own Plex/XBMC host, not a third party",
    (
        "couchpotato/core/notifications/xbmc.py",
        "http://%s/xbmcCmds/",
    ): "LAN endpoint for the user's own XBMC host, not a third party",
    (
        "couchpotato/core/notifications/xbmc.py",
        "http://%s/jsonrpc",
    ): "LAN endpoint for the user's own XBMC host, not a third party",
    (
        "couchpotato/core/downloaders/utorrent.py",
        "http://",
    ): "self.url = 'http://' + str(host) + ... : LAN endpoint for the "
       "user's own uTorrent host, not a third party",
    (
        "couchpotato/core/downloaders/qbittorrent_.py",
        "http://localhost:8080/",
    ): "default value for the user's own qBittorrent host; loopback, not a "
       "third party",
    (
        "couchpotato/core/downloaders/qbittorrent_.py",
        "RPC Communication URI. Usually <strong>http://localhost:8080/</strong>",
    ): "settings description text quoting the same loopback default above",
    (
        "couchpotato/core/downloaders/transmission.py",
        "http://localhost",
    ): "TransmissionRPC.__init__ default host; loopback, not a third party",
    (
        "couchpotato/core/downloaders/transmission.py",
        "http://localhost:9091",
    ): "default value for the user's own Transmission host; loopback, not a "
       "third party",
    (
        "couchpotato/core/downloaders/transmission.py",
        "Hostname with port. Usually <strong>http://localhost:9091</strong>",
    ): "settings description text quoting the same loopback default above",
    (
        "couchpotato/core/media/_base/providers/torrent/torrentpotato.py",
        "Base URL of your Jackett instance (e.g., http://localhost:9117)",
    ): "example text for the user's own, self-hosted Jackett instance; "
       "loopback, not a third party",
    (
        "couchpotato/simple_healthcheck.py",
        "http://localhost:5050",
    ): "default base URL for probing this application's OWN local instance, "
       "not a third party",

    # --- put.io callback URL: genuinely internet-facing (H2/2026-09-21 fix
    # --- round -- an EARLIER version of this entry called this "LAN callback
    # --- host", which the code three lines above the literal directly
    # --- contradicts ("Note callback_host is NOT our address, it's the
    # --- internet host that putio can call too"). The callback URL is built
    # --- as pre + callback_host + api_base, and runner.py's
    # --- `api_base = r'%sapi/%s/' % (web_base, api_key)` means it embeds this
    # --- CouchPotato instance's own API key. That key crosses the public
    # --- internet in clear text UNLESS the user ticks the "https" checkbox
    # --- for this downloader (self.conf('https')), which is off by default.
    # --- NOT fixed here: pre-existing, needs its own design (defaulting to
    # --- https requires knowing the callback host actually serves it, which
    # --- this code cannot verify), tracked separately from this S5332 pass.
    # --- Also unfixed, noted for whoever picks this up: the line reads
    # --- `Env.get('api_base'.strip('/'))` -- `.strip('/')` is called on the
    # --- LITERAL STRING `'api_base'` (which has no leading/trailing slash to
    # --- strip, so this is a no-op), not on the VALUE `Env.get('api_base')`
    # --- returns. Almost certainly meant to be `Env.get('api_base').strip('/')`.
    (
        "couchpotato/core/downloaders/putio/main.py",
        "http://",
    ): "pre = 'http://': callback URL handed to put.io's servers over the "
       "public internet, carrying this instance's own API key in clear "
       "text unless the user enables the https option. Pre-existing "
       "exposure, not fixed in this change -- see comment above this entry",

    # --- requests scheme registration and the deliberate proxy-hop scheme:
    # --- both explained in http_client.py itself at the literal's call site.
    (
        "couchpotato/core/http_client.py",
        "http://",
    ): "two call sites share this literal: session.mount('http://', adapter) "
       "is a scheme-registration call, not a URL (both schemes must be "
       "mounted for outgoing requests of either kind to work); and "
       "_get_proxy_config's proxy dict, which deliberately uses http:// for "
       "BOTH the 'http' and 'https' proxy keys because that is the scheme of "
       "the hop to the PROXY itself, not to the eventual target -- see the "
       "comment directly above that return statement",

    # --- generic host-string handling: not a URL to any specific service.
    (
        "couchpotato/core/helpers/variable.py",
        "http://",
    ): "two call sites share this literal: the loop that strips either "
       "scheme prefix off an arbitrary caller-supplied host, and "
       "cleanHost()'s ternary that prefixes a scheme onto an arbitrary host "
       "when building one (https when ssl=True, http otherwise) -- neither "
       "is a URL CouchPotato requests",

    # --- XML namespace identifiers: opaque strings that must match the feed
    # --- exactly. Changing either breaks feed parsing outright.
    (
        "couchpotato/core/media/movie/providers/automation/itunes.py",
        "http://www.w3.org/2005/Atom",
    ): "XML namespace URI (the Atom namespace), not a URL -- must match the "
       "feed's own namespace declaration exactly or parsing breaks",
    (
        "couchpotato/core/media/movie/providers/automation/itunes.py",
        "http://itunes.apple.com/rss",
    ): "XML namespace URI, not a URL -- must match the feed's own namespace "
       "declaration exactly or parsing breaks. Scoped to this literal only: "
       "line 71 of this same file was a genuine S5332 instance (an <a href> "
       "settings-description link to the same host) and has been fixed to "
       "https://, so this entry does not cover the whole file",

    # --- measured this round (2026-09-21): does not answer on 443, unlike
    # --- its sibling torrent-provider settings-description links, which
    # --- were fixed.
    (
        "couchpotato/core/media/_base/providers/torrent/torrentbytes.py",
        '<a href="http://torrentbytes.net" target="_blank">TorrentBytes</a>',
    ): "settings description link; measured 2026-09-21, does not answer on "
       "443",
}


def test_no_unexpected_clear_text_http_urls():
    """The sweep's found set must not contain anything ALLOWLIST doesn't.

    This is the regression direction: a clear-text http:// URL reintroduced
    anywhere under couchpotato/, or a brand new one, fails here by name --
    it does not need to be remembered and added to a hand list first.
    """
    found = _sweep()
    unexpected = found - set(ALLOWLIST)
    assert not unexpected, (
        f"{len(unexpected)} clear-text http:// literal(s) found under "
        f"couchpotato/ with no ALLOWLIST entry (python:S5332): "
        f"{sorted(unexpected)}. Either fix the scheme to https://, or add a "
        f"reasoned entry to ALLOWLIST in tests/unit/test_clear_text_provider_urls.py"
    )


def test_allowlist_entries_are_not_stale():
    """Every ALLOWLIST entry must still be found by the sweep.

    This is the staleness direction: if the code changed shape (the literal
    was fixed anyway, refactored, or deleted) the entry is protecting
    nothing and must be removed or re-pinned, not left to silently bless an
    absence. Checked against the AST-derived sweep result, not raw source
    text -- a `pinned_line in text` substring check (the previous version of
    this file) is satisfied by a COMMENTED-OUT line, which is not "still
    present" in any sense that matters.
    """
    found = _sweep()
    stale = [key for key in ALLOWLIST if key not in found]
    assert not stale, (
        f"{len(stale)} ALLOWLIST entries are stale -- the pinned literal is "
        f"no longer found by the sweep, so either the clear-text URL was "
        f"already fixed (remove the entry) or the code changed shape "
        f"(re-pin it): "
        + "\n".join(f"  {relpath!r}, {value!r}: {ALLOWLIST[(relpath, value)]}"
                     for relpath, value in stale)
    )


def test_sweep_folds_simple_split_literal_concatenation():
    """Regression guard for the sweep mechanism itself, not for app code.

    A reviewer demonstrated that a plain per-Constant-node scan (this file's
    first version) is defeated by splitting a literal:
    `API_HOST = 'webservice.fanart.tv'` then
    `'http://' + API_HOST + '/v3/...'` passed 43/43 with the key going over
    plaintext. `_fold_string` closes the DIRECT two-literal form of that
    (`'http://' + 'host'`) without executing anything; this test proves it
    against a synthetic fixture, isolated from any real source file, so it
    stays a permanent check on the mechanism rather than a one-off manual
    mutation. The Name-indirection form (`API_HOST` as a separate constant)
    is NOT resolved here by design -- see the module docstring -- and is
    instead closed for the URLs that need it via FIXED_URL_ATTRIBUTES below,
    proven against the real `fanarttv.py` in this change's commit.
    """
    source = textwrap.dedent(
        """
        API_HOST = 'webservice.fanart.tv'

        class FakeProvider:
            urls = {
                'api': 'http://' + API_HOST + '/v3/movies/%s?api_key=%s'
            }
        """
    )
    tree = ast.parse(source, filename="<split-literal-fixture>")
    doc_ids = _docstring_constant_ids(tree)
    found = _clear_text_http_literals(tree, doc_ids)

    # The Name (API_HOST) is not resolved, so the fold only recovers the
    # literal prefix 'http://' concatenated with itself where BinOp sides are
    # both literals -- but the two-sided direct-literal case must still be
    # caught. Prove that with a fixture the fold CAN fully resolve.
    direct_source = textwrap.dedent(
        """
        class FakeProvider:
            urls = {
                'api': 'http://' + 'webservice.fanart.tv' + '/v3/movies/%s'
            }
        """
    )
    direct_tree = ast.parse(direct_source, filename="<direct-split-literal-fixture>")
    direct_found = _clear_text_http_literals(direct_tree, _docstring_constant_ids(direct_tree))
    assert any("webservice.fanart.tv" in value for value in direct_found), (
        f"the sweep's folder failed to catch a direct 'http://' + 'host' + "
        f"'...' split literal -- found {direct_found!r}"
    )


# ---------------------------------------------------------------------------
# Part 3: live-attribute checks for the highest-value promoted URLs.
#
# Importing the module and reading the resolved class/module attribute is
# immune to ANY source-level obfuscation -- split literals, Name
# indirection, string formatting via a class-level template -- because
# Python has already evaluated it by the time the class body finishes
# executing. Used here for the promoted URLs worth that stronger guarantee;
# see module docstring for which URLs this deliberately does not cover and
# why (inline literals inside method bodies, gated behind conditions, are
# not simple attributes to introspect without executing the method).
# ---------------------------------------------------------------------------

FIXED_URL_ATTRIBUTES = [
    (
        "bluray.rss_url",
        "couchpotato.core.media.movie.providers.automation.bluray",
        "Bluray",
        lambda cls: cls.rss_url,
    ),
    (
        "bluray.backlog_url",
        "couchpotato.core.media.movie.providers.automation.bluray",
        "Bluray",
        lambda cls: cls.backlog_url,
    ),
    (
        "bluray.display_url",
        "couchpotato.core.media.movie.providers.automation.bluray",
        "Bluray",
        lambda cls: cls.display_url,
    ),
    (
        "letterboxd.url",
        "couchpotato.core.media.movie.providers.automation.letterboxd",
        "Letterboxd",
        lambda cls: cls.url,
    ),
    (
        "hdtrailers.urls[api]",
        "couchpotato.core.media.movie.providers.trailer.hdtrailers",
        "HDTrailers",
        lambda cls: cls.urls["api"],
    ),
    (
        "hdtrailers.urls[backup]",
        "couchpotato.core.media.movie.providers.trailer.hdtrailers",
        "HDTrailers",
        lambda cls: cls.urls["backup"],
    ),
    (
        "fanarttv.urls[api]",
        "couchpotato.core.media.movie.providers.info.fanarttv",
        "FanartTV",
        lambda cls: cls.urls["api"],
    ),
]


@pytest.mark.parametrize(
    "case_id,module_path,class_name,accessor",
    FIXED_URL_ATTRIBUTES,
    ids=[case_id for case_id, *_ in FIXED_URL_ATTRIBUTES],
)
def test_promoted_url_attributes_are_https(case_id, module_path, class_name, accessor):
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    value = accessor(cls)
    assert value.startswith("https://"), (
        f"{case_id}: live attribute value {value!r} does not start with "
        f"https:// (python:S5332) -- this is checked by importing the "
        f"module and reading the resolved value, so no source-level split "
        f"or indirection can hide a reintroduced http:// here"
    )
