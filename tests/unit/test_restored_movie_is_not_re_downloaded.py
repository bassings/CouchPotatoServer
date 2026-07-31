"""A movie restored to wanted must not re-download the copy it just rejected.

A pre-production review raised this as a HIGH: `copy_id` is size-based, so a
BYTE-IDENTICAL re-grab of the same release matches the stored identity and stays
`ignored` — from which it inferred that the movie never completes, `cleanDone`
re-opens the search gate weekly, and the searcher re-downloads forever. On a
private tracker that would be real ratio damage.

Measured, the download half of that does not happen, and this file pins why:
`Release.createFromSearch` refreshes `rel['status']` from the stored doc for a
release it already knows about, and `Release.tryDownloadResult` filters
`('ignored', 'failed')`. So the user's own rejection is remembered across
searches and the release is never grabbed again.

What DOES remain is the movie sitting in Wanted until something better appears.
That is the correct outcome, not a defect: the user asked for a better copy and
none exists yet. It is pinned here too, so nobody "fixes" it into a re-download.
"""
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.plugins.release.main import Release


def _stored(status):
    return {'_id': 'rel-x', '_rev': 'r1', '_t': 'release', 'media_id': 'movie-1',
            'identifier': 'md5abc', 'quality': '1080p', 'status': status,
            'info': {}, 'last_edit': 1000}


def _search_results():
    """What a provider returns when it re-finds the same release."""
    # `size` and `score` are read directly by tryDownloadResult's own filters
    # (release/main.py) -- a fixture missing them fails for the wrong reason.
    return [{'name': 'Some.Movie.1080p-GRP', 'url': 'http://x/1', 'score': 10,
             'size': 8000, 'protocol': 'nzb', 'id': 'abc'}]


def _db_for(stored):
    db = MagicMock()

    def _get(index, key, **kw):
        if index == 'release_identifier':
            return {'doc': dict(stored)} if kw.get('with_doc') else stored
        raise KeyError(key)

    db.get.side_effect = _get
    db.update.side_effect = lambda d: None
    db.insert.side_effect = lambda d: dict(d, _id='new', _rev='r')
    return db


def _run(status):
    """Drive the real createFromSearch then the real tryDownloadResult."""
    plugin = Release.__new__(Release)
    results = _search_results()
    db = _db_for(_stored(status))

    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
            patch('couchpotato.core.plugins.release.main.fireEvent',
                  side_effect=lambda n, *a, **k: ({'identifier': '1080p', 'is_3d': False}
                                                  if n == 'quality.guess' else None)), \
            patch('couchpotato.core.plugins.release.main.md5', return_value='md5abc'):
        plugin.createFromSearch(results, {'_id': 'movie-1'}, {'identifier': '1080p'})

    downloaded = []

    def _fire(name, *a, **k):
        # 'release.download' is the real event (release/main.py). An earlier
        # version of this stub used 'download', which returned None for EVERY
        # case -- so "zero download attempts" was true for the rejected release
        # and the good one alike, and proved nothing. The positive-direction
        # test below is what caught it.
        if name == 'release.download':
            downloaded.append(k.get('data'))
            return True
        return None

    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
            patch('couchpotato.core.plugins.release.main.fireEvent', side_effect=_fire), \
            patch.object(type(plugin), 'conf', return_value=False, create=True):
        plugin.tryDownloadResult(results, {'_id': 'movie-1', 'title': 'M'},
                                 {'identifier': '1080p', 'minimum_score': 1})

    return results[0].get('status'), downloaded


class TestARejectedCopyIsNotGrabbedAgain:

    @pytest.mark.parametrize('status', ['ignored', 'failed'])
    def test_a_set_aside_release_is_never_re_downloaded(self, status):
        refreshed, downloaded = _run(status)

        assert refreshed == status, (
            "createFromSearch did not refresh rel['status'] from the stored doc, "
            'so tryDownloadResult cannot see that the user rejected this release'
        )
        assert downloaded == [], (
            'the searcher re-grabbed a release the user had already set aside — '
            'on a private tracker this is repeated, pointless ratio damage'
        )


class TestAWantedReleaseIsStillGrabbed:
    """The other direction: the filter must not stop a legitimate download, or
    'move back to wanted' could never be satisfied by anything."""

    def test_an_available_release_is_downloaded(self):
        refreshed, downloaded = _run('available')

        assert refreshed == 'available'
        assert downloaded, 'refused to download a perfectly good release'
