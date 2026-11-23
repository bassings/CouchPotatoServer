"""SEC-006 P1b: `keep`, `restore` and the hold of removed keys, on the real `Settings`.

A secret cell of a token-carrying `save_group` is a string, `{"keep": i}` (store what
cell `i` of this secret column holds now) or `{"restore": {"token": T, "row": i}}`
(store the text held when the save that carried token `T` left cell `i` unkept).
`i` always means cell `i` of the secret column, on aligned and misaligned groups.

Real `Settings` over a temporary `config.ini` with the real declarations. Every key
is a placeholder; hosts are `.invalid`.
"""
import json
import logging
import os
import threading

import pytest

from couchpotato.core import settings as settings_module
from couchpotato.core.settings import Settings
from tests.helpers.combine_groups import (
    LogCapture,
    assert_nothing_changed,
    group_settings,
    memory_group,
    placeholder_rows,
    reader_view,
    register_providers,
    snapshot,
    stored_group,
    three_rows,
)

KEYS = ['placeholder-key-zero', ' placeholder key one ', 'placeholder-key-two']


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def token_of(settings, section='newznab'):
    return settings.combine_state()[section]['token']


def keyed_rows(settings, keys=KEYS, section='newznab', tag='a', column='api_key'):
    rows = placeholder_rows(settings.combine_groups()[section], len(keys), tag=tag)
    for row, key in zip(rows, keys):
        row[column] = key
    return rows


def seeded(settings, keys=KEYS, section='newznab', column='api_key'):
    """Store `keys` with distinct hosts and return (rows, the token a page would hold)."""
    rows = keyed_rows(settings, keys, section, column=column)
    assert settings.save_group(section, rows)['success'] is True
    return rows, token_of(settings, section)


def keep(index):
    return {'keep': index}


def restore(token, row):
    return {'restore': {'token': token, 'row': row}}


def api_key_cells(settings):
    return stored_group(settings.file, 'newznab', ['api_key'])['api_key'].split(',')


def memory_key_cells(settings):
    """The cells as the parser holds them: a file read back strips whitespace at the very edges."""
    return settings._stored_text('newznab', 'api_key').split(',')


def host_key_map(settings):
    hosts = settings._stored_text('newznab', 'host').split(',')
    return dict(zip(hosts, memory_key_cells(settings)))


def with_forms(rows, forms):
    """`rows` with the `api_key` of row r replaced by forms[r] where given."""
    out = [dict(row) for row in rows]
    for position, cell in forms.items():
        out[position]['api_key'] = cell
    return out


def refusal(result, row, column, reason):
    assert result['success'] is False, result
    assert result['invalid'] == [{'row': row, 'column': column, 'reason': reason}], result


class TestKeepStoresTheCellAtThatIndex:
    def test_keeping_every_key_while_one_other_cell_changes_leaves_every_key_byte_identical(self, settings):
        rows, token = seeded(settings)
        before = api_key_cells(settings)
        changed = with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)})
        changed[1]['custom_tag'] = 'changed-tag'

        result = settings.save_group('newznab', changed, token)

        assert result['success'] is True
        assert api_key_cells(settings) == before == KEYS
        assert stored_group(settings.file, 'newznab', ['custom_tag'])['custom_tag'].split(',')[1] == 'changed-tag'

    def test_a_reorder_keeps_each_key_with_its_own_host(self, settings):
        rows, token = seeded(settings)
        original = host_key_map(settings)
        reordered = with_forms([rows[2], rows[0], rows[1]], {0: keep(2), 1: keep(0), 2: keep(1)})

        assert settings.save_group('newznab', reordered, token)['success'] is True

        assert host_key_map(settings) == original
        assert stored_group(settings.file, 'newznab', ['host'])['host'].split(',') == [
            rows[2]['host'], rows[0]['host'], rows[1]['host']]

    def test_removing_the_middle_row_keeps_the_other_two_pairings(self, settings):
        rows, token = seeded(settings)
        original = host_key_map(settings)
        remaining = with_forms([rows[0], rows[2]], {0: keep(0), 1: keep(2)})

        assert settings.save_group('newznab', remaining, token)['success'] is True

        assert host_key_map(settings) == {rows[0]['host']: original[rows[0]['host']],
                                          rows[2]['host']: original[rows[2]['host']]}

    def test_a_new_string_in_one_cell_is_stored_and_the_rest_are_kept(self, settings):
        rows, token = seeded(settings)
        changed = with_forms(rows, {0: keep(0), 1: 'brand-new-key', 2: keep(2)})

        assert settings.save_group('newznab', changed, token)['success'] is True

        assert api_key_cells(settings) == [KEYS[0], 'brand-new-key', KEYS[2]]

    def test_saving_only_row_b_with_keep_one_stores_row_b_and_its_key(self, settings):
        rows, token = seeded(settings)

        assert settings.save_group('newznab', with_forms([rows[1]], {0: keep(1)}), token)['success']

        assert stored_group(settings.file, 'newznab', ['host'])['host'] == rows[1]['host']
        assert memory_key_cells(settings) == [KEYS[1]]

    def test_swapping_two_rows_with_their_keys_stores_hostb_hosta_and_keyb_keya(self, settings):
        rows, token = seeded(settings, keys=KEYS[:2])
        swapped = with_forms([rows[1], rows[0]], {0: keep(1), 1: keep(0)})

        assert settings.save_group('newznab', swapped, token)['success'] is True

        assert stored_group(settings.file, 'newznab', ['host'])['host'] == (
            rows[1]['host'] + ',' + rows[0]['host'])
        assert memory_key_cells(settings) == [KEYS[1], KEYS[0]]

    def test_the_stored_key_of_an_empty_cell_keeps_as_an_empty_cell(self, settings):
        rows, token = seeded(settings, keys=['placeholder-a', '', 'placeholder-c'])

        assert settings.save_group('newznab', with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)}),
                                   token)['success']

        assert api_key_cells(settings) == ['placeholder-a', '', 'placeholder-c']

    def test_a_legacy_bytes_literal_column_keeps_what_the_provider_reads(self, settings, monkeypatch):
        rows, token = seeded(settings)
        settings.set('newznab', 'api_key', "b'k-one,k-two,k-three'")
        settings.save()
        token = token_of(settings)
        before = [row[2] for row in reader_view(settings, monkeypatch, 'newznab')]

        assert settings.save_group('newznab', with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)}),
                                   token)['success']

        assert [row[2] for row in reader_view(settings, monkeypatch, 'newznab')] == before
        assert before[:3] == ['k-one', 'k-two', 'k-three']

    def test_the_provider_reads_the_same_strings_before_and_after_a_keep_save(self, settings, monkeypatch):
        rows, token = seeded(settings)
        before = reader_view(settings, monkeypatch, 'newznab')

        assert settings.save_group('newznab', with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)}),
                                   token)['success']

        assert reader_view(settings, monkeypatch, 'newznab') == before


class TestKeepOnAMisalignedGroup:
    """`i` is the secret column's own cell index: the pairing the providers already use."""

    def test_three_hosts_and_two_keys_keep_both_keys_in_their_cells(self, tmp_path, monkeypatch):
        stored = {'newznab': {'use': '1,1,1', 'host': 'https://h0.invalid,https://h1.invalid,https://h2.invalid',
                              'api_key': 'placeholder-k0,placeholder-k1', 'extra_score': '0,0,0',
                              'custom_tag': ',,'}}
        with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
            assert settings.group_misaligned('newznab') is True
            before = reader_view(settings, monkeypatch, 'newznab')
            rows = settings.group_stored_rows('newznab')
            sent = with_forms(rows, {0: keep(0), 1: keep(1), 2: ''})

            result = settings.save_group('newznab', sent, token_of(settings))

            assert result['success'] is True
            assert api_key_cells(settings)[:2] == ['placeholder-k0', 'placeholder-k1']
            after = reader_view(settings, monkeypatch, 'newznab')
            assert [(row[1], row[2]) for row in after[:2]] == [(row[1], row[2]) for row in before[:2]]

    def test_no_branch_on_misalignment_exists_in_the_group_writer(self):
        import inspect
        source = inspect.getsource(Settings._save_group) + inspect.getsource(Settings._resolve_group_cells)
        assert 'group_misaligned' not in source


class Untouched:
    """A seeded group with one held entry, and a way to send a save that must refuse and change nothing.

    AC-DATA-1: a refused save leaves the file's bytes AND mtime, the parser, the hold and
    the log free of every fixture key and free of anything about the group it was refused for.
    """

    def __init__(self, settings):
        self.settings = settings
        self.rows, self.token = seeded(settings)
        settings._hold.add('newznab', 'api_key', 'earlier-save', 0, 'held-earlier-text')
        self.before = snapshot(settings, 'newznab')
        self.held = dict(settings._hold._entries)
        self.mtime = os.stat(settings.file).st_mtime_ns

    def refused(self, section, rows, token, reason, row=None, column=None):
        before = snapshot(self.settings, section) if section != 'newznab' else self.before
        held, mtime = dict(self.settings._hold._entries), os.stat(self.settings.file).st_mtime_ns
        with LogCapture() as logs:
            result = self.settings.save_group(section, rows, token)
        assert result['success'] is False, result
        assert result['invalid'][0]['reason'] == reason, result
        if row != 'any':
            assert result['invalid'][0]['row'] == row
            assert result['invalid'][0]['column'] == column
        assert self.settings._hold._entries == held, 'a refused save changed the hold'
        assert os.stat(self.settings.file).st_mtime_ns == mtime, 'a refused save touched the file'
        assert all(key.strip() not in json.dumps(result) + logs.text() for key in KEYS), 'a key leaked'
        assert_nothing_changed(self.settings, section, before)
        return result


class TestEveryShapeOfASecretCellRefusesTheWholeSave:
    @pytest.fixture
    def world(self, settings):
        return Untouched(settings)

    @pytest.mark.parametrize('bad', [
        {'keep': True}, {'keep': False}, {'keep': 1.5}, {'keep': '0'}, {'keep': None}, {'keep': -1},
        {'keep': [0]}, {'keep': {}}, {}, {'keep': 0, 'extra': 1}, {'keep': 0, 'restore': {'token': 'x', 'row': 0}},
        {'Keep': 0}, {'restore': 0}, {'restore': {}}, {'restore': {'token': 'x'}}, {'restore': {'row': 0}},
        {'restore': {'token': 'x', 'row': 0, 'extra': 1}}, {'restore': {'token': 5, 'row': 0}},
        {'restore': {'token': 'x', 'row': True}}, {'restore': {'token': 'x', 'row': -1}},
        {'restore': {'token': 'x', 'row': 1.0}}, {'restore': {'token': 'x', 'row': '0'}},
        {'restore': 'x'}, {'restore': None},
    ])
    def test_a_malformed_form_is_bad_reference_with_nothing_changed(self, world, bad):
        result = world.refused('newznab', with_forms(world.rows, {1: bad}), world.token,
                               'bad_reference', 1, 'api_key')

        assert 'held' not in result

    @pytest.mark.parametrize('index', [3, 4, 99, 2 ** 40])
    def test_an_index_at_or_beyond_the_secret_columns_cell_count_is_bad_reference(self, world, index):
        world.refused('newznab', with_forms(world.rows, {0: keep(index)}), world.token,
                      'bad_reference', 0, 'api_key')

    def test_the_last_cell_is_in_range_and_one_past_it_is_not(self, world):
        settings, rows, token = world.settings, world.rows, world.token

        assert settings.save_group('newznab', with_forms(rows, {0: keep(2)}), token)['success'] is True

    def test_two_cells_naming_the_same_index_are_refused(self, world):
        world.refused('newznab', with_forms(world.rows, {0: keep(1), 1: keep(1)}), world.token,
                      'bad_reference', 1, 'api_key')

    def test_two_cells_carrying_the_same_restore_reference_are_refused(self, world):
        world.settings._hold.add('newznab', 'api_key', 'earlier-save', 1, 'held-second-text')
        sent = with_forms(world.rows, {0: restore('earlier-save', 0), 1: restore('earlier-save', 0)})

        world.refused('newznab', sent, world.token, 'bad_reference', 1, 'api_key')

    def test_a_keep_in_a_non_secret_column_is_bad_reference(self, world):
        world.rows[0]['host'] = keep(0)

        world.refused('newznab', world.rows, world.token, 'bad_reference', 0, 'host')

    def test_a_restore_in_a_non_secret_column_is_bad_reference(self, world):
        world.rows[0]['custom_tag'] = restore(world.token, 0)

        world.refused('newznab', world.rows, world.token, 'bad_reference', 0, 'custom_tag')

    def test_a_non_form_object_in_a_non_secret_column_is_still_not_string(self, world):
        world.rows[0]['host'] = {'anything': 1}

        world.refused('newznab', world.rows, world.token, 'not_string', 0, 'host')

    def test_a_keep_in_a_group_with_no_secret_column_is_bad_reference(self, settings):
        rows = three_rows(settings, 'imdb')
        before = snapshot(settings, 'imdb')
        rows[0]['automation_urls'] = keep(0)

        for token in (None, 'x' * 64):
            result = settings.save_group('imdb', rows, token)
            assert result['success'] is False
            assert result['invalid'][0]['reason'] == 'bad_reference'
        assert_nothing_changed(settings, 'imdb', before)

    def test_a_keep_with_no_token_is_token_missing(self, world):
        world.refused('newznab', with_forms(world.rows, {0: keep(0)}), None, 'token_missing')

    def test_a_restore_with_no_token_is_token_missing_when_the_entry_exists(self, world):
        world.settings._hold.add('newznab', 'api_key', 'earlier-save', 1, 'held-second-text')

        world.refused('newznab', with_forms(world.rows, {1: restore('earlier-save', 1)}), None, 'token_missing')

    def test_a_keep_under_a_stale_token_is_refused_as_stale(self, world):
        settings, rows, token = world.settings, world.rows, world.token
        changed = with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)})
        changed[0]['custom_tag'] = 'intervening'
        assert settings.save_group('newznab', changed, token)['success'] is True
        world.before = snapshot(settings, 'newznab')
        world.held = dict(settings._hold._entries)

        world.refused('newznab', with_forms(rows, {0: keep(0)}), token, 'stale')

    def test_a_keep_under_another_groups_token_is_stale(self, world):
        seeded(world.settings, section='torrentpotato', column='pass_key')
        world.before = snapshot(world.settings, 'newznab')

        world.refused('newznab', with_forms(world.rows, {0: keep(0)}),
                      token_of(world.settings, 'torrentpotato'), 'stale')

    def test_the_mask_inside_a_kept_cells_stored_text_is_refused_not_stored(self, settings):
        # The recorded limit: a stored key that already contains the mask text.
        rows, token = seeded(settings)
        settings.set('newznab', 'api_key', 'a' + settings_module.SECRET_MASK + ',b,c')
        settings.save()

        result = settings.save_group('newznab', with_forms(rows, {0: keep(0)}), token_of(settings))

        assert result['invalid'] == [{'row': 0, 'column': 'api_key', 'reason': 'masked_value'}]


class TestTheOrderOfRefusalsIsPinned:
    """Documented in the spec: shape, `restore_unknown`, `token_missing`, `token_unexpected`/`stale`, range last.

    Range is last so that a caller without the group's current token cannot learn how many
    cells a column holds.
    """

    def test_an_out_of_range_keep_is_token_missing_then_stale_then_bad_reference(self, settings):
        rows, token = seeded(settings)
        sent = with_forms(rows, {0: keep(99)})

        assert settings.save_group('newznab', sent)['invalid'][0]['reason'] == 'token_missing'
        assert settings.save_group('newznab', sent, 'f' * 64)['invalid'][0]['reason'] == 'stale'
        assert settings.save_group('newznab', sent, token)['invalid'][0]['reason'] == 'bad_reference'

    def test_a_restore_nobody_holds_is_decided_before_any_token_question(self, settings):
        rows, token = seeded(settings)
        sent = with_forms(rows, {0: restore('0' * 64, 0)})

        for presented in (None, 'f' * 64, token):
            assert settings.save_group('newznab', sent, presented)['invalid'][0]['reason'] == 'restore_unknown'


class TestWhatTheHoldRecords:
    def test_a_token_carrying_save_that_omits_a_row_holds_exactly_that_rows_key(self, settings):
        rows, token = seeded(settings, keys=KEYS + ['placeholder-key-three'])
        sent = with_forms([rows[0], rows[2], rows[3]], {0: keep(0), 1: keep(2), 2: keep(3)})

        assert settings.save_group('newznab', sent, token)['success'] is True

        assert settings._hold.list_by_token('newznab', token) == [('api_key', 1)]
        assert settings._hold.peek('newznab', 'api_key', token, 1) == ' placeholder key one '

    def test_omitting_a_row_whose_key_is_empty_makes_no_entry(self, settings):
        rows, token = seeded(settings, keys=['placeholder-a', '', 'placeholder-c'])

        assert settings.save_group('newznab', with_forms([rows[0], rows[2]], {0: keep(0), 1: keep(2)}),
                                   token)['success']

        assert settings._hold.list_by_token('newznab', token) == []

    def test_a_key_replaced_by_typing_is_held_as_a_removed_one_is(self, settings):
        rows, token = seeded(settings)

        assert settings.save_group('newznab', with_forms(rows, {0: keep(0), 1: 'typed-new', 2: keep(2)}),
                                   token)['success']

        assert settings._hold.list_by_token('newznab', token) == [('api_key', 1)]
        assert settings._hold.peek('newznab', 'api_key', token, 1) == KEYS[1]

    def test_two_rows_alike_except_their_keys_each_hold_their_own_when_removed(self, settings):
        rows = keyed_rows(settings, ['placeholder-x', 'placeholder-y'])
        rows[1] = dict(rows[0], api_key='placeholder-y')
        assert settings.save_group('newznab', rows)['success']
        for removed, other in ((0, 1), (1, 0)):
            token = token_of(settings)
            assert settings.save_group('newznab', with_forms([rows[other]], {0: keep(other)}), token)['success']

            assert settings._hold.peek('newznab', 'api_key', token, removed) == rows[removed]['api_key']
            assert settings.save_group('newznab', rows)['success']

    def test_a_save_with_no_token_holds_nothing(self, settings):
        seeded(settings)

        assert settings.save_group('newznab', keyed_rows(settings, tag='b'))['success']

        assert settings._hold._entries == {}

    def test_a_builder_save_holds_nothing(self, settings):
        seeded(settings)

        def builder():
            return keyed_rows(settings, tag='b')

        assert settings.save_group('newznab', builder)['success']
        assert settings._hold._entries == {}

    def test_a_refused_save_holds_nothing_and_earlier_entries_survive(self, settings):
        rows, token = seeded(settings)
        assert settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)['success']
        earlier = dict(settings._hold._entries)
        again = keyed_rows(settings, tag='b')          # a different state, so a different token
        assert settings.save_group('newznab', again)['success']
        fresh = token_of(settings)
        # Rows 0 and 1 kept, row 2's key left out: this body WOULD hold row 2's key if accepted.
        body = with_forms(again[:2], {0: keep(0), 1: keep(1)})
        refused_body = [dict(row) for row in body]
        refused_body[0]['host'] = 'a,b'

        result = settings.save_group('newznab', refused_body, fresh)

        assert result['invalid'][0]['reason'] == 'comma'
        assert settings._hold._entries == earlier, 'a refused save made or removed an entry'
        # The accepted twin, same token (the refusal changed nothing): it does hold.
        assert settings.save_group('newznab', body, fresh)['success'] is True
        assert settings._hold.peek('newznab', 'api_key', fresh, 2) == KEYS[2], (
            'the twin must create the entry the refused body would have')

    def test_a_save_whose_write_fails_holds_nothing_and_leaves_earlier_entries(self, settings, monkeypatch):
        rows, token = seeded(settings)
        assert settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)['success']
        earlier = dict(settings._hold._entries)
        assert earlier, 'the earlier removal must have made entries'
        again = keyed_rows(settings, tag='b')          # a different state, so a different token
        assert settings.save_group('newznab', again)['success']        # token-less: three keys stored again
        fresh = token_of(settings)
        assert fresh != token
        before = snapshot(settings, 'newznab')
        real_save = Settings.save
        monkeypatch.setattr(Settings, 'save', lambda self: (_ for _ in ()).throw(OSError('disk full')))

        # Removing rows 1 and 2 would hold two keys, if the write had landed.
        result = settings.save_group('newznab', with_forms(again[:1], {0: keep(0)}), fresh)

        assert result['success'] is False
        assert settings._hold._entries == earlier
        monkeypatch.setattr(Settings, 'save', real_save)
        assert memory_group(settings, 'newznab', settings.combine_groups()['newznab']) == before[1]

    def test_the_hold_is_keyed_by_the_token_the_save_carried_not_the_fresh_one(self, settings):
        rows, token = seeded(settings)

        result = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)

        assert settings._hold.list_by_token('newznab', token) != []
        assert settings._hold.list_by_token('newznab', result['token']) == []

    def test_every_unkept_non_empty_cell_is_held_by_an_all_string_save_that_carries_a_token(self, settings):
        rows, token = seeded(settings)

        assert settings.save_group('newznab', keyed_rows(settings, ['n0', 'n1', 'n2'], tag='b'), token)['success']

        assert settings._hold.list_by_token('newznab', token) == [('api_key', 0), ('api_key', 1), ('api_key', 2)]


class TestTheBound:
    def test_the_seventeenth_entry_evicts_the_first_of_that_section_only(self, settings):
        hold = settings._hold
        for row in range(16):
            hold.add('newznab', 'api_key', 't', row, 'k%d' % row)
        hold.add('torrentpotato', 'pass_key', 't', 0, 'other')

        hold.add('newznab', 'api_key', 't', 16, 'k16')

        assert hold.peek('newznab', 'api_key', 't', 0) is None
        assert hold.peek('newznab', 'api_key', 't', 1) == 'k1'
        assert hold.peek('newznab', 'api_key', 't', 16) == 'k16'
        assert hold.peek('torrentpotato', 'pass_key', 't', 0) == 'other'
        assert len([k for k in hold._entries if k[0] == 'newznab']) == 16

    def test_re_adding_an_existing_entry_moves_it_to_the_newest_and_keeps_the_order_sound(self, settings):
        hold = settings._hold
        for row in range(16):
            hold.add('newznab', 'api_key', 't', row, 'k%d' % row)

        hold.add('newznab', 'api_key', 't', 0, 'k0-again')   # the oldest, re-added
        hold.add('newznab', 'api_key', 't', 16, 'k16')       # evicts the NEW oldest, row 1

        assert hold.peek('newznab', 'api_key', 't', 0) == 'k0-again'
        assert hold.peek('newznab', 'api_key', 't', 1) is None
        assert len(hold._entries) == 16

    def test_the_limit_is_one_module_level_per_section_constant(self):
        assert settings_module._HOLD_LIMIT_PER_SECTION == 16

    def test_saves_that_make_many_entries_are_never_refused_for_the_bound(self, settings):
        rows, token = seeded(settings)
        for number in range(8):
            result = settings.save_group('newznab', keyed_rows(settings, ['n%d-0' % number, 'n%d-1' % number,
                                                                        'n%d-2' % number], tag='x%d' % number), token)
            assert result['success'] is True
            token = result['token']

        assert len([k for k in settings._hold._entries if k[0] == 'newznab']) == 16

    def test_the_hold_is_process_memory_only(self, settings):
        rows, token = seeded(settings)
        settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        assert settings._hold.peek('newznab', 'api_key', token, 1) == KEYS[1]

        assert KEYS[1].strip() not in open(settings.file, encoding='utf-8').read()


class TestRestore:
    def removed_row_world(self, settings):
        """Three rows; row 1 removed by a save that carried the token. Returns the pieces."""
        rows, token = seeded(settings)
        result = settings.save_group('newznab', with_forms([rows[0], rows[2]], {0: keep(0), 1: keep(2)}), token)
        assert result['success'] is True
        return rows, token, result['token']

    def test_restore_after_the_removal_landed_stores_the_exact_bytes_beside_its_row(self, settings):
        rows, removed_under, current = self.removed_row_world(settings)
        sent = with_forms([rows[0], rows[1], rows[2]], {0: keep(0), 1: restore(removed_under, 1), 2: keep(1)})

        result = settings.save_group('newznab', sent, current)

        assert result['success'] is True
        assert api_key_cells(settings) == KEYS      # the middle cell survives the file byte for byte
        assert memory_key_cells(settings) == KEYS
        assert stored_group(settings.file, 'newznab', ['host'])['host'].split(',')[1] == rows[1]['host']

    def test_a_restore_at_any_position_stores_the_held_text_beside_whatever_that_row_carries(self, settings):
        rows, removed_under, current = self.removed_row_world(settings)
        sent = with_forms([rows[1], rows[0], rows[2]], {0: restore(removed_under, 1), 1: keep(0), 2: keep(1)})

        assert settings.save_group('newznab', sent, current)['success']

        # In memory byte for byte; a file read back strips whitespace at its very edges.
        assert memory_key_cells(settings) == [' placeholder key one ', KEYS[0], KEYS[2]]

    def test_the_entry_is_consumed_and_the_same_reference_is_then_restore_unknown(self, settings):
        rows, removed_under, current = self.removed_row_world(settings)
        sent = with_forms([rows[0], rows[2], rows[1]], {0: keep(0), 1: keep(1), 2: restore(removed_under, 1)})
        fresh = settings.save_group('newznab', sent, current)['token']
        again = with_forms([rows[0], rows[2], rows[1], rows[1]],
                           {0: keep(0), 1: keep(1), 2: keep(2), 3: restore(removed_under, 1)})

        for token in (fresh, current):
            refusal(settings.save_group('newznab', again, token), 3, 'api_key', 'restore_unknown')

    def test_a_refused_save_leaves_every_entry_it_named_restorable(self, settings):
        rows, removed_under, current = self.removed_row_world(settings)
        bad = with_forms([rows[0], rows[2], rows[1]], {0: keep(0), 1: keep(1), 2: restore(removed_under, 1)})
        bad[0]['host'] = 'a,b'

        assert settings.save_group('newznab', bad, current)['success'] is False

        assert settings._hold.peek('newznab', 'api_key', removed_under, 1) == ' placeholder key one '

    def test_a_failed_write_leaves_the_entry_restorable(self, settings, monkeypatch):
        rows, removed_under, current = self.removed_row_world(settings)
        sent = with_forms([rows[0], rows[2], rows[1]], {0: keep(0), 1: keep(1), 2: restore(removed_under, 1)})
        real_save = Settings.save
        monkeypatch.setattr(Settings, 'save', lambda self: (_ for _ in ()).throw(OSError('disk full')))

        assert settings.save_group('newznab', sent, current)['success'] is False
        monkeypatch.setattr(Settings, 'save', real_save)

        assert settings._hold.peek('newznab', 'api_key', removed_under, 1) == ' placeholder key one '
        assert settings.save_group('newznab', sent, current)['success'] is True

    def test_two_entries_restored_in_the_opposite_order_in_one_save_each_store_their_own_key(self, settings):
        rows, token = seeded(settings)
        result = settings.save_group('newznab', with_forms(rows[2:], {0: keep(2)}), token)  # removes 0 and 1
        sent = with_forms([rows[2], rows[1], rows[0]],
                          {0: keep(0), 1: restore(token, 1), 2: restore(token, 0)})

        assert settings.save_group('newznab', sent, result['token'])['success'] is True

        assert memory_key_cells(settings) == [KEYS[2], KEYS[1], KEYS[0]]
        assert settings._hold.list_by_token('newznab', token) == []

    def test_two_cells_carrying_the_same_reference_in_one_save_are_refused(self, settings):
        rows, removed_under, current = self.removed_row_world(settings)
        sent = with_forms([rows[0], rows[1], rows[1]],
                          {0: keep(0), 1: restore(removed_under, 1), 2: restore(removed_under, 1)})

        refusal(settings.save_group('newznab', sent, current), 2, 'api_key', 'bad_reference')

    @pytest.mark.parametrize('mutate', ['never issued', 'other token', 'other row'])
    def test_a_reference_that_is_not_held_is_restore_unknown_whatever_differs(self, settings, mutate):
        """Each case differs from the held entry in ONE respect (the section and column have their own tests)."""
        rows, removed_under, current = self.removed_row_world(settings)
        reference = {'never issued': restore('0' * 64, 1), 'other token': restore(current, 1),
                     'other row': restore(removed_under, 0)}[mutate]
        sent = with_forms([rows[0], rows[2], rows[1]], {0: keep(0), 1: keep(1), 2: reference})

        result = settings.save_group('newznab', sent, current)

        assert result['success'] is False
        assert [p['reason'] for p in result['invalid']] == ['restore_unknown']
        assert result['invalid'][0]['column'] == 'api_key'

    def test_a_restore_is_bound_to_its_section_when_only_the_section_differs(self, settings):
        """Two sections whose secret column is BOTH `api_key`: the held entry is in newznab only."""
        rows, token = seeded(settings)
        removed = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        assert removed['success'] is True
        other_section_with_api_key(settings)
        other_rows = [{'use': '1', 'host': 'https://o%d.invalid' % n, 'api_key': 'placeholder-o%d' % n}
                      for n in range(2)]
        assert settings.save_group('zz_other', other_rows)['success']
        before = snapshot(settings, 'zz_other')
        held = dict(settings._hold._entries)
        assert settings._hold.peek('newznab', 'api_key', token, 1) == KEYS[1]

        sent = [dict(other_rows[0], api_key=keep(0)), dict(other_rows[1], api_key=restore(token, 1))]
        result = settings.save_group('zz_other', sent, token_of(settings, 'zz_other'))

        refusal(result, 1, 'api_key', 'restore_unknown')
        assert settings._hold._entries == held
        assert settings._hold.peek('newznab', 'api_key', token, 1) == KEYS[1]
        assert_nothing_changed(settings, 'zz_other', before)

    def test_an_evicted_entry_is_restore_unknown(self, settings):
        rows, removed_under, current = self.removed_row_world(settings)
        for number in range(16):
            settings._hold.add('newznab', 'api_key', 'filler', number, 'f%d' % number)
        sent = with_forms([rows[0], rows[2], rows[1]], {0: keep(0), 1: keep(1), 2: restore(removed_under, 1)})

        assert [p['reason'] for p in settings.save_group('newznab', sent, current)['invalid']] == [
            'restore_unknown']

    def test_restore_unknown_is_decided_before_the_token(self, settings):
        rows, removed_under, current = self.removed_row_world(settings)
        sent = with_forms([rows[0], rows[2], rows[1]], {0: keep(0), 1: keep(1), 2: restore('0' * 64, 1)})
        gone = with_forms(sent, {})
        for token in (current, 'not-the-token', removed_under, None):
            result = settings.save_group('newznab', gone, token)
            assert [p['reason'] for p in result['invalid']] == ['restore_unknown'], token

    def test_a_restore_is_validated_like_any_save(self, settings):
        rows, removed_under, current = self.removed_row_world(settings)
        settings._hold.add('newznab', 'api_key', 'poisoned', 0, 'a,b')   # cannot arise; proves validation
        sent = with_forms([rows[0], rows[1]], {0: keep(0), 1: restore('poisoned', 0)})

        assert settings.save_group('newznab', sent, current)['invalid'][0]['reason'] == 'comma'

    def test_two_threads_restoring_one_entry_land_exactly_one(self, settings, monkeypatch):
        """Thread one is held INSIDE its lookup until thread two is inside its own.

        With the writer lock, thread two cannot get that far, so thread one waits out the
        timeout, finishes and consumes the entry, and thread two is then refused. Without
        the lock both pass the lookup and both land, which is the defect this guards.
        """
        real_peek = settings_module._RemovedKeyHold.peek
        for attempt in range(8):
            rows, token = seeded(settings, keys=['p-a%d' % attempt, 'p-b%d' % attempt])
            removed = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
            current = removed['token']
            local = threading.local()
            meet = threading.Barrier(2)

            def peek(self, *args, _local=local, _meet=meet):
                # Each save looks the entry up twice: once to decide `restore_unknown` and
                # once, AFTER the token check, to take its text. Both threads meet there.
                _local.count = getattr(_local, 'count', 0) + 1
                found = real_peek(self, *args)
                if _local.count == 2:
                    try:
                        _meet.wait(0.25)
                    except threading.BrokenBarrierError:
                        pass
                return found

            monkeypatch.setattr(settings_module._RemovedKeyHold, 'peek', peek)
            outcomes = []

            def send():
                sent = with_forms([rows[0], rows[1]], {0: keep(0), 1: restore(token, 1)})
                outcomes.append(settings.save_group('newznab', sent, current)['success'])

            threads = [threading.Thread(target=send) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            monkeypatch.setattr(settings_module._RemovedKeyHold, 'peek', real_peek)

            assert sorted(outcomes) == [False, True], 'attempt %d: %r' % (attempt, outcomes)
            assert api_key_cells(settings).count('p-b%d' % attempt) == 1

    def test_a_restore_is_bound_to_its_column(self, settings):
        two_secret_group(settings)
        rows = [{'use': '1', 'host': 'https://x.invalid', 'key_a': 'placeholder-a', 'key_b': 'placeholder-b'},
                {'use': '1', 'host': 'https://y.invalid', 'key_a': 'placeholder-c', 'key_b': 'placeholder-d'}]
        assert settings.save_group('zz_two', rows)['success']
        token = token_of(settings, 'zz_two')
        removed = settings.save_group('zz_two', [dict(rows[0], key_a=keep(0), key_b=keep(0))], token)
        assert removed['success'] is True           # row 1 removed: key_a/1 and key_b/1 are both held
        settings._hold.take('zz_two', 'key_b', token, 1)     # leave only key_a's entry
        before = snapshot(settings, 'zz_two')

        result = settings.save_group('zz_two', [dict(rows[0], key_a=keep(0), key_b=restore(token, 1))],
                                     removed['token'])

        refusal(result, 0, 'key_b', 'restore_unknown')
        assert settings._hold.peek('zz_two', 'key_a', token, 1) == 'placeholder-c'
        assert_nothing_changed(settings, 'zz_two', before)


def other_section_with_api_key(settings):
    """A second registered group whose secret column is ALSO called `api_key`."""
    config = {'name': 'zz_other', 'groups': [{'name': 'g', 'options': [
        {'name': 'use'}, {'name': 'host'}, {'name': 'api_key'},
        {'name': 'cells', 'type': 'combined', 'combine': ['use', 'host', 'api_key'],
         'pairing': ['host', 'api_key', 'use'], 'secret': ['api_key'], 'address': ['host']}]}]}
    settings.addOptions('zz_other', config)
    options = {option['name']: option for group in config['groups'] for option in group['options']}
    settings.registerDefaults('zz_other', options, save=False)
    settings.save()


def two_secret_group(settings):
    config = {'name': 'zz_two', 'groups': [{'name': 'g', 'options': [
        {'name': 'use'}, {'name': 'host'}, {'name': 'key_a'}, {'name': 'key_b'},
        {'name': 'cells', 'type': 'combined', 'combine': ['use', 'host', 'key_a', 'key_b'],
         'pairing': ['host', 'key_a', 'key_b', 'use'], 'secret': ['key_a', 'key_b'],
         'address': ['host', 'host']}]}]}
    settings.addOptions('zz_two', config)
    options = {option['name']: option for group in config['groups'] for option in group['options']}
    settings.registerDefaults('zz_two', options, save=False)
    settings.save()


class TestTheStaleRefusalListsWhatIsHeldUnderItsToken:
    def test_it_lists_column_and_index_only_for_the_token_the_save_carried(self, settings):
        rows, token = seeded(settings)
        result = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        other_section_token = seeded(settings, section='torrentpotato', column='pass_key')[1]
        settings.save_group('torrentpotato', keyed_rows(settings, KEYS[:1], 'torrentpotato', column='pass_key'),
                            other_section_token)

        stale = settings.save_group('newznab', rows, token)

        assert stale['invalid'] == [{'row': None, 'column': None, 'reason': 'stale'}]
        assert stale['held'] == [{'column': 'api_key', 'row': 1}, {'column': 'api_key', 'row': 2}]
        assert result['success'] is True

    def test_it_lists_only_the_refused_saves_own_section_even_when_the_token_string_matches(self, settings):
        rows, token = seeded(settings)
        settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        # An entry in ANOTHER section under the very same token string.
        settings._hold.add('torrentpotato', 'pass_key', token, 0, 'placeholder-other-section')

        stale = settings.save_group('newznab', rows, token)

        assert stale['held'] == [{'column': 'api_key', 'row': 1}, {'column': 'api_key', 'row': 2}]

    def test_it_lists_nothing_when_nothing_is_held_under_that_token(self, settings):
        rows, token = seeded(settings)
        settings.save_group('newznab', keyed_rows(settings, tag='z'))   # token-less: moves the token, holds none

        assert settings.save_group('newznab', rows, token)['held'] == []

    def test_no_other_refusal_carries_the_field(self, settings):
        rows, token = seeded(settings)
        bad = with_forms(rows, {0: keep(0)})
        bad[0]['host'] = 'a,b'

        for result in (settings.save_group('newznab', bad, token),
                       settings.save_group('newznab', with_forms(rows, {0: keep(0)})),
                       settings.save_group('newznab', with_forms(rows, {0: keep(9)}), token),
                       settings.save_group('imdb', three_rows(settings, 'imdb'), 'x')):
            assert result['success'] is False
            assert 'held' not in result

    def test_a_forged_token_lists_nothing_and_reveals_nothing(self, settings):
        rows, token = seeded(settings)
        settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)

        stale = settings.save_group('newznab', rows, 'a' * 64)

        assert stale['held'] == []

    def test_the_listed_text_never_carries_a_key(self, settings):
        rows, token = seeded(settings)
        settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)

        text = repr(settings.save_group('newznab', rows, token))

        assert all(key.strip() not in text for key in KEYS)


class TestARestartForgetsTheHold:
    def test_a_new_settings_on_the_same_file_refuses_old_tokens_and_references(self, settings, monkeypatch):
        rows, token = seeded(settings)
        result = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        current = result['token']

        reborn = Settings()
        reborn.setFile(settings.file)
        register_providers(reborn)
        keep_save = with_forms(rows[:1], {0: keep(0)})
        restore_save = with_forms(rows, {0: keep(0), 1: restore(token, 1), 2: restore(token, 2)})

        stale = reborn.save_group('newznab', keep_save, current)
        unknown = reborn.save_group('newznab', restore_save, current)

        assert stale['invalid'] == [{'row': None, 'column': None, 'reason': 'stale'}]
        assert [p['reason'] for p in unknown['invalid']] == ['restore_unknown', 'restore_unknown']
        assert reborn._hold._entries == {}


def plain(messages):
    """The messages without the logger's `[module] ` prefix."""
    return [m.split('] ', 1)[-1] for m in messages]


class TestTheInfoLines:
    def run(self, settings, section, rows, token):
        with LogCapture() as logs:
            result = settings.save_group(section, rows, token)
        infos = [r.getMessage() for r in logs.records if r.levelno == logging.INFO]
        return result, infos, logs

    def kept(self, infos):
        return [m for m in plain(infos) if m.startswith('Kept a stored key on a changed address')]

    def test_a_keep_with_an_unchanged_address_logs_nothing(self, settings):
        rows, token = seeded(settings)

        result, infos, _ = self.run(settings, 'newznab', with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)}), token)

        assert result['success'] is True
        assert self.kept(infos) == []

    def test_a_reorder_with_the_hosts_moving_with_their_keys_logs_nothing(self, settings):
        rows, token = seeded(settings)
        _, infos, _ = self.run(settings, 'newznab',
                               with_forms([rows[2], rows[0], rows[1]], {0: keep(2), 1: keep(0), 2: keep(1)}), token)

        assert self.kept(infos) == []

    def test_a_changed_host_on_a_kept_key_logs_one_line_naming_section_column_and_row_only(self, settings):
        rows, token = seeded(settings)
        sent = with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)})
        sent[1]['host'] = 'https://elsewhere.invalid/api'

        _, infos, logs = self.run(settings, 'newznab', sent, token)

        assert self.kept(infos) == ['Kept a stored key on a changed address: section=newznab column=api_key row=1']
        text = logs.text()
        assert 'elsewhere' not in text
        assert not any(key.strip() in text for key in KEYS)
        assert rows[1]['host'] not in text

    @pytest.mark.parametrize('change', [lambda host: host.upper(), lambda host: host + ' '])
    def test_a_change_of_case_only_or_a_trailing_space_only_logs(self, settings, change):
        rows, token = seeded(settings)
        sent = with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)})
        sent[0]['host'] = change(sent[0]['host'])

        _, infos, _ = self.run(settings, 'newznab', sent, token)

        assert len(self.kept(infos)) == 1

    def test_a_change_to_use_or_extra_score_only_logs_nothing(self, settings):
        rows, token = seeded(settings)
        sent = with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)})
        sent[0]['use'] = '0' if sent[0]['use'] != '0' else '1'
        sent[1]['extra_score'] = '9'

        _, infos, _ = self.run(settings, 'newznab', sent, token)

        assert self.kept(infos) == []

    def test_two_changed_rows_log_two_lines(self, settings):
        rows, token = seeded(settings)
        sent = with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)})
        sent[0]['host'] = 'https://one.invalid'
        sent[2]['host'] = 'https://two.invalid'

        _, infos, _ = self.run(settings, 'newznab', sent, token)

        assert [m[-5:] for m in self.kept(infos)] == ['row=0', 'row=2']

    def test_an_absent_stored_address_cell_counts_as_empty_text(self, tmp_path, monkeypatch):
        stored = {'newznab': {'use': '1,1', 'host': 'https://h0.invalid', 'api_key': 'placeholder-k0,placeholder-k1',
                              'extra_score': '0,0', 'custom_tag': ','}}
        with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
            rows = settings.group_stored_rows('newznab')
            sent = with_forms(rows, {0: keep(0), 1: keep(1)})
            sent[1]['host'] = ''                       # stored: absent; submitted: empty -> same text
            sent[0]['host'] = 'https://h0.invalid'

            _, infos, _ = self.run(settings, 'newznab', sent, token_of(settings))
            assert self.kept(infos) == []

            sent[1]['host'] = 'https://new.invalid'
            _, infos, _ = self.run(settings, 'newznab', sent, token_of(settings))
            assert len(self.kept(infos)) == 1

    def test_a_refused_save_logs_no_keep_line(self, settings):
        rows, token = seeded(settings)
        sent = with_forms(rows, {0: keep(0)})
        sent[0]['host'] = 'a,b'

        result, infos, _ = self.run(settings, 'newznab', sent, token)

        assert result['success'] is False
        assert self.kept(infos) == []

    def test_a_restore_logs_one_line_per_restored_cell_and_never_a_value(self, settings):
        rows, token = seeded(settings)
        result = settings.save_group('newznab', with_forms(rows[2:], {0: keep(2)}), token)
        sent = with_forms([rows[2], rows[1], rows[0]], {0: keep(0), 1: restore(token, 1), 2: restore(token, 0)})

        outcome, infos, logs = self.run(settings, 'newznab', sent, result['token'])

        restored = [m for m in plain(infos) if m.startswith('Restored a removed key')]
        assert restored == ['Restored a removed key: section=newznab column=api_key row=1',
                            'Restored a removed key: section=newznab column=api_key row=2']
        assert outcome['success'] is True
        assert not any(key.strip() in logs.text() for key in KEYS)
        assert token not in logs.text()

    def test_a_refused_restore_logs_no_restore_line(self, settings):
        rows, token = seeded(settings)

        _, infos, _ = self.run(settings, 'newznab', with_forms(rows, {0: restore('0' * 64, 0)}), token)

        assert not [m for m in plain(infos) if m.startswith('Restored')]

    def test_a_builder_and_a_token_less_save_never_reach_the_key_lines_and_a_token_save_does(
            self, settings, monkeypatch):
        rows, token = seeded(settings)
        reached = []
        real = Settings._log_kept_and_restored
        monkeypatch.setattr(Settings, '_log_kept_and_restored',
                            lambda self, *args: reached.append(args[0]) or real(self, *args))

        self.run(settings, 'newznab', lambda: keyed_rows(settings, tag='b'), None)
        self.run(settings, 'newznab', keyed_rows(settings, tag='c'), None)
        assert reached == [], 'a builder or token-less save reached the kept/restored lines'

        again = settings.group_stored_rows('newznab')
        sent = with_forms(again, {0: keep(0), 1: keep(1), 2: keep(2)})
        sent[0]['host'] = 'https://moved.invalid'
        _, infos, _ = self.run(settings, 'newznab', sent, token_of(settings))
        assert reached == ['newznab'], 'the twin (a token save) must reach them'
        assert len(self.kept(infos)) == 1


class TestNothingTheHoldDoesLeaksOrDisagrees:
    """A forced exception in each hold operation, with a canary in its message."""

    CANARY = 'canary-held-text-or-token'

    def agree(self, settings, expect_new):
        columns = settings.combine_groups()['newznab']
        on_disk = stored_group(settings.file, 'newznab', columns)
        assert memory_group(settings, 'newznab', columns) == on_disk, 'parser and config.ini disagree'
        assert (on_disk['host'].split(',')[0] == 'https://placeholder-n-0.invalid/path') is expect_new
        return on_disk

    @staticmethod
    def boom(monkeypatch, name):
        def raising(self, *args, **kwargs):
            raise RuntimeError(TestNothingTheHoldDoesLeaksOrDisagrees.CANARY)
        monkeypatch.setattr(settings_module._RemovedKeyHold, name, raising)

    @pytest.mark.parametrize('operation', ['add', 'evict'])
    def test_a_failing_hold_write_after_the_write_leaves_an_accepted_reply_and_one_state(
            self, settings, monkeypatch, operation):
        rows, token = seeded(settings)
        self.boom(monkeypatch, operation)
        sent = with_forms(three_rows(settings, 'newznab', tag='n'), {0: keep(0)})
        sent = [dict(sent[0])]

        with LogCapture() as logs:
            result = settings.save_group('newznab', sent, token)

        assert result['success'] is True
        self.agree(settings, expect_new=True)
        text = logs.text() + repr(result)
        assert self.CANARY not in text
        assert token not in logs.text()
        assert 'RuntimeError' in logs.text()

    @pytest.mark.parametrize('scenario', ['kept on a changed address', 'restore'])
    def test_a_failing_log_call_after_the_write_leaves_an_accepted_reply_and_consumes_the_entry(
            self, settings, monkeypatch, scenario):
        rows, token = seeded(settings, keys=['placeholder-p0', 'placeholder-p1', 'placeholder-p2'])
        removed = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        sent = three_rows(settings, 'newznab', tag='n')[:2]     # a different host: the keep logs
        sent[0]['api_key'] = keep(0)
        sent[1]['api_key'] = restore(token, 1) if scenario == 'restore' else 'typed-new'

        def raising(*args, **kwargs):
            raise RuntimeError(self.CANARY)

        monkeypatch.setattr(settings.log, 'info', raising)

        with LogCapture() as logs:
            result = settings.save_group('newznab', sent, removed['token'])

        assert result['success'] is True
        self.agree(settings, expect_new=True)
        if scenario == 'restore':
            assert settings._hold.peek('newznab', 'api_key', token, 1) is None, (
                'the restored entry must be consumed even when a log call fails')
        assert 'RuntimeError' in logs.text()
        assert self.CANARY not in logs.text() + repr(result)

    def test_one_failing_key_line_does_not_drop_the_others_and_the_error_names_the_group(
            self, settings, monkeypatch):
        rows, token = seeded(settings, keys=['placeholder-p0', 'placeholder-p1', 'placeholder-p2'])
        removed = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        sent = three_rows(settings, 'newznab', tag='n')[:2]      # a different host: the keep logs first
        sent[0]['api_key'] = keep(0)
        sent[1]['api_key'] = restore(token, 1)
        real_info = settings.log.info

        def fail_the_keep_line(message, *args, **kwargs):
            if message.startswith('Kept a stored key'):
                raise RuntimeError(self.CANARY)
            return real_info(message, *args, **kwargs)

        monkeypatch.setattr(settings.log, 'info', fail_the_keep_line)

        with LogCapture() as logs:
            result = settings.save_group('newznab', sent, removed['token'])

        assert result['success'] is True
        text = plain([r.getMessage() for r in logs.records])
        assert 'Restored a removed key: section=newznab column=api_key row=1' in text
        errors = [m for m in plain([r.getMessage() for r in logs.at_or_above(logging.ERROR)])]
        assert errors == ['Could not log a kept key: section=newznab column=api_key (RuntimeError).']
        assert self.CANARY not in logs.text()

    def test_a_failing_take_after_the_write_leaves_an_accepted_reply_and_one_state(self, settings, monkeypatch):
        rows, token = seeded(settings, keys=['placeholder-p0', 'placeholder-p1', 'placeholder-p2'])
        removed = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        self.boom(monkeypatch, 'take')
        sent = three_rows(settings, 'newznab', tag='n')[:2]
        sent[0]['api_key'] = keep(0)
        sent[1]['api_key'] = restore(token, 1)

        with LogCapture() as logs:
            result = settings.save_group('newznab', sent, removed['token'])

        assert result['success'] is True
        self.agree(settings, expect_new=True)
        assert self.CANARY not in logs.text() + repr(result)
        assert removed['token'] not in logs.text()

    @pytest.mark.parametrize('operation', ['list_by_token', 'peek'])
    def test_a_failing_hold_read_before_the_write_gives_a_failure_reply_and_the_old_state(
            self, settings, monkeypatch, operation):
        rows, token = seeded(settings)
        before = snapshot(settings, 'newznab')
        if operation == 'list_by_token':
            settings.save_group('newznab', keyed_rows(settings, tag='q'))   # makes `token` stale
            before = snapshot(settings, 'newznab')
            sent = with_forms(rows[:1], {0: keep(0)})
        else:
            sent = with_forms(three_rows(settings, 'newznab', tag='n')[:1], {0: restore(token, 1)})
        self.boom(monkeypatch, operation)

        with LogCapture() as logs:
            result = settings.save_group('newznab', sent, token)

        assert result['success'] is False
        assert 'invalid' not in result or result['invalid'][0]['reason'] != 'stale'
        assert self.CANARY not in logs.text() + repr(result)
        assert token not in logs.text() + repr(result)
        assert_nothing_changed(settings, 'newznab', before)

    def test_no_log_record_or_reply_holds_a_key_or_token_across_every_outcome(self, settings):
        rows, token = seeded(settings)
        with LogCapture() as logs:
            results = []
            first = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
            results.append(first)
            results.append(settings.save_group('newznab', with_forms(rows, {1: restore(token, 1)}), first['token']))
            results.append(settings.save_group('newznab', rows, token))                       # stale
            results.append(settings.save_group('newznab', with_forms(rows, {0: restore('0' * 64, 0)}), token))
            results.append(settings.save_group('newznab', with_forms(rows, {0: keep(99)}), first['token']))
            results.append(settings.save_group('newznab', with_forms(rows, {0: keep(0)})))

        text = logs.text()
        assert all(key.strip() not in text for key in KEYS)
        assert token not in text
        assert first['token'] not in text
        for result in results:
            if not result['success']:
                assert all(key.strip() not in repr(result) for key in KEYS)
