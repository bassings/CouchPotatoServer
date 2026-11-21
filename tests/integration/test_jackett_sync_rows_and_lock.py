"""SEC-005 P2 review round 1: the rows a sync writes, and the read of the saved key under the settings lock.

A. The CHECK and the REQUEST use the normalised address (the string checked is
the string sent), but the ROWS a sync writes are built from the saved address as
the user saved it, after ``cleanHost``, exactly as before the guard: the merge
compares host strings exactly and ``_isJackettIndexerHost`` is frozen. A file
whose rows were written as master wrote them must therefore merge to "0 new",
leave every ``host`` byte as it was, and keep recognising every row as Jackett's.

B. ``_jackettCredentials`` reads address, key and binding in one hold of the lock
a key save holds, so a key save cannot land between the key read and the binding
read.

Hosts are ``.invalid`` or ``.local`` names and every key is a ``placeholder-`` string.
"""
import threading

import pytest
import requests
from urllib3.util import parse_url


from couchpotato.core.settings import _PASSWORD_SAVE_LOCK
from tests.helpers.jackett_binding import (
    BINDING_OPTION,
    KEY_OPTION,
    OPERATIONS,
    OTHER_KEY,
    PLACEHOLDER_KEY,
    REFUSAL,
    SECTION,
    URL_OPTION,
    guarded_world,
    on_disk,
)
from tests.integration.test_jackett_key_guard import bind, memory, run, save

pytestmark = pytest.mark.integration

COLUMNS = ('use', 'host', 'pass_key', 'name', 'seed_ratio', 'seed_time', 'extra_score')

# (label, the address as saved, the row host master wrote for indexer `alpha`).
# Every expected host is a literal: `cleanHost(saved).rstrip('/')` plus the potato path.
MASTER_ROWS = [
    ('a capital letter in the host', 'http://NAS:9117', 'http://NAS:9117/potato/alpha/api'),
    ('upper case scheme and host', 'HTTP://JACKETT.LOCAL:9117', 'HTTP://JACKETT.LOCAL:9117/potato/alpha/api'),
    ('an explicit default http port', 'http://jackett.local:80', 'http://jackett.local:80/potato/alpha/api'),
    ('an explicit default https port and a path', 'https://jackett.local:443/jackett',
     'https://jackett.local:443/jackett/potato/alpha/api'),
    ('a zero-padded port', 'http://jackett.local:09117', 'http://jackett.local:09117/potato/alpha/api'),
    ('a trailing slash', 'http://jackett.local:9117/', 'http://jackett.local:9117/potato/alpha/api'),
    ('no scheme', 'jackett.local:9117', 'http://jackett.local:9117/potato/alpha/api'),
    ('the bytes-literal wrapper', "b'http://jackett.local:9117/'", 'http://jackett.local:9117/potato/alpha/api'),
]


def stored_as_master_wrote_it(saved, row_host):
    """File-edit simulation of the previous release: its saved pair (no binding) and one synced row."""
    return {SECTION: {'use': '1', 'host': row_host, 'pass_key': PLACEHOLDER_KEY, 'name': 'Alpha',
                      'seed_ratio': '1', 'seed_time': '40', 'extra_score': '0',
                      URL_OPTION: saved, KEY_OPTION: PLACEHOLDER_KEY}}


def host_cells(settings):
    return [cell for cell in (on_disk(settings, 'host') or '').split(',') if cell]


@pytest.mark.parametrize('label,saved,row_host', MASTER_ROWS, ids=[row[0] for row in MASTER_ROWS])
class TestTheFirstSyncAfterUpgradeKeepsTheRowsItAlreadyHas:
    """AC-QA-1: Sync stores the indexers exactly as before the change."""

    def test_refused_then_the_key_re_entered_a_merge_sync_adds_nothing_and_rewrites_no_host(
            self, tmp_path, monkeypatch, label, saved, row_host):
        with guarded_world(tmp_path, monkeypatch, stored=stored_as_master_wrote_it(saved, row_host)) as (
                settings, client, provider, transport):
            recognised_before = [provider._isJackettIndexerHost(host) for host in host_cells(settings)]
            assert provider.jackettSync() == {'success': False, 'error': REFUSAL}
            assert host_cells(settings) == [row_host]
            assert save(client, KEY_OPTION, PLACEHOLDER_KEY).json()['success'] is True

            result = provider.jackettSync()

            assert result['success'] is True
            assert result['added'] == 0
            assert result['total'] == 1
            assert host_cells(settings) == [row_host]
            assert [provider._isJackettIndexerHost(host) for host in host_cells(settings)] == recognised_before
            if 'bytes' not in label:
                assert recognised_before == [True]

    def test_a_replace_sync_writes_the_row_host_master_would_have_written(
            self, tmp_path, monkeypatch, label, saved, row_host):
        with guarded_world(tmp_path, monkeypatch, stored=stored_as_master_wrote_it(saved, row_host)) as (
                settings, client, provider, transport):
            save(client, KEY_OPTION, PLACEHOLDER_KEY)

            result = provider.jackettSync(replace=True)

            assert result['success'] is True
            assert host_cells(settings) == [row_host]


# (bound address, the equivalent form used, scheme, host, effective port, path): all literals.
EQUIVALENT = [
    ('http://saved-a.invalid:9117', 'HTTP://SAVED-A.INVALID:9117', 'http', 'saved-a.invalid', 9117, ''),
    ('http://saved-a.invalid:9117', 'http://saved-a.invalid:9117/', 'http', 'saved-a.invalid', 9117, ''),
    ('http://saved-a.invalid:9117', 'saved-a.invalid:9117', 'http', 'saved-a.invalid', 9117, ''),
    ('http://saved-a.invalid', 'http://saved-a.invalid:80', 'http', 'saved-a.invalid', 80, ''),
    ('https://saved-a.invalid', 'https://saved-a.invalid:443/', 'https', 'saved-a.invalid', 443, ''),
    ('http://saved-a.invalid:9117/jackett', 'http://saved-a.invalid:9117/jackett/', 'http',
     'saved-a.invalid', 9117, '/jackett'),
    ('http://saved-a.invalid:9117', 'http://saved-a.invalid:09117', 'http', 'saved-a.invalid', 9117, ''),
]


def denotation(address):
    """(scheme, lower-case host, effective port, path) as the HTTP client's own parser reads it."""
    parsed = parse_url(address)
    default = {'http': 80, 'https': 443}[parsed.scheme]
    return parsed.scheme, parsed.host.lower(), parsed.port or default, (parsed.path or '').rstrip('/')


@pytest.mark.parametrize('bound,used,scheme,host,port,path', EQUIVALENT,
                         ids=[row[1] for row in EQUIVALENT])
class TestTheRowBaseDenotesTheAddressThatWasChecked:
    """AC-SEC-2: an accepted equivalent form writes rows for the same destination the key went to."""

    def test_the_row_base_and_the_request_name_the_same_scheme_host_port_and_path(
            self, tmp_path, monkeypatch, bound, used, scheme, host, port, path):
        with guarded_world(tmp_path, monkeypatch) as (settings, client, provider, transport):
            bind(client, bound)
            assert save(client, URL_OPTION, used).json()['success'] is True

            result = provider.jackettSync(replace=True)

            assert result['success'] is True
            row = host_cells(settings)[0]
            assert row.endswith('/potato/alpha/api')
            row_base = row[:-len('/potato/alpha/api')]
            assert denotation(row_base) == (scheme, host, port, path)
            assert denotation(transport.requests[0].split('/torznab/')[0]) == (scheme, host, port, path)


@pytest.mark.parametrize('refused', [
    'http://saved-a.invalid:9117@evil.invalid',
    r'http://evil.invalid\@saved-a.invalid:9117',
    'http://saved-a.invalid:9117#@evil.invalid',
    'http://saved-a.invalid.:9117',
    'http://sibling-a.invalid:9117',
])
def test_a_refused_form_writes_no_row_at_all(tmp_path, monkeypatch, refused):
    with guarded_world(tmp_path, monkeypatch) as (settings, client, provider, transport):
        bind(client)
        before = host_cells(settings)
        save(client, URL_OPTION, refused)

        for operation in OPERATIONS:
            assert run(provider, operation) == {'success': False, 'error': REFUSAL}

        assert host_cells(settings) == before
        assert transport.requests == []


def test_an_own_url_request_writes_rows_from_the_url_it_supplied_as_before(tmp_path, monkeypatch):
    with guarded_world(tmp_path, monkeypatch) as (settings, client, provider, transport):
        result = provider.jackettSync(jackett_url='HTTP://Caller.Invalid:80/', jackett_api_key=OTHER_KEY,
                                      replace=True)

        assert result['success'] is True
        assert host_cells(settings) == ['HTTP://Caller.Invalid:80/potato/alpha/api']


def as_the_transport_reads_it(url, provider, transport):
    """(scheme, host, port) of `url` after the preparation the HTTP client applies to every request.

    The real client is driven (its own quoting runs), the transport records the URL it is handed,
    and `requests` prepares that exactly as the session would before sending.
    """
    transport.requests.clear()
    provider.http_client.request(url)
    prepared = requests.Request('GET', transport.requests[-1]).prepare()
    parsed = parse_url(prepared.url)
    return parsed.scheme, parsed.host, parsed.port or {'http': 80, 'https': 443}[parsed.scheme]


# (label, the address as saved, the binding a key save must store, the row host a sync must write).
# Every string is a literal; the whitespace and the Kelvin sign are written as escapes so they stay visible.
UNUSUAL = [
    ('a Kelvin-sign host', 'http://jac\u212aett:9117', 'http://jackett:9117',
     'http://jackett:9117/potato/alpha/api'),
    ('a trailing no-break space', 'http://jackett:9117\u00a0', 'http://jackett:9117',
     'http://jackett:9117/potato/alpha/api'),
    ('a trailing ideographic space', 'http://jackett:9117\u3000', 'http://jackett:9117',
     'http://jackett:9117/potato/alpha/api'),
    ('a trailing next-line character', 'http://jackett:9117\u0085', 'http://jackett:9117',
     'http://jackett:9117/potato/alpha/api'),
    ('a leading space', ' jackett:9117', 'http://jackett:9117', 'http://jackett:9117/potato/alpha/api'),
    ('the bytes wrapper and a trailing space', "b'http://jackett:9117' ", 'http://jackett:9117',
     'http://jackett:9117/potato/alpha/api'),
    ('the bytes wrapper with a space inside', "b' jackett:9117'", 'http://jackett:9117',
     'http://jackett:9117/potato/alpha/api'),
]


@pytest.mark.parametrize('label,saved,binding,row_host', UNUSUAL, ids=[row[0] for row in UNUSUAL])
def test_AC_SEC_17_every_row_a_sync_writes_resolves_to_the_host_the_key_was_bound_to(
        tmp_path, monkeypatch, label, saved, binding, row_host):
    """Simulation of the saved address as the running process holds it in memory (the file's round
    trip strips surrounding whitespace, so only a process that has not restarted holds these);
    the key is then saved through settings.save, which binds it."""
    with guarded_world(tmp_path, monkeypatch) as (settings, client, provider, transport):
        settings.p.set(SECTION, URL_OPTION, saved)
        assert memory(settings, URL_OPTION) == saved
        assert save(client, KEY_OPTION, PLACEHOLDER_KEY).json()['success'] is True
        assert on_disk(settings, BINDING_OPTION) == binding

        result = provider.jackettSync(replace=True)

        assert result['success'] is True
        assert host_cells(settings) == [row_host]
        expected = ('http', 'jackett', 9117)
        sent = transport.requests[0].split('/torznab/')[0]
        assert as_the_transport_reads_it(binding, provider, transport) == expected
        assert as_the_transport_reads_it(sent, provider, transport) == expected
        for row in host_cells(settings):
            assert as_the_transport_reads_it(row, provider, transport) == expected


def test_a_request_with_its_own_key_and_no_url_writes_rows_by_the_formula_master_used(tmp_path, monkeypatch):
    with guarded_world(tmp_path, monkeypatch) as (settings, client, provider, transport):
        save(client, URL_OPTION, 'HTTP://Jackett.Local:80/')

        result = provider.jackettSync(jackett_api_key=OTHER_KEY, replace=True)

        assert result['success'] is True
        assert host_cells(settings) == ['HTTP://Jackett.Local:80/potato/alpha/api']


class TestTheKeyIsReadUnderTheSettingsLock:
    """B: a key save cannot land between the reader's reads of address, key and binding."""

    @pytest.mark.parametrize('pause_after', [KEY_OPTION, BINDING_OPTION])
    def test_a_key_save_waits_for_a_reader_that_has_not_finished_its_reads(
            self, tmp_path, monkeypatch, pause_after):
        """The reader is held after one of its reads (address already read as B); a real key save of K2
        then runs in another thread. Without the lock it sets the binding to B; paused after the key
        read, the reader then reads it and K1 goes to B. Paused after the binding read, the binding
        read itself being outside the lock is what lets the save land."""
        with guarded_world(tmp_path, monkeypatch) as (settings, client, provider, transport):
            bind(client)
            save(client, URL_OPTION, 'http://other-b.invalid:9117')
            assert memory(settings, BINDING_OPTION) == 'http://saved-a.invalid:9117'
            paused, release = threading.Event(), threading.Event()
            real = provider._savedJackettSetting

            def held_after_the_read(name):
                value = real(name)
                if name == pause_after:
                    paused.set()
                    assert release.wait(10)
                return value
            monkeypatch.setattr(provider, '_savedJackettSetting', held_after_the_read)
            results = []
            reader = threading.Thread(target=lambda: results.append(provider.jackettTest()))
            writer = threading.Thread(target=lambda: results.append(
                settings.saveView(section=SECTION, name=KEY_OPTION, value=OTHER_KEY)))
            reader.start()
            assert paused.wait(10)

            writer.start()
            writer.join(timeout=0.5)
            blocked = writer.is_alive()
            release.set()
            reader.join(10)
            writer.join(10)

            assert blocked, 'the key save did not wait for the reader'
            assert results[0] == {'success': False, 'error': REFUSAL}
            assert transport.requests == []
            assert memory(settings, BINDING_OPTION) == 'http://other-b.invalid:9117'
            assert PLACEHOLDER_KEY not in ' '.join(transport.requests)

    @pytest.mark.parametrize('operation', OPERATIONS)
    def test_a_reader_holds_the_lock_only_for_its_reads_never_for_the_request(
            self, tmp_path, monkeypatch, operation):
        with guarded_world(tmp_path, monkeypatch) as (settings, client, provider, transport):
            bind(client)
            held = []
            real_request = transport.request

            def watching(method, url, **kwargs):
                from tests.helpers.combine_groups import held_by_another_thread
                held.append(held_by_another_thread(_PASSWORD_SAVE_LOCK))
                return real_request(method, url, **kwargs)
            transport.request = watching

            assert run(provider, operation)['success'] is True
            assert held == [False]
