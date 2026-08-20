"""`sanitized_git_env()` strips git's whole `GIT_*` namespace, not a list of
names (T57).

`tests/unit/conftest.py` used to deny six specific "location" variables --
`GIT_DIR` and its siblings -- built on the axis "what redirects the repo".
That axis missed two real escapes: `GIT_CONFIG_PARAMETERS` (which `git -c
foo=bar <cmd>` EXPORTS into the environment of every subprocess it spawns,
so `git -c ... push` run from a worktree hands the suite arbitrary config)
and `GIT_TEMPLATE_DIR` (arbitrary code execution via a hook copied from the
template dir into the new repo and then RUN -- and not a location variable
at all, so no denylist built on that axis would ever have named it). See the
comment above `GIT_IDENTITY_ENV_PREFIXES` in `conftest.py` for the full
argument and the measurement behind it.

This file is deliberately separate from `test_fixtures_do_not_leak_gitdir.py`,
which polices CALL SITES (does every `git` subprocess call in the tree pass
`env=sanitized_git_env()`?) and the `GIT_DIR` location leak specifically.
This file polices what `sanitized_git_env()` itself removes -- a different
question, answered once, about one function -- and sits alongside that file
rather than folding into it, because the two guards fail for unrelated
reasons and a shared file would blur which one a red run is naming.

A previous attempt at this same guard, elsewhere, was proved vacuous: it
named `GIT_TEMPLATE_DIR` and `GIT_CONFIG_COUNT` explicitly, so it pinned two
real variables while its docstring claimed to pin the PROPERTY, and it
stayed green through three separate mutations, including a revert straight
back to a six-name denylist. `TestTheNamespaceIsStrippedNotAList` below is
written to fail that same way: it asserts against variable names git has
never defined and never will, which no list of REAL names -- however long --
can ever satisfy.
"""
import os
import stat
import subprocess

from tests.unit.conftest import GIT_IDENTITY_ENV_PREFIXES, sanitized_git_env


class TestTheNamespaceIsStrippedNotAList:
    """The load-bearing assertion a denylist can never satisfy.

    If `sanitized_git_env()` is genuinely a namespace rule, an unrecognised
    `GIT_*` variable is removed whether or not anyone has ever heard of it.
    If it is secretly still a list of known names, an unrecognised variable
    survives -- and a test that only ever probes `GIT_TEMPLATE_DIR` or
    `GIT_CONFIG_PARAMETERS` cannot tell the two apart, because both
    implementations pass it.
    """

    def test_an_unknown_GIT_variable_is_stripped(self, monkeypatch):
        monkeypatch.setenv('GIT_NOT_A_REAL_VARIABLE_47B3F9', 'anything')
        env = sanitized_git_env()
        assert 'GIT_NOT_A_REAL_VARIABLE_47B3F9' not in env, (
            'sanitized_git_env() let an unrecognised GIT_* variable through '
            '-- it is pinning specific names again, not the namespace'
        )

    def test_a_second_unknown_GIT_variable_is_also_stripped(self, monkeypatch):
        # A differently-shaped name from the one above, so passing the first
        # assertion cannot be a coincidence of matching one hardcoded string
        # somewhere in the implementation.
        monkeypatch.setenv('GIT_SOME_FUTURE_FLAG_THAT_DOES_NOT_EXIST_YET', '1')
        env = sanitized_git_env()
        assert 'GIT_SOME_FUTURE_FLAG_THAT_DOES_NOT_EXIST_YET' not in env, (
            'sanitized_git_env() let an unrecognised GIT_* variable through '
            '-- it is pinning specific names again, not the namespace'
        )


class TestTheAllowlistSurvives:
    """The exception the namespace rule deliberately carves out: the
    variables that change what a commit RECORDS (author/committer identity
    and date), never where an operation LANDS or what git EXECUTES."""

    def test_commit_identity_variables_survive(self, monkeypatch):
        identity_vars = {
            'GIT_AUTHOR_NAME': 'Test Author',
            'GIT_AUTHOR_EMAIL': 'author@example.com',
            'GIT_AUTHOR_DATE': '2026-01-01T00:00:00',
            'GIT_COMMITTER_NAME': 'Test Committer',
            'GIT_COMMITTER_EMAIL': 'committer@example.com',
            'GIT_COMMITTER_DATE': '2026-01-01T00:00:00',
        }
        for key, value in identity_vars.items():
            monkeypatch.setenv(key, value)

        env = sanitized_git_env()

        for key, value in identity_vars.items():
            assert env.get(key) == value, (
                '%s was stripped -- the allowlist must let commit-identity '
                'variables through, or every caller that relies on '
                'GIT_AUTHOR_*/GIT_COMMITTER_* for a scripted commit breaks'
                % key
            )

    def test_the_allowlist_is_exactly_the_two_documented_prefixes(self):
        # Pins the CONSTANT the function is documented to use, not just its
        # current behaviour, so a future edit that widens the prefix list
        # (or narrows it) without updating the surrounding comment is caught
        # here rather than discovered later by an unrelated variable quietly
        # surviving, or failing to survive, the strip.
        assert GIT_IDENTITY_ENV_PREFIXES == ('GIT_AUTHOR_', 'GIT_COMMITTER_')


class TestNonGitVariablesAreUntouched:
    """A namespace strip must stay ON the namespace: writing one too broad
    (matching anything that merely contains "GIT") is as easy a mistake as
    writing one too narrow, and both are invisible in a green run unless
    something specifically checks the boundary."""

    def test_an_unrelated_variable_survives(self, monkeypatch):
        monkeypatch.setenv('COUCHPOTATO_TEST_UNRELATED_VAR', 'kept')
        env = sanitized_git_env()
        assert env.get('COUCHPOTATO_TEST_UNRELATED_VAR') == 'kept'

    def test_a_variable_that_merely_contains_GIT_as_a_substring_survives(
        self, monkeypatch,
    ):
        # "LEGIT_UNRELATED_TOKEN" contains the substring "GIT_" starting at
        # index 2 -- it must not trip a strip that checks containment instead
        # of a leading-namespace prefix.
        monkeypatch.setenv('LEGIT_UNRELATED_TOKEN', 'kept')
        env = sanitized_git_env()
        assert env.get('LEGIT_UNRELATED_TOKEN') == 'kept'

    def test_PATH_survives(self):
        # Without PATH, git itself cannot be exec'd by any caller of this
        # function -- the strongest available check that the strip has not
        # eaten something load-bearing well outside the GIT_* namespace.
        env = sanitized_git_env()
        assert 'PATH' in env and env['PATH']


class TestTheTemplateDirEscapeIsClosed:
    """The concrete attack from the T57 measurement, driven directly rather
    than asserted from documentation or log text: a poisoned
    `GIT_TEMPLATE_DIR` containing an executable `hooks/pre-commit` is copied
    into every repo `git init` creates from that template, and RUN during
    the repo's own first commit. Proven hostile with a hook that writes a
    file to disk -- the sentinel's absence is the entire assertion, not a
    substring of a log line.
    """

    @staticmethod
    def _plant_hook(template_dir, sentinel_path):
        hooks_dir = template_dir / 'hooks'
        hooks_dir.mkdir(parents=True)
        hook = hooks_dir / 'pre-commit'
        hook.write_text('#!/bin/sh\ntouch "%s"\nexit 0\n' % sentinel_path)
        mode = hook.stat().st_mode
        hook.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return hook

    @staticmethod
    def _seed_commit(repo_dir, env=None):
        # `sanitized_git_env() if env is None else env` -- the same IfExp
        # shape `assert_git_dir_is` uses in conftest.py, and the one form
        # `test_no_test_file_invokes_git_without_sanitizing_the_environment`
        # recognises as sanitised without tracking dataflow through a bound
        # name. Deliberately NOT `env = env or sanitized_git_env()` bound
        # outside the closure and reused: that shape is exactly what the
        # call-site guard refuses to trust, on purpose, so the callers below
        # can hand this helper either the real sanitiser or a deliberately
        # raw environment and still pass that guard's scan.
        def git(*args):
            return subprocess.run(
                ['git', *args], cwd=str(repo_dir),
                env=sanitized_git_env() if env is None else env,
                capture_output=True, text=True,
            )

        init = git('init', '-q', '-b', 'main')
        assert init.returncode == 0, 'git init itself failed: %s' % init.stderr
        git('config', 'user.email', 't@example.com')
        git('config', 'user.name', 'T')
        (repo_dir / 'f.txt').write_text('seed\n')
        git('add', '-A')
        commit = git('commit', '-q', '-m', 'seed')
        assert commit.returncode == 0, (
            'the seed commit itself failed, which proves nothing about the '
            'hook either way: %s' % commit.stderr
        )
        head = git('rev-parse', 'HEAD')
        assert head.returncode == 0 and head.stdout.strip(), (
            'no commit was actually created -- the test setup is broken, '
            'not just the assertion under test'
        )

    def test_the_attack_is_real_without_the_scrub(self, tmp_path, monkeypatch):
        """Positive control, run FIRST so the negative result below means
        something: proves the sentinel-presence/absence assertion is
        actually pinned on the scrub, not on this platform or git version
        silently declining to copy or run hooks from a template dir."""
        template = tmp_path / 'hostile_template'
        sentinel = tmp_path / 'PWNED_CONTROL'
        self._plant_hook(template, sentinel)

        repo_dir = tmp_path / 'repo'
        repo_dir.mkdir()

        monkeypatch.setenv('GIT_TEMPLATE_DIR', str(template))
        # Deliberately the RAW ambient environment, not sanitized_git_env()
        # -- this is what a fixture would hand git if the scrub did not
        # exist at all.
        raw_env = os.environ.copy()

        self._seed_commit(repo_dir, raw_env)

        assert sentinel.exists(), (
            'the hook did not run even against the raw, unsanitised ambient '
            'environment -- this platform/git version does not exercise the '
            'attack this guard exists to close, so the test below would '
            'pass for the wrong reason'
        )

    def test_a_hook_in_a_poisoned_template_dir_never_runs(
        self, tmp_path, monkeypatch,
    ):
        template = tmp_path / 'hostile_template'
        sentinel = tmp_path / 'PWNED'
        self._plant_hook(template, sentinel)

        repo_dir = tmp_path / 'repo'
        repo_dir.mkdir()

        # The poison sits in the AMBIENT environment, exactly where a real
        # attacker or a misconfigured runner would place it -- this is what
        # a fixture receives before sanitized_git_env() ever runs, not a
        # value handed to the function as an argument.
        monkeypatch.setenv('GIT_TEMPLATE_DIR', str(template))

        env = sanitized_git_env()
        assert 'GIT_TEMPLATE_DIR' not in env, (
            'sanity check before the real assertion: the scrub must remove '
            'GIT_TEMPLATE_DIR from the returned env, or the git calls below '
            'are not actually exercising the fix'
        )

        self._seed_commit(repo_dir, env)

        assert not sentinel.exists(), (
            'the pre-commit hook from the poisoned GIT_TEMPLATE_DIR '
            'EXECUTED during the fixture\'s own seed commit -- '
            'sanitized_git_env() did not strip GIT_TEMPLATE_DIR from the '
            'environment handed to git'
        )
