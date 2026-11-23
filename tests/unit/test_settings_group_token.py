"""SEC-006 P1a: the per-group freshness token.

`combine_state[section]['token']` is a MAC, under a random key held in this
process's memory only, over an unambiguous encoding of the section name, every
column name and every column's stored text. A save that carries a token is
refused as stale, with nothing written, when the group has changed since the
token was issued; a save that carries none behaves exactly as it always did.

Real `Settings` over a temporary `config.ini` with the real declarations. The
Jackett sync is the real provider method with only its network call replaced.
Every value is a placeholder.
"""
import hashlib
import hmac
import json
import logging
import threading

import pytest

from couchpotato.core import settings as settings_module
from couchpotato.core.settings import GROUP_REFUSAL_REASONS, Settings
from couchpotato.environment import Env
from tests.helpers.combine_groups import (
    LogCapture,
    assert_nothing_changed,
    memory_group,
    group_settings,
    placeholder_rows,
    sha,
    snapshot,
    stored_group,
    three_rows,
)
from tests.helpers.jackett_binding import bind_saved_pair


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def token_of(settings, section='newznab'):
    return settings.combine_state()[section]['token']


def saved(settings, section='newznab', tag='a'):
    """Write three distinct rows and return them."""
    rows = three_rows(settings, section, tag=tag)
    assert settings.save_group(section, rows)['success'] is True
    return rows


class TestWhereTheTokenAppears:
    @pytest.mark.parametrize('section', ['newznab', 'torrentpotato'])
    def test_a_group_with_a_secret_column_has_a_token_in_the_read(self, settings, section):
        entry = settings.view()['combine_state'][section]

        assert set(entry) == {'misaligned', 'rows', 'token'}
        assert isinstance(entry['token'], str)
        assert len(entry['token']) >= 32

    @pytest.mark.parametrize('section', ['imdb', 'itunes', 'letterboxd'])
    def test_a_group_with_no_secret_column_carries_no_token(self, settings, section):
        assert set(settings.view()['combine_state'][section]) == {'misaligned', 'rows'}


class TestTheTokenFollowsTheStoredGroup:
    def test_two_reads_with_no_write_between_agree(self, settings):
        saved(settings)

        assert token_of(settings) == token_of(settings)

    @pytest.mark.parametrize('column', ['use', 'host', 'api_key', 'extra_score', 'custom_tag'])
    def test_a_change_to_any_one_column_changes_it(self, settings, column):
        rows = saved(settings)
        before = token_of(settings)
        rows[1][column] = '0' if column == 'use' and rows[1][column] != '0' else (
            '7' if column == 'extra_score' else 'changed-' + column)

        assert settings.save_group('newznab', rows)['success'] is True

        assert token_of(settings) != before

    def test_a_key_replaced_by_one_of_equal_length_changes_it(self, settings):
        rows = saved(settings)
        before = token_of(settings)
        key = rows[1]['api_key']
        rows[1]['api_key'] = key[:-1] + ('x' if key[-1] != 'x' else 'y')
        assert len(rows[1]['api_key']) == len(key)

        settings.save_group('newznab', rows)

        assert token_of(settings) != before

    def test_a_write_to_another_section_does_not_change_it(self, settings):
        saved(settings, 'newznab')
        before = token_of(settings)

        saved(settings, 'torrentpotato')
        settings.addSection('core')
        settings.set('core', 'zz_unrelated', '1')
        settings.save()

        assert token_of(settings) == before

    def test_a_write_to_a_non_group_option_of_the_same_section_does_not_change_it(self, settings):
        saved(settings)
        before = token_of(settings)

        settings.set('newznab', 'zz_not_a_column', 'x')
        settings.save()

        assert token_of(settings) == before

    def test_a_legacy_bytes_literal_reads_as_the_text_the_provider_sees(self, settings):
        saved(settings)
        settings.set('newznab', 'custom_tag', "b'x,y,z'")
        before = token_of(settings)
        settings.set('newznab', 'custom_tag', 'x,y,z')

        assert token_of(settings) == before


class TestTheTokenIsKeyedAndUnambiguous:
    def test_two_instances_with_identical_groups_produce_different_tokens(self, tmp_path, monkeypatch):
        tokens = []
        rows = None
        for name in ('one', 'two'):
            (tmp_path / name).mkdir()
            with group_settings(tmp_path / name, monkeypatch) as live:
                rows = rows or three_rows(live, 'newznab')
                live.save_group('newznab', rows)
                assert sha(live.file)
                tokens.append((token_of(live), stored_group(live.file, 'newznab', ['host', 'api_key'])))

        assert tokens[0][1] == tokens[1][1], 'the two groups must hold identical text'
        assert tokens[0][0] != tokens[1][0]

    def test_it_is_not_an_unkeyed_hash_of_the_stored_columns(self, settings):
        saved(settings)
        columns = settings.combine_groups()['newznab']
        stored = [settings._stored_text('newznab', column) for column in columns]
        framed = settings._group_token_input('newznab', columns, stored)
        guesses = ['newznab' + ''.join(stored), 'newznab' + ','.join(stored),
                   'newznab\n' + '\n'.join(stored), ','.join(stored), ''.join(stored),
                   json.dumps(['newznab', *stored]), json.dumps(['newznab', list(columns), stored])]
        token = token_of(settings)

        for guess in guesses:
            for digest in (hashlib.sha256, hashlib.sha1, hashlib.md5, hashlib.sha512):
                assert digest(guess.encode()).hexdigest() != token
        # The strongest guess: the exact framed message, hashed with no key.
        for digest in (hashlib.sha256, hashlib.sha1, hashlib.md5, hashlib.sha512, hashlib.blake2b):
            assert digest(framed).hexdigest() != token
        assert hmac.digest(b'', framed, 'sha256').hex() != token

    def test_the_key_is_per_instance_and_never_on_disk_or_in_the_read(self, settings):
        saved(settings)
        key = settings._token_key

        assert isinstance(key, bytes)
        assert len(key) >= 32
        assert key.hex() not in json.dumps(settings.view())
        assert key not in open(settings.file, 'rb').read()
        assert Settings()._token_key != key

    def test_two_sections_with_identical_columns_produce_different_tokens(self, settings):
        # Same columns, same stored text, different section name.
        columns = ['use', 'host', 'secret_cell']
        for name in ('zz_one', 'zz_two'):
            settings.addOptions(name, {'name': name, 'groups': [{'options': [
                {'name': 'use'}, {'name': 'host'}, {'name': 'secret_cell'},
                {'name': 'cells', 'type': 'combined', 'combine': columns,
                 'pairing': ['host', 'secret_cell', 'use'], 'secret': ['secret_cell'],
                 'address': ['host']}]}]})
            settings.addSection(name)
            for column, text in zip(columns, ('1', 'h.invalid', 'k')):
                settings.set(name, column, text)

        assert token_of(settings, 'zz_one') != token_of(settings, 'zz_two')

    def test_two_states_splitting_the_same_text_across_columns_differ(self, settings):
        columns = ['use', 'host', 'secret_cell']
        settings.addOptions('zz_split', {'name': 'zz_split', 'groups': [{'options': [
            {'name': 'use'}, {'name': 'host'}, {'name': 'secret_cell'},
            {'name': 'cells', 'type': 'combined', 'combine': columns,
             'pairing': ['host', 'secret_cell', 'use'], 'secret': ['secret_cell'],
             'address': ['host']}]}]})
        settings.addSection('zz_split')

        def state(host, key):
            settings.set('zz_split', 'use', '1')
            settings.set('zz_split', 'host', host)
            settings.set('zz_split', 'secret_cell', key)
            return token_of(settings, 'zz_split')

        assert state('ab', 'c') != state('a', 'bc')
        assert state('', 'abc') != state('abc', '')
        assert state('a1', 'b') != state('a', '1b')

    def test_texts_that_collide_when_unframed_do_not_collide(self, settings):
        encode = settings._group_token_input
        # Unframed, both are `s` `a` `b` `b`: the boundary between the texts moved.
        assert encode('s', ['a', 'b'], ['b', '']) != encode('s', ['a', 'b'], ['', 'b'])
        assert encode('s', ['a', 'b'], ['bc', '']) != encode('s', ['a', 'b'], ['b', 'c'])
        assert encode('s', ['a', 'b'], ['x', 'yz']) != encode('sx', ['a', 'b'], ['', 'yz'])

    def test_a_text_that_contains_the_next_columns_name_does_not_collide_through_a_real_group(
            self, settings):
        columns = ['use', 'host', 'secret_cell']
        settings.addOptions('zz_name', {'name': 'zz_name', 'groups': [{'options': [
            {'name': 'use'}, {'name': 'host'}, {'name': 'secret_cell'},
            {'name': 'cells', 'type': 'combined', 'combine': columns,
             'pairing': ['host', 'secret_cell', 'use'], 'secret': ['secret_cell'],
             'address': ['host']}]}]})
        settings.addSection('zz_name')

        def state(use, host, key):
            for column, text in zip(columns, (use, host, key)):
                settings.set('zz_name', column, text)
            return token_of(settings, 'zz_name')

        # Unframed, both read use, 1, host, secret_cell, secret_cellz.
        assert state('1', '', 'secret_cellz') != state('1', 'secret_cell', 'z')

    def test_the_column_names_are_part_of_the_input(self, settings):
        # Same section, same texts, different names: not reachable on one instance, so
        # drive the encoder with the two name lists directly.
        encode = settings._group_token_input
        assert encode('s', ['a', 'bc'], ['x', 'y']) != encode('s', ['ab', 'c'], ['x', 'y'])

    def test_it_is_compared_with_compare_digest(self, settings, monkeypatch):
        saved(settings)
        seen = []
        real = hmac.compare_digest
        monkeypatch.setattr(settings_module.hmac, 'compare_digest',
                            lambda a, b: seen.append((a, b)) or real(a, b))
        rows = three_rows(settings, 'newznab', tag='b')

        settings.save_group('newznab', rows, token_of(settings))

        assert seen
        assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in seen)


class TestASaveThatCarriesAToken:
    def test_a_current_token_is_accepted_and_the_reply_carries_the_fresh_one(self, settings):
        saved(settings)
        old = token_of(settings)
        rows = three_rows(settings, 'newznab', tag='b')

        result = settings.save_group('newznab', rows, old)

        assert result['success'] is True
        assert set(result) == {'success', 'token'}
        assert result['token'] == token_of(settings) != old

    def test_two_consecutive_saves_each_built_on_the_previous_reply_both_land(self, settings):
        saved(settings)
        first = settings.save_group('newznab', three_rows(settings, 'newznab', tag='b'), token_of(settings))
        second = settings.save_group('newznab', three_rows(settings, 'newznab', tag='c'), first['token'])

        assert second['success'] is True
        assert stored_group(settings.file, 'newznab', ['host'])['host'].split(',')[0].startswith(
            'https://placeholder-c-0')

    @pytest.mark.parametrize('intervening', ['use', 'host', 'api_key', 'extra_score', 'custom_tag'])
    def test_a_stale_token_is_refused_with_nothing_written(self, settings, intervening):
        rows = saved(settings)
        stale = token_of(settings)
        rows[0][intervening] = '0' if intervening == 'use' else (
            '9' if intervening == 'extra_score' else 'moved-' + intervening)
        assert settings.save_group('newznab', rows)['success'] is True
        before = snapshot(settings, 'newznab')

        result = settings.save_group('newznab', three_rows(settings, 'newznab', tag='z'), stale)

        assert result['success'] is False
        assert result['invalid'] == [{'row': None, 'column': None, 'reason': 'stale'}]
        assert 'token' not in result
        assert_nothing_changed(settings, 'newznab', before)

    @pytest.mark.parametrize('bad', ['', 'not-a-token', 'A' * 64, '0' * 64, True, 123, ['x'], {'a': 1}])
    def test_a_token_that_does_not_match_is_refused_whatever_its_shape(self, settings, bad):
        saved(settings)
        before = snapshot(settings, 'newznab')

        result = settings.save_group('newznab', three_rows(settings, 'newznab', tag='z'), bad)

        assert result['success'] is False
        assert result['invalid'][0]['reason'] == 'stale'
        assert_nothing_changed(settings, 'newznab', before)

    def test_the_other_groups_token_is_not_accepted(self, settings):
        saved(settings, 'newznab')
        saved(settings, 'torrentpotato')

        result = settings.save_group('newznab', three_rows(settings, 'newznab', tag='z'),
                                     token_of(settings, 'torrentpotato'))

        assert result['invalid'][0]['reason'] == 'stale'

    def test_a_token_for_a_group_with_no_secret_column_is_refused_with_its_own_reason(self, settings):
        before = snapshot(settings, 'imdb')

        result = settings.save_group('imdb', three_rows(settings, 'imdb'), 'a' * 64)

        assert result['invalid'] == [{'row': None, 'column': None, 'reason': 'token_unexpected'}]
        assert result['error'] == 'This group does not use a token. Nothing was saved.'
        assert 'Reload' not in result['error']
        assert_nothing_changed(settings, 'imdb', before)

    def test_a_validation_refusal_is_reported_with_a_current_token_and_carries_no_token(self, settings):
        saved(settings)
        rows = three_rows(settings, 'newznab', tag='b')
        rows[0]['host'] = 'a,b'

        result = settings.save_group('newznab', rows, token_of(settings))

        assert result['invalid'][0]['reason'] == 'comma'
        assert 'token' not in result

    def test_stale_is_a_registered_refusal_code_with_fixed_text(self, settings):
        assert 'stale' in GROUP_REFUSAL_REASONS
        saved(settings)

        result = settings.save_group('newznab', three_rows(settings, 'newznab', tag='b'), 'x')

        assert result['error'] == ('The rows changed after this page loaded them. '
                                   'Nothing was saved. Reload to see the current rows.')

    def test_a_write_landing_between_the_request_and_the_write_is_refused(self, settings, monkeypatch):
        """A write made at the earliest point outside the lock must still be caught."""
        rows = saved(settings)
        stale = token_of(settings)
        intruder = [dict(row, custom_tag='intruder') for row in rows]
        original = Settings.save_group
        fired = []

        def intrude_then_save(self, section, rows_, token=None):
            if not fired:
                fired.append(True)
                original(self, section, intruder)
            return original(self, section, rows_, token)

        monkeypatch.setattr(Settings, 'save_group', intrude_then_save)

        result = settings.save_group('newznab', three_rows(settings, 'newznab', tag='z'), stale)

        assert result['success'] is False
        assert result['invalid'][0]['reason'] == 'stale'
        assert stored_group(settings.file, 'newznab', ['custom_tag'])['custom_tag'] == (
            ','.join(['intruder'] * 3))

    def test_two_saves_released_together_on_one_token_land_exactly_one(self, settings):
        saved(settings)
        for attempt in range(20):
            token = token_of(settings)
            barrier = threading.Barrier(2)
            outcomes = []

            def send(tag):
                barrier.wait(5)
                outcomes.append(settings.save_group(
                    'newznab', three_rows(settings, 'newznab', tag='%s%d' % (tag, attempt)), token)['success'])

            threads = [threading.Thread(target=send, args=(tag,)) for tag in ('p', 'q')]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)

            assert sorted(outcomes) == [False, True], 'attempt %d: %r' % (attempt, outcomes)


class TestNothingAfterTheWriteCanReportFailure:
    """A step after `_write_group` must never restore the group or say it failed."""

    def test_a_failing_reply_token_leaves_a_success_reply_and_one_state_in_memory_and_on_disk(
            self, settings, monkeypatch):
        saved(settings)
        token = token_of(settings)
        columns = settings.combine_groups()['newznab']
        real = Settings._group_token
        calls = []

        def flaky(self, section):
            calls.append(section)
            if len(calls) > 1:  # the first call is the freshness check, the second the reply
                raise RuntimeError('canary-held-text')
            return real(self, section)

        monkeypatch.setattr(Settings, '_group_token', flaky)

        with LogCapture() as logs:
            result = settings.save_group('newznab', three_rows(settings, 'newznab', tag='b'), token)

        assert result == {'success': True}
        assert len(calls) == 2
        on_disk = stored_group(settings.file, 'newznab', columns)
        assert memory_group(settings, 'newznab', columns) == on_disk
        assert on_disk['host'].split(',')[0] == 'https://placeholder-b-0.invalid/path'
        assert 'RuntimeError' in logs.text()
        assert 'canary-held-text' not in logs.text()
        monkeypatch.setattr(Settings, '_group_token', real)
        settings.addSection('core')
        settings.set('core', 'zz_later_unrelated', '1')
        settings.save()
        assert stored_group(settings.file, 'newznab', columns) == on_disk, (
            'a later unrelated save wrote the old rows back')


class TestASaveWithNoTokenIsAsOnMaster:
    def test_the_reply_is_exactly_success_true(self, settings):
        assert settings.save_group('newznab', three_rows(settings, 'newznab')) == {'success': True}

    def test_it_is_accepted_whatever_changed_in_between(self, settings):
        saved(settings)
        assert settings.save_group('newznab', three_rows(settings, 'newznab', tag='b')) == {'success': True}

    def test_a_token_of_none_is_no_token(self, settings):
        assert settings.save_group('newznab', three_rows(settings, 'newznab'), None) == {'success': True}


class TestABuilderSaveMovesTheToken:
    @pytest.fixture
    def world(self, tmp_path, monkeypatch):
        jackett, key = 'http://jackett.invalid:9117', 'placeholder-jackett-key'
        stored = {'torrentpotato': {
            'use': '1,0', 'host': 'https://stored-one.invalid/api,https://stored-two.invalid/api',
            'pass_key': 'placeholder-stored-key-one,placeholder-stored-key-two',
            'name': 'one,two', 'seed_ratio': '1,1', 'seed_time': '40,40', 'extra_score': '0,0'}}
        with group_settings(tmp_path, monkeypatch, stored=stored) as live:
            monkeypatch.setattr(Env, '_settings', live)
            bind_saved_pair(live, jackett, key)
            from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
            provider = TorrentPotato.__new__(TorrentPotato)

            def fetch(url, api_key, movies_only=True):
                base = url.rstrip('/')
                return [{'id': 'alpha', 'title': 'Alpha', 'configured': True, 'supports_movies': True,
                         'potato_url': '%s/potato/alpha/api' % base}], None

            monkeypatch.setattr(provider, 'getJackettIndexers', fetch)
            yield live, provider

    def test_the_real_jackett_sync_changes_the_token(self, world):
        live, provider = world
        before = token_of(live, 'torrentpotato')

        assert provider.jackettSync()['success'] is True

        assert token_of(live, 'torrentpotato') != before

    def test_a_page_that_read_before_the_sync_is_refused_after_it(self, world):
        live, provider = world
        read_before_sync = token_of(live, 'torrentpotato')
        provider.jackettSync()
        snap = snapshot(live, 'torrentpotato')

        result = live.save_group('torrentpotato', placeholder_rows(
            live.combine_groups()['torrentpotato'], 2), read_before_sync)

        assert result['invalid'][0]['reason'] == 'stale'
        assert_nothing_changed(live, 'torrentpotato', snap)


class TestTheTokenIsNeverLogged:
    def test_no_log_record_holds_a_token_across_a_read_a_save_and_a_stale_refusal(self, settings):
        with LogCapture() as logs:
            rows = saved(settings)
            first = token_of(settings)
            changed = [dict(row, custom_tag='changed') for row in rows]
            accepted = settings.save_group('newznab', changed, first)  # changes the group
            assert accepted['success'] is True
            # `first` is now stale because the SERVER's own save changed the group.
            stale = settings.save_group('newznab', rows, first)
            assert stale['invalid'][0]['reason'] == 'stale'
            settings.save_group('newznab', rows, 'caller-supplied-token\nforged line')
            tokens = {first, accepted['token'], token_of(settings), token_of(settings, 'torrentpotato'),
                      'caller-supplied-token', 'forged line'}

        text = logs.text()
        assert 'reason=stale' in text
        assert all(token not in text for token in tokens)
        assert settings._token_key.hex() not in text
        assert not any('\n' in record.getMessage() for record in logs.at_or_above(logging.WARNING))
