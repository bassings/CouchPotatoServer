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


def test_runner_env_strips_git_star(monkeypatch):
    """mutmut shells out to git itself with no `env=` and no `cwd=` to decide
    whether its result cache is stale (`_run_git` in mutmut's own
    `__main__.py`: `git rev-parse HEAD` / `git diff --name-only` / `git
    ls-files`), inheriting whatever environment the mutation runner process
    was launched with. If a leaked `GIT_DIR` reached `runner_env()`, mutmut
    would answer those about a foreign repository too -- this is the last
    environment `mutation_changed.py` builds that still needs the same
    scrub as `git_toplevel()` and `changed_files()`.
    """
    monkeypatch.setenv("GIT_DIR", "/somewhere/foreign/.git")
    env = mutation_changed.runner_env()
    assert "GIT_DIR" not in env, (
        "runner_env() carried GIT_DIR through to the mutation runners"
    )


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


def run_script(cwd, *args, env=None):
    # sanitized_git_env() even though this spawns python, not git: the script
    # itself shells out to `git rev-parse --show-toplevel`, so an ambient
    # GIT_DIR reaches git one hop away. The process-level scrub in
    # tests/conftest.py already covers this; passing it explicitly keeps the
    # call honest about what it depends on. `env=` lets a caller override
    # that default deliberately, to prove the script's own entry point --
    # not just the imported functions -- handles a leaked GIT_DIR correctly
    # (see test_script_ignores_a_leaked_git_dir_end_to_end).
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True,
        text=True, env=sanitized_git_env() if env is None else env,
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


# ── GIT_DIR leak (#348) ──────────────────────────────────────────────────


def test_git_env_is_the_one_shared_helper_not_a_local_copy():
    """One definition of the scrub, not two.

    `check_test_traps.py` fixed its own `git ls-files` call in #347; #348 is
    that `mutation_changed.py`'s four call sites stayed unscrubbed because
    the fix lived only in the first file. Pinning identity, not merely equal
    behaviour, closes the gap a future edit could reopen: two independently
    written functions that both strip `GIT_*` would satisfy every other test
    in this file while drifting the moment one of them changes and the other
    does not.

    No `sys.path.insert` here: the module does it once at import time
    (above), and inserting again on every call would grow `sys.path` by one
    duplicate entry per test run for no benefit.
    """
    import check_test_traps
    import git_env as git_env_module

    assert mutation_changed.git_env is git_env_module.git_env, (
        "mutation_changed.py is not using scripts/git_env.py's git_env() -- "
        "it has its own copy again"
    )
    assert check_test_traps._git_env is git_env_module.git_env, (
        "check_test_traps.py is not using scripts/git_env.py's git_env() -- "
        "it has its own copy again"
    )


def _build_throwaway_repo(root):
    """A second, unrelated git repo with one committed file -- the shape of
    the foreign repository a leaked GIT_DIR points a subprocess at."""
    _git(root, "init", "-q", "-b", "master")
    _git(root, "config", "user.email", "throwaway@example.com")
    _git(root, "config", "user.name", "Throwaway")
    (root / "only-file.txt").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "x")
    return root


def _assert_git_dir_injection_took_effect(cwd, throwaway, env=None):
    """A git call from `cwd`, run with `env`, must resolve its git dir
    INSIDE `throwaway` -- proof the hostile environment a test builds
    actually reaches git, not just that the test called `setenv`/built a
    dict.

    Without this, a future change that moves the injection into a fixture,
    or has it overwritten before the call under test runs, leaves a
    leak-test passing while measuring nothing -- silently, because the
    function under test always scrubs `GIT_*` on its own path regardless of
    whether the leak this test means to simulate is actually present.
    `tests/unit/conftest.py`'s `assert_git_dir_is()` documents exactly this
    failure mode for the opposite polarity (proving sanitisation keeps an
    operation IN a directory); this proves the opposite -- that an
    unsanitised environment redirects one OUT.

    `env` is REQUIRED in practice, asserted below rather than merely
    documented: every caller in this file passes a hostile environment
    explicitly, and a caller that forgot would otherwise fall through to
    the `sanitized_git_env()` default below, which strips the very GIT_DIR
    this helper exists to confirm is present and turns the proof into a
    silent no-op. `env=sanitized_git_env() if env is None else env` is the
    default's shape anyway (not a bare `env=env`) because
    `test_fixtures_do_not_leak_gitdir.py`'s static audit requires every
    literal `git` subprocess call in tests/ to be recognisably sanitised at
    the call site -- the same escape hatch `_seed_commit` in
    `test_git_env_namespace_scrub.py` uses, on purpose, so a helper can
    still receive a deliberately hostile environment from its caller.
    """
    assert env is not None, (
        "_assert_git_dir_injection_took_effect() was called with no env -- "
        "pass the same hostile environment the test built, or this check "
        "would silently verify the sanitised default instead"
    )
    result = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=str(cwd),
        capture_output=True, text=True,
        env=sanitized_git_env() if env is None else env,
    )
    assert result.returncode == 0, (
        f"the git call used to prove the injected GIT_DIR took effect "
        f"failed outright: {result.stderr}"
    )
    resolved = os.path.realpath(result.stdout.strip())
    expected = os.path.realpath(str(throwaway / ".git"))
    assert resolved == expected, (
        f"a git call from {cwd} resolved its git dir to {resolved}, not "
        f"the throwaway's {expected} -- the GIT_DIR injection this test "
        f"built did not actually take effect, so it would prove nothing "
        f"about the leak"
    )


def test_git_toplevel_ignores_a_leaked_git_dir(temp_repo, tmp_path_factory, monkeypatch):
    """`cwd=` does not win over `GIT_DIR`. With `GIT_WORK_TREE` unset, git
    treats an explicit `GIT_DIR` as meaning "the current directory IS the
    work tree", so `git rev-parse --show-toplevel` stops walking up to find
    the real repo root and returns the caller's `cwd` unchanged instead.
    Called from a subdirectory that is exactly the failure: the "root"
    silently becomes the subdirectory rather than the repository's actual
    top level, and everything `changed_files()` does afterwards is scoped
    from the wrong place.

    Measured directly: from `couchpotato/core/db/` inside this repo, a
    foreign `GIT_DIR` makes `git rev-parse --show-toplevel` answer with that
    same subdirectory rather than the repo root.

    Exactly the leak `gitdir-leak-from-worktree-push` records: a worktree
    push exports `GIT_DIR` into a pre-push hook subprocess, and a lot of
    this project's work happens in worktrees.
    """
    throwaway = _build_throwaway_repo(tmp_path_factory.mktemp("throwaway"))
    subdir = temp_repo / "couchpotato" / "core" / "db"
    assert subdir.is_dir(), "fixture assumption is wrong -- no such subdirectory"

    monkeypatch.setenv("GIT_DIR", str(throwaway / ".git"))
    _assert_git_dir_injection_took_effect(subdir, throwaway, env=dict(os.environ))

    root = mutation_changed.git_toplevel(subdir)

    assert root == temp_repo, (
        f"git_toplevel() returned {root} under a leaked GIT_DIR pointing at "
        f"{throwaway} -- expected the real repo root {temp_repo}"
    )


def test_changed_files_ignores_a_leaked_git_dir(tmp_path, tmp_path_factory, monkeypatch):
    """The same leak reaching `changed_files()`'s three git calls
    (merge-base, diff, ls-files). With a foreign `GIT_DIR` set, HEAD and the
    base ref resolve inside the THROWAWAY repository's object database, so
    the diff compares a stranger's one-file tree against this repo's real
    working directory -- every file this repo has that the throwaway does
    not know about then looks "changed".

    Asserted against the real diff result, not a count: a count assertion
    would pass by coincidence if the throwaway happened to hold a similar
    number of files.

    Deliberately does NOT use the shared `temp_repo` fixture. An earlier
    version of this test did, and relied entirely on `temp_repo`'s
    README.md to tell a correct answer from a leaked one: the throwaway
    repo's one file (`only-file.txt`) diffs as a DELETION against the real
    working tree and `changed_files()` filters deletions out
    (`--diff-filter=d`), so it contributes nothing either way, and the
    tweaked adapter file is correctly present in both the leaked and the
    real answer regardless of the leak. README.md was the only thing that
    ever differed between them -- a reviewer proved it by deleting README.md
    from the fixture and removing all four scrubs from production code, and
    the test stayed green against completely unfixed code. This version
    builds its own untouched marker file so the discriminating evidence
    belongs to the test that depends on it, not to an unrelated fixture that
    does not know it is load-bearing.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    adapter = repo / "couchpotato" / "core" / "db" / "sqlite_adapter.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("def get(key):\n    return key\n")
    # Committed on master AND left untouched on feature, so it must be
    # ABSENT from the correct diff -- its presence in the leaked one is
    # this test's own evidence, not a borrowed coincidence.
    marker = repo / "leak_discriminator.txt"
    marker.write_text("untouched by the real diff\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    _git(repo, "checkout", "-q", "-b", "feature")

    adapter.write_text("def get(key):\n    return key.strip()\n")
    _git(repo, "commit", "-qam", "tweak adapter")

    expected = mutation_changed.changed_files("master", repo)
    assert expected == ["couchpotato/core/db/sqlite_adapter.py"], (
        "fixture assumption is wrong -- the baseline diff itself changed"
    )
    assert "leak_discriminator.txt" not in expected, (
        "fixture assumption is wrong -- the marker must be untouched by "
        "the correct diff, or its presence under the leak proves nothing"
    )

    throwaway = _build_throwaway_repo(tmp_path_factory.mktemp("throwaway"))
    monkeypatch.setenv("GIT_DIR", str(throwaway / ".git"))
    _assert_git_dir_injection_took_effect(repo, throwaway, env=dict(os.environ))

    leaked = mutation_changed.changed_files("master", repo)

    assert leaked == expected, (
        f"a leaked GIT_DIR changed changed_files()'s answer: {leaked!r} vs "
        f"the real result {expected!r} -- scope collapsed to a different "
        f"repository ({throwaway})"
    )


def test_script_ignores_a_leaked_git_dir_end_to_end(tmp_path, tmp_path_factory):
    """The tests above drive `git_toplevel()` and `changed_files()` as
    imported functions. What `make mutation-changed` actually runs is
    `scripts/mutation_changed.py` as a SUBPROCESS, with whatever `GIT_DIR`
    is already in its environment -- and `run_script()` elsewhere in this
    file always passes `sanitized_git_env()`, so no other test in this
    suite ever starts the script itself under a leak. This is the one that
    does: it also covers `runner_env()`, since the script is invoked the
    same way regardless of which environment it goes on to build.

    Deliberately does not use the shared `temp_repo` fixture, for the same
    reason `test_changed_files_ignores_a_leaked_git_dir` does not. An
    earlier version of this test did, and its marker was `temp_repo`'s
    README.md -- which is not source-scoped, so `python_targets()`/
    `js_targets()` silently drop it before it ever reaches the printed
    command line. Confirmed by mutation: with all four `env=git_env()`
    call sites removed, that version still passed. This one's marker is a
    `.js` file under the stryker-scoped directory, matching the real
    symptom this issue measured: "the script invented seven JavaScript
    mutation targets the branch never touched."
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    adapter = repo / "couchpotato" / "core" / "db" / "sqlite_adapter.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("def get(key):\n    return key\n")
    # Committed on master AND left untouched on feature, JS/TS-scoped
    # (stryker.conf.json's `mutate`), so a leak that makes it look "added"
    # invents a real mutation target instead of being silently dropped by
    # scope filtering the way a non-scoped file (README.md) would be.
    marker = repo / "couchpotato" / "static" / "scripts" / "ui" / "marker.js"
    marker.parent.mkdir(parents=True)
    marker.write_text("// untouched by the real diff\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    _git(repo, "checkout", "-q", "-b", "feature")

    adapter.write_text("def get(key):\n    return key.strip()\n")
    _git(repo, "commit", "-qam", "tweak adapter")

    correct = run_script(repo, "--base", "master", "--dry-run")
    assert correct.returncode == 0, correct.stderr
    assert "1 python target(s), 0 js target(s)" in correct.stdout, (
        f"fixture assumption is wrong -- the correct run does not show the "
        f"expected target counts:\n{correct.stdout}"
    )

    throwaway = _build_throwaway_repo(tmp_path_factory.mktemp("throwaway"))
    hostile_env = {**sanitized_git_env(), "GIT_DIR": str(throwaway / ".git")}
    _assert_git_dir_injection_took_effect(repo, throwaway, env=hostile_env)

    leaked = run_script(repo, "--base", "master", "--dry-run", env=hostile_env)

    assert leaked.returncode == 0, leaked.stderr
    assert leaked.stdout == correct.stdout, (
        f"a leaked GIT_DIR changed the script's dry-run output:\n"
        f"correct: {correct.stdout!r}\nleaked:  {leaked.stdout!r}"
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
