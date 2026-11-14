"""SEC-004 P1: the validated, all-or-nothing write of one ``combine`` group.

Five settings groups are edited as rows but stored as one comma-separated list
per column and paired back up by position. A comma inside a cell therefore
becomes a new position, and a credential ends up beside the wrong host.
``Settings.save_group`` is the one writer that takes rows, refuses a cell that
would break the pairing, and writes every column or none.

These tests drive the real ``Settings`` class over a temporary ``config.ini``
with the five real option declarations registered (``tests/helpers``), and
check the file, not only the return value. All hosts are ``.invalid`` and every
credential is a ``placeholder-`` string.
"""
import os

import pytest

from couchpotato.core.settings import Settings
from tests.helpers.combine_groups import (
    SECTIONS,
    assert_nothing_changed,
    group_settings,
    held_by_another_thread,
    memory_group,
    placeholder_rows,
    provider_configs,
    sha,
    snapshot,
    stored_group,
    three_rows,
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def declared_groups():
    """section -> combine list, read from the provider declarations themselves."""
    found = {}
    for config in provider_configs():
        for section in config:
            for group in section['groups']:
                for option in group['options']:
                    if option.get('combine'):
                        found[section['name']] = tuple(option['combine'])
    return found


class TestCombineGroupMap:
    """AC-ARCH-11(i): one method derives section -> ordered columns."""

    def test_derives_every_registered_group_in_declared_order(self, settings):
        assert settings.combine_groups() == declared_groups()
        assert set(settings.combine_groups()) == set(SECTIONS)

    def test_newznab_columns_keep_the_declared_order(self, settings):
        assert settings.combine_groups()['newznab'] == (
            'use', 'host', 'api_key', 'extra_score', 'custom_tag')

    def test_a_section_registered_later_is_derived_with_no_production_edit(self, settings):
        settings.addOptions('zz_test', {'name': 'zz_test', 'groups': [{'options': [
            {'name': 'use'},
            {'name': 'host'},
            {'name': 'key', 'type': 'combined', 'combine': ['use', 'host', 'key']},
        ]}]})

        assert settings.combine_groups()['zz_test'] == ('use', 'host', 'key')

    def test_an_option_without_a_combine_list_makes_no_group(self, settings):
        assert 'core' not in settings.combine_groups()


class TestCombineMembership:
    """AC-ARCH-11(i), AC-ARCH-2: one membership test, folded like the parser."""

    @pytest.mark.parametrize('name', [
        'host', 'HOST', 'Host', ' host', 'host ', ' api_key ', 'API_KEY', 'use\t',
    ])
    def test_a_name_that_would_become_a_column_is_a_member(self, settings, name):
        assert settings.is_combine_option('newznab', name) is True

    @pytest.mark.parametrize('section, name', [
        ('newznab', 'enabled'),
        ('newznab', 'custom_categories'),
        ('newznab', 'pass_key'),
        ('torrentpotato', 'jackett_url'),
        ('core', 'host'),
        ('no_such_section', 'host'),
        ('newznab', ''),
    ])
    def test_anything_else_is_not(self, settings, section, name):
        assert settings.is_combine_option(section, name) is False

    @pytest.mark.parametrize('name', [None, 7, b'host', ['host']])
    def test_a_non_string_name_is_not_a_member(self, settings, name):
        assert settings.is_combine_option('newznab', name) is False


def test_the_class_under_test_is_the_real_settings(settings):
    assert isinstance(settings, Settings)


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------

PAIRS = [(section, column) for section in SECTIONS for column in declared_groups()[section]]

#: The ten reason codes AC-ARCH-11(iii) freezes. `misaligned` is reachable only
#: from a builder callable, never from rows the writer is handed.
REASON_CODES = frozenset({
    'comma', 'control_character', 'not_string', 'not_encodable', 'missing_column',
    'unknown_column', 'not_writable', 'unknown_section', 'malformed', 'misaligned',
})


def refuse(settings, section, rows, *expected):
    """Save, expect a refusal listing exactly `expected`, and prove nothing moved."""
    before = snapshot(settings, section)
    result = settings.save_group(section, rows)
    assert result['success'] is False, result
    assert result['invalid'] == [
        {'row': row, 'column': column, 'reason': reason} for row, column, reason in expected], result
    assert_nothing_changed(settings, section, before)
    return result


class TestValidGroupSave:

    @pytest.mark.parametrize('section', SECTIONS)
    def test_three_rows_are_stored_column_by_column_in_row_order(self, settings, section):
        columns = settings.combine_groups()[section]
        rows = three_rows(settings, section)

        result = settings.save_group(section, rows)

        assert result == {'success': True}
        expected = {column: ','.join(row[column] for row in rows) for column in columns}
        assert stored_group(settings.file, section, columns) == expected
        assert memory_group(settings, section, columns) == expected

    def test_a_valid_save_leaves_every_other_option_alone(self, settings):
        before = {s: dict(settings.p.items(s)) for s in settings.p.sections()}
        columns = set(settings.combine_groups()['newznab'])

        rows = three_rows(settings, 'newznab')
        settings.save_group('newznab', rows)

        assert settings.p.get('newznab', 'host') == ','.join(r['host'] for r in rows), (
            'the group was not written, so "nothing else changed" proves nothing')
        for section in settings.p.sections():
            for option, value in settings.p.items(section):
                if section == 'newznab' and option in columns:
                    continue
                assert value == before[section][option], (section, option)

    def test_a_row_may_hold_empty_cells(self, settings):
        rows = three_rows(settings, 'newznab')
        rows[1]['api_key'] = ''
        rows[1]['custom_tag'] = ''

        keys = [rows[0]['api_key'], '', rows[2]['api_key']]

        assert settings.save_group('newznab', rows) == {'success': True}
        assert settings.p.get('newznab', 'api_key') == ','.join(keys)

    def test_one_all_empty_row_is_accepted(self, settings):
        columns = settings.combine_groups()['newznab']

        result = settings.save_group('newznab', [{column: '' for column in columns}])

        assert result == {'success': True}
        assert settings.p.get('newznab', 'host') == ''

    def test_a_column_marked_read_write_is_an_ordinary_writable_column(self, settings):
        """A column marked read-write is an ordinary writable column (control)."""
        settings.p.set('newznab', 'api_key_internal_meta', 'rw')
        rows = three_rows(settings, 'newznab')

        assert settings.save_group('newznab', rows) == {'success': True}
        assert settings.p.get('newznab', 'api_key') == ','.join(r['api_key'] for r in rows)


class TestCommaIsRefused:
    """AC-QA-2 (unit half), AC-DATA-2: validate fully, then mutate."""

    @pytest.mark.parametrize('section, column', PAIRS)
    def test_a_comma_in_the_last_row_of_any_column_refuses_the_whole_group(
            self, settings, section, column):
        rows = three_rows(settings, section)
        rows[2][column] = 'part-one,part-two'

        refuse(settings, section, rows, (2, column, 'comma'))

    def test_every_offending_cell_is_listed_in_row_then_column_order(self, settings):
        rows = three_rows(settings, 'newznab')
        rows[2]['custom_tag'] = 'x,y'
        rows[0]['api_key'] = 'p,q'
        rows[0]['host'] = 'https://h.invalid,https://evil.invalid'

        refuse(settings, 'newznab', rows,
               (0, 'host', 'comma'), (0, 'api_key', 'comma'), (2, 'custom_tag', 'comma'))

    @pytest.mark.parametrize('sent', ['%2C', '%2c', '%252C', 'a%41b', 'a+b', 'a&b=c', 'true', 'false'])
    def test_text_that_is_not_a_comma_is_stored_as_sent(self, settings, sent):
        """Values are taken as sent: no decode, no coercion, no refusal."""
        rows = three_rows(settings, 'newznab')
        rows[1]['api_key'] = sent

        assert settings.save_group('newznab', rows) == {'success': True}
        assert stored_group(settings.file, 'newznab', ['api_key'])['api_key'].split(',')[1] == sent

    def test_the_server_never_trims_a_cell(self, settings):
        rows = three_rows(settings, 'newznab')
        rows[1]['host'] = '  inner lead and trail  '

        assert settings.save_group('newznab', rows) == {'success': True}
        assert stored_group(settings.file, 'newznab', ['host'])['host'].split(',')[1] == (
            '  inner lead and trail  ')


class TestControlCharactersAreRefused:
    """AC-SEC-12: a line break can lose part of a credential on reload."""

    @pytest.mark.parametrize('char', ['\r', '\n', '\r\n', '\t', '\x00'])
    @pytest.mark.parametrize('section, column', PAIRS)
    def test_a_control_character_in_any_column_is_refused(self, settings, section, column, char):
        rows = three_rows(settings, section)
        rows[2][column] = 'placeholder' + char + '#after'

        refuse(settings, section, rows, (2, column, 'control_character'))

    def test_every_c0_control_character_is_refused(self, settings):
        for code in range(0x20):
            rows = three_rows(settings, 'newznab')
            rows[2]['custom_tag'] = 'a' + chr(code) + 'b'

            refuse(settings, 'newznab', rows, (2, 'custom_tag', 'control_character'))

    @pytest.mark.parametrize('value', ['a\n#b', 'a\n;b', 'a\rb'])
    def test_why_the_refusal_exists_the_parser_reloads_these_as_a_different_value(
            self, tmp_path, value):
        import configparser
        parser = configparser.RawConfigParser()
        parser.add_section('s')
        parser.set('s', 'k', value)
        path = tmp_path / 'raw.ini'
        with open(path, 'w', encoding='utf-8') as handle:
            parser.write(handle)

        reloaded = configparser.RawConfigParser()
        reloaded.read(str(path), encoding='utf-8')

        assert reloaded.get('s', 'k') != value


class TestOnlyStringsAreCells:
    """AC-SEC-11: a list cell would be stringified into text holding a comma."""

    @pytest.mark.parametrize('cell', [1, 1.5, True, False, None, ['a', 'b'], {'a': 'b'}, b'bytes'])
    def test_a_cell_of_any_other_type_refuses_and_nothing_is_coerced(self, settings, cell):
        rows = three_rows(settings, 'newznab')
        rows[2]['custom_tag'] = cell

        refuse(settings, 'newznab', rows, (2, 'custom_tag', 'not_string'))


class TestACellTheFileCannotHold:
    """A lone surrogate is valid JSON text but cannot be written as UTF-8.

    It used to pass validation and fail at the file write, so bad input was
    reported as a write failure with an ERROR line. It is refused up front, with
    a reason of its own: it is not a control character.
    """

    @pytest.mark.parametrize('cell', ['\ud800x', 'x\udfff', '\ud800', 'a\udc00\ud800b'])
    @pytest.mark.parametrize('section, column', PAIRS)
    def test_it_is_refused_in_any_column_with_nothing_written(self, settings, section, column, cell):
        rows = three_rows(settings, section)
        rows[2][column] = cell

        refuse(settings, section, rows, (2, column, 'not_encodable'))

    def test_it_is_a_warning_and_never_an_error(self, settings):
        import logging
        from tests.helpers.combine_groups import LogCapture
        rows = three_rows(settings, 'newznab')
        rows[1]['api_key'] = '\ud800canary'

        with LogCapture() as log:
            result = settings.save_group('newznab', rows)

        lines = log.at_or_above(logging.WARNING)
        assert result['success'] is False and 'invalid' in result
        assert [r.levelno for r in lines] == [logging.WARNING]
        assert 'reason=not_encodable' in lines[0].getMessage()
        assert 'canary' not in log.text()

    def test_well_formed_non_ascii_text_is_still_accepted(self, settings):
        rows = three_rows(settings, 'newznab')
        rows[1]['host'] = 'https://bücher.example/\U0001f9ea'

        assert settings.save_group('newznab', rows) == {'success': True}
        assert stored_group(settings.file, 'newznab', ['host'])['host'].split(',')[1] == (
            'https://bücher.example/\U0001f9ea')


class TestMalformedPayloads:
    """AC-QA-4, AC-SEC-4: only the declared columns of one named group."""

    @pytest.mark.parametrize('rows', ['text', {'0': {}}, None, 5, 1.5, True, ('a',)])
    def test_rows_that_are_not_a_list(self, settings, rows):
        refuse(settings, 'newznab', rows, (None, None, 'malformed'))

    def test_an_empty_row_list(self, settings):
        refuse(settings, 'newznab', [], (None, None, 'malformed'))

    @pytest.mark.parametrize('row', ['text', None, 7, ['host'], [('host', 'x')]])
    def test_a_row_that_is_not_an_object(self, settings, row):
        rows = three_rows(settings, 'newznab')
        rows[2] = row

        refuse(settings, 'newznab', rows, (2, None, 'malformed'))

    def test_a_row_missing_the_last_column(self, settings):
        rows = three_rows(settings, 'newznab')
        del rows[2]['custom_tag']

        refuse(settings, 'newznab', rows, (2, 'custom_tag', 'missing_column'))

    def test_a_row_with_every_column_but_one_missing(self, settings):
        rows = three_rows(settings, 'torrentpotato')
        rows[2] = {'host': 'https://h.invalid'}

        refuse(settings, 'torrentpotato', rows,
               (2, 'use', 'missing_column'), (2, 'pass_key', 'missing_column'),
               (2, 'name', 'missing_column'), (2, 'seed_ratio', 'missing_column'),
               (2, 'seed_time', 'missing_column'), (2, 'extra_score', 'missing_column'))

    @pytest.mark.parametrize('extra', [
        'enabled', 'custom_categories', 'password', 'auth_required', 'pass_key', 'API_KEY', 'host ',
    ])
    def test_a_column_the_group_does_not_declare(self, settings, extra):
        """An extra option, another section's column, or a case or space variant."""
        rows = three_rows(settings, 'newznab')
        rows[2][extra] = 'placeholder-value'

        refuse(settings, 'newznab', rows, (2, None, 'unknown_column'))

    @pytest.mark.parametrize('section', [
        'core', 'no_such_section', 'NEWZNAB', 'newznab ', '', None, 7, ['newznab'], {'a': 1},
    ])
    def test_a_section_that_is_not_a_registered_group(self, settings, section):
        settings.addSection('core')
        settings.p.set('core', 'password', 'placeholder-hash')
        settings.p.set('core', 'auth_required', '0')
        settings.save()
        core_before = sha(settings.file)
        rows = [{'password': 'placeholder-x', 'auth_required': '1'}]

        result = settings.save_group(section, rows)

        assert result['success'] is False
        assert result['invalid'] == [{'row': None, 'column': None, 'reason': 'unknown_section'}]
        assert sha(settings.file) == core_before
        assert settings.p.get('core', 'password') == 'placeholder-hash'

    @pytest.mark.parametrize('meta', ['ro', 'hidden', 'RO'])
    def test_a_column_that_is_not_writable_refuses_the_whole_request(self, settings, meta):
        settings.p.set('newznab', 'api_key_internal_meta', meta)
        settings.save()

        refuse(settings, 'newznab', three_rows(settings, 'newznab'),
               (None, 'api_key', 'not_writable'))

    def test_writability_is_asked_of_the_same_method_settings_save_uses(self, settings, monkeypatch):
        """A copied check would not see this patch."""
        asked = []

        def writable(section, option):
            asked.append((section, option))
            return option != 'custom_tag'

        monkeypatch.setattr(settings, 'isOptionWritable', writable)

        refuse(settings, 'newznab', three_rows(settings, 'newznab'),
               (None, 'custom_tag', 'not_writable'))
        assert ('newznab', 'custom_tag') in asked


class TestRefusalContract:
    """AC-ARCH-11(iii): the shape and the codes later slices build against."""

    def test_the_refusal_has_exactly_success_error_and_invalid(self, settings):
        rows = three_rows(settings, 'newznab')
        rows[1]['host'] = 'a,b'

        result = settings.save_group('newznab', rows)

        assert set(result) == {'success', 'error', 'invalid'}
        assert isinstance(result['error'], str) and result['error']
        assert all(set(entry) == {'row', 'column', 'reason'} for entry in result['invalid'])

    def test_the_error_text_is_fixed_and_carries_no_submitted_value(self, settings):
        first = three_rows(settings, 'newznab', tag='first')
        second = three_rows(settings, 'newznab', tag='second')
        first[1]['host'] = 'first-canary,x'
        second[1]['host'] = 'second-canary,x'

        a = settings.save_group('newznab', first)
        b = settings.save_group('newznab', second)

        assert a['error'] == b['error']
        assert 'canary' not in a['error']

    def test_the_writer_can_return_no_reason_outside_the_ten_codes(self, settings):
        from couchpotato.core.settings import GROUP_REFUSAL_REASONS
        assert GROUP_REFUSAL_REASONS == REASON_CODES

        seen = set()
        rows = three_rows(settings, 'newznab')
        hostile = [
            ('newznab', 'text'), ('newznab', []), ('core', rows), (None, rows),
            ('newznab', [dict(rows[0], host='a,b')]),
            ('newznab', [dict(rows[0], host='a\nb')]),
            ('newznab', [dict(rows[0], host=3)]),
            ('newznab', [dict(rows[0], host='\ud800x')]),
            ('newznab', [{'host': 'x'}]),
            ('newznab', [dict(rows[0], enabled='1')]),
            ('newznab', ['x']),
        ]
        for section, payload in hostile:
            seen.update(e['reason'] for e in settings.save_group(section, payload)['invalid'])

        settings.p.set('newznab', 'host_internal_meta', 'ro')
        seen.update(e['reason'] for e in settings.save_group('newznab', rows)['invalid'])

        assert seen == REASON_CODES - {'misaligned'}


class TestRowsAreKeyedByRow:
    """AC-DATA-5: pairing is exactly as sent, in numeric order."""

    def test_each_host_sits_at_the_position_of_its_own_key(self, settings):
        columns = settings.combine_groups()['newznab']
        rows = [{column: '' for column in columns}, {column: '' for column in columns}]
        rows[0].update(host='https://h1.invalid', api_key='placeholder-k1', use='1')
        rows[1].update(host='https://h2.invalid', api_key='placeholder-k2', use='1')

        assert settings.save_group('newznab', rows) == {'success': True}
        stored = stored_group(settings.file, 'newznab', columns)
        assert stored['host'].split(',') == ['https://h1.invalid', 'https://h2.invalid']
        assert stored['api_key'].split(',') == ['placeholder-k1', 'placeholder-k2']

    def test_twelve_rows_keep_rows_ten_and_eleven_at_positions_ten_and_eleven(self, settings):
        columns = settings.combine_groups()['newznab']
        rows = placeholder_rows(columns, 12)

        assert settings.save_group('newznab', rows) == {'success': True}
        stored = stored_group(settings.file, 'newznab', columns)
        hosts = stored['host'].split(',')
        assert len(hosts) == 12
        assert hosts[10] == rows[10]['host'] and hosts[11] == rows[11]['host']
        assert stored['api_key'].split(',')[10] == rows[10]['api_key']


class TestBuilderCallable:
    """AC-ARCH-11(ii): a builder runs under the lock and returns the rows."""

    def test_a_builder_is_called_once_with_the_lock_held_and_its_rows_are_saved(self, settings):
        from couchpotato.core import settings as settings_module
        rows = three_rows(settings, 'newznab')
        held_elsewhere = []

        def builder():
            held_elsewhere.append(held_by_another_thread(settings_module._PASSWORD_SAVE_LOCK))
            return rows

        assert settings.save_group('newznab', builder) == {'success': True}
        assert held_elsewhere == [True], 'the builder ran without the lock held'
        assert settings.p.get('newznab', 'host') == ','.join(r['host'] for r in rows)

    def test_a_builder_is_not_called_for_an_unknown_section(self, settings):
        called = []

        result = settings.save_group('core', lambda: called.append(1) or [])

        assert result['invalid'][0]['reason'] == 'unknown_section'
        assert called == []

    def test_rows_a_builder_returns_get_the_same_validation(self, settings):
        rows = three_rows(settings, 'newznab')
        rows[2]['custom_tag'] = 'a,b'

        before = snapshot(settings, 'newznab')
        result = settings.save_group('newznab', lambda: rows)

        assert result['invalid'] == [{'row': 2, 'column': 'custom_tag', 'reason': 'comma'}]
        assert_nothing_changed(settings, 'newznab', before)

    @pytest.mark.parametrize('ending', [
        'raises', 'declines_misaligned', 'returns_a_comma', 'returns_valid_rows_then_the_file_write_fails',
    ])
    def test_what_a_builder_wrote_to_the_group_is_undone_on_any_refusal_or_failure(
            self, settings, monkeypatch, ending):
        """The snapshot is taken BEFORE the builder runs.

        A builder only reads and returns rows, but one that sets a column in
        memory and then fails must not leave that value for the next unrelated
        save to persist.
        """
        from couchpotato.core.settings import GroupMisaligned
        rows = three_rows(settings, 'newznab')
        if ending == 'returns_a_comma':
            rows[2]['custom_tag'] = 'a,b'
        before = snapshot(settings, 'newznab')

        def builder():
            settings.set('newznab', 'host', 'builder-wrote-this')
            settings.set('newznab', 'api_key', 'builder-wrote-this-too')
            if ending == 'raises':
                raise RuntimeError('boom')
            if ending == 'declines_misaligned':
                raise GroupMisaligned()
            return rows

        def no_space(*args, **kwargs):
            raise OSError(28, 'No space left on device')

        with monkeypatch.context() as patched:
            if ending.endswith('file_write_fails'):
                patched.setattr(os, 'replace', no_space)
            result = settings.save_group('newznab', builder)

        assert result['success'] is False
        assert_nothing_changed(settings, 'newznab', before)

    def test_a_builder_that_declines_a_misaligned_group_is_a_request_level_refusal(self, settings):
        from couchpotato.core.settings import GroupMisaligned

        def builder():
            raise GroupMisaligned()

        before = snapshot(settings, 'newznab')
        result = settings.save_group('newznab', builder)

        assert result['success'] is False
        assert result['invalid'] == [{'row': None, 'column': None, 'reason': 'misaligned'}]
        assert_nothing_changed(settings, 'newznab', before)
