"""Guard: a log call must not pass a tuple where the format expects N arguments.

`log.debug('a=%s b=%s', (a, b))` looks right and is not. Python's logging does
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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "couchpotato"

LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception"}


def _placeholder_count(fmt: str) -> int:
    # %% is a literal percent, not a placeholder.
    return sum(fmt.replace("%%", "").count(f"%{c}") for c in "sdrifgex")


def iter_bad_log_calls():
    """Yield (path, lineno, source_line) for every tuple-as-single-arg log call."""
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
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
            if not (isinstance(func.value, ast.Name) and func.value.id == "log"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            fmt = node.args[0].value
            if not isinstance(fmt, str):
                continue
            if _placeholder_count(fmt) < 2:
                continue
            # The bug: exactly one extra arg, and it is a literal tuple.
            if len(node.args) == 2 and isinstance(node.args[1], ast.Tuple):
                yield (
                    path.relative_to(REPO_ROOT),
                    node.lineno,
                    lines[node.lineno - 1].strip(),
                )


def test_no_log_call_passes_a_tuple_where_multiple_args_are_expected():
    bad = list(iter_bad_log_calls())
    assert not bad, (
        "these log calls pass a tuple as ONE argument to a multi-placeholder "
        "format. At runtime they raise TypeError inside logging, the message is "
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
