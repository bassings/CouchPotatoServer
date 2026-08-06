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

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check_test_traps.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_test_traps  # noqa: E402


def run_checker(*args):
    """Run the checker as a subprocess, the way CI and verify.sh invoke it."""
    return subprocess.run(
        [sys.executable, str(CHECKER), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def findings_for(path: Path):
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
