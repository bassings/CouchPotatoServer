"""Guard against scripts/seed_e2e_data.py being pointed at a real library.

`ci.yml` invokes the script with `--data_dir=.config`, and `.config` is also
the conventional (gitignored) name for a developer's OWN local CouchPotato
data dir -- copy-pasting that exact invocation locally, against a `.config`
that already holds a real settings/library, is the realistic mistake
`_is_safe_seed_target` exists to catch before it silently writes fixture rows
into it.

Mirrors tests/unit/test_migrate_codernity_script.py's import pattern: scripts/
is not a package, so bootstrap sys.path the same way the script itself does.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "libs"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import seed_e2e_data  # noqa: E402


class TestIsSafeSeedTarget:

    def test_a_directory_that_does_not_exist_yet_is_safe(self, tmp_path):
        """The normal CI case: a fresh checkout, nothing at --data_dir yet."""
        target = tmp_path / "brand-new"
        assert seed_e2e_data._is_safe_seed_target(str(target)) is True

    def test_an_empty_existing_directory_is_safe(self, tmp_path):
        assert seed_e2e_data._is_safe_seed_target(str(tmp_path)) is True

    def test_a_non_empty_directory_with_an_unrelated_name_is_refused(self, tmp_path):
        """The core protection: a populated, arbitrarily-named directory (a
        stand-in for a real media library / NAS mount / production data dir)
        must never be silently seeded into.
        """
        real_library = tmp_path / "my-real-movies"
        real_library.mkdir()
        (real_library / "settings.conf").write_text("this is not a fixture")

        assert seed_e2e_data._is_safe_seed_target(str(real_library)) is False

    def test_a_non_empty_e2e_named_directory_under_the_repo_is_safe(self, monkeypatch):
        """The normal local dev loop: re-running the seed script against an
        already-seeded (non-empty) .e2e-data must keep working -- the script
        is idempotent by design (fixed _ids, see `_upsert`).
        """
        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", str(REPO_ROOT))
        target = REPO_ROOT / ".e2e-guard-test-data"
        target.mkdir(exist_ok=True)
        (target / "database_v2").mkdir(exist_ok=True)
        try:
            assert seed_e2e_data._is_safe_seed_target(str(target)) is True
        finally:
            (target / "database_v2").rmdir()
            target.rmdir()

    def test_a_non_empty_dot_config_under_the_repo_is_accepted_by_name(self, monkeypatch):
        """Documents the guard's accepted residual risk: `.config` under the
        repo is allowed by name/location even when non-empty, because it is
        ALSO the conventional dev data dir name and re-seeding into one a
        developer is deliberately using for E2E work must keep working. This
        guard stops an arbitrary/real library PATH, not a correctly-named
        directory that happens to hold real data -- see
        _is_safe_seed_target's docstring.
        """
        import os

        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", str(REPO_ROOT))
        target = REPO_ROOT / ".config"
        preexisting = os.path.isdir(target)
        if not preexisting:
            target.mkdir()
            (target / "marker").write_text("x")
        try:
            assert seed_e2e_data._is_safe_seed_target(str(target)) is True
        finally:
            if not preexisting:
                (target / "marker").unlink()
                target.rmdir()

    def test_a_non_empty_e2e_named_directory_outside_the_repo_is_refused(self, tmp_path, monkeypatch):
        """The name alone isn't enough -- it must also resolve under this
        repo's root, so an unrelated `.e2e-something` directory elsewhere on
        disk (a coincidence, or a copy-pasted path from a different project)
        isn't treated as ours.
        """
        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", str(REPO_ROOT))
        outside = tmp_path / ".e2e-elsewhere"
        outside.mkdir()
        (outside / "marker").write_text("x")

        assert seed_e2e_data._is_safe_seed_target(str(outside)) is False
