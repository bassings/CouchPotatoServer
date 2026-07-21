"""Tests for scripts/release/next_beta_version.py — the pure version-arithmetic
component of the beta/prod release-channel split (specs/FEAT-release-channels.md,
Component 1). Each test name/AC# maps directly to the spec's acceptance criteria
(AC1-AC11), asserting the exact expected output string for each tag-list input.

Model: minor bump per commit — every build is strictly higher than the last
(beta suffix always .1), computed from the highest minor across BOTH stable and
beta tags.
"""
import subprocess
import sys
from pathlib import Path

from scripts.release.next_beta_version import next_beta_version

SCRIPT_PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'release' / 'next_beta_version.py'


def test_ac1_single_stable_tag_bumps_minor():
    assert next_beta_version(['v3.9.1']) == '3.10.0-beta.1'


def test_ac2_lower_minor_stable_and_beta_tags_dont_affect_bump():
    assert next_beta_version(['v3.9.0', 'v3.9.0-beta.1', 'v3.9.1']) == '3.10.0-beta.1'


def test_ac3_existing_beta_advances_the_minor():
    # Minor bump per commit: an in-flight beta pushes the next build past it.
    assert next_beta_version(['v3.9.1', 'v3.10.0-beta.1']) == '3.11.0-beta.1'


def test_ac4_successive_commits_keep_climbing_the_minor():
    assert next_beta_version(
        ['v3.9.1', 'v3.10.0-beta.1', 'v3.11.0-beta.1']
    ) == '3.12.0-beta.1'


def test_ac5_patch_release_is_ignored_bump_uses_max_minor_not_max_patch():
    assert next_beta_version(['v3.8.1', 'v3.9.1']) == '3.10.0-beta.1'


def test_ac6_non_conforming_tags_are_ignored():
    assert next_beta_version(['foo', 'v3.9.1', 'nightly']) == '3.10.0-beta.1'


def test_ac7_empty_tag_list_yields_initial_version():
    assert next_beta_version([]) == '0.1.0-beta.1'


def test_ac8_bump_is_scoped_to_highest_major_only():
    assert next_beta_version(['v3.9.1', 'v4.0.0']) == '4.1.0-beta.1'


def test_ac10_lone_beta_with_no_stable_advances_the_minor():
    assert next_beta_version(['v3.10.0-beta.1']) == '3.11.0-beta.1'


def test_ac11_stable_already_at_bumped_minor_does_not_collide():
    assert next_beta_version(['v3.9.1', 'v3.10.0']) == '3.11.0-beta.1'


def test_ac9_cli_output_has_no_leading_v_and_single_trailing_newline():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), 'v3.9.1'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == '3.10.0-beta.1\n'
    assert not result.stdout.startswith('v')


def test_cli_reads_tags_from_stdin_only_with_explicit_flag():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), '--stdin'],
        input='v3.9.1\nv3.10.0-beta.1\n',
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == '3.11.0-beta.1\n'


def test_cli_with_no_argv_reads_git_tags_even_when_stdin_is_not_a_tty(tmp_path):
    """Regression: a GitHub Actions `run:` step has a NON-TTY stdin. An
    isatty()-based stdin fallback therefore read EOF and returned the
    empty-history version (0.1.0-beta.1) on every CI build instead of
    consulting git — which would have broken beta versioning on the very
    first run and collided on every run after. Exercise the real CI shape:
    no argv, stdin connected to /dev/null, inside a git repo with tags.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True)  # noqa: E731
    run('git', 'init', '-q')
    run('git', 'config', 'user.email', 't@example.com')
    run('git', 'config', 'user.name', 'T')
    (repo / 'f.txt').write_text('x')
    run('git', 'add', 'f.txt')
    run('git', 'commit', '-qm', 'init')
    run('git', 'tag', 'v3.9.1')
    run('git', 'tag', 'v3.10.0-beta.1')

    with open('/dev/null') as devnull:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=repo,
            stdin=devnull,
            capture_output=True,
            text=True,
            check=True,
        )

    assert result.stdout == '3.11.0-beta.1\n', (
        'CI invocation must read git tags, not fall through to empty stdin'
    )
