"""Contract test for partials/charts.html.

`tests/e2e/helpers.ts` stubs `/partial/charts` so the E2E suite does not wait on
external chart providers (measured at ~85s against the real services, which is
what made two specs time out). The stub has to stay faithful to the real
template, and here that matters more than usual for two reasons:

  * `accessibility.a11y.spec.ts` runs axe against the STUB's markup. Any
    a11y-relevant attribute the stub omits is an attribute nothing checks — the
    stub originally dropped the focus-ring classes, so axe was "verifying" a
    visible focus indicator that was not in the markup under test.
  * `charts.html`'s own `movie-skipped` listener selects
    `.poster-card[data-imdb="…"]`, so a card without `data-imdb` silently breaks
    skip-removal, and the stub had no `data-imdb` at all.

Asserts the structural contract the E2E specs and the page's own script rely on,
not exact markup, so restyling does not break it.
"""

import re
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "couchpotato" / "ui" / "templates"
TEMPLATE = "partials/charts.html"
STUB = REPO_ROOT / "tests" / "e2e" / "helpers.ts"

# Shape matters: charts.html reads `movie.identifiers.imdb` / `movie.info.*`,
# NOT the flat shape the search template uses. Getting it wrong renders
# `data-imdb=""` and a title of "Unknown", which is how this fixture first
# failed — a useful reminder that a contract test is only as good as its input.
FIXTURE_CHARTS = [
    {
        "name": "Blu-ray.com - New Releases",
        "list": [
            {
                "title": "Example Movie",
                "identifiers": {"imdb": "tt0137523"},
                "info": {
                    "titles": ["Example Movie"],
                    "year": 2026,
                    "images": {"poster": ["http://example.invalid/p.jpg"]},
                },
            },
        ],
    },
]


@pytest.fixture(scope="module")
def html():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True
    )
    return env.get_template(TEMPLATE).render(charts=FIXTURE_CHARTS, new_base="/")


def _card_tag(html: str) -> str:
    match = re.search(r"<button\b[^>]*\bposter-card\b[^>]*>", html)
    assert match, "no .poster-card button rendered"
    return match.group(0)


def test_renders_a_poster_card(html):
    """`waitForSuggestionsReady` waits on `#charts-grid .poster-card`."""
    assert "poster-card" in html


def test_card_carries_data_imdb(html):
    """charts.html's own movie-skipped listener selects `.poster-card[data-imdb]`.

    Without it, skipping a movie silently fails to remove its card.
    """
    assert re.search(r'data-imdb="[^"]+"', _card_tag(html)), (
        "the poster card has no data-imdb attribute"
    )


def test_card_has_an_accessible_name(html):
    """axe checks that interactive controls are labelled."""
    assert re.search(r'aria-label="[^"]+"', _card_tag(html)), (
        "the poster card button has no aria-label"
    )


def test_card_has_a_visible_focus_indicator(html):
    """WCAG 2.4.7. The E2E stub must carry this too, or axe checks nothing."""
    tag = _card_tag(html)
    # `focus:ring-2`, not just `focus:ring`: the offset utilities
    # (`focus:ring-offset-2`) also contain that substring, so a loose check
    # survived deleting the actual ring (confirmed by mutation).
    assert re.search(r"\bfocus:ring-\d", tag), (
        f"the poster card has no focus-ring WIDTH class, so keyboard focus is "
        f"invisible: {tag[:200]}"
    )


def test_the_e2e_stub_mirrors_the_contract_this_file_asserts():
    """The stub is what axe actually runs against — keep the two in step.

    A contract test that only checks the real template still lets the stub drift
    into asserting a11y properties the stub itself does not have.
    """
    stub = STUB.read_text(encoding="utf-8")
    charts_stub = stub.split("mockSuggestionsCharts", 1)[1].split("export ", 1)[0]

    for required in ("poster-card", "data-imdb=", "aria-label=", "focus:ring-2"):
        assert required in charts_stub, (
            f"the charts stub in tests/e2e/helpers.ts is missing {required!r}, "
            f"which the real template provides and the a11y spec asserts against"
        )
