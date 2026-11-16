"""The read-back the E2E suite uses to assert on a worker's real `config.ini`.

The E2E checks the settings FILE, not only the request body or the page's own
state (SEC-004 AC-QA-10, AC-QA-12). It shells out to this helper, which reads
through the provider's real reader (`getHosts` for newznab and torrentpotato,
the enabler-and-URL pairing for the automation readers), so a test cannot pass
against a reader that is gentler than the one the server runs.

The one property that matters most is that reading NEVER writes: the helper loads
a copy, because loading registers defaults and saves.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'libs'))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT))
import seed_e2e_data  # noqa: E402

HELPER = [sys.executable, '-m', 'tests.helpers.config_readback']


def run_raw(*args):
    return subprocess.run(
        [*HELPER, *[str(arg) for arg in args]],
        capture_output=True, text=True, timeout=60, check=False, cwd=REPO_ROOT,
    )


def run_helper(*args):
    completed = run_raw(*args)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture
def config_path(tmp_path):
    data_dir = tmp_path / '.e2e-readback'
    seed_e2e_data.apply_config_fixture(str(data_dir), 'newznab_aligned')
    return data_dir / 'config.ini'


def test_sha_is_the_sha256_of_the_file_bytes(config_path):
    assert run_helper('sha', config_path) == hashlib.sha256(config_path.read_bytes()).hexdigest()


def test_columns_are_the_raw_stored_strings_of_the_group(config_path):
    columns = run_helper('columns', config_path, 'newznab')

    assert columns['use'] == '1,0,1'
    assert columns['host'].count(',') == 2
    assert set(columns) == {'use', 'host', 'api_key', 'extra_score', 'custom_tag'}


def test_the_view_is_what_the_real_getHosts_returns(config_path):
    view = run_helper('view', config_path, 'newznab')

    assert [row[0] for row in view] == ['1', '0', '1']
    assert view[1][1].startswith('https://placeholder-two.invalid')
    assert view[1][2] == 'placeholder-key-two'


def test_reading_never_writes_the_file(config_path):
    """Loading settings registers defaults and saves, so the helper must load a copy."""
    before = config_path.read_bytes()

    run_helper('view', config_path, 'newznab')
    run_helper('view', config_path, 'torrentpotato')
    run_helper('columns', config_path, 'newznab')

    assert config_path.read_bytes() == before


def test_a_legacy_bytes_literal_is_unwrapped_by_the_view_and_kept_raw_by_columns(tmp_path):
    data_dir = tmp_path / '.e2e-readback-legacy'
    seed_e2e_data.apply_config_fixture(str(data_dir), 'newznab_legacy_bytes')
    path = data_dir / 'config.ini'

    columns = run_helper('columns', path, 'newznab')
    view = run_helper('view', path, 'newznab')

    assert columns['host'].startswith("b'")
    assert [row[1] for row in view] == [
        'https://placeholder-one.invalid/api', 'https://placeholder-two.invalid/api']


def test_the_automation_view_lists_the_urls_the_reader_would_fetch(tmp_path):
    data_dir = tmp_path / '.e2e-readback-auto'
    seed_e2e_data.apply_config_fixture(str(data_dir), 'all_groups_aligned')

    view = run_helper('view', data_dir / 'config.ini', 'letterboxd')

    assert len(view) == 1
    assert 'placeholder-letterboxd-one' in view[0]


def test_an_unknown_section_is_an_error_not_an_empty_answer(config_path):
    completed = run_raw('columns', config_path, 'no_such_section')

    assert completed.returncode != 0
    assert 'not a combine group' in completed.stderr
