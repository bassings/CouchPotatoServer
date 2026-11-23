"""SEC-006 P1c: the mechanism is generic, and the Jackett sync and the hold coexist.

* AC-ARCH-1: a synthetic combined option that declares `secret` and `address` is masked
  against (the refusal), kept, held, restored and revealed with no production edit.
* AC-QA-8 (second half): a Jackett sync, merge or replace, makes no entry and leaves
  earlier entries restorable.
* The restore-versus-eviction ordering: a restore is consumed before the same save's new
  holds can push entries out, so the oldest OTHER entry is the one that goes.
"""
import pytest

from couchpotato.core.settings import SECRET_MASK
from couchpotato.environment import Env
from tests.helpers.combine_groups import group_settings, snapshot, stored_group
from tests.helpers.jackett_binding import bind_saved_pair
from tests.unit.test_settings_keep_restore import (
    keep,
    keyed_rows,
    restore,
    seeded,
    token_of,
    two_secret_group,
    with_forms,
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


class TestASyntheticGroupNeedsNoProductionEdit:
    def rows(self, a='placeholder-a', b='placeholder-b'):
        return [{'use': '1', 'host': 'https://x.invalid', 'key_a': a, 'key_b': b},
                {'use': '1', 'host': 'https://y.invalid', 'key_a': 'placeholder-c', 'key_b': 'placeholder-d'}]

    def test_the_mask_is_refused_in_every_declared_secret_column_and_nowhere_else(self, settings):
        two_secret_group(settings)

        for column in ('key_a', 'key_b'):
            rows = self.rows()
            rows[0][column] = 'x' + SECRET_MASK
            result = settings.save_group('zz_two', rows)
            assert result['invalid'] == [{'row': 0, 'column': column, 'reason': 'masked_value'}]
        plain = self.rows()
        plain[0]['host'] = 'https://' + SECRET_MASK + '.invalid'
        assert settings.save_group('zz_two', plain) == {'success': True}

    def test_keep_hold_restore_and_a_reveal_style_read_all_work_per_column(self, settings):
        two_secret_group(settings)
        assert settings.save_group('zz_two', self.rows())['success']
        token = token_of(settings, 'zz_two')
        removed = settings.save_group('zz_two', [dict(self.rows()[0], key_a=keep(0), key_b=keep(0))], token)
        assert removed['success'] is True
        assert settings._hold.list_by_token('zz_two', token) == [('key_a', 1), ('key_b', 1)]

        restored = settings.save_group('zz_two', [
            dict(self.rows()[0], key_a=keep(0), key_b=keep(0)),
            dict(self.rows()[1], key_a=restore(token, 1), key_b=restore(token, 1))], removed['token'])

        assert restored['success'] is True
        assert settings.group_cells('zz_two')['key_a'] == ['placeholder-a', 'placeholder-c']
        assert settings.group_cells('zz_two')['key_b'] == ['placeholder-b', 'placeholder-d']
        current = restored['token']
        assert settings.reveal_cell('zz_two', 'key_b', 1, current) == {'success': True, 'value': 'placeholder-d'}
        assert settings.reveal_cell('zz_two', 'host', 1, current)['success'] is False
        assert settings.reveal_cell('zz_two', 'key_a', 0, removed['token'])['invalid'][0]['reason'] == 'stale'


class TestTheJackettSyncAndTheHold:
    @pytest.fixture
    def world(self, tmp_path, monkeypatch):
        jackett, key = 'http://jackett.invalid:9117', 'placeholder-jackett-key'
        stored = {'torrentpotato': {
            'use': '1,1,1', 'host': 'https://one.invalid/api,https://two.invalid/api,https://three.invalid/api',
            'pass_key': 'placeholder-pk-one,placeholder-pk-two,placeholder-pk-three', 'name': 'one,two,three',
            'seed_ratio': '1,1,1', 'seed_time': '40,40,40', 'extra_score': '0,0,0'}}
        with group_settings(tmp_path, monkeypatch, stored=stored) as live:
            monkeypatch.setattr(Env, '_settings', live)
            bind_saved_pair(live, jackett, key)
            from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
            provider = TorrentPotato.__new__(TorrentPotato)
            monkeypatch.setattr(provider, 'getJackettIndexers', lambda url, api_key, movies_only=True: ([
                {'id': 'alpha', 'title': 'Alpha', 'configured': True, 'supports_movies': True,
                 'potato_url': url.rstrip('/') + '/potato/alpha/api'}], None))
            yield live, provider

    def removed_row(self, live):
        """Remove the middle row with a token-carrying save; return the token it carried."""
        columns = live.combine_groups()['torrentpotato']
        rows = live.group_stored_rows('torrentpotato')
        token = token_of(live, 'torrentpotato')
        sent = [dict(rows[0], pass_key=keep(0)), dict(rows[2], pass_key=keep(2))]
        assert live.save_group('torrentpotato', sent, token)['success'] is True
        assert live._hold.peek('torrentpotato', 'pass_key', token, 1) == 'placeholder-pk-two'
        assert columns
        return token, rows

    @pytest.mark.parametrize('replace', [False, True])
    def test_a_sync_makes_no_entry_and_leaves_earlier_entries_restorable(self, world, replace):
        live, provider = world
        token, rows = self.removed_row(live)
        earlier = dict(live._hold._entries)

        result = provider.jackettSync(replace=replace)

        assert result['success'] is True
        assert live._hold._entries == earlier
        if replace:
            keys = live._stored_text('torrentpotato', 'pass_key').split(',')
            hosts = live._stored_text('torrentpotato', 'host').split(',')
            assert keys == ['placeholder-jackett-key'] * len(hosts), 'a replace sync writes the Jackett key into every row'
        current = token_of(live, 'torrentpotato')
        stored = live.group_stored_rows('torrentpotato')
        restoring = [dict(stored[0], pass_key=keep(0)), dict(rows[1], pass_key=restore(token, 1))]
        if replace:
            restoring = [dict(rows[1], pass_key=restore(token, 1))]
        outcome = live.save_group('torrentpotato', restoring, current)
        assert outcome['success'] is True, outcome
        assert 'placeholder-pk-two' in live._stored_text('torrentpotato', 'pass_key').split(',')

    def test_a_merge_sync_leaves_the_three_stored_keys_byte_identical_and_paired(self, world):
        live, provider = world
        before = stored_group(live.file, 'torrentpotato', ['host', 'pass_key'])

        assert provider.jackettSync()['success'] is True

        after = stored_group(live.file, 'torrentpotato', ['host', 'pass_key'])
        assert after['host'].split(',')[:3] == before['host'].split(',')
        assert after['pass_key'].split(',')[:3] == before['pass_key'].split(',')

    def test_a_sync_moves_the_token_so_a_page_that_read_before_it_is_refused(self, world):
        live, provider = world
        read_before = token_of(live, 'torrentpotato')
        provider.jackettSync()
        snap = snapshot(live, 'torrentpotato')

        result = live.save_group('torrentpotato', [dict(live.group_stored_rows('torrentpotato')[0],
                                                        pass_key=keep(0))], read_before)

        assert result['invalid'][0]['reason'] == 'stale'
        assert stored_group(live.file, 'torrentpotato', ['host'])['host'] == snap[1]['host']


class TestRestoreVersusEviction:
    def test_a_restore_is_consumed_before_the_same_saves_new_holds_can_evict_anything(self, settings):
        rows, token = seeded(settings, keys=['placeholder-p0', 'placeholder-p1', 'placeholder-p2',
                                              'placeholder-p3'])
        for number in range(4):                                    # the four OLDEST entries
            settings._hold.add('newznab', 'api_key', 'filler', number, 'filler-%d' % number)
        removed = settings.save_group('newznab', with_forms([rows[0], rows[2], rows[3]],
                                                            {0: keep(0), 1: keep(2), 2: keep(3)}), token)
        target = ('newznab', 'api_key', token, 1)
        assert settings._hold.peek(*target) == 'placeholder-p1'
        for number in range(4, 15):                                # newer than the target
            settings._hold.add('newznab', 'api_key', 'filler', number, 'filler-%d' % number)
        assert len([k for k in settings._hold._entries if k[0] == 'newznab']) == 16
        stored = settings.group_stored_rows('newznab')
        # Restore the target and replace every stored key: three new holds, none kept.
        sent = [dict(stored[0], api_key='typed-a'), dict(stored[0], host='https://r.invalid', api_key=restore(token, 1)),
                dict(stored[1], api_key='typed-b'), dict(stored[2], api_key='typed-c')]

        result = settings.save_group('newznab', sent, removed['token'])

        assert result['success'] is True
        assert settings.group_cells('newznab')['api_key'][1] == 'placeholder-p1'
        assert settings._hold.peek(*target) is None, 'the restored entry is consumed'
        mine = [k for k in settings._hold._entries if k[0] == 'newznab']
        assert len(mine) == 16, 'taking the restored entry first leaves room, so exactly two others go'
        assert ('newznab', 'api_key', 'filler', 0) not in settings._hold._entries
        assert ('newznab', 'api_key', 'filler', 1) not in settings._hold._entries
        assert ('newznab', 'api_key', 'filler', 2) in settings._hold._entries
        assert keyed_rows
