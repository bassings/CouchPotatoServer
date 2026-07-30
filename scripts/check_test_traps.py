#!/usr/bin/env python3
"""Static guard against *false green* test results.

The expensive failures on this repo have not been red tests — they have been
green ones. `CLAUDE.md` rules 9–11 cover the judgement half of that problem;
this script covers the mechanically detectable half, because a weaker agent
forgets prose but cannot get past a command that exits non-zero (global standard
#9). Pure stdlib, so it runs as a fast standalone gate.

Checks performed:

  1. **jsdom layout-zero reads.** The vitest environment is jsdom
     (`vitest.config.ts`), which performs NO layout:
     ``getBoundingClientRect()``, ``offsetHeight``/``offsetWidth``,
     ``offsetTop``/``offsetLeft``, ``scrollHeight``/``scrollWidth``,
     ``clientHeight``/``clientWidth``, ``window.innerHeight``/``innerWidth``
     and ``getComputedStyle()`` all read 0 (or an empty computed style) no
     matter what a browser would render. So
     ``expect(el.scrollTop).toBe(el.scrollHeight)`` passes as ``0 === 0``
     whether the code under test works or not. Flagged in
     ``tests/unit/**`` specs UNLESS the same file stubs that exact property —
     via ``Object.defineProperty(..., '<prop>', ...)`` or a direct assignment
     (``Element.prototype.<prop> = ...``). A file that demonstrably stubs a
     property has already confronted the blind spot for it; further reads of
     the *same* property in the *same* file are overwhelmingly likely to be
     reads of that stub. Same-file/same-property is deliberately a heuristic
     rather than data-flow analysis: the failure mode being prevented is
     "nobody stubbed this at all", not "the stub was subtly wrong".

     ``tests/e2e/**`` is out of scope — Playwright drives a real browser where
     these values are real.

  2. **Exit-code-eating pipes.** ``pytest ... | tail`` exits with *tail's*
     status, which is 0 essentially always, so a failing suite reports success.
     This has bitten this repo when piping Playwright output. Flagged when a
     test/verification runner is piped into a filter and ``pipefail`` is not in
     effect for that shell — in a ``.sh`` file (no ``set -o pipefail``), a
     Makefile recipe (every recipe line is its own shell, so pipefail is never
     inherited), or a GitHub workflow ``run:`` block (GitHub's default shell is
     ``bash -e``, which does NOT set pipefail).

  3. **Shell gates missing ``set -euo pipefail``.** ``set -e`` alone continues
     past a failed pipeline and past a typo'd variable. ``#!/bin/sh`` scripts
     are exempt from the ``pipefail`` half — it is not POSIX, and hard rule 8
     requires the Docker entrypoint to be ``#!/bin/sh``.

Usage:
    python scripts/check_test_traps.py [path ...]

With no arguments, scans the default roots below. Arguments may be individual
files or directories (scanned recursively). Exits 0 with a one-line summary when
clean, or non-zero after printing one ``file:line: message`` per finding.
"""

from __future__ import annotations

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

PIPEFAIL_RE = re.compile(r"set\s+-[a-z]*o\s+pipefail|set\s+-o\s+pipefail|set\s+-[a-zA-Z]*\bpipefail")

SHELL_SUFFIXES = (".sh",)
WORKFLOW_SUFFIXES = (".yml", ".yaml")


def _strip_js_comments(line: str) -> str:
    """Blank out // and /* */ comment text on a single line (line-local only)."""
    line = re.sub(r"//.*$", "", line)
    line = re.sub(r"/\*.*?\*/", "", line)
    line = re.sub(r"/\*.*$", "", line)
    return line


def _has_pipefail(text: str) -> bool:
    return bool(PIPEFAIL_RE.search(text))


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
    in_block_comment = False

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw
        if in_block_comment:
            if "*/" in line:
                line = line.split("*/", 1)[1]
                in_block_comment = False
            else:
                continue
        if "/*" in line and "*/" not in line.split("/*", 1)[1]:
            in_block_comment = True
        line = _strip_js_comments(line)

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


def check_shell_script(path: Path, text: str):
    """Rules 2 and 3 for a shell script.

    The two rules share one fix (`set -o pipefail`), so they are deliberately
    de-duplicated: when a *runner* pipe is present, the specific rule-2 finding
    is reported at that line and `pipefail` is dropped from the generic rule-3
    message. One concern, one actionable finding, at the most useful line.
    """
    lines = text.splitlines()
    shebang = lines[0] if lines else ""
    is_posix_sh = "/bin/sh" in shebang and "bash" not in shebang
    has_pipefail = _has_pipefail(text)

    # Rule 2 — piped runners (the specific, high-value case).
    runner_pipes = []
    if not has_pipefail:
        for line_no, raw in enumerate(lines, start=1):
            line = re.sub(r"#.*$", "", raw)
            if RUNNER_RE.search(line) and FILTER_RE.search(line):
                runner_pipes.append(line_no)

    # A script with no pipelines at all does not need pipefail.
    has_pipeline = any(
        re.search(r"(?<!\|)\|(?!\|)", re.sub(r"#.*$", "", ln)) for ln in lines
    )

    # Rule 3 — the gate's own options.
    if shebang.startswith("#!") and ("bash" in shebang or "/bin/sh" in shebang):
        missing = []
        set_lines = " ".join(ln for ln in lines if re.match(r"\s*set\s+-", ln))
        if not re.search(r"set\s+-[a-zA-Z]*e", set_lines):
            missing.append("-e (exit on error)")
        if not re.search(r"set\s+-[a-zA-Z]*u|nounset", set_lines):
            missing.append("-u (error on unset variable)")
        if not is_posix_sh and not has_pipefail and has_pipeline and not runner_pipes:
            missing.append("pipefail (a failing command in a pipeline is otherwise ignored)")
        if missing:
            yield (
                1,
                "shell script is missing "
                + ", ".join(missing)
                + " — `set -e` alone lets a gate continue past a failure. "
                + ("Use `set -eu` (pipefail is not POSIX)." if is_posix_sh
                   else "Use `set -euo pipefail`."),
            )

    for line_no in runner_pipes:
        yield (
            line_no,
            "pipes a test/verification command into a filter without `pipefail` — "
            "the pipeline reports the filter's exit status, so a failing run looks "
            "like a passing one. Add `set -o pipefail`, or capture the status "
            "explicitly with ${PIPESTATUS[0]}.",
        )


def check_makefile(path: Path, text: str):
    """Every recipe line runs in its own shell, so pipefail is never inherited."""
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.startswith("\t"):
            continue
        line = re.sub(r"#.*$", "", raw)
        if RUNNER_RE.search(line) and FILTER_RE.search(line) and not _has_pipefail(line):
            yield (
                line_no,
                "Makefile recipe pipes a test/verification command into a filter — each "
                "recipe line is its own shell, so `pipefail` is never in effect and the "
                "target passes even when the runner fails. Use "
                "`set -o pipefail; <cmd> | <filter>` on the line, or drop the pipe.",
            )


def check_workflow(path: Path, text: str):
    """GitHub's default shell is `bash -e` — pipefail is NOT set."""
    lines = text.splitlines()
    block_indent = None
    block_lines: list[tuple[int, str]] = []
    findings = []

    def flush(block):
        if not block:
            return
        body = "\n".join(ln for _n, ln in block)
        if _has_pipefail(body):
            return
        for line_no, line in block:
            stripped = re.sub(r"#.*$", "", line)
            if RUNNER_RE.search(stripped) and FILTER_RE.search(stripped):
                findings.append(
                    (
                        line_no,
                        "workflow step pipes a test/verification command into a filter "
                        "without `pipefail` — GitHub's default shell is `bash -e`, which "
                        "does not set it, so the step passes even when the runner fails. "
                        "Add `set -o pipefail` at the top of the run block.",
                    )
                )

    for line_no, raw in enumerate(lines, start=1):
        indent = len(raw) - len(raw.lstrip())
        run_match = re.match(r"\s*-?\s*run:\s*(.*)$", raw)

        if block_indent is not None and raw.strip() and indent <= block_indent:
            flush(block_lines)
            block_lines = []
            block_indent = None

        if run_match:
            flush(block_lines)
            block_lines = []
            inline = run_match.group(1).strip()
            if inline and inline not in ("|", ">", "|-", ">-"):
                # Single-line `run:` — its own shell, no pipefail possible.
                flush([(line_no, inline)])
                block_indent = None
            else:
                block_indent = indent
            continue

        if block_indent is not None:
            block_lines.append((line_no, raw))

    flush(block_lines)
    yield from findings


def check_file(path: Path):
    """Yield (line_no, message) for every trap found in ``path``."""
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
    elif path.name.endswith(SHELL_SUFFIXES) or (
        path.parent.name == ".githooks" and path.is_file()
    ):
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
