"""Exact inventory for the final low Web reliability false positives."""

from collections import Counter
from pathlib import Path
import re

from bs4 import BeautifulSoup
import pytest


TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "couchpotato" / "ui" / "templates"
JINJA_COMMENT = re.compile(r"{#-?(.*?)-?#}", re.DOTALL)

AUDITED_LOW_WEB_SOURCES = {
    (
        "partials/settings/trakt_auth.html",
        "dynamic-text-anchor",
        "verificationUrl",
        "verificationUrl",
        "_blank",
        ("noopener", "noreferrer"),
    ): "13080ec9-e723-412b-9fac-b6e3ce0d5324",
    (
        "base.html",
        "server-only-image-example",
        "/logout/",
    ): "f46ec5b5-6c8a-4599-b328-2d960c2288cd",
}


def _comments(source):
    return [match.group(1) for match in JINJA_COMMENT.finditer(source)]


def _served_source(source):
    return JINJA_COMMENT.sub("", source)


def _has_alternative(image):
    return any(name in image.attrs for name in ("alt", ":alt", "x-bind:alt"))


def _discover(template_root=TEMPLATE_ROOT):
    discovered = []
    for path in sorted(template_root.rglob("*.html")):
        relative_path = str(path.relative_to(template_root))
        source = path.read_text()
        served = BeautifulSoup(_served_source(source), "html.parser")

        for anchor in served.find_all("a", attrs={"x-text": True}):
            if not " ".join(anchor.stripped_strings):
                discovered.append((
                    relative_path,
                    "dynamic-text-anchor",
                    anchor.get(":href") or "",
                    anchor.get("x-text") or "",
                    anchor.get("target") or "",
                    tuple(sorted(anchor.get("rel") or [])),
                ))

        for comment in _comments(source):
            soup = BeautifulSoup(comment, "html.parser")
            for image in soup.find_all("img"):
                if not _has_alternative(image):
                    discovered.append((
                        relative_path,
                        "server-only-image-example",
                        image.get("src") or "",
                    ))
    return discovered


def _served_images_without_alternatives(template_root=TEMPLATE_ROOT):
    missing = []
    for path in sorted(template_root.rglob("*.html")):
        soup = BeautifulSoup(_served_source(path.read_text()), "html.parser")
        for image in soup.find_all("img"):
            if not _has_alternative(image):
                missing.append((str(path.relative_to(template_root)), image.get("src") or ""))
    return missing


def _assert_inventory(discovered):
    assert Counter(discovered) == Counter(AUDITED_LOW_WEB_SOURCES.keys())
    assert len(set(AUDITED_LOW_WEB_SOURCES.values())) == len(AUDITED_LOW_WEB_SOURCES)


def _fixture_root(tmp_path):
    for identity in AUDITED_LOW_WEB_SOURCES:
        relative_path = identity[0]
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((TEMPLATE_ROOT / relative_path).read_text())
    return tmp_path


def test_each_low_web_finding_has_one_exact_reviewed_source_identity():
    _assert_inventory(_discover())


def test_every_served_template_image_has_static_or_bound_alternative_text():
    assert _served_images_without_alternatives() == []


def test_duplicate_dynamic_anchor_identity_is_not_collapsed(tmp_path):
    template_root = _fixture_root(tmp_path)
    path = template_root / "partials/settings/trakt_auth.html"
    source = path.read_text()
    anchor = source[source.index("<a :href="):source.index("</a>") + 4]
    path.write_text(source.replace(anchor, anchor * 2, 1))

    with pytest.raises(AssertionError):
        _assert_inventory(_discover(template_root))


def test_exposing_the_security_example_creates_a_real_missing_alt_image(tmp_path):
    template_root = _fixture_root(tmp_path)
    path = template_root / "base.html"
    source = path.read_text()
    assert '`<img src="/logout/">`' in source
    path.write_text(source.replace(
        '`<img src="/logout/">`',
        '-#}<img src="/logout/">{#-',
        1,
    ))

    assert _served_images_without_alternatives(template_root) == [
        ("base.html", "/logout/"),
    ]
    with pytest.raises(AssertionError):
        _assert_inventory(_discover(template_root))


def test_removing_a_real_logo_alternative_is_detected(tmp_path):
    template_root = _fixture_root(tmp_path)
    path = template_root / "base.html"
    source = path.read_text()
    assert source.count('alt="CouchPotato"') == 2
    path.write_text(source.replace(' alt="CouchPotato"', "", 1))

    assert _served_images_without_alternatives(template_root) != []


@pytest.mark.parametrize(
    "comment",
    ['{#<img src="/future/">#}', '{#-<img src="/future/">-#}'],
)
def test_both_jinja_comment_delimiter_forms_are_audited(tmp_path, comment):
    template_root = _fixture_root(tmp_path)
    path = template_root / "base.html"
    path.write_text(path.read_text() + comment)

    assert (
        "base.html",
        "server-only-image-example",
        "/future/",
    ) in _discover(template_root)
