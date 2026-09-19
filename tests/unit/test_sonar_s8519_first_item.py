"""Contracts for Sonar reliability rule python:S8519.

The production expressions covered here need only the first yielded value.
Materialising the complete iterable is both unnecessary and unsafe for a
single-pass producer.  Keep the behavioral contracts beside one narrow AST
recurrence guard so this defect class is fixed as a class, not four times.
"""

import ast
from pathlib import Path

import pytest

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.media._base.searcher.main import Searcher
import couchpotato.core.plugins.profile.main as profile_module
from couchpotato.core.plugins.profile.main import ProfilePlugin
import couchpotato.core.plugins.renamer.main as renamer_module
from couchpotato.core.plugins.renamer.main import Renamer


REPO_ROOT = Path(__file__).resolve().parents[2]


def _direct_list_zero_lines(source):
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == 'list'
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == 0
    ]


def _production_violations():
    files = sorted((REPO_ROOT / 'couchpotato').rglob('*.py'))
    assert files, 'production Python inventory must not be empty'
    violations = []
    for path in files:
        for line in _direct_list_zero_lines(path.read_text(encoding='utf-8')):
            violations.append((path.relative_to(REPO_ROOT).as_posix(), line))
    return violations


@pytest.mark.parametrize(
    'source',
    [
        'value = list(items)[0]',
        'value = list(db.all())[0]',
        'value = list(factory().values())[0]',
    ],
)
def test_direct_list_zero_detector_rejects_formatting_variants(source):
    assert _direct_list_zero_lines(source) == [1]


@pytest.mark.parametrize(
    'source',
    [
        'value = sorted(list(items))[0]',
        'value = list(items)[1]',
        'value = list(items)[:1]',
        'value = list(items)',
    ],
)
def test_direct_list_zero_detector_allows_distinct_operations(source):
    assert _direct_list_zero_lines(source) == []


def test_production_has_no_direct_list_zero_materialization():
    assert _production_violations() == []


class _FirstThenExplodes:
    def __init__(self, first):
        self.first = first
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        yield self.first
        raise AssertionError('the first-item consumer requested a later row')


def test_profile_default_does_not_consume_past_the_first_row(monkeypatch):
    expected = {'_id': 'profile-first', 'order': 0}
    rows = _FirstThenExplodes({'doc': expected})

    class _DB:
        @staticmethod
        def all(index, limit=-1, with_doc=False):
            assert (index, limit, with_doc) == ('profile', 1, True)
            return rows

    monkeypatch.setattr(profile_module, 'get_db', lambda: _DB())

    assert ProfilePlugin.__new__(ProfilePlugin).default() == expected
    assert rows.iterations == 1


def test_profile_default_returns_none_when_no_profile_exists(monkeypatch):
    class _DB:
        @staticmethod
        def all(index, limit=-1, with_doc=False):
            assert (index, limit, with_doc) == ('profile', 1, True)
            return iter(())

    monkeypatch.setattr(profile_module, 'get_db', lambda: _DB())

    assert ProfilePlugin.__new__(ProfilePlugin).default() is None


def test_profile_default_uses_the_first_persisted_order(tmp_path, monkeypatch):
    db = SQLiteAdapter()
    db.create(str(tmp_path / 'profiles'))
    try:
        later = db.insert({'_t': 'profile', 'label': 'Later', 'order': 20})
        first = db.insert({'_t': 'profile', 'label': 'First', 'order': 10})
        monkeypatch.setattr(profile_module, 'get_db', lambda: db)

        selected = ProfilePlugin.__new__(ProfilePlugin).default()

        assert selected['_id'] == first['_id']
        assert selected['label'] == 'First'
        assert selected['_id'] != later['_id']
    finally:
        db.close()


class _RecordingLog:
    def __init__(self):
        self.info_calls = []

    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        self.info_calls.append((args, kwargs))


def test_renamer_logs_first_destination_and_moves_complete_mapping(monkeypatch):
    plugin = Renamer.__new__(Renamer)
    recorded = {}
    fake_log = _RecordingLog()

    settings = {
        'to': '/library',
        'unrar': False,
        'folder_name': '<folder>',
        'file_name': '<file>',
    }

    monkeypatch.setattr(type(plugin), 'conf', lambda _self, key, default=None: settings.get(key, default))
    monkeypatch.setattr(
        type(plugin), 'doReplace',
        lambda _self, pattern, replacements, folder=False: (
            'Movie Folder' if folder else 'part%s.%s' % (replacements['cd_nr'], replacements['ext'])
        ),
    )

    def _move(_self, mapping, group):
        recorded['mapping'] = dict(mapping)
        recorded['keys'] = list(mapping)
        recorded['group'] = group
        return 'moved'

    monkeypatch.setattr(type(plugin), '_moveRenamedFiles', _move)
    monkeypatch.setattr(renamer_module, 'log', fake_log)
    monkeypatch.setattr(renamer_module.os.path, 'isdir', lambda _path: True)

    group = {
        'media': {'identifier': 'tt1234567', 'info': {'title': 'Movie', 'year': 2020}},
        'files': {'movie': ['/source/first.mkv', '/source/second.avi']},
        'meta_data': {},
    }

    assert plugin._processGroup(group, media_folder='/library') == 'moved'

    expected = {
        '/source/first.mkv': '/library/Movie Folder/part1.mkv',
        '/source/second.avi': '/library/Movie Folder/part2.avi',
    }
    assert recorded == {
        'mapping': expected,
        'keys': list(expected),
        'group': group,
    }
    assert fake_log.info_calls[0][0] == (
        'Processing: %s -> %s',
        'Movie',
        expected['/source/first.mkv'],
    )


@pytest.mark.parametrize(
    ('parsed_name', 'movie_name', 'expected'),
    [
        ('sister act', 'Sister Act 3', False),
        ('frozen', 'Frozen II', False),
        ('avengers', 'The Avengers', True),
        ('the matrix', 'The Matrix', True),
        ('sister act', 'Sister Act Three Extended', False),
        ('', 'Matrix', False),
        ('matrix', '', False),
    ],
)
def test_searcher_single_missing_word_contract(monkeypatch, parsed_name, movie_name, expected):
    monkeypatch.setattr(
        'couchpotato.core.media._base.searcher.main.fireEvent',
        lambda *args, **kwargs: {'name': parsed_name, 'year': 2020},
    )

    result = Searcher().correctName(parsed_name, movie_name)

    assert result is expected
