"""Recurrence guard for the final Sonar JavaScript reliability finding."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_SCRIPT = REPO_ROOT / "couchpotato/ui/templates/partials/settings/scripts.html"


def test_setting_name_normalization_uses_the_explicit_all_occurrences_api() -> None:
    source = SETTINGS_SCRIPT.read_text(encoding="utf-8")

    assert "name.replaceAll('_', ' ')" in source
    assert "name.replace(/_/g, ' ')" not in source
