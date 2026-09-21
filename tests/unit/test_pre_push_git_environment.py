"""Regression coverage for the pre-push hook's inherited Git environment."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

from tests.unit.conftest import sanitized_git_env


HOOK = Path(__file__).resolve().parents[2] / '.githooks' / 'pre-push'


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_hook_repo(path: Path, identity_log: Path, selected: str) -> None:
    path.mkdir()
    subprocess.run(
        ['git', 'init', '-q'],
        cwd=path,
        env=sanitized_git_env(),
        check=True,
    )
    hook = path / '.githooks' / 'pre-push'
    hook.parent.mkdir()
    shutil.copy2(HOOK, hook)
    _write_executable(
        path / 'scripts' / 'push_base_ref.sh',
        '#!/bin/sh\nprintf "origin/master\\n"\n',
    )
    _write_executable(
        path / 'scripts' / 'needs_e2e.sh',
        '#!/bin/sh\nexit 1\n',
    )
    _write_executable(
        path / 'scripts' / 'verify.sh',
        '#!/bin/sh\n'
        f'printf "%s\\n" "{selected}"\n'
        f'printf "%s|%s|%s\\n" "${{GIT_AUTHOR_NAME-}}" '
        f'"${{GIT_COMMITTER_EMAIL-}}" "${{GIT_FUTURE_POISON-}}" > "{identity_log}"\n',
    )


def test_hook_scrubs_git_namespace_before_resolving_repository(tmp_path):
    """A foreign GIT_DIR must not redirect even the hook's first git call."""
    target = tmp_path / 'target'
    foreign = tmp_path / 'foreign'
    identity_log = tmp_path / 'identity.log'
    _make_hook_repo(target, identity_log, 'TARGET_GATE')
    _make_hook_repo(foreign, identity_log, 'FOREIGN_GATE')

    env = os.environ.copy()
    env.update({
        'GIT_DIR': str(foreign / '.git'),
        'GIT_WORK_TREE': str(foreign),
        'GIT_FUTURE_POISON': 'must-be-removed',
        'GIT_AUTHOR_NAME': 'Preserved Author',
        'GIT_COMMITTER_EMAIL': 'preserved@example.com',
    })
    result = subprocess.run(
        [str(target / '.githooks' / 'pre-push')],
        cwd=target,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert 'TARGET_GATE' in result.stdout
    assert 'FOREIGN_GATE' not in result.stdout
    assert identity_log.read_text().strip() == (
        'Preserved Author|preserved@example.com|'
    )
