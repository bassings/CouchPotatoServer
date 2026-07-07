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


def make_full_search_result(url, name, age=1, score=100, size=1000):
    """A search-result dict shaped like what tryDownloadResult() expects
    (score/size present, as a real provider's fillResult() would supply),
    but deliberately WITHOUT a 'status' key -- exactly like a fresh
    provider result before createFromSearch() has (or hasn't, in the
    conflict case) stamped one on."""
    result = make_search_result(url, name, age=age)
    result['score'] = score
    result['size'] = size
    return result


def test_conflict_skip_sets_status_so_try_download_result_does_not_crash():
    """End-to-end reproduction of the bug: createFromSearch() hits a
    ConflictError for one release in the batch, then the SAME
    search_results list (mutated in place -- these are the caller's dict
    objects, not copies) is fed into tryDownloadResult(), exactly as
    searcher.py does by firing 'release.create_from_search' and then
    'release.try_download_result' over the same `results` list.

    Before the fix, the conflicted release never got a 'status' key
    (the `continue` skipped the assignment), so tryDownloadResult()'s
    unguarded `rel['status']` raised KeyError on it -- aborting processing
    of the ENTIRE batch, including the other, perfectly downloadable
    releases that come after it in the list.
    """
    search_results = [
        make_full_search_result('http://example.com/a', 'Movie.A.2025.720p.BluRay'),
        make_full_search_result('http://example.com/b', 'Movie.B.2025.720p.BluRay'),
        make_full_search_result('http://example.com/c', 'Movie.C.2025.720p.BluRay'),
    ]
    conflicting_identifier = md5('http://example.com/b')

    db = _make_db(conflicting_identifier)
    quality = {'identifier': '720p', 'custom': {'3d': False}}
    quality_custom = {'minimum_score': 0}
    media = {'_id': 'media-1'}

    plugin = Release.__new__(Release)
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
         patch('couchpotato.core.plugins.release.main.fireEvent',
               return_value={'identifier': '720p', 'is_3d': False}):
        plugin.createFromSearch(search_results, media, quality)

    # The conflicted release ('b') must have a 'status' key -- not missing.
    conflicted_rel = next(r for r in search_results if md5(r['url']) == conflicting_identifier)
    assert 'status' in conflicted_rel
    assert conflicted_rel['status'] == 'available'

    # Now feed the SAME list into tryDownloadResult, as searcher.py does.
    download_calls = []

    def fake_fire_event(event_name, *args, **kwargs):
        if event_name == 'release.download':
            download_calls.append(kwargs.get('data'))
            return 'try_next'
        return None

    with patch('couchpotato.core.plugins.release.main.fireEvent', side_effect=fake_fire_event), \
         patch('couchpotato.core.plugins.release.main.Env.setting', return_value=1):
        # No KeyError raised -- this is the crash the fix prevents.
        result = plugin.tryDownloadResult(search_results, media, quality_custom)

    assert result is False  # nothing "waited for", none returned True
    # All three releases -- including the previously-conflicted one --
    # were processed normally, not silently dropped by an aborted batch.
    assert len(download_calls) == 3
    downloaded_urls = {rel['url'] for rel in download_calls}
    assert downloaded_urls == {
        'http://example.com/a',
        'http://example.com/b',
        'http://example.com/c',
    }


def _make_db_with_authoritative_reread(conflicting_identifier, existing_doc, authoritative_result):
    """A db double for the "re-read authoritative status on conflict" fix.

    Unlike `_make_db()` above (which always misses the `release_identifier`
    lookup, forcing the insert path), this fixture makes that lookup HIT for
    `conflicting_identifier` -- returning `existing_doc` (the STALE
    pre-conflict copy, carrying whatever status the test wants to prove is
    NOT used). `db.update()` then raises ConflictError for that same release,
    exactly like a concurrent writer (e.g. updateStatus()) won the race.

    `authoritative_result` controls what the post-conflict re-read
    (`db.get('id', existing_doc['_id'])`) does:
      - a dict -> returns that dict (the authoritative current doc)
      - an Exception instance -> raises it (e.g. concurrent delete)
    """
    db = MagicMock()

    def fake_get(index_name, key, with_doc=False):
        if index_name == 'release_identifier':
            if key == conflicting_identifier:
                return {'doc': dict(existing_doc), '_id': existing_doc['_id']}
            raise Exception('release_identifier not found')
        if index_name == 'id':
            if key == existing_doc['_id']:
                if isinstance(authoritative_result, Exception):
                    raise authoritative_result
                return dict(authoritative_result)
            raise KeyError(key)
        raise AssertionError(f'unexpected index_name in test double: {index_name}')

    db.get.side_effect = fake_get
    db.insert.side_effect = lambda doc: dict(doc)

    def fake_update(doc):
        if doc.get('identifier') == conflicting_identifier:
            raise ConflictError(doc['identifier'])
        doc['_rev'] = 'v2'
        return doc

    db.update.side_effect = fake_update
    return db


def test_create_from_search_conflict_uses_authoritative_status_not_stale_copy():
    """The core regression this fix closes: on ConflictError, the skip must
    re-read the CURRENT (authoritative) doc from the DB rather than reusing
    the stale pre-write copy (`rls`) -- the conflict happened precisely
    because a concurrent writer (e.g. updateStatus(release_id, 'ignored'))
    already changed this release's status in the DB. Using the stale copy
    would silently stamp a just-ignored release back to 'available'.

    The stale copy here carries status='available'; the authoritative doc
    carries status='ignored' -- deliberately different values so the
    assertion actually distinguishes stale-vs-authoritative. Against the
    pre-fix code (`rel['status'] = rls.get('status', 'available')`), this
    test fails because it would observe 'available' instead of 'ignored'.
    """
    conflicting_identifier = md5('http://example.com/b')
    existing_doc = {
        '_id': 'rel-existing-b',
        '_t': 'release',
        'identifier': conflicting_identifier,
        'quality': '720p',
        'status': 'available',  # STALE -- must NOT end up on rel['status']
    }
    authoritative_doc = {
        '_id': 'rel-existing-b',
        '_t': 'release',
        'identifier': conflicting_identifier,
        'quality': '720p',
        'status': 'ignored',  # set by a concurrent updateStatus() call
    }

    search_results = [make_search_result('http://example.com/b', 'Movie.B.2025.720p.BluRay')]
    db = _make_db_with_authoritative_reread(conflicting_identifier, existing_doc, authoritative_doc)
    quality = {'identifier': '720p', 'custom': {'3d': False}}
    media = {'_id': 'media-1'}

    plugin = Release.__new__(Release)
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
         patch('couchpotato.core.plugins.release.main.fireEvent',
               return_value={'identifier': '720p', 'is_3d': False}):
        plugin.createFromSearch(search_results, media, quality)

    assert search_results[0]['status'] == 'ignored'
    assert search_results[0]['status'] != existing_doc['status']


def test_create_from_search_conflict_falls_back_to_available_on_concurrent_delete():
    """If the release was deleted concurrently (not just status-changed),
    the post-conflict re-read (`db.get('id', ...)`) raises the adapter's
    "not found" exception (KeyError for SQLiteAdapter). This must not crash
    createFromSearch() -- it should fall back to the harmless 'available'
    placeholder, same as before any release existed."""
    conflicting_identifier = md5('http://example.com/b')
    existing_doc = {
        '_id': 'rel-existing-b',
        '_t': 'release',
        'identifier': conflicting_identifier,
        'quality': '720p',
        'status': 'busy',  # any stale value; must not leak through either
    }

    search_results = [make_search_result('http://example.com/b', 'Movie.B.2025.720p.BluRay')]
    db = _make_db_with_authoritative_reread(
        conflicting_identifier, existing_doc,
        KeyError(f"Document not found: {existing_doc['_id']}"),
    )
    quality = {'identifier': '720p', 'custom': {'3d': False}}
    media = {'_id': 'media-1'}

    plugin = Release.__new__(Release)
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
         patch('couchpotato.core.plugins.release.main.fireEvent',
               return_value={'identifier': '720p', 'is_3d': False}):
        # Must not raise.
        found_releases = plugin.createFromSearch(search_results, media, quality)

    assert search_results[0]['status'] == 'available'
    assert found_releases == []  # 'available' status alone isn't enough here --
    # the release was skipped via `continue`, never appended.


def test_try_download_result_missing_status_key_does_not_crash():
    """Minimal, direct proof of the defensive consumer fix: a result dict
    with NO 'status' key at all (as any raw provider result looks before
    createFromSearch() ever runs) must not raise KeyError -- it should be
    treated like a normal, non-ignored/failed candidate."""
    rel = make_full_search_result('http://example.com/only', 'Movie.Only.2025.720p.BluRay')
    assert 'status' not in rel

    quality_custom = {'minimum_score': 0}
    media = {'_id': 'media-1'}

    with patch('couchpotato.core.plugins.release.main.fireEvent', return_value=True), \
         patch('couchpotato.core.plugins.release.main.Env.setting', return_value=1):
        plugin = Release.__new__(Release)
        result = plugin.tryDownloadResult([rel], media, quality_custom)

    assert result is True
