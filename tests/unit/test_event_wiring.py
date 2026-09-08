"""Guard against events that are fired but never handled.

`fireEvent()` returns `[]` when a name has no handlers. That is indistinguishable
from "handled, found nothing", so a mis-wired event does not fail — the feature
behind it just quietly does nothing, forever.

Two real instances of this were found in July 2026:

- `movie.info.release_date` (BUG-017) — fired to fetch release dates, never
  handled, so the ETA gate had no dates and downloaded everything regardless
  of release date. Undetected for the life of the fork.
- `scheduler.interval` in `plugins/manage.py` — a typo for `schedule.interval`,
  so that call scheduled nothing. Harmless only because `setCrons()` does the
  same job correctly a few lines later.

This module fails CI when a new one appears. `couchpotato.core.event.OPTIONAL_EVENTS`
is the single allowlist, shared with the runtime warning in `fireEvent()`.
"""

import ast
import pathlib
import re

import pytest

from couchpotato.core.event import (
    HANDLERS_REACHABLE_ANOTHER_WAY,
    OPTIONAL_EVENTS,
    UNFIRED_EVENTS,
)

# Anchored to this file, not the CWD. A relative path silently yields an empty
# file list when pytest is invoked from anywhere but the repo root, and every
# assertion below would then pass trivially -- a guard providing zero coverage
# while reporting green is worse than no guard.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / 'couchpotato'

# CouchPotato.py sits at the repo root, outside SOURCE_ROOT, and it both
# registers and fires events: its SIGINT handler is the only producer of
# `app.shutdown`, whose consumer runs the clean shutdown that drains plugins
# before the server dies. Scanning only `couchpotato/` left that dispatch
# invisible to this audit, so a rename on one side and not the other would
# have gone unnoticed.
ENTRY_POINT = REPO_ROOT / 'CouchPotato.py'


def _python_files():
    files = [p for p in SOURCE_ROOT.rglob('*.py') if 'lib/' not in str(p)]
    assert files, 'found no source files under %s' % SOURCE_ROOT
    assert ENTRY_POINT.is_file(), (
        'the entry point is missing from %s. Skipping it silently would stop '
        'this guard scanning the only dispatch site outside couchpotato/.'
        % ENTRY_POINT
    )
    files.append(ENTRY_POINT)
    return files


def _call_name(node):
    """The bare function name of a Call node, however it was referenced."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _event_name_constants():
    """Identifier to value for every constant in couchpotato/core/event_names.py.

    Resolving these is load-bearing, not a convenience. This audit reads event
    names out of the source, and originally understood only a bare string
    literal. When SONAR-S1192 replaced 21 literals with constants, all 21
    silently dropped out of both the fired and the handled set, taking the
    audit's coverage of the renamer and manage paths with them, and the suite
    stayed green while doing it. Proved by deleting a handler registration:
    before this function existed the audit passed, after it the audit fails.
    """
    module = SOURCE_ROOT / 'core' / 'event_names.py'
    # Assert rather than return an empty map. Returning {} would silently drop
    # this audit back to literals only, which is the exact zero-coverage-while-
    # green failure the header comment above warns about, and it would be
    # inconsistent with the `assert names` below: an EMPTY constants file would
    # fail loudly while a MISSING one passed quietly.
    assert module.is_file(), (
        'the event-name constants module is missing from %s. This audit '
        'resolves names through it, so without it every constant-ised event '
        'silently drops out of view and this guard reports green on no '
        'coverage.' % module
    )
    names = {}
    for node in ast.walk(ast.parse(module.read_text(errors='replace'))):
        # AnnAssign as well as Assign. Matching only Assign meant that adding a
        # type annotation, `SEARCHER_PROTOCOLS: str = '...'`, removed that name
        # from this map and re-blinded the audit for it, silently, one constant
        # per annotation. A routine typing pass would have done it and nothing
        # in the gate would have questioned the commit.
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names[target.id] = value.value
    assert names, 'found no event-name constants in %s' % module
    return names


def _first_string_arg(node, constants = None):
    """The event name of a call, whether written as a literal or a constant."""
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    if constants is not None and isinstance(first, ast.Name):
        return constants.get(first.id)
    return None


def _collect():
    """Return (fired, handled) names found by static inspection.

    Uses the AST rather than regexes: a regex over source text matches its own
    documentation, so a comment mentioning `fireEvent('scheduler.interval')`
    would register as a real call site. Parsing sidesteps comments and strings
    entirely.

    Templated names (`'%s.snatched' % media_type`) are skipped — they are only
    concrete at runtime, which is exactly the gap the runtime warning in
    fireEvent() covers.

    Known limit: only calls written as `fireEvent(...)`/`addEvent(...)` are
    recognised, so an aliased import (`... import fireEvent as fe`) would
    escape the audit. No such alias exists in the tree; the runtime warning
    would still catch anything fired that way.
    """
    fired, handled = {}, set()
    constants = _event_name_constants()

    for path in _python_files():
        tree = ast.parse(path.read_text(errors='replace'))
        bound_literals, _bound_templates = _string_bindings(tree)

        for node in ast.walk(tree):
            # Notification plugins register their `listen_to` list
            # dynamically, so those names never appear in an addEvent() call.
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == 'listen_to' \
                            and isinstance(node.value, (ast.List, ast.Tuple)):
                        handled.update(
                            elt.value for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        )
                continue

            if not isinstance(node, ast.Call):
                continue

            call = _call_name(node)
            name = _first_string_arg(node, constants)

            # A fire whose name is a variable holding string literals, e.g.
            # `message_type = 'core.message.important' if ... else 'core.message'`
            # followed by `fireEvent(message_type, ...)`. Reading only the call
            # site reports both of those as never fired, and they work.
            if (not name and call in ('fireEvent', 'fireEventAsync')
                    and node.args and isinstance(node.args[0], ast.Name)):
                for literal in bound_literals.get(node.args[0].id, ()):
                    if '%' not in literal:
                        fired.setdefault(literal, set()).add(str(path))
                continue

            if not name:
                continue

            if call == 'addEvent':
                handled.add(name)
            elif call in ('fireEvent', 'fireEventAsync') and '%' not in name:
                fired.setdefault(name, set()).add(str(path))

    return fired, handled


# ---------------------------------------------------------------------------
# The reverse direction: registered but never fired.
#
# `test_every_fired_event_is_handled_or_allowlisted` above catches an event
# that is SENT with nobody listening. Nothing caught the opposite, an event
# that is LISTENED FOR and never sent, and that is the direction which has
# actually cost this project: `renamer.before` / `renamer.after` are
# registered and never fired, which is why subtitles, trailers, notifications
# and metadata are all silently dead despite correct plugin code.
#
# The hard part is not the assertion, it is not lying. `_collect()` ignores a
# fire whose name is computed (`'%s.snatched' % media_type`), so a naive
# reverse check reports every templated dispatch as dead. Measured on this
# tree that would be 38 names, of which 18 are working features: it would
# have sent someone rewiring `movie.snatched` and `movie.downloaded`, both of
# which fire correctly. Reporting a working feature as dead is worse than the
# gap this closes, so templated dispatch is resolved rather than skipped.
# ---------------------------------------------------------------------------

#: Templates whose `%s` is a VALUE the caller supplies: a media type, a
#: settings section, a provider. Any name matching the shape is genuinely
#: reachable, because some caller supplies that value.
#:
#: Derived by reading every templated fire site in the tree, not guessed;
#: `test_value_templates_match_the_tree` below fails if the tree grows one
#: this list does not know about, so it cannot quietly go stale.
VALUE_FIRE_TEMPLATES = (
    '%s.downloaded',            # release/main.py, media/_base/media/main.py
    '%s.info',                  # media/_base/search/main.py
    '%s.search',                # media/_base/search/main.py
    '%s.searcher.all_view',     # media/_base/searcher/main.py
    '%s.snatched',              # release/main.py
    '%s.searcher.single',       # media/__init__.py, via a bound variable
    '%s.update',                # media/__init__.py and media/_base/media/main.py,
                                #   also via a bound variable
    'provider.search.%s.%s',    # media/_base/searcher/main.py
    'setting.save.%s.%s',       # settings.py
    'setting.save.%s.%s.committed',
)

#: Hooks the DISPATCHER derives from whatever is being fired, in
#: `couchpotato/core/event.py`'s own `fireEvent`. These are NOT wildcards: the
#: `%s` is bound to the event currently being dispatched, so `X.after` fires
#: only when `X` does. Treating them as wildcards is the mistake that would
#: mark `renamer.after` as alive, and `renamer.after` being dead is the whole
#: reason this guard exists.
DERIVED_HOOK_SUFFIX = '.after'
DERIVED_HOOK_PREFIX = 'result.modify.'


def _string_bindings(tree):
    """Map every `name = <str>` / `name = '<fmt>' % ...` in a module.

    A fire whose name is held in a variable is invisible to a collector that
    only reads the call site, and there are three in this tree. Two are
    templates (`event = '%s.update' % media.get('type')`), and one is a
    straight choice between two literals:

        message_type = 'core.message.important' if important else 'core.message'
        fireEvent(message_type, ...)

    Without this, `core.message` and `core.message.important` are reported as
    dead. They work, and the notifications behind them work. Module scope, not
    function scope, is deliberately coarse: it can only ever make this guard
    MORE forgiving, and a false "dead" verdict is the expensive direction.
    """
    literals, templates = {}, {}

    def record(target, value):
        if not isinstance(target, ast.Name):
            return
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            literals.setdefault(target.id, set()).add(value.value)
        elif (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mod)
                and isinstance(value.left, ast.Constant)
                and isinstance(value.left.value, str)):
            templates.setdefault(target.id, set()).add(value.left.value)
        elif isinstance(value, ast.IfExp):
            record(target, value.body)
            record(target, value.orelse)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                record(t, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            record(node.target, node.value)

    return literals, templates


def _templated_fire_formats():
    """Every format string used as a fire name, e.g. `'%s.snatched'`.

    Only production code: the tests below deliberately fire crafted names.
    """
    formats = {}
    for path in _python_files():
        if 'tests' in path.parts:
            continue
        tree = ast.parse(path.read_text(errors='replace'))
        _bound_literals, bound_templates = _string_bindings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in ('fireEvent', 'fireEventAsync'):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if (isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod)
                    and isinstance(arg.left, ast.Constant)
                    and isinstance(arg.left.value, str)):
                formats.setdefault(arg.left.value, set()).add(
                    '%s:%s' % (path, node.lineno))
            elif isinstance(arg, ast.Name):
                # `event = '%s.update' % media.get('type')` then fireEvent(event)
                for fmt in bound_templates.get(arg.id, ()):
                    formats.setdefault(fmt, set()).add(
                        '%s:%s' % (path, node.lineno))
    return formats


def _template_matcher(template):
    """A template to a regex where each `%s`/`%d` is exactly one name segment.

    One segment, not `.*`: `setting.save.%s.%s` must not swallow a name with
    four segments after the prefix, or the guard silently widens every time
    someone adds a deeper name.
    """
    parts = re.split(r'(%[sd]|\*)', template)
    body = ''.join(r'[^.]+' if p in ('%s', '%d', '*') else re.escape(p)
                   for p in parts)
    return re.compile('^' + body + '$')


def _is_reachable(name, fired, matchers, _depth=0):
    """True if `name` can actually be dispatched at runtime.

    Recursive because the derived hooks compose: `setting.save.x.y.after` is
    reachable only because `setting.save.x.y` matches a value template, and
    `result.modify.movie.search` only because `movie.search` does.
    """
    if _depth > 8:          # a cycle cannot arise from these rules, but a
        return False        # future rule could; fail closed rather than hang.
    if name in fired:
        return True
    if any(m.match(name) for m in matchers):
        return True
    if name.endswith(DERIVED_HOOK_SUFFIX):
        base = name[:-len(DERIVED_HOOK_SUFFIX)]
        if base and _is_reachable(base, fired, matchers, _depth + 1):
            return True
    if name.startswith(DERIVED_HOOK_PREFIX):
        base = name[len(DERIVED_HOOK_PREFIX):]
        if base and _is_reachable(base, fired, matchers, _depth + 1):
            return True
    return False


#: Registration sites whose event NAME is computed, so `_collect()` cannot see
#: them and the reverse audit above cannot reason about them at all. Pinned as
#: a list rather than described in prose, so the blind spot is visible and
#: expires: adding one fails this file rather than silently widening the gap.
#:
#: Two of these are genuinely orphaned and cannot be recorded in
#: UNFIRED_EVENTS, because that allowlist's staleness check requires the name
#: to be visible in `handled`, and by construction these are not:
#:
#:   '%s.searcher.progress'  registered at searcher/base.py:17 and never
#:       fired: the only dispatch is `searcher.progress` (searcher/main.py:50),
#:       a DIFFERENT name. The feature still works, reached as the API view
#:       'movie.searcher.progress' (movie/searcher.py:75), so this is the same
#:       shape as media.mark_watched rather than a dead feature.
#:   'notify.%s'  registered per provider at notifications/base.py:26 and
#:       never fired. Providers are reached through `listen_to` and the test
#:       button goes to the API view 'notify.<name>.test', so again the door
#:       is unused rather than the behaviour missing.
TEMPLATED_REGISTRATION_SITES = {
    'couchpotato/core/media/_base/searcher/base.py:17': '%s.searcher.progress',
    'couchpotato/core/media/_base/searcher/base.py:33': 'setting.save.%s_searcher.cron_day.after',
    'couchpotato/core/media/_base/searcher/base.py:34': 'setting.save.%s_searcher.cron_hour.after',
    'couchpotato/core/media/_base/searcher/base.py:35': 'setting.save.%s_searcher.cron_minute.after',
    'couchpotato/core/notifications/base.py:26': 'notify.%s',
    'couchpotato/core/media/_base/providers/base.py:137': 'provider.search.%s.%s',
    'couchpotato/environment.py:101': '<forwarded *args>',
}


def _templated_registration_sites():
    """Every addEvent whose name is not a plain literal or a known constant."""
    found = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(errors='replace'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != 'addEvent':
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) or isinstance(arg, ast.Name):
                continue
            where = '%s:%s' % (path.relative_to(REPO_ROOT), node.lineno)
            if (isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod)
                    and isinstance(arg.left, ast.Constant)):
                found[where] = arg.left.value
            else:
                found[where] = '<forwarded *args>'
    return found


def _allowlisted_handler_methods():
    """Map each allowlisted event name to the handler methods registered for
    it, as `(module path, method name)` pairs."""
    methods = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(errors='replace'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != 'addEvent':
                continue
            if len(node.args) < 2 or not isinstance(node.args[0], ast.Constant):
                continue
            name = node.args[0].value
            if name not in UNFIRED_EVENTS:
                continue
            handler = node.args[1]
            attr = getattr(handler, 'attr', None) or getattr(handler, 'id', None)
            if attr:
                methods.setdefault(name, set()).add(
                    (str(path.relative_to(REPO_ROOT)), attr))
    return methods


def _methods_with_another_caller(candidates):
    """Of `(module, method)` pairs, those the code can reach some OTHER way:
    registered as an API view, or called directly from anywhere.

    Scoped to the module that registers the handler, because a method name
    alone collides across the tree: an earlier version of this analysis
    matched names globally and reported `renamer.after` as API-reachable
    through an unrelated `create()`.
    """
    wanted = {}
    for module, method in candidates:
        wanted.setdefault(module, set()).add(method)

    reachable = set()
    for path in _python_files():
        module = str(path.relative_to(REPO_ROOT))
        names = wanted.get(module)
        if not names:
            continue
        tree = ast.parse(path.read_text(errors='replace'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Registered as an API view: reachable over HTTP.
            if _call_name(node) == 'addApiView' and len(node.args) >= 2:
                attr = getattr(node.args[1], 'attr', None)
                if attr in names:
                    reachable.add((module, attr))
            # Called directly by something else in the same module, e.g.
            # Plex.test() calling self.addToLibrary().
            called = getattr(node.func, 'attr', None)
            if called in names and _call_name(node) != 'addEvent':
                reachable.add((module, called))

            # Handed to something else as a CALLABLE rather than called, which
            # is how the scheduler reaches checkSnatched:
            #   fireEvent('schedule.interval', 'renamer.check_snatched',
            #             self.checkSnatched, ...)
            # The string there is a schedule id, not a dispatch, and the
            # method runs. Reading only call sites misses this entirely.
            if _call_name(node) != 'addEvent':
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    passed = getattr(arg, 'attr', None)
                    if passed in names:
                        reachable.add((module, passed))
    return reachable


def _unfired_handlers():
    """Registered names that nothing can dispatch. Returns a sorted list."""
    fired, handled = _collect()
    matchers = [_template_matcher(t) for t in VALUE_FIRE_TEMPLATES]
    return sorted(n for n in handled if not _is_reachable(n, fired, matchers))


class TestNoUnhandledEvents:

    def test_every_fired_event_is_handled_or_allowlisted(self):
        fired, handled = _collect()

        unhandled = {
            name: sorted(paths) for name, paths in fired.items()
            if name not in handled and name not in OPTIONAL_EVENTS
        }

        assert not unhandled, (
            'These events are fired but nothing handles them, so they silently '
            'do nothing:\n%s\nEither wire up a handler, or add the name to '
            'OPTIONAL_EVENTS in couchpotato/core/event.py with a comment '
            'explaining why nothing needs to handle it.'
            % '\n'.join('  %s  <- %s' % (n, p[0]) for n, p in sorted(unhandled.items()))
        )

    def test_the_scheduler_interval_typo_stays_fixed(self):
        """Regression pin for the specific typo found by this audit. The real
        event is `schedule.interval` (singular)."""
        fired, _ = _collect()

        assert 'scheduler.interval' not in fired, (
            "'scheduler.interval' is a typo for 'schedule.interval' and "
            'schedules nothing'
        )

    def test_allowlist_has_no_stale_entries(self):
        """An allowlisted name that has since gained a handler, or is no longer
        fired at all, is misleading — it implies a known gap that isn't there."""
        fired, handled = _collect()

        stale = [
            name for name in OPTIONAL_EVENTS
            if name in handled or name not in fired
        ]

        assert not stale, (
            'OPTIONAL_EVENTS entries that are now handled or no longer fired: '
            '%s — remove them.' % stale
        )


class TestNoUnfiredHandlers:
    """The reverse direction: registered and never dispatched."""

    def test_every_handled_event_is_fired_or_allowlisted(self):
        unfired = [n for n in _unfired_handlers() if n not in UNFIRED_EVENTS]

        assert not unfired, (
            'These events are registered but nothing fires them, so the code '
            'behind them never runs:\n%s\nEither wire up the dispatch, delete '
            'the handler, or add the name to UNFIRED_EVENTS in '
            'couchpotato/core/event.py with a comment saying WHY it is '
            'unreachable and what would make that decision expire.'
            % '\n'.join('  %s' % n for n in unfired)
        )

    def test_a_templated_dispatch_is_not_reported_as_dead(self):
        """The false positive that would discredit this guard.

        `movie.snatched` and `movie.downloaded` are fired as
        `'%s.snatched' % data['type']` (release/main.py) and
        `'%s.downloaded' % m.get('type', 'movie')` (media/_base/media/main.py).
        They work. An earlier hand-audit called both dead, by grepping for the
        literal string, which by construction cannot match a computed name.
        If this ever fails, the guard is about to send someone rewiring a
        feature that already works.
        """
        unfired = _unfired_handlers()

        for name in ('movie.snatched', 'movie.downloaded'):
            assert name not in unfired, (
                '%s is dispatched with a computed name and works; reporting it '
                'as dead would be a false positive of exactly the kind that '
                'makes a guard get ignored.' % name
            )

    def test_the_dead_renamer_chain_is_still_caught(self):
        """The other half, and the reason the guard exists at all.

        `renamer.before` / `renamer.after` are registered by subtitles,
        trailers, notifications and metadata, and nothing fires bare `renamer`,
        so none of them has run since the FastAPI migration. A resolver
        generous enough to treat `%s.after` as a wildcard would mark
        `renamer.after` alive and miss this.
        """
        unfired = _unfired_handlers()

        for name in ('renamer.before', 'renamer.after'):
            # NOT `or name in UNFIRED_EVENTS`: both names are permanently in
            # that set, so the disjunct made this assertion a tautology. It
            # was a test named for the reason this guard exists that could
            # not fail. `unfired` is the raw result, unfiltered by the
            # allowlist, so membership in it is the real question.
            assert name in unfired, (
                '%s is registered and nothing fires it. If this stops being '
                'true the dispatch was wired up, which is good news: remove it '
                'from UNFIRED_EVENTS.' % name
            )

    def test_derived_hooks_are_not_treated_as_wildcards(self):
        """`X.after` fires only when `X` does, per fireEvent() in event.py.

        Pinned because the difference is invisible in the result until it
        matters: as a wildcard, every `*.after` name reads as alive.
        """
        fired, _ = _collect()
        matchers = [_template_matcher(t) for t in VALUE_FIRE_TEMPLATES]

        assert _is_reachable('app.load.after', fired, matchers), (
            'app.load is fired, so app.load.after is derived from it'
        )
        assert not _is_reachable('nothing.fires.this.after', fired, matchers), (
            'a .after hook whose base event is never fired is not reachable'
        )

    def test_value_templates_match_the_tree(self):
        """Fail when the tree grows a templated dispatch this file does not
        know about, rather than silently reporting its handlers as dead."""
        matchers = [_template_matcher(t) for t in VALUE_FIRE_TEMPLATES]
        unexplained = {}

        for fmt, sites in _templated_fire_formats().items():
            if fmt in VALUE_FIRE_TEMPLATES:
                continue
            # A derived hook, or a value template with one composed onto it.
            base = fmt
            for _ in range(3):
                if base.endswith(DERIVED_HOOK_SUFFIX):
                    base = base[:-len(DERIVED_HOOK_SUFFIX)]
                elif base.startswith(DERIVED_HOOK_PREFIX):
                    base = base[len(DERIVED_HOOK_PREFIX):]
                else:
                    break
            if base in ('%s', ''):          # the dispatcher's own hooks
                continue
            if base in VALUE_FIRE_TEMPLATES:
                continue
            if any(m.match(base.replace('%s', 'x').replace('%d', '1'))
                   for m in matchers):
                continue
            unexplained[fmt] = sorted(sites)

        assert not unexplained, (
            'These templated dispatches are not covered by '
            'VALUE_FIRE_TEMPLATES, so every handler they serve will be '
            'reported as dead:\n%s'
            % '\n'.join('  %s  <- %s' % (f, s[0]) for f, s in sorted(unexplained.items()))
        )

    def test_templated_registrations_stay_disclosed(self):
        """The reverse audit's OTHER blind spot, held visible.

        `_collect()` only sees an addEvent whose name is a literal or a known
        constant, so a registration under a computed name is invisible to
        every assertion in this class. That is not fixable by resolving the
        name (the value only exists at runtime), so it is disclosed and
        pinned instead: a new one fails here rather than quietly enlarging
        the set of handlers nobody is auditing.
        """
        found = _templated_registration_sites()

        added = {k: v for k, v in found.items() if k not in TEMPLATED_REGISTRATION_SITES}
        assert not added, (
            'New addEvent site(s) with a computed name. The reverse audit in '
            'this class cannot see these handlers at all, so record them in '
            'TEMPLATED_REGISTRATION_SITES with what they register and whether '
            'anything fires it:\n%s'
            % '\n'.join('  %s  %s' % (k, v) for k, v in sorted(added.items()))
        )

        gone = {k: v for k, v in TEMPLATED_REGISTRATION_SITES.items() if k not in found}
        assert not gone, (
            'These recorded sites no longer register a computed name, so the '
            'entry describes nothing. Remove them, or correct the line '
            'number if the file merely moved:\n%s'
            % '\n'.join('  %s  %s' % (k, v) for k, v in sorted(gone.items()))
        )

    def test_reachable_handlers_are_declared(self):
        """No allowlist comment may say a handler is dead when it is not.

        Three rounds of review on this branch each found one: `category.all`
        filed as unreachable while the settings UI calls it, and
        `renamer.after` described as seven dead handlers when
        `Plex.addToLibrary` runs from the Test button. Both were caught by a
        human reading plugin files. This resolves each allowlisted name to
        its handler methods and asks whether anything else reaches them, so
        the claim is checked rather than believed.
        """
        registered = _allowlisted_handler_methods()
        pairs = {p for methods in registered.values() for p in methods}
        reachable = _methods_with_another_caller(pairs)

        found = {}
        for name, methods in registered.items():
            hit = {m for module, m in methods if (module, m) in reachable}
            if hit:
                found[name] = hit

        missing = {n: sorted(m) for n, m in found.items()
                   if m != set(HANDLERS_REACHABLE_ANOTHER_WAY.get(n, ()))}
        assert not missing, (
            'These allowlisted events have handler methods something ELSE can '
            'reach (an API view, a direct call, or handed over as a callable), '
            'and HANDLERS_REACHABLE_ANOTHER_WAY does not say so. Saying a '
            'handler is dead when it is not reads as a licence to delete live '
            'code:\n%s'
            % '\n'.join('  %s -> %s' % (n, m) for n, m in sorted(missing.items()))
        )

        stale = {n: sorted(m) for n, m in HANDLERS_REACHABLE_ANOTHER_WAY.items()
                 if set(m) != found.get(n, set())}
        assert not stale, (
            'These are declared reachable another way, and nothing reaches '
            'them any more. The other route was removed, so the handler may '
            'now be genuinely dead:\n%s'
            % '\n'.join('  %s -> %s' % (n, m) for n, m in sorted(stale.items()))
        )

    def test_unfired_allowlist_has_no_stale_entries(self):
        """Fails in BOTH directions, so the allowlist is a record of decisions
        rather than a place to hide names.

        An entry that gains a dispatch, or stops being registered at all, has
        to be revisited: without this the list only ever grows.
        """
        _, handled = _collect()
        unfired = set(_unfired_handlers())

        now_fired = sorted(n for n in UNFIRED_EVENTS if n in handled and n not in unfired)
        assert not now_fired, (
            'These are in UNFIRED_EVENTS but something now fires them. Good '
            'news, remove them from the list:\n%s'
            % '\n'.join('  %s' % n for n in now_fired)
        )

        gone = sorted(n for n in UNFIRED_EVENTS if n not in handled)
        assert not gone, (
            'These are in UNFIRED_EVENTS but nothing registers them any more, '
            'so the entry describes nothing. Remove them:\n%s'
            % '\n'.join('  %s' % n for n in gone)
        )


class TestFireEventWarnsOnUnhandled:
    """The runtime half. Static analysis cannot see templated names like
    `'%s.snatched' % media_type`, so fireEvent() reports them itself."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        """Both pieces of module state, or a test that fills the cache leaves
        the cap-announced flag set and silently disarms the next one."""
        from couchpotato.core import event

        def clear():
            event._warned_unhandled.clear()
            event._warned_cache_full[0] = False

        clear()
        yield
        clear()

    def test_warns_once_for_an_unhandled_event(self, caplog):
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            fireEvent('totally.made.up.event')

        assert 'totally.made.up.event' in caplog.text

    def test_does_not_repeat_the_warning(self, caplog):
        """fireEvent is hot — one line per name, not per call."""
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            for _ in range(5):
                fireEvent('another.made.up.event')

        assert caplog.text.count('another.made.up.event') == 1

    def test_stays_quiet_for_allowlisted_events(self, caplog):
        from couchpotato.core.event import OPTIONAL_EVENTS, fireEvent

        name = sorted(OPTIONAL_EVENTS)[0]

        with caplog.at_level('WARNING'):
            fireEvent(name)

        assert name not in caplog.text

    def test_still_returns_the_empty_result(self):
        """The warning must not change the contract callers rely on."""
        from couchpotato.core.event import fireEvent

        assert fireEvent('yet.another.made.up.event') == []

    def test_stays_quiet_for_the_structural_hooks(self, caplog):
        """fireEvent() derives `result.modify.<name>` and `<name>.after` from
        EVERY dispatch. They are opt-in hooks and unhandled for nearly every
        event, so warning about them would mean two useless lines per event
        name in the system -- which is what a first cut of this actually did.
        """
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            fireEvent('result.modify.something')
            fireEvent('something.after')

        assert 'result.modify.something' not in caplog.text
        assert 'something.after' not in caplog.text

    def test_stays_quiet_for_per_setting_hooks(self, caplog):
        """Settings.save() fires `setting.save.<section>.<option>` for every
        saved option, and only a handful have a handler -- so without this a
        single settings save emits a warning per option. Measured: 7 options,
        7 warnings.
        """
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            for option in ('api_key', 'username', 'password', 'port'):
                fireEvent('setting.save.core.%s' % option)

        assert caplog.text == '', (
            'a settings save must not warn per option, got: %r' % caplog.text
        )

    def test_names_that_merely_contain_a_hook_word_still_warn(self, caplog):
        """The suppression is prefix/suffix anchored, not a substring match --
        it must not silence a genuine dead event whose name happens to contain
        one of the hook words."""
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            fireEvent('movie.after.something')       # '.after' not at the end
            fireEvent('plugin.result.modify.thing')  # prefix not at the start

        assert 'movie.after.something' in caplog.text
        assert 'plugin.result.modify.thing' in caplog.text

    def test_a_real_dispatch_emits_no_hook_noise(self, caplog):
        """End to end: firing one handled event must produce NO warnings, even
        though it internally dispatches both derived hooks."""
        from couchpotato.core.event import addEvent, fireEvent, removeEvent

        addEvent('quiet.test.event', lambda: 'ok')
        try:
            with caplog.at_level('WARNING'):
                result = fireEvent('quiet.test.event')
        finally:
            removeEvent('quiet.test.event')

        assert result == ['ok']
        assert caplog.text == '', 'a normal dispatch must be silent, got: %r' % caplog.text

    def test_the_warning_cache_is_bounded(self, caplog):
        """Event names can be caller-derived: `Search.search()` fires
        `'%s.search' % media_type` where `types` comes straight off the API
        request. An unbounded cache would grow for the life of the process on
        arbitrary input -- a slow memory leak plus a log line each.

        Past the cap the cache stops growing and stops logging.
        """
        from couchpotato.core import event
        from couchpotato.core.event import fireEvent

        for i in range(event.MAX_WARNED_UNHANDLED + 50):
            fireEvent('attacker.controlled.%d.search' % i)

        assert len(event._warned_unhandled) <= event.MAX_WARNED_UNHANDLED

    def test_says_so_when_it_stops_reporting(self, caplog):
        """Hitting the cap disables the guard for the rest of the process --
        including for genuinely new dead events unrelated to whatever filled
        it. Silently going quiet is the same failure this whole mechanism
        exists to prevent, so it must announce that it has stopped.
        """
        from couchpotato.core import event
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            for i in range(event.MAX_WARNED_UNHANDLED + 1):
                fireEvent('filler.%d.search' % i)

        assert 'no longer reporting' in caplog.text.lower(), (
            'reaching the cap must be announced, got: %r' % caplog.text[-400:]
        )

    def test_announces_the_cap_only_once(self, caplog):
        from couchpotato.core import event
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            for i in range(event.MAX_WARNED_UNHANDLED + 20):
                fireEvent('filler.%d.search' % i)

        assert caplog.text.lower().count('no longer reporting') == 1

    def test_stops_logging_once_the_cache_is_full(self, caplog):
        from couchpotato.core import event
        from couchpotato.core.event import fireEvent

        for i in range(event.MAX_WARNED_UNHANDLED):
            fireEvent('filler.%d.search' % i)

        with caplog.at_level('WARNING'):
            fireEvent('one.more.unhandled.search')

        assert 'one.more.unhandled.search' not in caplog.text, (
            'past the cap, further unknown names must not log'
        )

    def test_a_crafted_name_cannot_forge_log_lines(self, caplog):
        """`name` is caller-derived -- the search API's `types` param becomes
        `'<type>.search'` -- and this is the first place it reaches the log.
        %r escapes newlines, so an injected line break cannot fake a second
        log record."""
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            fireEvent('evil\nWARNING  forged log line.search')

        assert 'forged log line' in caplog.text, 'sanity: the name was logged'
        assert '\nWARNING  forged' not in caplog.text, (
            'a newline in the event name must not survive into the log'
        )

    def test_an_absurdly_long_name_is_truncated(self, caplog):
        from couchpotato.core.event import fireEvent

        with caplog.at_level('WARNING'):
            fireEvent('x' * 5000 + '.search')

        assert len(caplog.text) < 1000, (
            'a caller-supplied name must not write an unbounded log line'
        )

    def test_handled_events_do_not_warn(self, caplog):
        from couchpotato.core.event import addEvent, fireEvent, removeEvent

        addEvent('a.real.test.event', lambda: 'ok')
        try:
            with caplog.at_level('WARNING'):
                fireEvent('a.real.test.event')
        finally:
            removeEvent('a.real.test.event')

        assert 'a.real.test.event' not in caplog.text
