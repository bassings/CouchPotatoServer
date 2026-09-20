"""Prevent retired MooTools plugin assets from returning to the source tree.

FastAPI serves ``couchpotato/static`` only.  The old ClientScript plugin that
collected files from ``couchpotato/core/**/static`` was removed with the legacy
UI, so files in those directories are unreachable in a production install.
"""

from pathlib import Path
import re

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ALWAYS_ACTIVE_GUIDANCE = (
    "AGENTS.md",
    "CLAUDE.md",
    "docs/design-system/README.md",
    "docs/technical-debt.md",
)
LIFECYCLE = re.compile(
    r"^> \*\*Lifecycle: "
    r"(active|proposed|queued|completed|superseded|historical)\*\*$",
    re.IGNORECASE | re.MULTILINE,
)
LEGACY_SPEC_REFERENCE = re.compile(
    r"(?:https?://[^\s)>\]]+/old(?:/|\*|\b)|"
    r"(?<![\w@])/old(?:/|\*|\b)|MooTools|"
    r"(?:legacy|classic|old|former) (?:UI|interface|stack|asset|runtime)|"
    r"(?:updater|putio|trakt)\.js|couchpotato/core/\*\*/static)",
    re.IGNORECASE,
)
LEGACY_RUNTIME_MARKER = "> **Legacy runtime: retired; `/old/*`: redirect-only.**"
# This tracked plan has a user-owned uncommitted edit in the main checkout and
# one queued data-only task. T14 must neither rewrite nor silently reclassify it;
# the current plan records the bounded owner-reconciliation deferment instead.
LIFECYCLE_EXEMPT = {"specs/PLAN-2026-09-07-post-sonarqube-followups.md"}


def _lifecycle(text):
    match = LIFECYCLE.search("\n".join(text.splitlines()[:12]))
    return match.group(1).lower() if match else None


def _lifecycle_documents():
    return sorted(
        path
        for directory in (REPO_ROOT / "specs", REPO_ROOT / "QA")
        for path in directory.glob("*.md")
        if _lifecycle(path.read_text()) is not None
    )


def _active_guidance():
    paths = set(ALWAYS_ACTIVE_GUIDANCE)
    for path in _lifecycle_documents():
        if _lifecycle(path.read_text()) in {"active", "proposed", "queued"}:
            paths.add(path.relative_to(REPO_ROOT).as_posix())
    return sorted(paths)


def _legacy_implementation_specs():
    return sorted(
        path
        for directory in (REPO_ROOT / "specs", REPO_ROOT / "QA")
        for path in directory.glob("*.md")
        if path.relative_to(REPO_ROOT).as_posix() not in LIFECYCLE_EXEMPT
        and LEGACY_SPEC_REFERENCE.search(path.read_text())
    )


def test_no_unserved_core_static_assets_remain():
    legacy_assets = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "couchpotato" / "core").glob("**/static/**/*")
        if path.is_file()
    )

    assert legacy_assets == [], (
        "FastAPI does not serve couchpotato/core/**/static; move a still-live "
        "asset into couchpotato/static and reference it from the current UI, "
        f"or delete the unreachable legacy asset(s): {legacy_assets}"
    )


def test_active_guidance_records_the_legacy_static_tree_as_retired():
    remediation = (REPO_ROOT / "specs" / "REMEDIATION-2026-08.md").read_text()
    cleanup_spec = (
        REPO_ROOT / "specs" / "UI-CLEANUP-01-retire-legacy-assets.md"
    ).read_text()
    qa_plan = (REPO_ROOT / "QA" / "QA_TEST_PLAN.md").read_text()
    downloader = (
        REPO_ROOT / "couchpotato" / "core" / "_base" / "downloader" / "main.py"
    ).read_text()

    assert "**Resolved by Sonar T14.**" in remediation
    assert "**Completion status — read first.**" in cleanup_spec
    assert "The legacy runtime is retired; `/old/*` is only a redirect." in cleanup_spec
    assert "Redirect-only; contains no classic page" in qa_plan
    assert "here to load the static files" not in downloader
    sonar_plan = "specs/PLAN-2026-09-15-sonarqube-improvements.md"
    assert sonar_plan not in _active_guidance()
    assert _lifecycle((REPO_ROOT / sonar_plan).read_text()) == "completed"

    active_without_marker = [
        relative
        for relative in _active_guidance()
        if LEGACY_SPEC_REFERENCE.search((REPO_ROOT / relative).read_text())
        and LEGACY_RUNTIME_MARKER not in (REPO_ROOT / relative).read_text()
    ]
    assert active_without_marker == [], (
        "active legacy-UI guidance must carry the canonical retirement marker: "
        f"{active_without_marker}"
    )


def test_lifecycle_deferment_is_explicit_and_bounded():
    assert LIFECYCLE_EXEMPT == {
        "specs/PLAN-2026-09-07-post-sonarqube-followups.md"
    }
    current_plan = (
        REPO_ROOT / "specs" / "PLAN-2026-09-15-sonarqube-improvements.md"
    ).read_text()
    assert "`PLAN-2026-09-07-post-sonarqube-followups.md`" in current_plan
    assert "owner-reconciliation task" in current_plan


def test_legacy_ui_records_declare_their_lifecycle():
    missing_status = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _legacy_implementation_specs()
        if _lifecycle(path.read_text()) is None
    ]

    assert missing_status == [], (
        "legacy-UI specs must declare whether they are active or completed near "
        f"the title, so historical work cannot read as a current order: {missing_status}"
    )


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("> **Lifecycle: active**", "active"),
        ("> **Lifecycle: proposed**", "proposed"),
        ("> **Lifecycle: queued**", "queued"),
        ("> **Lifecycle: completed**", "completed"),
        ("> **Status: active.**", None),
    ],
)
def test_lifecycle_parser_uses_one_canonical_machine_readable_form(marker, expected):
    assert _lifecycle(f"# Example\n\n{marker}\n") == expected


@pytest.mark.parametrize(
    "reference",
    [
        "Open /old/ to verify the redirect.",
        "Use http://localhost:5050/old/ for redirect verification.",
        "Production URL: https://example.test/old/",
        "The old UI had this feature.",
        "The former interface exposed a shortcut.",
    ],
)
def test_legacy_reference_discovery_covers_routes_urls_and_vocabulary(reference):
    assert LEGACY_SPEC_REFERENCE.search(reference)


def test_legacy_reference_discovery_ignores_npm_old_alias():
    assert not LEGACY_SPEC_REFERENCE.search("@typescript/old: npm:typescript@^6")
