"""A test fixture shelling out to `git` must never touch the developer's
real repository (T31 follow-up).

Git sets `GIT_DIR` (and its siblings `GIT_WORK_TREE`, `GIT_INDEX_FILE`,
`GIT_OBJECT_DIRECTORY`, `GIT_COMMON_DIR`,
`GIT_ALTERNATE_OBJECT_DIRECTORIES`) in the environment of hook subprocesses
-- but only when the push comes from a `git worktree` checkout rather than
the main one. `pre-push` runs `make verify`, which runs this suite, so a
push from a worktree hands the pytest *process itself* a `GIT_DIR` naming
the worktree's real `.git`.

`tests/unit/test_hybrid_gate.py` and
`tests/unit/test_gate_covers_the_ui_backend.py` shell out to `git init`,
`git commit`, `git checkout -b`, etc. inside a throwaway `tmp_path`. Before
the fix, those calls did not sanitise the subprocess environment, so they
inherited GIT_DIR straight from the ambient pytest process. With GIT_DIR
set, `git init` in a fresh directory does not create a new repo there -- it
RE-INITIALISES the repo GIT_DIR already points at, and every later fixture
`git commit`/`checkout -b` lands there too.

This test runs the REAL fixtures as a subprocess pytest invocation with
GIT_DIR poisoned in the ambient environment -- exactly the shape a worktree
push produces -- rather than a hand-written mirror of the fixture code, so
it stays true to whatever the fixtures actually do rather than to what this
file assumes they do. It proves two things: the fixtures still pass under a
poisoned ambient environment, and a stand-in "victim" repository is left
byte-for-byte untouched: same HEAD commit, same branch, same `core.bare`,
no new branches, and its one uncommitted file still on disk.

The two node IDs below were chosen to touch all five of the originally
audited unsanitised call sites between them:
  - test_gate_covers_the_ui_backend.py's `repo` fixture (git init) and
    `classify()` (git add/commit, and the needs_e2e.sh invocation) --
    exercised together because `classify()` is only ever called against an
    already-initialised `repo`.
  - test_hybrid_gate.py's `repo` fixture (git init/commit) and `_run()`
    (the needs_e2e.sh invocation).
"""
import os
import subprocess
from tests.unit.conftest import sanitized_git_env
import sys
from pathlib import Path
import ast

REPO = Path(__file__).resolve().parents[2]

# Between them, exercises the repo fixture + classify()/needs_e2e.sh call in
# BOTH files -- i.e. all five originally audited unsanitised call sites.
REPRESENTATIVE_NODE_IDS = (
    'tests/unit/test_hybrid_gate.py::TestTheScriptAnswersTheQuestion::'
    'test_non_browser_changes_do_not[README.md]',
    'tests/unit/test_gate_covers_the_ui_backend.py::'
    'TestOnlyProvablyIrrelevantPathsSkip::test_these_skip[README.md]',
)


def _victim_repo(tmp_path):
    """A throwaway repo standing in for the developer's real checkout, with
    a real commit, a real HEAD left mid-work, and uncommitted work sitting
    in it -- the shape of the actual incidents this test is pinned against.
    """
    victim = tmp_path / 'victim'
    victim.mkdir()

    def git(*args):
        # sanitized_git_env(), because THIS helper builds the victim. Under a
        # real worktree push the parent pytest already carries the checkout's
        # GIT_DIR, which this inherits -- so without stripping it, the fixture
        # that exists to prove we do not corrupt the real repo would build its
        # victim INSIDE the real repo. The regression test would carry the bug
        # it tests for.
        return subprocess.run(
            ['git', *args], cwd=str(victim), check=True,
            capture_output=True, text=True, env=sanitized_git_env(),
        )

    git('init', '-q', '-b', 'main')
    git('config', 'user.email', 'victim@example.com')
    git('config', 'user.name', 'Victim')
    (victim / 'important.txt').write_text('do not touch\n')
    git('add', '-A')
    git('commit', '-qm', 'the only real commit')
    git('checkout', '-q', '-b', 'feature/in-progress')
    (victim / 'wip.txt').write_text('uncommitted intent\n')  # untracked on purpose

    return {'dir': victim, 'git_dir': victim / '.git'}


def _snapshot(victim):
    def git(*args):
        # Same reason as the builder above: a snapshot taken through an
        # ambient GIT_DIR would describe the wrong repository, so the
        # before/after comparison could pass while the victim was mangled.
        return subprocess.run(
            ['git', *args], cwd=str(victim['dir']),
            capture_output=True, text=True, env=sanitized_git_env(),
        ).stdout.strip()

    return {
        'head_sha': git('rev-parse', 'HEAD'),
        'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
        'bare': git('config', '--get', 'core.bare'),
        'branches': sorted(git('branch', '--format=%(refname:short)').split()),
        'wip_exists': (victim['dir'] / 'wip.txt').exists(),
    }


def test_the_real_fixtures_survive_a_poisoned_ambient_GIT_DIR(tmp_path):
    victim = _victim_repo(tmp_path)
    before = _snapshot(victim)

    # This is what git hands a hook subprocess launched from a worktree --
    # simulated directly rather than via a real `git worktree add`, because
    # setting GIT_DIR by hand on the child process reproduces exactly what
    # git itself does; no worktree is needed to prove the defect.
    poisoned_env = os.environ.copy()
    poisoned_env['GIT_DIR'] = str(victim['git_dir'])

    result = subprocess.run(
        [sys.executable, '-B', '-m', 'pytest', *REPRESENTATIVE_NODE_IDS, '-q'],
        cwd=str(REPO), capture_output=True, text=True, env=poisoned_env,
    )

    after = _snapshot(victim)

    assert result.returncode == 0, (
        'the fixtures themselves failed under a poisoned ambient GIT_DIR '
        '(rather than corrupting the victim, which is checked separately) '
        'stdout=%s stderr=%s' % (result.stdout, result.stderr)
    )
    assert after['head_sha'] == before['head_sha'], (
        'the victim repository gained commits it never made'
    )
    assert after['branch'] == before['branch'], (
        'the victim repository HEAD moved onto a fixture branch'
    )
    assert after['bare'] == before['bare'], (
        "core.bare flipped on the real repository -- this is the flip that "
        "broke the working tree in the real incident"
    )
    assert after['branches'] == before['branches'], (
        'fixture branches leaked into the victim repository'
    )
    assert after['wip_exists'], 'uncommitted work in the victim disappeared'


def test_no_test_file_invokes_git_without_sanitizing_the_environment():
    """The guard that makes the fix survive the next contributor.

    The original fix audited two files and sanitised every git call in both.
    That was true and insufficient: review then found the SAME pattern in
    `test_check_test_traps.py` (12 sites), `test_mutation_changed.py`,
    `test_gitleaks_config.py` -- and, worst of all, in the victim fixture of
    THIS file, so the regression test for the corruption bug was itself
    carrying the corruption bug.

    A prose rule ("remember to pass env=") could not have caught that, because
    forgetting is exactly the failure mode. This scans the tree instead, so a
    new unsanitised call site fails by name at the next `make verify` rather
    than the next time somebody pushes from a worktree.

    Deliberately a source scan, not a runtime check: the damage happens inside
    a subprocess in a test that may not run on this machine, so the only place
    to catch it reliably is the source.

    Deliberately AST, not a regex. The first version of this guard WAS a
    regex, and it reported five false positives on calls that were correctly
    sanitised -- because `[^)]*?` stops at the first `)`, and
    `cwd=str(tmp_path)` closes the match before `env=` is ever reached. A
    guard that cries wolf on correct code gets deleted by the next person in a
    hurry, which is worse than not having it.

    ALIASES ARE RESOLVED PER FILE, and that is not a refinement. The second
    version matched only `subprocess.run`, while `test_hybrid_gate.py` -- the
    file the original incident happened in -- does `import subprocess as sp`
    inside nearly every test method and calls `sp.run(...)`. Seventeen of its
    twenty git calls were invisible to the guard. They happened to be
    correctly sanitised already, so nothing was leaking; the defect was that
    the guard's COVERAGE did not match its claim, which is the same
    looks-like-protection shape it exists to prevent.
    """
    tests_dir = Path(__file__).parent
    offenders = []

    def subprocess_aliases(tree):
        """Every local name bound to the `subprocess` module in this file,
        including imports nested inside functions and methods."""
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'subprocess':
                        names.add(alias.asname or 'subprocess')
        return names

    for path in sorted(tests_dir.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        aliases = subprocess_aliases(tree)
        if not aliases:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute)
                    and func.attr in ('run', 'check_output', 'check_call', 'call', 'Popen')):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id in aliases):
                continue
            if not node.args:
                continue
            argv = node.args[0]
            if not (isinstance(argv, ast.List) and argv.elts):
                continue
            first = argv.elts[0]
            if not (isinstance(first, ast.Constant) and first.value == 'git'):
                continue
            if any(kw.arg == 'env' for kw in node.keywords):
                continue
            offenders.append('%s:%d' % (path.relative_to(tests_dir), node.lineno))

    assert not offenders, (
        'these git subprocess calls pass no env=, so an ambient GIT_DIR (which '
        'git exports into pre-push hooks launched from a worktree) makes them '
        'operate on the REAL repository instead of their cwd -- `git init` in a '
        'tmp dir silently re-inits the repo GIT_DIR names. Pass '
        'env=sanitized_git_env():\n  ' + '\n  '.join(offenders)
    )
