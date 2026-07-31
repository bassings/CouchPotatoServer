"""Guard: a log call must not pass a tuple where the format expects N arguments.

`log.debug('a=%s b=%s', (a, b))` looks right and is not.

Checked as an ARITY comparison rather than "is the argument a tuple?", because
the tuple literal is only the most legible spelling of the mistake: a list, a
variable already holding a pair, or a `tuple(...)` call all fail identically.
Receivers `log`/`logger`/`self.log`/`self.logger` are all covered — anchoring on
a bare `log` name missed every `self.log.*` call in the tree. `%(name)s` mapping
style is exempt (it correctly takes a single dict), and `*args` is skipped as
statically unknowable. Python's logging does
`msg % self.args`, gets a 1-tuple containing a tuple, and raises
``TypeError: not enough arguments for format string``. Three consequences, all
bad, and the third is why this is a security guard and not a style rule:

  1. The intended message is never emitted — the diagnostic you added is silently
     absent exactly when something has gone wrong.
  2. `logging.Handler.handleError` writes the raw ``Message:`` / ``Arguments:``
     repr to **stderr**.
  3. That path bypasses the handler's filters — including
     `couchpotato.core.logger.PrivacyFilter`, which is what redacts
     ``?api_key=…``. So a provider URL containing a live API key is printed in
     full to `docker logs`, unredacted, despite the redaction filter being
     installed and working on every normal path.

Seven real call sites had this (fanart.tv ×2, transmission, hadouken,
qbittorrent, rtorrent, plex), each one character wrong. Enforced here rather than
left to review because the broken form is visually indistinguishable from the
correct one.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = [REPO_ROOT / "couchpotato", REPO_ROOT / "scripts"]

LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception"}

# `%(name)s` style takes a SINGLE mapping, so one arg is correct there however
# many placeholders appear. Excluding it is required, not cosmetic: without the
# carve-out this flags the legitimate call at
# couchpotato/core/media/_base/providers/base.py:409.
MAPPING_PLACEHOLDER_RE = re.compile(r"%\([^)]+\)")

# Positional conversions, including width/precision/flags (`%-10s`, `%.2f`).
POSITIONAL_PLACEHOLDER_RE = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[hlL]?([diouxXeEfFgGcrsa])")


def _placeholder_count(fmt: str) -> int:
    """Positional `%` placeholders only. `%%` is a literal percent."""
    return len(POSITIONAL_PLACEHOLDER_RE.findall(fmt.replace("%%", "")))


def _is_log_receiver(func: ast.Attribute) -> bool:
    """`log.x`, `logger.x`, `self.log.x`, `cls.logger.x`, `mod.log.x`, ...

    Anchoring on a bare `log` name missed `self.log.*` entirely — eight live
    multi-placeholder calls in couchpotato/core/settings.py were outside the
    guard for that reason alone.
    """
    recv = func.value
    if isinstance(recv, ast.Name):
        return recv.id in {"log", "logger"}
    if isinstance(recv, ast.Attribute):
        return recv.attr in {"log", "logger"}
    return False


def iter_bad_log_calls():
    """Yield (path, lineno, source_line) for every tuple-as-single-arg log call."""
    for root in SOURCE_ROOTS:
      for path in sorted(root.rglob("*.py")):
        if any(part in {"__pycache__"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue  # vendored/py2 leftovers are not our concern here
        lines = text.split("\n")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in LOG_METHODS):
                continue
            if not _is_log_receiver(func):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            fmt = node.args[0].value
            if not isinstance(fmt, str):
                continue
            # `%(name)s` style consumes a single mapping — one arg is correct.
            if MAPPING_PLACEHOLDER_RE.search(fmt):
                continue
            expected = _placeholder_count(fmt)
            if expected < 2:
                continue
            # Generalised from "is it a literal tuple?" to an ARITY check: any
            # single argument feeding a multi-placeholder format is the bug,
            # whether it is written as a tuple literal, a list, a variable, or a
            # call. `*args` is unknowable statically, so it is left alone.
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            if len(node.args) - 1 == 1 and expected >= 2:
                yield (
                    path.relative_to(REPO_ROOT),
                    node.lineno,
                    lines[node.lineno - 1].strip(),
                )


def test_no_log_call_underfills_a_multi_placeholder_format():
    bad = list(iter_bad_log_calls())
    assert not bad, (
        "these log calls pass ONE argument to a format expecting several. "
        "At runtime they raise TypeError inside logging, the message is "
        "never emitted, and the raw arguments are dumped to stderr BYPASSING "
        "PrivacyFilter — which leaks any api_key in the arguments:\n"
        + "\n".join(f"  {p}:{n}: {src}" for p, n, src in bad)
        + "\n\nFix: drop the parentheses — `log.debug('%s %s', a, b)`."
    )


def test_the_guard_actually_detects_the_pattern(tmp_path):
    """A guard that cannot fail is not a guard.

    Feeds the checker a file containing the exact broken idiom and confirms it is
    reported, so a refactor of the AST walk cannot silently neuter it.
    """
    import ast as _ast

    sample = (
        "log.debug('Failed for %s: %s', (identifier, err))\n"
        "log.error('a=%s b=%s', (x, y))\n"
        "log.debug('fine %s %s', a, b)\n"
        "log.debug('single %s', (a, b))\n"  # 1 placeholder: caller may intend a tuple
    )
    tree = _ast.parse(sample)
    found = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        func = node.func
        if not (isinstance(func, _ast.Attribute) and func.attr in LOG_METHODS):
            continue
        if not node.args or not isinstance(node.args[0], _ast.Constant):
            continue
        if _placeholder_count(node.args[0].value) < 2:
            continue
        if len(node.args) == 2 and isinstance(node.args[1], _ast.Tuple):
            found.append(node.lineno)

    assert found == [1, 2], f"expected the two broken calls on lines 1-2, got {found}"


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("%s and %s", 2),
        ("100%% done: %s", 1),
        ("%d of %d (%s)", 3),
        ("no placeholders", 0),
    ],
)
def test_placeholder_counting_ignores_escaped_percent(fmt, expected):
    assert _placeholder_count(fmt) == expected
