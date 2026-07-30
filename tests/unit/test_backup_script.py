"""Tests for scripts/backup.sh — the prod DB + settings snapshot script.

The script is the only thing standing between a bad prod promotion and an
unrecoverable database (see "Deploying to prod" in docs/development-process.md),
so these tests exercise it end-to-end against a real SQLite file rather than
mocking it out. Two properties matter most and are asserted explicitly:

  * the snapshot must be a *complete, valid* SQLite database — a plain `cp` of a
    live DB can capture a torn page, which is exactly the failure a backup is
    supposed to insure against, and which only shows up when you try to restore;
  * `config.bak/` must survive untouched. It sits next to the data dir in prod
    and must never be deleted (CLAUDE.md); a retention sweep that walks one
    directory too far up is the plausible way that happens.
"""

import os
import re
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup.sh"

TIMESTAMP_DIR = re.compile(r"^\d{8}-\d{6}$")


def _make_db(path: Path, rows: int = 3) -> None:
    """Create a real SQLite DB with content, so a torn copy is detectable.

    WAL mode is deliberate. In WAL, committed rows can still live in the
    sidecar `-wal` file rather than the main `.db`, so copying `couchpotato.db`
    alone (`cp`) silently loses recent commits while `.backup` checkpoints them
    in. That is the difference between a backup that restores and one that looks
    fine until you need it, and it is what makes the copy-method assertions
    below load-bearing rather than decorative.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE media (id INTEGER PRIMARY KEY, identifier TEXT)")
        conn.executemany(
            "INSERT INTO media (identifier) VALUES (?)",
            [(f"imdb-tt{i:07d}",) for i in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def prod_layout(tmp_path):
    """Mirror the prod layout: <root>/config/data/{config.ini,database_v2/} + config.bak/."""
    root = tmp_path / "CouchPotato"
    data_dir = root / "config" / "data"
    _make_db(data_dir / "database_v2" / "couchpotato.db")
    (data_dir / "config.ini").write_text("[core]\nport = 5050\n")

    # The directory that must never be touched.
    config_bak = root / "config.bak"
    config_bak.mkdir(parents=True)
    (config_bak / "sentinel.ini").write_text("do not delete me")

    return {
        "root": root,
        "data_dir": data_dir,
        "backup_dir": root / "backups",
        "config_bak": config_bak,
    }


def _run(prod_layout, *args, extra_env=None, expect_ok=True):
    env = dict(os.environ)
    env.update(
        {
            "CP_DATA_DIR": str(prod_layout["data_dir"]),
            "BACKUP_DIR": str(prod_layout["backup_dir"]),
        }
    )
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        ["bash", str(BACKUP_SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
    )
    if expect_ok:
        assert result.returncode == 0, (
            f"backup.sh failed ({result.returncode}):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _snapshots(backup_dir: Path):
    if not backup_dir.exists():
        return []
    return sorted(p for p in backup_dir.iterdir() if p.is_dir() and TIMESTAMP_DIR.match(p.name))


def test_script_is_executable_and_has_a_shebang():
    assert BACKUP_SCRIPT.exists(), f"{BACKUP_SCRIPT} does not exist"
    assert BACKUP_SCRIPT.read_text().startswith("#!"), "missing shebang"
    mode = BACKUP_SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "backup.sh must be executable (cron runs it directly)"


def test_creates_one_timestamped_snapshot_with_db_and_settings(prod_layout):
    _run(prod_layout)

    snapshots = _snapshots(prod_layout["backup_dir"])
    assert len(snapshots) == 1, f"expected exactly one snapshot, got {snapshots}"

    snapshot = snapshots[0]
    assert (snapshot / "couchpotato.db").is_file(), "DB missing from snapshot"
    assert (snapshot / "config.ini").is_file(), "settings missing from snapshot"
    assert (snapshot / "config.ini").read_text() == "[core]\nport = 5050\n"


def test_snapshot_db_is_a_complete_valid_sqlite_database(prod_layout):
    """The point of the backup: the copy must actually restore."""
    _run(prod_layout)
    copied = _snapshots(prod_layout["backup_dir"])[0] / "couchpotato.db"

    conn = sqlite3.connect(copied)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        identifiers = [r[0] for r in conn.execute("SELECT identifier FROM media ORDER BY id")]
    finally:
        conn.close()

    assert identifiers == ["imdb-tt0000000", "imdb-tt0000001", "imdb-tt0000002"]


def test_backs_up_a_database_that_is_open_and_being_written(prod_layout):
    """Prod is live when this runs, and this is the test that pins the *method*.

    The connection stays open across the backup, so SQLite does not checkpoint:
    the row committed below is in the `-wal` sidecar, not yet in
    `couchpotato.db`. A `cp` of the main file alone therefore produces a
    plausible-looking database that is missing the most recent commits, while
    `.backup` (or Python's backup API) captures them. Asserting the exact row
    count is what makes the difference visible — swapping `.backup` for `cp`
    fails here and nowhere else.
    """
    db = prod_layout["data_dir"] / "database_v2" / "couchpotato.db"
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal", (
            "fixture must be in WAL mode or this test cannot distinguish "
            "cp from .backup"
        )
        conn.execute("INSERT INTO media (identifier) VALUES ('imdb-tt9999999')")
        conn.commit()
        # Leave the connection open across the backup — no checkpoint happens.
        _run(prod_layout)
    finally:
        conn.close()

    copied = _snapshots(prod_layout["backup_dir"])[0] / "couchpotato.db"
    restored = sqlite3.connect(copied)
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        count = restored.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    finally:
        restored.close()

    assert count == 4, "committed row missing from the snapshot"


def test_falls_back_to_python_when_the_sqlite3_cli_is_unusable(prod_layout, tmp_path):
    """The prod host may have no sqlite3 binary; the snapshot must still be valid.

    Shims a failing `sqlite3` ahead of the real one on PATH, which covers both
    'absent' and 'present but broken' — in either case the script must not
    silently produce a `cp`-grade copy or claim success without a file.
    """
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    shim = shim_dir / "sqlite3"
    shim.write_text("#!/bin/sh\necho 'sqlite3: simulated failure' >&2\nexit 1\n")
    shim.chmod(0o755)

    result = _run(prod_layout, extra_env={"PATH": f"{shim_dir}:{os.environ['PATH']}"})

    copied = _snapshots(prod_layout["backup_dir"])[0] / "couchpotato.db"
    conn = sqlite3.connect(copied)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 3
    finally:
        conn.close()

    assert "python" in (result.stdout + result.stderr).lower(), (
        "expected the script to say it fell back to Python, so a silently "
        "degraded backup path is visible in the cron log"
    )


def test_never_touches_config_bak(prod_layout):
    """config.bak/ lives beside the data dir in prod and must never be deleted."""
    _run(prod_layout, "--retain", "1")

    sentinel = prod_layout["config_bak"] / "sentinel.ini"
    assert prod_layout["config_bak"].is_dir(), "config.bak/ was removed"
    assert sentinel.is_file(), "config.bak/ contents were removed"
    assert sentinel.read_text() == "do not delete me"


def test_retain_prunes_oldest_snapshots_only(prod_layout):
    backup_dir = prod_layout["backup_dir"]
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in ("20200101-000000", "20200102-000000", "20200103-000000"):
        (backup_dir / name).mkdir()
        (backup_dir / name / "couchpotato.db").write_text("old")

    _run(prod_layout, "--retain", "2")

    remaining = {p.name for p in _snapshots(backup_dir)}
    assert len(remaining) == 2, f"expected 2 snapshots retained, got {sorted(remaining)}"
    assert "20200101-000000" not in remaining, "oldest snapshot should have been pruned"
    assert "20200103-000000" in remaining, "newest pre-existing snapshot was pruned"


def test_retain_ignores_unrelated_files_and_directories(prod_layout):
    """A retention sweep must only ever delete its own timestamped output.

    The decoy directory is named to sort *before* the timestamped snapshots.
    With a name like `keep-me` it sorts last and survives a broken
    match-everything sweep by accident — the test then passes while guarding
    nothing (confirmed: that version survived the mutation).
    """
    backup_dir = prod_layout["backup_dir"]
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "20200101-000000").mkdir()
    (backup_dir / "0-keep-me").mkdir()
    (backup_dir / "0-keep-me" / "important.txt").write_text("not a snapshot")
    (backup_dir / "0-notes.txt").write_text("also not a snapshot")

    _run(prod_layout, "--retain", "1")

    assert (backup_dir / "0-keep-me" / "important.txt").is_file(), "unrelated dir deleted"
    assert (backup_dir / "0-notes.txt").is_file(), "unrelated file deleted"
    assert not (backup_dir / "20200101-000000").exists(), "old snapshot not pruned"
    # Retention must never delete the snapshot this very run just took.
    assert len(_snapshots(backup_dir)) == 1, "the fresh snapshot was pruned"


def test_retain_zero_or_negative_is_rejected_rather_than_deleting_everything(prod_layout):
    """`--retain 0` must not be read as 'keep nothing' — that deletes the backup
    it just took. Fail loudly instead."""
    result = _run(prod_layout, "--retain", "0", expect_ok=False)
    assert result.returncode != 0
    assert "retain" in result.stderr.lower()


def test_fails_loudly_when_the_database_is_missing(prod_layout):
    """A silent success with no DB is worse than no backup — it looks fine in cron.

    Asserting on the *diagnosis*, not just the exit code: without the up-front
    existence check the script still fails, but it fails several steps later with
    "neither sqlite3 nor Python was usable", which blames the tooling for what is
    actually a wrong `CP_DATA_DIR`. That misdiagnosis is the defect worth
    guarding — a bare `returncode != 0` assertion here survives removing the
    check entirely (confirmed by mutation).
    """
    shutil.rmtree(prod_layout["data_dir"] / "database_v2")

    result = _run(prod_layout, expect_ok=False)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "database not found" in output, f"expected a missing-database diagnosis, got:\n{output}"
    assert "couchpotato.db" in output, "the message should name the file it looked for"
    assert "CP_DATA_DIR" in output, "the message should point at the likely cause"
    assert _snapshots(prod_layout["backup_dir"]) == [], "left an empty snapshot behind"


def test_succeeds_without_settings_but_warns(prod_layout):
    """A missing config.ini is odd but must not cost you the DB backup."""
    (prod_layout["data_dir"] / "config.ini").unlink()

    result = _run(prod_layout)

    snapshot = _snapshots(prod_layout["backup_dir"])[0]
    assert (snapshot / "couchpotato.db").is_file()
    assert not (snapshot / "config.ini").exists()
    assert "config.ini" in (result.stdout + result.stderr)
