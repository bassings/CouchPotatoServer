"""Tests for scripts/check_test_traps.py — the false-green guard.

This checker exists because the expensive failures on this repo have not been
red tests; they have been *green* ones. It mechanises three ways a suite can
report success while guarding nothing:

  1. **jsdom has no layout.** `getBoundingClientRect()`, `offsetHeight`,
     `scrollHeight` and friends all read 0 under the vitest jsdom environment
     no matter what a browser would render, so `expect(a).toBe(b)` on two of
     them passes as `0 === 0`. Only a same-file stub makes such a read
     meaningful.
  2. **Pipes eat exit codes.** `pytest ... | tail` reports the exit status of
     `tail`, which is 0 essentially always. Without `pipefail` a failing suite
     looks like a passing one — this has actually happened here when piping
     Playwright output.
  3. **`set -e` alone is not enough.** A shell gate missing `-u`, or missing
     `pipefail` while containing a pipeline, silently continues past a typo'd
     variable or a failed pipeline stage.
  4. **A git hook that is not executable** is silently ignored by git, so the
     gate it implements never runs at all.

The tests below drive the checker over synthetic files (so each rule is pinned
independently of the current tree) and also assert it is clean on the real tree,
which is what makes it usable as a blocking gate.
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check_test_traps.py"

# AC-QA-74: pytest cases needing `node` skip visibly rather than going red,
# so scripts/test-local.sh's node-less Alpine container stays clean.
# Resolved ONCE at import. A live `shutil.which` call is unsafe here: the
# missing-node tests monkeypatch the shared `shutil` module object, so a
# later call would see their patch and skip the very test doing the patching.
_NODE_ON_THIS_MACHINE = shutil.which("node") is not None

requires_node = pytest.mark.skipif(
    not _NODE_ON_THIS_MACHINE,
    reason="node is not installed; required for check_test_traps' template "
    "inline-script rule (CI-003 Part B, AC-QA-74).",
)

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_test_traps  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rule6_guard_corpus import SHAPES as RULE6_SHAPES  # noqa: E402


def run_checker(*args):
    """Run the checker as a subprocess, the way CI and verify.sh invoke it."""
    return subprocess.run(
        [sys.executable, str(CHECKER), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def findings_for(path: Path):
    """Run the checker over one file.

    Skips, visibly, when the file would reach rule 8 and this machine has no
    `node`. Tagging the ~15 affected tests with `@requires_node` individually
    was the obvious fix and the wrong one: the next html test added without the
    decorator silently reintroduces the problem, and this file grows. Verified
    by removing node from PATH — 12 tests failed before this guard, 0 after,
    which is what `scripts/test-local.sh` (Alpine, no node) would have hit.

    Keyed on `_NODE_ON_THIS_MACHINE`, resolved ONCE at import, not on a live
    `shutil.which` call. `monkeypatch.setattr(check_test_traps.shutil, "which",
    ...)` patches the shared `shutil` MODULE object, so a live call here sees
    the patch too — which made `test_missing_node_is_a_hard_named_failure`
    silently SKIP instead of asserting. Caught by running with `-rs` and
    reading a "node is not installed" skip on a machine that has node.
    """
    if path.suffix == ".html" and not _NODE_ON_THIS_MACHINE:
        pytest.skip("node is not installed; rule 8 cannot parse template scripts here")
    return list(check_test_traps.check_file(path))


def messages_for(path: Path):
    return [msg for _line, msg in findings_for(path)]


# ── Rule 1: jsdom layout-zero reads ─────────────────────────────────────────


def test_flags_unstubbed_geometry_read_in_a_vitest_spec(tmp_path):
    spec = tmp_path / "widget.spec.ts"
    spec.write_text(
        "import { it, expect } from 'vitest';\n"
        "it('scrolls to the bottom', () => {\n"
        "  const el = document.createElement('div');\n"
        "  expect(el.scrollTop).toBe(el.scrollHeight);\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    line_no, message = findings[0]
    assert line_no == 4
    assert "scrollHeight" in message
    assert "jsdom" in message.lower()


def test_flags_get_bounding_client_rect_and_computed_style(tmp_path):
    spec = tmp_path / "layout.spec.ts"
    spec.write_text(
        "it('measures', () => {\n"
        "  const r = document.body.getBoundingClientRect();\n"
        "  const s = window.getComputedStyle(document.body);\n"
        "  expect(r.width).toBeGreaterThanOrEqual(0);\n"
        "  expect(s.display).toBeDefined();\n"
        "});\n"
    )

    messages = messages_for(spec)
    assert any("getBoundingClientRect" in m for m in messages)
    assert any("getComputedStyle" in m for m in messages)


def test_does_not_flag_a_geometry_read_stubbed_via_define_property(tmp_path):
    """A file that stubs the property has already confronted the blind spot."""
    spec = tmp_path / "stubbed.spec.ts"
    spec.write_text(
        "beforeEach(() => {\n"
        "  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {\n"
        "    configurable: true, get: () => 400,\n"
        "  });\n"
        "});\n"
        "it('scrolls', () => {\n"
        "  const el = document.createElement('div');\n"
        "  expect(el.scrollHeight).toBe(400);\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_does_not_flag_a_geometry_read_stubbed_by_direct_assignment(tmp_path):
    spec = tmp_path / "assigned.spec.ts"
    spec.write_text(
        "Element.prototype.getBoundingClientRect = function () {\n"
        "  return { top: 0, left: 0, width: 100, height: 50 };\n"
        "};\n"
        "it('measures', () => {\n"
        "  expect(document.body.getBoundingClientRect().width).toBe(100);\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_stubbing_one_property_does_not_excuse_another(tmp_path):
    """The exemption is per-property — stubbing scrollHeight says nothing about offsetWidth."""
    spec = tmp_path / "partial.spec.ts"
    spec.write_text(
        "Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { get: () => 10 });\n"
        "it('mixes', () => {\n"
        "  expect(document.body.scrollHeight).toBe(10);\n"
        "  expect(document.body.offsetWidth).toBe(0);\n"
        "});\n"
    )

    messages = messages_for(spec)
    assert len(messages) == 1, messages
    assert "offsetWidth" in messages[0]


def test_playwright_e2e_specs_are_out_of_scope(tmp_path):
    """E2E runs in a real browser where geometry is real — the rule must not fire."""
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    spec = e2e_dir / "layout.spec.ts"
    spec.write_text(
        "test('has a visible header', async ({ page }) => {\n"
        "  const box = await page.locator('header').boundingBox();\n"
        "  const h = await page.evaluate(() => document.body.scrollHeight);\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_comments_are_not_flagged(tmp_path):
    spec = tmp_path / "commented.spec.ts"
    spec.write_text(
        "// jsdom returns 0 for scrollHeight, so we assert on the call instead\n"
        "/* offsetHeight is unusable here */\n"
        "it('works', () => { expect(1).toBe(1); });\n"
    )

    assert findings_for(spec) == []


# ── Rule 2: exit-code-eating pipes ──────────────────────────────────────────


def test_flags_pytest_piped_into_tail_without_pipefail(tmp_path):
    """`set -eu` is present, so the *only* remaining problem is the pipe itself.

    That isolation is deliberate: it pins the specific runner-pipe finding rather
    than catching the generic "missing strict options" message by accident.
    """
    script = tmp_path / "run.sh"
    script.write_text("#!/usr/bin/env bash\nset -eu\npytest tests/unit -q | tail -20\n")

    findings = findings_for(script)
    assert len(findings) == 1, findings
    line_no, message = findings[0]
    assert line_no == 3, "should point at the offending pipe, not the top of the file"
    assert "pipefail" in message
    assert "exit status" in message


def test_does_not_flag_a_pipe_when_the_script_sets_pipefail(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\npytest tests/unit -q | tail -20\n"
    )

    assert findings_for(script) == []


def test_flags_a_piped_runner_in_a_makefile_recipe(tmp_path):
    """Each Makefile recipe line is its own shell — pipefail is never in effect."""
    makefile = tmp_path / "Makefile"
    makefile.write_text("test-py:\n\tpytest tests/unit/ -q | tail -5\n")

    findings = findings_for(makefile)
    assert len(findings) == 1, findings
    assert "pipefail" in findings[0][1]


def test_flags_a_piped_runner_in_a_github_workflow_run_block(tmp_path):
    """GitHub's default shell is `bash -e` — no pipefail."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - name: Run tests\n"
        "      run: npx playwright test | tail -30\n"
    )

    findings = findings_for(workflow)
    assert len(findings) == 1, findings
    assert "pipefail" in findings[0][1]


def test_does_not_flag_a_workflow_run_block_that_sets_pipefail(tmp_path):
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - run: |\n"
        "        set -o pipefail\n"
        "        npx playwright test | tail -30\n"
    )

    assert findings_for(workflow) == []


def test_does_not_flag_a_non_runner_pipe_as_an_exit_code_eater(tmp_path):
    """Only test/verification commands get the runner-pipe finding.

    A plumbing pipe still earns the generic "this file has pipelines but no
    pipefail" note — that is intended — but it must not be reported as a
    swallowed *test* exit code, which is the actionable, false-green case.
    """
    script = tmp_path / "run.sh"
    script.write_text("#!/usr/bin/env bash\nset -eu\ncat foo.txt | sort | uniq > bar.txt\n")

    messages = messages_for(script)
    assert not any("test/verification command" in m for m in messages), messages


# ── Rule 3: shell gates missing set -euo pipefail ───────────────────────────


def test_flags_a_shell_script_with_only_set_e(tmp_path):
    """`set -e` alone is not enough: -u and pipefail must both be demanded.

    Asserts on the named OPTIONS rather than on the advice sentence, so it cannot
    be satisfied by remediation wording alone.
    """
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/bash\nset -e\nls | wc -l\npytest tests/unit\n")

    findings = findings_for(script)
    assert len(findings) == 1, findings
    message = findings[0][1]
    assert "-u (error on unset variable)" in message
    assert "pipefail (a failing command in a pipeline is otherwise ignored)" in message


def test_does_not_demand_pipefail_from_a_script_with_no_pipelines(tmp_path):
    """pipefail is meaningless without a pipeline — don't manufacture busywork."""
    script = tmp_path / "simple.sh"
    script.write_text("#!/usr/bin/env bash\nset -eu\necho hello\nexit 0\n")

    assert findings_for(script) == []


def test_accepts_set_euo_pipefail_in_any_order(tmp_path):
    """Each body contains a runner pipe, so the pipefail half is actually exercised.

    Without a pipeline `PIPEFAIL_RE` is never consulted and this test passes with
    pipefail detection entirely broken (confirmed by mutation).
    """
    for body in (
        "#!/usr/bin/env bash\nset -euo pipefail\npytest tests/ | tail -5\n",
        "#!/usr/bin/env bash\nset -eu\nset -o pipefail\npytest tests/ | tail -5\n",
        "#!/usr/bin/env bash\nset -eu -o pipefail\npytest tests/ | tail -5\n",
    ):
        script = tmp_path / "s.sh"
        script.write_text(body)
        assert findings_for(script) == [], body


# ── Rule 7: unquoted `>`/`>=` on a `pip install` line ───────────────────────
#
# T1.5's actual bug: `.github/workflows/ci.yml` had `run: pip install
# ruff>=0.9.0` — an unquoted `>` is shell stdout redirection, not a version
# constraint, so the shell parses it as `pip install ruff` (floating latest)
# with stdout written to a file literally named `=0.9.0`. This rule is what
# would have caught that automatically instead of three lenses finding it by
# hand during planning.


def test_flags_unquoted_pip_install_version_redirect(tmp_path):
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "    - name: Install ruff\n"
        "      run: pip install ruff>=0.9.0\n"
    )

    findings = findings_for(workflow)
    assert len(findings) == 1, findings
    line_no, message = findings[0]
    assert line_no == 5
    assert "redirect" in message.lower() or ">=" in message


def test_does_not_flag_a_correctly_quoted_pip_install_requirement(tmp_path):
    """`'pyyaml>=6.0'` is quoted, so the `>` is literal text passed to pip."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "    - name: Install pyyaml\n"
        "      run: pip install 'pyyaml>=6.0'\n"
    )

    assert findings_for(workflow) == []


def test_does_not_flag_a_legitimate_redirect_that_is_not_a_pip_install(tmp_path):
    """A real `>` redirect on a non-pip-install line is not this rule's business."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "    - name: Log output\n"
        "      run: echo x > file\n"
    )

    assert findings_for(workflow) == []


def test_flags_both_real_broken_lines_from_ci_yml(tmp_path):
    """Regression pin for the actual T1.5 bug: both floating installs, in one
    synthetic workflow shaped like the real ci.yml, are caught — two findings,
    not one, and not silently deduped or short-circuited after the first.
    """
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "    - name: Install ruff\n"
        "      run: pip install ruff>=0.9.0\n"
        "  security-lint:\n"
        "    steps:\n"
        "    - name: Install ruff\n"
        "      run: pip install ruff>=0.15.16\n"
    )

    findings = findings_for(workflow)
    assert len(findings) == 2, findings
    line_nos = {line_no for line_no, _msg in findings}
    assert line_nos == {5, 9}, findings


def test_pip3_install_is_also_covered(tmp_path):
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "    - run: pip3 install ruff>=0.9.0\n"
    )

    assert len(findings_for(workflow)) == 1


def test_unquoted_pip_install_redirect_is_flagged_even_when_pipefail_is_set(tmp_path):
    """Rule 7 has nothing to do with pipefail — it must not be hidden behind
    rule 2/3's `if pipefail: continue` early exit."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "    - run: |\n"
        "        set -o pipefail\n"
        "        pip install ruff>=0.9.0\n"
    )

    findings = findings_for(workflow)
    assert len(findings) == 1, findings


# ── Regressions: bugs found in review of this very guard ────────────────────


def test_the_word_pipefail_in_a_comment_does_not_count_as_setting_it(tmp_path):
    """The guard's own false green: `_has_pipefail` used to search raw text.

    A script that merely *mentions* pipefail in a TODO passed the gate while
    `pytest | tail` silently swallowed the exit code — the exact defect class
    this script exists to catch, inside the script.
    """
    script = tmp_path / "gate.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# TODO: this really ought to use set -o pipefail one day\n"
        "set -eu\n"
        "pytest tests/unit/ -q | tail -20\n"
    )

    messages = messages_for(script)
    assert len(messages) == 1, messages
    assert "exit status" in messages[0]


def test_a_commented_pipefail_in_a_workflow_run_block_does_not_count(tmp_path):
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - run: |\n"
        "        # NOTE: remember set -o pipefail if you add a pipe here\n"
        "        pytest tests/ | tail -20\n"
    )

    assert len(findings_for(workflow)) == 1, findings_for(workflow)


def test_flags_a_backslash_continued_runner_pipe_in_a_workflow(tmp_path):
    """A continuation split the runner from its filter across physical lines."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - run: |\n"
        "        pytest tests/ \\\n"
        "          | tail -20\n"
    )

    findings = findings_for(workflow)
    assert len(findings) == 1, findings
    assert findings[0][0] == 5, "should report the line the command starts on"


def test_flags_a_backslash_continued_runner_pipe_in_a_shell_script(tmp_path):
    script = tmp_path / "gate.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -eu\npytest tests/unit \\\n  -q | tail -20\n"
    )

    findings = findings_for(script)
    assert len(findings) == 1, findings
    assert findings[0][0] == 3


def test_flags_a_multiline_run_block_that_must_be_caught(tmp_path):
    """The `run: |` form is what this repo's workflows actually use.

    Its collection branch was previously deletable with no red test.
    """
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - name: Unit\n"
        "      run: |\n"
        "        echo starting\n"
        "        npx playwright test | tail -30\n"
        "        echo done\n"
    )

    findings = findings_for(workflow)
    assert len(findings) == 1, findings
    assert findings[0][0] == 7


def test_pipefail_in_one_step_does_not_excuse_a_later_step(tmp_path):
    """Per-block state: the second step is a different shell."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - run: |\n"
        "        set -o pipefail\n"
        "        pytest tests/a | tail -5\n"
        "    - run: |\n"
        "        pytest tests/b | tail -5\n"
    )

    findings = findings_for(workflow)
    assert len(findings) == 1, findings
    assert findings[0][0] == 8, "only the second step should be flagged"


@pytest.mark.parametrize("indicator", ["|", "|-", "|+", ">", ">-", "|2"])
def test_all_yaml_block_scalar_indicators_are_scanned(tmp_path, indicator):
    """`run: |2` and `run: |+` used to skip the whole block silently."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        f"    - run: {indicator}\n"
        "        pytest tests/ | tail -20\n"
    )

    assert len(findings_for(workflow)) == 1, f"indicator {indicator!r} skipped the block"


def test_explicit_shell_bash_is_not_flagged(tmp_path):
    """GitHub's `shell: bash` IS `bash --noprofile --norc -eo pipefail`.

    Flagging it makes a blocking gate reject correct configuration.
    """
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - shell: bash\n"
        "      run: |\n"
        "        pytest tests/ | tail -20\n"
    )

    assert findings_for(workflow) == []


def test_defaults_run_shell_bash_is_not_flagged(tmp_path):
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "defaults:\n"
        "  run:\n"
        "    shell: bash\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - run: |\n"
        "        pytest tests/ | tail -20\n"
    )

    assert findings_for(workflow) == []


def test_default_shell_without_an_explicit_declaration_is_still_flagged(tmp_path):
    """`shell: sh` is `sh -e` — no pipefail — so it must still be caught."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - shell: sh\n"
        "      run: |\n"
        "        pytest tests/ | tail -20\n"
    )

    assert len(findings_for(workflow)) == 1


def test_non_shell_run_blocks_are_ignored(tmp_path):
    """`shell: python` is not a shell pipeline; the check does not apply."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "    - shell: python\n"
        "      run: |\n"
        "        print('pytest tests/ | tail -20')\n"
    )

    assert findings_for(workflow) == []


def test_an_unmatched_block_comment_open_inside_a_line_comment_does_not_blind_the_rule(tmp_path):
    """State-machine regression: a stray `/*` used to latch forever."""
    spec = tmp_path / "widget.spec.ts"
    spec.write_text(
        "// legacy note: the old code used /* the C-style form\n"
        "it('measures', () => {\n"
        "  expect(document.body.offsetHeight).toBe(0);\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert findings[0][0] == 3


def test_a_block_comment_marker_inside_a_string_does_not_blind_the_rule(tmp_path):
    spec = tmp_path / "widget.spec.ts"
    spec.write_text(
        "const GLOB = '/*';\n"
        "it('measures', () => {\n"
        "  expect(document.body.offsetHeight).toBe(0);\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1, findings_for(spec)


def test_a_url_in_a_string_does_not_hide_a_geometry_read_on_the_same_line(tmp_path):
    """`//` inside a quoted string is not a comment."""
    spec = tmp_path / "widget.spec.ts"
    spec.write_text(
        "it('measures', () => {\n"
        "  const u = 'http://localhost/'; expect(document.body.offsetHeight).toBe(0);\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert findings[0][0] == 2


def test_a_real_multiline_block_comment_is_still_ignored(tmp_path):
    spec = tmp_path / "widget.spec.ts"
    spec.write_text(
        "/*\n"
        " * offsetHeight and scrollHeight are unusable here.\n"
        " */\n"
        "it('works', () => { expect(1).toBe(1); });\n"
    )

    assert findings_for(spec) == []


def test_flags_a_non_executable_git_hook(tmp_path):
    """A hook that is not executable is silently ignored by git — the gate is inert.

    This was real: .githooks/pre-push was mode 0644 in the tree.
    """
    hooks = tmp_path / ".githooks"
    hooks.mkdir()
    hook = hooks / "pre-push"
    hook.write_text("#!/usr/bin/env bash\nset -euo pipefail\nmake verify\n")
    hook.chmod(0o644)

    messages = messages_for(hook)
    assert any("not executable" in m for m in messages), messages

    hook.chmod(0o755)
    assert messages_for(hook) == []


def test_the_repos_own_hooks_are_executable():
    """Guards the actual enforcement mechanism, not a fixture."""
    hooks_dir = REPO_ROOT / ".githooks"
    hooks = [p for p in hooks_dir.iterdir() if p.is_file()]
    assert hooks, "no hooks found — the pre-push gate would not exist"
    for hook in hooks:
        assert os.access(hook, os.X_OK), (
            f"{hook.name} is not executable, so git ignores it and the gate never runs"
        )


# ── Rule 5: orphaned test files ─────────────────────────────────────────────
#
# This rule exists because tests/integration/ sat orphaned in exactly this
# tree: pytest.ini's `testpaths = tests` technically "covered" it, but no
# runner invocation in scripts/verify.sh or .github/workflows/ci.yml ever
# passed it to pytest, so 31 tests never ran anywhere. A rule anchored on
# `testpaths` would have passed against that orphaned suite and is therefore
# vacuous: the tests below key on the runner invocations instead.


def test_flags_a_tracked_test_file_no_runner_executes():
    """A file under `tests/` (so testpaths 'covers' it) but under no runner
    root must still be flagged: this is the exact orphaning bug, reproduced.

    `runner_texts` mirrors the real shape: one entry PER RUNNER FILE
    (verify.sh, ci.yml), each of which invokes both roots: see
    `test_does_not_flag_a_file_under_an_executed_root` and the module
    docstring on `check_orphaned_test_files` for why this is per-file
    intersection, not a flat union of every invocation seen anywhere.
    """
    verify_sh_like = "pytest tests/unit/ -q\npytest tests/integration/ -v\n"
    ci_yml_like = "pytest tests/unit/ -v\npytest tests/integration/ -v\n"
    findings = list(
        check_test_traps.check_orphaned_test_files(
            tracked_files=["tests/orphaned_suite/test_thing.py"],
            runner_texts=[verify_sh_like, ci_yml_like],
        )
    )
    assert len(findings) == 1, findings
    path, line_no, message = findings[0]
    assert path == "tests/orphaned_suite/test_thing.py"
    assert line_no == 1
    assert "not executed" in message.lower() or "orphan" in message.lower()


def test_tracked_test_files_sees_both_pytest_naming_conventions(tmp_path):
    """`*_test.py` counts as a test file, not just `test_*.py`.

    Every other test in this section injects `tracked_files`, so none of
    them exercises the naming predicate that decides what lands in that
    list. The predicate is where this rule actually missed: three
    `*_test.py` files sat tracked under `couchpotato/`, outside `testpaths`
    and outside `pytest.ini`'s narrowed `python_files = test_*.py`, so
    nothing collected them and nothing flagged them. One had been failing
    since the Python 3 port and was hiding a live defect in the settings
    file browser. A rule that only knows the prefix calls that tree clean.

    Asserting the exact list, not membership, so it also pins what must NOT
    be swept in: a helper module and a conftest are not tests.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "pkg").mkdir()
    for name in ("test_prefix.py", "suffix_test.py", "helpers.py", "conftest.py"):
        (tmp_path / "pkg" / name).write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    assert check_test_traps._tracked_test_files(tmp_path) == [
        "pkg/suffix_test.py",
        "pkg/test_prefix.py",
    ]


def test_does_not_flag_a_file_under_an_executed_root():
    verify_sh_like = "pytest tests/unit/ -q\npytest tests/integration/ -v\n"
    ci_yml_like = "pytest tests/unit/ -v\npytest tests/integration/ -v\n"
    findings = list(
        check_test_traps.check_orphaned_test_files(
            tracked_files=["tests/integration/test_duplicate_detection.py"],
            runner_texts=[verify_sh_like, ci_yml_like],
        )
    )
    assert findings == []


def test_flags_a_file_dropped_from_one_runner_file_but_not_the_other():
    """Per-file intersection, not union: a suite still invoked by ci.yml but
    dropped from verify.sh (or vice versa) is still a real gap: the local
    gate would no longer mirror CI. This is exactly the mutation the guard
    must catch: deleting the tests/integration/ invocation from verify.sh
    alone, while ci.yml keeps it, must still be flagged.
    """
    verify_sh_like_after_mutation = "pytest tests/unit/ -q\n"  # integration line deleted
    ci_yml_like_unchanged = "pytest tests/unit/ -v\npytest tests/integration/ -v\n"
    findings = list(
        check_test_traps.check_orphaned_test_files(
            tracked_files=["tests/integration/test_duplicate_detection.py"],
            runner_texts=[verify_sh_like_after_mutation, ci_yml_like_unchanged],
        )
    )
    assert len(findings) == 1, findings
    assert findings[0][0] == "tests/integration/test_duplicate_detection.py"


def test_does_not_flag_an_exact_file_argument_match():
    findings = list(
        check_test_traps.check_orphaned_test_files(
            tracked_files=["tests/local/test_one_off.py"],
            runner_texts=["pytest tests/local/test_one_off.py -q"],
        )
    )
    assert findings == []


def test_allowlist_exempts_only_the_named_file_not_its_whole_directory():
    """The exemption must be exact, not a directory shadow.

    A sibling file in the same directory as an allowlisted entry, but not
    itself allowlisted, must still be flagged if it is genuinely orphaned:
    otherwise the allowlist silently exempts a whole directory instead of the
    one file it names.
    """
    assert check_test_traps.ORPHAN_ALLOWLIST, "allowlist must not be empty for this test"
    allowlisted_path = sorted(check_test_traps.ORPHAN_ALLOWLIST)[0]
    sibling = str(Path(allowlisted_path).parent / "test_definitely_not_allowlisted.py")

    findings = list(
        check_test_traps.check_orphaned_test_files(
            tracked_files=[allowlisted_path, sibling],
            runner_texts=["pytest tests/unit/ -q"],
        )
    )
    flagged = {f[0] for f in findings}
    assert allowlisted_path not in flagged, "the allowlisted file itself must never be flagged"
    assert sibling in flagged, (
        "a non-allowlisted sibling in the same directory must still be flagged: "
        "the allowlist must not accidentally exempt the whole directory"
    )


def test_orphan_allowlist_entries_are_commented(tmp_path):
    """Mirrors the .gitleaksignore-requires-a-comment convention
    (tests/unit/test_gitleaks_config.py): every exemption in the source file
    must carry its justification on the line, not just live in a set literal.
    """
    source = (REPO_ROOT / "scripts" / "check_test_traps.py").read_text(encoding="utf-8")
    match = re.search(r"ORPHAN_ALLOWLIST\s*=\s*\{(.*?)\n\}", source, re.DOTALL)
    assert match, "ORPHAN_ALLOWLIST set literal not found"
    body = match.group(1)
    # Walk the literal IN ORDER and require each entry to be immediately
    # preceded by a comment line.
    #
    # This compared totals (`len(comment_lines) >= len(entry_lines)`), which
    # cannot fail while any existing entry carries a multi-line justification:
    # the single current entry has a six-line block, so five more entries could
    # be added with no reason at all before the counts crossed. Measured: adding
    # an uncommented entry left the suite at 80 passed, exit 0.
    #
    # That matters because this allowlist is Rule 5's only escape hatch. An
    # agent told "the orphan check is failing" could silence it with no
    # justification, which is exactly the .gitleaksignore failure this test was
    # modelled on preventing.
    previous_was_comment = False
    unjustified = []
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            previous_was_comment = True
            continue
        if not previous_was_comment:
            unjustified.append(stripped)
        previous_was_comment = False

    assert not unjustified, (
        "every ORPHAN_ALLOWLIST entry must be immediately preceded by a comment "
        "justifying why that file is exempt from Rule 5. Unjustified: %s"
        % unjustified
    )


def test_tracked_test_files_uses_git_ls_files_not_a_filesystem_walk(tmp_path):
    """AC-DATA-21: an untracked local scratch file must be structurally
    invisible to this rule, not merely filtered out by convention.
    """
    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    tracked = repo / "test_tracked.py"
    tracked.write_text("def test_x():\n    pass\n")
    subprocess.run(["git", "add", "test_tracked.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    # Untracked scratch file, same test_*.py naming pattern, sitting right
    # next to the tracked one on disk.
    (repo / "test_scratch.py").write_text("def test_y():\n    pass\n")

    files = check_test_traps._tracked_test_files(repo)
    assert files == ["test_tracked.py"], (
        f"an untracked scratch file leaked into scope: {files}"
    )


def test_tracked_test_files_excludes_libs(tmp_path):
    """Vendored code under libs/ is not ours to flag."""
    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    (repo / "libs").mkdir()
    (repo / "libs" / "test_vendored.py").write_text("def test_x():\n    pass\n")
    (repo / "test_ours.py").write_text("def test_y():\n    pass\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    files = check_test_traps._tracked_test_files(repo)
    assert files == ["test_ours.py"], files


def test_extract_pytest_path_args_finds_directory_and_file_targets():
    dir_roots, file_args = check_test_traps._extract_pytest_path_args(
        "python -m pytest tests/unit/ -v --tb=short -W ignore::SyntaxWarning\n"
        "pytest tests/local/test_real_database.py -q\n"
    )
    assert dir_roots == {"tests/unit/"}
    assert file_args == {"tests/local/test_real_database.py"}


def test_extract_pytest_path_args_ignores_flags_and_trailing_message_text():
    """A pytest invocation followed by shell control flow and a message
    string must not leak spurious path-shaped tokens.
    """
    dir_roots, file_args = check_test_traps._extract_pytest_path_args(
        '"$PYTHON" -m pytest tests/integration/ -q --tb=short \\\n'
        '  || fail "Python integration tests failed"\n'
    )
    assert dir_roots == {"tests/integration/"}
    assert file_args == set()


def test_real_verify_and_ci_invoke_both_unit_and_integration_roots():
    """Anchors the extracted values, not just 'zero findings' on the real
    tree: a regex that silently stopped matching would make the whole-tree
    check pass for the wrong reason (nothing to compare against) rather than
    fail loudly.
    """
    dir_roots: set[str] = set()
    file_args: set[str] = set()
    for text in (
        (REPO_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8"),
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
    ):
        d, f = check_test_traps._extract_pytest_path_args(text)
        dir_roots |= d
        file_args |= f
    assert "tests/unit/" in dir_roots, dir_roots
    assert "tests/integration/" in dir_roots, dir_roots


def test_checker_is_clean_on_the_real_tree_under_rule_5():
    """The real tree, with the real verify.sh/ci.yml/tracked files, must have
    zero orphaned test_*.py files: meaning Part 2's wiring genuinely closed
    the gap rule 5 exists to catch.
    """
    findings = list(check_test_traps.check_orphaned_test_files())
    assert findings == [], findings


def test_strip_shell_comments_respects_quotes():
    """Quote-awareness is claimed in the docstring but was never asserted."""
    strip = check_test_traps.strip_shell_comments

    assert strip('echo "a # b" # real comment').rstrip() == 'echo "a # b"'
    assert strip("echo 'a # b' # real").rstrip() == "echo 'a # b'"
    # A backslash is NOT an escape inside single quotes in shell, so this string
    # ends at the second quote and the `#` that follows IS a comment.
    assert "pytest" not in strip("PAT='\\'  # pytest tests/ | tail -1")
    # blank_strings mode blanks contents but keeps the delimiters.
    blanked = strip('echo "set -o pipefail"', blank_strings=True)
    assert "pipefail" not in blanked
    assert blanked.count('"') == 2


def test_pipefail_is_detected_in_every_real_form_and_not_when_disabled():
    has = check_test_traps._has_pipefail
    for setting in (
        "set -o pipefail",
        "set -euo pipefail",
        "set -eu -o pipefail",
        "set -o errexit -o pipefail",
        "set -eox pipefail",
    ):
        assert has(setting), f"missed a real pipefail form: {setting!r}"

    assert not has("set +o pipefail"), "disabling pipefail must not count as setting it"
    assert not has("# set -o pipefail"), "a comment must not count"
    assert not has('echo "set -o pipefail"'), "a string literal must not count"


def test_makefile_pipe_outside_a_recipe_line_is_not_flagged(tmp_path):
    """A variable assignment is not a shell command."""
    makefile = tmp_path / "Makefile"
    makefile.write_text("FILTER = pytest | tail\n# comment: pytest | tail -5\nall:\n\techo hi\n")

    assert findings_for(makefile) == []


def test_makefile_recipe_with_inline_pipefail_is_not_flagged(tmp_path):
    makefile = tmp_path / "Makefile"
    makefile.write_text("test-py:\n\tset -o pipefail; pytest tests/unit/ -q | tail -5\n")

    assert findings_for(makefile) == []


def test_posix_sh_scripts_are_not_asked_for_pipefail(tmp_path):
    """`set -o pipefail` is not POSIX — a /bin/sh script must not be flagged for it.

    The Docker entrypoint is `#!/bin/sh` by hard rule 8, so this exemption is
    load-bearing, not hypothetical.

    The fixture contains a pipeline so the POSIX branch is actually reached.
    (Note: the reachability claim is only meaningful while rule 3 demands
    pipefail — it does so again as of the second remediation. The stronger
    guarantee lives in the next test, which pins the *advice* a /bin/sh script
    gets and fails if the POSIX branch is removed.)
    """
    script = tmp_path / "entrypoint.sh"
    script.write_text("#!/bin/sh\nset -eu\ncat a | sort > b\nexec \"$@\"\n")

    assert findings_for(script) == []


def test_posix_sh_runner_pipe_is_not_advised_to_use_bash_only_features(tmp_path):
    """A /bin/sh script still gets the runner-pipe finding, but not bash advice."""
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/sh\nset -eu\npytest tests/unit -q | tail -20\n")

    messages = messages_for(script)
    assert len(messages) == 1, messages
    assert "exit status" in messages[0]
    assert "bash-only" in messages[0], "should say why pipefail isn't the remedy here"


# ── Rule 6: vacuous E2E guards ───────────────────────────────────────────────
#
# `tests/e2e/**`'s own defect class (T1.4): a Playwright test whose only
# assertion lives inside `if (await x.isVisible()/count())`, so the test
# passes whether or not the guard is ever true. AGENTS.md used to ask
# `lens-qa` to keep re-finding this by hand ("the pattern was removed once in
# movie-detail.spec.ts and still exists elsewhere") — this rule is what
# retires that.


def _e2e_spec(tmp_path, name="feature.spec.ts"):
    """A `tests/e2e/<name>` file under tmp_path — `_is_e2e_spec` requires an
    actual `e2e` path segment, so every test in this section needs one."""
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True, exist_ok=True)
    return e2e_dir / name


def test_flags_expect_inside_an_isvisible_guard(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('shows a thing', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) {\n"
        "    await expect(btn).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    line_no, message = findings[0]
    assert line_no == 3, "should point at the `if` line, not the expect() line"
    assert "expect(" in message
    assert "isVisible" in message or "count" in message


def test_flags_a_guard_whose_await_was_hoisted_to_a_previous_line(tmp_path):
    """Moving one expression up a line must not defeat the rule.

    This is not hypothetical: the FIRST new code written after Rule 6 landed
    did exactly this (`const count = await cardLinks.count();` then
    `if (count > 1) {`), and the rule was silent on it. A guard introduced to
    retire a human review step has to survive the most obvious reformatting
    of the thing it looks for.
    """
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('has cards', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  const total = await cards.count();\n"
        "\n"
        "  if (total > 1) {\n"
        "    await expect(cards.nth(1)).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert findings[0][0] == 5, "should point at the `if` line"


def test_flags_a_hoisted_isvisible_guard_too(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('shows a thing', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  const shown = await btn.isVisible();\n"
        "  if (shown) {\n"
        "    await expect(btn).toHaveText('Go');\n"
        "  }\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_flags_an_early_return_guard_with_no_block(tmp_path):
    """`if (cond) return;` skips everything after it, braces or not.

    `stripped.endswith("{")` made the whole non-braced family invisible, and
    both forms are ordinary JS that Prettier produces. Two live instances
    already existed in this suite when the rule was widened.
    """
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('has cards', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  if (await cards.count() === 0) return;\n"
        "  await expect(cards.first()).toBeVisible();\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_flags_a_hoisted_guard_whose_await_was_wrapped_to_the_next_line(tmp_path):
    """Prettier wraps a long assignment. The rule must not be defeated by
    formatting alone, which a per-line scan was."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('has cards', async ({ page }) => {\n"
        "  const someVeryLongLocatorName = page.locator('.card');\n"
        "  const total =\n"
        "    await someVeryLongLocatorName.count();\n"
        "  if (total > 1) {\n"
        "    await expect(someVeryLongLocatorName.nth(1)).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_flags_a_parenthesised_await_assignment(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('shows', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  const shown = (await btn.isVisible());\n"
        "  if (shown) {\n"
        "    await expect(btn).toHaveText('Go');\n"
        "  }\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_flags_a_reassigned_guard_name(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('has cards', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  let total = 0;\n"
        "  total = await cards.count();\n"
        "  if (total > 1) {\n"
        "    await expect(cards.nth(1)).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_a_non_braced_guards_region_stops_at_the_enclosing_block(tmp_path):
    """A teardown helper must not be flagged because of an unrelated test.

    Review measured that this whole narrowing was uncovered: reverting it left
    all 90 trap tests green. The pre-fix code ran the brace matcher for a line
    with no `{`, so `line[line.rfind("{"):]` was the last character, depth
    never balanced, and the "body" ran to end of file -- picking up a sibling
    `test(...)`'s `expect(` and flagging a helper that asserts nothing.
    The documented remedy for a false positive is an opt-out comment, so this
    trained people to silence the rule.
    """
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "async function teardown(page) {\n"
        "  const btn = page.locator('.del');\n"
        "  if (await btn.count() === 0) return;\n"
        "  await btn.click();\n"
        "}\n"
        "\n"
        "test('unrelated', async ({ page }) => {\n"
        "  await expect(page.locator('h1')).toBeVisible();\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_a_one_line_braced_guard_uses_the_brace_matcher(tmp_path):
    """`if (cond) { ... }` all on one line has a real block.

    Keying the branch on `endswith("{")` sent this down the indentation path,
    which then ran to the end of the enclosing block and pulled in every
    following sibling -- a false positive on correct code, reintroducing
    through a different door the exact outcome the narrowing was written to
    remove. `{` anywhere on the line is the right test.
    """
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('clicks then asserts', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  if (await cards.count() > 0) { await cards.first().click(); }\n"
        "  await expect(page.locator('h1')).toBeVisible();\n"
        "});\n"
    )

    # The guard's own block contains no expect(, and the assertion that
    # follows it is unconditional, so there is nothing to flag.
    assert findings_for(spec) == []


def test_a_one_line_braced_guard_with_its_own_expect_is_still_flagged(tmp_path):
    """The other direction, so the fix above cannot become a blanket exemption."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('asserts only sometimes', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  if (await cards.count() > 0) { await expect(cards.first()).toBeVisible(); }\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_a_non_braced_guard_with_a_template_literal_condition_is_still_flagged(tmp_path):
    """A balanced brace pair in the CONDITION is not a block.

    `if (await page.locator(`#movie-${id}`).count() === 0) return;` was caught
    before the routing was widened to "any brace on the line" and silent
    after: the matcher balanced on the `${...}` inside the guard's own
    condition, so the region collapsed to nothing. Template literals already
    appear in two locator calls in this suite, so this is one ordinary edit
    away, and it is the shape the rule most needs to survive -- the module's
    own comment says it "has to survive the most obvious reformatting of the
    thing it looks for".
    """
    spec = _e2e_spec(tmp_path)
    # The template literal must be IN the guard condition. Hoisting it to the
    # previous line is a different, already-handled shape -- the first draft
    # of this test did exactly that and passed under the routing it was
    # written to catch.
    spec.write_text(
        "test('has a card', async ({ page }) => {\n"
        "  const id = 'abc';\n"
        "  if (await page.locator(`#movie-${id}`).count() === 0) return;\n"
        "  await expect(page.locator(`#movie-${id}`)).toBeVisible();\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_a_non_braced_guard_with_braces_in_a_selector_string_is_still_flagged(tmp_path):
    """Same shape, the other common spelling."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('has a card', async ({ page }) => {\n"
        "  if (await page.locator('[data-json=\"{}\"]').count() === 0) return;\n"
        "  await expect(page.locator('h1')).toBeVisible();\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_a_one_line_guard_with_a_nested_object_literal_is_still_flagged(tmp_path):
    """The `expect(` precedes the nested `{`, so slicing from the LAST brace
    would miss it and slicing from the first would pick up the condition's."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('asserts sometimes', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  if (await cards.count() > 0) { await expect(cards).toHaveCount(1, { timeout: 5 }); }\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_a_braced_guard_with_its_expect_on_the_guard_line_is_flagged(tmp_path):
    """The block opens here and closes later, with the assertion up top.

    Slicing the guard line's tail only when the braces balanced silenced this
    shape, and arbitrarily: written `} else if (...) {` it was still flagged,
    because the leading `}` balanced the count and routed it differently. Two
    spellings of one shape must not disagree.
    """
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('asserts sometimes', async ({ page }) => {\n"
        "  const c = page.locator('.card');\n"
        "  if (await c.count() > 0) { await expect(c).toBeVisible();\n"
        "    await c.click();\n"
        "  }\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_the_else_if_spelling_of_that_shape_agrees(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('asserts sometimes', async ({ page }) => {\n"
        "  const c = page.locator('.card');\n"
        "  if (false) {\n"
        "  } else if (await c.count() > 0) { await expect(c).toBeVisible();\n"
        "    await c.click();\n"
        "  }\n"
        "});\n"
    )

    assert len(findings_for(spec)) == 1


def test_the_guard_lines_condition_is_not_treated_as_body(tmp_path):
    """Slice from the BLOCK opener, not from the first brace on the line.

    `line.index("{")` picks up a brace inside the CONDITION -- a template
    literal, or a selector containing braces -- so everything from there
    onwards, including the rest of the condition, is scanned as if it were the
    guard's body. A condition that merely mentions `expect(` then produces a
    finding against a guard whose block asserts nothing, which is a false
    positive on correct code, and the documented remedy for a false positive
    is an opt-out comment.
    """
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('clicks a labelled control', async ({ page }) => {\n"
        # The `expect(` must sit AFTER the condition's own brace, or slicing
        # from that brace never reaches it and the fixture proves nothing --
        # which is what the first draft of this test did.
        "  if (await page.getByText('{0} expect(x)').count() > 0) { await page.click('.go'); }\n"
        "  await page.waitForTimeout(1);\n"
        "});\n"
    )

    assert findings_for(spec) == []


@pytest.mark.parametrize(
    'name,source,expected',
    [(n, src, exp) for n, src, exp in RULE6_SHAPES],
    ids=[n.split()[0] for n, _s, _e in RULE6_SHAPES],
)
def test_rule6_guard_spelling_corpus(tmp_path, name, source, expected):
    """Every guard spelling, scored in one place (spec gap 23).

    The individual tests above each pin the shape whose round found it. This
    scores the whole table on every edit, which is the difference between
    "the last bug does not recur" and "the rule is right". Shape 23 -- a false
    positive from a `){` inside a condition string -- is only visible here.
    """
    spec = _e2e_spec(tmp_path, name='corpus.spec.ts')
    spec.write_text(source)

    findings = findings_for(spec)
    assert len(findings) == expected, (
        '%s: expected %d finding(s), got %d\n%s'
        % (name, expected, len(findings), findings)
    )


def test_an_early_return_guard_can_be_opted_out_of(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "async function teardown(page) {\n"
        "  const btn = page.locator('.del');\n"
        "  if (await btn.count() === 0) return; // vacuous-guard-ok: idempotent teardown.\n"
        "  await expect(btn).toBeVisible();\n"
        "}\n"
    )

    assert findings_for(spec) == []


def test_does_not_flag_an_if_on_an_unrelated_name(tmp_path):
    """The other direction. Only names bound to an awaited
    isVisible()/count() count; an ordinary conditional must stay silent, or
    the rule becomes noise everyone opts out of."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('branches on config', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  const total = await cards.count();\n"
        "  const isCi = process.env.CI === '1';\n"
        "  if (isCi) {\n"
        "    await expect(cards).toHaveCount(total);\n"
        "  }\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_a_hoisted_guard_can_be_opted_out_of_on_the_if_line(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('has cards', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  const total = await cards.count();\n"
        "  if (total > 1) { // vacuous-guard-ok: the provider decides how many render.\n"
        "    await expect(cards.nth(1)).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_flags_expect_inside_a_count_guard(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('has cards', async ({ page }) => {\n"
        "  const cards = page.locator('.card');\n"
        "  if (await cards.count() > 0) {\n"
        "    expect(await cards.count()).toBeGreaterThan(0);\n"
        "  }\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert findings[0][0] == 3


def test_does_not_flag_an_assertion_outside_the_guard(tmp_path):
    """The real defect this rule targets is the assertion living INSIDE the
    guard with nothing outside it — checkNoErrors-style patterns (an
    assertion that always runs, with an unrelated action inside the guard)
    are exactly what T1.4 decided were NOT vacuous."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('clicks if present', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) {\n"
        "    await btn.click();\n"
        "  }\n"
        "  expect(errors).toHaveLength(0);\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_does_not_flag_a_guard_with_no_expect_at_all(tmp_path):
    """A click-only guard with zero assertions anywhere is a real defect too
    (T1.4 fixed several by hand), but it is a DIFFERENT shape than this rule
    covers -- catching it needs knowing whether the whole enclosing test()
    asserts anything anywhere, not just this block. Out of scope by design,
    documented in check_e2e_spec_guards' own docstring."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('clicks if present', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) {\n"
        "    await btn.click();\n"
        "  }\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_opt_out_with_a_reason_is_not_flagged(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('rare state', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) { // vacuous-guard-ok: only rendered for a fixture this suite cannot produce.\n"
        "    await expect(btn).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_opt_out_with_no_reason_is_itself_flagged(tmp_path):
    """A bare `vacuous-guard-ok:` with nothing after the colon is
    indistinguishable from silencing the check -- exactly the false-green
    this rule exists to prevent, so it must be flagged too."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('rare state', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) { // vacuous-guard-ok:\n"
        "    await expect(btn).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert "no reason" in findings[0][1]


def test_opt_out_with_only_whitespace_after_the_colon_is_flagged(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('rare state', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) { // vacuous-guard-ok:    \n"
        "    await expect(btn).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert "no reason" in findings[0][1]


def test_opt_out_must_be_on_the_guards_own_line(tmp_path):
    """A comment elsewhere (even the line above) does not count -- "near the
    guard" is not something the next edit can reliably preserve."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('rare state', async ({ page }) => {\n"
        "  // vacuous-guard-ok: this comment is one line too early\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) {\n"
        "    await expect(btn).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert "vacuous-guard-ok" in findings[0][1]


def test_finds_the_matching_close_brace_across_nested_braces(tmp_path):
    """The guard body contains its own nested braces (an object literal, an
    arrow function) before the expect() -- the close-brace scan must not
    stop at the first `}` it sees."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('nested', async ({ page }) => {\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) {\n"
        "    await page.route('**/x', route => route.fulfill({ status: 200 }));\n"
        "    const opts = { a: 1, b: { c: 2 } };\n"
        "    await expect(btn).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert findings[0][0] == 3


def test_expect_after_the_guard_closes_is_not_pulled_in(tmp_path):
    """A close-brace scan that overshoots would treat a LATER, unrelated
    expect() as belonging to this guard and wrongly excuse it, or double
    count it against the wrong guard."""
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('two guards', async ({ page }) => {\n"
        "  const a = page.locator('a');\n"
        "  if (await a.isVisible()) {\n"
        "    await a.click();\n"
        "  }\n"
        "  const b = page.locator('b');\n"
        "  if (await b.count() > 0) {\n"
        "    await expect(b).toBeVisible();\n"
        "  }\n"
        "});\n"
    )

    findings = findings_for(spec)
    assert len(findings) == 1, findings
    assert findings[0][0] == 7, "should point at the second guard (b), not the first (a)"


def test_a_commented_out_guard_is_not_flagged(tmp_path):
    spec = _e2e_spec(tmp_path)
    spec.write_text(
        "test('x', async ({ page }) => {\n"
        "  // if (await btn.isVisible()) { expect(btn).toBeVisible(); }\n"
        "  expect(1).toBe(1);\n"
        "});\n"
    )

    assert findings_for(spec) == []


def test_helpers_ts_is_in_scope_not_only_spec_files(tmp_path):
    """AC-QA-42 scopes this to every file under tests/e2e/**, not only
    *.spec.ts -- a guard like this could land in a shared helper just as
    easily as in a spec (e.g. tests/e2e/helpers.ts)."""
    helper = _e2e_spec(tmp_path, name="helpers.ts")
    helper.write_text(
        "export async function maybeClick(page) {\n"
        "  const btn = page.locator('button');\n"
        "  if (await btn.isVisible()) {\n"
        "    expect(await btn.isEnabled()).toBe(true);\n"
        "  }\n"
        "}\n"
    )

    findings = findings_for(helper)
    assert len(findings) == 1, findings


def test_a_ts_file_outside_tests_e2e_is_not_scanned_by_this_rule(tmp_path):
    """Scope check: the identical pattern in a non-e2e file is not this
    rule's concern (jsdom geometry aside, Rule 1 already covers vitest specs
    on their own terms)."""
    other = tmp_path / "tests" / "unit" / "ui" / "widget.spec.ts"
    other.parent.mkdir(parents=True)
    other.write_text(
        "it('x', () => {\n"
        "  if (someCondition()) {\n"
        "    expect(1).toBe(1);\n"
        "  }\n"
        "});\n"
    )

    assert findings_for(other) == []


def test_checker_is_clean_on_tests_e2e_under_rule_6():
    result = run_checker(REPO_ROOT / "tests" / "e2e")
    assert result.returncode == 0, (
        f"check_test_traps.py rule 6 is not clean on tests/e2e:\n"
        f"{result.stdout}\n{result.stderr}"
    )


# ── Whole-tree behaviour ────────────────────────────────────────────────────


@requires_node  # DEFAULT_ROOTS now includes the template roots rule 8 scans.
def test_checker_is_clean_on_the_real_tree():
    """It has to be green on the repo to be a blocking gate.

    The file count and the known-file assertions are the point: a bare
    "returncode == 0" passes when the walk is broken and the gate scans one file
    instead of 116 — the "green because it did no work" failure this whole script
    exists to prevent. Confirmed by mutation: disabling the directory recursion
    survived a returncode-only assertion.
    """
    result = run_checker()
    assert result.returncode == 0, (
        f"check_test_traps.py is not clean on the tree:\n{result.stdout}\n{result.stderr}"
    )

    match = re.search(r"passed \((\d+) file\(s\) scanned\)", result.stdout)
    assert match, f"no scan count in output: {result.stdout!r}"
    assert int(match.group(1)) >= 100, (
        f"only {match.group(1)} files scanned — the walk is broken, so 'passed' is "
        f"meaningless. Expected the whole of tests/unit + scripts + .githooks + "
        f".github/workflows + Makefile."
    )


def test_default_roots_all_exist_and_are_covered():
    """Every default root must resolve and contribute files.

    An emptied or mistyped root makes the gate silently skip a whole area while
    still reporting "passed" (confirmed by mutation).
    """
    assert check_test_traps.DEFAULT_ROOTS, "no default roots at all"
    for root in check_test_traps.DEFAULT_ROOTS:
        assert root.exists(), f"default root does not exist: {root}"

    scanned = check_test_traps.iter_files(check_test_traps.DEFAULT_ROOTS)
    scanned_str = {str(p) for p in scanned}
    # One representative file per root, so a dropped root fails here. At least one
    # must be NESTED: with only top-level files listed, downgrading the walk from
    # rglob to glob passed while dropping all six tests/unit/ui/*.spec.ts — i.e.
    # every vitest spec in the repo, which is rule 1's entire target set.
    for expected in (
        REPO_ROOT / "tests" / "unit" / "test_check_test_traps.py",
        REPO_ROOT / "tests" / "unit" / "ui" / "movie-filter.spec.ts",  # nested
        REPO_ROOT / "tests" / "e2e" / "interactions.e2e.spec.ts",  # rule 6's target set
        REPO_ROOT / "scripts" / "verify.sh",
        REPO_ROOT / "scripts" / "release" / "next_beta_version.py",  # nested
        REPO_ROOT / ".githooks" / "pre-push",
        REPO_ROOT / ".github" / "workflows" / "ci.yml",
        REPO_ROOT / "Makefile",
        # nested, AC-A11Y-6's representative for rule 8's template root
        REPO_ROOT / "couchpotato" / "ui" / "templates" / "partials" / "movie_detail.html",
        REPO_ROOT / "couchpotato" / "templates" / "login.html",  # AC-QA-78
    ):
        assert str(expected) in scanned_str, f"{expected} was not scanned"

    # And explicitly: every vitest spec must be in scope, by discovery not by list.
    specs = sorted((REPO_ROOT / "tests" / "unit").rglob("*.spec.ts"))
    assert specs, "no vitest specs found at all — check the glob"
    missing = [str(s) for s in specs if str(s) not in scanned_str]
    assert not missing, f"vitest specs not scanned (rule 1 would be dead for them): {missing}"


def test_exits_nonzero_and_prints_file_line_message_on_a_finding(tmp_path):
    spec = tmp_path / "bad.spec.ts"
    spec.write_text("it('x', () => { expect(document.body.offsetHeight).toBe(0); });\n")

    result = run_checker(spec)
    assert result.returncode != 0
    assert f"{spec}:1:" in result.stdout
    assert "offsetHeight" in result.stdout


def test_reports_a_summary_when_clean(tmp_path):
    spec = tmp_path / "fine.spec.ts"
    spec.write_text("it('x', () => { expect(1).toBe(1); });\n")

    result = run_checker(spec)
    assert result.returncode == 0
    assert "passed" in result.stdout.lower()


class TestRule5WithoutGit:
    """Rule 5's input is `git ls-files`. What happens when git is not there.

    `./scripts/test-local.sh` runs this suite inside `python:3.14-alpine`,
    which ships no git. An unhandled `FileNotFoundError` there turned
    `make check-traps` into a crash and took the container run from 34 red
    to 40 red, all of them `FileNotFoundError: 'git'` and none of them a real
    finding.

    Catching it creates the opposite hazard, and it is the one this whole
    script exists to prevent: a rule that silently does nothing while the
    command still exits 0. That is why `--require-git` exists, and why these
    tests pin BOTH directions. Without the second one, "we handled it" would
    rest entirely on a comment.
    """

    @staticmethod
    def _path_without_git(tmp_path):
        """A PATH with no `git` on it, so the lookup raises FileNotFoundError.

        Keeps `node` reachable: this class is isolating rule 5's git-missing
        behaviour, and losing node too would fail these tests via rule 8
        (CI-003 Part B) for an unrelated reason.
        """
        empty_bin = tmp_path / 'empty-bin'
        empty_bin.mkdir()
        node_path = shutil.which("node")
        node_dir = str(Path(node_path).parent) if node_path else ""
        return os.pathsep.join(p for p in (str(empty_bin), node_dir) if p)

    @requires_node
    def test_a_missing_git_skips_the_rule_rather_than_crashing(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECKER)],
            capture_output=True, text=True, cwd=REPO_ROOT,
            env={**os.environ, 'PATH': self._path_without_git(tmp_path)},
        )

        assert result.returncode == 0, (
            'the checker crashed instead of skipping rule 5:\n%s' % result.stderr
        )
        assert 'Traceback' not in result.stderr, result.stderr
        # The skip must be visible. A silent one is the failure mode.
        assert 'orphan-test check skipped' in result.stderr, result.stderr
        # The other six rules must still have run.
        assert 'passed' in result.stdout.lower(), result.stdout

    def test_require_git_turns_the_skip_into_a_failure(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECKER), '--require-git'],
            capture_output=True, text=True, cwd=REPO_ROOT,
            env={**os.environ, 'PATH': self._path_without_git(tmp_path)},
        )

        assert result.returncode != 0, (
            '--require-git let the run pass with rule 5 skipped; stdout:\n%s'
            % result.stdout
        )
        assert 'must not skip a rule silently' in result.stderr, result.stderr

    def test_the_authoritative_gates_both_pass_require_git(self):
        """The flag is worth nothing if the gates do not use it.

        verify.sh is the local gate and ci.yml is its mirror (hard rule 2:
        `make verify` must pass locally before every push, don't rely on CI).
        Both must opt in, or the skip branch is reachable from the run whose
        green means something.

        `make check-traps` passes it too, since 2026-08-06. It was left bare on
        the theory that the git-less Alpine container needs the lenient path --
        measured, nothing git-less invokes that target at all
        (`scripts/test-local.sh` only mentions the checker in a comment), so
        the theory was wrong and the command CLAUDE.md's table names could
        silently skip a rule.
        """
        for relative in ('scripts/verify.sh', '.github/workflows/ci.yml', 'Makefile'):
            text = (REPO_ROOT / relative).read_text(encoding='utf-8')
            invocations = [
                line for line in text.splitlines()
                if 'check_test_traps.py' in line and not line.strip().startswith('#')
            ]
            assert invocations, 'no check_test_traps.py invocation found in %s' % relative
            for line in invocations:
                assert '--require-git' in line, (
                    '%s invokes the checker without --require-git, so a missing '
                    'git would silently skip rule 5 in an authoritative gate: %s'
                    % (relative, line.strip())
                )

    def test_git_present_but_failing_is_handled_the_same_way(self, tmp_path):
        """`git ls-files` outside a work tree exits non-zero, not not-found.

        A different exception class, the same consequence, and it is the one
        that would bite a `pip install`-ed copy of this repo rather than a
        container. Driven directly because the CLI always runs at REPO_ROOT.
        """
        assert check_test_traps._tracked_test_files(tmp_path) == []

        with pytest.raises(SystemExit) as excinfo:
            check_test_traps._tracked_test_files(tmp_path, require_git=True)
        assert 'must not skip a rule silently' in str(excinfo.value)


class TestRule3ShellOptionsAreBothPinned:
    """Rule 3 asks for `-e` AND `-u`. Only the `-u` half could fail.

    Measured: replacing the `-e` condition with `if False:` left all 131 tests
    green. Every negative fixture in this file also omitted `-u`, so
    `len(findings) == 1` held whether the `-e` check ran or not -- the
    incidentally-passing shape, which reads as specific and is not.
    """

    def test_a_script_with_u_but_no_e_is_flagged(self, tmp_path):
        # The one fixture the suite lacked: -u present, -e absent, so the
        # finding can ONLY come from the -e half.
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -u\necho hi\n')

        findings = findings_for(script)

        assert len(findings) == 1, findings
        assert '-e (exit on error)' in findings[0][1], findings

    def test_a_script_with_e_but_no_u_is_flagged(self, tmp_path):
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -e\necho hi\n')

        findings = findings_for(script)

        assert len(findings) == 1, findings
        assert '-u (error on unset variable)' in findings[0][1], findings

    @pytest.mark.parametrize('set_line', [
        'set -eu',
        'set -e -u',
        'set -o errexit -o nounset',
        'set -e -o nounset',        # cluster and long form together
        'set -o errexit -u',
    ])
    def test_the_long_forms_are_accepted(self, tmp_path, set_line):
        """`set -o errexit -o nounset -o pipefail` is the canonical spelling.

        It was FLAGGED as missing -e: `nounset` was accepted as a long form
        and `errexit` was not, so a blocking gate rejected the most explicit
        correct way to write the thing it demands. Whoever hit it would have
        "fixed" a correct script to satisfy the checker.
        """
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\n%s\necho hi\n' % set_line)

        assert findings_for(script) == []


class TestRule3ParsingEdgeCases:
    """Three spellings the tokenised parser got wrong, found by review.

    Two false greens and one false positive, all measured by driving the real
    checker. Kept as a separate class because they are about the PARSER, not
    about which flags the rule demands.
    """

    def test_a_flag_mentioned_inside_a_string_does_not_count(self, tmp_path):
        # `strip_shell_comments(ln)` without blank_strings=True read the `-u`
        # inside the echo. That is the same false-green the pipefail rule
        # already learned ("echo \"hint: add set -o pipefail\" silenced rule 2
        # for a whole file"), reintroduced two rules away by dropping one
        # keyword argument.
        script = tmp_path / 'gate.sh'
        script.write_text(
            '#!/bin/bash\n'
            'set -e; echo "run with set -u for stricter checking"\n'
        )

        findings = findings_for(script)

        assert len(findings) == 1, findings
        assert '-u (error on unset variable)' in findings[0][1], findings

    def test_set_dash_dash_sets_positional_parameters_not_flags(self, tmp_path):
        # `set -- -e -u` assigns $1 and $2. It enables nothing, and was being
        # read as `set -eu` because the tokeniser skipped `--` and carried on.
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -- -e -u\necho "$1"\n')

        messages = [m for _line, m in findings_for(script)]

        assert len(messages) == 1, messages
        assert '-e (exit on error)' in messages[0], messages
        assert '-u (error on unset variable)' in messages[0], messages

    def test_flags_belonging_to_another_command_on_the_line_are_not_counted(self, tmp_path):
        """`sort -u` is not `set -u`.

        The tokeniser walked every token on the line, so `set -e; sort -u
        /etc/hosts` came back CLEAN -- a blocking gate passing a script that
        genuinely lacks `-u`. Measured against the regex this parser replaced
        (`git show f7f57b62`), which flagged it correctly: a regression
        introduced by the rewrite that was meant to remove false results.
        """
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -e; sort -u /etc/hosts\n')

        findings = findings_for(script)

        assert len(findings) == 1, findings
        assert '-u (error on unset variable)' in findings[0][1], findings

    def test_dash_dash_ends_options_for_its_own_command_only(self, tmp_path):
        """`set -- alpha; set -eu` enables both. Breaking on `--` for the rest
        of the physical line reported it as missing both -- a false positive on
        a correct script, which the rule's own comment argues is not a harmless
        nag."""
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -- alpha; set -eu\necho "$1"\n')

        assert findings_for(script) == []

    def test_a_set_after_another_command_on_the_same_line_still_counts(self, tmp_path):
        """`echo hi; set -eu` genuinely enables both.

        The line filter required `set` to be the first thing on the line, so
        this was reported as missing both -- a false positive that predates
        the tokeniser and is closed by the same change.
        """
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\necho hi; set -eu\necho done\n')

        assert findings_for(script) == []

    def test_a_trailing_semicolon_does_not_hide_a_long_form(self, tmp_path):
        # `set -o errexit; set -o nounset;` tokenises as `errexit;`/`nounset;`.
        # The equality test missed both and the file was reported as missing
        # BOTH flags -- a blocking gate rejecting a correct script, and a
        # REGRESSION against the substring regex this parser replaced.
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -o errexit; set -o nounset;\necho hi\n')

        assert findings_for(script) == []

    def test_a_later_set_line_is_not_terminated_by_an_earlier_dash_dash(self, tmp_path):
        # Parsing is per-line, so `--` ends options for ITS line only.
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -- alpha beta\nset -eu\necho "$1"\n')

        assert findings_for(script) == []


class TestRule2FilterAlternatives:
    """Rule 2's filter list must be more than `tail`.

    Measured: narrowing `FILTER_RE` to `tail` alone left all 131 tests green
    -- only `tail` was ever exercised in a runner-pipe position, so twelve of
    the thirteen alternatives were unguarded. `scripts/verify.sh` contains a
    live `ruff --version | awk` pipeline that depends on one of them.
    """

    @pytest.mark.parametrize('filter_cmd', [
        'tail -1', 'head -5', 'grep -c FAIL', 'tee out.log', "awk '{print $1}'",
        "sed -n '1p'", 'sort', 'uniq', 'wc -l', 'cat', 'less', 'more', 'jq .',
    ])
    def test_every_filter_in_the_list_is_detected_after_a_runner(self, tmp_path, filter_cmd):
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -eu\npytest tests/ | %s\n' % filter_cmd)

        findings = findings_for(script)

        assert findings, 'pytest | %s was not flagged' % filter_cmd
        assert any('exit' in message.lower() for _, message in findings), findings

    def test_a_pipeline_with_pipefail_is_left_alone(self, tmp_path):
        """The rule must not fire on a pipeline whose exit code is preserved,
        or the remedy it prints would not clear the finding."""
        script = tmp_path / 'gate.sh'
        script.write_text('#!/bin/bash\nset -euo pipefail\npytest tests/ | tail -1\n')

        assert findings_for(script) == []


class TestCaplogInfoLevelTrap:
    """`caplog.at_level("INFO")` captures nothing, and looks like a missing log.

    `couchpotato/core/logger.py:24` calls `logging.addLevelName(21, 'INFO')` to
    register the INFO2 level. That overwrites `logging._nameToLevel['INFO']`
    from 20 to 21, so pytest resolving the STRING "INFO" sets the capture
    threshold to 21 and drops every genuine `log.info()` record, which is
    emitted at 20.

    Measured on this tree:

        before importing couchpotato.core.logger : INFO -> 20
        after                                    : INFO -> 21

    The failure mode is a false RED, not a false green, which is why it is worth
    a guard rather than a paragraph: the test author sees "no log line was
    captured", concludes the code never logged, and either deletes a correct
    assertion or adds a log call that was already there. It cost the PR 2b
    implementer exactly that detour. `'ERROR'` and `'WARNING'` are unaffected,
    which is why no existing test has ever tripped over it.

    The int form (`logging.INFO`) bypasses the name lookup and works.
    """

    def _py_test(self, tmp_path, body: str) -> Path:
        path = tmp_path / "test_sample.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_at_level_with_the_info_string_is_flagged(self, tmp_path):
        path = self._py_test(
            tmp_path,
            "def test_thing(caplog):\n"
            "    with caplog.at_level('INFO'):\n"
            "        do_something()\n",
        )
        assert any('INFO' in m for m in messages_for(path)), (
            "caplog.at_level('INFO') was not flagged; it silently captures "
            "nothing because logger.py remaps the INFO name to 21"
        )

    def test_set_level_with_the_info_string_is_flagged(self, tmp_path):
        path = self._py_test(
            tmp_path,
            "def test_thing(caplog):\n"
            "    caplog.set_level(\"INFO\")\n",
        )
        assert any('INFO' in m for m in messages_for(path)), (
            'caplog.set_level("INFO") was not flagged'
        )

    def test_the_int_form_is_left_alone(self, tmp_path):
        """The fix must not be flagged, or the guard just teaches people to
        suppress it."""
        path = self._py_test(
            tmp_path,
            "import logging\n"
            "def test_thing(caplog):\n"
            "    with caplog.at_level(logging.INFO):\n"
            "        do_something()\n",
        )
        assert not messages_for(path), (
            'the int form logging.INFO is correct and must not be flagged: %s'
            % messages_for(path)
        )

    def test_other_level_strings_are_left_alone(self, tmp_path):
        """Only INFO is remapped. Flagging ERROR would be noise."""
        path = self._py_test(
            tmp_path,
            "def test_thing(caplog):\n"
            "    with caplog.at_level('ERROR'):\n"
            "        do_something()\n"
            "    caplog.set_level('WARNING')\n",
        )
        assert not messages_for(path), (
            'ERROR and WARNING are not remapped and must not be flagged: %s'
            % messages_for(path)
        )

    def test_the_premise_still_holds(self):
        """Pins WHY the rule exists, so it cannot outlive its reason.

        If logger.py stops remapping INFO, this guard is obsolete and should be
        deleted rather than kept out of habit.
        """
        import logging

        import couchpotato.core.logger  # noqa: F401

        assert logging.getLevelName('INFO') == 21, (
            "logger.py no longer remaps the INFO name to 21, so "
            "caplog.at_level('INFO') is safe again and this whole guard "
            "should be deleted"
        )
        assert logging.INFO == 20


# ── Rule 8: template <script> blocks must parse as JavaScript ──────────────
#
# CI-003 Part B (specs/CI-003-fast-gate.md). The #230 defect: a dropped `+`
# in couchpotato/ui/templates/suggestions.html broke a whole Alpine component
# and only four E2E tests going red caught it — nothing else looks at
# template JS at all. See scripts/check_test_traps.py's check_html_template.

TEMPLATES_ROOT = REPO_ROOT / "couchpotato" / "ui" / "templates"
# BOTH live Jinja render roots (couchpotato/__init__.py:48-51). Reviewing the
# first version of this rule found the second root covered by a hardcoded
# `login.html` rather than a walk, so a new template dropped beside it was
# never scanned and the gate exited 0. Enumerating both here is what makes
# test_every_template_with_a_non_src_inline_script_is_scanned able to see it.
TEMPLATE_ROOTS = (TEMPLATES_ROOT, REPO_ROOT / "couchpotato" / "templates")
LOGIN_HTML = REPO_ROOT / "couchpotato" / "templates" / "login.html"


@requires_node
def test_flags_a_genuine_syntax_error_in_a_classic_script_block(tmp_path):
    path = tmp_path / "bad.html"
    path.write_text("<script>\nfunction f() {\n  const bad = (;\n}\n</script>\n")
    findings = findings_for(path)
    assert findings, "a real JS syntax error was not flagged"
    line_no, message = findings[0]
    assert line_no == 3, (line_no, findings)
    assert "Error" in message


@requires_node
def test_valid_classic_script_is_clean(tmp_path):
    path = tmp_path / "good.html"
    path.write_text("<script>\nfunction f() {\n  return 1;\n}\n</script>\n")
    assert findings_for(path) == []


@requires_node
def test_finding_line_is_the_html_line_not_a_block_offset(tmp_path):
    """AC-QA-76: prints the line IN THE .HTML FILE, proved on a block that
    opens well down the file (the real wanted.html/movie_detail.html shape)."""
    padding = "\n".join(f"<!-- padding {i} -->" for i in range(1, 50))  # 49 lines
    text = padding + "\n<script>\nconst ok = 1;\nconst bad = (;\n</script>\n"
    path = tmp_path / "deep.html"
    path.write_text(text)
    findings = findings_for(path)
    assert findings, findings
    # 49 padding lines + "<script>" on 50 + "const ok" on 51 -> error on 52.
    assert findings[0][0] == 52, (findings, text.split("\n")[51])


@requires_node
@pytest.mark.parametrize(
    "rel, needle",
    [
        # The spec's own examples (AC-QA-76): both scripts open well down
        # the file (wanted.html:191, movie_detail.html:363), so a
        # line-mapping bug invisible on a shallow fixture cannot hide here.
        ("wanted.html", "selectedIds: new Set(),\n"),
        ("partials/movie_detail.html", "saving: false,\n"),
    ],
)
def test_line_mapping_matches_the_real_html_line_on_a_deep_file(tmp_path, rel, needle):
    original = (TEMPLATES_ROOT / rel).read_text(encoding="utf-8")
    assert needle in original, f"fixture text moved in {rel}; update this test"
    expected_line = original[: original.index(needle)].count("\n") + 1
    mutated = original.replace(needle, needle.rstrip("\n").rstrip(",") + "(;\n", 1)
    path = tmp_path / Path(rel).name
    path.write_text(mutated)
    findings = findings_for(path)
    assert findings, f"{rel}: the mutated line was not flagged"
    line_no, _ = findings[0]
    assert line_no == expected_line, (rel, line_no, expected_line)


@requires_node
def test_two_broken_blocks_yield_two_findings_not_one(tmp_path):
    path = tmp_path / "two.html"
    path.write_text(
        "<script>\nconst a = (;\n</script>\n"
        "<p>x</p>\n"
        "<script>\nconst b = (;\n</script>\n"
    )
    assert len(findings_for(path)) == 2, findings_for(path)


@requires_node
def test_a_clean_first_block_does_not_short_circuit_a_broken_second(tmp_path):
    """A per-file short-circuit (stop at the first block) must not pass this."""
    path = tmp_path / "second_broken.html"
    path.write_text(
        "<script>\nconst a = 1;\n</script>\n"
        "<script>\nconst b = (;\n</script>\n"
    )
    findings = findings_for(path)
    assert len(findings) == 1, findings


@requires_node
def test_reintroducing_the_230_defect_is_flagged(tmp_path):
    """Prove it against the REAL defect (project rule 10), on a copy so the
    tracked template is never touched (AC-SIMP-9)."""
    original = (TEMPLATES_ROOT / "suggestions.html").read_text(encoding="utf-8")
    needle = "console.warn('[suggestions] focus did not reach ' + ref +\n"
    assert needle in original, "the #230 line moved; update this fixture"
    mutated = original.replace(needle, needle.replace(" +\n", "\n"), 1)
    path = tmp_path / "suggestions.html"
    path.write_text(mutated)
    findings = findings_for(path)
    assert findings, "the exact #230 defect (a dropped `+`) was not flagged"
    line_no, message = findings[0]
    assert line_no == 226, (line_no, findings)
    assert "Error" in message


@requires_node
def test_the_real_suggestions_html_is_clean_today():
    assert findings_for(TEMPLATES_ROOT / "suggestions.html") == []


@requires_node
def test_movie_detail_html_parses_clean_via_jinja_substitution_not_exclusion():
    """AC-QA-70: a naive extract-and-parse fails on this file at block line 5
    (`newProfile: '{{ movie.get(...) }}'`) — it must be masked, not excluded."""
    findings = findings_for(TEMPLATES_ROOT / "partials" / "movie_detail.html")
    assert findings == [], findings


@requires_node
def test_a_jinja_bearing_block_with_a_syntax_error_is_flagged(tmp_path):
    """AC-A11Y-7, direction 1: masking must not become a blanket silencer."""
    path = tmp_path / "jinja_bad.html"
    path.write_text(
        "<script>\n"
        "const url = '{{ web_base }}partial/{{ movie_id }}' + window.loc;\n"
        "const bad = (;\n"
        "</script>\n"
    )
    findings = findings_for(path)
    assert findings, "a syntax error alongside masked Jinja was not flagged"


@requires_node
def test_jinja_if_endif_wrapping_valid_js_is_not_flagged(tmp_path):
    """AC-A11Y-7, direction 2: valid JS wrapped in a Jinja control tag must
    not be reported, or the substitution has become a blanket silencer."""
    path = tmp_path / "jinja_if.html"
    path.write_text(
        "<script>\n"
        "{% if debug %}\n"
        "console.log('debug mode');\n"
        "{% endif %}\n"
        "function ready() { return true; }\n"
        "</script>\n"
    )
    assert findings_for(path) == []


def test_a_jinja_control_tag_in_expression_position_is_not_a_false_red(tmp_path):
    """The M2 regression: a conditional object property is ordinary template
    code and rendered valid JS on every branch, but the first version of the
    mask substituted the identifier `__JINJA__` -- legal only where a VALUE
    is legal -- and reported a SyntaxError against correct code.

    A blocking gate that is red on valid input is how a team learns to reach
    for --no-verify, and this rule deliberately has no override.
    """
    path = tmp_path / "expr_position.html"
    path.write_text(
        "<script>\n"
        "const cfg = {\n"
        "  a: 1,\n"
        "  {% if feature %}\n"
        "  b: 2,\n"
        "  {% endif %}\n"
        "};\n"
        "</script>\n"
    )
    assert findings_for(path) == []


def test_a_jinja_tag_splitting_one_expression_is_a_KNOWN_false_red(tmp_path):
    """The limit of masking, pinned so it is known rather than discovered.

    No substitution makes this parse without rendering the template, which is
    far beyond a parse gate. The test exists so that if someone later teaches
    the mask to handle it, this fails and the docstring gets updated -- and so
    that nobody reports it as a fresh bug.
    """
    path = tmp_path / "split_expr.html"
    path.write_text(
        "<script>\n"
        "fetchAll({% if debug %} 'verbose' {% else %} 'quiet' {% endif %});\n"
        "</script>\n"
    )
    assert findings_for(path), (
        "the split-expression false RED is documented as a known limit; if it "
        "now passes, the mask improved and _mask_jinja's docstring is stale"
    )


def test_a_greater_than_inside_an_attribute_value_does_not_split_the_tag(tmp_path):
    """The M3 regression: `[^>]*` stopped at the first `>`, so ` b">` was
    prepended to the body and valid JS was reported as a SyntaxError at a
    line number pointing at the tag rather than at any fault."""
    path = tmp_path / "attr_gt.html"
    path.write_text('<script data-cfg="a > b">\nconst y = 1;\n</script>\n')
    assert findings_for(path) == []


def test_an_unterminated_script_is_reported_as_skipped_not_silently_dropped(tmp_path):
    """The M3 false-NEGATIVE half: a missing `</script>` meant the block was
    not scanned, not flagged, and absent from the skipped list -- an
    extraction failure invisible in the very output added to surface
    extraction failures."""
    path = tmp_path / "unterminated.html"
    path.write_text("<script>\nconst ok = 1;\n")
    kinds = [kind for _line, kind, _body in
             check_test_traps._iter_script_blocks(path.read_text())]
    assert "skip-unterminated" in kinds, (
        "an unterminated <script> vanished instead of being reported: %s" % kinds
    )


def test_a_commented_script_mention_is_not_reported_as_unterminated(tmp_path):
    """The skipped list must be CORRECT, not merely present.

    The first version of the unterminated check took a positional slice of
    leftover `<script` openers, which is only equivalent to "the unmatched
    ones" when the unmatched openers come last. They do not: `base.html` says
    `// <script>` in a comment at :238, so the count was off by one and the
    slice blamed :511 -- a real, terminated, correctly-parsed block. Four such
    false lines printed on every green run, in the channel added precisely so
    a real extraction failure could not hide.

    Both halves asserted together, because either alone passes trivially: the
    commented mention must NOT be reported, and the genuinely unterminated
    block after it MUST be, at its own line.
    """
    path = tmp_path / "mixed.html"
    path.write_text(
        "<script>\n"
        "// <script> mentioned inside a comment\n"
        "const a = 1;\n"
        "</script>\n"
        "<script>\n"
        "const b = 2;\n"
    )
    skips = [(line, kind) for line, kind, _body in
             check_test_traps._iter_script_blocks(path.read_text())
             if kind == "skip-unterminated"]
    assert skips == [(5, "skip-unterminated")], (
        "expected exactly the genuinely unterminated block at line 5, got %r" % skips
    )


@pytest.mark.parametrize("closer", [
    "</script>",
    "</script >",
    "</script\t>",
    "</script\n>",
    "</script\t\n bar>",   # CodeQL alert #95: end tags may carry ignored attributes
    "</SCRIPT>",           # end tags are case-insensitive
])
def test_whitespace_before_the_end_tag_bracket_does_not_produce_a_false_green(tmp_path, closer):
    """The worst outcome this rule can have, and it shipped for one commit.

    HTML permits whitespace before an end tag's `>`. `</script>` alone did not
    match `</script >`, so the block was never parsed, was reported merely as
    "skip-unterminated", and THE GATE EXITED 0 with a genuine syntax error
    inside it. A false green in the rule whose entire purpose is preventing
    false greens.

    Found by CodeQL's bad-HTML-filtering-regexp query, which is the second time
    that query has caught this exact class in this repo -- so it is pinned here
    rather than trusted to a comment.
    """
    path = tmp_path / "closer.html"
    path.write_text("<script>\nconst broken = (;\n%s\n" % closer)
    findings = findings_for(path)
    assert findings, "a syntax error was NOT reported with closer %r" % closer
    assert findings[0][0] == 2, "wrong line for closer %r: %r" % (closer, findings)


def test_a_hyphenated_custom_element_is_not_a_script_block(tmp_path):
    """`\\b` is a word boundary and `-` is a non-word character, so
    `<script-loader>` matched. Two measured false REDs from one cause:

      * the custom element's contents were parsed as JavaScript;
      * a `"</script-loader>"` STRING inside a real block closed that block
        early, reporting a SyntaxError at the wrong line.

    HTML5 terminates a tag name with whitespace, `/` or `>` and nothing else.
    The second assertion is the sharper one: it fails on the LINE NUMBER, so a
    fix that merely stops the early close but keeps mis-parsing would not pass.
    """
    element = tmp_path / "custom.html"
    element.write_text("<script-loader>\nnot js at all (;\n</script-loader>\n")
    assert findings_for(element) == [], "a hyphenated custom element was parsed as JS"

    early_close = tmp_path / "string_closer.html"
    early_close.write_text(
        '<script>\nconst a = "</script-loader>";\nconst broken = (;\n</script>\n'
    )
    findings = findings_for(early_close)
    assert findings and findings[0][0] == 3, (
        "expected the real error at line 3, got %r -- the block was closed early "
        "by a string" % findings
    )


def test_a_commented_out_script_element_is_not_parsed(tmp_path):
    """A `<script>` inside `<!-- -->` is not code the browser ever runs, so
    reporting a SyntaxError in one is a false RED in a gate with no override.

    The control is the point: an ADJACENT real block must still be checked, or
    the fix has simply stopped scanning files that contain a comment.
    """
    commented = tmp_path / "commented.html"
    commented.write_text("<div>\n<!--\n<script>\nconst broken = (;\n</script>\n-->\n</div>\n")
    assert findings_for(commented) == [], "a commented-out script block was parsed"

    both = tmp_path / "both.html"
    both.write_text(
        "<!--\n<script>\nignored (;\n</script>\n-->\n<script>\nconst broken = (;\n</script>\n"
    )
    findings = findings_for(both)
    assert findings and findings[0][0] == 7, (
        "the real block after a comment must still be checked, at its own line; got %r"
        % findings
    )


def test_a_data_src_attribute_does_not_hide_a_block_from_the_parser(tmp_path):
    """Second false green of the same family as the `</script >` closer.

    `\\bsrc\\s*=` also matches `data-src=`, because `-` is a non-word character
    so `\\b` matches inside it. A block carrying `data-src` was classified as
    external and never parsed -- so a real syntax error inside one exited 0.

    The control matters: a genuine `src=` must still skip, or the fix has
    simply disabled the external-script exemption.
    """
    hidden = tmp_path / "datasrc.html"
    hidden.write_text('<script data-src="x">\nconst broken = (;\n</script>\n')
    assert findings_for(hidden), "a data-src attribute hid a syntax error from the gate"

    external = tmp_path / "realsrc.html"
    external.write_text('<script src="/static/x.js"></script>\n')
    assert findings_for(external) == [], "a genuine external script is no longer exempt"


def test_an_unquoted_type_attribute_is_classified_correctly(tmp_path):
    """HTML permits unquoted attribute values, so `type=application/json` was
    read as an empty type and the JSON parsed as JavaScript -- a false RED on a
    data block, in a gate with no override.

    Both directions: the data block must be exempt, and an unquoted
    `type=module` must still be parsed as a module rather than skipped.
    """
    data = tmp_path / "unquoted_json.html"
    data.write_text('<script type=application/json>\n{"a": 1}\n</script>\n')
    assert findings_for(data) == [], "an unquoted non-JS type was parsed as JavaScript"

    module = tmp_path / "unquoted_module.html"
    module.write_text("<script type=module>\nexport const a = 1;\n</script>\n")
    assert findings_for(module) == [], "an unquoted type=module was misclassified"
    kinds = [k for _l, k, _b in
             check_test_traps._iter_script_blocks(module.read_text())]
    assert kinds == ["module"], "expected the block parsed AS a module, got %r" % kinds


def test_a_nested_block_literal_is_a_KNOWN_false_red(tmp_path):
    """A second unmaskable case, pinned rather than left to be rediscovered.

    `{{` opens a Jinja interpolation as far as the mask is concerned, so a
    nested block in a function body is eaten whole:

        function f() {{ return 1; }}   ->   function f() __JINJA__

    Same family as the split-expression limit above. Recorded so the next
    person to hit it finds a decision instead of filing a bug, and so that
    teaching the mask to handle it makes this fail loudly.
    """
    path = tmp_path / "nested_block.html"
    path.write_text("<script>\nfunction f() {{ return 1; }}\n</script>\n")
    assert findings_for(path), (
        "the nested-block-literal false RED is a documented known limit; if it "
        "now passes, the mask improved and _mask_jinja's docstring is stale"
    )


def test_node_options_in_the_environment_cannot_make_the_checker_execute(tmp_path, monkeypatch):
    """SB-2 / AC-SEC-1's headline property, enforced by the code that claims it.

    `node` honours NODE_OPTIONS on every invocation, and it accepts
    `--require`. Without stripping it, "parses without executing" would be a
    property of whoever happened to set the environment, not of this checker.

    The control matters as much as the assertion: the same NODE_OPTIONS is
    first shown to DO fire against a bare `node --check`, so a green result
    below cannot be the mechanism silently not working.
    """
    if not _NODE_ON_THIS_MACHINE:
        pytest.skip("node is not installed; the control below cannot run")
    marker = tmp_path / "executed"
    payload = tmp_path / "payload.js"
    payload.write_text("require('fs').writeFileSync(%r, 'x');\n" % str(marker))
    node_options = f"--require {payload}"

    control = subprocess.run(
        ["node", "--check", "-"], input="const a = 1;\n", text=True,
        capture_output=True, env={**os.environ, "NODE_OPTIONS": node_options},
    )
    if control.returncode != 0 or not marker.exists():
        pytest.skip("NODE_OPTIONS --require did not fire on this node; test would prove nothing")
    marker.unlink()

    path = tmp_path / "plain.html"
    path.write_text("<script>\nconst a = 1;\n</script>\n")
    monkeypatch.setenv("NODE_OPTIONS", node_options)
    assert findings_for(path) == []
    assert not marker.exists(), "NODE_OPTIONS executed code during a parse-only check"


def test_external_script_with_empty_body_is_not_flagged(tmp_path):
    path = tmp_path / "ext.html"
    path.write_text('<script src="/static/x.js"></script>\n')
    assert findings_for(path) == []


@requires_node
def test_module_script_with_top_level_import_export_is_not_flagged(tmp_path):
    """AC-QA-72b — the real case is base.html:47. Node 22+ auto-detects
    module syntax for a FILE but not for `--check -` on stdin (measured), so
    this pins the intended handling rather than the interpreter's default."""
    body = "import { x } from './x.js';\nexport const y = x + 1;\n"
    path = tmp_path / "mod.html"
    path.write_text(f'<script type="module">\n{body}</script>\n')
    assert findings_for(path) == []


@requires_node
def test_the_same_import_export_as_a_classic_script_is_flagged(tmp_path):
    body = "import { x } from './x.js';\nexport const y = x + 1;\n"
    path = tmp_path / "classic_mod.html"
    path.write_text(f"<script>\n{body}</script>\n")
    findings = findings_for(path)
    assert findings, "import/export outside a module script must be a syntax error"


def test_non_js_script_type_is_not_parsed_as_js(tmp_path):
    path = tmp_path / "data.html"
    path.write_text('<script type="application/json">\n{ this is not JSON either }\n</script>\n')
    assert findings_for(path) == []


def test_discovers_at_least_15_nonempty_script_bodies_by_directory_walk():
    """AC-QA-71's positive anchor: discovery must be a real walk, not a list,
    so extraction stopping silently is itself detectable."""
    total = 0
    for root in (TEMPLATES_ROOT, LOGIN_HTML.parent):
        for path in root.rglob("*.html"):
            for _line, _kind, body in check_test_traps._iter_script_blocks(
                path.read_text(encoding="utf-8")
            ):
                if body.strip():
                    total += 1
    assert total >= 15, f"only {total} non-empty <script> bodies discovered"


@requires_node
def test_a_brand_new_template_is_discovered_by_the_walk_not_a_list(tmp_path):
    """No hardcoded file list: a template check_test_traps.py has never seen
    is still scanned and its broken block still flagged."""
    nested = tmp_path / "some" / "new" / "widget.html"
    nested.parent.mkdir(parents=True)
    nested.write_text("<script>\nconst x = (;\n</script>\n")
    assert nested in check_test_traps.iter_files([tmp_path])
    assert findings_for(nested), "a new template's broken script was not flagged"


@requires_node
def test_output_reports_parsed_and_skipped_block_counts(tmp_path):
    (tmp_path / "a.html").write_text(
        '<script src="/x.js"></script>\n'
        "<script>\nconst ok = 1;\n</script>\n"
    )
    result = run_checker(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "template scripts: 1 parsed, 1 skipped" in result.stdout, result.stdout
    assert f"skipped {tmp_path / 'a.html'}:1" in result.stdout, result.stdout


def test_one_parser_invocation_per_nonempty_block_not_per_line(tmp_path, monkeypatch):
    """AC-QA-79: bounded at one `node` call per block, whatever its length."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(check_test_traps.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(check_test_traps.subprocess, "run", fake_run)
    path = tmp_path / "many_lines.html"
    body_lines = "\n".join(f"const x{i} = {i};" for i in range(200))
    path.write_text(
        f"<script>\n{body_lines}\n</script>\n<script src='/x.js'></script>\n<script>\nconst y = 1;\n</script>\n"
    )
    list(findings_for(path))
    assert len(calls) == 2, f"expected one call per non-src block (2), got {len(calls)}"


def test_missing_node_is_a_hard_named_failure_not_a_silent_skip(tmp_path, monkeypatch):
    """AC-QA-74. Simulated regardless of whether this machine has node, so the
    guard is proven even where it can never fire for real."""
    monkeypatch.setattr(check_test_traps.shutil, "which", lambda name: None)
    path = tmp_path / "any.html"
    path.write_text("<script>\nconst x = 1;\n</script>\n")
    findings = findings_for(path)
    assert findings, "a missing node produced no finding at all — a silent skip"
    assert "node" in findings[0][1].lower()


def test_missing_node_fails_the_cli_and_never_prints_passed(tmp_path):
    """The CLI-level half of AC-QA-74, with `node` actually removed from
    PATH — the same shape `make check-traps`/CI would hit."""
    (tmp_path / "t.html").write_text("<script>\nconst x = 1;\n</script>\n")
    env = dict(os.environ)
    node_path = shutil.which("node")
    if node_path:
        # shutil.which returns a PATH entry joined with the name, unresolved —
        # so the matching directory to drop is the plain parent, NOT the
        # symlink-resolved one (node is a symlink into ../Cellar/... on
        # Homebrew, which is never itself a PATH entry).
        node_dir = str(Path(node_path).parent)
        env["PATH"] = os.pathsep.join(
            p for p in env.get("PATH", "").split(os.pathsep) if p and p != node_dir
        )
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env,
    )
    assert result.returncode != 0
    assert "node" in (result.stdout + result.stderr).lower()
    assert "test-trap check passed" not in result.stdout


def test_unrelated_parser_failure_is_reported_as_could_not_run(tmp_path, monkeypatch):
    """AC-QA-75: a non-syntax-error parser failure must say "could not run",
    never be misread as a syntax error at a fabricated line."""
    monkeypatch.setattr(check_test_traps.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(
        check_test_traps.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 2, stdout="", stderr="node: fatal crash\n"),
    )
    path = tmp_path / "x.html"
    path.write_text("<script>\nconst x = 1;\n</script>\n")
    findings = findings_for(path)
    assert findings, findings
    message = findings[0][1]
    assert "could not run" in message
    assert "SyntaxError" not in message


def test_a_killed_parser_is_reported_as_could_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(check_test_traps.shutil, "which", lambda name: "/usr/bin/node")

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=10)

    monkeypatch.setattr(check_test_traps.subprocess, "run", raise_timeout)
    path = tmp_path / "x.html"
    path.write_text("<script>\nconst x = 1;\n</script>\n")
    findings = findings_for(path)
    assert findings and "could not run" in findings[0][1], findings


@requires_node
def test_the_check_parses_without_executing(tmp_path):
    """AC-SEC-1's own fixture: a body that touches a file must be reported as
    parsing fine, AND the file must not exist — `node --check` parses only."""
    marker = tmp_path / "pwned"
    path = tmp_path / "exploit.html"
    path.write_text(
        "<script>\n"
        f"require('child_process').execSync('touch {marker}');\n"
        "</script>\n"
    )
    findings = findings_for(path)
    assert findings == [], f"a syntactically valid block was flagged: {findings}"
    assert not marker.exists(), "node --check EXECUTED the body instead of only parsing it"


def test_no_temp_file_is_used_for_the_script_body():
    """AC-SEC-3: the body is fed on stdin only — grep the actual source for
    `tempfile`/a hard-coded `/tmp` path, not just an assertion about behaviour."""
    import inspect

    src = "".join(
        inspect.getsource(fn)
        for fn in (
            check_test_traps._node_check,
            check_test_traps.check_html_template,
            check_test_traps._iter_script_blocks,
        )
    )
    assert "tempfile" not in src
    assert "/tmp" not in src
    assert "NamedTemporaryFile" not in src


def test_no_per_file_allowlist_in_the_rule_itself():
    """AC-SIMP-7: no template filename may be special-cased by the mechanism
    (as opposed to being cited in a comment as evidence, this file's own
    convention — e.g. docker-entrypoint.sh above)."""
    import inspect

    src = "".join(
        inspect.getsource(fn)
        for fn in (
            check_test_traps._iter_script_blocks,
            check_test_traps._mask_jinja,
            check_test_traps._node_check,
            check_test_traps.check_html_template,
        )
    )
    # Match the MECHANISM, not the prose. This file's convention is to cite the
    # exact file that proved a bug as evidence (`docker-entrypoint.sh` in
    # DEFAULT_ROOTS above; `base.html:238` in the unterminated-block comment).
    # Matching raw source made this guard punish the evidence rather than the
    # defect -- and the cheapest way to make it green would have been deleting
    # the comment, which is the wrong direction entirely.
    #
    # `ast.unparse` drops comments; docstrings are stripped explicitly below.
    # Both are documentation, and the AC-SIMP-7 criterion is about the
    # MECHANISM special-casing a file. What remains is code plus operative
    # string literals -- exactly the surface a real allowlist has to live in.
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            body[0] = ast.Expr(value=ast.Constant(value=""))
    code = ast.unparse(ast.fix_missing_locations(tree))
    for banned in (".html", "ALLOWLIST", "movie_detail", "suggestions", "wanted", "base.html"):
        assert banned not in code, f"per-file special-casing found: {banned!r}"


def test_login_html_is_in_scope_and_clean():
    """AC-QA-78: login.html sits outside couchpotato/ui/templates/, so it
    must be a deliberate root, not silently excluded."""
    scanned = {str(p) for p in check_test_traps.iter_files(check_test_traps.DEFAULT_ROOTS)}
    assert str(LOGIN_HTML) in scanned, "login.html is not in DEFAULT_ROOTS' scan"


@requires_node
def test_login_html_parses_clean():
    assert findings_for(LOGIN_HTML) == []


def test_every_template_with_a_non_src_inline_script_is_scanned():
    """AC-A11Y-6: enumerate the real tree at runtime and fail if any file
    with an inline <script> is not covered by DEFAULT_ROOTS' walk."""
    scanned = {str(p) for p in check_test_traps.iter_files(check_test_traps.DEFAULT_ROOTS)}
    missing = []
    for root in TEMPLATE_ROOTS:
        for path in root.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            for _line, kind, body in check_test_traps._iter_script_blocks(text):
                if kind != "skip-src" and body.strip() and str(path) not in scanned:
                    missing.append(str(path))
    assert not missing, f"templates with inline <script> not scanned: {missing}"


def test_a_new_template_in_either_render_root_is_covered_by_the_walk(tmp_path):
    """The M1 regression, pinned as a test rather than as a fixed filename.

    `iter_files` walking a directory is already covered elsewhere; what was
    broken was DEFAULT_ROOTS naming `couchpotato/templates/login.html`
    instead of its directory, so the walk stopped at whatever happened to be
    there the day the rule was written. Asserting on DEFAULT_ROOTS' shape is
    what catches a regression to a filename, because a file entry can never
    cover a sibling.
    """
    for root in TEMPLATE_ROOTS:
        assert root in check_test_traps.DEFAULT_ROOTS, (
            "%s is a live Jinja render root but is not in DEFAULT_ROOTS" % root
        )
        assert root.is_dir(), "%s must be entered as a DIRECTORY, not a file" % root
