"""Tests for CouchPotato utility/helper functions.

Tests encoding helpers (toUnicode, toSafeString, simplifyString)
and variable helpers (tryInt, tryFloat, getImdb, etc.).
"""
import os
import re
import time
from urllib.parse import urlparse

import pytest

from couchpotato.core.helpers.encoding import toUnicode, toSafeString, simplifyString
from couchpotato.core.helpers.variable import removePyc, tryInt, getImdb, isLocalIP, longestBracketedName

pytestmark = pytest.mark.unit


class TestEncodingHelpers:
    """Test string encoding/conversion utilities."""

    def test_toUnicode_with_str(self):
        assert toUnicode('hello') == 'hello'

    def test_toUnicode_with_bytes(self):
        result = toUnicode(b'hello', 'utf-8')
        assert isinstance(result, str)
        assert result == 'hello'

    def test_toUnicode_with_int(self):
        result = toUnicode(42)
        assert result == '42'

    def test_toSafeString_strips_special_chars(self):
        result = toSafeString('Hello/World:Test!')
        assert '/' not in result
        assert ':' not in result
        assert '!' not in result

    def test_toSafeString_preserves_alphanumeric(self):
        result = toSafeString('Hello World 2024')
        assert 'Hello' in result
        assert 'World' in result
        assert '2024' in result

    def test_simplifyString_lowercase_and_clean(self):
        result = simplifyString('The Lost City (2022)')
        assert result == result.lower()
        assert 'the' in result
        assert 'lost' in result
        assert 'city' in result
        assert '2022' in result

    def test_simplifyString_strips_accents(self):
        result = simplifyString('Amélie')
        assert 'amelie' in result


class TestVariableHelpers:
    """Test variable/type conversion utilities."""

    def test_tryInt_with_valid_int(self):
        assert tryInt('42') == 42

    def test_tryInt_with_float_string(self):
        assert tryInt('3.14') == 0  # not a clean int

    def test_tryInt_with_invalid_returns_default(self):
        assert tryInt('not_a_number') == 0

    def test_tryInt_with_none(self):
        assert tryInt(None) == 0

    def test_getImdb_extracts_from_url(self):
        result = getImdb('https://www.imdb.com/title/tt1234567/')
        assert result == 'tt1234567'

    def test_getImdb_extracts_bare_id(self):
        result = getImdb('tt7654321')
        assert result == 'tt7654321'

    def test_getImdb_returns_falsy_for_no_match(self):
        result = getImdb('no imdb here')
        assert not result


class TestRemovePyc:
    """removePyc() runs at CouchPotato.py import time, before anything else
    -- an unhandled exception here crashes the whole process before a
    single log line is written.

    T1.7 (E2E per-worker isolation) starts multiple CouchPotato.py
    processes concurrently against the SAME checkout: every worker's
    process walks and cleans the identical couchpotato/**/__pycache__
    tree. Measured directly: with `--workers=3`, a second process's
    os.listdir() on a __pycache__ directory a FIRST process had just
    emptied and os.rmdir()'d raised an unhandled FileNotFoundError,
    killing that worker's server before it ever bound a port -- with
    tests/e2e/fixtures.ts's readiness check correctly turning that into
    "the application under test exited", but a genuinely avoidable one.

    removePyc's own os.remove() call two lines above is already wrapped in
    try/except Exception (line-for-line the same defensive shape this test
    pins for os.listdir/os.rmdir) -- this is completing a pattern already
    established in the function, not introducing a new one.
    """

    def test_tolerates_a_directory_vanishing_between_walk_and_listdir(self, tmp_path, monkeypatch):
        # Simulate the race directly: os.walk() has already yielded this
        # directory's name, but a concurrent process deletes it before
        # THIS call reaches os.listdir(). Everything else in the tree is
        # real, so only the raced directory is faked.
        pkg_dir = tmp_path / 'pkg'
        pkg_dir.mkdir()
        cache_dir = pkg_dir / '__pycache__'
        cache_dir.mkdir()
        (cache_dir / 'mod.cpython-314.pyc').write_text('stale bytecode')
        (pkg_dir / 'mod.py').write_text('# real source')

        real_listdir = os.listdir

        def racy_listdir(path):
            if os.path.abspath(path) == os.path.abspath(str(cache_dir)):
                raise FileNotFoundError(2, 'No such file or directory', str(cache_dir))
            return real_listdir(path)

        monkeypatch.setattr(os, 'listdir', racy_listdir)

        # Must not raise -- this is the exact crash observed under
        # concurrent workers.
        removePyc(str(tmp_path), show_logs=False)

    def test_tolerates_a_directory_vanishing_before_rmdir(self, tmp_path, monkeypatch):
        # A narrower window of the same race: os.listdir() succeeds (sees
        # an empty dir) but a concurrent process removes the directory
        # before THIS call's own os.rmdir() runs.
        pkg_dir = tmp_path / 'pkg'
        pkg_dir.mkdir()
        cache_dir = pkg_dir / '__pycache__'
        cache_dir.mkdir()

        real_rmdir = os.rmdir

        def racy_rmdir(path):
            if os.path.abspath(path) == os.path.abspath(str(cache_dir)):
                raise FileNotFoundError(2, 'No such file or directory', str(cache_dir))
            return real_rmdir(path)

        monkeypatch.setattr(os, 'rmdir', racy_rmdir)

        removePyc(str(tmp_path), show_logs=False)

    def test_still_removes_excess_pyc_in_the_non_racy_case(self, tmp_path):
        # The guard must not make removePyc a no-op -- its actual job
        # (delete a .pyc with no matching .py) still has to happen when
        # nothing races it.
        #
        # The now-empty __pycache__ dir is NOT pruned on this same call:
        # os.walk() is top-down, so a directory's emptiness is checked
        # while visiting its PARENT, before the walk has descended into it
        # and deleted its .pyc files -- pre-existing behaviour, unrelated
        # to this guard, confirmed separately below (it takes a second
        # call, i.e. the next process restart, to prune it).
        pkg_dir = tmp_path / 'pkg'
        pkg_dir.mkdir()
        cache_dir = pkg_dir / '__pycache__'
        cache_dir.mkdir()
        stale_pyc = cache_dir / 'orphan.cpython-314.pyc'
        stale_pyc.write_text('stale bytecode, no matching orphan.py')

        removePyc(str(tmp_path), show_logs=False)

        assert not stale_pyc.exists()

    def test_prunes_an_empty_pycache_dir_left_over_from_a_prior_call(self, tmp_path):
        # Completes the case above: a __pycache__ left empty by an EARLIER
        # removePyc call (or process exit) is pruned on the next one.
        pkg_dir = tmp_path / 'pkg'
        pkg_dir.mkdir()
        cache_dir = pkg_dir / '__pycache__'
        cache_dir.mkdir()

        removePyc(str(tmp_path), show_logs=False)

        assert not cache_dir.exists()


class TestIsLocalIP:
    """isLocalIP() used to embed a JAVASCRIPT regex literal (the wrapping
    '/../' delimiters) directly in a Python re.search() call. In Python
    those slashes are literal characters, not delimiters, so two of the
    seven alternatives could never match: one needed a literal '/' before
    '^' (start of string) and one needed a literal '/' after '$' (end of
    string). The practical effect was that IPv6 loopback ('::1') was never
    recognised by the regex -- only the standalone http_client.py caller
    matters here (couchpotato/core/http_client.py:131, which exempts local
    hosts from being permanently disabled after repeated failures), so an
    IPv6-only local service got disabled where the same service on
    127.0.0.1 would not.

    These tests pin the full table, including the cases that already
    passed, so the fix cannot regress them.
    """

    # -- IPv4 loopback and private ranges (already worked before the fix) --

    def test_ipv4_loopback_is_local(self):
        assert isLocalIP('127.0.0.1') is True

    def test_ipv4_class_c_private_is_local(self):
        assert isLocalIP('192.168.1.10') is True

    def test_ipv4_class_a_private_is_local(self):
        assert isLocalIP('10.0.0.5') is True

    def test_hostname_localhost_is_local(self):
        assert isLocalIP('localhost') is True

    # -- 172.16.0.0/12: the real private range is 172.16.x through 172.31.x --

    def test_172_16_lower_bound_is_local(self):
        assert isLocalIP('172.16.0.1') is True

    def test_172_20_mid_range_is_local(self):
        assert isLocalIP('172.20.5.5') is True

    def test_172_31_upper_bound_is_local(self):
        assert isLocalIP('172.31.255.255') is True

    def test_172_15_just_below_range_is_not_local(self):
        assert isLocalIP('172.15.0.1') is False

    def test_172_32_just_above_range_is_not_local(self):
        assert isLocalIP('172.32.0.1') is False

    # -- public addresses stay public --

    def test_public_ip_google_dns_is_not_local(self):
        assert isLocalIP('8.8.8.8') is False

    def test_arbitrary_public_ip_is_not_local(self):
        assert isLocalIP('1.2.3.4') is False

    # -- IPv6 loopback: THE BUG. Was False before the fix. --

    def test_ipv6_loopback_shorthand_is_local(self):
        assert isLocalIP('::1') is True

    def test_ipv6_loopback_full_form_is_local(self):
        # '0:0:0:0:0:0:0:1' is the same address as '::1' written without
        # zero-compression. Supported deliberately: a client library is as
        # likely to hand us one form as the other, and refusing the
        # uncompressed form would just re-introduce the same class of bug
        # for a differently-formatted address. Deliberately NOT attempting
        # general IPv6 canonicalisation (case folding, partial compression
        # like '0:0:0:0:0:0:0:01', mixed forms) -- that is a much bigger
        # surface for false positives than this helper's job justifies.
        assert isLocalIP('0:0:0:0:0:0:0:1') is True

    # -- anchoring: must not match the pattern mid-string --

    def test_public_ip_followed_by_private_looking_text_is_not_local(self):
        # A careless (unanchored) alternation could match '10.0.0.1'
        # wherever it appears in the string, not just at the start.
        assert isLocalIP('8.8.8.8 via 10.0.0.1') is False

    def test_hostname_containing_loopback_looking_text_is_not_local(self):
        # '127.0.0.1' appears in this string but not at the start, and the
        # whole thing is a hostname, not a loopback address.
        assert isLocalIP('not-127.0.0.1.example.com') is False


class TestIsLocalIPWithPortAndBrackets:
    """The first round of this fix pinned isLocalIP() against bare
    addresses only ('::1', '127.0.0.1'). Review found the only real
    caller never sends a bare address: couchpotato/core/http_client.py:131
    calls isLocalIP(host) where host is built at http_client.py:203 as

        host = f'{parsed_url.hostname}{(":" + str(parsed_url.port)) if parsed_url.port else ""}'

    urlparse() strips brackets from an IPv6 host, so for a URL like
    'http://[::1]:9117/api' this produces the string '::1:9117' -- and the
    end-anchored '::1$' alternative from round one cannot match that,
    because the port defeats the anchor. So the bug this task exists to
    fix (IPv6-only local services get permanently disabled where the same
    service on 127.0.0.1 would not) was still live for essentially every
    real IPv6 deployment, since a self-hosted service almost always has an
    explicit port.

    These tests pin the host:port and bracketed shapes directly, plus a
    set of hostile inputs designed to prove the fix does not widen the
    match to catch strings that merely *contain* a private-looking prefix
    or suffix.
    """

    # -- IPv4 with an explicit port: must still recognise the address --

    def test_ipv4_loopback_with_port_is_local(self):
        assert isLocalIP('127.0.0.1:9117') is True

    def test_ipv4_private_with_port_is_local(self):
        assert isLocalIP('192.168.1.5:8080') is True

    def test_public_ipv4_with_port_is_not_local(self):
        assert isLocalIP('8.8.8.8:443') is False

    # -- bare (unbracketed) IPv6 loopback with a port. THE BUG. --
    #
    # Deliberate rule: 'addr:port' is genuinely ambiguous for a bare IPv6
    # address (unlike IPv4, IPv6 addresses themselves contain colons), so
    # a trailing ':<digits>' is read as a port ONLY when stripping it
    # leaves one of the two recognised loopback forms. Anything else is
    # used exactly as given -- it is not a false "host:port" guess, it is
    # the address, and it only matches if it IS a loopback address.

    def test_bare_ipv6_loopback_with_port_is_local(self):
        assert isLocalIP('::1:9117') is True

    def test_bare_ipv6_loopback_full_form_with_port_is_local(self):
        assert isLocalIP('0:0:0:0:0:0:0:1:9117') is True

    def test_public_ipv6_documentation_address_is_not_local(self):
        # 2001:db8::/32 is the IPv6 documentation range. It is not a
        # loopback address before OR after stripping a trailing number, so
        # the ambiguous-port rule must not touch it.
        assert isLocalIP('2001:db8::1') is False

    def test_public_ipv6_documentation_address_with_port_is_not_local(self):
        # Same address as above with a trailing ':9117'. A careless rule
        # ("if it ends in :digits, strip and treat the rest as the
        # address") would wrongly read this as address '2001:db8::1',
        # which is itself not a loopback address either -- but a rule that
        # instead always keeps the STRIPPED form would need checking too.
        # Neither the stripped nor the unstripped form is a loopback
        # address, so this must stay False either way.
        assert isLocalIP('2001:db8::1:9117') is False

    # -- bracketed IPv6, the standard URL host form: unambiguous --

    def test_bracketed_ipv6_loopback_is_local(self):
        assert isLocalIP('[::1]') is True

    def test_bracketed_ipv6_loopback_with_port_is_local(self):
        assert isLocalIP('[::1]:9117') is True

    # -- must not widen: string CONTAINS a private prefix/suffix, isn't one --

    def test_hostname_with_colon_port_that_looks_like_an_ip_suffix_is_not_local(self):
        # The 'port' half of this host:port split is not digits, so it
        # must not be treated as a port at all -- and the whole string
        # must not be mistaken for the address '127.0.0.1' it contains.
        assert isLocalIP('evil.com:127.0.0.1') is False

    def test_private_ip_followed_by_non_digit_text_after_colon_is_not_local(self):
        # The single-colon split must only ever be treated as 'address:port'
        # when what follows the colon really is a port (all digits). If that
        # check were dropped, a private-looking address with a colon and
        # arbitrary text after it -- not a real port -- would be quietly
        # reduced down to just the address and wrongly recognised as local.
        assert isLocalIP('127.0.0.1:evil') is False

    def test_hostname_with_loopback_looking_prefix_and_real_suffix_is_not_local(self):
        # Starts with '127.0.0.1' but is not that address -- it is a
        # hostname with more labels after it. The IPv4 patterns must be
        # end-anchored, not just start-anchored, or this slips through.
        assert isLocalIP('127.0.0.1.evil.com') is False


class TestIsLocalIPLocalhostIsExactNotSubstring:
    """`localhost` must match the literal hostname, never as a substring.

    This was the SAME defect as the start-anchored IPv4 alternatives, sitting
    one clause below them, and fixing only those left it open. A hostname is
    attacker-chosen and `isLocalIP` decides which hosts are exempt from being
    disabled after repeated failures, so anything containing the word must not
    inherit that exemption.
    """

    def test_the_literal_hostname_is_local(self):
        assert isLocalIP('localhost') is True

    def test_the_literal_hostname_with_a_port_is_local(self):
        assert isLocalIP('localhost:9117') is True

    def test_a_scheme_prefixed_localhost_is_local(self):
        assert isLocalIP('http://localhost:8080') is True

    @pytest.mark.parametrize('host', ['localhost.', 'localhost.:9117', 'http://localhost.:9117'])
    def test_the_absolute_dns_spelling_is_local(self, host):
        """`localhost.` with the root dot is a legitimate way to name the host,
        and urlparse preserves it, so a service configured that way must keep
        the exemption. An exact `== 'localhost'` rejected it, which would have
        disabled a genuinely local endpoint after five transient failures.
        """
        assert isLocalIP(host) is True

    @pytest.mark.parametrize('host', [
        'localhost.evil.com',
        'localhost.evil.com.',
        'evil-localhost.com',
        'notlocalhost.net',
        'my.localhost.attacker.io',
        'localhost.attacker.io:443',
    ])
    def test_a_hostname_merely_containing_localhost_is_not_local(self, host):
        assert isLocalIP(host) is False, (
            '%r contains "localhost" but is an ordinary registerable hostname. '
            'Treating it as local would exempt an attacker-chosen host from '
            'the failure-disable path.' % host
        )


class TestIsLocalIPMatchesHttpClientHostShape:
    """http_client.py:203 builds the host string isLocalIP() actually
    receives from urlparse(), not by hand. Every isLocalIP test above
    (and every one from round one) asserts on a hand-written address
    string, so the suite stayed green while the real call path -- an
    IPv6 URL with an explicit port -- was still broken. These tests
    replicate http_client.py:203's own construction from a real URL via
    urlparse, so a future change to either side that breaks the pairing
    is caught here rather than only in production.
    """

    @staticmethod
    def _host_from_url(url):
        # Deliberately duplicates http_client.py:203's host construction
        # rather than importing http_client (which pulls in the wider
        # client machinery for one two-line expression). Keep this in
        # sync with that line if it changes.
        parsed_url = urlparse(url)
        return f'{parsed_url.hostname}{(":" + str(parsed_url.port)) if parsed_url.port else ""}'

    def test_ipv6_loopback_url_with_port_is_local(self):
        host = self._host_from_url('http://[::1]:9117/api')
        assert host == '::1:9117'  # pin the exact shape the bug report measured
        assert isLocalIP(host) is True

    def test_ipv6_loopback_url_without_port_is_local(self):
        host = self._host_from_url('http://[::1]/api')
        assert host == '::1'
        assert isLocalIP(host) is True

    def test_ipv4_loopback_url_with_port_is_local(self):
        host = self._host_from_url('http://127.0.0.1:9117/')
        assert host == '127.0.0.1:9117'
        assert isLocalIP(host) is True

    def test_public_host_url_with_port_is_not_local(self):
        host = self._host_from_url('http://example.com:8443/')
        assert host == 'example.com:8443'
        assert isLocalIP(host) is False


def _old_bracketed_name_expression(name):
    """The exact expression both call sites used before the fix.

    Kept here, not imported, so the test pins the ORIGINAL behaviour rather
    than whatever the two call sites happen to say today.
    """
    return max(re.findall(r'[^[]*\[([^]]*)\]', name), key = len).strip()


class TestLongestBracketedNameEquivalence:
    """`longestBracketedName` must match the old inline expression exactly
    for ordinary, at-or-under-the-cap input -- this is the searcher and the
    scorer, so a behaviour change here changes which releases match.
    """

    ORDINARY_NAMES = [
        'Some.Movie.2024.1080p.BluRay.x264-GROUP',
        'Some.Movie.2024.1080p.BluRay.x264-GROUP [PublicHD]',
        'Movie [Nested [inner] outer] Name',
        'Movie [first] and [a much longer second bracket group]',
        'No brackets at all here',
        '',
        '[]',
        'Leading ] bracket has no opener',
        'Trailing [ bracket has no closer',
        'Movie [empty][also empty][third]',
        '][][][',
    ]

    @pytest.mark.parametrize('name', ORDINARY_NAMES)
    def test_matches_old_expression_when_old_expression_succeeds(self, name):
        try:
            expected = _old_bracketed_name_expression(name)
        except Exception:
            pytest.skip('old expression raises for %r, covered separately' % name)

        assert longestBracketedName(name) == expected

    @pytest.mark.parametrize('name', ORDINARY_NAMES)
    def test_raises_exactly_when_old_expression_raises(self, name):
        old_raised = False
        try:
            _old_bracketed_name_expression(name)
        except Exception:
            old_raised = True

        if not old_raised:
            pytest.skip('old expression succeeds for %r, covered separately' % name)

        with pytest.raises(Exception):
            longestBracketedName(name)

    def test_picks_the_longest_group_not_the_first_or_last(self):
        name = 'Movie [x] middle [a much longer bracketed group here] end [y]'
        assert longestBracketedName(name) == 'a much longer bracketed group here'

    def test_strips_the_result(self):
        name = 'Movie [  padded group  ]'
        assert longestBracketedName(name) == 'padded group'


class TestLongestBracketedNamePerformanceCap:
    """The DoS: re.findall retries from every start position, so a run of
    unclosed '[' is quadratic in length. Measured on this machine against
    the OLD expression: 8000 unclosed brackets ~124 ms, 16000 ~496 ms, and
    sceneScore() (score/main.py:66) runs this per search RESULT, so a
    hostile provider controls both the length of each name and how many
    results one response contains.
    """

    def test_pathological_input_is_bounded(self):
        pathological = '[' * 16000

        # Absolute, not relative-to-baseline: the property under test is
        # "a 16000-char adversarial input does not cost anywhere near its
        # unbounded ~496 ms", and the cap makes the cost independent of
        # input length, so there is no meaningful baseline to be relative
        # to. The margin is wide (50 ms, ~8x a cold/loaded run of the
        # capped-prefix parse) so this does not flake on a busy machine --
        # the unpatched code is ~10x slower than even this generous bound.
        started = time.perf_counter()
        try:
            longestBracketedName(pathological)
        except Exception:
            pass
        elapsed = time.perf_counter() - started

        assert elapsed < 0.05, (
            'longestBracketedName took %.4f s on a 16000-char adversarial '
            'input; the input length must be capped before parsing so a '
            'provider-supplied release name cannot make this quadratic-cost '
            'regex run against tens of thousands of characters' % elapsed
        )

    def test_capped_prefix_still_finds_a_bracket_within_the_limit(self):
        # A merely long (not pathological) name with its bracket inside the
        # capped prefix must still score -- capping bounds cost, it must not
        # blanket-reject anything over the limit.
        name = 'A' * 100 + ' [group] ' + 'B' * 500
        assert longestBracketedName(name) == 'group'
