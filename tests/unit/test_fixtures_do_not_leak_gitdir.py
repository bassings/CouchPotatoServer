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
from tests.unit.conftest import assert_git_dir_is, sanitized_git_env
import sys
from pathlib import Path
import ast
import pytest
import tempfile

REPO = Path(__file__).resolve().parents[2]

# Between them, exercises the repo fixture + classify()/needs_e2e.sh call in
# BOTH files -- i.e. TWO REPRESENTATIVE tests, one per fixture file.
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
        # Generous, but bounded: an inner pytest that deadlocks on a fixture
        # would otherwise hang the whole gate with no diagnosis, which is a
        # worse failure than a red test.
        timeout=600,
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

    KNOWN LIMIT, stated rather than implied. This matches CALL SHAPES, so it
    cannot see argv assembled elsewhere -- an `*args`-forwarding wrapper such
    as `run = lambda *a: subprocess.run(a, ...)` in
    `test_next_beta_version.py` passes it cleanly while invoking git. Chasing
    every wrapper, alias and lambda is a losing game: each is a new spelling,
    and this guard was wrong four times learning that.

    Which is why it is NO LONGER the primary protection. `tests/conftest.py`
    strips git's location variables from `os.environ` for the whole process
    before collection, so every subprocess is clean by construction whatever
    shape the call takes. This guard is defence in depth over that, and its
    blind spots are survivable because of it. Revisit if the scrub is ever
    removed, and prove any change by PLANTING an offender rather than reading
    the code -- every defect in this guard was found that way and none by
    inspection.

    ALIASES ARE RESOLVED PER FILE, and that is not a refinement. The second
    version matched only `subprocess.run`, while `test_hybrid_gate.py` -- the
    file the original incident happened in -- does `import subprocess as sp`
    inside nearly every test method and calls `sp.run(...)`. Seventeen of its
    twenty git calls were invisible to the guard. They happened to be
    correctly sanitised already, so nothing was leaking; the defect was that
    the guard's COVERAGE did not match its claim, which is the same
    looks-like-protection shape it exists to prevent.
    """
    # tests/ ROOT, not tests/unit: a git call added under integration/,
    # e2e/ or directly in tests/ would otherwise go unscanned. None exist
    # today -- this is preventive, and cheap enough that waiting for the
    # first one would be the wrong trade.
    tests_dir = Path(__file__).parents[1]
    offenders = []

    def _is_sanitized(node):
        """`env=` must be a DIRECT `sanitized_git_env(...)` call.

        Deliberately no dataflow. The previous version tracked names bound
        from the sanitiser so `env = sanitized_git_env()` then `env=env` would
        be recognised -- 43 lines that produced three of this guard's five
        defects, ending with binding names file-wide rather than per scope, so
        one function's clean `env` vouched for another function's dirty one.

        Requiring the call inline removes that entire class by construction
        instead of patching its fifth instance. The cost is a real one and
        worth stating: a future caller wanting to reuse one env across several
        calls gets flagged and has to inline. That is a visible, actionable
        message rather than a silent wrong answer, which is the right way for
        this to fail given its record.
        """
        if isinstance(node, ast.IfExp):
            # `sanitized_git_env() if env is None else env` -- a helper with a
            # deliberate caller override. Accepted as a SYNTACTIC form, not by
            # tracking what the other branch holds: the shape is visible in one
            # node, so unlike name binding it cannot pick up a value from
            # somewhere else in the file.
            return _is_sanitized(node.body) or _is_sanitized(node.orelse)
        return (isinstance(node, ast.Call)
                and ((isinstance(node.func, ast.Name)
                      and node.func.id == 'sanitized_git_env')
                     or (isinstance(node.func, ast.Attribute)
                         and node.func.attr == 'sanitized_git_env')))

    SPAWNERS = ('run', 'check_output', 'check_call', 'call', 'Popen')

    def subprocess_bindings(tree):
        """Names bound to the `subprocess` MODULE, and names bound directly to
        its spawning FUNCTIONS.

        Both forms, because tracking only the module import made
        `from subprocess import run` skip the ENTIRE file: `aliases` came back
        empty and the early `continue` fired before a single call was
        examined. Missing one call shape is a gap; silently declining to scan
        a whole file is the guard reporting CLEAN on code it never read, which
        is the failure this whole exercise is about.

        Covers imports nested inside functions and methods too, which is how
        the file the original incident happened in writes them.
        """
        modules, funcs = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'subprocess':
                        modules.add(alias.asname or 'subprocess')
            elif isinstance(node, ast.ImportFrom) and node.module == 'subprocess':
                for alias in node.names:
                    if alias.name in SPAWNERS:
                        funcs.add(alias.asname or alias.name)
        return modules, funcs

    for path in sorted(tests_dir.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        modules, funcs = subprocess_bindings(tree)
        if not modules and not funcs:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr not in SPAWNERS:
                    continue
                if not (isinstance(func.value, ast.Name) and func.value.id in modules):
                    continue
            elif isinstance(func, ast.Name):
                if func.id not in funcs:
                    continue
            else:
                continue
            if not node.args:
                continue
            argv = node.args[0]
            if not (isinstance(argv, ast.List) and argv.elts):
                continue
            first = argv.elts[0]
            if not (isinstance(first, ast.Constant) and first.value == 'git'):
                continue
            env_kw = next((kw for kw in node.keywords if kw.arg == 'env'), None)
            if env_kw is not None and _is_sanitized(env_kw.value):
                continue
            if env_kw is not None:
                offenders.append('%s:%d (env= is not sanitized_git_env())'
                                 % (path.relative_to(tests_dir), node.lineno))
                continue
            offenders.append('%s:%d' % (path.relative_to(tests_dir), node.lineno))

    assert not offenders, (
        'these git subprocess calls pass no env=, so an ambient GIT_DIR (which '
        'git exports into pre-push hooks launched from a worktree) makes them '
        'operate on the REAL repository instead of their cwd -- `git init` in a '
        'tmp dir silently re-inits the repo GIT_DIR names. Pass '
        'env=sanitized_git_env():\n  ' + '\n  '.join(offenders)
    )


class TestTheContainmentAssertionIsItselfGuarded:
    """Isolates the SECOND layer, which was previously untested.

    Measured before this class existed: deleting the containment assertion
    from both `repo` fixtures left 49 tests passing, because the per-call
    `sanitized_git_env()` already kept every path clean. Deleting the
    sanitisation instead failed one test. So the two layers were not two
    proven layers -- one was proven and the other was decoration that happened
    to be correct.

    Defence in depth and an untested second layer are indistinguishable from a
    green run. These tests drive the assertion DIRECTLY, with the first layer
    deliberately bypassed, so each layer now fails on its own removal.
    """

    def test_it_rejects_a_git_dir_outside_the_directory(self, tmp_path):
        """The case it exists for, driven with sanitisation bypassed: an
        ambient GIT_DIR pointing at another repo, and no `.git` ever created
        in tmp_path."""
        victim = tmp_path / 'victim'
        victim.mkdir()
        subprocess.run(
            ['git', 'init', '-q', str(victim)], check=True,
            capture_output=True, env=sanitized_git_env(),
        )
        target = tmp_path / 'throwaway'
        target.mkdir()

        poisoned = os.environ.copy()
        poisoned['GIT_DIR'] = str(victim / '.git')

        with pytest.raises(AssertionError) as excinfo:
            assert_git_dir_is(target, env=poisoned)

        message = str(excinfo.value)
        assert 'refusing to continue' in message, (
            'the assertion fired but not with its named, actionable message; '
            'got: %s' % message
        )
        assert str(victim) in message, (
            'the message must name WHERE git actually pointed, or the reader '
            'cannot tell which repository was about to be written to'
        )
        # And specifically NOT an OSError from resolving a `.git` that was
        # never created -- the failure mode this helper is shaped to avoid.
        assert not (target / '.git').exists()

    def test_it_accepts_a_git_dir_inside_the_directory(self, tmp_path):
        """The other direction, so the assertion cannot be satisfied by
        rejecting everything."""
        subprocess.run(
            ['git', 'init', '-q'], cwd=str(tmp_path), check=True,
            capture_output=True, env=sanitized_git_env(),
        )
        assert_git_dir_is(tmp_path)


def test_the_process_scrub_protects_a_file_that_never_heard_of_the_helper():
    """Isolates the SCRUB layer, the one that actually closes the class.

    The per-call `sanitized_git_env()` only protects call sites that remember
    to use it, and an AST guard policing that was wrong four times: aliased
    imports, a subdirectory, accepting any `env=` whatever it contained, and
    argv built by an `*args`-forwarding lambda. Every wrapper and alias is a
    new spelling, so shape-matching is a losing game.

    `tests/conftest.py` therefore strips git's location variables from
    `os.environ` once, for the whole process, before anything is collected.
    After that every subprocess inherits a clean environment by construction.

    This test drives that specifically: it runs `test_next_beta_version.py`,
    which builds a repo with a bare `*args` lambda and passes NO `env=`
    anywhere, under an ambient GIT_DIR pointing at a throwaway victim. Only
    the scrub can save it -- the helper is never imported there. If the victim
    survives, the scrub is doing the work.
    """
    with tempfile.TemporaryDirectory() as tmp:
        victim = Path(tmp) / 'victim'
        victim.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(victim)],
                       check=True, capture_output=True, env=sanitized_git_env())
        (victim / 'f.txt').write_text('original\n')
        for args in (('add', '-A'), ('-c', 'user.email=t@e.com', '-c', 'user.name=T',
                                     'commit', '-qm', 'seed')):
            subprocess.run(['git', *args], cwd=str(victim), check=True,
                           capture_output=True, env=sanitized_git_env())
        before = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(victim),
                                capture_output=True, text=True,
                                env=sanitized_git_env()).stdout.strip()

        poisoned = os.environ.copy()
        poisoned['GIT_DIR'] = str(victim / '.git')
        result = subprocess.run(
            [sys.executable, '-B', '-m', 'pytest',
             'tests/unit/test_next_beta_version.py', '-q'],
            cwd=str(REPO), capture_output=True, text=True, env=poisoned,
            timeout=600,
        )

        after = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(victim),
                               capture_output=True, text=True,
                               env=sanitized_git_env()).stdout.strip()
        branch = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=str(victim),
                                capture_output=True, text=True,
                                env=sanitized_git_env()).stdout.strip()
        bare = subprocess.run(['git', 'config', '--get', 'core.bare'], cwd=str(victim),
                              capture_output=True, text=True,
                              env=sanitized_git_env()).stdout.strip()

    assert result.returncode == 0, (
        'the unsanitised suite failed under a poisoned GIT_DIR:\n%s' % result.stdout[-2000:]
    )
    assert after == before, 'the victim HEAD moved -- the scrub did not protect it'
    assert branch == 'main', 'the victim branch changed -- the scrub did not protect it'
    assert bare == 'false', 'core.bare flipped on the victim -- the exact 2026-08-18 damage'
