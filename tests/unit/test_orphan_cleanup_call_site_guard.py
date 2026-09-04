"""BUG-017 fix round one, FIX 3: a bypass beside the gate survives every
existing test.

A reviewer of commit 312f2472f restored the old unconditional
`clean_orphaned_movies(db)` call as a second block sitting right next to
`_run_orphan_cleanup(db, log)` at the startup call site in
`couchpotato/runner.py`. All five gate tests in
`tests/unit/test_orphan_cleanup_gate.py`, and the entire rest of the unit
suite, stayed green -- because none of them assert anything about
`runner.py`'s CALL SITE, only about `_run_orphan_cleanup` driven directly.
A unit test that calls the gate function itself structurally cannot see
whether something else calls the real thing beside it.

Modelled on the precedent for the same shape of bug in
`tests/unit/test_auth_required_gate.py::TestTheStartupMigrationRunsBeforeDefaultsAreMaterialised`,
which pins `resolve_auth_required_setting()`'s position by source order for
the same reason.

That precedent counts matching source LINES by string prefix. This guard
parses `runner.py` with `ast` instead, and counts real `ast.Call` nodes,
because a plain string/line count of "clean_orphaned_movies(db)" is a trap
here specifically: `_run_orphan_cleanup`'s own docstring (runner.py, around
line 323) mentions the literal text `clean_orphaned_movies(db)` in prose,
explaining why an unreadable property store doesn't imply the cleanup would
also raise. A naive occurrence count sees that docstring line as a second
call on entirely clean code, and either fails a passing repo or needs a
fudge factor that makes the guard unable to fail on a real bypass. Parsing
the AST and filtering to `Call` nodes only counts code that actually
executes.
"""
import ast
from pathlib import Path

RUNNER_PATH = Path(__file__).resolve().parents[2] / 'couchpotato' / 'runner.py'

GATE_FUNCTION_NAME = '_run_orphan_cleanup'
GUARDED_CALL_NAME = 'clean_orphaned_movies'


def _parse_runner():
    source = RUNNER_PATH.read_text(encoding='utf-8')
    return source, ast.parse(source, filename=str(RUNNER_PATH))


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _real_calls_to(tree, func_name):
    """Every `ast.Call` node that invokes a function named `func_name`,
    whether referenced bare (`clean_orphaned_movies(db)`) or via attribute
    access (`module.clean_orphaned_movies(db)`). Deliberately does not look
    at strings, comments or docstrings -- those are `ast.Constant` nodes,
    not `ast.Call` nodes, so prose mentioning the name is invisible here.
    """
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == func_name:
            calls.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == func_name:
            calls.append(node)
    return calls


class TestExactlyOneRealCallSiteInsideTheGate:
    """FIX 3. `clean_orphaned_movies` must be called exactly once anywhere
    in `runner.py`, and that one call must live inside
    `_run_orphan_cleanup` -- never beside it at the startup call site,
    unguarded, and never a second time anywhere else in the file.
    """

    def test_docstring_mention_is_not_miscounted_as_a_call(self):
        """Sanity check on the guard itself, not on runner.py: the known
        docstring mention of the literal text "clean_orphaned_movies(db)"
        must not appear as an `ast.Call` node, or this whole guard is
        vacuous on a file that has never had a bypass.
        """
        source, tree = _parse_runner()
        assert 'clean_orphaned_movies(db)' in source, (
            'this test assumes the docstring mention still exists; if it '
            'was removed, this sanity check no longer proves anything and '
            'should be removed too'
        )
        calls = _real_calls_to(tree, GUARDED_CALL_NAME)
        assert len(calls) == 1, (
            'the docstring\'s prose mention of clean_orphaned_movies(db) '
            'must not be counted as a real call -- if it is, this guard '
            'cannot tell prose from code and is measuring the wrong thing'
        )

    def test_exactly_one_call_and_it_is_inside_the_gate_function(self):
        _source, tree = _parse_runner()

        calls = _real_calls_to(tree, GUARDED_CALL_NAME)

        assert len(calls) == 1, (
            'expected exactly one real call to %s() in runner.py, found %d '
            'at line(s) %s. More than one means an unguarded bypass has '
            'been restored beside the gate; zero means the gate itself is '
            'gone.' % (GUARDED_CALL_NAME, len(calls), [c.lineno for c in calls])
        )

        gate_fn = _find_function(tree, GATE_FUNCTION_NAME)
        assert gate_fn is not None, (
            '%s is missing from runner.py entirely' % GATE_FUNCTION_NAME
        )

        call_line = calls[0].lineno
        assert gate_fn.lineno <= call_line <= gate_fn.end_lineno, (
            'the one call to %s() at line %d is OUTSIDE %s (lines %d-%d) '
            '-- an ungated bypass exists at the startup call site' % (
                GUARDED_CALL_NAME, call_line, GATE_FUNCTION_NAME,
                gate_fn.lineno, gate_fn.end_lineno,
            )
        )
