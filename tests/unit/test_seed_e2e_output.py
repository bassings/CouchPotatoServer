"""The seeder reports whether real fixture rows were inserted or reused."""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'libs'))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
import seed_e2e_data  # noqa: E402


def test_second_real_seed_reports_existing_profile_movie_and_releases(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(seed_e2e_data, '_REPO_ROOT', os.path.realpath(tmp_path))
    target = tmp_path / '.e2e-seed-output'

    assert seed_e2e_data.main(['--data_dir', str(target)]) == 0
    first = capsys.readouterr()
    assert 'already present' not in first.out
    assert first.err == ''

    assert seed_e2e_data.main(['--data_dir', str(target)]) == 0
    second = capsys.readouterr()
    assert second.out.count('already present') >= 3
    assert 'profile %s: already present' % seed_e2e_data.PROFILE_ID in second.out
    assert 'movie   %s (imdb %s): already present' % (
        seed_e2e_data.MOVIE_ID, seed_e2e_data.IMDB_ID,
    ) in second.out
    assert any(
        line.strip().startswith('release ') and line.endswith(': already present')
        for line in second.out.splitlines()
    )
    assert second.err == ''
