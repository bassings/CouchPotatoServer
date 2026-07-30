"""Contract test for partials/search_results.html.

`tests/e2e/helpers.ts` stubs `/partial/search` with hand-written HTML so the E2E
suite does not depend on a live TMDB lookup (an external dependency that made the
search specs slow and, under parallel workers, flaky). A hand-written stub can
drift: the template changes shape, the stub keeps the old shape, and the E2E
assertions keep passing against markup the app no longer produces — a false green.

This test renders the REAL template and asserts the same structural contract the
E2E specs rely on. If the template stops producing any of it, this fails and the
stub gets updated with it. It deliberately asserts on the *selectors the specs
use*, not on exact markup, so ordinary restyling does not break it.
"""

import re
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "couchpotato" / "ui" / "templates"
TEMPLATE = "partials/search_results.html"

# Kept in step with tests/e2e/helpers.ts -> mockMovieSearch().
FIXTURE_MOVIES = [
    {
        "titles": ["The Matrix"],
        "year": 1999,
        "imdb": "tt0133093",
        "directors": ["Lana Wachowski"],
        "images": {"poster": ["http://example.invalid/p.jpg"]},
    },
    {
        "titles": ["The Matrix Reloaded"],
        "year": 2003,
        "imdb": "tt0234215",
        "directors": [],
        "images": {},
    },
]


def render(movies) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    return env.get_template(TEMPLATE).render(movies=movies, new_base="/")


@pytest.fixture(scope="module")
def html():
    return render(FIXTURE_MOVIES)


def test_renders_one_card_per_movie_with_the_selector_the_specs_use(html):
    """`search.spec.ts` locates results via `.rounded-md` inside #search-results."""
    cards = re.findall(r'class="[^"]*\brounded-md\b[^"]*"', html)
    assert len(cards) >= len(FIXTURE_MOVIES), (
        f"expected at least {len(FIXTURE_MOVIES)} `.rounded-md` cards, found {len(cards)}"
    )


def test_first_paragraph_in_a_card_is_the_year(html):
    """`search.spec.ts` reads the year from the card's FIRST <p> (DEF-007).

    If a new <p> is ever added above it, that spec silently starts asserting on
    the wrong text — so the ordering is part of the contract, not an accident.
    """
    body = html.split('class="p-2.5"', 1)[1]
    first_p = re.search(r"<p[^>]*>(.*?)</p>", body, re.DOTALL)
    assert first_p, "no <p> found inside the card body"
    assert "1999" in first_p.group(1), (
        f"the first <p> in a card should carry the year; got {first_p.group(1)!r}"
    )


def test_each_card_has_a_profile_select(html):
    """`search.spec.ts` asserts a `select` is visible in the results."""
    selects = re.findall(r"<select\b", html)
    assert len(selects) >= len(FIXTURE_MOVIES), (
        f"expected a profile <select> per card, found {len(selects)}"
    )


def test_each_card_has_an_add_button(html):
    """`search.spec.ts` filters buttons by the text 'Add'."""
    assert re.search(r">\s*Add\s*<", html), "no button labelled 'Add' in the rendered card"


def test_year_falls_back_to_tba_rather_than_rendering_zero():
    """A missing year must not render as `0` — that is what DEF-007 fixed."""
    html = render([{"titles": ["No Year Movie"], "year": 0, "imdb": "tt0000001"}])
    assert "TBA" in html
    assert not re.search(r"<p[^>]*>\s*0\s*</p>", html), "rendered a bare 0 as the year"


def test_empty_results_render_the_no_results_state():
    """The specs distinguish 'no results' from 'not loaded yet'."""
    html = render([])
    assert "No results found" in html


def test_identifying_info_is_present_for_def_007(html):
    """DEF-007: results must carry enough to tell two same-titled films apart."""
    assert "tt0133093" in html, "imdb id missing from the card"
    assert "Lana Wachowski" in html, "director missing when the provider supplies one"
