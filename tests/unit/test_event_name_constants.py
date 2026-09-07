"""Guard for SONAR-S1192 (T5): the 24 duplicated event-name string literals
must be replaced with named constants at every `addEvent()` / `fireEvent()` /
`fireEventAsync()` call site.

Event wiring in this codebase fails silently in both directions: a mistyped
name in `addEvent()` registers a listener nothing ever calls, and a mistyped
name in `fireEvent()`/`fireEventAsync()` calls nothing. Neither raises. That
has already cost this project twice -- `renamer.before`/`renamer.after` are
never fired (subtitles, trailers, notifications and metadata are silently
dead), and `app.test` has four registered listeners and zero fire sites
anywhere in the repository. A bare string literal at the call site cannot be
checked by anything short of grepping the tree by hand; a named constant
turns a typo into an immediate `NameError`/`ImportError`/`AttributeError` at
import time.

This test does not assert a constant's value equals the literal it replaces
-- that would restate the constant and could not fail for any reason worth
catching. It scans the actual call sites instead, so it is RED for as long
as any of them still spells the event name out by hand, and it stays RED if
someone reintroduces one after the fix lands.

See specs/SPEC-SONAR-S1192-event-name-constants.md.
"""

import ast
import pathlib

# Anchored to this file, not the CWD -- tests/unit/test_x.py -> repo root ->
# couchpotato. A relative path silently yields an empty file list when pytest
# runs from somewhere other than the repo root, and the assertion below would
# then pass on zero files scanned: a guard providing no coverage while
# reporting green is worse than no guard. Mirrors test_event_wiring.py.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / 'couchpotato'

# CouchPotato.py is outside SOURCE_ROOT and fires `app.shutdown` from its
# SIGINT handler, so scanning only `couchpotato/` let one real dispatch site
# escape this guard entirely.
ENTRY_POINT = REPO_ROOT / 'CouchPotato.py'

# The 21 event names SONAR-S1192 assigns named constants, exactly as they
# appear in the source today.
#
# The spec originally listed 24. Three were wrong, and the error is worth
# recording because of how it was made: the list was built by matching
# dotted-lowercase strings in the scanner output, never by checking how
# each string is USED. `couchpotato.db` is the SQLite filename passed to
# os.path.join(); `updater.check` and `release.manual_download` are
# addApiView() route names. None is dispatched as an event, so none
# belongs in a module called event_names, and a constant nobody imports
# is worse than no constant: it tells the next reader that
# `couchpotato.db` is an event.
EVENT_NAMES = frozenset({
    'app.load',
    'app.restart',
    'app.shutdown',
    'library.query',
    'library.related',
    'library.tree',
    'manage.update',
    'media.get',
    'media.restatus',
    'media.types',
    'media.with_status',
    'movie.update',
    'notify.frontend',
    'profile.default',
    'release.add',
    'release.for_media',
    'release.update_status',
    'release.with_status',
    'renamer.scan',
    'scanner.name_year',
    'searcher.protocols',
})

EVENT_CALL_NAMES = ('addEvent', 'fireEvent', 'fireEventAsync')


def _python_files():
    files = [p for p in SOURCE_ROOT.rglob('*.py') if 'lib/' not in str(p)]
    assert files, 'found no source files under %s' % SOURCE_ROOT
    if ENTRY_POINT.is_file():
        files.append(ENTRY_POINT)
    return files


def _call_name(node):
    """The bare function name of a Call node, however it was referenced
    (`fireEvent(...)` or `self.fireEvent(...)`)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _first_string_arg(node):
    if node.args and isinstance(node.args[0], ast.Constant) \
            and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def _find_literal_event_call_sites():
    """(path, lineno, literal) for every addEvent/fireEvent/fireEventAsync
    call whose first positional argument is still a bare string literal
    matching one of the 21 event names this task assigns a constant.

    Uses the AST rather than a text regex: a regex over source text matches
    its own documentation, so a comment mentioning `fireEvent('media.get')`
    would register as a real call site. Parsing sidesteps comments and
    strings-inside-strings entirely.
    """
    hits = []
    for path in _python_files():
        tree = ast.parse(path.read_text(errors='replace'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in EVENT_CALL_NAMES:
                continue
            literal = _first_string_arg(node)
            if literal in EVENT_NAMES:
                hits.append((str(path), node.lineno, literal))
    return hits


class TestEventNameConstantsReplaceLiterals:

    def test_constant_values_match_what_non_python_consumers_expect(self):
        """Pin every constant's value against a literal written out here.

        This looks circular, and for a constant used only from Python it would
        be: renaming both sides together is safe, so a value pin would restate
        the constant and could never fail for a reason worth catching. That
        argument does NOT hold for these names, and the difference is the whole
        point of this test.

        These strings cross out of Python, into places no Python rename will
        ever reach:

          - `addApiView('app.restart', ...)` and eight more route
            registrations, which build the HTTP API's URLs
          - HTML templates that fetch those URLs by hand, for example
            `couchpotato/ui/templates/partials/settings/scripts.html:579`
            (`/app.restart/`) and `couchpotato/ui/templates/wanted.html:41`
            (`/manage.update/?full=1`)
          - `callApiHandler('media.get', ...)` in `couchpotato/ui/__init__.py`
          - the legacy JS, which listens for `movie.update` and requests
            `renamer.scan`

        So a constant's VALUE is a published contract, not an implementation
        detail. Changing it renames the event on the Python side and leaves the
        template fetching a URL that no longer exists, with nothing raising.
        Measured before this test existed: retyping APP_SHUTDOWN, APP_RESTART
        and MANAGE_UPDATE left the entire unit suite green at 3895 passed.
        Only MOVIE_UPDATE and RENAMER_SCAN were pinned at all, and only by
        accident, through unrelated tests that happened to match on the name.
        """
        from couchpotato.core import event_names

        expected = {
            'APP_LOAD': 'app.load',
            'APP_RESTART': 'app.restart',
            'APP_SHUTDOWN': 'app.shutdown',
            'LIBRARY_QUERY': 'library.query',
            'LIBRARY_RELATED': 'library.related',
            'LIBRARY_TREE': 'library.tree',
            'MANAGE_UPDATE': 'manage.update',
            'MEDIA_GET': 'media.get',
            'MEDIA_RESTATUS': 'media.restatus',
            'MEDIA_TYPES': 'media.types',
            'MEDIA_WITH_STATUS': 'media.with_status',
            'MOVIE_UPDATE': 'movie.update',
            'NOTIFY_FRONTEND': 'notify.frontend',
            'PROFILE_DEFAULT': 'profile.default',
            'RELEASE_ADD': 'release.add',
            'RELEASE_FOR_MEDIA': 'release.for_media',
            'RELEASE_UPDATE_STATUS': 'release.update_status',
            'RELEASE_WITH_STATUS': 'release.with_status',
            'RENAMER_SCAN': 'renamer.scan',
            'SCANNER_NAME_YEAR': 'scanner.name_year',
            'SEARCHER_PROTOCOLS': 'searcher.protocols',
        }

        actual = {
            name: value for name, value in vars(event_names).items()
            if name.isupper() and isinstance(value, str)
        }

        assert actual == expected, (
            'An event-name constant no longer matches the string its '
            'non-Python consumers use. These values appear in addApiView() '
            'routes, HTML templates and legacy JS, none of which a Python '
            'rename updates, so changing one here silently breaks the URL '
            'the UI fetches. If the rename is deliberate, change every '
            'consumer and then this table.'
        )

    def test_no_bare_literal_at_event_call_sites(self):
        hits = _find_literal_event_call_sites()

        assert not hits, (
            'These addEvent()/fireEvent()/fireEventAsync() calls still pass '
            'a bare string literal for one of the 21 event names '
            'SONAR-S1192 assigns a named constant. A typo here fails '
            'silently in this codebase -- a mistyped addEvent() name '
            'registers a listener nothing calls, a mistyped fireEvent() '
            'name calls nothing, and neither raises -- so replace the '
            'literal with the constant, making a future typo a load-time '
            'NameError/ImportError/AttributeError instead:\n%s'
            % '\n'.join('  %s:%d  %r' % hit for hit in sorted(hits))
        )
