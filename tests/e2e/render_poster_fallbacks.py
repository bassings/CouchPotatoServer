#!/usr/bin/env python3
"""Render the four production poster fallbacks for browser verification."""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "libs"))

from couchpotato.ui import _jinja  # noqa: E402


SURFACES = {
    "charts": (
        "partials/charts.html",
        {
            "charts": [{
                "name": "Fallback chart",
                "list": [{
                    "title": "Charts fallback movie",
                    "identifiers": {"imdb": "tt0000001"},
                    "info": {
                        "titles": ["Charts fallback movie"],
                        "year": 2026,
                        "images": {"poster": ["http://poster.test/charts.png"]},
                    },
                }],
            }],
        },
    ),
    "search": (
        "partials/search_results.html",
        {
            "movies": [{
                "titles": ["Search fallback movie"],
                "year": 2026,
                "imdb": "tt0000002",
                "directors": ["Fixture Director"],
                "images": {"poster": ["http://poster.test/search.png"]},
            }],
        },
    ),
    "suggestions": (
        "partials/suggestions.html",
        {
            "movies": [{
                "titles": ["Suggestions fallback movie"],
                "year": 2026,
                "imdb": "tt0000003",
                "images": {"poster": ["http://poster.test/suggestions.png"]},
            }],
        },
    ),
    "library": (
        "partials/movie_cards.html",
        {
            "movies": [{
                "_id": "fallback-library-movie",
                "status": "active",
                "profile": {},
                "releases": [],
                "info": {
                    "titles": ["Library fallback movie"],
                    "year": 2026,
                    "images": {"poster": ["http://poster.test/library.png"]},
                },
            }],
        },
    ),
}


def render() -> str:
    rendered = []
    for surface, (template, context) in SURFACES.items():
        html = _jinja.get_template(template).render(new_base="/", **context)
        rendered.append(
            f'<section data-poster-surface="{surface}">{html}</section>'
        )
    return "<!doctype html><html><body>" + "".join(rendered) + "</body></html>"


def main(output_path: str) -> int:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(), encoding="utf-8")
    print(json.dumps({"output": str(output), "surfaces": list(SURFACES)}))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: render_poster_fallbacks.py OUTPUT_PATH")
    raise SystemExit(main(sys.argv[1]))
