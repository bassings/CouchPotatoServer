"""Regression guard for deterministic production HTML parsing."""

import ast
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOTS = (
    REPO_ROOT / "couchpotato",
    REPO_ROOT / "scripts",
    REPO_ROOT / "CouchPotato.py",
)


def _python_files():
    for root in PRODUCTION_ROOTS:
        if root.is_file():
            yield root
        elif root.is_dir():
            yield from sorted(root.rglob("*.py"))


def _beautifulsoup_calls(source, filename="<source>"):
    tree = ast.parse(source, filename=filename)
    direct_names = set()
    module_names = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "bs4":
            for imported in node.names:
                if imported.name == "BeautifulSoup":
                    direct_names.add(imported.asname or imported.name)
        elif isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name == "bs4":
                    module_names.add(imported.asname or imported.name)

    def is_constructor_alias(value):
        return (
            isinstance(value, ast.Name) and value.id in direct_names
        ) or (
            isinstance(value, ast.Attribute)
            and value.attr == "BeautifulSoup"
            and isinstance(value.value, ast.Name)
            and value.value.id in module_names
        )

    # Follow simple aliases to a fixed point so `Soup = BeautifulSoup` and
    # chains such as `Parser = Soup` cannot hide a newly implicit call.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            targets = []
            value = None
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            if value is None or not is_constructor_alias(value):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in direct_names:
                    direct_names.add(target.id)
                    changed = True

    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        direct_call = isinstance(node.func, ast.Name) and node.func.id in direct_names
        module_call = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "BeautifulSoup"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in module_names
        )
        if direct_call or module_call:
            calls.append(node)
    return calls


def _has_explicit_parser(call):
    if len(call.args) >= 2:
        return True
    return any(keyword.arg == "features" for keyword in call.keywords)


def _literal_parser(call):
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        return call.args[1].value
    for keyword in call.keywords:
        if keyword.arg == "features" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def test_guard_recognises_aliased_calls_and_parser_forms():
    calls = _beautifulsoup_calls(
        """
from bs4 import BeautifulSoup as Soup
import bs4 as beautiful
Soup(payload)
Soup(payload, 'lxml')
beautiful.BeautifulSoup(payload, features='lxml')
beautiful.BeautifulSoup(payload, builder='lxml')
beautiful.BeautifulSoup(payload, builder=tree_builder)
"""
    )

    assert len(calls) == 5
    assert [_has_explicit_parser(call) for call in calls] == [
        False,
        True,
        True,
        False,
        False,
    ]


def test_guard_follows_simple_and_chained_constructor_assignments():
    calls = _beautifulsoup_calls(
        """
from bs4 import BeautifulSoup
import bs4 as beautiful
Soup = BeautifulSoup
Parser = Soup
ModuleSoup = beautiful.BeautifulSoup
Soup(payload)
Parser(payload, 'lxml')
ModuleSoup(payload, features='lxml')
"""
    )

    assert len(calls) == 3
    assert [_has_explicit_parser(call) for call in calls] == [False, True, True]


def test_every_production_beautifulsoup_call_names_a_parser():
    found = []
    implicit = []

    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        for call in _beautifulsoup_calls(source, filename=str(path)):
            location = "%s:%d" % (path.relative_to(REPO_ROOT), call.lineno)
            found.append(location)
            if not _has_explicit_parser(call):
                implicit.append(location)

    assert found, "anti-vacuity: no production BeautifulSoup calls were discovered"
    assert not implicit, "BeautifulSoup calls without an explicit parser:\n%s" % "\n".join(
        implicit
    )


def test_external_parser_choices_are_literal_and_pinned():
    parsers = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        parsers.extend(
            _literal_parser(call)
            for call in _beautifulsoup_calls(source, filename=str(path))
        )

    assert parsers
    assert set(parsers) <= {"html.parser", "lxml"}
    assert "lxml==6.1.3" in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()


def _unfinished(html, malformed):
    return html.replace("</body></html>", "") if malformed else html


def _bare_provider(provider_class, **methods):
    provider = object.__new__(provider_class)
    for name, value in methods.items():
        setattr(provider, name, value if callable(value) else Mock(return_value=value))
    return provider


@pytest.mark.parametrize("malformed", [False, True])
def test_binsearch_real_search_keeps_candidate_fields(malformed):
    from couchpotato.core.media._base.providers.nzb.binsearch import Base

    data = _unfinished(
        """<html><body><table id="r2"><tr>
        <td><span class="s">Example Release</span>
        <input type="checkbox" name="nzb-7">
        <span class="d">size: 1 GB available: 10 / 10 <a href="/detail/7">info</a></span></td>
        <td>2d</td></tr></table></body></html>""",
        malformed,
    )
    provider = _bare_provider(
        Base,
        getHTMLData=data,
        buildUrl="query",
        parseSize=lambda value: value,
    )
    results = []

    provider._search({}, {}, results)

    assert [(item["id"], item["name"], item["size"], item["detail_url"]) for item in results] == [
        ("nzb-7", "example release", "1 GB", "https://www.binsearch.info/detail/7")
    ]


@pytest.mark.parametrize("malformed", [False, True])
def test_torrent_search_providers_keep_candidate_fields(malformed):
    from couchpotato.core.media._base.providers.torrent.alpharatio import Base as AlphaRatio
    from couchpotato.core.media._base.providers.torrent.awesomehd import Base as AwesomeHD
    from couchpotato.core.media._base.providers.torrent.iptorrents import Base as IPTorrents
    from couchpotato.core.media._base.providers.torrent.scenetime import Base as SceneTime
    from couchpotato.core.media._base.providers.torrent.thepiratebay import Base as PirateBay
    from couchpotato.core.media._base.providers.torrent.torrentbytes import Base as TorrentBytes

    alpha_html = _unfinished(
        """<html><body><table id="torrent_table"><tr class="torrent">
        <td><a dir="ltr" href="torrents.php?id=101&amp;x=1">Alpha Name</a>
        <a title="Download" href="download/101">get</a></td><td>x</td><td>x</td>
        <td>1 GB</td><td>x</td><td>4</td><td>2</td></tr></table></body></html>""",
        malformed,
    )
    alpha = _bare_provider(
        AlphaRatio,
        buildUrl=("query", "0", 1),
        getHTMLData=alpha_html,
        parseSize=lambda value: value,
    )
    alpha_results = []
    alpha._search({}, {}, alpha_results)
    assert [(item["id"], str(item["name"]), item["size"]) for item in alpha_results] == [
        ("101", "Alpha Name", "1 GB")
    ]

    awesome_html = _unfinished(
        """<html><body><authkey>auth</authkey><torrent><id>202</id><name>Awesome Name</name>
        <year>2025</year><releasegroup>GROUP</releasegroup><resolution>1080p</resolution>
        <encoding>x264</encoding><freeleech>1</freeleech><media>BluRay</media>
        <audioformat>DTS</audioformat><size>1048576</size><seeders>8</seeders><leechers>1</leechers>
        </torrent></body></html>""",
        malformed,
    )
    awesome = _bare_provider(
        AwesomeHD,
        getHTMLData=awesome_html,
        conf=lambda key: {"passkey": "pass", "only_internal": False,
                          "prefer_internal": False, "favor": "none"}.get(key),
    )
    awesome_results = []
    awesome._search({"identifier": "tt1"}, {}, awesome_results)
    assert [(item["id"], item["name"], item["size"]) for item in awesome_results] == [
        ("202", "Awesome.Name.2025.1080p.BluRay.DTS.x264-GROUP", 1.0)
    ]

    ip_html = _unfinished(
        """<html><body><table id="torrents"><tr><th>head</th></tr><tr>
        <td>x</td><td><a href="/details.php?id=303">IP Name</a></td><td>x</td>
        <td><a href="/download/file name.torrent">get</a></td>
        <td class="ac t_seeders">6</td><td>2 GB</td><td class="ac t_leechers">3</td>
        </tr></table></body></html>""",
        malformed,
    )
    ip = _bare_provider(
        IPTorrents,
        conf=False,
        buildUrl="https://example.invalid/search?free=%s&page=%d",
        shuttingDown=False,
        getHTMLData=ip_html,
        getRequestHeaders={},
        parseSize=lambda value: value,
    )
    ip_results = []
    ip._searchOnTitle("title", {}, {}, ip_results)
    assert [(item["id"], item["name"], item["size"]) for item in ip_results] == [
        ("303", "IP Name", "2 GB")
    ]

    pirate_html = _unfinished(
        """<html><body><table id="searchResult"><tr><th>head</th></tr><tr>
        <td><a href="/torrent/404/name">Pirate Name</a>
        <a href="magnet:?xt=urn:btih:404">magnet</a>
        <font class="detDesc">Size 3 GB, Uploaded now</font></td><td>x</td><td>7</td><td>1</td>
        </tr></table></body></html>""",
        malformed,
    )
    pirate = _bare_provider(
        PirateBay,
        getCatId=200,
        getDomain=lambda path=None: "https://tpb.invalid%s" % (path or ""),
        buildUrl=("title", 0, 200),
        getHTMLData=pirate_html,
        conf=False,
        parseSize=lambda value: value,
    )
    pirate_results = []
    pirate._search({}, {}, pirate_results)
    assert [(item["id"], item["name"], item["size"]) for item in pirate_results] == [
        ("404", "Pirate Name", "3 GB")
    ]

    torrentbytes_html = _unfinished(
        """<html><body><table border="1"><tr><th>head</th></tr><tr>
        <td>x</td><td><a class="index" href="details.php?id=5050000-extra" title="Bytes Name">name</a></td>
        <td>x</td><td>x</td><td>x</td><td>x</td><td>4 <span>unit</span>GB</td><td>x</td>
        <td><span>9</span></td><td><span>2</span></td></tr></table></body></html>""",
        malformed,
    )
    torrentbytes = _bare_provider(
        TorrentBytes,
        getCatId=[5],
        getHTMLData=torrentbytes_html,
        parseSize=lambda value: value,
    )
    torrentbytes_results = []
    torrentbytes._searchOnTitle("title", {"info": {"year": 2025}}, {}, torrentbytes_results)
    assert [(item["id"], item["name"], item["size"]) for item in torrentbytes_results] == [
        ("5050000", "Bytes Name", "4 GB")
    ]

    scenetime_html = _unfinished(
        """<html><body><table id="torrenttable"><tr><th>head</th></tr><tr>
        <td>x</td><td><a class="index" href="download.php/606/file.torrent">Scene Name</a></td>
        <td>x</td><td>x</td><td>x</td><td>5 <span>unit</span>GB</td><td><span>10</span></td>
        </tr></table></body></html>""",
        malformed,
    )
    scenetime = _bare_provider(
        SceneTime,
        getCatId=[59],
        getHTMLData=scenetime_html,
        parseSize=lambda value: value,
    )
    scenetime_results = []
    scenetime._searchOnTitle("title", {"info": {"year": 2025}}, {}, scenetime_results)
    assert [(item["id"], item["name"], item["size"]) for item in scenetime_results] == [
        ("606", "Scene Name", "5 GB")
    ]


@pytest.mark.parametrize("malformed", [False, True])
def test_description_parsers_keep_extracted_text(malformed):
    from couchpotato.core.media._base.providers.torrent.bithdtv import Base as BitHDTV
    from couchpotato.core.media._base.providers.torrent.thepiratebay import Base as PirateBay

    pirate = _bare_provider(
        PirateBay,
        getCache=_unfinished('<html><body><div class="nfo">Pirate details</div></body></html>', malformed),
    )
    bit = _bare_provider(
        BitHDTV,
        getCache=_unfinished('<html><body><table class="detail"><tr><td>Bit details</td></tr></table></body></html>', malformed),
    )

    assert pirate.getMoreInfo({"id": "1", "detail_url": "unused"})["description"] == "Pirate details"
    assert bit.getMoreInfo({"id": "2", "detail_url": "unused"})["description"] == "Bit details"


@pytest.mark.parametrize("malformed", [False, True])
def test_letterboxd_real_watchlist_keeps_titles(malformed):
    from couchpotato.core.media.movie.providers.automation.letterboxd import Letterboxd

    data = _unfinished(
        """<html><body><ul><li class="paginate-page"><a>2</a></li>
        <li class="poster-container"><img alt="Example Film"></li></ul></body></html>""",
        malformed,
    )
    provider = _bare_provider(
        Letterboxd,
        conf=lambda key: {"automation_urls_use": "1", "automation_urls": "tester"}[key],
        getHTMLData=data,
    )

    assert provider.getWatchlist() == [{"title": "Example Film"}]


@pytest.mark.parametrize("malformed", [False, True])
def test_bluray_real_backlog_keeps_identifier(malformed):
    from couchpotato.core.media.movie.providers.automation.bluray import Bluray

    current = _unfinished(
        """<html><body><div><a><h3>Example Film Blu-ray 2025</h3></a>
        <small>studio | 2025</small></div></body></html>""",
        malformed,
    )
    cutoff = _unfinished("<html><body><div><h3>Archive 1999</h3></div></body></html>", malformed)
    provider = _bare_provider(
        Bluray,
        conf=lambda key, **kwargs: True if key == "backlog" and "value" not in kwargs else None,
        getHTMLData=Mock(side_effect=[current, cutoff]),
        getMinimal=2000,
        search={"imdb": "tt1234567"},
        isMinimalMovie=True,
        getRSSData=[],
    )

    assert provider.getIMDBids() == ["tt1234567"]


@pytest.mark.parametrize("malformed", [False, True])
def test_hdtrailers_real_parsers_keep_provider_links_and_no_match_result(malformed):
    from couchpotato.core.media.movie.providers.trailer.hdtrailers import HDTrailers

    data = _unfinished(
        """<html><body><table class="bottomTable"><tr>
        <td><span class="standardTrailerName">Official Trailer</span> apple.ico trailer</td>
        <td class="bottomTableResolution"><a href="https://trailers.invalid/720">720p</a></td>
        </tr></table></body></html>""",
        malformed,
    )
    provider = object.__new__(HDTrailers)

    assert provider.findByProvider(data, "apple.ico")["720p"] == ["https://trailers.invalid/720"]
    provider.getCache = Mock(return_value=_unfinished("<html><body><table><p>No matching trailer</p></table></body></html>", malformed))
    assert provider.findViaAlternative({"title": "Example Film", "identifier": "tt1"}) == {
        "480p": [], "720p": [], "1080p": []
    }


@pytest.mark.parametrize("malformed", [False, True])
def test_hdtrailers_alternative_matching_heading_preserves_existing_failure(malformed):
    """A matching heading currently calls Tag.lower(), which is not callable."""
    from couchpotato.core.media.movie.providers.trailer.hdtrailers import HDTrailers

    data = _unfinished(
        """<html><body><table><tr><td><h2>Example Film trailer</h2></td></tr>
        </table></body></html>""",
        malformed,
    )
    provider = object.__new__(HDTrailers)
    provider.getCache = Mock(return_value=data)

    with pytest.raises(TypeError, match="'NoneType' object is not callable"):
        provider.findViaAlternative({"title": "Example Film", "identifier": "tt1"})


@pytest.mark.parametrize("malformed", [False, True])
def test_userscript_real_parsers_keep_title_and_year(malformed):
    from couchpotato.core.media.movie.providers.userscript.filmstarts import Filmstarts
    from couchpotato.core.media.movie.providers.userscript.filmweb import Filmweb

    filmstarts_data = _unfinished(
        """<html><head><meta property="og:title" content="Fallback"></head><body>
        <section class="section ovw ovw-synopsis" id="synopsis-details">
        <span>Originaltitel</span><h2>Original Name</h2>
        <span>Produktionsjahr</span><span>2025</span></section></body></html>""",
        malformed,
    )
    filmstarts = _bare_provider(Filmstarts, getUrl=filmstarts_data, search=lambda name, year: (name, year))
    assert filmstarts.getMovie("unused") == ("Original Name", "2025")

    filmweb_data = _unfinished(
        '<html><head><meta name="title" content="Film Name (2025) - Filmweb"></head><body></body></html>',
        malformed,
    )
    filmweb = _bare_provider(Filmweb, urlopen=filmweb_data, search=lambda name, year: (name, year))
    with patch(
        "couchpotato.core.media.movie.providers.userscript.filmweb.fireEvent",
        return_value={"name": "Film Name", "year": 2025},
    ):
        assert filmweb.getMovie("unused") == ("Film Name", 2025)


def test_filmweb_missing_title_metadata_skips_search():
    from couchpotato.core.media.movie.providers.userscript.filmweb import Filmweb

    search = Mock()
    provider = _bare_provider(
        Filmweb,
        urlopen="<html><head></head><body></body></html>",
        search=search,
    )

    with patch(
        "couchpotato.core.media.movie.providers.userscript.filmweb.fireEvent"
    ) as parse_name_year:
        assert provider.getMovie("unused") is None

    parse_name_year.assert_not_called()
    search.assert_not_called()


@pytest.mark.parametrize(
    "html",
    [
        "<html><body></body></html>",
        """<html><head></head><body>
        <section class="section ovw ovw-synopsis" id="synopsis-details">
        <span>Produktionsjahr</span><span>2025</span></section></body></html>""",
        """<html><head><meta property="og:title" content="Fallback"></head><body>
        <section class="section ovw ovw-synopsis" id="synopsis-details">
        </section></body></html>""",
        """<html><body>
        <section class="section ovw ovw-synopsis" id="synopsis-details">
        <span>Originaltitel</span>
        <span>Produktionsjahr</span><span>2025</span></section>
        <nav><h2>Navigation heading</h2></nav></body></html>""",
        """<html><head><meta property="og:title" content="Fallback"></head><body>
        <section class="section ovw ovw-synopsis" id="synopsis-details">
        <span>Produktionsjahr</span></section>
        <footer><span>Privacy</span></footer></body></html>""",
    ],
    ids=[
        "missing-synopsis",
        "missing-title",
        "missing-year",
        "title-decoy-outside-synopsis",
        "year-decoy-outside-synopsis",
    ],
)
def test_filmstarts_missing_required_metadata_skips_search(html):
    from couchpotato.core.media.movie.providers.userscript.filmstarts import Filmstarts

    search = Mock()
    provider = _bare_provider(Filmstarts, getUrl=html, search=search)

    assert provider.getMovie("unused") is None
    search.assert_not_called()


def test_awesomehd_missing_authkey_skips_results_with_actionable_error():
    from couchpotato.core.media._base.providers.torrent.awesomehd import Base as AwesomeHD

    provider = _bare_provider(
        AwesomeHD,
        getHTMLData="<html><body><torrent><id>202</id></torrent></body></html>",
        conf=lambda key: {"passkey": "pass", "only_internal": False}.get(key),
        getName="Awesome-HD",
    )
    results = []

    with patch("couchpotato.core.media._base.providers.torrent.awesomehd.log") as logger:
        provider._search({"identifier": "tt1"}, {}, results)

    assert results == []
    logger.error.assert_called_once_with(
        "Awesome-HD response did not include an auth key; skipping results."
    )


def test_awesomehd_error_element_is_logged_and_skips_results():
    from couchpotato.core.media._base.providers.torrent.awesomehd import Base as AwesomeHD

    provider = _bare_provider(
        AwesomeHD,
        getHTMLData="<html><body><error>Invalid credentials</error></body></html>",
        conf=lambda key: {"passkey": "pass", "only_internal": False}.get(key),
    )
    results = []

    with patch("couchpotato.core.media._base.providers.torrent.awesomehd.log") as logger:
        provider._search({"identifier": "tt1"}, {}, results)

    assert results == []
    logger.info.assert_called_once_with("Invalid credentials")
    logger.error.assert_not_called()


def test_bithdtv_missing_detail_table_returns_empty_description():
    from couchpotato.core.media._base.providers.torrent.bithdtv import Base as BitHDTV

    provider = _bare_provider(
        BitHDTV,
        getCache="<html><body><p>No description supplied</p></body></html>",
    )
    item = {"id": "2", "detail_url": "unused"}

    result = provider.getMoreInfo(item)

    assert result is item
    assert result["description"] == ""
