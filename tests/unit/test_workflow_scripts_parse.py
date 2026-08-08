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


#: Globals the workflow runtime does NOT provide. It is a sandbox, not Node:
#: `agent`, `parallel`, `pipeline`, `log`, `phase`, `args`, `budget` and
#: `workflow` exist; the Node standard library does not.
#:
#: This is not hypothetical. `review-cycle.js` shipped
#:
#:     const MAIN_REPO = process.cwd()
#:
#: written to replace a hardcoded contributor path -- a correct intent with an
#: unavailable mechanism. It PARSED fine, so the parse test above passed it, and
#: the failure only appeared when the mandated review gate was actually invoked:
#:
#:     Error: process is not defined  at workflow.js:9:26
#:
#: A syntax check cannot see an undefined global. This can, and it costs one
#: grep rather than a broken gate discovered at the moment it was needed.
FORBIDDEN_GLOBALS = ('process.', 'require(', '__dirname', '__filename',
                     'globalThis.process')


def _strip_line_comment(line: str) -> str:
    """Drop a `//` comment, but only one that is not inside a string.

    `line.split('//', 1)[0]` truncates at the FIRST `//` wherever it appears --
    including inside a string literal. A URL is the obvious case, and
    `.claude/workflows/review-cycle.js` carries several `https://` strings, so
    a forbidden global appearing after one on the same line would have been
    sliced away and the check would pass a script it should reject.

    That is the same "comment stripping that ignores quotes" bug class
    `scripts/check_test_traps.py` is explicitly guarded against for shell
    comments; this checker had not been given the equivalent treatment.
    """
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == '\\':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ('"', "'", '`'):
            quote = ch
        elif ch == '/' and line[i + 1:i + 2] == '/':
            return line[:i]
        i += 1
    return line


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_the_workflow_script_uses_no_node_only_globals(script):
    text = script.read_text(encoding='utf-8')
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        code = _strip_line_comment(line)
        if code.lstrip().startswith(('*', '#:')):
            continue
        for bad in FORBIDDEN_GLOBALS:
            if bad in code:
                hits.append('%d: %s  (uses %s)' % (lineno, line.strip(), bad))

    assert not hits, (
        '%s uses globals the workflow runtime does not provide:\n  %s\n\n'
        'The runtime is a sandbox: agent/parallel/pipeline/log/phase/args/'
        'budget/workflow exist, the Node standard library does not. This '
        'PARSES, so the parse test cannot catch it -- it fails only when the '
        'workflow is invoked, which for the review cycle means at the moment '
        'the gate is needed. Resolve paths inside an agent (which runs in a '
        'real shell) instead: `git rev-parse --git-common-dir` works from a '
        'worktree as well as the main checkout.'
        % (script.name, '\n  '.join(hits))
    )


class TestTheCommentStripperRespectsQuotes:
    """The stripper is the thing that decides what the guard above SEES."""

    def test_a_url_does_not_hide_a_later_global(self):
        line = "const doc = 'https://example.com/x'; const p = process.cwd()"

        assert 'process.' in _strip_line_comment(line), (
            'the `//` inside a URL truncated the line, so a forbidden global '
            'after it was invisible to the check')

    def test_a_real_comment_is_still_stripped(self):
        """The counterweight: a stripper that strips nothing is no better."""
        assert 'process.' not in _strip_line_comment('const a = 1  // process.cwd()')

    def test_an_escaped_quote_does_not_unbalance_it(self):
        line = "const s = 'it\\'s fine'  // process.cwd()"

        assert 'process.' not in _strip_line_comment(line), line
