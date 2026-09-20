"""Regression coverage for Sonar's raw movie-detail JavaScript parser."""

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from couchpotato.ui import _jinja


TEMPLATE = (
    Path(__file__).parents[2]
    / "couchpotato"
    / "ui"
    / "templates"
    / "partials"
    / "movie_detail.html"
)


class _ProfileEditorRootParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attrs = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "div" and attributes.get("x-data") == "profileEditor()":
            self.attrs = attributes


class _ExplicitAlpineInitParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.factories = []

    def handle_starttag(self, _tag, attrs):
        attributes = dict(attrs)
        factory = attributes.get("x-data", "")
        if attributes.get("x-init") == "init()" and factory.endswith("()"):
            self.factories.append(factory[:-2])


def _classic_script_source():
    source = TEMPLATE.read_text(encoding="utf-8")
    body = source.split("<script>", 1)[1].split("</script>", 1)[0]
    # Sonar understands template control tags, but the JavaScript bridge still
    # parses output expressions in quoted script content. Removing control tags
    # reproduces that boundary without hiding the output-expression defect.
    return re.sub(r"{%.*?%}|{#.*?#}", "", body, flags=re.DOTALL)


def _explicit_alpine_init_inventory(templates):
    found = Counter()
    for path in templates.rglob("*.html"):
        parser = _ExplicitAlpineInitParser()
        parser.feed(path.read_text(encoding="utf-8"))
        found.update((str(path.relative_to(templates)), name) for name in parser.factories)
    return found


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_movie_detail_classic_script_parses_before_jinja_rendering():
    result = subprocess.run(
        ["node", "--check", "-"],
        input=_classic_script_source(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_profile_identifier_is_inert_autoescaped_markup_not_script_source():
    profile_id = "profile-'\"<&"
    rendered = _jinja.get_template("partials/movie_detail.html").render(
        movie={"_id": "m1", "profile_id": profile_id, "info": {}},
        movie_id="m1",
        releases=[],
        new_base="/",
    )
    parser = _ProfileEditorRootParser()
    parser.feed(rendered)

    assert parser.attrs is not None
    assert parser.attrs["data-current-profile-id"] == profile_id
    assert profile_id not in _classic_script_source()
    assert "newProfile: ''" in _classic_script_source()
    assert "this.newProfile = this.$el.dataset.currentProfileId || '';" in (
        _classic_script_source()
    )


def test_no_new_component_explicitly_duplicates_alpines_automatic_init():
    templates = TEMPLATE.parents[1]
    found = _explicit_alpine_init_inventory(templates)

    # These pre-existing duplicates are a bounded inventory, not examples to
    # copy. Any addition fails until it relies on Alpine's automatic init().
    known_debt = Counter({
        ("logs.html", "logsPanel"): 1,
        ("settings.html", "settingsPanel"): 1,
        ("wizard.html", "setupWizard"): 1,
        ("partials/movie_releases.html", "releaseDownloader"): 1,
    })
    assert found == known_debt


def test_duplicate_init_inventory_preserves_occurrence_counts(tmp_path):
    template = tmp_path / "logs.html"
    template.write_text(
        '<div x-data="logsPanel()" x-init="init()"></div>\n'
        '<div x-data="logsPanel()" x-init="init()"></div>\n',
        encoding="utf-8",
    )

    inventory = _explicit_alpine_init_inventory(tmp_path)

    assert inventory[("logs.html", "logsPanel")] == 2
