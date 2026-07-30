#!/usr/bin/env python3
"""Static guard against *false green* test results.

The expensive failures on this repo have not been red tests — they have been
green ones. `CLAUDE.md` rules 9–11 cover the judgement half of that problem;
this script covers the mechanically detectable half, because a weaker agent
forgets prose but cannot get past a command that exits non-zero (global standard
#9). Pure stdlib — no PyYAML, no deps — so it runs in the `lint` CI job as-is.

Checks performed:

  1. **jsdom layout-zero reads.** The vitest environment is jsdom
     (`vitest.config.ts`), which performs NO layout:
     ``getBoundingClientRect()``, ``offsetHeight``/``offsetWidth``,
     ``offsetTop``/``offsetLeft``, ``scrollHeight``/``scrollWidth``,
     ``clientHeight``/``clientWidth``, ``window.innerHeight``/``innerWidth``
     and ``getComputedStyle()`` all read 0 (or an empty computed style) no
     matter what a browser would render. So
     ``expect(el.scrollTop).toBe(el.scrollHeight)`` passes as ``0 === 0``
     whether the code under test works or not. Flagged in ``tests/unit/**``
     specs UNLESS the same file stubs that exact property — via
     ``Object.defineProperty(..., '<prop>', ...)`` or a direct assignment
     (``Element.prototype.<prop> = ...``). A file that demonstrably stubs a
     property has already confronted the blind spot for it. Same-file/
     same-property is deliberately a heuristic rather than data-flow analysis:
     the failure mode being prevented is "nobody stubbed this at all", not "the
     stub was subtly wrong".

     ``tests/e2e/**`` is out of scope — Playwright drives a real browser.

  2. **Exit-code-eating pipes.** ``pytest ... | tail`` exits with *tail's*
     status, which is 0 essentially always, so a failing suite reports success.
     Flagged when a test/verification runner is piped into a filter and
     ``pipefail`` is not in effect for that shell: a ``.sh`` file, a Makefile
     recipe (every recipe line is its own shell, so pipefail is never
     inherited), or a GitHub workflow ``run:`` block.

  3. **Shell gates missing ``set -e`` / ``set -u``.** ``set -e`` alone continues
     past a typo'd variable. ``pipefail`` is deliberately NOT demanded here — it
     is only meaningful for a pipeline, and check 2 already reports the
     pipelines that matter, at the exact line. (Demanding it generally produced
     false positives on ``case a|b)`` alternations and on ``|`` inside quoted
     strings.)

  4. **Git hooks must be executable.** A non-executable file under
     ``.githooks/`` is silently ignored by git, so the gate it implements never
     runs and every "the hook will catch it" assumption is void. Not
     hypothetical: ``.githooks/pre-push`` was mode 0644 in this tree, i.e. the
     pre-push gate had been inert.

Correctness notes for the checks themselves — each was a live bug found in
review, and each has a regression test:

  * ``pipefail`` detection strips comments FIRST. Searching raw text meant the
    word "pipefail" in a ``# TODO: use set -o pipefail`` comment silenced the
    check — a false green inside the false-green detector.
  * Backslash continuations are joined before matching, so a ``pytest`` command
    split across two physical lines before its ``| tail`` is not missed.
  * A workflow step's ``shell:`` is honoured. GitHub's *default* shell is
    ``bash -e`` (no pipefail), but an explicit ``shell: bash`` is
    ``bash --noprofile --norc -eo pipefail``, and flagging that would mean a
    blocking gate rejecting correct config.
  * All YAML block-scalar indicators are recognised (``|``, ``>``, ``|-``,
    ``>+``, ``|2``, ...), not just the four most common.
  * JS comment stripping is a real state machine over strings and template
    literals, so an unmatched ``/*`` inside a line comment, or a
    ``'http://…'`` URL, cannot silence the rest of the file.

Usage:
    python scripts/check_test_traps.py [path ...]

With no arguments, scans the default roots below. Exits 0 with a one-line
summary when clean, or non-zero after printing one ``file:line: message`` per
finding.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_ROOTS = [
    REPO_ROOT / "tests" / "unit",
    REPO_ROOT / "scripts",
    REPO_ROOT / ".githooks",
    REPO_ROOT / ".github" / "workflows",
    REPO_ROOT / "Makefile",
]

# ── Rule 1: jsdom layout-zero properties ────────────────────────────────────

GEOMETRY_PROPERTIES = (
    "getBoundingClientRect",
    "getClientRects",
    "getComputedStyle",
    "offsetHeight",
    "offsetWidth",
    "offsetTop",
    "offsetLeft",
    "scrollHeight",
    "scrollWidth",
    "clientHeight",
    "clientWidth",
    "innerHeight",
    "innerWidth",
)

# `scrollTop`/`scrollLeft` are deliberately absent: they are writable and jsdom
# persists whatever you assign, so reading one back is not inherently vacuous.

VITEST_SPEC_SUFFIXES = (".test.ts", ".test.js", ".spec.ts", ".spec.js")

# ── Rule 2: runners whose exit code must not be swallowed ───────────────────

RUNNER_RE = re.compile(
    r"\b("
    r"pytest|py\.test"
    r"|playwright(?!\s+install)"
    r"|vitest"
    r"|stryker"
    r"|mutmut"
    r"|ruff"
    r"|npm\s+(?:run\s+)?test[\w:-]*"
    r"|npm\s+run\s+\S*(?:test|verify|lint)\S*"
    r"|make\s+(?:verify|test)[\w-]*"
    r"|verify\.sh"
    r")\b"
)

# Filters that discard the upstream exit status when they succeed.
FILTER_RE = re.compile(r"\|\s*(tail|head|grep|tee|awk|sed|sort|uniq|wc|cat|less|more|jq)\b")

# `set -o pipefail`, `set -euo pipefail`, `set -eu -o pipefail`, ...
PIPEFAIL_RE = re.compile(r"set\s+(?:-[a-zA-Z]+\s+)*-[a-zA-Z]*o\s+pipefail\b")

SHELL_SUFFIXES = (".sh",)
WORKFLOW_SUFFIXES = (".yml", ".yaml")

# Interpreters where a shell pipeline's exit code is not the concern.
NON_SHELL_INTERPRETERS = ("python", "pwsh", "powershell", "node", "ruby", "perl", "cmd")


# ── Comment stripping (correctness-critical — see module docstring) ──────────


def strip_shell_comments(line: str) -> str:
    """Remove a `#` comment, respecting single and double quotes."""
    out = []
    quote = None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def strip_js_comments(text: str) -> list[str]:
    """Return code-only lines, line numbering preserved.

    A state machine over strings, template literals and both comment forms. The
    previous line-local regex approach let an unmatched `/*` inside a `//`
    comment latch block-comment state for the rest of the file, and let
    `'http://x/'` eat the remainder of its own line — both silently disabling
    rule 1. A regex cannot see string context; this can.
    """
    lines = text.split("\n")
    out = [""] * len(lines)
    row, col = 0, 0
    state = "code"  # code | line_comment | block_comment | squote | dquote | template

    while row < len(lines):
        line = lines[row]
        if col >= len(line):
            if state == "line_comment":
                state = "code"
            row += 1
            col = 0
            continue

        ch = line[col]
        nxt = line[col + 1] if col + 1 < len(line) else ""

        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line_comment"
                col += 2
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                col += 2
            else:
                if ch == "'":
                    state = "squote"
                elif ch == '"':
                    state = "dquote"
                elif ch == "`":
                    state = "template"
                out[row] += ch
                col += 1
            continue

        if state == "line_comment":
            col = len(line)
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                col += 2
            else:
                col += 1
            continue

        # Inside a string. Keep the characters (a geometry read cannot live in a
        # string literal, and keeping them preserves column meaning), but track
        # the terminator, honouring backslash escapes.
        out[row] += ch
        if ch == "\\":
            if col + 1 < len(line):
                out[row] += line[col + 1]
                col += 2
            else:
                col += 1
            continue
        if (
            (state == "squote" and ch == "'")
            or (state == "dquote" and ch == '"')
            or (state == "template" and ch == "`")
        ):
            state = "code"
        col += 1

    return out


def join_continuations(lines: list[str]) -> list[tuple[int, str]]:
    """Join backslash-continued lines, keeping the FIRST line's number.

    `pytest tests/ \\` followed by `| tail -20` is one logical command; matching
    line-by-line misses the pipe entirely.
    """
    joined: list[tuple[int, str]] = []
    buf = ""
    start = 1
    for line_no, raw in enumerate(lines, start=1):
        stripped = raw.rstrip()
        if not buf:
            start = line_no
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        joined.append((start, buf + raw))
        buf = ""
    if buf:
        joined.append((start, buf))
    return joined


def _has_pipefail(text: str) -> bool:
    """True only if `pipefail` is actually SET — a mention in a comment is not."""
    cleaned = "\n".join(strip_shell_comments(ln) for ln in text.split("\n"))
    return bool(PIPEFAIL_RE.search(cleaned))


def _is_vitest_spec(path: Path) -> bool:
    if not path.name.endswith(VITEST_SPEC_SUFFIXES):
        return False
    # Playwright E2E specs run in a real browser — geometry is real there.
    return "e2e" not in {part.lower() for part in path.parts}


def _stubbed_properties(text: str) -> set[str]:
    """Properties the file stubs, by either sanctioned mechanism."""
    stubbed = set()
    for match in re.finditer(r"""Object\.defineProperty\s*\([^,]+,\s*['"]([A-Za-z]+)['"]""", text):
        stubbed.add(match.group(1))
    for match in re.finditer(r"""\.([A-Za-z]+)\s*=\s*(?:function\b|\([^)]*\)\s*=>|vi\.fn)""", text):
        stubbed.add(match.group(1))
    return stubbed


def check_vitest_spec(path: Path, text: str):
    stubbed = _stubbed_properties(text)

    for line_no, line in enumerate(strip_js_comments(text), start=1):
        for prop in GEOMETRY_PROPERTIES:
            if prop in stubbed:
                continue
            if re.search(rf"\b{re.escape(prop)}\b", line):
                yield (
                    line_no,
                    f"reads `{prop}` in a jsdom test without stubbing it — jsdom performs "
                    f"no layout, so this reads 0/empty regardless of the code under test "
                    f"(a false green). Stub it with Object.defineProperty(..., '{prop}', ...) "
                    f"or assert the behaviour in a Playwright E2E spec instead.",
                )


def _runner_pipe_message(is_posix_sh: bool) -> str:
    remedy = (
        "Capture the status explicitly (`cmd > out; status=$?`) or drop the pipe — "
        "`set -o pipefail` and ${PIPESTATUS[0]} are bash-only and this is a "
        "/bin/sh script."
        if is_posix_sh
        else "Add `set -o pipefail`, or capture the status explicitly with ${PIPESTATUS[0]}."
    )
    return (
        "pipes a test/verification command into a filter without `pipefail` — "
        "the pipeline reports the filter's exit status, so a failing run looks "
        "like a passing one. " + remedy
    )


def check_shell_script(path: Path, text: str):
    """Rules 2 and 3 for a shell script."""
    lines = text.split("\n")
    shebang = lines[0] if lines else ""
    is_posix_sh = "/bin/sh" in shebang and "bash" not in shebang
    has_pipefail = _has_pipefail(text)

    # Rule 3 — the gate's own options. pipefail is intentionally not required
    # here; rule 2 reports the pipelines that actually matter, at their line.
    if shebang.startswith("#!") and ("bash" in shebang or "/bin/sh" in shebang):
        missing = []
        set_lines = " ".join(
            strip_shell_comments(ln) for ln in lines if re.match(r"\s*set\s+-", ln)
        )
        if not re.search(r"set\s+-[a-zA-Z]*e", set_lines):
            missing.append("-e (exit on error)")
        if not re.search(r"set\s+-[a-zA-Z]*u|nounset", set_lines):
            missing.append("-u (error on unset variable)")
        if missing:
            yield (
                1,
                "shell script is missing "
                + ", ".join(missing)
                + " — `set -e` alone lets a gate continue past a failure. Use "
                + ("`set -eu`." if is_posix_sh else "`set -euo pipefail`."),
            )

    # Rule 2 — piped runners.
    if not has_pipefail:
        for line_no, logical in join_continuations(lines):
            line = strip_shell_comments(logical)
            if RUNNER_RE.search(line) and FILTER_RE.search(line):
                yield (line_no, _runner_pipe_message(is_posix_sh))


def check_makefile(path: Path, text: str):
    """Every recipe line runs in its own shell, so pipefail is never inherited."""
    for line_no, logical in join_continuations(text.split("\n")):
        # Only recipe lines (tab-indented) are shell. A variable assignment or a
        # comment containing a pipe is not a command.
        if not logical.startswith("\t"):
            continue
        line = strip_shell_comments(logical)
        if RUNNER_RE.search(line) and FILTER_RE.search(line) and not _has_pipefail(line):
            yield (
                line_no,
                "Makefile recipe pipes a test/verification command into a filter — each "
                "recipe line is its own shell, so `pipefail` is never in effect and the "
                "target passes even when the runner fails. Use "
                "`set -o pipefail; <cmd> | <filter>` on the line, or drop the pipe.",
            )


# A YAML block scalar: | or > with any chomping/indentation indicator.
BLOCK_SCALAR_RE = re.compile(r"^[|>](?:[+-]?\d*|\d*[+-]?)$")

# The optional `-?` matters: a step's first key carries the list dash, as in
# `- shell: bash`, and anchoring on `shell:` alone silently misses it — which
# made the guard flag correct `shell: bash` steps.
SHELL_KEY_RE = re.compile(r"^\s*-?\s*shell:\s*(.+?)\s*$")


def _shell_sets_pipefail(shell_value: str) -> bool | None:
    """Does this `shell:` value have pipefail set?

    None means "not a POSIX-ish shell at all" (python, pwsh, ...), so the
    pipeline check does not apply.

    GitHub's documented mapping: `bash` -> `bash --noprofile --norc -eo pipefail
    {0}`; `sh` -> `sh -e {0}`. A custom command string is taken at its word.
    """
    value = shell_value.strip().strip("'\"").lower()
    if any(value.startswith(interp) for interp in NON_SHELL_INTERPRETERS):
        return None
    if value == "bash":
        return True
    return "pipefail" in value


def check_workflow(path: Path, text: str):
    """GitHub's DEFAULT shell is `bash -e` — pipefail is not set unless asked for."""
    lines = text.split("\n")

    # A workflow- or job-level `defaults: run: shell:` applies to every step that
    # does not override it. Detected coarsely: any `defaults:` block declaring a
    # pipefail-setting shell suppresses the check for the file. A false negative
    # here is far cheaper than a blocking gate rejecting a correct workflow.
    defaults_pipefail = False
    in_defaults = False
    defaults_indent = 0
    for raw in lines:
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if stripped.startswith("defaults:"):
            in_defaults = True
            defaults_indent = indent
            continue
        if in_defaults:
            if stripped and indent <= defaults_indent:
                in_defaults = False
            else:
                match = SHELL_KEY_RE.match(raw)
                if match and _shell_sets_pipefail(match.group(1)):
                    defaults_pipefail = True

    findings: list[tuple[int, str]] = []

    def step_shell_pipefail(run_index: int) -> bool | None:
        """Find a `shell:` in the same step as the `run:` at ``run_index``.

        A step spans from the nearest preceding `- ` list item to the next one.
        """
        start = 0
        for i in range(run_index, -1, -1):
            if re.match(r"^\s*-\s", lines[i]):
                start = i
                break
        end = len(lines)
        for i in range(run_index + 1, len(lines)):
            if re.match(r"^\s*-\s", lines[i]):
                end = i
                break
        for i in range(start, end):
            match = SHELL_KEY_RE.match(lines[i])
            if match:
                return _shell_sets_pipefail(match.group(1))
        return False

    def scan_block(block: list[tuple[int, str]], pipefail: bool | None) -> None:
        if pipefail is None:
            return  # not a shell whose pipeline status we police
        body = "\n".join(body_line for _n, body_line in block)
        if pipefail or _has_pipefail(body):
            return
        # Map the joined logical line back to its real file line number.
        for local_no, logical in join_continuations([b for _n, b in block]):
            actual = block[local_no - 1][0] if 0 < local_no <= len(block) else block[0][0]
            cleaned = strip_shell_comments(logical)
            if RUNNER_RE.search(cleaned) and FILTER_RE.search(cleaned):
                findings.append(
                    (
                        actual,
                        "workflow step pipes a test/verification command into a filter "
                        "without `pipefail` — GitHub's default shell is `bash -e`, which "
                        "does not set it, so the step passes even when the runner fails. "
                        "Add `set -o pipefail` at the top of the run block, or declare "
                        "`shell: bash` (which is `-eo pipefail`).",
                    )
                )

    i = 0
    while i < len(lines):
        raw = lines[i]
        run_match = re.match(r"(\s*)-?\s*run:\s*(.*)$", raw)
        if not run_match:
            i += 1
            continue

        indent = len(raw) - len(raw.lstrip())
        inline = run_match.group(2).strip()
        pipefail = step_shell_pipefail(i)
        if pipefail is False and defaults_pipefail:
            pipefail = True

        if inline and not BLOCK_SCALAR_RE.match(inline):
            scan_block([(i + 1, inline)], pipefail)  # single-line `run:`
            i += 1
            continue

        block: list[tuple[int, str]] = []
        j = i + 1
        while j < len(lines):
            body_line = lines[j]
            if body_line.strip():
                body_indent = len(body_line) - len(body_line.lstrip())
                if body_indent <= indent:
                    break
            block.append((j + 1, body_line))
            j += 1
        scan_block(block, pipefail)
        i = max(j, i + 1)

    yield from findings


def check_git_hook(path: Path):
    """Rule 4: a non-executable hook is silently ignored by git."""
    if not os.access(path, os.X_OK):
        yield (
            1,
            "git hook is not executable, so git SILENTLY IGNORES it and the gate it "
            "implements never runs. `chmod +x` it and commit the mode. (This file was "
            "mode 0644 in the tree — which is exactly how a pre-push gate stops "
            "existing without anyone noticing.)",
        )


def check_file(path: Path):
    """Yield (line_no, message) for every trap found in ``path``."""
    is_hook = path.parent.name == ".githooks"
    if is_hook:
        yield from check_git_hook(path)

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    if _is_vitest_spec(path):
        yield from check_vitest_spec(path, text)
    elif path.name == "Makefile" or path.name.endswith(".mk"):
        yield from check_makefile(path, text)
    elif path.name.endswith(WORKFLOW_SUFFIXES):
        yield from check_workflow(path, text)
    elif path.name.endswith(SHELL_SUFFIXES) or is_hook:
        yield from check_shell_script(path, text)


def iter_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if any(part in {"node_modules", "__pycache__", ".venv"} for part in path.parts):
                    continue
                files.append(path)
    return sorted(set(files))


def main(argv: list[str]) -> int:
    roots = [Path(p) for p in argv] if argv else DEFAULT_ROOTS
    files = iter_files(roots)

    total = 0
    for path in files:
        for line_no, message in check_file(path):
            print(f"{path}:{line_no}: {message}")
            total += 1

    if total:
        print(
            f"\ntest-trap check FAILED: {total} finding(s) across {len(files)} file(s) scanned",
            file=sys.stderr,
        )
        return 1

    print(f"test-trap check passed ({len(files)} file(s) scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
