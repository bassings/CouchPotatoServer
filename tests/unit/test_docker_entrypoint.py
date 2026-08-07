"""`docker-entrypoint.sh` is PID 1 in the shipped image, and nothing tested it.

Two things came together to make this worth pinning:

1. The false-green guard's shell rule (`scripts/check_test_traps.py`, rule 3)
   requires `set -eu` and says so in its message: "`set -e` alone lets a gate
   continue past a failure. Use `set -eu`." The one file in the repo that
   violates that rule is this one -- and the guard could not see it, because
   `DEFAULT_ROOTS` covered `tests/`, `scripts/`, `.githooks/`,
   `.github/workflows/` and `Makefile`, but no repo-root shell script.

2. Applying the rule's own remedy verbatim BREAKS the default `docker run`.
   Measured on the `set -e` original with `-u` added and no arguments:
   `line 3: $1: unbound variable`, exit 1. The container would not start.

So whoever widened the roots (the obvious fix) and followed the message would
have shipped a container that dies at PID 1 on the most common invocation.
Both halves had to move together: guard the `$1` expansions first, then add
`-u`, then let the checker see the file.

These tests pin the dispatch itself, not the `set` line, so they would have
caught that breakage regardless of which order the two changes arrived in.
`test_declares_set_eu` is the other half: it stops `-u` being quietly dropped
again to "fix" a future unbound-variable error, which would restore exactly
the swallowed-failure behaviour the rule exists to prevent.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / 'docker-entrypoint.sh'

# Every stub records its own name and argv, then exits 0. `exec` means the
# entrypoint's own process is replaced, so whichever stub runs last is what
# the container would actually have become.
_STUB = '#!/bin/sh\necho "%s $*"\n'


@pytest.fixture
def stub_path(tmp_path):
    """A PATH holding stand-ins for the commands the entrypoint execs.

    The real ones cannot run here: `su-exec` is Alpine-only, and `chown -R`
    on /config and /data would need root and those paths do not exist.
    """
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for name in ('chown', 'su-exec', 'python3', 'some-other-command'):
        stub = bindir / name
        stub.write_text(_STUB % name)
        stub.chmod(0o755)
    return bindir


def run_entrypoint(stub_path, *args):
    env = dict(os.environ, PATH='%s:%s' % (stub_path, os.environ['PATH']))
    return subprocess.run(
        ['sh', str(ENTRYPOINT), *args],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
    )


class TestDispatch:
    def test_no_arguments_starts_couchpotato_as_the_couchpotato_user(self, stub_path):
        # The default `docker run` path, and the one that `set -u` broke.
        result = run_entrypoint(stub_path)

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[-1] == (
            'su-exec couchpotato python3 CouchPotato.py --console_log '
            '--data_dir=/data --config_file=/config/config.ini'
        )

    def test_a_leading_flag_is_appended_to_the_default_command(self, stub_path):
        result = run_entrypoint(stub_path, '--debug')

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[-1] == (
            'su-exec couchpotato python3 CouchPotato.py --console_log '
            '--data_dir=/data --config_file=/config/config.ini --debug'
        )

    def test_an_explicit_python3_command_replaces_the_default_entirely(self, stub_path):
        # docker-compose `command:` overrides arrive this way.
        result = run_entrypoint(stub_path, 'python3', '-c', 'pass')

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[-1] == 'su-exec couchpotato python3 -c pass'

    def test_any_other_command_is_exec_d_directly_without_su_exec(self, stub_path):
        # Deliberately NOT dropped to the couchpotato user: this is the
        # `docker run <image> sh` debugging path.
        result = run_entrypoint(stub_path, 'some-other-command', 'arg')

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[-1] == 'some-other-command arg'

    def test_an_empty_first_argument_still_starts_the_default(self, stub_path):
        # `docker run <image> ""`. Distinct from no-arguments: `$1` is SET
        # here, so it exercises the `-z` branch rather than the `${1:-}`
        # default, and a `${1-}` (unset-only) expansion would pass the test
        # above while failing this one.
        result = run_entrypoint(stub_path, '')

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[-1].startswith(
            'su-exec couchpotato python3 CouchPotato.py --console_log'
        )


class TestShellSafety:
    def test_declares_set_eu(self):
        # Not a style preference. Without -e the chown failure path continues;
        # without -u a typo'd variable expands to empty and the entrypoint
        # execs a subtly wrong command as root.
        #
        # Matched as a DIRECTIVE, not as a substring. `'set -eu' in source`
        # is vacuous here: the comment block above the directive explains the
        # -u trap and contains the literal string, so that spelling stayed
        # green with `set -e` on the executable line. Caught by running the
        # mutation rather than by reading it -- `make check-traps` went red
        # and this test did not, which is the wrong way round for the test
        # that is meant to be specific about this file.
        directives = [
            line.strip() for line in ENTRYPOINT.read_text().splitlines()
            if line.strip().startswith('set -') and not line.lstrip().startswith('#')
        ]

        assert directives, 'docker-entrypoint.sh has no `set` directive at all'
        assert 'set -eu' in directives, (
            'docker-entrypoint.sh must use `set -eu`; found %r. If -u was '
            'dropped to fix an unbound-variable error, guard the expansion '
            'with ${var:-} instead -- that is what the $1 references here '
            'already do.' % directives
        )

    def test_is_covered_by_the_false_green_guard(self):
        # The guard that requires `set -eu` has to be able to SEE this file.
        # It could not until the repo-root shell scripts were added to
        # DEFAULT_ROOTS, which is why the violation survived.
        import sys
        sys.path.insert(0, str(REPO_ROOT / 'scripts'))
        import check_test_traps

        covered = any(
            root == ENTRYPOINT or (root.is_dir() and ENTRYPOINT.is_relative_to(root))
            for root in check_test_traps.DEFAULT_ROOTS
        )
        assert covered, (
            'docker-entrypoint.sh is not in check_test_traps.DEFAULT_ROOTS, so '
            'the shell rule cannot see PID 1 of the shipped image.'
        )
