"""SEC-006 P1a: the mask constant and the refusal of any secret cell that contains it.

The settings read is still unmasked in this slice. The refusal ships first so
that, by the time the read is masked, a page that sends a mask back is refused
and the stored key survives (AC-QA-5). Only a SECRET column refuses it: a
non-secret column that holds the same characters is saved as it always was.

Every key here is a placeholder. The real-format keys (hex, alphanumeric,
punctuation, one with `*`) prove that no genuine key format is made unsaveable.
"""
import json
import string

import pytest

from couchpotato.core.settings import GROUP_REFUSAL_REASONS, SECRET_MASK
from tests.helpers.combine_groups import (
    assert_nothing_changed,
    group_settings,
    snapshot,
    stored_group,
    three_rows,
)

#: What JavaScript's String.prototype.trim removes (ECMAScript WhiteSpace and LineTerminator).
JS_TRIMMED = ('\u0009\u000a\u000b\u000c\u000d        '
              '          　﻿')


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def with_secret(settings, section, column, value, row=1):
    rows = three_rows(settings, section)
    rows[row][column] = value
    return rows


class TestTheMaskConstant:
    def test_equals_its_own_strip(self):
        assert SECRET_MASK == SECRET_MASK.strip()

    def test_survives_the_trim_a_browser_applies(self):
        assert SECRET_MASK == SECRET_MASK.strip(JS_TRIMMED)

    def test_has_no_whitespace_comma_or_control_character(self):
        assert not any(c.isspace() or c == ',' or ord(c) < 0x20 or ord(c) == 0x7f for c in SECRET_MASK)
        assert not set(SECRET_MASK) & set(JS_TRIMMED)

    def test_is_at_least_eight_characters(self):
        assert len(SECRET_MASK) >= 8

    def test_contains_a_non_ascii_character(self):
        assert any(ord(c) > 0x7f for c in SECRET_MASK)

    def test_is_not_made_only_of_characters_a_real_key_uses(self):
        assert not set(SECRET_MASK) <= set(string.printable)

    def test_survives_a_json_round_trip(self):
        assert json.loads(json.dumps(SECRET_MASK)) == SECRET_MASK
        assert json.loads(json.dumps(SECRET_MASK, ensure_ascii=False)) == SECRET_MASK

    def test_is_not_the_mask_every_other_credential_shows(self):
        # The page and the older read mask other credentials with asterisks; a real
        # pass key may contain one, so the constant must not be made of them.
        assert '*' not in SECRET_MASK

    def test_the_refusal_has_a_code_with_fixed_text(self):
        assert 'masked_value' in GROUP_REFUSAL_REASONS


class TestTheMaskIsRefusedAsASecretValue:
    @pytest.mark.parametrize('section, column', [('newznab', 'api_key'), ('torrentpotato', 'pass_key')])
    @pytest.mark.parametrize('shape', ['{m}', 'before{m}', '{m}after', 'a{m}b', '{m}{m}'])
    def test_any_string_containing_the_mask_is_refused(self, settings, section, column, shape):
        rows = with_secret(settings, section, column, shape.format(m=SECRET_MASK))
        before = snapshot(settings, section)

        result = settings.save_group(section, rows)

        assert result['success'] is False
        assert result['invalid'] == [{'row': 1, 'column': column, 'reason': 'masked_value'}]
        assert_nothing_changed(settings, section, before)

    def test_the_refusal_text_is_fixed_and_carries_no_submitted_text(self, settings):
        rows = with_secret(settings, 'newznab', 'api_key', 'canary-before' + SECRET_MASK)

        result = settings.save_group('newznab', rows)

        assert 'canary' not in json.dumps(result)
        assert result['error'] == ('A saved key was sent back as the dots shown in its place. '
                                   'Nothing was saved.')

    def test_the_stored_key_survives_the_refused_save(self, settings):
        good = three_rows(settings, 'newznab')
        assert settings.save_group('newznab', good)['success'] is True
        columns = settings.combine_groups()['newznab']
        before = stored_group(settings.file, 'newznab', columns)
        rows = [dict(row) for row in good]
        rows[0]['api_key'] = SECRET_MASK

        result = settings.save_group('newznab', rows)

        assert result['success'] is False
        assert stored_group(settings.file, 'newznab', columns) == before

    def test_the_trim_the_page_applies_to_a_masked_read_is_still_refused(self, settings):
        # The page splits the stored value on the comma and trims every cell
        # (`deriveGroupRows`), then trims again on send (`groupPayloadRows`). Play
        # exactly that over a masked column: one mask per non-empty cell, joined.
        masked_read = ','.join([SECRET_MASK, '', SECRET_MASK])
        cells = [cell.strip(JS_TRIMMED) for cell in masked_read.split(',')]
        rows = three_rows(settings, 'newznab')
        for row, cell in zip(rows, cells):
            row['api_key'] = cell.strip(JS_TRIMMED)

        result = settings.save_group('newznab', rows)

        assert result['success'] is False
        assert [p['row'] for p in result['invalid']] == [0, 2]
        assert {p['reason'] for p in result['invalid']} == {'masked_value'}

    def test_padding_around_the_mask_does_not_hide_it(self, settings):
        rows = with_secret(settings, 'newznab', 'api_key', '  ' + SECRET_MASK + '  ')

        assert settings.save_group('newznab', rows)['invalid'][0]['reason'] == 'masked_value'

    def test_other_problems_in_the_same_save_are_still_reported(self, settings):
        rows = with_secret(settings, 'newznab', 'api_key', SECRET_MASK)
        rows[2]['host'] = 'a,b'

        result = settings.save_group('newznab', rows)

        assert {(p['row'], p['column'], p['reason']) for p in result['invalid']} == {
            (1, 'api_key', 'masked_value'), (2, 'host', 'comma')}


class TestOnlyASecretColumnRefusesIt:
    def test_a_non_secret_column_of_a_credential_group_still_saves_the_same_text(self, settings):
        rows = with_secret(settings, 'newznab', 'custom_tag', 'tag' + SECRET_MASK)

        result = settings.save_group('newznab', rows)

        assert result == {'success': True}
        assert stored_group(settings.file, 'newznab', ['custom_tag'])['custom_tag'].split(',')[1] == (
            'tag' + SECRET_MASK)

    def test_the_other_groups_non_secret_column_still_saves_it(self, settings):
        rows = with_secret(settings, 'torrentpotato', 'name', SECRET_MASK)

        assert settings.save_group('torrentpotato', rows) == {'success': True}

    def test_the_other_groups_secret_is_not_confused_with_this_groups(self, settings):
        # `api_key` is not a column of torrentpotato and `pass_key` not of newznab: a
        # mask in the host column of either is plain text.
        rows = with_secret(settings, 'torrentpotato', 'host', 'https://h.invalid/' + SECRET_MASK)

        assert settings.save_group('torrentpotato', rows) == {'success': True}

    def test_a_group_with_no_secret_column_saves_it_as_on_master(self, settings):
        rows = three_rows(settings, 'imdb')
        rows[0]['automation_urls'] = 'https://l.invalid/' + SECRET_MASK

        assert settings.save_group('imdb', rows) == {'success': True}


class TestNoRealKeyFormatIsLockedOut:
    KEYS = {
        'thirty-two hex': '0123456789abcdef0123456789abcdef',
        'forty alphanumeric': 'Ab3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5hJ7k',
        'a pass key containing asterisks': 'pk*placeholder**key*',
        'only asterisks': '*****',
        'ascii punctuation': '!"#$%&\'()*+-./:;<=>?@[\\]^_`{|}~',
        'a short key': 'k',
        'non-ascii that is not the mask': 'päss-kéy-•',
    }

    @pytest.mark.parametrize('label', sorted(KEYS))
    @pytest.mark.parametrize('section, column', [('newznab', 'api_key'), ('torrentpotato', 'pass_key')])
    def test_the_key_saves_and_is_read_back_intact(self, settings, label, section, column):
        key = self.KEYS[label]
        rows = with_secret(settings, section, column, key)

        result = settings.save_group(section, rows)

        assert result == {'success': True}
        assert stored_group(settings.file, section, [column])[column].split(',')[1] == key

    def test_a_single_bullet_is_not_the_mask(self, settings):
        rows = with_secret(settings, 'newznab', 'api_key', '•')

        assert settings.save_group('newznab', rows) == {'success': True}


class TestRecordedLimitAStoredKeyThatAlreadyContainsTheMask:
    """A recorded limit (SEC-006, hard constraint 1), pinned so it cannot change unseen.

    Nothing on master writes eight consecutive U+2022, so no install should hold one.
    An install whose STORED key does has every save of that group, and a Jackett merge
    sync, refused as `masked_value` until the key is corrected in `config.ini`.
    """

    BAD = 'before' + SECRET_MASK + 'after'

    def test_every_save_of_that_group_is_refused_until_the_key_is_corrected(self, tmp_path, monkeypatch):
        stored = {'newznab': {'use': '1,1', 'host': 'https://a.invalid,https://b.invalid',
                              'api_key': self.BAD + ',placeholder-key-b', 'extra_score': '0,0',
                              'custom_tag': ','}}
        with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
            rows = settings.group_stored_rows('newznab')
            assert rows[0]['api_key'] == self.BAD
            before = snapshot(settings, 'newznab')

            result = settings.save_group('newznab', rows)

            assert result['success'] is False
            assert result['invalid'] == [{'row': 0, 'column': 'api_key', 'reason': 'masked_value'}]
            assert_nothing_changed(settings, 'newznab', before)

            settings.set('newznab', 'api_key', 'placeholder-key-a,placeholder-key-b')
            settings.save()
            assert settings.save_group('newznab', settings.group_stored_rows('newznab')) == {'success': True}

    def test_a_jackett_merge_sync_is_refused_too(self, tmp_path, monkeypatch):
        from couchpotato.environment import Env
        from tests.helpers.jackett_binding import bind_saved_pair
        stored = {'torrentpotato': {'use': '1', 'host': 'https://s.invalid/api', 'pass_key': self.BAD,
                                    'name': 's', 'seed_ratio': '1', 'seed_time': '40', 'extra_score': '0'}}
        with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
            monkeypatch.setattr(Env, '_settings', settings)
            bind_saved_pair(settings, 'http://jackett.invalid:9117', 'placeholder-jackett-key')
            from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
            provider = TorrentPotato.__new__(TorrentPotato)
            monkeypatch.setattr(provider, 'getJackettIndexers', lambda url, key, movies_only=True: ([
                {'id': 'alpha', 'title': 'Alpha', 'configured': True, 'supports_movies': True,
                 'potato_url': url + '/potato/alpha/api'}], None))
            before = snapshot(settings, 'torrentpotato')

            result = provider.jackettSync()

            assert result['success'] is False
            assert_nothing_changed(settings, 'torrentpotato', before)
