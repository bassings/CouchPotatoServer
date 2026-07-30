#!/usr/bin/env python3
"""Run mutation testing over only what this branch changed.

`make mutation` mutates everything in scope, which is slow enough that in
practice it only ever runs nightly — so survivors go unreviewed and the
"review the survivor list" half of the informational-mutation rule quietly stops
happening (`docs/development-process.md` → Mutation testing). This narrows a run
to the files the branch touched, which makes it usable per-change:

    make mutation-changed                  # vs master
    make mutation-changed BASE=origin/master
    python scripts/mutation_changed.py --dry-run   # show the commands only

Scope is read from the real configs — ``[tool.mutmut] source_paths`` in
``pyproject.toml`` and ``mutate`` in ``stryker.conf.json`` — never duplicated
here. A second hard-coded copy of those lists would rot silently: widen
``source_paths`` and this script would keep mutating the old set with nothing to
signal the gap. A missing/renamed config key is a hard error rather than an empty
scope, because "mutated nothing" and "found no survivors" look identical in the
output.

Changed files = everything differing from the merge-base with ``--base``,
including uncommitted and untracked work, so it can be run mid-edit.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    """A mutation config key is missing — scope cannot be determined."""


# ── Config ──────────────────────────────────────────────────────────────────


def parse_toml_string_array(text: str, section: str, key: str) -> list[str]:
    """Extract ``key = ["a", "b"]`` from ``[section]`` of a TOML document.

    A deliberately small hand parser rather than ``tomllib``: this repo supports
    Python 3.10, where ``tomllib`` is absent, and the values needed are simple
    string arrays. Raises ConfigError rather than returning [] so a renamed key
    cannot masquerade as an empty scope.
    """
    section_re = re.compile(
        rf"^\[{re.escape(section)}\]\s*$(.*?)(?=^\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = section_re.search(text)
    if not match:
        raise ConfigError(f"section [{section}] not found")

    body = match.group(1)
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)
    key_match = key_re.search(body)
    if not key_match:
        raise ConfigError(
            f"key '{key}' not found in [{section}] — the mutation config was "
            f"renamed or removed; fix scripts/mutation_changed.py to match "
            f"rather than letting it mutate nothing"
        )

    return re.findall(r"""['"]([^'"]+)['"]""", key_match.group(1))


def python_scope(repo_root: Path) -> list[str]:
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    for key in ("source_paths", "paths_to_mutate"):
        try:
            return parse_toml_string_array(text, "tool.mutmut", key)
        except ConfigError:
            continue
    raise ConfigError(
        "neither 'source_paths' nor the deprecated 'paths_to_mutate' found in "
        "[tool.mutmut] of pyproject.toml"
    )


def js_scope(repo_root: Path) -> list[str]:
    config = json.loads((repo_root / "stryker.conf.json").read_text(encoding="utf-8"))
    try:
        return config["mutate"]
    except KeyError as exc:
        raise ConfigError("key 'mutate' not found in stryker.conf.json") from exc


# ── Changed files ───────────────────────────────────────────────────────────


def changed_files(base: str, cwd: Path) -> list[str]:
    """Files differing from the merge-base with ``base``, plus untracked files."""
    merge_base = subprocess.run(
        ["git", "merge-base", "HEAD", base],
        cwd=cwd, capture_output=True, text=True,
    )
    if merge_base.returncode != 0:
        raise SystemExit(
            f"mutation_changed: cannot resolve base ref '{base}': "
            f"{merge_base.stderr.strip()}"
        )

    diff = subprocess.run(
        ["git", "diff", "--name-only", merge_base.stdout.strip()],
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=cwd, capture_output=True, text=True, check=True,
    )

    files = {ln.strip() for ln in diff.stdout.splitlines() if ln.strip()}
    files |= {ln.strip() for ln in untracked.stdout.splitlines() if ln.strip()}
    return sorted(files)


# ── Mapping changed files to targets ────────────────────────────────────────


def _in_python_scope(path: str, scope: list[str]) -> bool:
    for entry in scope:
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry or path.startswith(entry.rstrip("/") + "/"):
            return True
    return False


def python_targets(files: list[str], scope: list[str]) -> list[str]:
    """Changed in-scope .py files as dotted module paths."""
    targets = []
    for path in files:
        if not path.endswith(".py"):
            continue
        if path.startswith("tests/") or Path(path).name.startswith("test_"):
            continue
        if not _in_python_scope(path, scope):
            continue
        targets.append(path[: -len(".py")].replace("/", "."))
    return sorted(set(targets))


def _expand_braces(pattern: str) -> list[str]:
    """`*.{js,ts}` -> ['*.js', '*.ts'] so fnmatch can handle it."""
    match = re.search(r"\{([^}]*)\}", pattern)
    if not match:
        return [pattern]
    expanded = []
    for option in match.group(1).split(","):
        expanded.extend(
            _expand_braces(pattern[: match.start()] + option + pattern[match.end():])
        )
    return expanded


def js_targets(files: list[str], scope: list[str]) -> list[str]:
    """Changed files matching stryker's `mutate` globs."""
    patterns = []
    for entry in scope:
        for pattern in _expand_braces(entry):
            patterns.append(pattern)
            # fnmatch's `*` crosses `/`, but `**/` must also match zero
            # directories: `ui/**/*.js` has to match `ui/a.js`.
            if "**/" in pattern:
                patterns.append(pattern.replace("**/", "", 1))

    targets = [
        path for path in files if any(fnmatch.fnmatch(path, p) for p in patterns)
    ]
    return sorted(set(targets))


# ── Commands ────────────────────────────────────────────────────────────────


def runner_env() -> dict[str, str]:
    """Environment for the mutation runners.

    `PYTHONPATH` must include `libs/` — mutmut re-runs pytest from inside its
    `mutants/` sandbox, and without the vendored libs on the path collection
    fails with an ImportError before a single mutant is evaluated (observed:
    `test_add_via_url.py` failing to import `couchpotato.api`). `make
    mutation-py` sets this, so a bare `python scripts/mutation_changed.py` must
    not silently lack it.
    """
    env = dict(os.environ)
    libs = str(REPO_ROOT / "libs")
    existing = env.get("PYTHONPATH", "")
    if libs not in existing.split(os.pathsep):
        env["PYTHONPATH"] = f"{libs}{os.pathsep}{existing}" if existing else libs
    return env


def build_commands(python_targets: list[str], js_targets: list[str]) -> list[list[str]]:
    commands: list[list[str]] = []

    if python_targets:
        # mutmut 3.x filters by *mutant name* (module.function__mutmut_N), so a
        # bare module path matches nothing — the trailing glob is required.
        commands.append(
            [sys.executable, "-m", "mutmut", "run", *[f"{t}*" for t in python_targets]]
        )

    if js_targets:
        commands.append(["npx", "stryker", "run", "--mutate", ",".join(js_targets)])

    return commands


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run mutation testing only on files changed vs a base ref."
    )
    parser.add_argument(
        "--base", default="master", help="base ref to diff against (default: master)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the commands instead of running them"
    )
    args = parser.parse_args(argv)

    cwd = Path.cwd()
    files = changed_files(args.base, cwd)

    try:
        py_scope = python_scope(REPO_ROOT)
        stryker_scope = js_scope(REPO_ROOT)
    except ConfigError as exc:
        print(f"mutation_changed: {exc}", file=sys.stderr)
        return 2

    py = python_targets(files, py_scope)
    js = js_targets(files, stryker_scope)
    commands = build_commands(py, js)

    if not commands:
        print(
            f"mutation_changed: nothing to do — none of the {len(files)} changed "
            f"file(s) are in the mutation scope.\n"
            f"  python scope: {', '.join(py_scope)}\n"
            f"  js scope:     {', '.join(stryker_scope)}"
        )
        return 0

    print(f"mutation_changed: {len(py)} python target(s), {len(js)} js target(s)")
    for argv_ in commands:
        print(f"  $ {' '.join(argv_)}")

    if args.dry_run:
        return 0

    # Mutation testing is informational — run every command and report, rather
    # than fail-fast, so one language's survivors don't hide the other's.
    worst = 0
    for argv_ in commands:
        result = subprocess.run(argv_, cwd=REPO_ROOT, env=runner_env())
        worst = max(worst, result.returncode)
    if worst:
        print(
            "\nmutation_changed: a runner exited non-zero. Mutation results are "
            "INFORMATIONAL — review the survivor list above and strengthen the "
            "weak assertions; there is no score threshold to satisfy.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
