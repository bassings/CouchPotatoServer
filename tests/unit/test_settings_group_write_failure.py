"""SEC-004 P1: a group write that fails, races or must round-trip leaves nothing behind.

Companion to ``test_settings_group_write.py``. That file proves what a group
save accepts and refuses; this one proves what happens around the file write:
the in-memory rollback (AC-DATA-1), the single continuous hold of the lock
(AC-DATA-3), one file write per save (AC-QA-6), the log lines (AC-OPS-1,
AC-OPS-3, AC-SEC-7), and that aligned configurations and the rollback path are
byte-for-byte what the per-column save produces (AC-DATA-12, -13, -15).

Hosts are ``.invalid`` and every credential is a ``placeholder-`` string.
"""
import configparser
import logging
import os
import threading
import time
from pathlib import Path

import pytest

from couchpotato.core import settings as settings_module
from couchpotato.environment import Env
from tests.helpers.combine_groups import (
    SECTIONS,
    InstrumentedLock,
    LogCapture,
    assert_nothing_changed,
    group_settings,
    memory_group,
    placeholder_rows,
    sha,
    snapshot,
    stored_group,
    three_rows,
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def no_space_left(*args, **kwargs):
    raise OSError(28, 'No space left on device')


class TestAWriteThatFails:
    """AC-DATA-1: no residue in memory or on disk."""

    @pytest.mark.parametrize('section', SECTIONS)
    def test_a_failed_file_replace_leaves_disk_and_memory_as_they_were(
            self, settings, monkeypatch, section):
        before = snapshot(settings, section)
        rows = three_rows(settings, section)

        with monkeypatch.context() as patched:
            patched.setattr(os, 'replace', no_space_left)
            result = settings.save_group(section, rows)

        assert result['success'] is False
        assert 'invalid' not in result, 'a write failure is not a refusal of the rows'
        assert_nothing_changed(settings, section, before)

    def test_a_later_save_of_something_else_does_not_publish_the_failed_group(
            self, settings, monkeypatch):
        """Measured on master for the per-column path: the failed value lands on
        disk at the next unrelated save. Here the rows were never kept."""
        columns = settings.combine_groups()['newznab']
        before = snapshot(settings, 'newznab')
        with monkeypatch.context() as patched:
            patched.setattr(os, 'replace', no_space_left)
            settings.save_group('newznab', three_rows(settings, 'newznab'))

        settings.set('newznab', 'enabled', 'False')
        settings.save()

        assert stored_group(settings.file, 'newznab', columns) == before[1]
        assert stored_group(settings.file, 'newznab', ['enabled'])['enabled'] == 'False'

    def test_the_failure_is_a_result_and_not_an_exception(self, settings, monkeypatch):
        with monkeypatch.context() as patched:
            patched.setattr(os, 'replace', no_space_left)
            result = settings.save_group('newznab', three_rows(settings, 'newznab'))

        assert set(result) == {'success', 'error'}
        assert result['success'] is False

    def test_a_section_the_parser_did_not_have_is_removed_again(self, settings, monkeypatch):
        settings.addOptions('zz_new', {'name': 'zz_new', 'groups': [{'options': [
            {'name': 'use'}, {'name': 'host'},
            {'name': 'key', 'type': 'combined', 'combine': ['use', 'host', 'key']},
        ]}]})
        assert not settings.p.has_section('zz_new')
        rows = [{'use': '1', 'host': 'https://h.invalid', 'key': 'placeholder-k'}]

        with monkeypatch.context() as patched:
            patched.setattr(os, 'replace', no_space_left)
            assert settings.save_group('zz_new', rows)['success'] is False

        assert not settings.p.has_section('zz_new')

    def test_an_option_the_parser_did_not_have_is_removed_again(self, settings, monkeypatch):
        settings.p.remove_option('newznab', 'custom_tag')
        settings.save()
        before = sha(settings.file)

        with monkeypatch.context() as patched:
            patched.setattr(os, 'replace', no_space_left)
            settings.save_group('newznab', three_rows(settings, 'newznab'))

        assert not settings.p.has_option('newznab', 'custom_tag')
        assert sha(settings.file) == before

    def test_a_keyboard_interrupt_mid_write_restores_memory_and_propagates(
            self, settings, monkeypatch):
        before = snapshot(settings, 'newznab')

        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt

        rows = three_rows(settings, 'newznab')
        with monkeypatch.context() as patched:
            patched.setattr(os, 'replace', interrupted)
            with pytest.raises(KeyboardInterrupt):
                settings.save_group('newznab', rows)

        assert_nothing_changed(settings, 'newznab', before)

    def test_a_builder_that_raises_is_a_failure_result_and_changes_nothing(self, settings):
        before = snapshot(settings, 'newznab')

        def builder():
            raise RuntimeError('boom')

        result = settings.save_group('newznab', builder)

        assert result['success'] is False
        assert 'invalid' not in result
        assert_nothing_changed(settings, 'newznab', before)


class TestTheRollbackHappensInsideTheLock:
    """AC-DATA-1, concurrent case, with the instrumented re-entrant lock.

    A barrier cannot show this: a rollback made just AFTER the lock is released
    is invisible to a second writer that merely happens to run a moment later.
    The lock reports the group's in-memory columns at the instant the writer's
    outermost hold ends, which is what the next thread to take it would see.
    """

    def test_the_columns_are_back_to_their_pre_save_values_when_the_hold_ends(
            self, settings, monkeypatch):
        monkeypatch.setattr(Env, '_settings', settings)
        columns = settings.combine_groups()['newznab']
        pre = memory_group(settings, 'newznab', columns)
        writer = threading.get_ident()
        at_release = []
        lock = InstrumentedLock(
            lambda ident: at_release.append(memory_group(settings, 'newznab', columns))
            if ident == writer else None)
        monkeypatch.setattr(settings_module, '_PASSWORD_SAVE_LOCK', lock)

        second = {}
        calls = []
        real_replace = os.replace

        def fail_first_then_work(src, dst):
            calls.append(src)
            if len(calls) > 1:
                return real_replace(src, dst)
            thread = threading.Thread(target=lambda: Env.setting(
                'zz_probe', section='zz_other', value='placeholder-second'))
            thread.start()
            second['thread'] = thread
            deadline = time.monotonic() + 2
            while lock.waiting < 1 and time.monotonic() < deadline:
                time.sleep(0.005)
            second['was_blocked'] = lock.waiting >= 1
            raise OSError(28, 'No space left on device')

        monkeypatch.setattr(os, 'replace', fail_first_then_work)

        rows = three_rows(settings, 'newznab')
        try:
            result = settings.save_group('newznab', rows)
        finally:
            if 'thread' in second:
                second['thread'].join(5)

        assert result['success'] is False
        assert second['was_blocked'], 'the second writer was not waiting on the lock'
        assert at_release[0] == pre, 'the failed values were still in memory when the lock was released'
        assert stored_group(settings.file, 'newznab', columns) == pre
        parser = configparser.RawConfigParser()
        parser.read(settings.file, encoding='utf-8')
        assert parser.get('zz_other', 'zz_probe') == 'placeholder-second', (
            'the second writer finished with its value lost')


class TestOneContinuousHold:
    """AC-DATA-3: the parser writes and the file write share one hold of the lock."""

    @pytest.fixture
    def world(self, settings, monkeypatch):
        monkeypatch.setattr(Env, '_settings', settings)
        columns = settings.combine_groups()['newznab']
        lock = InstrumentedLock()
        monkeypatch.setattr(settings_module, '_PASSWORD_SAVE_LOCK', lock)
        main = threading.get_ident()
        world = {
            'columns': columns, 'lock': lock, 'main': main,
            'a': placeholder_rows(columns, 3, tag='a'),
            'b': placeholder_rows(columns, 2, tag='b'),
            'release': threading.Event(), 'any_done': threading.Event(),
            'group_set_holds': [], 'replace_holds': [], 'written': [],
            'finished_while_held': None, 'threads': [],
        }

        original_set = settings.set

        def hooked_set(section, option, value):
            """Fire AFTER `Settings.set` has returned, i.e. BETWEEN two columns.

            Inside `Settings.set` the lock is held by that call alone, so a
            second writer is blocked whether or not the writer holds the lock
            across the whole group: an assertion made there cannot fail. Here
            only the writer's own outer hold keeps the second writer out.
            """
            result = original_set(section, option, value)
            if threading.get_ident() == main and section == 'newznab' and option in columns:
                world['group_set_holds'].append(lock.hold_of(main))
                if world['finished_while_held'] is None:
                    world['release'].set()
                    world['finished_while_held'] = world['any_done'].wait(1.0)
            return result

        monkeypatch.setattr(settings, 'set', hooked_set)

        real_replace = os.replace

        def spy(src, dst):
            parser = configparser.RawConfigParser()
            parser.read(src, encoding='utf-8')
            world['written'].append({c: parser.get('newznab', c) for c in columns})
            if threading.get_ident() == main:
                world['replace_holds'].append(lock.hold_of(main))
            return real_replace(src, dst)

        monkeypatch.setattr(os, 'replace', spy)
        try:
            yield world
        finally:
            # A failing test must not leave a writer thread running or waiting.
            world['release'].set()
            for thread in world['threads']:
                thread.join(5)

    def start_second_writer(self, world, action):
        def run():
            world['release'].wait(5)
            action()
            world['any_done'].set()

        thread = threading.Thread(target=run)
        thread.start()
        world['threads'].append(thread)

    @staticmethod
    def joined(rows, columns):
        return {c: ','.join(r[c] for r in rows) for c in columns}

    @pytest.mark.parametrize('kind', ['env_setting', 'save_view', 'second_group'])
    def test_a_second_writer_waits_for_the_first_group_to_be_on_disk(
            self, settings, world, kind):
        actions = {
            'env_setting': lambda: Env.setting('enabled', section='newznab', value='False'),
            'save_view': lambda: settings.saveView(
                section='newznab', name='custom_categories', value='placeholder-categories'),
            'second_group': lambda: settings.save_group('newznab', world['b']),
        }
        self.start_second_writer(world, actions[kind])
        a, b = (self.joined(world[k], world['columns']) for k in ('a', 'b'))

        result = settings.save_group('newznab', world['a'])
        for thread in world['threads']:
            thread.join(5)

        assert result == {'success': True}
        assert world['finished_while_held'] is False, (
            'the second writer finished while the first group was half written')
        assert world['written'][0] == a, 'the first file write was not the whole first group'
        assert all(snap in (a, b) for snap in world['written']), (
            'a file was written holding a mix of two groups: %r' % world['written'])
        final = stored_group(settings.file, 'newznab', world['columns'])
        assert final == (b if kind == 'second_group' else a)
        if kind == 'env_setting':
            assert stored_group(settings.file, 'newznab', ['enabled'])['enabled'] == 'False'
        if kind == 'save_view':
            assert stored_group(settings.file, 'newznab', ['custom_categories'])[
                'custom_categories'] == 'placeholder-categories'

    def test_every_column_set_and_the_file_write_share_one_hold(self, settings, world):
        result = settings.save_group('newznab', world['a'])

        holds = set(world['group_set_holds']) | set(world['replace_holds'])
        assert result == {'success': True}
        assert len(world['group_set_holds']) == len(world['columns'])
        assert None not in holds, 'a column was set or the file written with no lock held'
        assert len(holds) == 1, 'the group write was split across separate lock holds: %r' % holds


class TestOneFileWrite:
    """AC-QA-6: one config write per group save, however many columns."""

    @pytest.mark.parametrize('section', SECTIONS)
    def test_a_successful_group_save_writes_the_file_once(self, settings, monkeypatch, section):
        saves = []
        replaces = []
        real_save = settings_module.Settings._save
        real_replace = os.replace
        monkeypatch.setattr(settings_module.Settings, '_save',
                            lambda self: saves.append(1) or real_save(self))
        monkeypatch.setattr(os, 'replace',
                            lambda src, dst: replaces.append(dst) or real_replace(src, dst))

        result = settings.save_group(section, three_rows(settings, section))

        assert result == {'success': True}
        assert len(saves) == 1
        assert len(replaces) == 1



class TestWhatIsLogged:
    """AC-OPS-1, AC-OPS-3, AC-SEC-7: one line, a count, never a value."""

    CANARY_HOST = 'https://canary-host.invalid,https://canary-evil.invalid'
    CANARY_KEY = 'canary-key,canary-key-two'

    def two_offending_cells(self, settings):
        rows = three_rows(settings, 'newznab')
        rows[1]['host'] = self.CANARY_HOST
        rows[2]['api_key'] = self.CANARY_KEY
        return rows

    def test_a_refusal_logs_exactly_one_warning_with_the_first_cell_and_the_count(self, settings):
        with LogCapture() as log:
            settings.save_group('newznab', self.two_offending_cells(settings))

        lines = log.at_or_above(logging.WARNING)
        assert len(lines) == 1, [r.getMessage() for r in log.records]
        message = lines[0].getMessage()
        for part in ('section=newznab', 'first_row=1', 'first_column=host',
                     'reason=comma', 'offences=2'):
            assert part in message, message

    def test_no_value_reaches_any_log_line_at_any_level(self, settings):
        with LogCapture() as log:
            settings.save_group('newznab', self.two_offending_cells(settings))

        assert 'canary' not in log.text()

    @pytest.mark.parametrize('payload', [
        'text', [], ['x'], [{'host': 'canary-only'}],
        [{'use': '1', 'host': 'canary', 'api_key': 'canary', 'extra_score': '0',
          'custom_tag': 'canary', 'enabled': 'canary'}],
    ])
    def test_every_other_refusal_also_logs_one_warning_and_no_value(self, settings, payload):
        with LogCapture() as log:
            result = settings.save_group('newznab', payload)

        assert result['success'] is False
        assert len(log.at_or_above(logging.WARNING)) == 1
        assert 'canary' not in log.text()

    def test_an_unregistered_section_name_is_not_echoed_to_the_log(self, settings):
        with LogCapture() as log:
            settings.save_group('canary-section', [])

        assert 'canary' not in log.text()
        assert len(log.at_or_above(logging.WARNING)) == 1

    def test_a_valid_save_logs_no_warning_and_no_value(self, settings):
        rows = three_rows(settings, 'newznab')
        rows[1]['api_key'] = 'canary-valid-key'

        with LogCapture() as log:
            assert settings.save_group('newznab', rows) == {'success': True}

        assert log.at_or_above(logging.WARNING) == []
        assert 'canary' not in log.text()

    def test_a_builder_that_raises_logs_one_error_with_the_type_and_no_traceback_or_value(
            self, settings):
        def builder():
            raise RuntimeError('canary-in-the-exception-text')

        with LogCapture() as log:
            result = settings.save_group('newznab', builder)

        lines = log.at_or_above(logging.WARNING)
        assert result['success'] is False
        assert 'invalid' not in result
        assert len(lines) == 1, [r.getMessage() for r in log.records]
        assert lines[0].levelno == logging.ERROR
        assert lines[0].exc_info is None
        assert 'newznab' in lines[0].getMessage()
        assert 'RuntimeError' in lines[0].getMessage()
        assert 'canary' not in log.text()
        assert 'canary' not in repr(result)

    def test_a_failed_write_logs_one_error_naming_the_section_and_exception_type(
            self, settings, monkeypatch):
        rows = three_rows(settings, 'newznab')
        rows[1]['api_key'] = 'canary-key'

        with LogCapture() as log, monkeypatch.context() as patched:
            patched.setattr(os, 'replace', no_space_left)
            result = settings.save_group('newznab', rows)

        lines = log.at_or_above(logging.WARNING)
        assert result['success'] is False
        assert len(lines) == 1, [r.getMessage() for r in log.records]
        assert lines[0].levelno == logging.ERROR
        assert 'newznab' in lines[0].getMessage()
        assert 'OSError' in lines[0].getMessage()
        assert lines[0].exc_info is None, 'no traceback is logged for a write failure'
        assert 'canary' not in log.text()
        assert 'canary' not in repr(result)


class TestAStoredGroupIsOnlyRewrittenByASaveOfThatGroup:
    """AC-DATA-12, unit half."""

    def test_a_misaligned_group_survives_every_other_save_byte_for_byte(self, tmp_path, monkeypatch):
        stored = {'newznab': {'host': 'a,b,c', 'api_key': 'k1,k2'}}
        with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
            monkeypatch.setattr(Env, '_settings', settings)
            before = sha(settings.file)
            before_lines = set(Path(settings.file).read_text(encoding='utf-8').splitlines())

            settings.view()
            settings.getValues()
            assert sha(settings.file) == before, 'opening the page wrote the file'

            settings.saveView(section='imdb', name='automation_enabled', value='True')
            Env.setting('zz_probe', section='zz_other', value='placeholder')

            after_lines = set(Path(settings.file).read_text(encoding='utf-8').splitlines())
            assert stored_group(settings.file, 'newznab', ['host', 'api_key']) == {
                'host': 'a,b,c', 'api_key': 'k1,k2'}
            changed = before_lines ^ after_lines
            assert changed, 'the unrelated saves changed nothing, so this proves nothing'
            assert not any(line.startswith(('host =', 'api_key =')) for line in changed), changed


def derive_rows(path, section, columns):
    """The rows the page derives from an ALIGNED stored group: one per position."""
    parser = configparser.RawConfigParser()
    parser.read(str(path), encoding='utf-8')
    cells = {column: parser.get(section, column).split(',') for column in columns}
    count = max(len(values) for values in cells.values())
    assert all(len(values) == count for values in cells.values()), 'fixture is not aligned'
    return [{column: cells[column][index] for column in columns} for index in range(count)]


ALIGNED_FIXTURES = {
    'newznab, empty cells, a trailing empty row, an IDN host and a literal %': ('newznab', {
        'host': 'https://h1.invalid,,https://bücher.example,',
        'api_key': 'placeholder-k%1,,placeholder-k3,',
        'use': '1,,0,',
        'extra_score': '0,5,0,',
        'custom_tag': 'a=1,,,',
    }),
    'newznab, the fresh-install shape': ('newznab', None),
    'newznab, a key in default row 4': ('newznab', {'api_key': ',,,placeholder-key,,'}),
    'torrentpotato, empty cells, a trailing empty row, an IDN host and a literal %': ('torrentpotato', {
        'use': '1,0,',
        'host': 'https://t1.invalid,https://bücher.invalid,',
        'pass_key': 'placeholder-pk%1,placeholder-pk2,',
        'name': 'user1,,',
        'seed_ratio': '1,2,',
        'seed_time': '40,41,',
        'extra_score': '0,1,',
    }),
    'itunes, the shipped default (a URL, a comma, and a single comma in use)': ('itunes', None),
    'imdb, a trailing empty row': ('imdb', {
        'automation_urls': 'https://placeholder.invalid/a,', 'automation_urls_use': '1,'}),
    'letterboxd, empty cells and a literal %': ('letterboxd', {
        'automation_urls': 'placeholder-user-a,,placeholder-user%b',
        'automation_urls_use': '1,0,1'}),
}


class TestAlignedConfigurationsRoundTrip:
    """AC-DATA-13 (everything but the trim clause, which is E2E in P3)."""

    @pytest.fixture(params=list(ALIGNED_FIXTURES), ids=list(ALIGNED_FIXTURES))
    def aligned(self, request, tmp_path, monkeypatch):
        section, stored = ALIGNED_FIXTURES[request.param]
        with group_settings(tmp_path, monkeypatch,
                            stored={section: stored} if stored else None) as settings:
            yield settings, section

    def test_saving_exactly_the_rows_derived_leaves_the_whole_file_identical(self, aligned):
        settings, section = aligned
        columns = settings.combine_groups()[section]
        before = sha(settings.file)
        rows = derive_rows(settings.file, section, columns)

        assert settings.save_group(section, rows) == {'success': True}

        assert sha(settings.file) == before

    def test_changing_one_cell_changes_exactly_one_line(self, aligned):
        settings, section = aligned
        columns = settings.combine_groups()[section]
        before = Path(settings.file).read_text(encoding='utf-8').splitlines()
        rows = derive_rows(settings.file, section, columns)
        rows[0][columns[-1]] = 'placeholder-changed'

        assert settings.save_group(section, rows) == {'success': True}

        after = Path(settings.file).read_text(encoding='utf-8').splitlines()
        assert len(after) == len(before)
        assert len([1 for old, new in zip(before, after) if old != new]) == 1

    def test_a_wizard_shaped_group_has_its_surplus_default_cells_dropped_on_save(
            self, tmp_path, monkeypatch):
        """The Definitions' one accepted change: rows sent are rows stored."""
        stored = {'newznab': {'host': 'https://h1.invalid,https://h2.invalid,https://h3.invalid',
                              'api_key': 'placeholder-k1,placeholder-k2,placeholder-k3',
                              'use': '1,1,1'}}
        with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
            columns = settings.combine_groups()['newznab']
            rows = [{'use': '1', 'host': 'https://h%d.invalid' % n, 'api_key': 'placeholder-k%d' % n,
                     'extra_score': '0', 'custom_tag': ''} for n in (1, 2, 3)]

            assert settings.save_group('newznab', rows) == {'success': True}

            stored_now = stored_group(settings.file, 'newznab', columns)
            assert stored_now['extra_score'] == '0,0,0'
            assert stored_now['custom_tag'] == ',,'


class TestRollbackIsARevert:
    """AC-DATA-15: the stored format did not change, so reverting is enough."""

    @staticmethod
    def structure(path):
        parser = configparser.RawConfigParser()
        parser.read(str(path), encoding='utf-8')
        return {section: sorted(parser.options(section)) for section in parser.sections()}

    @pytest.mark.parametrize('section', SECTIONS)
    def test_a_group_save_writes_the_same_bytes_as_the_per_column_saves_it_replaces(
            self, tmp_path, monkeypatch, section):
        (tmp_path / 'master').mkdir()
        (tmp_path / 'group').mkdir()
        with group_settings(tmp_path / 'master', monkeypatch) as per_column:
            columns = per_column.combine_groups()[section]
            rows = placeholder_rows(columns, 3)
            baseline = self.structure(per_column.file)
            for column in columns:
                result = per_column.saveView(
                    section=section, name=column, value=','.join(r[column] for r in rows))
                assert result['success'] is True
            master_bytes = Path(per_column.file).read_bytes()
            master_structure = self.structure(per_column.file)

        with group_settings(tmp_path / 'group', monkeypatch) as grouped:
            assert grouped.save_group(section, rows) == {'success': True}
            group_bytes = Path(grouped.file).read_bytes()
            group_structure = self.structure(grouped.file)

        assert group_bytes == master_bytes
        assert group_structure == master_structure == baseline, (
            'a group save added, dropped or renamed an option (a marker, a token)')

    @pytest.mark.parametrize('section', ['newznab', 'torrentpotato'])
    def test_the_providers_real_reader_reads_the_group_written_file_to_the_same_rows(
            self, tmp_path, monkeypatch, section):
        from tests.helpers.combine_groups import expected_view, reader_view
        with group_settings(tmp_path, monkeypatch) as settings:
            rows = three_rows(settings, section)
            assert settings.save_group(section, rows) == {'success': True}

            assert reader_view(settings, monkeypatch, section) == expected_view(section, rows)
