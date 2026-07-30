"""Tests for scripts/mutation_changed.py — changed-files-only mutation testing.

Full mutation runs are slow enough that in practice they only happen nightly,
which means survivors go unreviewed and the informational-mutation rule
(`docs/development-process.md` → Mutation testing) quietly stops being followed.
This script narrows a run to what the branch actually touched so it is usable
per-change.

The important property under test is that scope comes from the *real* configs
(`[tool.mutmut] source_paths` in pyproject.toml, `mutate` in stryker.conf.json)
rather than a second hard-coded copy of them. A duplicated list rots silently:
someone widens `source_paths`, this script keeps mutating the old set, and the
gap is invisible. `test_scope_is_read_from_the_real_configs` fails if the two
ever drift apart.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "mutation_changed.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import mutation_changed  # noqa: E402


# ── Config parsing ──────────────────────────────────────────────────────────


def test_parses_a_toml_string_array_from_the_right_section():
    text = (
        "[tool.other]\n"
        'source_paths = ["nope/wrong.py"]\n'
        "\n"
        "[tool.mutmut]\n"
        "# a comment\n"
        'source_paths = ["couchpotato/core/db/sqlite_adapter.py", "couchpotato/api.py"]\n'
        'tests_dir = ["tests/unit/"]\n'
    )

    assert mutation_changed.parse_toml_string_array(text, "tool.mutmut", "source_paths") == [
        "couchpotato/core/db/sqlite_adapter.py",
        "couchpotato/api.py",
    ]


def test_parses_a_multiline_toml_string_array():
    text = "[tool.mutmut]\nsource_paths = [\n  'a/b.py',\n  'c/d.py',\n]\n"

    assert mutation_changed.parse_toml_string_array(text, "tool.mutmut", "source_paths") == [
        "a/b.py",
        "c/d.py",
    ]


def test_missing_key_raises_rather_than_silently_mutating_nothing():
    """A renamed config key must be loud — silently mutating nothing looks like
    a clean run."""
    text = "[tool.mutmut]\nrunner = 'pytest'\n"

    with pytest.raises(mutation_changed.ConfigError) as exc:
        mutation_changed.parse_toml_string_array(text, "tool.mutmut", "source_paths")
    assert "source_paths" in str(exc.value)


def test_scope_is_read_from_the_real_configs():
    """Guards against this script drifting from pyproject.toml / stryker.conf.json.

    Asserts the scope resolves, is non-empty, and every entry it names actually
    exists — so a renamed config key, an emptied list, or a path deleted by a
    refactor all fail here instead of silently mutating nothing.
    """
    py_scope = mutation_changed.python_scope(REPO_ROOT)
    js_scope = mutation_changed.js_scope(REPO_ROOT)

    assert py_scope, "mutmut scope is empty — a run would mutate nothing"
    assert js_scope, "stryker mutate is empty — a run would mutate nothing"

    expected_js = json.loads((REPO_ROOT / "stryker.conf.json").read_text())["mutate"]
    assert js_scope == expected_js

    for entry in py_scope:
        assert (REPO_ROOT / entry).exists(), (
            f"[tool.mutmut] names '{entry}', which does not exist — the scope is stale"
        )


def test_python_scope_accepts_the_deprecated_paths_to_mutate_key():
    """mutmut 3.6 renamed `paths_to_mutate` to `source_paths`; support both.

    The repo is on the modern key, but a config written against either mutmut
    generation must resolve rather than raise — otherwise a version bump turns
    into a silent "nothing to mutate".
    """
    old = "[tool.mutmut]\npaths_to_mutate = ['couchpotato/api.py']\n"
    new = "[tool.mutmut]\nsource_paths = ['couchpotato/api.py']\n"

    for text in (old, new):
        assert mutation_changed.parse_toml_string_array(
            text,
            "tool.mutmut",
            "paths_to_mutate" if "paths_to_mutate" in text else "source_paths",
        ) == ["couchpotato/api.py"]


# ── Mapping changed files to mutation targets ───────────────────────────────


def test_maps_a_changed_python_file_to_a_dotted_mutant_filter():
    targets = mutation_changed.python_targets(
        ["couchpotato/core/db/sqlite_adapter.py"],
        scope=["couchpotato/core/db/sqlite_adapter.py"],
    )
    assert targets == ["couchpotato.core.db.sqlite_adapter"]


def test_ignores_python_files_outside_the_mutmut_scope():
    targets = mutation_changed.python_targets(
        ["couchpotato/core/plugins/renamer.py", "couchpotato/core/db/sqlite_adapter.py"],
        scope=["couchpotato/core/db/sqlite_adapter.py"],
    )
    assert targets == ["couchpotato.core.db.sqlite_adapter"]


def test_directory_scope_matches_files_beneath_it():
    targets = mutation_changed.python_targets(
        ["couchpotato/core/db/sqlite_adapter.py", "couchpotato/api.py"],
        scope=["couchpotato/core/db/"],
    )
    assert targets == ["couchpotato.core.db.sqlite_adapter"]


def test_ignores_tests_and_non_python_files():
    targets = mutation_changed.python_targets(
        [
            "tests/unit/test_sqlite_adapter.py",
            "docs/README.md",
            "couchpotato/core/db/sqlite_adapter.py",
        ],
        scope=["couchpotato/", "tests/"],
    )
    assert targets == ["couchpotato.core.db.sqlite_adapter"]


def test_maps_changed_ui_scripts_to_stryker_mutate_paths():
    targets = mutation_changed.js_targets(
        [
            "couchpotato/static/scripts/ui/movie-filter.js",
            "couchpotato/static/scripts/legacy/mootools.js",
            "couchpotato/ui/templates/base.html",
        ],
        scope=["couchpotato/static/scripts/ui/**/*.{js,ts}"],
    )
    assert targets == ["couchpotato/static/scripts/ui/movie-filter.js"]


def test_js_scope_glob_matches_nested_directories():
    targets = mutation_changed.js_targets(
        ["couchpotato/static/scripts/ui/nested/deep/thing.ts"],
        scope=["couchpotato/static/scripts/ui/**/*.{js,ts}"],
    )
    assert targets == ["couchpotato/static/scripts/ui/nested/deep/thing.ts"]


# ── Command construction ────────────────────────────────────────────────────


def test_builds_a_mutmut_command_filtered_to_the_changed_module():
    commands = mutation_changed.build_commands(
        python_targets=["couchpotato.core.db.sqlite_adapter"], js_targets=[]
    )
    assert len(commands) == 1
    argv = commands[0]
    assert "mutmut" in argv
    assert "run" in argv
    assert "couchpotato.core.db.sqlite_adapter*" in argv, (
        "mutmut 3.x filters by mutant name; a bare module path matches nothing"
    )


def test_builds_a_stryker_command_with_mutate_scoped_to_changed_files():
    commands = mutation_changed.build_commands(
        python_targets=[], js_targets=["couchpotato/static/scripts/ui/a.js",
                                       "couchpotato/static/scripts/ui/b.js"]
    )
    assert len(commands) == 1
    argv = commands[0]
    assert "stryker" in " ".join(argv)
    assert "--mutate" in argv
    assert argv[argv.index("--mutate") + 1] == (
        "couchpotato/static/scripts/ui/a.js,couchpotato/static/scripts/ui/b.js"
    )


def test_builds_both_commands_when_both_languages_changed():
    commands = mutation_changed.build_commands(
        python_targets=["couchpotato.api"],
        js_targets=["couchpotato/static/scripts/ui/a.js"],
    )
    assert len(commands) == 2


def test_builds_no_commands_when_nothing_is_in_scope():
    assert mutation_changed.build_commands(python_targets=[], js_targets=[]) == []


def test_runner_env_puts_vendored_libs_on_the_pythonpath():
    """mutmut re-runs pytest from its `mutants/` sandbox, where collection fails
    with an ImportError unless `libs/` is on the path — observed for real, not
    hypothetical."""
    env = mutation_changed.runner_env()
    libs = str(REPO_ROOT / "libs")
    assert libs in env["PYTHONPATH"].split(os.pathsep)


def test_runner_env_preserves_an_existing_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
    env = mutation_changed.runner_env()
    parts = env["PYTHONPATH"].split(os.pathsep)
    assert str(REPO_ROOT / "libs") in parts
    assert "/somewhere/else" in parts


def test_runner_env_does_not_duplicate_libs(monkeypatch):
    libs = str(REPO_ROOT / "libs")
    monkeypatch.setenv("PYTHONPATH", libs)
    env = mutation_changed.runner_env()
    assert env["PYTHONPATH"].split(os.pathsep).count(libs) == 1


# ── End-to-end against a real git repo ──────────────────────────────────────


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def temp_repo(tmp_path):
    """A real git repo with a master branch and a feature branch."""
    _git(tmp_path, "init", "-b", "master")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")

    adapter = tmp_path / "couchpotato" / "core" / "db" / "sqlite_adapter.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("def get(key):\n    return key\n")
    (tmp_path / "README.md").write_text("hello\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")
    _git(tmp_path, "checkout", "-b", "feature")
    return tmp_path


def run_script(cwd, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True
    )


def test_dry_run_lists_the_mutmut_command_for_a_committed_change(temp_repo):
    adapter = temp_repo / "couchpotato" / "core" / "db" / "sqlite_adapter.py"
    adapter.write_text("def get(key):\n    return key.strip()\n")
    _git(temp_repo, "commit", "-am", "tweak adapter")

    result = run_script(temp_repo, "--base", "master", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "couchpotato.core.db.sqlite_adapter*" in result.stdout


def test_dry_run_picks_up_uncommitted_changes(temp_repo):
    """Tight iteration means running this before committing."""
    adapter = temp_repo / "couchpotato" / "core" / "db" / "sqlite_adapter.py"
    adapter.write_text("def get(key):\n    return key.upper()\n")

    result = run_script(temp_repo, "--base", "master", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "couchpotato.core.db.sqlite_adapter*" in result.stdout


def test_dry_run_picks_up_untracked_files_in_scope(tmp_path):
    """A brand-new, never-committed file in scope must still be mutated.

    The scoped path comes from the real `[tool.mutmut] source_paths`, so this
    repo deliberately leaves that exact file untracked rather than inventing a
    second path the config does not cover.
    """
    _git(tmp_path, "init", "-b", "master")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("hello\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    scoped = mutation_changed.python_scope(REPO_ROOT)[0]
    new_file = tmp_path / scoped
    new_file.parent.mkdir(parents=True, exist_ok=True)
    new_file.write_text("def get(key):\n    return key\n")

    result = run_script(tmp_path, "--base", "master", "--dry-run")

    expected = scoped[: -len(".py")].replace("/", ".") + "*"
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout, result.stdout


def test_exits_zero_with_a_clear_message_when_nothing_in_scope_changed(temp_repo):
    (temp_repo / "README.md").write_text("hello again\n")
    _git(temp_repo, "commit", "-am", "docs only")

    result = run_script(temp_repo, "--base", "master", "--dry-run")

    assert result.returncode == 0
    assert "nothing" in result.stdout.lower()
    assert "mutmut" not in result.stdout, "should not emit a command with no targets"


def test_fails_clearly_on_an_unknown_base_ref(temp_repo):
    result = run_script(temp_repo, "--base", "no-such-branch", "--dry-run")

    assert result.returncode != 0
    assert "no-such-branch" in (result.stdout + result.stderr)
