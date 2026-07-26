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

import pytest

from couchpotato.core.event import OPTIONAL_EVENTS

# Anchored to this file, not the CWD. A relative path silently yields an empty
# file list when pytest is invoked from anywhere but the repo root, and every
# assertion below would then pass trivially -- a guard providing zero coverage
# while reporting green is worse than no guard.
SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / 'couchpotato'


def _python_files():
    files = [p for p in SOURCE_ROOT.rglob('*.py') if 'lib/' not in str(p)]
    assert files, 'found no source files under %s' % SOURCE_ROOT
    return files


def _call_name(node):
    """The bare function name of a Call node, however it was referenced."""
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

    for path in _python_files():
        tree = ast.parse(path.read_text(errors='replace'))

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
            name = _first_string_arg(node)
            if not name:
                continue

            if call == 'addEvent':
                handled.add(name)
            elif call in ('fireEvent', 'fireEventAsync') and '%' not in name:
                fired.setdefault(name, set()).add(str(path))

    return fired, handled


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


class TestFireEventWarnsOnUnhandled:
    """The runtime half. Static analysis cannot see templated names like
    `'%s.snatched' % media_type`, so fireEvent() reports them itself."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from couchpotato.core import event

        event._warned_unhandled.clear()
        yield
        event._warned_unhandled.clear()

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

    def test_handled_events_do_not_warn(self, caplog):
        from couchpotato.core.event import addEvent, fireEvent, removeEvent

        addEvent('a.real.test.event', lambda: 'ok')
        try:
            with caplog.at_level('WARNING'):
                fireEvent('a.real.test.event')
        finally:
            removeEvent('a.real.test.event')

        assert 'a.real.test.event' not in caplog.text
