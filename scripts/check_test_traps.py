#!/usr/bin/env python3
"""Static guard against *false green* test results.

The expensive failures on this repo have not been red tests — they have been
green ones. `CLAUDE.md` rules 9–11 cover the judgement half of that problem;
this script covers the mechanically detectable half, because a weaker agent
forgets prose but cannot get past a command that exits non-zero (global standard
#9). Requires PyYAML (in requirements-dev.txt, and pip-installed in the `lint`
job) to parse workflow files with a real parser; everything else is stdlib.

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

  3. **Shell gates missing ``set -e`` / ``set -u`` / ``pipefail``.** ``set -e``
     alone continues past a typo'd variable, and without ``pipefail`` a failing
     command mid-pipeline is ignored. ``pipefail`` is demanded only when the file
     actually contains a pipeline, and only when check 2 has not already reported
     that exact line (one fix, one finding). It covers the pipelines check 2
     cannot: ``docker build | tee`` and ``./guardrails.sh | grep -c FAIL`` swallow
     an exit code just as thoroughly as ``pytest`` does, and ``RUNNER_RE`` will
     never list every command. ``#!/bin/sh`` files are exempt from the
     ``pipefail`` half — it is not POSIX (hard rule 8 requires a ``sh``
     entrypoint).

  4. **Git hooks must be executable.** A non-executable file under
     ``.githooks/`` is silently ignored by git, so the gate it implements never
     runs and every "the hook will catch it" assumption is void. Not
     hypothetical: ``.githooks/pre-push`` was mode 0644 in this tree, i.e. the
     pre-push gate had been inert.

  5. **Orphaned test files.** A tracked file named ``test_*.py`` (pytest.ini's
     own ``python_files`` convention) that no pytest invocation in
     ``scripts/verify.sh`` or ``.github/workflows/ci.yml`` actually executes.
     Not hypothetical either: ``tests/integration/`` sat exactly like this ,
     "covered" by ``pytest.ini``'s ``testpaths = tests`` on paper, invoked by
     no runner in practice: until the PR that added this rule also wired it
     in. Deliberately keyed on the **runner invocations themselves**, not on
     ``testpaths``: a rule anchored on ``testpaths`` would have passed against
     that orphaned suite the whole time, which makes it vacuous. Enumerates
     candidates via ``git ls-files`` (never a filesystem walk, so an untracked
     local scratch file cannot trip it or be swept into scope), reports only
     (never deletes, moves or modifies anything), and honours a small,
     comment-required ``ORPHAN_ALLOWLIST`` for files that are deliberately
     local-only by design (``tests/local/test_real_database.py``, gated on a
     39 MB machine-local backup that will never exist in CI).

  6. **Vacuous E2E guards.** ``expect(`` inside an
     ``if (await x.isVisible()/count()) { ... }`` block under ``tests/e2e/**``
     — that shape lets a Playwright test pass while asserting nothing, because
     the guard can be false with nothing outside it to catch the gap (T1.4,
     AGENTS.md's ``lens-qa`` note: "the pattern was removed once in
     ``movie-detail.spec.ts`` and still exists elsewhere" — this rule retires
     the need for a human to keep re-finding it). Opt out with a same-line
     trailing comment, ``// vacuous-guard-ok: <reason>``, for a guard whose
     precondition is genuinely outside the test's control (a fixture gap, an
     environment-dependent provider state) rather than something the test
     could make unconditional — see ``movie-detail.spec.ts``'s "Mark Failed &
     Re-search requires confirmation when shown" for a real example. The
     opt-out itself is checked: present with no text after the colon, it is
     flagged too, so ``// vacuous-guard-ok:`` cannot become a silent universal
     bypass.

  7. **Unquoted `>`/`>=` on a `pip install` line.** ``pip install ruff>=0.9.0``
     in a GitHub workflow ``run:`` block is not a version constraint: an
     unquoted ``>`` is shell stdout redirection, so the shell actually runs
     ``pip install ruff`` (floating latest) and writes stdout to a file
     literally named ``=0.9.0``. Not hypothetical: this is exactly how
     ``.github/workflows/ci.yml`` floated ruff in two jobs while looking
     pinned (T1.5). Flagged when a line contains ``pip install``/``pip3
     install`` AND an unquoted ``>`` (tracked with a small quote-aware scan,
     so ``pip install 'pyyaml>=6.0'`` is correctly left alone — the ``>``
     there is literal text inside the quotes). Scope is deliberately narrow:
     only lines that already match ``pip install``/``pip3 install`` are
     considered, so an unrelated ``echo x > file`` is never touched. That
     narrowness has one accepted false positive: a deliberate
     ``pip install -r requirements.txt > some.log`` redirect would also be
     flagged. No such pattern exists in this codebase today, and quoting the
     redirect target is not meaningfully worse than the status quo, so this is
     a documented trade-off, not a bug to route around.

  8. **A template's inline ``<script>`` does not parse.** A dropped ``+`` in
     ``suggestions.html`` broke a whole Alpine component and only four E2E
     tests going red caught it (PR #230) — nothing else looks at template JS.
     See ``check_html_template``.

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

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs it; see .github/workflows/ci.yml
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_ROOTS = [
    REPO_ROOT / "tests" / "unit",
    REPO_ROOT / "tests" / "e2e",
    REPO_ROOT / "scripts",
    REPO_ROOT / ".githooks",
    REPO_ROOT / ".github" / "workflows",
    REPO_ROOT / "Makefile",
    # Repo-root shell scripts. Named individually rather than globbed,
    # because a glob evaluated at import time silently covers nothing when a
    # file is renamed -- and this list is exactly where that already went
    # wrong: docker-entrypoint.sh is PID 1 in the shipped image, was the ONE
    # file in the repo failing this script's own shell rule, and the rule
    # could not see it. `test_default_roots_all_exist_and_are_covered` fails
    # if any entry here stops existing.
    REPO_ROOT / "docker-entrypoint.sh",
    REPO_ROOT / "couchpotato" / "ui" / "templates",
    # The OTHER live Jinja render root (couchpotato/__init__.py:48-51). The
    # DIRECTORY, not `login.html`: it held only that file when this rule was
    # written, so naming the file looked equivalent -- and it silently was
    # not. Review proved it by executing: a new template dropped in beside
    # login.html with `const broken = (;` in a <script> block was never
    # scanned and the gate exited 0. Naming a file here means the walk stops
    # at today's contents, which is the same "glob evaluated once" failure
    # the comment above warns about, in a different shape.
    REPO_ROOT / "couchpotato" / "templates",
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
        # blank_strings=True, like the pipefail check three rules up. Without
        # it, `set -e; echo "run with set -u for stricter checking"` counted
        # the `-u` INSIDE the string and the file came back clean -- the exact
        # false-green class strip_shell_comments' own docstring records
        # (`echo "hint: add set -o pipefail"` silenced rule 2 for a whole
        # file), reintroduced two rules away by omitting one keyword.
        #
        # Kept per-line rather than joined, so a `--` on one `set` line cannot
        # terminate option parsing for a later one.
        set_lines_list = [
            strip_shell_comments(ln, blank_strings=True)
            for ln in lines if re.search(r"(?:^|[;&|])\s*set\s+-", ln)
        ]
        # Tokenised rather than pattern-matched against the whole line.
        # Two false positives on correct scripts, both from a BLOCKING gate,
        # and both because the old regexes anchored on `set -<cluster>`:
        #
        #   set -o errexit -o nounset   -> flagged "missing -e". `nounset` was
        #                                  accepted as a long form and
        #                                  `errexit` was not, so the checker
        #                                  rejected the most explicit correct
        #                                  spelling of what it demands.
        #   set -e -u                   -> flagged "missing -u". Separate
        #                                  clusters do not sit adjacent to the
        #                                  word `set`, so only the first was
        #                                  ever read.
        #
        # A false positive here is not a harmless nag: the reader "fixes" a
        # correct script to satisfy the gate, or learns to bypass the gate.
        enabled = set()
        for set_line in set_lines_list:
            # Split into COMMANDS first, and read only the arguments of the
            # ones that are actually `set`. Tokenising the whole line counted
            # flags belonging to the next command: measured,
            # `set -e; sort -u /etc/hosts` came back CLEAN, because `sort`'s
            # `-u` was read as `set -u`. A blocking gate passing a script that
            # genuinely lacks `-u` -- and a REGRESSION, since the regex this
            # tokeniser replaced flagged it correctly.
            #
            # Splitting also removes the trailing `;` that `set -o nounset;`
            # used to carry, so no separate strip is needed, and it makes `--`
            # end options for ITS OWN command rather than for the rest of the
            # line (`set -- alpha; set -eu` was being reported as missing
            # both).
            for command in re.split(r"[;&|]+", set_line):
                tokens = command.split()
                if not tokens or tokens[0] != "set":
                    continue
                for token in tokens[1:]:
                    if token == "--":
                        # End of options: everything after it is a POSITIONAL
                        # parameter, not a flag. `set -- -e -u` sets $1 and $2
                        # and enables nothing; it was read as `set -eu`.
                        break
                    if token.startswith("-") and not token.startswith("--"):
                        # A flag cluster: `-eu`, `-e`, `-euo`. `+e` DISABLES
                        # and is deliberately not read as enabling.
                        enabled.update(token[1:])
                    elif token in ("errexit", "nounset"):
                        # Long forms, as in `set -o errexit`.
                        enabled.add({"errexit": "e", "nounset": "u"}[token])

        if "e" not in enabled:
            missing.append("-e (exit on error)")
        if "u" not in enabled:
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


# ── Rule 7: unquoted `>`/`>=` on a `pip install` line ───────────────────────

PIP_INSTALL_RE = re.compile(r"\bpip3?\s+install\b")

PIP_INSTALL_REDIRECT_MESSAGE = (
    "unquoted `>`/`>=` on a `pip install` line — the shell parses a bare `>` as "
    "stdout redirection, not part of the argument, so e.g. "
    "`pip install ruff>=0.9.0` actually runs `pip install ruff` (floating "
    "latest) and writes stdout to a file literally named `=0.9.0`. Quote the "
    "requirement so `>`/`>=` is passed to pip as literal text: "
    "`pip install 'pkg==X.Y.Z'`."
)


def _has_unquoted_redirect(line: str) -> bool:
    """True if `line` contains a `>` that sits outside single/double quotes.

    A small quote-tracking scan, same shape as `strip_shell_comments`'s quote
    handling: walk the line, flip in/out of a quoted region on `'`/`"`, and
    only count a `>` seen while not inside one. `pip install 'pyyaml>=6.0'`
    must NOT trip this — the `>` there is literal text the shell hands to pip
    unchanged — while `pip install ruff>=0.9.0` must, because that `>` is
    live shell syntax.
    """
    quote = None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == ">":
            return True
    return False


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

        # For a block scalar (`|`/`>`) the value starts on the line AFTER the
        # indicator; for an inline value it starts on the mark's own line.
        block = run_node.style in ("|", ">")
        first_content_line = run_node.start_mark.line + (1 if block else 0)

        lines = body.split("\n")

        # Rule 7 runs unconditionally per shell run-step — an unquoted `>`/`>=`
        # on a `pip install` line has nothing to do with pipefail, so it must
        # not be hidden behind the pipefail early-exit below.
        for local_no, logical in join_continuations(lines):
            cleaned = strip_shell_comments(logical)
            if PIP_INSTALL_RE.search(cleaned) and _has_unquoted_redirect(cleaned):
                yield (first_content_line + local_no, PIP_INSTALL_REDIRECT_MESSAGE)

        if pipefail or _has_pipefail(body):
            continue

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


# ── Rule 5: orphaned test files ─────────────────────────────────────────────

VERIFY_SH = REPO_ROOT / "scripts" / "verify.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Files this rule must never flag, each with the reason it is deliberately
# outside every runner invocation. Mirrors the .gitleaksignore-requires-a-
# comment convention (tests/unit/test_gitleaks_config.py enforces the same
# idea for secrets): an exemption without a reason on the line is not
# acceptable, because a bare filename in a set gives the next reader nothing
# to check it against.
ORPHAN_ALLOWLIST = {
    # Gated on /var/media/config_backup.zip, a ~39 MB machine-local backup
    # that will never exist on a CI runner (pytest.ini's addopts also carries
    # --ignore=tests/local for the same reason). See the file's own
    # docstring for the full rationale: it must not be wired into CI, by a
    # secret or otherwise: the real backup carries live credentials.
    "tests/local/test_real_database.py",
}

# Matches the word `pytest` and captures the rest of its logical line, so the
# path arguments that follow can be pulled out below.
PYTEST_INVOCATION_RE = re.compile(r"\bpytest\b(.*)$", re.MULTILINE)


def _tracked_test_files(repo_root: Path, require_git: bool = False) -> list[str]:
    """Tracked test-shaped ``.py`` files, via ``git ls-files``: NOT a filesystem walk.

    A filesystem walk would let an untracked local scratch file trip this
    guard, or be silently swept into scope by a later "fix the finding" pass.
    exactly the thing AC-DATA-21 rules out. ``git ls-files`` structurally
    cannot see a file nobody has ``git add``-ed.

    Both of pytest's default naming conventions count, ``test_*.py`` AND
    ``*_test.py``, even though this repo's ``pytest.ini`` narrows
    ``python_files`` to the first. Narrowing it is precisely what made the
    suffix form dangerous: three ``*_test.py`` files sat tracked under
    ``couchpotato/`` reading like a live suite while no runner and no
    collector would ever touch them, and one of them was sitting on a
    Python 3 port defect that 500'd the settings file browser. A rule that
    only knows the prefix declares that tree clean.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        # No git, or not a work tree. `scripts/test-local.sh` runs this suite
        # inside python:3.14-alpine, which has no git, and an unhandled
        # traceback there turned `make check-traps` into a crash and added
        # seven red tests to the optional container run.
        #
        # This IS the silent-skip that the PyYAML branch 500 lines up refuses
        # to do ("a check that quietly does nothing is the exact failure this
        # script exists to prevent"), so the asymmetry needs a reason rather
        # than a preference. The reason is that the two absences mean
        # different things. PyYAML is in requirements-dev.txt and the workflow
        # files are right there: its absence is a broken install, and a rule
        # that COULD run does not. Git's absence removes the rule's input
        # entirely -- "tracked" is not a property a tree has without it -- so
        # there is nothing to check rather than something being left unchecked.
        #
        # That reasoning would still be an excuse if it let the real gate skip
        # quietly, which is why `--require-git` exists and why scripts/verify.sh
        # and ci.yml both pass it. The authoritative runs cannot take this
        # branch at all; only the supplementary container run can, and it says
        # so on stderr when it does.
        if require_git:
            raise SystemExit(
                'test-trap check FAILED: --require-git was passed but git is '
                'unavailable (%s: %s), so the orphaned-test rule cannot run. '
                'This is the authoritative gate; it must not skip a rule '
                'silently.' % (type(exc).__name__, exc)
            )
        print('note: orphan-test check skipped, git is unavailable (%s: %s). '
              'Pass --require-git to make this an error.'
              % (type(exc).__name__, exc), file=sys.stderr)
        return []   # a LIST: the caller iterates this, and returning None
                    # here traded a traceback in one place for a TypeError
                    # in another.
    files = []
    for line in result.stdout.splitlines():
        path = line.strip()
        if not path or path.startswith("libs/"):
            continue  # vendored, not ours to flag
        name = Path(path).name
        if name.startswith("test_") and name.endswith(".py"):
            files.append(path)
        elif name.endswith("_test.py"):
            files.append(path)
    return sorted(files)


def _extract_pytest_path_args(text: str) -> tuple[set[str], set[str]]:
    """Directory roots and exact file paths passed to ``pytest`` invocations.

    Returns ``(dir_roots, file_args)``. A token is a directory root if it
    ends in ``/`` (``tests/unit/``), an exact file argument if it ends in
    ``.py``; anything else (flags, warning filters, shell control-flow words,
    message text) is ignored. Backslash-continued invocations are joined
    first, so a path on one physical line and its trailing ``|| fail ...`` on
    the next are read as one logical command.
    """
    dir_roots: set[str] = set()
    file_args: set[str] = set()
    for _start, logical in join_continuations(text.split("\n")):
        cleaned = strip_shell_comments(logical)
        for match in PYTEST_INVOCATION_RE.finditer(cleaned):
            for token in match.group(1).split():
                if token.startswith("-"):
                    continue
                if token.endswith("/"):
                    dir_roots.add(token)
                elif token.endswith(".py"):
                    file_args.add(token)
    return dir_roots, file_args


def _is_executed(path: str, dir_roots: set[str], file_args: set[str]) -> bool:
    if path in file_args:
        return True
    return any(path.startswith(root) for root in dir_roots)


def check_orphaned_test_files(
    repo_root: Path = REPO_ROOT,
    *,
    tracked_files: list[str] | None = None,
    runner_texts: list[str] | None = None,
    require_git: bool = False,
):
    """Rule 5: a tracked ``test_*.py`` file no runner invocation executes.

    Whole-repo by nature (needs the full ``git ls-files`` picture plus both
    runner files), so unlike rules 1-4 it is not dispatched per path from
    ``check_file``. ``tracked_files``/``runner_texts`` are injectable so
    tests can pin the rule's behaviour against synthetic fixtures without a
    real git repo or without depending on the state of this tree; production
    use (``main()``) calls it with no arguments and it reads the real repo.

    Yields ``(path, line_no, message)``: REPORTS ONLY. It never deletes,
    moves or modifies the orphaned file (AC-DATA-21); ``line_no`` is always 1
    since there is no meaningful line within the orphaned file itself to
    point at, consistent with how ``check_git_hook`` reports a whole-file
    property at line 1.

    ``runner_texts`` holds ONE entry per configured runner FILE (verify.sh,
    ci.yml: each of which may itself contain several pytest invocations). A
    path must be executed according to EVERY entry, not merely at least one:
    the local gate (verify.sh) and CI (ci.yml) are two independent gates, and
    a suite present in one but silently dropped from the other is still a
    real gap: the local gate no longer mirrors CI (hard rule 2), or CI is
    carrying dead weight nobody runs locally. Union semantics here would have
    let this exact mutation through: deleting the tests/integration/
    invocation from verify.sh alone, while it stayed in ci.yml, must still be
    caught.
    """
    if tracked_files is None:
        tracked_files = _tracked_test_files(repo_root, require_git=require_git)
    if runner_texts is None:
        runner_texts = [
            VERIFY_SH.read_text(encoding="utf-8"),
            CI_WORKFLOW.read_text(encoding="utf-8"),
        ]

    per_runner = [_extract_pytest_path_args(text) for text in runner_texts]

    for path in tracked_files:
        if path in ORPHAN_ALLOWLIST:
            continue
        if all(_is_executed(path, d, f) for d, f in per_runner):
            continue
        yield (
            path,
            1,
            f"`{path}` is named like a test (`test_*.py` or `*_test.py`) and "
            "is tracked, but no pytest invocation in scripts/verify.sh or "
            ".github/workflows/ci.yml executes it: it can rot indefinitely "
            "with nothing ever noticing (tests/integration/ did exactly "
            "this: 'covered' by pytest.ini's testpaths, run by no runner, "
            "until this rule and its fix). If it is deliberately local-only, "
            "add it to ORPHAN_ALLOWLIST in scripts/check_test_traps.py with "
            "a comment explaining why; otherwise wire it into a runner.",
        )


# ── Rule 6: vacuous E2E guards ───────────────────────────────────────────────

# AC-QA-42 scopes this to "under tests/e2e/**" — every `.ts`/`.js` file
# there, not only `*.spec.ts`: `helpers.ts` is exactly the kind of file a
# guard like this could land in via a shared helper, and a rule that only
# looked at spec files would miss it.
E2E_FILE_SUFFIXES = (".ts", ".js")

# A guard line: `if (`, an `await`, a call to `.isVisible(` or `.count(`
# somewhere in the condition, and the block opens on the SAME physical line
# (the codebase's own uniform style — every real instance found while writing
# this rule looked like `if (await x.isVisible()) {`). A condition split
# across lines is a false negative, same trade-off Rule 1 makes for
# same-file/same-property: catching the real, common shape beats chasing every
# way JS could theoretically be formatted.
GUARD_CONDITION_RE = re.compile(r"\bif\s*\(.*\bawait\b.*\.(?:isVisible|count)\s*\(")

# The same guard, written with the await hoisted to a previous line:
#
#     const count = await cardLinks.count();
#     ...
#     if (count > 1) {            <- GUARD_CONDITION_RE cannot see this
#
# Moving one expression up a line defeated the rule entirely, and the first
# new code written after the rule landed did exactly that
# (interactions.e2e.spec.ts). A rule introduced to retire a human review step
# has to survive the most obvious reformatting of the thing it looks for.
#
# Deliberately file-scoped rather than scope-aware: this is a regex-based
# guard, not a JS parser, and a name bound to an awaited count anywhere in a
# spec file is a name whose `if` is worth a written justification. The opt-out
# below is the pressure valve.
HOISTED_ASSIGNMENT_RE = re.compile(
    r"\b(?:const|let|var)?\s*([A-Za-z_$][\w$]*)\s*=\s*\(?\s*await\b[^;]*?\.(?:isVisible|count)\s*\(",
    re.DOTALL,
)

# WHAT THIS RULE STILL DOES NOT SEE, stated rather than left to silence.
# AGENTS.md retired a human review step in favour of this rule, so the next
# reviewer needs to know where the rule is a partial substitute. Measured by
# review 2026-08-06 against 12 hand-built specs; the first four below were
# closed in response, these remain open:
#
#   * a single-statement `if` with no braces and no `return`
#         if (shown)
#           await expect(...);
#   * a ternary                      shown ? await expect(...) : null;
#   * a logical-and short circuit    shown && await expect(...);
#   * a destructured binding         const { count } = await probe();
#   * `test.skip(total === 0, '...')` -- a skip, not an if
#
# None of THOSE is currently used in tests/e2e/**. But the list above is
# `if`-shaped only, and that is not the whole class. Review found the rule
# silent on ITERATION-COUNT guards, and one was live in the tree at the time:
#
#       for (let i = 0; i < Math.min(count, 5); i++) { ... expect(...) }
#
# runs zero times when `count` is 0, so every assertion inside it is skipped
# on exactly the input the test exists to catch. `while`, `switch` and a
# multi-line `if (` condition are silent for the same reason. Those instances
# were fixed by hand; the rule still cannot see the shape.
#
# And for a guard with NO braces at all, the region is approximated by
# indentation (see `_end_of_enclosing_block`), which is narrower than what
# `return` really does. Measured as silent: a non-braced guard nested one
# block deeper than the assertions it skips, and one whose body contains a
# line at column 0 (a template literal handed to `page.setContent` or
# `addInitScript`). Neither is live in tests/e2e/** today.
#
# Closing any of this properly needs a JS parser rather than more regexes,
# which is the point at which this rule should become an ESLint plugin rather
# than be extended again.

# A trailing comment naming why this specific guard cannot be made
# unconditional. Must be on the SAME line as the `if` (where every opt-out
# written for T1.4 puts it) — a comment three lines away could belong to
# anything, and "near the guard" is not a check the next edit can rely on.
OPT_OUT_RE = re.compile(r"//\s*vacuous-guard-ok:\s*(.*)$")

EXPECT_CALL_RE = re.compile(r"\bexpect\s*\(")


def _is_e2e_spec(path: Path) -> bool:
    if not path.name.endswith(E2E_FILE_SUFFIXES):
        return False
    return "e2e" in {part.lower() for part in path.parts}


def _hoisted_guard_names(cleaned_lines: list[str]) -> set[str]:
    """Names bound to an awaited `.isVisible()`/`.count()` anywhere in the file.

    Scanned over the JOINED text, not line by line: Prettier wraps a long
    assignment onto the next line (`const total =` / `  await x.count();`),
    and a per-line scan missed that, so reformatting alone defeated the rule.
    A bare reassignment (`total = await x.count();`) counts too.
    """
    return {
        match.group(1)
        for match in HOISTED_ASSIGNMENT_RE.finditer("\n".join(cleaned_lines))
    }


def _is_guard_if_line(line: str, hoisted_names: frozenset = frozenset()) -> bool:
    """A comment-stripped line that opens an isVisible()/count() guard block.

    Either written inline (`if (await x.count() > 1) {`) or with the await
    hoisted to an earlier line and the resulting name used here.
    """
    stripped = line.rstrip()
    if GUARD_CONDITION_RE.search(stripped) and stripped.endswith("{"):
        return True
    if not stripped.endswith("{"):
        # A non-braced `if` and an early `return` are ordinary JS that
        # Prettier will produce, and requiring a trailing `{` made both
        # invisible. Two live examples already exist in this suite
        # (`if (await delBtn.count() === 0) return;`), both in best-effort
        # teardown helpers, so neither is vacuous today -- but the rule
        # should see the shape.
        if not re.match(r"^\}?\s*(?:else\s+)?if\s*\(", stripped.lstrip()):
            return False
        return _condition_uses_a_guard_name(stripped, hoisted_names) or bool(
            GUARD_CONDITION_RE.search(stripped)
        )
    if not re.match(r"^\}?\s*(?:else\s+)?if\s*\(", stripped.lstrip()):
        return False
    return _condition_uses_a_guard_name(stripped, hoisted_names)


def _condition_uses_a_guard_name(line: str, hoisted_names) -> bool:
    condition = line[line.index("if"):] if "if" in line else ""
    return any(
        re.search(r"\b%s\b" % re.escape(name), condition) for name in hoisted_names
    )


def _else_branch_asserts(cleaned_lines: list[str], close_idx: int,
                         search_from: int = 0) -> bool:
    """Does the `else` attached to the guard closing at `close_idx` assert?

    If it does, the test cannot pass while asserting nothing, which is the
    whole property this rule protects -- and "assert both branches" is what
    the rule's own message recommends. Flagging it anyway meant live opt-outs
    existed purely to silence the rule for complying with its own advice.

    Two constraints, both learned by getting them wrong:

    - The `else` must follow the guard's CLOSING brace (`search_from` is the
      offset just past the guard's opening brace on a one-liner). Searching
      the whole line matched a guard's own `} else if (...)` prefix and read
      the guard's assertion as the else branch's.
    - The body is sliced from the ELSE's brace, not the line's first. On a
      one-liner the guard's own `{` comes first.

    Approximate, like the rest of this rule. A false negative only leaves the
    guard flagged, which the written opt-out already handles.
    """
    if close_idx >= len(cleaned_lines):
        return False

    segment = cleaned_lines[close_idx][search_from:]
    match = re.search(r"\}\s*else\b", segment)
    if match:
        rest, base_idx = segment[match.end():], close_idx
    else:
        # `}` and `else` on separate lines.
        if close_idx + 1 >= len(cleaned_lines):
            return False
        nxt = cleaned_lines[close_idx + 1]
        head = re.match(r"^\s*else\b", nxt)
        if not head:
            return False
        rest, base_idx = nxt[head.end():], close_idx + 1

    if "{" not in rest:
        return bool(EXPECT_CALL_RE.search(rest))

    else_close = _find_matching_brace(cleaned_lines, base_idx)
    body = rest[rest.index("{") + 1:] + "\n" + "\n".join(
        cleaned_lines[base_idx + 1:else_close]
    )
    return bool(EXPECT_CALL_RE.search(body))


def _end_of_enclosing_block(cleaned_lines: list[str], start_idx: int) -> int:
    """First line STRICTLY LESS indented than `start_idx`: where its block ends.

    Used only for guards with no `{` at all. Approximate by design -- this is a
    regex checker, not a parser -- and knowingly narrower than what `return`
    actually does, which is exit the whole function. Two consequences, both
    measured and both recorded in the module's WHAT THIS RULE STILL DOES NOT
    SEE list rather than left as silence:

    - a guard nested one block deeper than the assertions it skips is missed,
      because the region stops at the dedent;
    - a body containing a line at column 0 (a template literal passed to
      `page.setContent` or `addInitScript`) ends the region early.

    The alternative, which this replaced, was the brace matcher scanning to end
    of file: that flagged a teardown helper because an unrelated test lower in
    the file happened to contain `expect(`, and the documented remedy for a
    false positive is an opt-out comment, which is how a rule that replaced a
    human review step trains people to silence it.
    """
    indent = len(cleaned_lines[start_idx]) - len(cleaned_lines[start_idx].lstrip())
    for idx in range(start_idx + 1, len(cleaned_lines)):
        line = cleaned_lines[idx]
        if not line.strip():
            continue
        # STRICTLY less, not <=. An early return affects every statement that
        # follows it at the SAME level, which is the whole point of the shape;
        # stopping at the first sibling would find an empty body and flag
        # nothing. Dedenting past the guard is where the enclosing block ends,
        # and that is what keeps a sibling `test(...)` out of the body.
        if len(line) - len(line.lstrip()) < indent:
            return idx
    return len(cleaned_lines)


def _find_matching_brace(cleaned_lines: list[str], start_idx: int) -> int:
    """Index of the line whose `}` closes the `{` ending ``cleaned_lines[start_idx]``.

    Heuristic brace counting over comment-stripped source, same trade-off as
    the rest of this file: it does not additionally blank out string-literal
    contents, so a `{`/`}` character inside a JS string could in principle
    miscount. Every real guard body in this suite is plain Playwright
    calls and `expect(...)` assertions with no such string, so this is
    accepted rather than building a full parser for it.
    """
    depth = 0
    for idx in range(start_idx, len(cleaned_lines)):
        line = cleaned_lines[idx]
        segment = line if idx != start_idx else line[line.rfind("{"):]
        for ch in segment:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return idx
    return len(cleaned_lines) - 1


def check_e2e_spec_guards(path: Path, text: str):
    """Rule 6: ``expect(`` inside an ``if (await x.isVisible()/count())`` guard.

    That shape lets a Playwright test pass while asserting nothing: the guard
    can resolve false with no assertion outside it to catch the gap. Scans
    comment-stripped lines (``strip_js_comments``, shared with Rule 1) for a
    guard line, finds its matching closing brace, and flags any ``expect(``
    strictly between them — UNLESS the guard's own line carries a same-line
    ``// vacuous-guard-ok: <reason>`` comment, checked against the RAW (not
    comment-stripped) line, with a non-empty reason after the colon.

    Deliberately does not flag a guard with NO ``expect(`` inside it at all
    (a click-only conditional): that is a different, harder-to-detect shape
    (it requires knowing whether the enclosing `test(...)` asserts anything
    ANYWHERE, not just within this block) and is out of this rule's scope —
    T1.4 fixed those by hand; this rule guards against the shape regressing,
    which is the ``expect(`` case.
    """
    raw_lines = text.split("\n")
    cleaned_lines = strip_js_comments(text)
    hoisted_names = frozenset(_hoisted_guard_names(cleaned_lines))

    for idx, line in enumerate(cleaned_lines):
        if not _is_guard_if_line(line, hoisted_names):
            continue

        # Route on whether the line actually opens or contains a BLOCK, not on
        # whether it contains any brace. `"{" in line` was too coarse: a
        # non-braced guard whose CONDITION carries a balanced brace pair --
        # `if (await page.locator(`#movie-${id}`).count() === 0) return;`, or a
        # selector string containing `{}` -- went to the brace matcher, which
        # balanced on the guard line itself, collapsed the region to nothing
        # and reported clean. Measured across sixteen formatting shapes: that
        # spelling was caught before the previous round and silent after it,
        # while template literals already appear in two locator calls in this
        # suite.
        opens_block = line.count("{") > line.count("}")
        # Blank STRING CONTENTS first, then take the FIRST `){`.
        #
        # Taking the last match was the previous attempt, and it traded a
        # false positive for a false-negative class: a nested block opener
        # after the assertion on the guard line (`if (...) { await expect(x);
        # if (n > 1) { ... } }`) made the slice start past the `expect(`, so
        # the rule went silent on a genuinely vacuous guard. Wrong direction
        # for a false-green gate.
        #
        # The root cause of both is that `strip_js_comments` does not blank
        # string contents -- its own docstring says so -- so a literal `){`
        # inside a selector looked like a block opener. Blanking the contents
        # removes that without inventing a new heuristic, and the first match
        # is then genuinely the block opener. Length is preserved so the
        # offsets still index the real line.
        _blanked = re.sub(
            r"'[^']*'|\"[^\"]*\"|`[^`]*`",
            lambda m: m.group(0)[0] + "-" * (len(m.group(0)) - 2) + m.group(0)[-1],
            line,
        )
        inline_block = re.search(r"\)\s*\{", _blanked)
        if opens_block or inline_block:
            close_idx = _find_matching_brace(cleaned_lines, idx)
        else:
            # A non-braced guard (`if (cond) return;`) has no block, so the
            # brace matcher would scan to end of file and pick up an unrelated
            # test's `expect(` -- flagging a teardown helper that asserts
            # nothing, and teaching people to silence the rule with an opt-out.
            # The affected region is the rest of the ENCLOSING block, which
            # indentation approximates cheaply and without a JS parser.
            close_idx = _end_of_enclosing_block(cleaned_lines, idx)
        # For a one-line guard (`if (cond) { await expect(x).toBeVisible(); }`)
        # the braces balance on that line, so close_idx lands on it and the
        # joined slice below is empty -- the rule saw nothing in the most
        # compact spelling of the very shape it exists to catch.
        #
        # Sliced from the first `){` on the string-blanked line, which is the
        # block opener. NOT `index("{")`,
        # which picks up the condition's own brace (a template literal), and
        # NOT `rfind("{")`, which misses an `expect(` preceding a nested
        # object literal.
        # Slice whenever the line contains a block opener, INCLUDING when the
        # block also stays open. Gating this on `not opens_block` silenced a
        # braced guard whose `expect(` sits on the guard line while the block
        # closes later -- and arbitrarily so: the identical shape written
        # `} else if (...) {` was still flagged, because the leading `}`
        # balanced the count and sent it down the other path.
        inline_body = line[inline_block.end():] if inline_block else ""
        body = inline_body + "\n" + "\n".join(cleaned_lines[idx + 1:close_idx])
        if not EXPECT_CALL_RE.search(body):
            continue

        # If the ELSE branch also asserts, the test cannot pass while
        # asserting nothing, which is the whole property this rule protects.
        # The rule used to flag it anyway -- while its own message recommended
        # exactly that remedy ("assert both branches if it is not"), so two of
        # the suite's live opt-outs existed purely to silence the rule for
        # complying with its own advice. Every opt-out spent on a compliant
        # pattern devalues the ones spent on genuine exceptions.
        if _else_branch_asserts(
                cleaned_lines, close_idx,
                search_from=inline_block.end() if (inline_block and close_idx == idx) else 0):
            continue

        line_no = idx + 1
        raw_line = raw_lines[idx] if idx < len(raw_lines) else ""
        opt_out = OPT_OUT_RE.search(raw_line)

        if opt_out is None:
            yield (
                line_no,
                "expect( inside an `if (...isVisible()/count())` guard -- "
                "this can pass while asserting nothing, if the guard is ever "
                "false. Make the precondition unconditional if it is actually "
                "guaranteed, assert both branches if it is not, or opt out with "
                "a same-line `// vacuous-guard-ok: <reason>` comment if the "
                "guard is genuinely outside this test's control.",
            )
            continue

        reason = opt_out.group(1).strip()
        if not reason:
            yield (
                line_no,
                "`// vacuous-guard-ok:` opt-out has no reason after the colon -- "
                "a bare opt-out is indistinguishable from silencing the check, "
                "which is the exact false-green this rule exists to prevent. "
                "Say why the guard cannot be made unconditional or assert both "
                "branches instead.",
            )


#: pytest's caplog resolves a level given as a STRING through
#: `logging.getLevelName`, and `couchpotato/core/logger.py` calls
#: `logging.addLevelName(21, 'INFO')` to register INFO2. That overwrites
#: `_nameToLevel['INFO']` from 20 to 21, so `caplog.at_level('INFO')` sets the
#: threshold ABOVE every genuine `log.info()` record and captures none of them.
#:
#: Only INFO is remapped, which is why `'ERROR'` and `'WARNING'` are fine and
#: why no existing test has ever tripped over this.
_CAPLOG_LEVEL_METHODS = {"at_level", "set_level"}
_REMAPPED_LEVEL_NAMES = {"INFO"}


def check_python_test(path: Path, text: str):
    """Flag `caplog.at_level("INFO")`, which silently captures nothing.

    Parsed with `ast` rather than matched with a regex, deliberately: this
    checker's OWN test file contains the offending call inside string literals
    as fixture source, and a regex would flag itself. An AST walk only sees real
    calls, so the rule needs no self-exemption entry to stay clean.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in _CAPLOG_LEVEL_METHODS:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Constant) and arg.value in _REMAPPED_LEVEL_NAMES:
                yield (
                    node.lineno,
                    "caplog.%s(%r) captures NOTHING: couchpotato/core/logger.py "
                    "calls logging.addLevelName(21, 'INFO'), which remaps the "
                    "name so the string resolves to 21 and every real INFO "
                    "record (level 20) is dropped. Use the int form "
                    "logging.INFO instead. This reads as 'the code never "
                    "logged' and costs a debugging detour."
                    % (func.attr, arg.value),
                )


def _is_python_test(path: Path) -> bool:
    # Deliberately keyed on the `test_*.py` name alone, NOT on a `tests/` path
    # component: the rule must fire on a synthetic fixture written to a tmp_path
    # as well as on the real suite, and an earlier version that required
    # `"tests" in path.parts` passed its own tests vacuously for exactly that
    # reason -- the fixture was never scanned.
    return path.suffix == ".py" and path.name.startswith("test_")


# ── Rule 8: template <script> blocks must parse as JavaScript ──────────────

TEMPLATE_SUFFIXES = (".html",)

# Attribute values may legally contain `>`. A plain `[^>]*` stops at the first
# one, so `<script data-cfg="a > b">` splits mid-tag and ` b">` is prepended to
# the body -- turning correct code into a SyntaxError at a line number pointing
# at the tag. A blocking gate that is red on valid input is how people learn to
# reach for --no-verify, so quoted runs are consumed whole.
# The end tag is `</script\b[^>]*>`, and every part of that is load-bearing.
#
# HTML end tags may carry whitespace AND ignored attributes before the `>`, so
# `</script>` and even `</script\s*>` are both too narrow. This is not
# cosmetic: a block whose closer did not match was never parsed, was reported
# only as "skip-unterminated", and THE GATE EXITED 0 WITH A SYNTAX ERROR INSIDE
# IT -- a false green in the rule whose whole purpose is preventing false
# greens. Measured on `<script>const broken = (;</script >`: exit 0.
#
# CodeQL's py/bad-tag-filter found it, twice in a row: alert #94 for
# `</script >`, then #95 for `</script\t\n bar>` once the first was narrowed to
# `\s*`. This repo has now been round that loop on this same query more than
# once, so it is written in the general form rather than patched per report.
#
# The terminator is `(?=[\s/>])`, NOT `\b`. `\b` is a word boundary, and `-` is
# a non-word character, so it matched hyphenated custom elements -- both
# measured as false REDs before this fix:
#
#   * `<script-loader>...</script-loader>` was treated as a script block and its
#     contents parsed as JavaScript;
#   * a `"</script-loader>"` STRING inside a real block closed that block early,
#     reporting a SyntaxError at the wrong line.
#
# HTML5 terminates a tag name with whitespace, `/` or `>` and nothing else,
# which is what this now says.
SCRIPT_TAG_RE = re.compile(
    r"""<script(?=[\s/>])((?:[^>"']|"[^"]*"|'[^']*')*)>(.*?)</script(?=[\s/>])[^>]*>""",
    re.IGNORECASE | re.DOTALL,
)

# HTML comments are stripped before extraction, newlines preserved so later
# line numbers stay true. A commented-out `<script>` block is not code, and
# parsing one reported a SyntaxError against a block the browser never runs.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Counts `<script` openers so an UNTERMINATED one cannot vanish: without this a
# missing `</script>` means the block is not scanned, not flagged, and not
# listed as skipped -- an extraction failure that is invisible in the very
# output added to make extraction failures visible.
SCRIPT_OPEN_RE = re.compile(r"<script(?=[\s/>])", re.IGNORECASE)
# Attributes are TOKENISED, not pattern-matched out of the raw tag text, and
# both shortcuts this replaces were live defects:
#
#   * `\bsrc\s*=` also matched `data-src=`, because `-` is a non-word character
#     so `\b` matches inside it. A block carrying `data-src` was classified
#     external and never parsed -- measured: a real SyntaxError inside one
#     exited 0. Same false-green family as the `</script >` closer.
#   * a `type` pattern requiring quotes missed `type=application/json`, which
#     HTML permits unquoted, so a JSON data block was parsed as JavaScript and
#     reported as a SyntaxError. A false RED in a gate with no override.
ATTR_RE = re.compile(
    r"""(?:^|\s)([A-Za-z_:][-A-Za-z0-9_:.]*)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+))?"""
)


def _parse_attrs(attrs: str) -> dict:
    """`{name_lower: value_lower_unquoted}`; a bare attribute maps to ``""``."""
    out = {}
    for name, raw in ATTR_RE.findall(attrs):
        value = raw[1:-1] if raw[:1] in ('"', "'") and raw[-1:] == raw[:1] else raw
        out[name.lower()] = value.strip().lower()
    return out
JINJA_TAG_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)

# `type=` values that ARE JavaScript — anything else is template DATA, not code.
JS_SCRIPT_TYPES = {"", "text/javascript", "application/javascript", "module"}

# Tallied by check_html_template, printed by main() (AC-QA-71): a rule that
# silently stopped discovering blocks must not report "passed" the same as
# one that scanned 17.
TEMPLATE_SCRIPT_STATS = {"parsed": 0, "skipped": []}


def _mask_jinja(body: str) -> str:
    """Replace `{{ }}`/`{% %}`/`{# #}`, never skip.

    Skipping would permanently exempt every Jinja-bearing block, including
    the accessibility-critical ones this rule most needs to see (decision 2,
    AC-A11Y-7). Newlines inside a tag are preserved so a later finding's line
    number is unaffected.

    The two tag families mask DIFFERENTLY, and the reason is a false-RED class
    review caught in the first version, which masked everything to the bare
    identifier `__JINJA__`:

        const cfg = { a: 1, {% if f %} b: 2, {% endif %} };

    became `{ a: 1, __JINJA__ b: 2, __JINJA__ }` -- a SyntaxError reported
    against template code that renders valid JavaScript on every branch. An
    identifier is only legal where a VALUE is legal, and `{% %}` is control
    flow that appears wherever the author likes. A block comment is legal
    everywhere, so control tags and comment tags become one:

      - `{% %}` and `{# #}` -> `/*...*/`, carrying no content (a `*/` inside a
        Jinja comment would otherwise close the mask early).
      - `{{ }}` -> `__JINJA__`, because an interpolation IS in value position
        and a comment there would leave a hole.

    Still not covered, and deliberately: a `{% %}` splitting one expression
    into alternatives, e.g. `f({% if d %} 'a' {% else %} 'b' {% endif %})`,
    masks to two adjacent string literals and is a genuine false RED. No
    substitution fixes that without rendering the template, which is far
    beyond a parse gate. It is pinned by a test so the limit is known rather
    than discovered.
    """
    def _sub(m):
        newlines = "\n" * m.group(0).count("\n")
        if m.group(0).startswith("{{"):
            return "__JINJA__" + newlines
        return "/*" + newlines + "*/"

    return JINJA_TAG_RE.sub(_sub, body)


def _iter_script_blocks(text: str):
    """Yield (html_line, kind, body) per `<script>` — html_line is where the
    body starts. `kind` is `"classic"`/`"module"`, or `"skip-*"` (external
    `src=`, non-JS `type=`, empty body).
    """

    # Comments blanked (newlines kept) before anything else looks at the text,
    # so a commented-out <script> is neither parsed nor counted as an opener.
    text = HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for m in SCRIPT_TAG_RE.finditer(text):

        attrs, body = _parse_attrs(m.group(1)), m.group(2)
        line = text.count("\n", 0, m.start(2)) + 1
        if "src" in attrs:
            yield (line, "skip-src", body)
            continue
        if not body.strip():
            yield (line, "skip-empty", body)
            continue
        script_type = attrs.get("type", "")
        if script_type not in JS_SCRIPT_TYPES:
            yield (line, f"skip-type:{script_type}", body)
            continue
        yield (line, "module" if script_type == "module" else "classic", body)

    # Every `<script` opener NOT inside a matched element lost its body to a
    # missing or malformed `</script>`. Report it, so an extraction failure is
    # not indistinguishable from a file with no scripts at all.
    #
    # By span containment, NOT by count. The first version took a positional
    # slice of the leftovers, which is only equivalent when the unmatched
    # openers happen to come last -- and they do not. `base.html` contains the
    # literal `// <script>` inside a JS comment at :238, so the count was off
    # by one and the slice named the LAST opener (:511, a real, terminated,
    # correctly-parsed block) as unterminated. That put four false lines into
    # the operator-facing channel added specifically so an extraction failure
    # could not hide, on every green run -- noise in the one place that must
    # stay trustworthy.
    element_spans = [m.span() for m in SCRIPT_TAG_RE.finditer(text)]
    for opener in SCRIPT_OPEN_RE.finditer(text):
        if any(start <= opener.start() < end for start, end in element_spans):
            continue
        yield (text.count("\n", 0, opener.start()) + 1, "skip-unterminated", "")


def _node_check(body: str, *, module: bool):
    """Run `node --check -` on stdin — list argv, never a shell. Returns
    (ok, line_in_body, message, ran); ran=False means the parser itself
    could not run (AC-QA-75: "the check could not run", not a fake syntax
    error).
    """
    args = ["node", "--input-type=module", "--check", "-"] if module else ["node", "--check", "-"]
    # NODE_OPTIONS is honoured by every node invocation and can carry
    # `--require`, so "parses without executing" would otherwise be a property
    # of the ambient environment rather than of this checker. Dropped here so
    # the guarantee is enforced by the code that claims it.
    env = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    try:
        result = subprocess.run(
            args, input=body, capture_output=True, text=True, timeout=10, env=env
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, 0, f"{type(exc).__name__}: {exc}", False)
    if result.returncode == 0:
        return (True, 0, "", True)
    line_match = re.search(r"\[stdin\]:(\d+)", result.stderr)
    msg_match = re.search(r"^(\S*Error:.*)$", result.stderr, re.MULTILINE)
    if not (line_match and msg_match):
        return (False, 0, result.stderr.strip()[:300] or "no output from node", False)
    return (False, int(line_match.group(1)), msg_match.group(1), True)


def check_html_template(path: Path, text: str):
    """Rule 8: inline `<script>` in Jinja templates must parse as JS.

    Masks Jinja tags, feeds each classic/module body to `node --check -` on
    stdin: parses without executing (AC-SEC-1), no temp file (AC-SEC-3). A
    missing `node` is a hard, named failure per block (AC-QA-74), same shape
    as the PyYAML branch above, not a silent skip.

    WHAT THIS RULE STILL DOES NOT SEE (AC-OPS-13). Stated so the rule is not
    over-trusted as "template JS is now gated", which it is not:

    * **JS in Alpine/htmx ATTRIBUTES** (`x-data`, `@click`, `hx-on:`) and in
      static `.js` files — only the inline `<script>` body is parsed. This is
      not a corner: the densest accessibility-critical inline JS in this repo
      lives there, including `partials/movie_detail.html`'s trailer focus trap
      (~:318-326) and the restore-picker focus return (~:206). Breaking those
      yields ZERO findings.
    * **Top-level `return`.** `node --check` reads stdin as a CommonJS module,
      whose wrapper makes a top-level `return` legal; a browser rejects it.
      Measured: `<script>return 1;</script>` passes. Fixing it needs the Script
      grammar via `vm.Script`, which means `node -e` — banned by AC-SEC-1 as an
      execution surface. The narrower risk was preferred to the broader one.
    * **A `{% %}` that splits one expression**, and a `{{ }}` eating a nested
      block literal — both pinned as KNOWN limits by tests rather than fixed;
      no substitution handles them without rendering the template.
    * **An unterminated `<script>` FOLLOWED by a terminated one**: the first
      swallows the second, and the result is reported as a SyntaxError at the
      swallowed boundary rather than as `skip-unterminated`. It fails closed
      and names the file and line, so it is a misleading diagnosis, not a hole.

    *Does it parse*, not *does it match a style guide*: a dropped operator is a
    syntax error only where ASI cannot paper over it, so this catches #230's
    class, not every dropped token.
    """
    node = shutil.which("node")
    for line, kind, body in _iter_script_blocks(text):
        if kind.startswith("skip"):
            TEMPLATE_SCRIPT_STATS["skipped"].append((path, line, kind))
            continue
        TEMPLATE_SCRIPT_STATS["parsed"] += 1
        if node is None:
            yield (line, "cannot check this <script>: `node` is not installed "
                   "(install from nodejs.org) — this gate must not skip silently.")
            continue
        ok, body_line, message, ran = _node_check(_mask_jinja(body), module=(kind == "module"))
        if ok:
            continue
        if not ran:
            yield (line, f"the check could not run for this <script> block: {message}")
            continue
        yield (line + body_line - 1, message)


def check_file(path: Path):
    """Yield (line_no, message) for every trap found in ``path``."""
    is_hook = path.parent.name == ".githooks"
    if is_hook:
        yield from check_git_hook(path)

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    if _is_python_test(path):
        yield from check_python_test(path, text)
    elif _is_vitest_spec(path):
        yield from check_vitest_spec(path, text)
    elif _is_e2e_spec(path):
        yield from check_e2e_spec_guards(path, text)
    elif path.name == "Makefile" or path.name.endswith(".mk"):
        yield from check_makefile(path, text)
    elif path.name.endswith(WORKFLOW_SUFFIXES):
        yield from check_workflow(path, text)
    elif path.name.endswith(SHELL_SUFFIXES) or is_hook:
        yield from check_shell_script(path, text)
    elif path.suffix in TEMPLATE_SUFFIXES:
        yield from check_html_template(path, text)


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
    # --require-git turns "git is unavailable, so rule 5 cannot run" from a
    # note on stderr into a hard failure. scripts/verify.sh and ci.yml pass
    # it; the container run (scripts/test-local.sh, which has no git) does
    # not. So the authoritative gates cannot skip a rule quietly, while the
    # supplementary one still runs the other six rules instead of crashing.
    # Rule 8's counters are module-global, so a second main() in the same
    # interpreter would report the FIRST run's totals added to its own. The
    # CLI is one process per invocation today, which masks it -- but the
    # counters exist to make "the rule stopped discovering blocks" visible,
    # and a stale count is exactly the wrong answer for that question.
    TEMPLATE_SCRIPT_STATS["parsed"] = 0
    TEMPLATE_SCRIPT_STATS["skipped"] = []

    require_git = "--require-git" in argv
    argv = [a for a in argv if a != "--require-git"]
    roots = [Path(p) for p in argv] if argv else DEFAULT_ROOTS
    files = iter_files(roots)

    total = 0
    for path in files:
        for line_no, message in check_file(path):
            print(f"{path}:{line_no}: {message}")
            total += 1

    # Rule 5 is whole-repo by nature (git ls-files + both runner files), not
    # scoped by `roots`/argv the way rules 1-4 are, so it runs unconditionally
    # rather than being folded into the per-path loop above.
    for path, line_no, message in check_orphaned_test_files(require_git=require_git):
        print(f"{path}:{line_no}: {message}")
        total += 1

    parsed, skipped = TEMPLATE_SCRIPT_STATS["parsed"], TEMPLATE_SCRIPT_STATS["skipped"]
    if parsed or skipped:
        print(f"template scripts: {parsed} parsed, {len(skipped)} skipped")
        for spath, sline, reason in skipped:
            # Repo-relative: the DEFAULT_ROOTS invocation the Makefile and CI
            # actually run produced absolute paths on every green run, which
            # puts the developer's home directory into CI logs and makes the
            # output differ from every finding line above it.
            try:
                spath = Path(spath).relative_to(REPO_ROOT)
            except ValueError:
                pass
            print(f"  skipped {spath}:{sline}: {reason}")

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
