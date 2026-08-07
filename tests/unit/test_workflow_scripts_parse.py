"""The repo's workflow scripts must parse in the mode the runtime loads them.

`.claude/workflows/*.js` are the multi-lens plan and review cycles. A repo-local
copy WINS over the user-level one on name collision, so a broken copy here does
not fail loudly -- it silently takes the mandated review gate offline or falls
back to a global copy that lacks every fix made in this repo.

That is not hypothetical. This branch committed:

    const ARCH_FILES = ['a.py', 'b.py', 'c.py'  // NOT core/api.py -- ..., 'd.py']

A `//` inside an array literal swallows the rest of the PHYSICAL LINE, closing
bracket included, so the array ran on into the next declaration.

It shipped because the check used to approve it was run in the wrong mode:

    node --check review-cycle.js    -> exit 0
    node --check review-cycle.mjs   -> SyntaxError: Unexpected token 'const'

The file carries `export const meta`, so the runtime loads it as an ES module.
`node --check` on a `.js` extension parses as a script and accepted it. A green
check in the wrong environment is exactly the false-green shape CLAUDE.md §11
warns about, and it took a multi-lens review to catch what the check had blessed.

So this asserts the runtime's OWN shape: `export const meta` stripped (the
runtime reads it separately), the remainder wrapped in an async function
(top-level `return` and `await` are legal there and only there).
"""
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO / '.claude' / 'workflows'

SCRIPTS = sorted(WORKFLOW_DIR.glob('*.js')) if WORKFLOW_DIR.is_dir() else []


def _as_runtime_module(source: str) -> str:
    """Reshape a workflow script the way the runtime does before executing it."""
    body = re.sub(r'^export\s+const\s+meta\s*=\s*\{.*?\n\}\s*$', '', source,
                  flags=re.S | re.M)
    return 'async function __main(){\n' + body + '\n}\n'


def _node_check(module_source: str, tmp_path: Path):
    """Return (ok, stderr). Uses a .mjs extension so node parses as ESM."""
    probe = tmp_path / 'probe.mjs'
    probe.write_text(module_source, encoding='utf-8')
    result = subprocess.run(['node', '--check', str(probe)],
                            capture_output=True, text=True)
    return result.returncode == 0, result.stderr


pytestmark = pytest.mark.skipif(
    shutil.which('node') is None, reason='node is not installed'
)


def test_there_are_workflow_scripts_to_check():
    """Anti-vacuity: a parametrised test over an empty list passes silently."""
    assert SCRIPTS, (
        'no .claude/workflows/*.js found. If the repo-local copies were removed '
        'deliberately, delete this test with them; otherwise the parametrised '
        'test below is passing over an empty list.'
    )


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_the_workflow_script_parses_as_the_runtime_loads_it(script, tmp_path):
    ok, stderr = _node_check(_as_runtime_module(script.read_text(encoding='utf-8')),
                             tmp_path)
    assert ok, (
        '%s does not parse as an ES module.\n\n%s\n'
        'A repo-local workflow copy WINS over the user-level one, so this does '
        'not fail loudly -- it takes the review gate offline or silently falls '
        'back to a copy without this repo\'s fixes.\n\n'
        'NOTE: `node --check <file>.js` is NOT a valid check here. These files '
        'carry `export const meta`, so the runtime loads them as ES modules; '
        'the .js extension makes node parse as a script and accept code the '
        'runtime rejects. That is how the bug this test exists for shipped.'
        % (script.name, stderr.strip())
    )


def test_the_check_rejects_a_comment_that_eats_a_closing_bracket(tmp_path):
    """Prove the guard fails for the exact defect it was written for.

    A parse check that cannot fail is worse than none: it certifies whatever it
    is pointed at. This reproduces the shipped line rather than a generic
    syntax error, so the test is pinned to the real failure mode.
    """
    broken = textwrap.dedent("""\
        const ARCH_FILES = ['a.py', 'b.py'  // swallows the bracket, 'c.py']
        const OPS_GLOBS = ['Dockerfile']
        return { ok: true }
    """)
    ok, stderr = _node_check(_as_runtime_module(broken), tmp_path)

    assert not ok, 'the guard accepted an array literal with an unterminated bracket'
    assert 'const' in stderr, (
        'expected node to point at the following declaration; got: %s' % stderr
    )


def test_the_check_accepts_top_level_return_and_await(tmp_path):
    """The wrapper must model the runtime, not merely be strict.

    Workflow scripts legitimately use top-level `return` and `await` because the
    runtime executes them inside an async function. A check that rejected those
    would fail every valid script, and the natural "fix" would be to weaken the
    check until it passed -- back to the mode that accepted the broken file.
    """
    valid = textwrap.dedent("""\
        const x = await Promise.resolve(1)
        if (!x) return { report: 'nothing to do' }
        return { x }
    """)
    ok, stderr = _node_check(_as_runtime_module(valid), tmp_path)

    assert ok, 'the guard rejected valid workflow-script shape: %s' % stderr
