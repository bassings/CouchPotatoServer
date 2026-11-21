"""SEC-004 P2 fix: a legacy bytes-literal value is read as `Settings.get()` reads it.

An old configuration can hold a value written as a Python bytes literal, such as
``host = b'https://stored.invalid/api'``. ``Settings.get()`` strips that wrapper
(``_coerce_value``), so master's ``getHosts()`` saw the real value. The group
readers read the raw parser value, so a merge sync that appended a row wrote
``b'key',placeholder-key-two``: the wrapper could then no longer be stripped (the
whole value no longer ends with the quote) and ``getHosts()`` returned ``b'key``
as the old credential, while the sync reported success.

Hosts are ``.invalid`` and every credential is a ``placeholder-`` string.
"""
import os

import pytest

from couchpotato.environment import Env
from tests.helpers.combine_groups import (
    assert_nothing_changed,
    group_settings,
    reader_view,
    sha,
    snapshot,
    stored_group,
)
from tests.helpers.jackett_binding import bind_saved_pair

JACKETT = 'http://jackett.invalid:9117'
JACKETT_KEY = 'placeholder-jackett-key'
COLUMNS = ('use', 'host', 'pass_key', 'name', 'seed_ratio', 'seed_time', 'extra_score')


def wrapped(value):
    return "b'%s'" % value


ONE_ROW = {'use': '1', 'host': 'https://stored.invalid/api', 'pass_key': 'placeholder-stored-key',
           'name': 'stored-name', 'seed_ratio': '2', 'seed_time': '72', 'extra_score': '3'}
TWO_ROWS = {'use': '1,0', 'host': 'https://one.invalid/api,https://two.invalid/api',
            'pass_key': 'placeholder-key-one,placeholder-key-two', 'name': 'name-one,name-two',
            'seed_ratio': '1,2', 'seed_time': '40,50', 'extra_score': '0,5'}


def legacy(columns):
    return {column: wrapped(value) for column, value in columns.items()}


@pytest.fixture
def make_world(tmp_path, monkeypatch):
    def build(columns):
        stored = {'torrentpotato': dict(columns)}
        manager = group_settings(tmp_path, monkeypatch, stored=stored)
        settings = manager.__enter__()
        monkeypatch.setattr(Env, '_settings', settings)
        bind_saved_pair(settings, JACKETT, JACKETT_KEY)  # a bound key, through the production writer (AC-QA-20)
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        provider = TorrentPotato.__new__(TorrentPotato)
        monkeypatch.setattr(provider, 'getJackettIndexers', lambda url, key, movies_only=True: (
            [{'id': 'alpha', 'title': 'Alpha', 'potato_url': JACKETT + '/potato/alpha/api',
              'configured': True, 'supports_movies': True}], None))
        build.managers.append(manager)
        return settings, provider
    build.managers = []
    yield build
    for manager in build.managers:
        manager.__exit__(None, None, None)


def stored(settings):
    return stored_group(settings.file, 'torrentpotato', COLUMNS)


def cells(settings, column):
    return stored(settings)[column].split(',')


class TestAMergeSyncOverALegacyBytesLiteral:

    @pytest.mark.parametrize('columns', [ONE_ROW, TWO_ROWS], ids=['one row', 'two rows'])
    def test_the_stored_rows_keep_their_real_values_and_lose_the_wrapper(
            self, make_world, columns):
        settings, provider = make_world(legacy(columns))

        result = provider.jackettSync()

        assert result['success'] is True
        for column in COLUMNS:
            assert "b'" not in stored(settings)[column], '%s kept the wrapper' % column
        rows = len(columns['host'].split(','))
        assert cells(settings, 'host')[:rows] == columns['host'].split(',')
        assert cells(settings, 'pass_key')[:rows] == columns['pass_key'].split(',')
        assert cells(settings, 'name')[:rows] == columns['name'].split(',')
        assert cells(settings, 'seed_time')[:rows] == columns['seed_time'].split(',')
        assert cells(settings, 'host')[rows:] == [JACKETT + '/potato/alpha/api']

    @pytest.mark.parametrize('columns', [ONE_ROW, TWO_ROWS], ids=['one row', 'two rows'])
    def test_the_real_reader_pairs_each_host_with_its_own_key_afterwards(
            self, make_world, monkeypatch, columns):
        settings, provider = make_world(legacy(columns))

        provider.jackettSync()

        view = reader_view(settings, monkeypatch, 'torrentpotato')
        expected = list(zip(columns['host'].split(','), columns['pass_key'].split(',')))
        expected.append((JACKETT + '/potato/alpha/api', JACKETT_KEY))
        assert [(row[1], row[2]) for row in view] == expected

    def test_a_replace_sync_leaves_only_the_jackett_rows_without_a_wrapper(self, make_world):
        settings, provider = make_world(legacy(TWO_ROWS))

        result = provider.jackettSync(replace=True)

        assert result['success'] is True
        assert cells(settings, 'host') == [JACKETT + '/potato/alpha/api']
        for column in COLUMNS:
            assert "b'" not in stored(settings)[column]

    def test_a_failed_write_leaves_the_legacy_file_byte_identical_wrapper_included(
            self, make_world, monkeypatch):
        settings, provider = make_world(legacy(TWO_ROWS))
        before = snapshot(settings, 'torrentpotato')
        assert stored(settings)['host'].startswith("b'"), 'fixture: the wrapper is on disk'

        def no_space_left(*args, **kwargs):
            raise OSError(28, 'No space left on device')

        with monkeypatch.context() as patched:
            patched.setattr(os, 'replace', no_space_left)
            result = provider.jackettSync()

        assert result['success'] is False
        assert_nothing_changed(settings, 'torrentpotato', before)
        assert stored(settings)['pass_key'] == wrapped(TWO_ROWS['pass_key'])

    def test_a_refused_sync_leaves_the_legacy_file_byte_identical(self, make_world):
        columns = dict(TWO_ROWS, pass_key='placeholder-key-one')
        settings, provider = make_world(legacy(columns))
        file_before = sha(settings.file)

        result = provider.jackettSync()

        assert result['success'] is False
        assert sha(settings.file) == file_before


class TestTheGroupReadersNormaliseLikeGet:

    @pytest.mark.parametrize('value', [
        "b'https://a.invalid/api'",
        "b'https://a.invalid/api,https://b.invalid/api'",
        "b'a',b'b'",
        "b''",
        "b'",
        "plain,value",
        "b'unterminated",
        "xb'inside'",
    ])
    def test_every_column_reads_as_get_reads_it_split_into_cells(self, make_world, value):
        settings, _ = make_world({'host': value})

        assert settings.group_cells('torrentpotato')['host'] == settings.get(
            'host', section='torrentpotato').split(',')

    @pytest.mark.parametrize('aligned', [True, False])
    def test_alignment_is_classified_as_for_the_same_values_unwrapped(
            self, make_world, tmp_path, aligned):
        columns = dict(TWO_ROWS)
        if not aligned:
            columns['pass_key'] = 'placeholder-key-one'
        settings, _ = make_world(legacy(columns))

        assert settings.group_misaligned('torrentpotato') is (not aligned)

    def test_the_rows_read_back_without_the_wrapper(self, make_world):
        settings, _ = make_world(legacy(TWO_ROWS))

        rows = settings.group_stored_rows('torrentpotato', {'use': '0'})

        assert [row['host'] for row in rows] == TWO_ROWS['host'].split(',')
        assert [row['pass_key'] for row in rows] == TWO_ROWS['pass_key'].split(',')
