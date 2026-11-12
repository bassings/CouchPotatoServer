"""Characterisation of which movie file a group-based tag/untag acts on.

``tagRelease`` and ``untagRelease`` pick the lexicographically first path in
``group['files']['movie']`` and write or delete ignore markers next to it.
These tests pin that selection so the expression that computes it can be
simplified without changing which file is touched.
"""
from pathlib import Path

import pytest

from couchpotato.core.plugins.renamer.cleanup import CleanupMixin


class _Cleanup(CleanupMixin):
    def createFile(self, filename, text):
        Path(filename).write_text(text)


def _group(folder, movies):
    return {'files': {'movie': movies}, 'parentdir': str(folder), 'dirname': 'release'}


def _markers(folder):
    return sorted(p.name for p in Path(folder).iterdir() if p.name.endswith('.ignore'))


def _movies(folder, names):
    paths = []
    for name in names:
        path = Path(folder) / name
        path.write_text('media')
        paths.append(str(path))
    return paths


@pytest.mark.parametrize('container', [set, frozenset, list, tuple, iter])
def test_tag_marks_only_the_first_path_whatever_the_container(tmp_path, container):
    paths = _movies(tmp_path, ['b.mkv', 'c.mkv', 'a.mkv'])

    _Cleanup().tagRelease('hold', group=_group(tmp_path, container(paths)))

    assert _markers(tmp_path) == ['a.hold.ignore']


def test_tag_single_item_is_marked(tmp_path):
    paths = _movies(tmp_path, ['only.mkv'])

    _Cleanup().tagRelease('hold', group=_group(tmp_path, {paths[0]}))

    assert _markers(tmp_path) == ['only.hold.ignore']


def test_tag_tie_on_equal_paths_marks_that_one_path(tmp_path):
    paths = _movies(tmp_path, ['a.mkv', 'b.mkv'])

    _Cleanup().tagRelease('hold', group=_group(tmp_path, [paths[0], paths[0], paths[1]]))

    assert _markers(tmp_path) == ['a.hold.ignore']


def test_tag_orders_by_code_point_not_case(tmp_path):
    paths = _movies(tmp_path, ['a.mkv', 'B.mkv'])

    _Cleanup().tagRelease('hold', group=_group(tmp_path, set(paths)))

    # 'B' (66) sorts before 'a' (97)
    assert _markers(tmp_path) == ['B.hold.ignore']


def test_tag_does_not_mutate_the_callers_collection(tmp_path):
    paths = _movies(tmp_path, ['b.mkv', 'a.mkv'])
    movies = [paths[0], paths[1]]

    _Cleanup().tagRelease('hold', group=_group(tmp_path, movies))

    assert movies == paths


def test_tag_with_no_movie_files_raises_and_writes_nothing(tmp_path):
    with pytest.raises((IndexError, ValueError)):
        _Cleanup().tagRelease('hold', group=_group(tmp_path, set()))

    assert list(tmp_path.iterdir()) == []


def test_tag_with_unorderable_mixed_types_raises_and_writes_nothing(tmp_path):
    paths = _movies(tmp_path, ['a.mkv'])

    with pytest.raises(TypeError):
        _Cleanup().tagRelease('hold', group=_group(tmp_path, [paths[0], 7]))

    assert _markers(tmp_path) == []


@pytest.mark.parametrize('container', [set, frozenset, list, tuple, iter])
def test_untag_removes_only_the_first_paths_marker(tmp_path, container):
    paths = _movies(tmp_path, ['b.mkv', 'c.mkv', 'a.mkv'])
    for stem in 'abc':
        (tmp_path / f'{stem}.hold.ignore').write_text('tag')

    _Cleanup().untagRelease(group=_group(tmp_path, container(paths)),
                            release_download={'folder': str(tmp_path), 'files': []}, tag='hold')

    assert _markers(tmp_path) == ['b.hold.ignore', 'c.hold.ignore']
    assert sorted(p.name for p in tmp_path.glob('*.mkv')) == ['a.mkv', 'b.mkv', 'c.mkv']


def test_untag_tie_on_equal_paths_removes_that_marker_only(tmp_path):
    paths = _movies(tmp_path, ['a.mkv', 'b.mkv'])
    for stem in 'ab':
        (tmp_path / f'{stem}.hold.ignore').write_text('tag')

    _Cleanup().untagRelease(group=_group(tmp_path, [paths[0], paths[0], paths[1]]),
                            release_download={'folder': str(tmp_path), 'files': []}, tag='hold')

    assert _markers(tmp_path) == ['b.hold.ignore']


def test_untag_does_not_mutate_the_callers_collection(tmp_path):
    paths = _movies(tmp_path, ['b.mkv', 'a.mkv'])
    movies = [paths[0], paths[1]]
    (tmp_path / 'a.hold.ignore').write_text('tag')

    _Cleanup().untagRelease(group=_group(tmp_path, movies),
                            release_download={'folder': str(tmp_path), 'files': []}, tag='hold')

    assert movies == paths


def test_untag_with_no_movie_files_raises_and_removes_nothing(tmp_path):
    (tmp_path / 'a.hold.ignore').write_text('tag')

    with pytest.raises((IndexError, ValueError)):
        _Cleanup().untagRelease(group=_group(tmp_path, set()),
                                release_download={'folder': str(tmp_path), 'files': []}, tag='hold')

    assert _markers(tmp_path) == ['a.hold.ignore']


def test_untag_with_unorderable_mixed_types_raises_and_removes_nothing(tmp_path):
    paths = _movies(tmp_path, ['a.mkv'])
    (tmp_path / 'a.hold.ignore').write_text('tag')

    with pytest.raises(TypeError):
        _Cleanup().untagRelease(group=_group(tmp_path, [paths[0], 7]),
                                release_download={'folder': str(tmp_path), 'files': []}, tag='hold')

    assert _markers(tmp_path) == ['a.hold.ignore']


def test_untag_missing_parentdir_returns_false(tmp_path):
    group = _group(tmp_path / 'gone', {str(tmp_path / 'a.mkv')})

    assert _Cleanup().untagRelease(group=group, release_download={'folder': 'x', 'files': []}) is False
