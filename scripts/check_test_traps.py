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

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs it; see .github/workflows/ci.yml
    yaml = None

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

# Matches `set -o pipefail`, `set -euo pipefail`, `set -eu -o pipefail`,
# `set -o errexit -o pipefail`, `set -eox pipefail`. Anything containing an `o`
# in the flag cluster (or a preceding `-o word`) followed by the literal
# `pipefail` counts; `set +o pipefail` deliberately does not.
# Note `o` may sit ANYWHERE in the flag cluster: `set -eox pipefail` really does
# enable pipefail (verified: `set -eox pipefail; set -o | grep pipefail` -> on),
# so anchoring on a cluster that *ends* in `o` missed it and flagged a correct
# script.
PIPEFAIL_RE = re.compile(
    r"set\s+(?:[+-][a-zA-Z]*(?:\s+[a-z]+)?\s+)*-[a-zA-Z]*o[a-zA-Z]*\s+pipefail\b"
)

SHELL_SUFFIXES = (".sh",)
WORKFLOW_SUFFIXES = (".yml", ".yaml")

# Interpreters where a shell pipeline's exit code is not the concern.
NON_SHELL_INTERPRETERS = ("python", "pwsh", "powershell", "node", "ruby", "perl", "cmd")


# ── Comment stripping (correctness-critical — see module docstring) ──────────


def strip_shell_comments(line: str, blank_strings: bool = False) -> str:
    """Remove a `#` comment, respecting single and double quotes.

    ``blank_strings`` additionally replaces string *contents* with spaces. That
    matters for pipefail detection: `echo "hint: add set -o pipefail"` silenced
    rule 2 for a whole file — the same false-green class as the `# TODO`
    comment that prompted the comment-stripping in the first place.

    Shell quoting rules, not C's: a backslash is NOT an escape inside single
    quotes, so `'\\'` is a complete string.
    """
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if quote == '"' and ch == "\\" and i + 1 < len(line):
                out.append("  " if blank_strings else line[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
                out.append(ch)
            else:
                out.append(" " if blank_strings else ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < len(line):
            out.append(line[i : i + 2])
            i += 2
            continue
        if ch == "#":
            break
        out.append(ch)
        i += 1
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
            # A single- or double-quoted JS string cannot contain a raw newline,
            # so an unterminated one means we mis-detected the opening quote —
            # most often a quote inside a regex literal such as /['"]/. Reset at
            # end of line so the damage is bounded to that line instead of
            # latching for the rest of the file (which turned real `//` comments
            # into reported geometry reads). Template literals DO span lines, so
            # they are deliberately not reset.
            if state in ("squote", "dquote"):
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
    """True only if `pipefail` is actually SET.

    A mention in a comment does not count, and neither does one inside a string
    literal — both were live false-green holes.
    """
    cleaned = "\n".join(
        strip_shell_comments(ln, blank_strings=True) for ln in text.split("\n")
    )
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
    # `vi.spyOn(window, 'getComputedStyle')` is the idiomatic vitest stub and was
    # being flagged as unstubbed.
    for match in re.finditer(r"""(?:vi|jest)\.spyOn\s*\([^,]+,\s*['"]([A-Za-z]+)['"]""", text):
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


def _has_real_pipeline(lines: list[str]) -> bool:
    """Is there an actual `cmd | cmd` pipeline?

    Excludes `||`, `|` inside quotes, and `case a|b)` alternations — the three
    things that made a naive `"|" in line` check reject correct scripts.
    """
    for raw in lines:
        line = strip_shell_comments(raw, blank_strings=True)
        if re.match(r"\s*case\s", line) or re.search(r"^\s*[^()]*\)\s*$", line):
            continue
        if re.search(r"(?<!\|)\|(?!\|)", line):
            return True
    return False


def check_shell_script(path: Path, text: str):
    """Rules 2 and 3 for a shell script."""
    lines = text.split("\n")
    shebang = lines[0] if lines else ""
    is_posix_sh = "/bin/sh" in shebang and "bash" not in shebang
    has_pipefail = _has_pipefail(text)

    # Rule 2 candidates are computed first: when a runner pipe is present, the
    # specific finding is reported at its line and `pipefail` is dropped from the
    # generic rule-3 message, so one fix is never reported twice.
    runner_pipes = []
    if not has_pipefail:
        for line_no, logical in join_continuations(lines):
            cleaned = strip_shell_comments(logical)
            if RUNNER_RE.search(cleaned) and FILTER_RE.search(cleaned):
                runner_pipes.append(line_no)

    # Rule 3 — the gate's own options.
    #
    # `pipefail` IS required when the script contains a real pipeline. That
    # requirement was briefly dropped because it false-positived on `case a|b)`
    # and on `|` inside quoted strings — but that lost genuine coverage: a
    # `docker build ... | tee` or `./guardrails.sh | grep -c FAIL` swallows its
    # exit code just as thoroughly as pytest does, and RUNNER_RE will never list
    # every command. Now that comment/string stripping is quote-aware, the
    # requirement is back without the false positives.
    if shebang.startswith("#!") and ("bash" in shebang or "/bin/sh" in shebang):
        missing = []
        set_lines = " ".join(
            strip_shell_comments(ln) for ln in lines if re.match(r"\s*set\s+-", ln)
        )
        if not re.search(r"set\s+-[a-zA-Z]*e", set_lines):
            missing.append("-e (exit on error)")
        if not re.search(r"set\s+-[a-zA-Z]*u|nounset", set_lines):
            missing.append("-u (error on unset variable)")
        if not is_posix_sh and not has_pipefail and _has_real_pipeline(lines) and not runner_pipes:
            missing.append("pipefail (a failing command in a pipeline is otherwise ignored)")
        if missing:
            yield (
                1,
                "shell script is missing "
                + ", ".join(missing)
                + " — `set -e` alone lets a gate continue past a failure. Use "
                + ("`set -eu`." if is_posix_sh else "`set -euo pipefail`."),
            )

    for line_no in runner_pipes:
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


def _iter_run_steps(node, inherited_shell=None):
    """Yield (run_scalar_node, effective_shell) for every `run:` in a workflow.

    Walks the composed YAML node graph, so `shell:` is resolved by real document
    structure and `defaults.run.shell` inheritance — not by scanning nearby lines.

    This replaced a hand-rolled scanner that walked backwards to the nearest
    `- ` to find a step boundary. Two review rounds each found a fresh way to
    break it: a `- ` at the start of a block-scalar body truncated the step and
    hid a `shell:` declared after `run:` (flagging a CORRECT workflow), and a
    `# comment` after `shell: bash` made it misread the value. Both are
    structural mistakes that a real parser cannot make, which is why the parser
    won over a third round of patches.
    """
    if isinstance(node, yaml.MappingNode):
        keys = {k.value: v for k, v in node.value if isinstance(k, yaml.ScalarNode)}

        # `defaults: run: shell:` at this level applies to everything below it.
        shell_here = inherited_shell
        defaults = keys.get("defaults")
        if isinstance(defaults, yaml.MappingNode):
            for dk, dv in defaults.value:
                if dk.value == "run" and isinstance(dv, yaml.MappingNode):
                    for rk, rv in dv.value:
                        if rk.value == "shell" and isinstance(rv, yaml.ScalarNode):
                            shell_here = rv.value

        # A step: `run:` plus optionally its own `shell:`, in any key order.
        run_node = keys.get("run")
        if isinstance(run_node, yaml.ScalarNode):
            step_shell = shell_here
            own = keys.get("shell")
            if isinstance(own, yaml.ScalarNode):
                step_shell = own.value
            yield run_node, step_shell

        for _k, value in node.value:
            yield from _iter_run_steps(value, shell_here)

    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _iter_run_steps(item, inherited_shell)


def check_workflow(path: Path, text: str):
    """GitHub's DEFAULT shell is `bash -e` — pipefail is not set unless asked for."""
    if yaml is None:
        yield (
            1,
            "cannot check this workflow: PyYAML is not installed, so the "
            "exit-code-eating-pipe check cannot run. Install it "
            "(`pip install 'pyyaml>=6.0'`, and it is in requirements-dev.txt). "
            "Failing loudly rather than skipping silently — a check that quietly "
            "does nothing is the exact failure this script exists to prevent.",
        )
        return

    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        yield (1, f"could not parse as YAML, so it was not checked for piped runners: {exc}")
        return
    if root is None:
        return

    for run_node, shell_value in _iter_run_steps(root):
        pipefail = _shell_sets_pipefail(shell_value) if shell_value else False
        if pipefail is None:
            continue  # not a shell whose pipeline status we police
        body = run_node.value
        if pipefail or _has_pipefail(body):
            continue

        # For a block scalar (`|`/`>`) the value starts on the line AFTER the
        # indicator; for an inline value it starts on the mark's own line.
        block = run_node.style in ("|", ">")
        first_content_line = run_node.start_mark.line + (1 if block else 0)

        lines = body.split("\n")
        for local_no, logical in join_continuations(lines):
            cleaned = strip_shell_comments(logical)
            if RUNNER_RE.search(cleaned) and FILTER_RE.search(cleaned):
                yield (
                    first_content_line + local_no,
                    "workflow step pipes a test/verification command into a filter "
                    "without `pipefail` — GitHub's default shell is `bash -e`, which "
                    "does not set it, so the step passes even when the runner fails. "
                    "Add `set -o pipefail` at the top of the run block, or declare "
                    "`shell: bash` (which is `-eo pipefail`).",
                )


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
