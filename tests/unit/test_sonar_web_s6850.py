"""Inventory Alpine headings adjudicated under Sonar Web:S6850."""

from collections import Counter
from pathlib import Path

import pytest
from bs4 import BeautifulSoup


TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "couchpotato" / "ui" / "templates"

# Each entry records the source identity of one exact Sonar finding. A newly
# discovered heading must be rendered and reviewed before it can be added here.
AUDITED_DYNAMIC_HEADINGS = {
    (
        "partials/movie_info_modal.html",
        "h2",
        "movie?.title || 'Unknown'",
    ): "9d9ab681-6bd2-47fe-a9ef-37b13bcd7f04",
    (
        "partials/settings/categories.html",
        "h3",
        "formState.id ? 'Edit Category' : 'New Category'",
    ): "f0bd11d6-213c-451f-a4e9-78a87ba77ac8",
    (
        "partials/settings/combined_basics_card.html",
        "h3",
        "group.label",
    ): "2f2065a1-e3b8-430a-853c-84cad1a000ee",
    (
        "partials/settings/combined_basics_card.html",
        "h4",
        "subGroup._subLabel",
    ): "b03efab7-9794-4874-8f00-7078d63fd3b6",
    (
        "partials/settings/profiles.html",
        "h3",
        "formState.id ? 'Edit Profile' : 'New Profile'",
    ): "c7207712-0587-439b-b88e-c34e28375115",
    (
        "partials/settings/provider_card.html",
        "h3",
        "group.label || group.name",
    ): "af8d5d6f-2821-45d1-999e-baaf8ca42dd8",
    (
        "settings.html",
        "h2",
        "getCategoryLabel(groupIdx)",
    ): "a6bf8d7c-1885-4b67-9379-de8382d88989",
}


def _dynamic_headings_without_literal_content(template_root=TEMPLATE_ROOT):
    discovered = []
    for path in sorted(template_root.rglob("*.html")):
        soup = BeautifulSoup(path.read_text(), "html.parser")
        for heading in soup.find_all([f"h{level}" for level in range(1, 7)]):
            expression = heading.get("x-text")
            if expression is not None and not heading.get_text(strip=True):
                discovered.append((str(path.relative_to(template_root)), heading.name, expression))
    return discovered


def _assert_inventory_matches(discovered, audited=AUDITED_DYNAMIC_HEADINGS):
    expected = list(audited)

    assert Counter(discovered) == Counter(expected), (
        "dynamic-only headings changed without rendered accessibility review; "
        f"unreviewed={sorted((Counter(discovered) - Counter(expected)).elements())}, "
        f"stale={sorted((Counter(expected) - Counter(discovered)).elements())}"
    )
    assert len(set(audited.values())) == len(audited)


def test_every_dynamic_only_heading_has_an_exact_audited_sonar_finding():
    _assert_inventory_matches(_dynamic_headings_without_literal_content())


def test_duplicate_dynamic_heading_occurrences_are_not_collapsed(tmp_path):
    template = tmp_path / "duplicate.html"
    template.write_text('<h3 x-text="group.label"></h3><h3 x-text="group.label"></h3>')

    discovered = _dynamic_headings_without_literal_content(tmp_path)

    assert len(discovered) == 2
    audited = {("duplicate.html", "h3", "group.label"): "synthetic-issue-key"}
    with pytest.raises(AssertionError, match="unreviewed=.*duplicate.html"):
        _assert_inventory_matches(discovered, audited)
