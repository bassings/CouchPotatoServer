"""Guards for repository metadata surfaced by GitHub."""

import hashlib
from collections import Counter
from pathlib import Path
import subprocess

from tests.unit.conftest import sanitized_git_env


REPO = Path(__file__).resolve().parents[2]
GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"


def _dice(left, right):
    if not left and not right:
        return 1.0
    overlap = sum((left & right).values())
    return 2 * overlap / (sum(left.values()) + sum(right.values()))


def _is_probable_license_copy(candidate, canonical):
    """Recognize lightly edited copies with Licensee-style linear scoring."""
    candidate_words = candidate.casefold().split()
    canonical_words = canonical.casefold().split()
    candidate_bigrams = Counter(zip(candidate_words, candidate_words[1:]))
    canonical_bigrams = Counter(zip(canonical_words, canonical_words[1:]))
    return (
        _dice(Counter(candidate_words), Counter(canonical_words)) >= 0.95
        and _dice(candidate_bigrams, canonical_bigrams) >= 0.475
    )


def _tracked_root_files(repo=REPO):
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=sanitized_git_env(),
    )
    names = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    return [repo / name for name in names if name and "/" not in name]


def test_license_is_canonical_and_linked_once():
    """GitHub should expose one canonical GPL license, not two root copies."""
    license_path = REPO / "LICENSE"
    license_bytes = license_path.read_bytes()
    assert hashlib.sha256(license_bytes).hexdigest() == GPL3_SHA256
    license_text = license_bytes.decode("utf-8")

    gpl_documents = []
    for path in _tracked_root_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _is_probable_license_copy(text, license_text):
            gpl_documents.append(path.name)
    assert sorted(gpl_documents) == ["LICENSE"]

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "[GPL-3.0-or-later](LICENSE)" in readme
    assert "license.txt" not in readme.casefold()
    assert "Copyright (C) 2011 Ruud Burger" in readme


def test_duplicate_guard_recognizes_a_lightly_edited_copy():
    canonical = (REPO / "LICENSE").read_text(encoding="utf-8")
    edited = canonical.replace(
        "Everyone is permitted to copy and distribute verbatim copies",
        "Everyone may copy and distribute verbatim copies",
    )
    assert edited != canonical
    assert _is_probable_license_copy(edited, canonical)


def test_duplicate_guard_covers_insertions_deletions_and_reordering():
    canonical = (REPO / "LICENSE").read_text(encoding="utf-8")
    words = canonical.split()
    unique_preamble = " ".join("project-notice-%d" % i for i in range(200))

    assert _is_probable_license_copy(unique_preamble + "\n" + canonical, canonical)
    assert _is_probable_license_copy(" ".join(words[:-200]), canonical)
    assert not _is_probable_license_copy(" ".join(reversed(words)), canonical)


def test_license_scan_uses_only_git_tracked_root_files(tmp_path):
    tracked_root = tmp_path / "LICENSE"
    tracked_root.write_text("tracked root", encoding="utf-8")
    tracked_nested = tmp_path / "docs" / "LICENSE"
    tracked_nested.parent.mkdir()
    tracked_nested.write_text("tracked nested", encoding="utf-8")
    untracked_root = tmp_path / "COPYING"
    untracked_root.write_text("untracked root", encoding="utf-8")

    subprocess.run(
        ["git", "init", "-q"],
        cwd=tmp_path,
        check=True,
        env=sanitized_git_env(),
    )
    subprocess.run(
        ["git", "add", "LICENSE", "docs/LICENSE"],
        cwd=tmp_path,
        check=True,
        env=sanitized_git_env(),
    )

    assert _tracked_root_files(tmp_path) == [tracked_root]
