"""Exact source inventory for the remaining medium Web reliability findings."""

from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup
import pytest


TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "couchpotato" / "ui" / "templates"
FORBIDDEN_MENU_ROLES = {"menu", "menubar", "menuitem"}

AUDITED_MEDIUM_SOURCES = {
    (
        "base.html",
        "native-mobile-navigation",
        ((
            "nav",
            "Mobile menu",
            1,
            0,
            (("post", "{{ web_base }}logout/", (("button", "submit", "Sign out everywhere"),)),),
        ),),
        (("nav", "Mobile navigation", 1, 0),),
    ): "31ce04e7-1f09-44c0-9f93-ce465b1c34b7",
    (
        "partials/movie_releases.html",
        "focusable-overflow-region",
        "Releases table, scrolls horizontally",
        "0",
    ): "d4e2bb26-a9ba-4fb5-94c4-5b5cc2205107",
}


def _discover_medium_sources(template_root=TEMPLATE_ROOT):
    discovered = []
    base = BeautifulSoup((template_root / "base.html").read_text(), "html.parser")

    def forbidden_count(element):
        return sum(
            child.get("role") in FORBIDDEN_MENU_ROLES
            or (child.name == "form" and child.get("role") == "none")
            for child in (element, *element.find_all(True))
        )

    drawers = tuple(
        (
            drawer.name,
            drawer.get("aria-label") or "",
            len(drawer.find_all("a", href=True)),
            forbidden_count(drawer),
            tuple(
                (
                    (form.get("method") or "").lower(),
                    form.get("action") or "",
                    tuple(
                        (
                            button.name,
                            (button.get("type") or "submit").lower(),
                            button.get("aria-label") or "",
                        )
                        for button in form.find_all("button")
                    ),
                )
                for form in drawer.find_all("form")
            ),
        )
        for drawer in base.find_all(id="mobile-menu")
    )
    bottom_navigation = tuple(
        (
            bottom.name,
            bottom.get("aria-label") or "",
            len(bottom.find_all("a", href=True)),
            forbidden_count(bottom),
        )
        for bottom in base.find_all("nav", attrs={"aria-label": "Mobile navigation"})
    )
    discovered.append((
        "base.html",
        "native-mobile-navigation",
        drawers,
        bottom_navigation,
    ))

    for path in sorted(template_root.rglob("*.html")):
        relative_path = str(path.relative_to(template_root))
        soup = BeautifulSoup(path.read_text(), "html.parser")
        for region in soup.find_all("section", attrs={"tabindex": True}):
            if "overflow-x-auto" in (region.get("class") or []):
                discovered.append((
                    relative_path,
                    "focusable-overflow-region",
                    region.get("aria-label") or "",
                    region.get("tabindex") or "",
                ))
    return discovered


def _assert_inventory_matches(discovered, audited=AUDITED_MEDIUM_SOURCES):
    assert Counter(discovered) == Counter(audited.keys())
    assert len(set(audited.values())) == len(audited)


def test_each_medium_web_finding_has_one_exact_reviewed_source_state():
    _assert_inventory_matches(_discover_medium_sources())


def _fixture_root(tmp_path):
    partials = tmp_path / "partials"
    partials.mkdir()
    for relative_path in ("base.html", "partials/movie_releases.html"):
        source = TEMPLATE_ROOT / relative_path
        target = tmp_path / relative_path
        target.write_text(source.read_text())
    return tmp_path


def test_duplicate_source_occurrences_are_not_collapsed(tmp_path):
    template_root = _fixture_root(tmp_path)
    base_path = template_root / "base.html"
    source = base_path.read_text()
    base_path.write_text(source + source)

    with pytest.raises(AssertionError):
        _assert_inventory_matches(_discover_medium_sources(template_root))


def test_navigation_without_native_destination_links_is_rejected(tmp_path):
    template_root = _fixture_root(tmp_path)
    base_path = template_root / "base.html"
    before, marker, bottom = base_path.read_text().partition("<!-- MOBILE BOTTOM NAV -->")
    assert marker
    bottom = bottom.replace("<a ", "<span ", 1).replace("</a>", "</span>", 1)
    base_path.write_text(before + marker + bottom)

    with pytest.raises(AssertionError):
        _assert_inventory_matches(_discover_medium_sources(template_root))


def test_navigation_with_non_post_logout_is_rejected(tmp_path):
    template_root = _fixture_root(tmp_path)
    base_path = template_root / "base.html"
    before, marker, mobile = base_path.read_text().partition("<!-- MOBILE MENU OVERLAY -->")
    assert marker
    assert mobile.count('method="post" action="{{ web_base }}logout/"') == 1
    mobile = mobile.replace(
        'method="post" action="{{ web_base }}logout/"',
        'method="get" action="{{ web_base }}logout/"',
    )
    base_path.write_text(before + marker + mobile)

    with pytest.raises(AssertionError):
        _assert_inventory_matches(_discover_medium_sources(template_root))
