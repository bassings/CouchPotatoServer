"""SEC-005 P2: the saved Jackett API key is only ever sent to the address it was saved for.

The real routes' functions run over a real ``Settings`` and a real
``TorrentPotato``; ``HttpClient`` runs for real too, and the only thing replaced
is the HTTP session behind ``Env.get('http_opener')``, which records every
request that would leave the process (``Transport``). So "zero requests" means
nothing reached the transport, and "one request" is read off the URL that would
have been opened. A key is bound through the production writer, a
``settings.save`` of the key, in every test; the only direct file edits are the
ones a criterion names (an older release's edit, a restored file), and each says
so in its docstring.

Hosts are ``.invalid`` or ``.local`` names and every key is a ``placeholder-``
string.
"""
import itertools
import re
import shutil
import threading

import pytest
from urllib3.util import parse_url

from couchpotato.core.event import addEvent
from couchpotato.core.media._base.providers.torrent import torrentpotato as torrentpotato_module
from couchpotato.core.settings import _PASSWORD_SAVE_LOCK
from couchpotato.environment import Env
from tests.helpers.combine_groups import LogCapture, held_by_another_thread, sha
from tests.helpers.jackett_binding import (
    BINDING_OPTION,
    KEY_OPTION,
    OPERATIONS,
    OTHER_KEY,
    PLACEHOLDER_KEY,
    REFUSAL,
    REQUIRED,
    ROUTE_OF,
    SECTION,
    UNPARSEABLE,
    URL_OPTION,
    guarded_world,
    on_disk,
)
from tests.helpers.combine_groups import three_rows
from tests.integration.test_settings_group_save_route import url

pytestmark = pytest.mark.integration

ROUTE = 'settings.save'
ADDRESS_A = 'http://saved-a.invalid:9117'
ADDRESS_B = 'http://other-b.invalid:9117'
HOST_A = 'saved-a.invalid'
HOST_B = 'other-b.invalid'
ONE_INDEXER = 'alpha'


@pytest.fixture
def world(tmp_path, monkeypatch):
    with guarded_world(tmp_path, monkeypatch) as live:
        yield live


def save(client, name, value):
    return client.post(url(route=ROUTE), data={'section': SECTION, 'name': name, 'value': value})


def save_json(client, name, value):
    return client.post(url(route=ROUTE), json={'section': SECTION, 'name': name, 'value': value})


def bind(client, address=ADDRESS_A, key=PLACEHOLDER_KEY):
    """The user's own steps: address first, then key."""
    assert save(client, URL_OPTION, address).json()['success'] is True
    assert save(client, KEY_OPTION, key).json()['success'] is True


def run(provider, operation, **params):
    return getattr(provider, operation)(**params)


def reached(request_url):
    """(scheme, host, port, path-before-the-query) the transport would connect to, by the transport's own parser."""
    parsed = parse_url(request_url)
    return parsed.scheme, parsed.host, parsed.port, (parsed.path or '').split('/torznab')[0]


def assert_refused(result):
    assert result['success'] is False
    assert result['error'] == REFUSAL


def memory(settings, option):
    return settings.p.get(SECTION, option) if settings.p.has_option(SECTION, option) else None


def remove_binding_option(settings):
    """File-edit simulation (AC-SEC-3): the option absent, as in a file from before this release."""
    settings.p.remove_option(SECTION, BINDING_OPTION)
    settings.save()
    assert on_disk(settings, BINDING_OPTION) is None


# Destinations that are not A (AC-SEC-1). `A with a userinfo prefix` is the one
# the spec names: Python's `urlsplit` reads the host after the `@`.
DIFFERENT_DESTINATIONS = [
    ('another host', ADDRESS_B),
    ('another port', 'http://saved-a.invalid:9118'),
    ('the other scheme', 'https://saved-a.invalid:9117'),
    ('another path', 'http://saved-a.invalid:9117/other'),
    ('A with a userinfo prefix', 'http://saved-a.invalid:9117@other-b.invalid'),
]


@pytest.mark.parametrize('operation', OPERATIONS)
class TestAnAddressChangeRefusesTheSavedKey:
    """AC-SEC-1, AC-SEC-10, AC-DESIGN-5 (API error clause), AC-DATA-8"""

    @pytest.mark.parametrize('label,destination', DIFFERENT_DESTINATIONS,
                             ids=[row[0] for row in DIFFERENT_DESTINATIONS])
    def test_AC_SEC_1_the_key_saved_for_A_is_refused_at_B_with_nothing_sent_or_written(
            self, world, operation, label, destination):
        settings, client, provider, transport = world
        bind(client)
        assert save(client, URL_OPTION, destination).json()['success'] is True
        before = sha(settings.file)

        result = run(provider, operation)

        assert_refused(result)
        assert transport.requests == []
        assert sha(settings.file) == before

    def test_AC_SEC_10_nothing_private_escapes_and_one_warning_names_the_route_and_reason(
            self, world, operation):
        settings, client, provider, transport = world
        bind(client)
        save(client, URL_OPTION, ADDRESS_B)

        with LogCapture() as logs:
            result = run(provider, operation)

        assert_refused(result)
        private = (ADDRESS_A, ADDRESS_B, HOST_A, HOST_B, PLACEHOLDER_KEY)
        for value in private:
            assert value not in str(result)
            assert value not in logs.text()
        warnings = logs.at_or_above(30)
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert warnings[0].levelname == 'WARNING'
        assert ROUTE_OF[operation] in message
        assert 'mismatch' in message
        assert 'unbound' not in message

    def test_AC_SEC_10_an_unbound_key_logs_the_unbound_code(self, world, operation):
        settings, client, provider, transport = world
        bind(client)
        remove_binding_option(settings)

        with LogCapture() as logs:
            result = run(provider, operation)

        assert_refused(result)
        for value in (ADDRESS_A, HOST_A, PLACEHOLDER_KEY):
            assert value not in logs.text()
        warnings = logs.at_or_above(30)
        assert len(warnings) == 1
        assert ROUTE_OF[operation] in warnings[0].getMessage()
        assert 'unbound' in warnings[0].getMessage()
        assert 'mismatch' not in warnings[0].getMessage()

    def test_AC_DATA_8_a_refusal_changes_nothing_and_setting_the_address_back_works_without_the_key(
            self, world, operation):
        settings, client, provider, transport = world
        columns = ('use', 'host', 'pass_key', 'name', 'seed_ratio', 'seed_time', 'extra_score')
        bind(client)
        run(provider, 'jackettSync')
        transport.requests.clear()
        save(client, URL_OPTION, ADDRESS_B)
        before = (sha(settings.file), memory(settings, KEY_OPTION), memory(settings, BINDING_OPTION),
                  [memory(settings, column) for column in columns])

        assert_refused(run(provider, operation))
        assert transport.requests == []

        assert (sha(settings.file), memory(settings, KEY_OPTION), memory(settings, BINDING_OPTION),
                [memory(settings, column) for column in columns]) == before
        assert save(client, URL_OPTION, ADDRESS_A).json()['success'] is True

        assert run(provider, operation)['success'] is True
        assert len(transport.requests) == 1
        assert reached(transport.requests[0])[1:3] == (HOST_A, 9117)
        assert PLACEHOLDER_KEY in transport.requests[0]


class TestTheRefusalOverTheRealRoutes:
    """AC-DESIGN-5 (API error clause), AC-SEC-10 (response body), AC-OPS-10"""

    @pytest.mark.parametrize('route', sorted(ROUTE_OF.values()))
    def test_both_routes_answer_the_exact_text_and_the_body_carries_nothing_private(
            self, world, route):
        settings, client, provider, transport = world
        bind(client)
        save(client, URL_OPTION, ADDRESS_B)

        response = client.get(url(route=route), headers={'Origin': 'http://testserver'})

        assert response.status_code == 200
        body = response.json()
        assert body == {'success': False, 'error': REFUSAL}
        for value in (ADDRESS_A, ADDRESS_B, HOST_A, HOST_B, PLACEHOLDER_KEY):
            assert value not in response.text
        assert transport.requests == []

    def test_the_text_asks_for_the_address_check_first_and_names_nothing_internal(self):
        assert REFUSAL.index('Check the address') < REFUSAL.index('enter the API key again')
        for word in ('binding', 'fingerprint', 'normalis', 'Settings'):
            assert word not in REFUSAL

    def test_the_provider_serves_the_same_text_as_the_spec_fixes(self):
        assert torrentpotato_module.KEY_REFUSAL_TEXT == REFUSAL

    def test_AC_OPS_10_an_unbound_or_mismatched_key_does_not_touch_health_or_log_errors(
            self, world):
        settings, client, provider, transport = world
        bind(client)
        save(client, URL_OPTION, ADDRESS_B)

        with LogCapture() as logs:
            home = client.get('/')
            refused = [run(provider, 'jackettSync'), run(provider, 'jackettTest')]

        assert home.status_code < 500
        assert all(result['success'] is False for result in refused)
        assert logs.at_or_above(40) == []
        assert len(logs.at_or_above(30)) == 2, 'only the one WARNING per refused use'


@pytest.mark.parametrize('operation', OPERATIONS)
class TestEquivalentAddressesAreTheSameAddress:
    """AC-SEC-2, AC-QA-5"""

    @pytest.mark.parametrize('bound,used', [
        (ADDRESS_A, 'HTTP://SAVED-A.INVALID:9117'),
        (ADDRESS_A, ADDRESS_A + '/'),
        (ADDRESS_A, 'saved-a.invalid:9117'),
        ('http://saved-a.invalid', 'http://saved-a.invalid:80'),
        ('https://saved-a.invalid', 'https://saved-a.invalid:443/'),
        ('http://saved-a.invalid:9117/jackett', 'http://saved-a.invalid:9117/jackett/'),
        ('http://test-user:test-pass@saved-a.invalid:9117',
         'http://test-user:test-pass@saved-a.invalid:9117/'),
    ])
    def test_an_equivalent_form_is_accepted_and_reaches_the_bound_host(
            self, world, operation, bound, used):
        settings, client, provider, transport = world
        bind(client, bound)
        assert save(client, URL_OPTION, used).json()['success'] is True

        result = run(provider, operation)

        assert result['success'] is True
        assert len(transport.requests) == 1
        expected = parse_url(bound)
        scheme, host, port, path = reached(transport.requests[0])
        assert (scheme, host, port, path) == (
            expected.scheme, expected.host, expected.port, (expected.path or '').rstrip('/'))
        assert (parse_url(transport.requests[0]).auth) == expected.auth

    @pytest.mark.parametrize('label,refused', [
        ('userinfo naming the bound host', 'http://saved-a.invalid:9117@evil.invalid'),
        ('a backslash before the real host', r'http://evil.invalid\@saved-a.invalid:9117'),
        ('a backslash after the real host', r'http://saved-a.invalid:9117\@other/'),
        ('a fragment ahead of the bound host', 'http://other#@saved-a.invalid:9117'),
        ('a space before the real host', 'http://saved-a.invalid:9117 @other/'),
        ('a trailing-dot host', 'http://saved-a.invalid.:9117'),
        ('a fragment hiding a second host', 'http://saved-a.invalid:9117#@evil.invalid'),
        ('an internationalised host', 'http://bücher.example:9117'),
        ('a query the bound address did not carry', 'http://saved-a.invalid:9117?x=1'),
        ('an empty fragment', 'http://saved-a.invalid:9117/#'),
        ('a sibling host', 'http://sibling-a.invalid:9117'),
        ('a different path prefix', 'http://saved-a.invalid:9117/a'),
    ])
    def test_a_different_destination_is_refused_before_any_request(
            self, world, operation, label, refused):
        settings, client, provider, transport = world
        bind(client)
        assert save(client, URL_OPTION, refused).json()['success'] is True

        assert_refused(run(provider, operation))
        assert transport.requests == []

    @pytest.mark.parametrize('label,refused', [
        ('userinfo that reads as another host', r'http://test-user:test-pass@evil.invalid\@saved-a.invalid:9117'),
        ('other userinfo', 'http://other-user:test-pass@saved-a.invalid:9117'),
        ('the userinfo removed', ADDRESS_A),
    ])
    def test_when_the_bound_address_has_userinfo_only_the_same_userinfo_is_accepted(
            self, world, operation, label, refused):
        settings, client, provider, transport = world
        bind(client, 'http://test-user:test-pass@saved-a.invalid:9117')
        assert save(client, URL_OPTION, refused).json()['success'] is True

        assert_refused(run(provider, operation))
        assert transport.requests == []

    def test_an_address_that_has_no_normal_form_is_never_sent_to(self, world, operation):
        settings, client, provider, transport = world
        bind(client)
        assert save(client, URL_OPTION, 'localhost:99999').json()['success'] is True

        assert_refused(run(provider, operation))
        assert transport.requests == []

    def test_AC_SEC_2_the_string_checked_is_the_string_sent(self, world, operation):
        """The saved address is written differently from the bound one; the request carries the normal form."""
        settings, client, provider, transport = world
        bind(client)
        save(client, URL_OPTION, 'HTTP://SAVED-A.INVALID:9117/')

        run(provider, operation)

        assert transport.requests[0].startswith(ADDRESS_A + '/torznab/all/api?apikey=')


@pytest.mark.parametrize('operation', OPERATIONS)
class TestAnUnboundKeyIsRefused:
    """AC-SEC-3, AC-QA-13 (sync clauses), AC-DATA-6 (sync clauses), AC-QA-15 (sync clause)"""

    PRE_UPGRADE = 'a file from before this release: key and address, no binding option'
    AFTER_DEFAULTS = 'the same file after registerDefaults wrote the binding empty'

    def seed_pair(self, settings):
        """File-edit simulation of an older release: the saved pair with no binding."""
        settings.p.set(SECTION, URL_OPTION, ADDRESS_A)
        settings.p.set(SECTION, KEY_OPTION, PLACEHOLDER_KEY)
        settings.save()

    def test_a_pre_upgrade_file_with_no_binding_option_is_refused_as_unbound(self, world, operation):
        settings, client, provider, transport = world
        self.seed_pair(settings)
        remove_binding_option(settings)

        assert_refused(run(provider, operation))
        assert transport.requests == []

    def test_the_same_file_after_registerDefaults_wrote_the_binding_empty_is_refused(
            self, world, operation):
        settings, client, provider, transport = world
        self.seed_pair(settings)
        assert on_disk(settings, BINDING_OPTION) == ''
        before = sha(settings.file)

        assert_refused(run(provider, operation))
        assert transport.requests == []
        assert sha(settings.file) == before

    def test_no_key_is_the_required_error_and_not_an_unbound_key(self, world, operation):
        settings, client, provider, transport = world
        save(client, URL_OPTION, ADDRESS_A)

        result = run(provider, operation)

        assert result['success'] is False
        assert result['error'].startswith(REQUIRED)
        assert transport.requests == []

    @pytest.mark.parametrize('blank', ['   ', '\t', ' \n '])
    def test_a_key_saved_as_blanks_counts_as_no_key(self, world, operation, blank):
        settings, client, provider, transport = world
        bind(client)
        save(client, KEY_OPTION, blank)

        result = run(provider, operation)

        assert result['error'].startswith(REQUIRED)
        assert transport.requests == []

    @pytest.mark.parametrize('falsy', [0, False, None, []])
    def test_a_falsy_non_text_key_sends_nothing_before_or_after_a_restart(
            self, world, operation, falsy):
        settings, client, provider, transport = world
        save(client, URL_OPTION, ADDRESS_A)
        save_json(client, KEY_OPTION, falsy)

        assert run(provider, operation)['success'] is False
        assert transport.requests == []

    @pytest.mark.parametrize('label,saved', UNPARSEABLE[:4], ids=[row[0] for row in UNPARSEABLE[:4]])
    def test_AC_DATA_6_an_address_with_no_normal_form_binds_nothing_until_it_is_fixed_and_the_key_re_entered(
            self, world, operation, label, saved):
        settings, client, provider, transport = world
        save(client, URL_OPTION, saved)
        assert save(client, KEY_OPTION, PLACEHOLDER_KEY).json()['success'] is True
        assert on_disk(settings, BINDING_OPTION) == ''

        assert_refused(run(provider, operation))
        assert transport.requests == []

        save(client, URL_OPTION, ADDRESS_A)
        assert_refused(run(provider, operation))
        assert transport.requests == []

        save(client, KEY_OPTION, PLACEHOLDER_KEY)
        assert run(provider, operation)['success'] is True
        assert len(transport.requests) == 1

    def test_AC_QA_13_a_key_save_binds_the_unbound_install_and_the_sync_then_proceeds(
            self, world, operation):
        settings, client, provider, transport = world
        self.seed_pair(settings)
        assert_refused(run(provider, operation))

        save(client, KEY_OPTION, PLACEHOLDER_KEY)

        assert run(provider, operation)['success'] is True
        assert len(transport.requests) == 1

    def test_AC_QA_13_no_log_line_of_an_unbound_refusal_carries_a_value(self, world, operation):
        settings, client, provider, transport = world
        self.seed_pair(settings)

        with LogCapture() as logs:
            run(provider, operation)

        for value in (ADDRESS_A, HOST_A, PLACEHOLDER_KEY):
            assert value not in logs.text()

    def test_AC_QA_15_legacy_bytes_literal_values_are_refused_then_sent_unwrapped(
            self, world, operation):
        """File-edit simulation (AC-QA-15): both values in the `b'...'` wrapper of an older release, no binding."""
        settings, client, provider, transport = world
        settings.p.set(SECTION, URL_OPTION, "b'%s/'" % ADDRESS_A)
        settings.p.set(SECTION, KEY_OPTION, "b'placeholder-bytes-key'")
        settings.save()
        assert_refused(run(provider, operation))
        assert transport.requests == []

        save(client, KEY_OPTION, "b'placeholder-bytes-key'")

        assert on_disk(settings, BINDING_OPTION) == ADDRESS_A
        assert run(provider, operation)['success'] is True
        assert len(transport.requests) == 1
        assert transport.requests[0].startswith(ADDRESS_A + '/torznab/all/api?apikey=placeholder-bytes-key&')
        assert "b'" not in transport.requests[0]


@pytest.mark.parametrize('operation', OPERATIONS)
class TestClearingAndRebinding:
    """AC-SEC-7 (sync clauses), AC-SEC-6 (sync clauses), AC-DATA-1 (sync clause)"""

    def test_after_the_key_is_cleared_the_error_is_the_required_one_and_a_new_key_binds(
            self, world, operation):
        settings, client, provider, transport = world
        bind(client)
        save(client, KEY_OPTION, '')

        result = run(provider, operation)

        assert result['error'].startswith(REQUIRED)
        assert transport.requests == []
        save(client, KEY_OPTION, OTHER_KEY)
        assert run(provider, operation)['success'] is True
        assert OTHER_KEY in transport.requests[0]

    def test_with_the_key_still_saved_an_address_of_B_is_refused(self, world, operation):
        settings, client, provider, transport = world
        bind(client)
        save(client, URL_OPTION, ADDRESS_B)

        assert_refused(run(provider, operation))
        assert transport.requests == []

    def test_clearing_the_address_leaves_the_key_refused_not_sent_nowhere(self, world, operation):
        settings, client, provider, transport = world
        bind(client)
        save(client, URL_OPTION, '')

        result = run(provider, operation)

        assert result['success'] is False
        assert transport.requests == []

    @pytest.mark.parametrize('refused_save', ['mask', 'faulted_replace', 'url_alone', 'group_save'])
    def test_a_refused_or_failed_save_leaves_the_key_refused_at_B(
            self, world, operation, monkeypatch, refused_save):
        settings, client, provider, transport = world
        bind(client)
        save(client, URL_OPTION, ADDRESS_B)
        binding_before = memory(settings, BINDING_OPTION)
        if refused_save == 'mask':
            save(client, KEY_OPTION, '*' * len(PLACEHOLDER_KEY))
        elif refused_save == 'faulted_replace':
            import couchpotato.core.settings as settings_module

            def broken(src, dst):
                raise OSError('simulated write fault')
            with monkeypatch.context() as faulted:
                faulted.setattr(settings_module.os, 'replace', broken)
                assert save(client, KEY_OPTION, OTHER_KEY).json()['success'] is False
        elif refused_save == 'url_alone':
            for _ in range(3):
                save(client, URL_OPTION, ADDRESS_B)
        else:
            rows = three_rows(settings, SECTION)
            sent = client.post(url(route='settings.save_group'), json={'section': SECTION, 'rows': rows})
            assert sent.json()['success'] is True

        assert memory(settings, BINDING_OPTION) == binding_before
        assert_refused(run(provider, operation))
        assert transport.requests == []


@pytest.mark.parametrize('operation', OPERATIONS)
class TestAParametersAreNotCheckedAgainstTheBinding:
    """AC-SEC-9"""

    SUPPLIED = 'http://caller-supplied.invalid:9117'
    SUPPLIED_KEY = 'placeholder-callers-own-key'

    @pytest.fixture(params=['mismatched', 'empty', 'absent'])
    def binding_state(self, request, world):
        settings, client, provider, transport = world
        bind(client)
        if request.param == 'mismatched':
            save(client, URL_OPTION, ADDRESS_B)
        elif request.param == 'empty':
            # An address with no normal form at the key save leaves the binding empty (AC-DATA-6).
            save(client, URL_OPTION, 'localhost:99999')
            save(client, KEY_OPTION, PLACEHOLDER_KEY)
            save(client, URL_OPTION, ADDRESS_B)
            assert on_disk(settings, BINDING_OPTION) == ''
        else:
            remove_binding_option(settings)
        return request.param

    def test_its_own_url_and_key_go_out_once_and_the_saved_key_never_does(
            self, world, operation, binding_state):
        settings, client, provider, transport = world
        before = memory(settings, BINDING_OPTION)

        result = run(provider, operation, jackett_url=self.SUPPLIED, jackett_api_key=self.SUPPLIED_KEY)

        assert result['success'] is True
        assert len(transport.requests) == 1
        assert transport.requests[0].startswith(self.SUPPLIED + '/torznab/')
        assert self.SUPPLIED_KEY in transport.requests[0]
        assert PLACEHOLDER_KEY not in transport.requests[0]
        assert memory(settings, BINDING_OPTION) == before

    def test_its_own_key_alone_goes_to_the_saved_url_and_the_saved_key_never_does(
            self, world, operation, binding_state):
        settings, client, provider, transport = world
        saved_url = settings.p.get(SECTION, URL_OPTION)

        result = run(provider, operation, jackett_api_key=self.SUPPLIED_KEY)

        assert result['success'] is True
        assert len(transport.requests) == 1
        assert transport.requests[0].startswith(saved_url + '/torznab/')
        assert self.SUPPLIED_KEY in transport.requests[0]
        assert PLACEHOLDER_KEY not in transport.requests[0]

    def test_a_supplied_url_without_a_key_is_still_refused(self, world, operation, binding_state):
        settings, client, provider, transport = world

        result = run(provider, operation, jackett_url=self.SUPPLIED)

        assert result['success'] is False
        assert result['error'] != REFUSAL
        assert transport.requests == []


@pytest.mark.parametrize('operation', OPERATIONS)
class TestTheHappyPathAndTheSaveOrder:
    """AC-QA-1, AC-QA-11, AC-ARCH-9 (not-refused clause)"""

    def test_AC_QA_1_a_bound_key_goes_to_its_address_and_the_operation_behaves_as_before(
            self, world, operation):
        settings, client, provider, transport = world
        bind(client)

        result = run(provider, operation)

        assert result['success'] is True
        assert len(transport.requests) == 1
        assert reached(transport.requests[0]) == ('http', HOST_A, 9117, '')
        assert transport.requests[0].startswith(ADDRESS_A + '/torznab/all/api?apikey=' + PLACEHOLDER_KEY)
        if operation == 'jackettTest':
            assert result['count'] == 1
        else:
            assert result['added'] == 1
            assert on_disk(settings, 'pass_key') == PLACEHOLDER_KEY
            assert on_disk(settings, 'host') == ADDRESS_A + '/potato/%s/api' % ONE_INDEXER

    def test_AC_QA_11_order_A_address_then_key_sends_the_key_to_the_new_address(self, world, operation):
        settings, client, provider, transport = world
        bind(client)

        save(client, URL_OPTION, ADDRESS_B)
        save(client, KEY_OPTION, OTHER_KEY)

        assert run(provider, operation)['success'] is True
        assert reached(transport.requests[0])[1] == HOST_B
        assert OTHER_KEY in transport.requests[0]

    def test_AC_QA_11_order_B_key_then_address_is_refused_with_no_request(self, world, operation):
        settings, client, provider, transport = world
        bind(client)

        save(client, KEY_OPTION, OTHER_KEY)
        save(client, URL_OPTION, ADDRESS_B)

        assert_refused(run(provider, operation))
        assert transport.requests == []

    def test_AC_ARCH_9_the_wizards_order_with_a_delayed_address_save_is_not_refused(
            self, world, operation):
        """The wizard awaits the address save, then saves the key, then syncs."""
        settings, client, provider, transport = world
        bind(client)
        for address, key in ((ADDRESS_B, OTHER_KEY), ('http://third-c.invalid:9117', PLACEHOLDER_KEY)):
            assert save(client, URL_OPTION, address).json()['success'] is True
            assert save(client, KEY_OPTION, key).json()['success'] is True

            assert run(provider, operation)['success'] is True
            assert transport.requests[-1].startswith(address + '/torznab/')


class TestConcurrentSaves:
    """AC-QA-12, AC-DATA-1 (sync clause), AC-DATA-4"""

    def test_AC_QA_12_a_racing_address_and_key_save_never_sends_the_key_anywhere_else(self, world):
        settings, client, provider, transport = world
        bind(client)
        addresses = ('http://race-%d.invalid:9117' % n for n in itertools.count(1))
        for _ in range(50):
            address = next(addresses)
            barrier = threading.Barrier(2)

            def save_address():
                barrier.wait()
                settings.saveView(section=SECTION, name=URL_OPTION, value=address)

            def save_key():
                barrier.wait()
                settings.saveView(section=SECTION, name=KEY_OPTION, value=OTHER_KEY)

            workers = [threading.Thread(target=save_address), threading.Thread(target=save_key)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            transport.requests.clear()

            result = provider.jackettTest()

            bound = on_disk(settings, BINDING_OPTION)
            assert bound in (ADDRESS_A, address) or bound == ''
            if result['success']:
                assert len(transport.requests) == 1
                assert transport.requests[0].startswith(bound + '/torznab/')
                assert bound == address
            else:
                assert result['error'] == REFUSAL
                assert transport.requests == []
            bind(client)

    def test_AC_QA_12_an_address_save_waits_for_a_key_save_that_has_read_the_address(self, world):
        settings, client, provider, transport = world
        save(client, URL_OPTION, ADDRESS_A)
        paused, release = threading.Event(), threading.Event()
        addEvent('setting.save.torrentpotato.jackett_api_key',
                 lambda value: (paused.set(), release.wait(10)) and None)
        key_save = threading.Thread(
            target=lambda: settings.saveView(section=SECTION, name=KEY_OPTION, value=OTHER_KEY))
        address_save = threading.Thread(
            target=lambda: settings.saveView(section=SECTION, name=URL_OPTION, value=ADDRESS_B))
        key_save.start()
        assert paused.wait(10)

        address_save.start()
        address_save.join(timeout=0.5)
        blocked = address_save.is_alive()
        release.set()
        key_save.join(10)
        address_save.join(10)

        assert blocked, 'the address save did not wait for the key save'
        result = provider.jackettTest()
        if result['success']:
            assert reached(transport.requests[0])[1] == HOST_A
        else:
            assert_refused(result)
            assert transport.requests == []

    def test_AC_DATA_4_one_read_of_the_saved_address_serves_the_check_and_the_send(self, world):
        settings, client, provider, transport = world
        bind(client)
        real, reads = provider.conf, []

        def flapping(name, *args, **kwargs):
            if name == URL_OPTION:
                reads.append(name)
                return ADDRESS_A if len(reads) == 1 else ADDRESS_B
            return real(name, *args, **kwargs)
        provider.conf = flapping

        result = provider.jackettTest()

        assert result['success'] is True
        assert len(reads) == 1
        assert [reached(r)[1] for r in transport.requests] == [HOST_A]

    def test_AC_DATA_4_a_first_read_of_B_is_refused_and_A_is_never_reached_on_a_second_read(self, world):
        settings, client, provider, transport = world
        bind(client)
        real, reads = provider.conf, []

        def flapping(name, *args, **kwargs):
            if name == URL_OPTION:
                reads.append(name)
                return ADDRESS_B if len(reads) == 1 else ADDRESS_A
            return real(name, *args, **kwargs)
        provider.conf = flapping

        assert_refused(provider.jackettTest())
        assert transport.requests == []

    def test_AC_DATA_1_a_failed_key_save_leaves_the_old_pair_and_nothing_goes_to_the_new_address(
            self, world, monkeypatch):
        settings, client, provider, transport = world
        bind(client)
        save(client, URL_OPTION, ADDRESS_B)
        import couchpotato.core.settings as settings_module

        def broken(src, dst):
            raise OSError('simulated write fault')
        with monkeypatch.context() as faulted:
            faulted.setattr(settings_module.os, 'replace', broken)
            assert save(client, KEY_OPTION, OTHER_KEY).json()['success'] is False

        settings.addSection('core')
        settings.set('core', 'zz_later_unrelated', '1')
        settings.save()

        assert on_disk(settings, KEY_OPTION) == PLACEHOLDER_KEY
        assert on_disk(settings, BINDING_OPTION) == ADDRESS_A
        assert_refused(provider.jackettSync())
        assert transport.requests == []

    def test_the_key_save_still_holds_the_settings_lock_while_it_reads_the_address(self, world):
        settings, client, provider, transport = world
        save(client, URL_OPTION, ADDRESS_A)
        held = []
        addEvent('setting.save.torrentpotato.jackett_api_key',
                 lambda value: held.append(held_by_another_thread(_PASSWORD_SAVE_LOCK)))

        save(client, KEY_OPTION, PLACEHOLDER_KEY)

        assert held == [True]


class TestRestoreAndRollback:
    """AC-DATA-10 (restore and rollback cases): each runs on a copy of the file, and nothing is bound automatically."""

    def load_copy(self, tmp_path, monkeypatch, source, text_edit=None):
        """Start a fresh world over a COPY of `source` (a start-up, with `registerDefaults`)."""
        folder = tmp_path / ('copy-%d' % len(list(tmp_path.glob('copy-*'))))
        folder.mkdir()
        target = folder / 'config.ini'
        shutil.copyfile(source, target)
        if text_edit:
            target.write_text(text_edit(target.read_text(encoding='utf-8')), encoding='utf-8')
        return guarded_world(folder, monkeypatch)

    def test_a_restored_pre_release_file_is_unbound_and_its_sync_is_refused_until_the_key_is_entered(
            self, tmp_path, monkeypatch):
        """File-edit simulation: a backup taken before this release, with a key and an address and no binding option or flag."""
        legacy = tmp_path / 'legacy'
        legacy.mkdir()
        (legacy / 'config.ini').write_text(
            '[torrentpotato]\njackett_url = %s\njackett_api_key = %s\n' % (ADDRESS_A, PLACEHOLDER_KEY),
            encoding='utf-8')

        with guarded_world(legacy, monkeypatch) as (settings, client, provider, transport):
            assert on_disk(settings, BINDING_OPTION) == ''
            assert_refused(provider.jackettSync())
            assert transport.requests == []
            save(client, KEY_OPTION, PLACEHOLDER_KEY)
            assert provider.jackettSync()['success'] is True

    def test_an_address_edited_by_an_older_release_is_a_mismatch_after_re_upgrade(
            self, tmp_path, monkeypatch):
        """File-edit simulation: an older release edits `jackett_url` in the file and knows nothing of the binding."""
        origin = tmp_path / 'origin'
        origin.mkdir()
        with guarded_world(origin, monkeypatch) as (settings, client, provider, transport):
            bind(client)
            source = settings.file
        copy_dir = tmp_path / 'older-release'
        copy_dir.mkdir()
        edited = re.sub(r'(?m)^jackett_url = .*$', 'jackett_url = ' + ADDRESS_B,
                        open(source, encoding='utf-8').read())
        assert 'jackett_url = ' + ADDRESS_B in edited
        assert BINDING_OPTION + ' = ' + ADDRESS_A in edited
        (copy_dir / 'config.ini').write_text(edited, encoding='utf-8')

        with guarded_world(copy_dir, monkeypatch) as (settings, client, provider, transport):
            assert on_disk(settings, BINDING_OPTION) == ADDRESS_A
            assert_refused(provider.jackettSync())
            assert transport.requests == []
            assert on_disk(settings, BINDING_OPTION) == ADDRESS_A, 'a refusal never re-binds'

    def test_rolling_back_and_forward_with_nothing_changed_keeps_the_binding(self, tmp_path, monkeypatch):
        origin = tmp_path / 'origin'
        origin.mkdir()
        with guarded_world(origin, monkeypatch) as (settings, client, provider, transport):
            bind(client)
            source = settings.file
        again = tmp_path / 'forward'
        again.mkdir()
        shutil.copyfile(source, again / 'config.ini')

        with guarded_world(again, monkeypatch) as (settings, client, provider, transport):
            assert on_disk(settings, BINDING_OPTION) == ADDRESS_A
            assert provider.jackettSync()['success'] is True
            assert reached(transport.requests[0])[1] == HOST_A
            assert on_disk(settings, BINDING_OPTION) == ADDRESS_A
            assert on_disk(settings, KEY_OPTION) == PLACEHOLDER_KEY


class TestStoredRowsAreUntouchedByTheBinding:
    """AC-PROD-5, AC-PROD-7"""

    ROW_HOST = 'http://stored-row.invalid:9117/potato/alpha/api'
    ROW_KEY = 'placeholder-row-own-key'

    def stored(self):
        return {SECTION: {
            'use': '1', 'host': self.ROW_HOST, 'pass_key': self.ROW_KEY, 'name': 'Alpha',
            'seed_ratio': '1', 'seed_time': '40', 'extra_score': '0',
            'jackett_url': 'http://stored-row.invalid:9117', 'jackett_api_key': PLACEHOLDER_KEY}}

    def search_once(self, provider, transport):
        transport.body = '{"results": [{"torrent_id": "1", "release_name": "Film.2020", "download_url": "http://dl.invalid/1.torrent", "size": 1, "seeders": 5, "leechers": 1}]}'
        transport.requests.clear()
        media = {'identifiers': {'imdb': 'tt0000001'}, 'info': {'year': 2020, 'titles': ['Film']}}
        results = []  # the raw rows the provider would hand the release filter
        host = provider.getHosts()[0]
        provider._searchOnHost(host, media, None, results, manual=True)
        return results

    def test_AC_PROD_5_an_upgraded_install_searches_its_stored_row_with_the_rows_own_key_and_only_sync_is_refused(
            self, tmp_path, monkeypatch):
        """File-edit simulation: the file is an older release's, a saved pair and a synced row with no binding."""
        with guarded_world(tmp_path, monkeypatch, stored=self.stored()) as (settings, client, provider, transport):
            assert on_disk(settings, BINDING_OPTION) == ''

            results = self.search_once(provider, transport)

            assert len(transport.requests) == 1
            assert transport.requests[0].startswith(self.ROW_HOST + '?')
            assert 'passkey=' + self.ROW_KEY in transport.requests[0]
            assert PLACEHOLDER_KEY not in transport.requests[0]
            assert [row['name'] for row in results] == ['Film.2020']
            transport.requests.clear()
            assert_refused(provider.jackettSync())
            assert transport.requests == []

    def test_AC_PROD_7_a_search_is_the_same_request_before_and_after_an_address_change_and_never_refused(
            self, tmp_path, monkeypatch):
        with guarded_world(tmp_path, monkeypatch, stored=self.stored()) as (settings, client, provider, transport):
            save(client, KEY_OPTION, PLACEHOLDER_KEY)
            self.search_once(provider, transport)
            first = list(transport.requests)

            save(client, URL_OPTION, ADDRESS_B)
            assert_refused(provider.jackettTest())
            self.search_once(provider, transport)

            assert transport.requests == first
            assert len(first) == 1
            assert 'passkey=' + self.ROW_KEY in first[0]


class TestTheNormaliserIsTheCheckersToo:
    """AC-ARCH-5 (checker clauses)"""

    def test_the_writer_and_the_checker_both_call_the_one_normaliser(self, world, monkeypatch):
        settings, client, provider, transport = world
        seen = []
        real = torrentpotato_module.normalise_jackett_address

        def spy(value):
            seen.append(value)
            return real(value)
        monkeypatch.setattr(torrentpotato_module, 'normalise_jackett_address', spy)

        bind(client)
        written = len(seen)
        provider.jackettTest()

        assert written >= 1
        assert len(seen) > written, 'the checker did not call the shared normaliser'

    def test_a_no_value_answer_from_the_normaliser_is_unbound(self, world, monkeypatch):
        settings, client, provider, transport = world
        bind(client)
        monkeypatch.setattr(torrentpotato_module, 'normalise_jackett_address', lambda value: None)

        assert_refused(provider.jackettTest())
        assert transport.requests == []

    def test_the_checker_never_treats_an_empty_normal_form_as_matching_an_empty_binding(
            self, world, monkeypatch):
        settings, client, provider, transport = world
        bind(client)
        settings.set_internal(SECTION, BINDING_OPTION, '')
        monkeypatch.setattr(torrentpotato_module, 'normalise_jackett_address', lambda value: '')

        assert_refused(provider.jackettTest())
        assert transport.requests == []


class TestNothingGrows:
    """AC-OPS-11"""

    @staticmethod
    def option_names(settings):
        return {(section, option) for section in settings.p.sections() for option in settings.p.options(section)}

    def test_a_key_save_and_a_sync_add_no_option_name(self, world):
        settings, client, provider, transport = world
        after_startup = self.option_names(settings)
        assert (SECTION, BINDING_OPTION) in after_startup

        bind(client)
        provider.jackettSync()

        assert self.option_names(settings) == after_startup

    def test_start_up_names_only_declared_options_and_their_flags(self, tmp_path, monkeypatch):
        """File-edit simulation: a pre-release file holding the key and the address, loaded as a start-up does."""
        legacy = tmp_path / 'legacy'
        legacy.mkdir()
        (legacy / 'config.ini').write_text(
            '[torrentpotato]\njackett_url = %s\njackett_api_key = %s\n' % (ADDRESS_A, PLACEHOLDER_KEY),
            encoding='utf-8')
        declared = {option['name'] for section in torrentpotato_module.config
                    for group in section['groups'] for option in group['options']}

        with guarded_world(legacy, monkeypatch) as (settings, client, provider, transport):
            named = set(settings.p.options(SECTION))

        extras = named - declared
        assert BINDING_OPTION in declared
        assert extras <= {name + '_internal_meta' for name in declared}, 'an undeclared option was written'
        assert BINDING_OPTION + '_internal_meta' in extras
