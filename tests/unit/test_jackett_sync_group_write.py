"""SEC-004 P2, AC-SEC-9 / AC-DATA-9: the Jackett sync writes its rows as one validated group.

``jackettSync`` used to write the seven torrentpotato columns with seven
separate saves and no comma check, so a title such as ``A, B`` or a failure
between the saves left a pass_key stored against a host it was not entered for.
It now fetches the indexers first (lock free), then hands the P1 group writer a
builder that reads the stored rows and returns the merged rows under the lock.

The real provider reads and writes a real ``Settings`` over a temporary
``config.ini`` with the real option declarations. Only the network is replaced.
Hosts are ``.invalid`` and every credential is a ``placeholder-`` string.

Choice for a Jackett cell the file cannot hold (AC-SEC-9 leaves it open): that
indexer is SKIPPED and counted. A partial row is never written and one bad title
never blocks the others.
"""
import logging
import os
import threading

import pytest

from couchpotato.core import settings as settings_module
from couchpotato.environment import Env
from tests.helpers.combine_groups import (
    InstrumentedLock,
    LogCapture,
    assert_nothing_changed,
    group_settings,
    held_by_another_thread,
    reader_view,
    sha,
    snapshot,
    stored_group,
)

JACKETT = 'http://jackett.invalid:9117'
JACKETT_KEY = 'placeholder-jackett-key'
COLUMNS = ('use', 'host', 'pass_key', 'name', 'seed_ratio', 'seed_time', 'extra_score')

STORED = {
    'use': '1,0',
    'host': 'https://stored-one.invalid/api,https://stored-two.invalid/api',
    'pass_key': 'placeholder-stored-key-one,placeholder-stored-key-two',
    'name': 'stored-name-one,stored-name-two',
    'seed_ratio': '2.50,1',
    'seed_time': '72,40',
    'extra_score': '3,0',
}


def indexer(identifier, title):
    return {'id': identifier, 'title': title, 'potato_url': '%s/potato/%s/api' % (JACKETT, identifier),
            'configured': True, 'supports_movies': True}


@pytest.fixture
def world(tmp_path, monkeypatch):
    stored = {'torrentpotato': dict(STORED, jackett_url=JACKETT, jackett_api_key=JACKETT_KEY)}
    with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
        monkeypatch.setattr(Env, '_settings', settings)
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        provider = TorrentPotato.__new__(TorrentPotato)
        provider.fetched = []
        provider.indexers = [indexer('alpha', 'Alpha'), indexer('beta', 'Beta')]

        def fetch(url, key, movies_only=True):
            """Like the real call, the potato URL is built from the URL it was given."""
            provider.fetched.append((url, key))
            base = url.rstrip('/')
            return [dict(i, potato_url='%s/potato/%s/api' % (base, i['id']))
                    for i in provider.indexers], None

        monkeypatch.setattr(provider, 'getJackettIndexers', fetch)
        yield settings, provider


def columns(settings):
    return stored_group(settings.file, 'torrentpotato', COLUMNS)


def cells(settings, column):
    return columns(settings)[column].split(',')


class TestASuccessfulSync:

    def test_the_stored_rows_keep_their_cells_verbatim_and_the_new_rows_follow(self, world):
        settings, provider = world

        result = provider.jackettSync()

        assert result['success'] is True
        assert result['added'] == 2
        assert result['total'] == 4
        assert cells(settings, 'host') == [
            'https://stored-one.invalid/api', 'https://stored-two.invalid/api',
            JACKETT + '/potato/alpha/api', JACKETT + '/potato/beta/api']
        assert cells(settings, 'seed_ratio') == ['2.50', '1', '1', '1'], (
            'a stored cell is written back as it was stored, not re-formatted')
        assert cells(settings, 'name') == ['stored-name-one', 'stored-name-two', 'Alpha', 'Beta']
        assert cells(settings, 'pass_key') == [
            'placeholder-stored-key-one', 'placeholder-stored-key-two', JACKETT_KEY, JACKETT_KEY]

    def test_every_column_has_one_cell_per_row_and_the_real_reader_pairs_each_key_with_its_host(
            self, world, monkeypatch):
        settings, provider = world

        provider.jackettSync()

        assert {len(cells(settings, column)) for column in COLUMNS} == {4}
        view = reader_view(settings, monkeypatch, 'torrentpotato')
        assert [(row[1], row[2]) for row in view] == [
            ('https://stored-one.invalid/api', 'placeholder-stored-key-one'),
            ('https://stored-two.invalid/api', 'placeholder-stored-key-two'),
            (JACKETT + '/potato/alpha/api', JACKETT_KEY),
            (JACKETT + '/potato/beta/api', JACKETT_KEY)]

    def test_an_indexer_that_is_already_stored_is_not_added_twice(self, world):
        settings, provider = world
        provider.indexers = [indexer('alpha', 'Alpha')]
        provider.jackettSync()

        result = provider.jackettSync()

        assert result['added'] == 0
        assert cells(settings, 'host').count(JACKETT + '/potato/alpha/api') == 1

    def test_replace_keeps_nothing_that_was_stored(self, world):
        settings, provider = world

        result = provider.jackettSync(replace=True)

        assert result['success'] is True
        assert cells(settings, 'host') == [JACKETT + '/potato/alpha/api', JACKETT + '/potato/beta/api']
        assert {len(cells(settings, column)) for column in COLUMNS} == {2}

    @pytest.mark.parametrize('flag', [False, None, 'false', 'False', '0', '', 'no', 'off', ' ', 'maybe',
                                      0, 1, 2, 1.0, ['true'], ['1'], {'0': 'true'}, ('true',)])
    def test_a_replace_flag_that_is_not_plainly_true_does_not_replace(self, world, flag):
        settings, provider = world

        provider.jackettSync(replace=flag)

        assert 'https://stored-one.invalid/api' in cells(settings, 'host')

    @pytest.mark.parametrize('flag', [True, 'true', 'True', ' TRUE ', '1', 'yes', 'Yes', 'on', 'ON'])
    def test_a_replace_flag_that_says_true_replaces(self, world, flag):
        settings, provider = world

        provider.jackettSync(replace=flag)

        assert 'https://stored-one.invalid/api' not in cells(settings, 'host')

    @pytest.mark.parametrize('query', [
        {'replace[0]': 'false'}, {'replace[0]': 'true'}, {'replace[a]': 'true'},
        {'replace': '0'}, {'replace': 'no'}, {'replace': 'off'}, {'replace': 'false'},
    ])
    def test_a_query_that_is_not_plainly_replace_true_keeps_the_stored_rows(self, world, query):
        """Through the real parameter parser: `replace[0]=false` arrives as the
        list `['false']`, which is truthy."""
        from couchpotato.core.helpers.request import getParams
        settings, provider = world

        result = provider.jackettSync(**getParams(query))

        assert result['success'] is True
        assert 'https://stored-one.invalid/api' in cells(settings, 'host')

    @pytest.mark.parametrize('query', [{'replace': 'true'}, {'replace': '1'}, {'replace': 'yes'},
                                       {'replace': 'on'}])
    def test_a_query_that_says_replace_true_replaces(self, world, query):
        from couchpotato.core.helpers.request import getParams
        settings, provider = world

        provider.jackettSync(**getParams(query))

        assert 'https://stored-one.invalid/api' not in cells(settings, 'host')

    def test_the_blank_rows_of_the_shipped_defaults_are_not_carried_into_the_synced_group(
            self, tmp_path, monkeypatch):
        defaults = {'torrentpotato': {'jackett_url': JACKETT, 'jackett_api_key': JACKETT_KEY}}
        with group_settings(tmp_path, monkeypatch, stored=defaults) as settings:
            monkeypatch.setattr(Env, '_settings', settings)
            from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
            provider = TorrentPotato.__new__(TorrentPotato)
            monkeypatch.setattr(provider, 'getJackettIndexers',
                                lambda url, key, movies_only=True: ([indexer('alpha', 'Alpha')], None))
            assert settings.get('pass_key', section='torrentpotato') == ',', 'fixture: the shipped default'

            result = provider.jackettSync()

            assert result['success'] is True
            assert cells(settings, 'host') == [JACKETT + '/potato/alpha/api']
            assert {len(cells(settings, column)) for column in COLUMNS} == {1}


class TestOneWriteInOneHold:
    """AC-DATA-9"""

    def test_a_sync_is_one_file_write_and_one_save(self, world, monkeypatch):
        settings, provider = world
        replaced = []
        real_replace = os.replace
        monkeypatch.setattr(os, 'replace', lambda src, dst: replaced.append(dst) or real_replace(src, dst))
        saves = []
        real_save = settings.save
        monkeypatch.setattr(settings, 'save', lambda: saves.append(1) or real_save())

        provider.jackettSync()

        assert len(replaced) == 1
        assert len(saves) == 1

    def test_the_read_of_the_stored_rows_and_the_write_share_one_hold_of_the_lock(
            self, world, monkeypatch):
        settings, provider = world
        lock = InstrumentedLock()
        monkeypatch.setattr(settings_module, '_PASSWORD_SAVE_LOCK', lock)
        me = threading.get_ident()
        read_in_hold = []
        write_in_hold = []
        real_rows = settings.group_stored_rows
        real_replace = os.replace

        def spy_rows(*args, **kwargs):
            read_in_hold.append(lock.hold_of(me))
            return real_rows(*args, **kwargs)

        def spy_replace(src, dst):
            write_in_hold.append(lock.hold_of(me))
            return real_replace(src, dst)

        monkeypatch.setattr(settings, 'group_stored_rows', spy_rows)
        monkeypatch.setattr(os, 'replace', spy_replace)

        provider.jackettSync()

        assert len(write_in_hold) == 1
        assert write_in_hold[0] is not None, 'the file was written outside any hold'
        assert read_in_hold, 'the stored rows were never read'
        assert write_in_hold[0] in read_in_hold, (
            'the stored rows were read in a different hold from the one that wrote them')

    def test_a_value_changed_between_the_fetch_and_the_lock_survives_the_sync(self, world, monkeypatch):
        """The lost update: rows built before the writer takes the lock are stale
        by the time they are written. The change lands as the writer is entered,
        i.e. after the fetch and before the lock is taken."""
        settings, provider = world
        real_save_group = settings.save_group

        def other_writer_first(section, rows):
            settings.set('torrentpotato', 'pass_key',
                         'placeholder-rotated-key-one,placeholder-stored-key-two')
            settings.save()
            return real_save_group(section, rows)

        monkeypatch.setattr(settings, 'save_group', other_writer_first)

        result = provider.jackettSync()

        assert result['success'] is True
        assert cells(settings, 'pass_key')[:2] == ['placeholder-rotated-key-one',
                                                   'placeholder-stored-key-two']

    def test_the_fetch_happens_while_the_lock_is_free(self, world, monkeypatch):
        """A fetch under the lock would stall every other settings write for as
        long as Jackett takes to answer."""
        settings, provider = world
        lock = InstrumentedLock()
        monkeypatch.setattr(settings_module, '_PASSWORD_SAVE_LOCK', lock)
        held_during_fetch = []

        def fetch(url, key, movies_only=True):
            held_during_fetch.append(held_by_another_thread(lock))
            return [indexer('alpha', 'Alpha')], None

        monkeypatch.setattr(provider, 'getJackettIndexers', fetch)

        result = provider.jackettSync()

        assert result['success'] is True
        assert held_during_fetch == [False], 'the lock was held during the network fetch'

    def test_a_failed_write_with_replace_leaves_the_file_and_memory_as_they_were(
            self, world, monkeypatch):
        settings, provider = world
        before = snapshot(settings, 'torrentpotato')

        def no_space_left(*args, **kwargs):
            raise OSError(28, 'No space left on device')

        with monkeypatch.context() as patched:
            patched.setattr(os, 'replace', no_space_left)
            result = provider.jackettSync(replace=True)

        assert result['success'] is False
        assert_nothing_changed(settings, 'torrentpotato', before)
        assert 'Alpha' not in str(result)


class TestACellTheFileCannotHold:
    """AC-SEC-9: a comma or a control character in a Jackett title, id or key."""

    HOSTILE_TITLES = ['A, B', ',', 'A\nB', 'A\rB', 'A\tB', 'A\x00B', '\ud800x', None]

    @pytest.mark.parametrize('title', HOSTILE_TITLES)
    def test_that_indexer_is_skipped_the_others_are_written_and_the_columns_stay_aligned(
            self, world, title):
        settings, provider = world
        provider.indexers = [indexer('alpha', 'Alpha'), indexer('bad', title), indexer('beta', 'Beta')]

        result = provider.jackettSync()

        assert result['success'] is True
        assert result['added'] == 2
        assert result['skipped'] == 1
        assert {len(cells(settings, column)) for column in COLUMNS} == {4}
        assert cells(settings, 'name')[2:] == ['Alpha', 'Beta']
        assert 'bad' not in ''.join(columns(settings).values()), 'a partial row was written'

    def test_a_comma_in_an_indexer_id_is_skipped_too(self, world):
        settings, provider = world
        provider.indexers = [indexer('a,b', 'Alpha'), indexer('beta', 'Beta')]

        result = provider.jackettSync()

        assert (result['added'], result['skipped']) == (1, 1)
        assert {len(cells(settings, column)) for column in COLUMNS} == {3}
        assert cells(settings, 'pass_key')[2] == JACKETT_KEY, 'the new key sits at its own host'

    def test_the_stored_rows_are_untouched_by_the_skip(self, world):
        settings, provider = world
        provider.indexers = [indexer('bad', 'A, B')]

        provider.jackettSync()

        assert cells(settings, 'host')[:2] == ['https://stored-one.invalid/api',
                                               'https://stored-two.invalid/api']
        assert cells(settings, 'pass_key')[:2] == ['placeholder-stored-key-one',
                                                   'placeholder-stored-key-two']

    @pytest.mark.parametrize('jackett_url, jackett_key', [
        ('http://jackett.invalid:9117/a,b', JACKETT_KEY),
        (JACKETT, 'placeholder,key'),
        (JACKETT, 'placeholder\nkey'),
    ])
    def test_a_url_or_key_that_makes_every_row_unstorable_refuses_the_sync_unchanged(
            self, world, jackett_url, jackett_key):
        settings, provider = world
        before = snapshot(settings, 'torrentpotato')

        result = provider.jackettSync(jackett_url=jackett_url, jackett_api_key=jackett_key)

        assert result['success'] is False
        assert_nothing_changed(settings, 'torrentpotato', before)
        for private in (jackett_url, jackett_key, 'Alpha'):
            assert private not in str(result)

    def test_nothing_that_was_skipped_is_logged_or_returned_by_title(self, world):
        settings, provider = world
        provider.indexers = [indexer('alpha', 'Alpha'), indexer('bad', 'Secret, Title')]

        with LogCapture() as logs:
            result = provider.jackettSync()

        assert 'Secret' not in logs.text() + str(result)
        assert JACKETT_KEY not in logs.text()


class TestTheWriterRefusesWhatTheBuilderReturned:
    """The writer is the one validator: a refusal it makes is relayed."""

    def test_a_stored_cell_the_writer_refuses_fails_the_sync_with_the_file_unchanged(self, world):
        settings, provider = world
        settings.set('torrentpotato', 'name', 'stored-name-one,bad\x01name')
        settings.save()
        before = snapshot(settings, 'torrentpotato')

        with LogCapture() as logs:
            result = provider.jackettSync()

        assert result['success'] is False
        assert_nothing_changed(settings, 'torrentpotato', before)
        warnings = [r for r in logs.at_or_above(logging.WARNING) if 'settings group' in r.getMessage()]
        assert len(warnings) == 1, 'the writer logs one line per refusal and the sync adds none'
        assert 'bad' not in logs.text()


class TestNoPerColumnWriterRemains:
    """AC-DATA-10, the runtime half: a sync never calls the per-column setting."""

    def test_a_sync_never_writes_a_column_through_conf(self, world, monkeypatch):
        settings, provider = world
        written = []
        real_conf = type(provider).conf

        def watching_conf(self, attr, value=None, default=None, section=None):
            if value is not None:
                written.append(attr)
            return real_conf(self, attr, value=value, default=default, section=section)

        monkeypatch.setattr(type(provider), 'conf', watching_conf)

        provider.jackettSync()

        assert written == []


MISALIGNED = dict(STORED, pass_key='placeholder-key-two,placeholder-key-three',
                  host='https://p1.invalid/api,https://p2.invalid/api,https://p3.invalid/api',
                  use='1,1,1', name='n1,n2,n3', seed_ratio='1,1,1', seed_time='40,40,40',
                  extra_score='0,0,0')


@pytest.fixture
def misaligned_world(tmp_path, monkeypatch):
    """The stored group the gate reviewer measured: three hosts, two pass_keys."""
    stored = {'torrentpotato': dict(MISALIGNED, jackett_url=JACKETT, jackett_api_key=JACKETT_KEY)}
    with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
        monkeypatch.setattr(Env, '_settings', settings)
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        provider = TorrentPotato.__new__(TorrentPotato)
        requested = []
        xml = '<indexers><indexer id="alpha" configured="true"><title>Alpha</title></indexer></indexers>'
        monkeypatch.setattr(provider, 'urlopen', lambda url, **kwargs: requested.append(url) or xml)
        yield settings, provider, requested


class TestAMisalignedStoredGroup:
    """AC-SEC-9 rule (c). Measured on the old code: with `host` of P1,P2,P3 and
    `pass_key` of K2,K3 the sync returned success, wrote an aligned group with
    P1 paired to K2, and the notice disappeared."""

    def test_the_fixture_is_really_misaligned_for_the_real_reader(self, misaligned_world, monkeypatch):
        settings, _, _ = misaligned_world

        view = reader_view(settings, monkeypatch, 'torrentpotato')

        assert view[0][1:3] == ('https://p1.invalid/api', 'placeholder-key-two'), (
            'P1 is already paired with the key meant for P2')

    def test_a_merge_sync_is_refused_before_any_network_request_and_nothing_is_written(
            self, misaligned_world):
        settings, provider, requested = misaligned_world
        before = snapshot(settings, 'torrentpotato')

        result = provider.jackettSync()

        assert result['success'] is False
        assert requested == [], 'a request reached Jackett'
        assert 'Settings' in result['error'], 'the user is told where to fix the rows'
        assert_nothing_changed(settings, 'torrentpotato', before)

    def test_the_refusal_is_one_warning_and_carries_no_value(self, misaligned_world):
        settings, provider, _ = misaligned_world

        with LogCapture() as logs:
            result = provider.jackettSync()

        assert len(logs.at_or_above(logging.WARNING)) == 1
        for private in ('p1.invalid', 'placeholder-key', JACKETT_KEY, JACKETT, 'n1'):
            assert private not in logs.text() + str(result)

    def test_a_short_pass_key_column_and_a_short_use_column_are_both_refused(
            self, tmp_path, monkeypatch):
        for short in ('pass_key', 'use'):
            columns = dict(STORED, **{short: STORED[short].split(',')[0]})
            stored = {'torrentpotato': dict(columns, jackett_url=JACKETT, jackett_api_key=JACKETT_KEY)}
            (tmp_path / short).mkdir()
            with group_settings(tmp_path / short, monkeypatch, stored=stored) as settings:
                monkeypatch.setattr(Env, '_settings', settings)
                from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
                provider = TorrentPotato.__new__(TorrentPotato)
                monkeypatch.setattr(provider, 'getJackettIndexers',
                                    lambda *a, **k: pytest.fail('a request reached Jackett'))

                assert provider.jackettSync()['success'] is False, short

    def test_replace_is_allowed_and_replaces_every_row_from_jackett(self, misaligned_world):
        settings, provider, requested = misaligned_world

        result = provider.jackettSync(replace=True)

        assert result['success'] is True
        assert len(requested) == 1
        assert cells(settings, 'host') == [JACKETT + '/potato/alpha/api']
        assert {len(cells(settings, column)) for column in COLUMNS} == {1}

    def test_the_group_going_misaligned_after_the_pre_check_is_refused_under_the_lock(self, world):
        """Another writer can land between the pre-check and the lock. The
        builder asks the same question again, under the lock, and declines."""
        settings, provider = world
        fetch = provider.getJackettIndexers

        def fetch_then_a_writer_misaligns_the_group(url, key, movies_only=True):
            settings.set('torrentpotato', 'pass_key', 'placeholder-stored-key-one')
            settings.save()
            return fetch(url, key, movies_only)

        provider.getJackettIndexers = fetch_then_a_writer_misaligns_the_group
        with LogCapture() as logs:
            result = provider.jackettSync()

        assert result['success'] is False
        assert 'Settings' in result['error']
        assert 'Alpha' not in ''.join(columns(settings).values()), 'a row was written'
        assert cells(settings, 'host') == ['https://stored-one.invalid/api',
                                           'https://stored-two.invalid/api']
        assert len([r for r in logs.at_or_above(logging.WARNING)
                    if 'settings group' in r.getMessage()]) == 1

    def test_the_shipped_defaults_are_not_misaligned(self, tmp_path, monkeypatch):
        defaults = {'torrentpotato': {'jackett_url': JACKETT, 'jackett_api_key': JACKETT_KEY}}
        with group_settings(tmp_path, monkeypatch, stored=defaults) as settings:
            monkeypatch.setattr(Env, '_settings', settings)
            from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
            provider = TorrentPotato.__new__(TorrentPotato)
            monkeypatch.setattr(provider, 'getJackettIndexers',
                                lambda url, key, movies_only=True: ([indexer('alpha', 'Alpha')], None))

            assert provider.jackettSync()['success'] is True
