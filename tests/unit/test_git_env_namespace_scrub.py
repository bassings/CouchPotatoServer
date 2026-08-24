r"""`sanitized_git_env()` strips git's whole `GIT_*` namespace, not a list of
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

TWO LAYERS apply this rule, and both are covered here.
`tests/unit/conftest.py`'s `sanitized_git_env()` returns a sanitised COPY for
an explicit `env=`, tested by `TestTheNamespaceIsStrippedNotAList` and the
rest of the classes above `TestTheRootProcessWideScrubAppliesTheSameRule`.
`tests/conftest.py` also pops the same namespace directly out of
`os.environ`, once, for the WHOLE test process, before anything is
collected -- a denylist reverted there would leave `sanitized_git_env()`
correct while every subprocess that never calls it (the whole point of that
layer, per its own comment) stayed exposed. `TestTheRootProcessWideScrubAppliesTheSameRule`
proves that layer independently, in a subprocess, because its scrub runs
once at import time, before any test in THIS process starts -- there is no
way to poison `os.environ` and re-trigger it from inside a running test.

The whole-tree sweep for anything that reads a `GIT_*` variable (the claim
`tests/conftest.py`'s "safe to do unconditionally" comment rests on,
widened from GIT_DIR alone to the full namespace for T57's follow-up):

    grep -rn "GIT_" --include='*.py' --include='*.sh' --include='*.yml' \
      --include='*.yaml' . | grep -v '\.venv' | grep -v '/\.git/'

and, with no extension filter at all, to catch anything outside those
extensions:

    grep -rn "GIT_" . | grep -vE '\.venv/|/\.git/|node_modules/|\.pytest_cache/|__pycache__/|/\.next/|/dist/|/build/'

Every hit outside this file, `tests/conftest.py`, `tests/unit/conftest.py`,
`test_fixtures_do_not_leak_gitdir.py`, `test_mutation_changed.py` and
`test_hybrid_gate.py` (all already accounted for above) is
documentation in `specs/REMEDIATION-2026-08.md`. Nothing reads a `GIT_*`
variable, so nothing depends on inheriting one outside the identity
allowlist.
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

from tests.unit.conftest import GIT_IDENTITY_ENV_PREFIXES, sanitized_git_env

REPO = Path(__file__).resolve().parents[2]


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

    def test_a_variable_beginning_GIT_without_the_separator_survives(
        self, monkeypatch,
    ):
        # The likelier typo than a containment bug: a prefix one character
        # short. `startswith('GIT')` still strips every GIT_* the tests above
        # check, so all of them stay green while GITHUB_* is silently deleted
        # from every environment this function hands to a subprocess. On a CI
        # runner that is GITHUB_TOKEN, GITHUB_REF and the rest of the family.
        # Nothing in this suite reads them today, which is exactly why no
        # other assertion here can see the mistake.
        monkeypatch.setenv('GITHUB_TOKEN', 'kept')
        monkeypatch.setenv('GOPATH', 'kept')
        env = sanitized_git_env()
        assert env.get('GITHUB_TOKEN') == 'kept', (
            'a variable starting with "GIT" but outside the GIT_ namespace '
            'was stripped -- the prefix is missing its trailing underscore'
        )
        assert env.get('GOPATH') == 'kept', (
            'GOPATH was stripped -- the prefix has collapsed to "G"'
        )

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

    def test_the_attack_is_real_without_the_scrub(self, tmp_path):
        """Positive control, run FIRST so the negative result below means
        something: proves the sentinel-presence/absence assertion is
        actually pinned on the scrub, not on this platform or git version
        silently declining to copy or run hooks from a template dir."""
        template = tmp_path / 'hostile_template'
        sentinel = tmp_path / 'PWNED_CONTROL'
        self._plant_hook(template, sentinel)

        repo_dir = tmp_path / 'repo'
        repo_dir.mkdir()

        # An environment built from NOTHING, carrying only what git needs to
        # run plus the single variable under test. Not `os.environ.copy()`,
        # and not `sanitized_git_env()` either, and the difference between
        # those two rejected options is the whole point.
        #
        # The raw ambient copy is what this test used until review measured
        # the cost. An ambient GIT_DIR -- exactly what git exports into a
        # `pre-push` hook from a worktree, which is the leak this file exists
        # to close -- redirects every command below into the developer's REAL
        # repository, and `assert sentinel.exists()` says nothing about where
        # the commit landed, so it reports PASS while doing it. Measured on a
        # victim repo with the root scrub regressed: a stray commit,
        # `user.name` overwritten, a tracked file dropped from the index,
        # test green.
        #
        # `sanitized_git_env()` fixes that single fault and was the first fix
        # taken here, but it only MOVES the dependency: this test would then
        # be safe because of a function that this same file exists to prove
        # can regress, and a second review measured a double fault (root
        # scrub regressed AND the sanitiser no-oped) still damaging the
        # victim while reporting PASS.
        #
        # A literal dict depends on neither layer, so the control keeps
        # working when either or both regress -- which is the point of a
        # control. `_seed_commit` sets user.email/user.name locally, so
        # nothing further is needed.
        #
        # HOME is carried from the ambient environment ON PURPOSE, and an
        # earlier revision of this test got that wrong in a way worth
        # recording. Aiming HOME at `tmp_path` looks like extra isolation and
        # is really a hole: git reads GLOBAL config from HOME, and a global
        # `core.hooksPath` copies a template hook into a new repo while
        # SUPPRESSING its execution. Measured: hook copied YES, hook executed
        # NO. That is precisely "this platform silently declines to run
        # hooks", the condition the assertion below exists to announce, and a
        # synthetic HOME hides it -- the negative test then passes because
        # hooks are globally off rather than because anything stripped
        # GIT_TEMPLATE_DIR, and this control cannot tell you so. The control
        # must share the global-config regime of the test it validates.
        #
        # The isolation that change claimed to buy did not exist: an explicit
        # GIT_TEMPLATE_DIR overrides a global `init.templateDir` anyway,
        # because environment beats config. Measured both ways.
        #
        # Neither PATH nor HOME is in the GIT_* namespace, so carrying them
        # keeps this dict independent of both scrub layers. Note the residual
        # limit: HOME covers global config only, so a SYSTEM-level
        # (`/etc/gitconfig`) `core.hooksPath` is still caught here, since no
        # GIT_CONFIG_NOSYSTEM is set.
        raw_env = {
            'PATH': os.environ.get('PATH', ''),
            'HOME': os.environ.get('HOME', str(tmp_path)),
            'GIT_TEMPLATE_DIR': str(template),
        }

        self._seed_commit(repo_dir, raw_env)

        assert sentinel.exists(), (
            'the hook did not run even with GIT_TEMPLATE_DIR set and '
            'nothing stripping it -- this platform/git version does not '
            'exercise the attack this guard exists to close, so the test '
            'below would pass for the wrong reason. Look at git version and '
            'core.hooksPath (global config is deliberately in scope here), '
            'NOT at an ambient GIT_* variable: this test reads only PATH and '
            'HOME from the environment'
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


class TestTheRootProcessWideScrubAppliesTheSameRule:
    """`tests/conftest.py` pops the same `GIT_*` namespace directly out of
    `os.environ`, once, for the whole test process, before collection --
    the layer `test_fixtures_do_not_leak_gitdir.py`'s
    `test_the_process_scrub_protects_a_file_that_never_heard_of_the_helper`
    already exercises for the GIT_DIR leak specifically. This class is the
    T57 equivalent of that test: it proves the ROOT scrub applies the
    namespace rule, not a list, independently of `sanitized_git_env()`.

    Every case here runs a fresh Python subprocess rather than poisoning
    `os.environ` in-process. `tests/conftest.py`'s scrub is a MODULE-LEVEL
    side effect that fires once, the moment the module is first imported --
    by the time any test in this file runs, that has already happened in
    THIS process, using whatever `os.environ` looked like at collection
    start. Setting a variable now and re-importing would hit Python's module
    cache and run nothing. A subprocess is the only way to observe the
    scrub actually firing.
    """

    @staticmethod
    def _import_conftest_and_report(env_vars):
        """Run `import tests.conftest` in a fresh subprocess with the given
        environment, and report which of `env_vars` survived into
        `os.environ` afterwards -- one name per output line, in the same
        order as `env_vars`, so the caller can assert on each independently
        without a second subprocess round-trip per variable."""
        poisoned = os.environ.copy()
        poisoned.update(env_vars)
        probe = (
            'import tests.conftest, os\n'
            + '\n'.join(
                "print('PRESENT' if %r in os.environ else 'ABSENT')" % name
                for name in env_vars
            )
        )
        result = subprocess.run(
            [sys.executable, '-c', probe], cwd=str(REPO), env=poisoned,
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            'importing tests.conftest failed outright, which proves nothing '
            'about the scrub: stdout=%s stderr=%s'
            % (result.stdout, result.stderr)
        )
        lines = result.stdout.strip().splitlines()
        assert len(lines) == len(env_vars), (
            'expected one PRESENT/ABSENT line per probed variable, got: %r'
            % result.stdout
        )
        return dict(zip(env_vars, lines))

    def test_an_unknown_GIT_variable_does_not_survive_process_start(self):
        report = self._import_conftest_and_report(
            {'GIT_NOT_A_REAL_VARIABLE_47B3F9': 'anything'},
        )
        assert report['GIT_NOT_A_REAL_VARIABLE_47B3F9'] == 'ABSENT', (
            'an unrecognised GIT_* variable survived importing '
            'tests.conftest -- the root scrub is pinning specific names '
            'again, not the namespace'
        )

    def test_commit_identity_variables_survive_process_start(self):
        report = self._import_conftest_and_report({
            'GIT_AUTHOR_NAME': 'Test Author',
            'GIT_COMMITTER_NAME': 'Test Committer',
        })
        assert report['GIT_AUTHOR_NAME'] == 'PRESENT', (
            'GIT_AUTHOR_NAME did not survive the root scrub -- a scripted '
            'commit relying on ambient author identity would silently lose it'
        )
        assert report['GIT_COMMITTER_NAME'] == 'PRESENT', (
            'GIT_COMMITTER_NAME did not survive the root scrub'
        )

    def test_an_unrelated_variable_survives_process_start(self):
        # LEGIT_UNRELATED_TOKEN contains "GIT_" at index 2, so it also pins
        # the containment direction at THIS layer. The per-call class has
        # covered that since the first commit; this layer did not, which left
        # the higher-leverage of the two scrubs able to delete a non-git
        # variable from the whole test process with every test still green.
        report = self._import_conftest_and_report(
            {
                'COUCHPOTATO_TEST_UNRELATED_VAR': 'kept',
                'LEGIT_UNRELATED_TOKEN': 'kept',
            },
        )
        assert report['COUCHPOTATO_TEST_UNRELATED_VAR'] == 'PRESENT', (
            'a variable outside the GIT_* namespace was removed by the root '
            'scrub -- it is too broad, not just too narrow'
        )
        assert report['LEGIT_UNRELATED_TOKEN'] == 'PRESENT', (
            'a variable merely CONTAINING "GIT_" was removed by the root '
            'scrub -- it is matching containment, not a leading namespace'
        )

    def test_a_variable_beginning_GIT_without_the_separator_survives_process_start(self):
        # The same one-character-short prefix mutation survives at THIS layer
        # too, and this is the higher-leverage of the two: the root scrub
        # mutates os.environ for the whole test process, so a prefix of 'GIT'
        # deletes GITHUB_* from every test and every subprocess any of them
        # spawns. Measured under that mutation: the full unit suite passed.
        report = self._import_conftest_and_report(
            {'GITHUB_TOKEN': 'kept', 'GOPATH': 'kept'},
        )
        assert report['GITHUB_TOKEN'] == 'PRESENT', (
            'GITHUB_TOKEN did not survive the root scrub -- the prefix is '
            'missing its trailing underscore and is eating GITHUB_*'
        )
        assert report['GOPATH'] == 'PRESENT', (
            'GOPATH did not survive the root scrub -- the prefix has '
            'collapsed to "G"'
        )
