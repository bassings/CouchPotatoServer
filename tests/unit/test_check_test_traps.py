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
  3. **`set -e` alone is not enough.** A shell gate missing `pipefail`/`-u`
     silently continues past a failed pipeline or a typo'd variable.

The tests below drive the checker over synthetic files (so each rule is pinned
independently of the current tree) and also assert it is clean on the real tree,
which is what makes it usable as a blocking gate.
"""

import subprocess
import sys
from pathlib import Path

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
    script = tmp_path / "gate.sh"
    script.write_text("#!/bin/bash\nset -e\nls | wc -l\npytest tests/unit\n")

    messages = messages_for(script)
    assert any("pipefail" in m for m in messages)
    assert any("-u" in m or "nounset" in m for m in messages)


def test_does_not_demand_pipefail_from_a_script_with_no_pipelines(tmp_path):
    """pipefail is meaningless without a pipeline — don't manufacture busywork."""
    script = tmp_path / "simple.sh"
    script.write_text("#!/usr/bin/env bash\nset -eu\necho hello\nexit 0\n")

    assert findings_for(script) == []


def test_accepts_set_euo_pipefail_in_any_order(tmp_path):
    for body in (
        "#!/usr/bin/env bash\nset -euo pipefail\necho hi\n",
        "#!/usr/bin/env bash\nset -eu\nset -o pipefail\necho hi\n",
        "#!/usr/bin/env bash\nset -o pipefail\nset -euo nounset\necho hi\n",
    ):
        script = tmp_path / "s.sh"
        script.write_text(body)
        assert findings_for(script) == [], body


def test_posix_sh_scripts_are_not_asked_for_pipefail(tmp_path):
    """`set -o pipefail` is not POSIX — a /bin/sh script must not be flagged for it.

    The Docker entrypoint is `#!/bin/sh` by hard rule 8, so this exemption is
    load-bearing, not hypothetical.
    """
    script = tmp_path / "entrypoint.sh"
    script.write_text("#!/bin/sh\nset -eu\nexec \"$@\"\n")

    assert findings_for(script) == []


# ── Whole-tree behaviour ────────────────────────────────────────────────────


def test_checker_is_clean_on_the_real_tree():
    """It has to be green on the repo to be a blocking gate."""
    result = run_checker()
    assert result.returncode == 0, (
        f"check_test_traps.py is not clean on the tree:\n{result.stdout}\n{result.stderr}"
    )


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
