"""Release metadata was never stored (the non-latent half of the py2 cleanup).

`Release.createFromSearch()` seeds each release document with `'info': {}` and
then fills it in a loop. That loop's first statement was:

    if not isinstance(rel[info], (str, unicode, int, long, float)):

`unicode` and `long` do not exist in Python 3, so it raised NameError on the
first key of every release, on every install — swallowed by the loop's own
`except Exception: log.debug(...)`, which then moved to the next key and
raised again. `rls['info']` therefore stayed empty forever.

Two things fell out of that, both checked against master before the fix:

- `fix_release_quality` (the startup migration) reads `info.get('name')` and
  does `if not release_name: continue`, so it skipped every release and could
  never have repaired anything.
- "release table Size/Provider" is an outstanding gap in
  `specs/UI-MIGRATION.md`, consistent with the data never existing.

These tests drive `createFromSearch()` and assert on what lands in the
document, so they fail against the unfixed code rather than merely re-reading
the source.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.plugins.release.main import Release


@pytest.fixture
def plugin():
    return object.__new__(Release)


def _search_result(**overrides):
    """A provider result as `searcher.search` hands it over."""
    result = {
        'name': 'Some.Movie.2026.1080p.BluRay.x264-GROUP',
        'url': 'https://indexer.example/download/abc123',
        'size': 8543,
        'provider': 'TorrentPotato',
        'seeders': 42,
        'score': 17.5,
        'age': 3,
    }
    result.update(overrides)
    return result


def _run(plugin, results):
    """Drive createFromSearch, returning the stored release document."""
    stored = {}

    def fake_insert(doc):
        stored.update(doc)
        stored.setdefault('_id', 'release-1')
        stored.setdefault('_rev', '001')
        return stored

    db = MagicMock()
    db.insert.side_effect = fake_insert
    # No existing release for this identifier -> the insert branch.
    db.get.side_effect = KeyError('not found')

    def fake_fire_event(name, *args, **kwargs):
        if name == 'quality.guess':
            return {'identifier': '1080p', 'is_3d': False}
        return None

    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
            patch('couchpotato.core.plugins.release.main.fireEvent', side_effect=fake_fire_event), \
            patch('couchpotato.core.plugins.release.main.media_lock'):
        plugin.createFromSearch(
            results,
            {'_id': 'movie-1', 'title': 'Some Movie'},
            {'identifier': '1080p'},
        )

    return stored


class TestReleaseInfoIsPopulated:

    def test_string_fields_are_stored(self, plugin):
        """Bug repro: on the unfixed code `info` stays `{}` for every key,
        because the NameError fires before the first assignment."""
        stored = _run(plugin, [_search_result()])

        assert stored['info'].get('name') == 'Some.Movie.2026.1080p.BluRay.x264-GROUP'
        assert stored['info'].get('provider') == 'TorrentPotato'

    def test_numeric_fields_are_stored(self, plugin):
        """`size` is what the UI's release table shows, and `int`/`float` were
        in the original type tuple alongside the two dead names."""
        stored = _run(plugin, [_search_result()])

        assert stored['info'].get('size') == 8543
        assert stored['info'].get('seeders') == 42
        assert stored['info'].get('score') == 17.5

    def test_release_name_is_available_to_the_quality_migration(self, plugin):
        """`fix_release_quality` bails on `if not release_name: continue`, so
        an empty `info` made that whole migration a no-op."""
        stored = _run(plugin, [_search_result()])

        assert stored['info'].get('name'), (
            'fix_release_quality skips any release with no info["name"]'
        )

    def test_non_scalar_values_are_still_filtered_out(self, plugin):
        """The point of the type check is to keep functions and containers out
        of the document — widening it would put unserialisable values in the
        database."""
        stored = _run(plugin, [_search_result(
            callback=lambda: None,
            extra_dict={'a': 1},
            extra_list=[1, 2],
        )])

        assert 'callback' not in stored['info']
        assert 'extra_dict' not in stored['info']
        assert 'extra_list' not in stored['info']

    def test_a_large_integer_is_stored(self, plugin):
        """The original tuple listed `long` beside `int` for Python 2's split
        integer types. Python 3 has one unbounded `int`, so dropping `long`
        must not reject a value that exceeds the old 32-bit range."""
        stored = _run(plugin, [_search_result(size=2 ** 40)])

        assert stored['info'].get('size') == 2 ** 40

    def test_booleans_are_still_accepted(self, plugin):
        """`bool` subclasses `int`, so it passed the old tuple and must keep
        passing the new one — dropping it would silently lose flags."""
        stored = _run(plugin, [_search_result(verified=True)])

        assert stored['info'].get('verified') is True
