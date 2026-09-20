"""Behavior and recurrence contracts for the Python S8786 rule-family batch."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_test_traps  # noqa: E402


VULNERABLE_BOUNDARIES = {
    "scripts/check_test_traps.py": (
        "PIPEFAIL_RE = re.compile(",
        're.search(r"^\\s*[^()]*\\)\\s*$", line)',
        "OPT_OUT_RE = re.compile(",
        "_LOCATOR_BINDING = re.compile(",
        're.search(r"^(\\S*Error:.*)$", result.stderr, re.MULTILINE)',
    ),
    "couchpotato/core/media/_base/providers/nzb/binsearch.py": (
        "re.search(r'(?P<size>\\d+d)'",
    ),
    "couchpotato/core/media/movie/providers/metadata/wdtv.py": (
        "text_re = re.compile('>\\n\\\\s+([^<>\\\\s].*?)\\n\\\\s+</', re.DOTALL)",
    ),
    "couchpotato/core/media/movie/providers/metadata/xbmc.py": (
        "text_re = re.compile('>\\n\\\\s+([^<>\\\\s].*?)\\n\\\\s+</', re.DOTALL)",
    ),
    "couchpotato/core/media/movie/providers/metadata/base.py": (
        "re.compile('>\\n\\\\s+([^<>\\\\s].*?)\\n\\\\s+</', re.DOTALL)",
    ),
    "couchpotato/core/plugins/log/main.py": (
        "log_pattern = re.compile(",
    ),
}


def test_the_nine_s8786_boundaries_do_not_restore_the_vulnerable_expressions():
    found = []
    for relative_path, snippets in VULNERABLE_BOUNDARIES.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        found.extend(
            f"{relative_path}:{index}"
            for index, snippet in enumerate(snippets, start=1)
            if snippet in source
        )
    assert not found, "vulnerable S8786 boundary restored: " + ", ".join(found)


@pytest.mark.timeout(2)
def test_test_trap_string_parsers_are_bounded_on_long_non_matches():
    from couchpotato.core.media.movie.providers.metadata.base import compactPrettyXmlText
    from couchpotato.core.plugins.log.main import _parse_log_header

    hostile = " " * 100_000
    started = perf_counter()
    assert not check_test_traps._has_real_pipeline([hostile + ")"])
    assert not check_test_traps._has_pipefail("set " + ("-e " * 50_000) + "pipefail")
    assert not check_test_traps._has_pipefail(("set -e " * 8_000) + "ordinary")
    assert check_test_traps._live_region_bindings(
        "const target = page.locator('" + hostile + "');"
    ) is None
    assert check_test_traps._live_region_bindings(
        ("const ordinary = " * 40_000) + "page.locator('.ordinary')"
    ) is None
    assert check_test_traps._vacuous_guard_reason("// " + hostile) == (False, "")
    assert check_test_traps._node_error_message(hostile) is None
    assert _parse_log_header("01-02 03:04:05 NOPE " + hostile) is None
    compacted = compactPrettyXmlText("<plot>\n  " + hostile + "A\n  </plot>\n")
    assert compacted == "<plot>A</plot>\n"
    metadata_no_match = ">\n  A\n  X" * 10_000
    assert compactPrettyXmlText(metadata_no_match) == metadata_no_match
    assert perf_counter() - started < 1.5


@pytest.mark.timeout(2)
def test_each_repaired_subgroup_is_bounded_when_the_match_is_late():
    from couchpotato.core.media._base.providers.nzb.binsearch import _age_in_days
    from couchpotato.core.media.movie.providers.metadata.base import compactPrettyXmlText
    from couchpotato.core.plugins.log.main import _parse_log_header

    prefix = "ordinary " * 20_000
    assert check_test_traps._has_real_pipeline([prefix + "left | right"])
    assert check_test_traps._has_pipefail(prefix + "set -o pipefail")
    assert check_test_traps._vacuous_guard_reason(
        prefix + "// vacuous-guard-ok: justified"
    ) == (True, "justified")
    assert check_test_traps._live_region_bindings(
        ("const ordinary = 1;" * 20_000)
        + "const status = page.locator('[data-testid=\"trakt-auth-status\"]');"
    ) == ("status", ("trakt-auth-status",))
    assert check_test_traps._node_error_message(
        ("ordinary diagnostic\n" * 20_000) + "SyntaxError: final failure"
    ) == "SyntaxError: final failure"

    assert _age_in_days(("x" * 100_000) + "12d") == 12
    xml = "<plot>\n" + (" " * 100_000) + "A\n  </plot>"
    assert compactPrettyXmlText(xml) == "<plot>A</plot>"
    header = _parse_log_header("01-02 03:04:05 INFO " + ("x" * 100_000))
    assert header == ("01-02 03:04:05", "INFO", "x" * 100_000)


def test_pipefail_continuation_and_spaced_opt_out_keep_their_contracts():
    assert check_test_traps._has_real_pipeline(["docker build | tee build.log"])
    assert not check_test_traps._has_real_pipeline(["false || echo recovered"])
    assert not check_test_traps._has_real_pipeline(["echo 'not | a pipeline'"])
    assert not check_test_traps._has_real_pipeline(["ready|waiting)"])
    assert check_test_traps._has_pipefail("set -eu -o \\\npipefail")
    assert check_test_traps._vacuous_guard_reason(
        "if (x) { //    vacuous-guard-ok: external precondition"
    ) == (True, "external precondition")
    assert check_test_traps._vacuous_guard_reason(
        "if (x) { // note: vacuous-guard-ok: not an exemption"
    ) == (False, "")
    assert check_test_traps._vacuous_guard_reason(
        "vacuous-guard-ok: decoy // vacuous-guard-ok: actual reason"
    ) == (True, "actual reason")


def _binsearch_result(age_text: str):
    from couchpotato.core.media._base.providers.nzb.binsearch import Base

    html = f"""<html><body><table id="r2"><tr>
    <td><span class="s">Example Release</span>
    <input type="checkbox" name="nzb-7">
    <span class="d">size: 1 GB available: 10 / 10 <a href="/detail/7">info</a></span></td>
    <td>{age_text}</td></tr></table></body></html>"""
    provider = object.__new__(Base)
    provider.getHTMLData = lambda _url: html
    provider.buildUrl = lambda _media, _quality: "query"
    provider.parseSize = lambda value: value
    results = []

    provider._search({}, {}, results)

    assert len(results) == 1
    return results[0]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("12d", 12),
        ("posted 7d ago", 7),
        ("1d then 2d", 1),
        ("²d 7d", 7),
        ("①d 8d", 8),
        ("12345", 0),
        ("unknown", 0),
    ],
)
def test_binsearch_age_contract(source, expected):
    result = _binsearch_result(source)
    assert result["age"] == expected
    assert result["id"] == "nzb-7"
    assert result["size"] == "1 GB"


@pytest.mark.timeout(2)
def test_binsearch_age_parser_is_bounded_on_a_long_digit_only_cell():
    from couchpotato.core.media._base.providers.nzb.binsearch import _age_in_days

    assert _age_in_days("9" * 100_000) == 0


def test_binsearch_missing_age_cell_keeps_this_and_later_candidates(monkeypatch):
    from couchpotato.core.media._base.providers.nzb import binsearch

    def row(name, age_cells):
        title = SimpleNamespace(text=name)
        checkbox = {"name": name}
        link = {"href": f"/{name}"}
        info = SimpleNamespace(text="size: 1 GB available: 10 / 10")
        info.find = lambda _tag: link
        candidate = Mock()
        candidate.find.side_effect = lambda _tag, attrs=None: (
            title if attrs == {"class": "s"} else checkbox if attrs == {"type": "checkbox"} else info
        )
        candidate.find_all.return_value = age_cells
        return candidate

    table = Mock()
    table.find_all.return_value = [
        row("missing-age", []),
        row("valid-age", [SimpleNamespace(text="2d")]),
    ]
    document = Mock()
    document.find.return_value = table
    monkeypatch.setattr(binsearch, "BeautifulSoup", lambda *_args, **_kwargs: document)
    provider = object.__new__(binsearch.Base)
    provider.getHTMLData = lambda _url: "response"
    provider.buildUrl = lambda _media, _quality: "query"
    provider.parseSize = lambda value: value
    results = []

    provider._search({}, {}, results)

    assert [(item["id"], item["age"]) for item in results] == [
        ("missing-age", 0),
        ("valid-age", 2),
    ]


def _metadata_fixture(provider_class):
    images = {
        key: []
        for key in (
            "actors",
            "poster_original",
            "backdrop_original",
            "banner",
            "disc_art",
            "logo",
            "clear_art",
            "landscape",
            "extra_thumbs",
            "extra_fanart",
        )
    }
    movie_info = {
        "images": images,
        "rating": {},
        "plot": "A < B & C\nsecret-shaped=not-a-secret",
        "genres": ["Drama"],
    }
    data = {"identifier": "tt123", "files": {}, "meta_data": {}, "renamed_files": []}
    provider = object.__new__(provider_class)
    provider.conf = lambda _name: False
    return provider.getNfo(movie_info, data)


@pytest.mark.parametrize(
    ("module_name", "class_name", "root_name", "expected_sha256"),
    [
        (
            "couchpotato.core.media.movie.providers.metadata.wdtv",
            "WdtvLive",
            "details",
            "5c52d824d7478a61bd952d7a1f3f4b9c95b07fc86e4a48242d7cb23a0cdfa2af",
        ),
        (
            "couchpotato.core.media.movie.providers.metadata.xbmc",
            "XBMC",
            "movie",
            "34a8d28215643c9c99c640b58dd32b276b90b2e6288a8a9bb25a2bb710e6b5d6",
        ),
    ],
)
def test_metadata_output_remains_parseable_and_escaped(
    module_name, class_name, root_name, expected_sha256
):
    module = __import__(module_name, fromlist=[class_name])
    output = _metadata_fixture(getattr(module, class_name))

    assert isinstance(output, bytes)
    assert hashlib.sha256(output).hexdigest() == expected_sha256
    assert b"A &lt; B &amp; C" in output
    assert b"< B & C" not in output
    root = ElementTree.fromstring(output)
    assert root.tag == root_name
    assert root.findtext("plot") == "A < B & C\nsecret-shaped=not-a-secret"


@pytest.mark.parametrize(
    ("module_name", "class_name", "plot", "expected"),
    [
        ("couchpotato.core.media.movie.providers.metadata.wdtv", "WdtvLive", "\n  A\n  ", "A"),
        ("couchpotato.core.media.movie.providers.metadata.xbmc", "XBMC", "\n  A\n  ", "A"),
        ("couchpotato.core.media.movie.providers.metadata.wdtv", "WdtvLive", "\n\n A\n\n ", "A"),
        ("couchpotato.core.media.movie.providers.metadata.xbmc", "XBMC", "\n\n A\n\n ", "A"),
        ("couchpotato.core.media.movie.providers.metadata.wdtv", "WdtvLive", "\nA\n ", "\nA\n "),
        ("couchpotato.core.media.movie.providers.metadata.xbmc", "XBMC", "\nA\n ", "\nA\n "),
    ],
)
def test_metadata_leading_whitespace_keeps_legacy_compaction(
    module_name, class_name, plot, expected
):
    module = __import__(module_name, fromlist=[class_name])
    provider_class = getattr(module, class_name)

    images = {
        key: []
        for key in (
            "actors", "poster_original", "backdrop_original", "banner", "disc_art",
            "logo", "clear_art", "landscape", "extra_thumbs", "extra_fanart",
        )
    }
    provider = object.__new__(provider_class)
    provider.conf = lambda _name: False
    output = provider.getNfo(
        {"images": images, "rating": {}, "plot": plot},
        {"identifier": "tt123", "files": {}, "meta_data": {}, "renamed_files": []},
    )

    if expected == "A":
        assert b"<plot>A</plot>" in output
    assert ElementTree.fromstring(output).findtext("plot") == expected


def test_log_parser_preserves_headers_continuations_and_later_entries():
    from couchpotato.core.plugins.log.main import Logging

    parser = object.__new__(Logging)
    content = (
        "ignored preamble\n"
        "01-02 03:04:05 INFO first message  \n"
        "  traceback detail\n"
        "\n"
        "malformed continuation\n"
        "02-03 04:05:06 ERROR \n"
        "03-04 05:06:07 DEBUG last\n"
    )

    assert parser.toList(content) == [
        {
            "time": "01-02 03:04:05",
            "type": "INFO",
            "message": "first message  \n  traceback detail\nmalformed continuation",
        },
        {"time": "02-03 04:05:06", "type": "ERROR", "message": ""},
        {"time": "03-04 05:06:07", "type": "DEBUG", "message": "last"},
    ]


def test_log_parser_rejects_non_decimal_digit_lookalikes():
    from couchpotato.core.plugins.log.main import _parse_log_header

    assert _parse_log_header("²1-02 03:04:05 INFO message") is None
    assert _parse_log_header("01-02 ⓪3:04:05 INFO message") is None


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_log_parser_recognizes_every_production_level_and_strips_ansi(level):
    from couchpotato.core.plugins.log.main import Logging

    parser = object.__new__(Logging)
    result = parser.toList(f"\x1b[31m01-02 03:04:05 {level} message\x1b[0m")
    assert result == [
        {"time": "01-02 03:04:05", "type": level, "message": "message"}
    ]
