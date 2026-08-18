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
gap is invisible. `test_scope_is_actually_read_from_the_config_files` pins it, by
pointing the loaders at a temp root with distinctive values — an earlier version
compared `js_scope()` against `json.loads(...)["mutate"]`, which is literally its
own implementation, and so passed with the scope hardcoded.
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
from tests.unit.conftest import sanitized_git_env


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


def _write_configs(root: Path, py_paths: str, js_mutate: str) -> None:
    (root / "pyproject.toml").write_text(f"[tool.mutmut]\nsource_paths = [{py_paths}]\n")
    (root / "stryker.conf.json").write_text(json.dumps({"mutate": json.loads(js_mutate)}))


def test_scope_is_actually_read_from_the_config_files(tmp_path):
    """The headline claim: scope comes from the configs, not a second copy here.

    Both functions take a repo root, so pointing them at a temp root with
    *distinctive* values is what proves they parse the files. Comparing against
    `json.loads(stryker.conf.json)["mutate"]` — which is literally `js_scope`'s
    implementation — is a tautology that passes with the scope hardcoded
    (confirmed by mutation: hardcoding either scope survived that assertion).
    """
    _write_configs(
        tmp_path,
        '"sentinel/py/module.py", "sentinel/py/other.py"',
        '["sentinel/js/**/*.ts"]',
    )

    assert mutation_changed.python_scope(tmp_path) == [
        "sentinel/py/module.py",
        "sentinel/py/other.py",
    ]
    assert mutation_changed.js_scope(tmp_path) == ["sentinel/js/**/*.ts"]


def test_real_repo_scope_resolves_and_names_files_that_exist():
    """Complements the above: the committed config must not be stale."""
    py_scope = mutation_changed.python_scope(REPO_ROOT)
    js_scope = mutation_changed.js_scope(REPO_ROOT)

    assert py_scope, "mutmut scope is empty — a run would mutate nothing"
    assert js_scope, "stryker mutate is empty — a run would mutate nothing"

    for entry in py_scope:
        assert (REPO_ROOT / entry).exists(), (
            f"[tool.mutmut] names '{entry}', which does not exist — the scope is stale"
        )


def test_python_scope_accepts_the_deprecated_paths_to_mutate_key(tmp_path):
    """mutmut 3.6 renamed `paths_to_mutate` to `source_paths`; support both.

    Calls `python_scope` — the thing with the fallback — rather than
    `parse_toml_string_array` with the key the test itself chose, which only
    proved "parsing the key you asked for works" and left the fallback entirely
    uncovered (confirmed by mutation: deleting `paths_to_mutate` from the
    fallback tuple survived).
    """
    (tmp_path / "stryker.conf.json").write_text('{"mutate": ["x/**/*.js"]}')

    (tmp_path / "pyproject.toml").write_text(
        "[tool.mutmut]\npaths_to_mutate = ['legacy/only.py']\n"
    )
    assert mutation_changed.python_scope(tmp_path) == ["legacy/only.py"]

    (tmp_path / "pyproject.toml").write_text(
        "[tool.mutmut]\nsource_paths = ['modern/only.py']\n"
    )
    assert mutation_changed.python_scope(tmp_path) == ["modern/only.py"]


def test_python_scope_raises_when_neither_key_is_present(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.mutmut]\nrunner = 'pytest'\n")

    with pytest.raises(mutation_changed.ConfigError) as exc:
        mutation_changed.python_scope(tmp_path)
    assert "source_paths" in str(exc.value)


def test_js_scope_raises_when_mutate_is_missing(tmp_path):
    (tmp_path / "stryker.conf.json").write_text('{"testRunner": "vitest"}')

    with pytest.raises(mutation_changed.ConfigError) as exc:
        mutation_changed.js_scope(tmp_path)
    assert "mutate" in str(exc.value)


def test_a_comment_containing_a_bracket_does_not_truncate_the_array(tmp_path):
    """A `]` in a trailing comment used to silently drop every later entry."""
    text = (
        "[tool.mutmut]\n"
        "source_paths = [\n"
        '  "couchpotato/core/db/sqlite_adapter.py",  # also see [tool.stryker]\n'
        '  "couchpotato/api.py",\n'
        "]\n"
    )

    assert mutation_changed.parse_toml_string_array(text, "tool.mutmut", "source_paths") == [
        "couchpotato/core/db/sqlite_adapter.py",
        "couchpotato/api.py",
    ]


def test_an_empty_array_raises_rather_than_silently_mutating_nothing(tmp_path):
    """"Mutated nothing" and "no survivors found" look identical in the output."""
    text = "[tool.mutmut]\nsource_paths = []\n"

    with pytest.raises(mutation_changed.ConfigError) as exc:
        mutation_changed.parse_toml_string_array(text, "tool.mutmut", "source_paths")
    assert "no paths" in str(exc.value)


def test_a_key_in_a_later_section_is_not_used_for_an_earlier_one():
    """Section body must stop at the next `[section]` header.

    The decoy is placed AFTER the target here: with it before, an over-running
    section body is undetectable, and dropping the terminating lookahead survived
    (confirmed by mutation).
    """
    text = (
        "[tool.mutmut]\n"
        "runner = 'pytest'\n"
        "\n"
        "[tool.other]\n"
        'source_paths = ["wrong/leaked.py"]\n'
    )

    with pytest.raises(mutation_changed.ConfigError):
        mutation_changed.parse_toml_string_array(text, "tool.mutmut", "source_paths")


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
    """Each exclusion is pinned by a case that ONLY it can exclude.

    `tests/unit/test_sqlite_adapter.py` alone satisfies both the `tests/` prefix
    check and the `test_` name check, so either could be deleted undetected; and
    `docs/README.md` is excluded by scope rather than by the `.py` filter
    (confirmed by mutation — all three survived). Hence the extra cases.
    """
    targets = mutation_changed.python_targets(
        [
            "tests/unit/test_sqlite_adapter.py",  # excluded twice over
            "tests/unit/helpers.py",  # ONLY the tests/ prefix excludes this
            "couchpotato/core/test_helper.py",  # ONLY the test_ name check
            "couchpotato/README.md",  # ONLY the .py extension check
            "couchpotato/core/db/sqlite_adapter.py",
        ],
        scope=["couchpotato/", "tests/"],
    )
    assert targets == ["couchpotato.core.db.sqlite_adapter"]


def test_scope_entry_without_a_trailing_slash_matches_the_file_and_below():
    """A `source_paths` entry can be a bare file OR a dir without a trailing slash.

    The non-trailing-slash branch was entirely untested: reducing it to
    `path == entry` survived, which would make a `source_paths = ["couchpotato"]`
    entry silently match nothing.
    """
    # Exact file match.
    assert mutation_changed.python_targets(
        ["couchpotato/api.py"], scope=["couchpotato/api.py"]
    ) == ["couchpotato.api"]

    # Directory named without a trailing slash must still match files beneath it.
    assert mutation_changed.python_targets(
        ["couchpotato/core/db/sqlite_adapter.py"], scope=["couchpotato"]
    ) == ["couchpotato.core.db.sqlite_adapter"]

    # But it must not match a sibling that merely shares the prefix.
    assert mutation_changed.python_targets(
        ["couchpotatoextra/thing.py"], scope=["couchpotato"]
    ) == []


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


def test_js_scope_glob_matches_both_nested_and_top_level_files():
    """`ui/**/*.js` must match `ui/a.js` (zero directories) AND `ui/x/y/a.js`.

    fnmatch's `*` crosses `/`, so the nested case alone is satisfied by the
    `**/`-stripped pattern and pins neither half of the expansion (confirmed by
    mutation: dropping either pattern survived). Asserting both in one call is
    what makes both halves load-bearing.
    """
    scope = ["couchpotato/static/scripts/ui/**/*.{js,ts}"]
    files = [
        "couchpotato/static/scripts/ui/top.js",
        "couchpotato/static/scripts/ui/nested/deep/thing.ts",
        "couchpotato/static/scripts/other/skip.js",
    ]

    assert mutation_changed.js_targets(files, scope) == [
        "couchpotato/static/scripts/ui/nested/deep/thing.ts",
        "couchpotato/static/scripts/ui/top.js",
    ]


def test_expand_braces_handles_nesting_and_sequential_groups():
    """Nested groups produced stray `}` with the old first-`}` regex."""
    assert mutation_changed._expand_braces("a.{js,ts}") == ["a.js", "a.ts"]
    assert mutation_changed._expand_braces("a.{js,{ts,tsx}}") == ["a.js", "a.ts", "a.tsx"]
    assert mutation_changed._expand_braces("{ui,src}/*.{js,ts}") == [
        "ui/*.js",
        "ui/*.ts",
        "src/*.js",
        "src/*.ts",
    ]
    assert mutation_changed._expand_braces("plain.js") == ["plain.js"]
    # Unbalanced braces must be treated literally rather than crashing.
    assert mutation_changed._expand_braces("a.{js") == ["a.{js"]


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


def test_runner_env_puts_vendored_libs_on_the_pythonpath(monkeypatch):
    """mutmut re-runs pytest from its `mutants/` sandbox, where collection fails
    with an ImportError unless `libs/` is on the path — observed for real, not
    hypothetical.

    PYTHONPATH is cleared first: `scripts/verify.sh` exports an ABSOLUTE
    `<root>/libs`, so under `make verify` this assertion was satisfied by the
    ambient environment and passed with `runner_env` gutted to
    `return dict(os.environ)` (confirmed by mutation). The test must not depend
    on how it was invoked.
    """
    monkeypatch.delenv("PYTHONPATH", raising=False)

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
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=sanitized_git_env()).stdout


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
    # sanitized_git_env() even though this spawns python, not git: the script
    # itself shells out to `git rev-parse --show-toplevel`, so an ambient
    # GIT_DIR reaches git one hop away. The process-level scrub in
    # tests/conftest.py already covers this; passing it explicitly keeps the
    # call honest about what it depends on.
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True,
        text=True, env=sanitized_git_env(),
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


def test_untracked_files_are_scoped_from_the_repo_root_not_the_cwd(tmp_path):
    """`git ls-files --others` prints CWD-relative paths; `git diff` prints
    root-relative ones. Run from a subdirectory the two disagree, and an
    untracked in-scope file gets mis-scoped out of the mutation set.

    Uses a bare repo (not `temp_repo`) so the scoped path is genuinely absent at
    baseline and therefore genuinely untracked.
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

    subdir = new_file.parent
    result = run_script(subdir, "--base", "master", "--dry-run")

    expected = scoped[: -len(".py")].replace("/", ".") + "*"
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout, (
        f"running from {subdir} mis-scoped the untracked file:\n{result.stdout}"
    )


def test_deleted_files_are_not_offered_as_mutation_targets(temp_repo):
    """A deleted file cannot be mutated, and stryker errors on a missing path.

    `temp_repo` already committed the scoped file on master, so deleting it on
    the branch is exactly the scenario.
    """
    scoped = mutation_changed.python_scope(REPO_ROOT)[0]
    target = temp_repo / scoped
    assert target.is_file(), "fixture should have committed the scoped file"

    target.unlink()
    _git(temp_repo, "commit", "-am", "delete scoped file")

    result = run_script(temp_repo, "--base", "master", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "nothing" in result.stdout.lower(), (
        f"a deleted file was offered as a mutation target:\n{result.stdout}"
    )


# ── The execution path (previously untested end to end) ─────────────────────


def test_executes_the_built_commands_with_the_libs_pythonpath(monkeypatch, tmp_path):
    """Without --dry-run the runners must actually be invoked, with the env.

    The three `runner_env` unit tests passed while nothing proved the env ever
    reached a subprocess — dropping `env=runner_env()` from the call survived
    (confirmed by mutation), which would silently reintroduce the mutmut
    collection ImportError.
    """
    calls = []

    def fake_run(argv, cwd=None, env=None, **kwargs):
        calls.append({"argv": argv, "cwd": cwd, "env": env})

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(mutation_changed.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mutation_changed, "changed_files", lambda base, cwd: ["couchpotato/api.py"]
    )
    monkeypatch.setattr(mutation_changed, "python_scope", lambda root: ["couchpotato/"])
    monkeypatch.setattr(mutation_changed, "js_scope", lambda root: ["nothing/**/*.js"])

    exit_code = mutation_changed.main(["--base", "master"])

    assert exit_code == 0
    assert len(calls) == 1, calls
    assert "couchpotato.api*" in calls[0]["argv"]
    assert calls[0]["cwd"] == mutation_changed.REPO_ROOT
    assert str(mutation_changed.REPO_ROOT / "libs") in calls[0]["env"]["PYTHONPATH"].split(
        os.pathsep
    )


def test_dry_run_executes_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mutation_changed.subprocess, "run", lambda *a, **k: calls.append(a) or None
    )
    monkeypatch.setattr(
        mutation_changed, "changed_files", lambda base, cwd: ["couchpotato/api.py"]
    )
    monkeypatch.setattr(mutation_changed, "python_scope", lambda root: ["couchpotato/"])
    monkeypatch.setattr(mutation_changed, "js_scope", lambda root: ["nothing/**/*.js"])

    assert mutation_changed.main(["--base", "master", "--dry-run"]) == 0
    assert calls == [], "--dry-run must not invoke a runner"


def test_a_failing_runner_still_exits_zero_because_mutation_is_informational(monkeypatch):
    """The documented contract: survivors are for review, not a build failure."""

    class Failed:
        returncode = 1

    monkeypatch.setattr(mutation_changed.subprocess, "run", lambda *a, **k: Failed())
    monkeypatch.setattr(
        mutation_changed, "changed_files", lambda base, cwd: ["couchpotato/api.py"]
    )
    monkeypatch.setattr(mutation_changed, "python_scope", lambda root: ["couchpotato/"])
    monkeypatch.setattr(mutation_changed, "js_scope", lambda root: ["nothing/**/*.js"])

    assert mutation_changed.main(["--base", "master"]) == 0


def test_a_config_error_exits_two_rather_than_pretending_there_was_nothing_to_do(monkeypatch):
    def boom(root):
        raise mutation_changed.ConfigError("source_paths went missing")

    monkeypatch.setattr(mutation_changed, "changed_files", lambda base, cwd: ["x.py"])
    monkeypatch.setattr(mutation_changed, "python_scope", boom)

    assert mutation_changed.main(["--base", "master", "--dry-run"]) == 2


def test_base_defaults_to_master(monkeypatch):
    """Every other test passes --base explicitly, so the default was uncovered."""
    seen = {}
    monkeypatch.setattr(
        mutation_changed,
        "changed_files",
        lambda base, cwd: seen.setdefault("base", base) and [],
    )
    monkeypatch.setattr(mutation_changed, "python_scope", lambda root: ["couchpotato/"])
    monkeypatch.setattr(mutation_changed, "js_scope", lambda root: ["x/**/*.js"])

    mutation_changed.main(["--dry-run"])
    assert seen["base"] == "master"
