"""Tests for Release.createFromSearch() per-release ConflictError guard.

createFromSearch() loops over search_results and calls db.update(rls) to
persist each upserted release doc. Before this fix, a ConflictError raised
for just ONE release in that loop -- plausible because Release.updateStatus()
can concurrently mutate the very same release doc via its own CAS retry path
-- propagated all the way to the function-level `except Exception: ... return
[]` handler. That silently discarded every found_releases entry already
accumulated for the OTHER releases in the same batch, not just the one that
lost the CAS race. Mirrors the per-iteration guard already applied to
couchpotato/core/migration/fix_release_quality.py in this same PR.
"""
import logging
from unittest.mock import MagicMock, patch

from couchpotato import md5
from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.core.plugins.release.main import Release


def make_search_result(url, name, age=1):
    return {
        'url': url,
        'name': name,
        'age': age,
    }


def _make_db(conflicting_identifier):
    """A db double: db.get always misses on 'release_identifier' (forcing
    the insert path createFromSearch falls back to), and db.update raises
    ConflictError only for the one release whose identifier matches
    `conflicting_identifier` -- succeeding normally for the rest."""
    db = MagicMock()
    db.get.side_effect = Exception('release_identifier not found')
    db.insert.side_effect = lambda doc: dict(doc)

    def fake_update(doc):
        if doc.get('identifier') == conflicting_identifier:
            raise ConflictError(doc['identifier'])
        doc['_rev'] = 'v2'
        return doc

    db.update.side_effect = fake_update
    return db


def test_create_from_search_skips_conflicting_release_but_keeps_others(caplog):
    search_results = [
        make_search_result('http://example.com/a', 'Movie.A.2025.720p.BluRay'),
        make_search_result('http://example.com/b', 'Movie.B.2025.720p.BluRay'),
        make_search_result('http://example.com/c', 'Movie.C.2025.720p.BluRay'),
    ]
    conflicting_identifier = md5('http://example.com/b')

    db = _make_db(conflicting_identifier)
    quality = {'identifier': '720p', 'custom': {'3d': False}}
    media = {'_id': 'media-1'}

    plugin = Release.__new__(Release)
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
         patch('couchpotato.core.plugins.release.main.fireEvent',
               return_value={'identifier': '720p', 'is_3d': False}), \
         caplog.at_level(logging.WARNING, logger='couchpotato.core.plugins.release'):
        found_releases = plugin.createFromSearch(search_results, media, quality)

    expected_a = md5('http://example.com/a')
    expected_c = md5('http://example.com/c')

    # (a) did not raise (implicit -- we got here)
    # (b) + (c): partial found_releases -- the other two releases still
    # processed and returned, NOT an empty list.
    assert found_releases == [expected_a, expected_c]
    assert conflicting_identifier not in found_releases

    # db.update was attempted for all 3 -- the conflict on 'b' did not
    # abort the loop before reaching 'c'.
    assert db.update.call_count == 3

    # (d) a warning was logged for the skipped release, and nothing was
    # escalated to the generic ERROR-level "Failed: <traceback>" path.
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(warning_records) == 1
    assert conflicting_identifier in warning_records[0].getMessage()
    assert error_records == []


def test_create_from_search_returns_all_releases_when_no_conflict():
    """Happy-path contract must be unchanged: with no conflicts, all
    releases are processed and returned, and db.update is called once per
    release exactly as before this fix."""
    search_results = [
        make_search_result('http://example.com/a', 'Movie.A.2025.720p.BluRay'),
        make_search_result('http://example.com/b', 'Movie.B.2025.720p.BluRay'),
    ]

    db = _make_db(conflicting_identifier=None)
    quality = {'identifier': '720p', 'custom': {'3d': False}}
    media = {'_id': 'media-1'}

    plugin = Release.__new__(Release)
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
         patch('couchpotato.core.plugins.release.main.fireEvent',
               return_value={'identifier': '720p', 'is_3d': False}):
        found_releases = plugin.createFromSearch(search_results, media, quality)

    expected_a = md5('http://example.com/a')
    expected_b = md5('http://example.com/b')
    assert found_releases == [expected_a, expected_b]
    assert db.update.call_count == 2
