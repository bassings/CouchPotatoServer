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
line 359) mentions the literal text `clean_orphaned_movies(db)` in prose,
explaining why its own scan loop cannot be relied on to raise when it
fails. A naive occurrence count sees that docstring line as a second call
on entirely clean code, and either fails a passing repo or needs a fudge
factor that makes the guard unable to fail on a real bypass. Parsing the
AST and filtering to `Call` nodes only counts code that actually executes.

Fix round two, FIX C: `_real_calls_to` originally matched only the bare
name `clean_orphaned_movies`. A reviewer measured that renaming the import
at the bypass site (`from couchpotato.core.migration.clean_orphans import
clean_orphaned_movies as _oc`, then `_oc(db)` planted beside the gate)
made the bypass invisible to this guard -- it passed, and so did the
entire unit suite, 3797 tests, the identical count that currently reads as
clean. `_real_calls_to` now also resolves any local name the real function
is imported under via `from couchpotato.core.migration.clean_orphans
import clean_orphaned_movies as <alias>` and counts calls to that name
too.

Scope of what this guard catches, so nobody later mistakes it for more
than it is: a second call under the ORIGINAL bare name, a call via
attribute access on any module alias (`module.clean_orphaned_movies(db)`,
regardless of what `module` itself is imported as), and now a call via a
local alias created by an explicit `from ... import ... as ...` of the
real function. It does NOT catch a bypass reached through `getattr`, or a
call planted in some other module that itself imports and calls the real
function and is then invoked here under a name this guard has never heard
of -- both of those require a second layer of indirection deliberate
enough that a reviewer judged them non-accidents, not something a rename
slips past by itself, and this guard does not chase them.
"""
import ast
from pathlib import Path

RUNNER_PATH = Path(__file__).resolve().parents[2] / 'couchpotato' / 'runner.py'

GATE_FUNCTION_NAME = '_run_orphan_cleanup'
GUARDED_CALL_NAME = 'clean_orphaned_movies'
GUARDED_MODULE_NAME = 'couchpotato.core.migration.clean_orphans'


def _parse_runner():
    source = RUNNER_PATH.read_text(encoding='utf-8')
    return source, ast.parse(source, filename=str(RUNNER_PATH))


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _local_names_bound_to(tree, module_name, func_name):
    """Every local name `func_name` is bound to by a
    `from module_name import func_name [as alias]` statement anywhere in
    the tree, including `func_name` itself. Renaming the import at a
    bypass site (`... import clean_orphaned_movies as _oc`) must not hide
    the call from `_real_calls_to` below -- see FIX C in the module
    docstring.
    """
    names = {func_name}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            for alias in node.names:
                if alias.name == func_name:
                    names.add(alias.asname or alias.name)
    return names


def _real_calls_to(tree, func_name, module_name=GUARDED_MODULE_NAME):
    """Every `ast.Call` node that invokes `func_name`, whether referenced
    bare under its original name, under a local alias created by
    `from module_name import func_name as <alias>`, or via attribute
    access (`module.func_name(db)`, whatever `module` itself is bound to).
    Deliberately does not look at strings, comments or docstrings -- those
    are `ast.Constant` nodes, not `ast.Call` nodes, so prose mentioning the
    name is invisible here. See the module docstring for what this
    deliberately does NOT catch.
    """
    local_names = _local_names_bound_to(tree, module_name, func_name)

    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in local_names:
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


class TestRealCallsToDetectsAnAliasedImport:
    """FIX C, fix round two. `_real_calls_to` used to match only the bare
    name `clean_orphaned_movies`, so a bypass imported under a different
    local name (`from couchpotato.core.migration.clean_orphans import
    clean_orphaned_movies as _oc`, then `_oc(db)` planted beside the gate)
    was invisible to it. A reviewer measured that exact shape passing both
    this guard and the entire unit suite, 3797 tests, the identical count
    that currently reads as clean.

    This test does not mutate the real runner.py -- it parses a small
    synthetic module string that reproduces the aliased-bypass shape, so
    the helper's own alias resolution is pinned on every run without
    depending on a file mutation. The real-file mutation is proved
    separately, by hand, as part of this fix's review evidence.
    """

    def test_call_via_an_aliased_import_is_counted(self):
        source = (
            "from couchpotato.core.migration.clean_orphans import "
            "clean_orphaned_movies as _oc\n"
            "\n"
            "def _run_orphan_cleanup(db, log):\n"
            "    pass\n"
            "\n"
            "_oc(db)\n"
        )
        tree = ast.parse(source)

        calls = _real_calls_to(tree, GUARDED_CALL_NAME)

        assert len(calls) == 1, (
            'a call to the guarded function imported under a different '
            'local name via "import ... as" must still be counted -- '
            'otherwise renaming the import at an unguarded call site '
            'defeats this guard entirely (FIX C)'
        )

    def test_call_via_the_original_bare_name_is_still_counted(self):
        """The plain bypass -- no alias at all -- must still be caught,
        so the alias-resolution fix cannot have narrowed the guard.
        """
        source = (
            "from couchpotato.core.migration.clean_orphans import "
            "clean_orphaned_movies\n"
            "\n"
            "def _run_orphan_cleanup(db, log):\n"
            "    pass\n"
            "\n"
            "clean_orphaned_movies(db)\n"
        )
        tree = ast.parse(source)

        calls = _real_calls_to(tree, GUARDED_CALL_NAME)

        assert len(calls) == 1
