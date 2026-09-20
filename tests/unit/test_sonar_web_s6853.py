"""Multiplicity-preserving inventory for the four Sonar Web:S6853 sites."""

from collections import Counter
from pathlib import Path
import re

from bs4 import BeautifulSoup, NavigableString
import pytest


TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "couchpotato" / "ui" / "templates"
_JINJA_COMMENT = re.compile(r"{#.*?#}", re.S)
_CAPTION_EXPRESSION = "opt.label || opt.name.replace(/_/g, ' ')"

# Identity is path, semantic shape, and the dynamic expression that makes the
# site interesting to S6853. A repeated occurrence remains repeated when the
# discovered list is compared with Counter below.
AUDITED_S6853_SOURCES = {
    (
        "wizard.html",
        "dynamic-label",
        "field.label",
        "'wizard-tracker-' + tracker.id + '-' + field.name",
    ): "6e758dd9-a124-4bb7-936d-0985c6d48192",
    (
        "partials/settings/combined_basics_card.html",
        "neutral-caption",
        _CAPTION_EXPRESSION,
        "",
    ): "d640ffb9-d60e-4628-b8dc-b4b0c572be45",
    (
        "partials/settings/header.html",
        "implicit-button-label",
        "Advanced",
        "switch",
    ): "05311c2f-ce5f-4fad-a0e5-1c2e1a68e85c",
    (
        "partials/settings/provider_card.html",
        "neutral-caption",
        _CAPTION_EXPRESSION,
        "opt.type !== 'combined' && opt.type !== 'bool'",
    ): "1d6c71b3-2142-4cfa-a2e5-76b6d8c0f0bd",
}


def _discover_s6853_sources(template_root=TEMPLATE_ROOT):
    discovered = []
    for path in sorted(template_root.rglob("*.html")):
        relative_path = str(path.relative_to(template_root))
        soup = BeautifulSoup(_JINJA_COMMENT.sub("", path.read_text()), "html.parser")
        for element in soup.find_all(["label", "span"]):
            if element.name == "label" and element.get("x-text"):
                discovered.append((
                    relative_path,
                    "dynamic-label",
                    element.get("x-text"),
                    element.get(":for") or "",
                ))
                continue

            button = element.find("button") if element.name == "label" else None
            if button is not None:
                text = " ".join(
                    str(child).strip()
                    for child in element.descendants
                    if isinstance(child, NavigableString) and str(child).strip()
                )
                discovered.append((
                    relative_path,
                    "implicit-button-label",
                    text,
                    button.get("role") or "button",
                ))
                continue

            if (element.name == "span" and element.get("aria-hidden") == "true"
                    and element.get("x-text") == _CAPTION_EXPRESSION):
                discovered.append((
                    relative_path,
                    "neutral-caption",
                    element.get("x-text"),
                    element.get("x-show") or "",
                ))
    return discovered


def _assert_inventory_matches(discovered, audited=AUDITED_S6853_SOURCES):
    assert Counter(discovered) == Counter(audited.keys())
    assert len(set(audited.values())) == len(audited)


def test_each_s6853_finding_has_one_exact_expected_source_state():
    _assert_inventory_matches(_discover_s6853_sources())


def test_duplicate_source_occurrences_are_not_collapsed(tmp_path):
    template = tmp_path / "duplicate.html"
    template.write_text(
        '<label :for="item.id" x-text="item.label"></label>'
        '<label :for="item.id" x-text="item.label"></label>'
    )
    identity = ("duplicate.html", "dynamic-label", "item.label", "item.id")

    with pytest.raises(AssertionError):
        _assert_inventory_matches(
            _discover_s6853_sources(tmp_path),
            {identity: "synthetic-issue-key"},
        )
