"""Tests for couchpotato/runner.py's CodernityDB->SQLite auto-migration
wiring (REFACTOR-01).

The migration logic itself was moved out of the live application tree into
the standalone scripts/migrate_codernity_to_sqlite.py (see
tests/unit/test_migrate_codernity_script.py for that module's own tests).
runner.py now only detects whether a legacy CodernityDB database needs
migrating and, if so, runs that script ONCE as a subprocess before opening
the resulting SQLite database -- it must not import the migration code or
CodernityDB itself. On subprocess failure, runner.py must abort startup
rather than silently falling through to fresh-database creation, which
would look like a successful (but empty) start and discard the user's
existing library.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.helpers.encoding import sp
from couchpotato.runner import _open_or_create_database, _resolve_migration_script

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_resolve_migration_script_finds_real_script():
    script_path = _resolve_migration_script(str(REPO_ROOT))
    assert os.path.isfile(script_path)
    assert script_path.endswith(os.path.join('scripts', 'migrate_codernity_to_sqlite.py'))


def test_resolve_migration_script_raises_clear_error_when_missing(tmp_path):
    with pytest.raises(RuntimeError, match='migration script is missing'):
        _resolve_migration_script(str(tmp_path))


def test_opens_existing_sqlite_database_without_touching_codernity(tmp_path):
    (tmp_path / 'database_v2').mkdir()
    (tmp_path / 'database_v2' / 'couchpotato.db').write_bytes(b'')
    # A stray legacy dir alongside an already-open SQLite DB must be ignored.
    (tmp_path / 'database').mkdir()

    db = MagicMock()
    with patch('couchpotato.runner.subprocess.run') as mock_run:
        db_exists = _open_or_create_database(db, str(tmp_path), str(REPO_ROOT))

    assert db_exists is True
    db.open.assert_called_once_with(sp(os.path.join(str(tmp_path), 'database_v2')))
    db.create.assert_not_called()
    mock_run.assert_not_called()


def test_creates_fresh_database_when_nothing_exists(tmp_path):
    db = MagicMock()
    with patch('couchpotato.runner.subprocess.run') as mock_run:
        db_exists = _open_or_create_database(db, str(tmp_path), str(REPO_ROOT))

    assert db_exists is False
    db.create.assert_called_once_with(sp(os.path.join(str(tmp_path), 'database_v2')))
    db.open.assert_not_called()
    mock_run.assert_not_called()


def test_migrates_legacy_codernity_db_via_subprocess_on_success(tmp_path):
    (tmp_path / 'database').mkdir()
    db = MagicMock()

    mock_result = MagicMock(returncode=0)
    with patch('couchpotato.runner.subprocess.run', return_value=mock_result) as mock_run:
        db_exists = _open_or_create_database(db, str(tmp_path), str(REPO_ROOT))

    assert db_exists is True

    expected_script = sp(os.path.join(str(REPO_ROOT), 'scripts', 'migrate_codernity_to_sqlite.py'))
    mock_run.assert_called_once_with(
        [sys.executable, expected_script, '--data-dir', str(tmp_path)],
        check=False,
    )
    # The script does the database.bak rename itself; runner.py must only
    # open the resulting SQLite database, not re-migrate or re-rename.
    db.open.assert_called_once_with(sp(os.path.join(str(tmp_path), 'database_v2')))
    db.create.assert_not_called()


def test_migration_subprocess_failure_aborts_and_does_not_create_fresh_db(tmp_path):
    (tmp_path / 'database').mkdir()
    db = MagicMock()

    mock_result = MagicMock(returncode=1)
    with patch('couchpotato.runner.subprocess.run', return_value=mock_result):
        with pytest.raises(RuntimeError, match='CodernityDB migration failed'):
            _open_or_create_database(db, str(tmp_path), str(REPO_ROOT))

    # Must NOT silently fall through to creating (or opening) a database --
    # that would discard the user's unmigrated library without a trace.
    db.create.assert_not_called()
    db.open.assert_not_called()
    # The legacy CodernityDB directory itself must be left untouched (no
    # rename happens in runner.py; only the script renames on its own
    # success, which didn't happen here).
    assert (tmp_path / 'database').is_dir()
    assert not (tmp_path / 'database.bak').exists()


def test_skips_migration_when_backup_already_exists(tmp_path):
    """A database.bak alongside database/ means migration already ran (or
    was completed manually) -- matches pre-refactor behavior of falling
    through to fresh-SQLite-database creation rather than re-migrating."""
    (tmp_path / 'database').mkdir()
    (tmp_path / 'database.bak').mkdir()
    db = MagicMock()

    with patch('couchpotato.runner.subprocess.run') as mock_run:
        db_exists = _open_or_create_database(db, str(tmp_path), str(REPO_ROOT))

    assert db_exists is False
    mock_run.assert_not_called()
    db.create.assert_called_once_with(sp(os.path.join(str(tmp_path), 'database_v2')))


def test_missing_migration_script_raises_before_invoking_subprocess(tmp_path):
    """If the install is missing scripts/migrate_codernity_to_sqlite.py
    entirely, fail loudly and early rather than trying (and failing) to
    subprocess into a nonexistent file."""
    (tmp_path / 'database').mkdir()
    fake_base_path = tmp_path / 'fake_install'
    fake_base_path.mkdir()
    db = MagicMock()

    with patch('couchpotato.runner.subprocess.run') as mock_run:
        with pytest.raises(RuntimeError, match='migration script is missing'):
            _open_or_create_database(db, str(tmp_path), str(fake_base_path))

    mock_run.assert_not_called()
    db.create.assert_not_called()
    db.open.assert_not_called()


def test_runner_source_does_not_reference_codernity_migration_chain():
    """The live server process must not import the CodernityDB->SQLite
    migration chain (codernity_to_sqlite / fix_indexes / rebuild_buckets) or
    CodernityDB itself -- that logic now lives entirely outside
    couchpotato/core/ and is only ever invoked out-of-process via the
    standalone script. Checked statically against the source (rather than
    sys.modules) so it isn't order-dependent on whatever other test modules
    already imported in this same pytest process.

    clean_orphans and fix_release_quality are deliberately NOT part of this
    assertion: unlike the CodernityDB migration chain, they run on every
    startup (not just during a legacy-database migration) and correctly
    remain in couchpotato/core/migration/ -- see runner.py's app.migrate
    section."""
    runner_path = REPO_ROOT / 'couchpotato' / 'runner.py'
    source = runner_path.read_text()

    assert 'core.migration.codernity_to_sqlite' not in source
    assert 'core.migration.fix_indexes' not in source
    assert 'core.migration.rebuild_buckets' not in source
    assert 'from CodernityDB' not in source
    assert 'import CodernityDB' not in source
