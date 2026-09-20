"""Exact source inventory for Sonar Web:S6847 image-error false positives."""

from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup
import pytest


TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "couchpotato" / "ui" / "templates"
HANDLER = "this.style.display='none';this.nextElementSibling.style.display='flex'"

AUDITED_S6847_SOURCES = {
    (
        "partials/charts.html",
        HANDLER,
        "button",
        "",
        "div",
        "display:none",
    ): "2c2425aa-1986-4871-a339-dc8faa87412f",
    (
        "partials/search_results.html",
        HANDLER,
        "button",
        "",
        "div",
        "display:none",
    ): "da38d30f-594d-40af-99d4-a9f343dca2ca",
    (
        "partials/suggestions.html",
        HANDLER,
        "button",
        "",
        "div",
        "display:none",
    ): "a48992f0-9b52-4630-b021-7ae7bf56fae8",
    (
        "partials/movie_cards.html",
        HANDLER,
        "a",
        "{{ title }}",
        "div",
        "display:none",
    ): "fe776ece-7d5f-4f9b-a70f-16871444e5bb",
}


def _discover(template_root=TEMPLATE_ROOT):
    discovered = []
    for path in sorted(template_root.rglob("*.html")):
        soup = BeautifulSoup(path.read_text(), "html.parser")
        for image in soup.find_all("img", onerror=True):
            control = image.find_parent(["button", "a"])
            fallback = image.find_next_sibling()
            discovered.append((
                str(path.relative_to(template_root)),
                image.get("onerror") or "",
                control.name if control else "",
                image.get("alt") or "",
                fallback.name if fallback else "",
                (fallback.get("style") or "") if fallback else "",
            ))
    return discovered


def _assert_exact_inventory(discovered):
    assert Counter(discovered) == Counter(AUDITED_S6847_SOURCES.keys())
    assert len(set(AUDITED_S6847_SOURCES.values())) == len(AUDITED_S6847_SOURCES)


def _fixture_root(tmp_path):
    for identity in AUDITED_S6847_SOURCES:
        relative_path = identity[0]
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((TEMPLATE_ROOT / relative_path).read_text())
    return tmp_path


def test_every_image_error_handler_is_one_exact_reviewed_s6847_source():
    _assert_exact_inventory(_discover())


@pytest.mark.parametrize("relative_path", [identity[0] for identity in AUDITED_S6847_SOURCES])
def test_each_handler_owns_hiding_the_failed_image(tmp_path, relative_path):
    template_root = _fixture_root(tmp_path)
    path = template_root / relative_path
    source = path.read_text()
    assert source.count(HANDLER) == 1
    path.write_text(source.replace(HANDLER, "this.nextElementSibling.style.display='flex'"))

    with pytest.raises(AssertionError):
        _assert_exact_inventory(_discover(template_root))


def test_a_duplicate_occurrence_is_not_collapsed(tmp_path):
    template_root = _fixture_root(tmp_path)
    path = template_root / "partials/charts.html"
    source = path.read_text()
    image_and_fallback = source[source.index("<img "):source.index("{% else %}")]
    path.write_text(source.replace(image_and_fallback, image_and_fallback * 2, 1))

    with pytest.raises(AssertionError):
        _assert_exact_inventory(_discover(template_root))


def test_the_fallback_must_remain_the_initially_hidden_immediate_sibling(tmp_path):
    template_root = _fixture_root(tmp_path)
    path = template_root / "partials/suggestions.html"
    source = path.read_text()
    source = source.replace(
        '<div class="w-full h-full items-center',
        '<span data-displaced-fallback></span><div class="w-full h-full items-center',
        1,
    )
    path.write_text(source)

    with pytest.raises(AssertionError):
        _assert_exact_inventory(_discover(template_root))


def test_the_fallback_must_not_be_visible_before_an_error(tmp_path):
    template_root = _fixture_root(tmp_path)
    path = template_root / "partials/search_results.html"
    source = path.read_text()
    assert source.count('style="display:none"') >= 1
    path.write_text(source.replace('style="display:none"', 'style="display:flex"', 1))

    with pytest.raises(AssertionError):
        _assert_exact_inventory(_discover(template_root))
