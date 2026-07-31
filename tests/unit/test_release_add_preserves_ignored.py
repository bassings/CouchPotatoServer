"""A library rescan must not resurrect a deliberately-ignored release.

`Release.add` is the scanner's entry point. When a file it finds is already in
the database it rebuilds the release doc with a hardcoded `'status': 'done'`,
never reading the current status -- so any release the USER (or the app on the
user's behalf) has deliberately set aside is silently returned to 'done' by an
unrelated maintenance action.

This is not a FEAT-008 invention. Two features already depend on 'ignored'
sticking:

  - `MovieSearcher.tryNextRelease` ("Try next release") marks the snatched/done
    release 'ignored' so the searcher will pick something else.
  - FEAT-008's `movie.restore_to_wanted` marks the held releases 'ignored' so
    the movie is genuinely wanted again.

For both, a rescan -- the Manage tab's "Update Library" button, or the
`library_refresh_interval` cron -- resurrects the release, which then finishes
the movie again through `media.restatus` and blocks the search again through
`single()`'s has_better_quality loop. On a `manual_confirmation` profile (the
default) it also fires a false `movie.downloaded` "awaiting review"
notification for a movie that was never re-downloaded.

'failed' is preserved for the same reason: `markFailedAndResearch` sets it
deliberately, and a rescan finding the file on disk does not mean the download
was good.
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.plugins.release.main import Release


def _group(identifier='tt1234567'):
    return {
        'meta_data': {
            'quality': {'identifier': '1080p', 'is_3d': 0},
        },
        'files': {'movie': ['/movies/Some.Movie.1080p.mkv']},
        'identifier': identifier,
    }


def _run_add(existing_status, update_id=None):
    """Drive Release.add against a release doc that already exists."""
    plugin = Release.__new__(Release)
    media = {'_id': 'movie-1', 'title': 'Some Movie', 'identifiers': {'imdb': 'tt1234567'}}
    existing = {
        '_id': 'rel-1',
        '_rev': 'rev-1',
        '_t': 'release',
        'media_id': 'movie-1',
        'identifier': 'tt1234567.1080p',
        'quality': '1080p',
        'status': existing_status,
        'last_edit': 1000,
    }
    written = []

    db = MagicMock()

    def _get(index, key, **kwargs):
        if index == 'media':
            return {'doc': dict(media)}
        if index == 'id':
            return dict(existing)
        if index == 'release_identifier':
            return {'doc': dict(existing)} if kwargs.get('with_doc') else existing
        raise KeyError(key)

    db.get.side_effect = _get
    db.update.side_effect = lambda doc: written.append(dict(doc))

    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
            patch('couchpotato.core.plugins.release.main.fireEvent', return_value=None), \
            patch.object(type(plugin), 'conf', return_value=False, create=True):
        plugin.add(_group(), update_id=update_id)

    assert written, 'nothing was written'
    return written[-1]


class TestARescanDoesNotResurrectAnIgnoredRelease:

    @pytest.mark.parametrize('path', ['identifier-match', 'update_id'])
    def test_an_ignored_release_stays_ignored(self, path):
        written = _run_add('ignored', update_id='rel-1' if path == 'update_id' else None)

        assert written['status'] == 'ignored', (
            "a library rescan set a deliberately-ignored release back to %r, "
            "which silently undoes 'Try next release' and 'Move back to "
            "wanted' and re-fires the false downloaded notification"
            % written['status']
        )

    @pytest.mark.parametrize('path', ['identifier-match', 'update_id'])
    def test_a_failed_release_stays_failed(self, path):
        written = _run_add('failed', update_id='rel-1' if path == 'update_id' else None)

        assert written['status'] == 'failed', (
            'a rescan marked a failed download done just because the file is '
            'still on disk'
        )


class TestTheGuardIsNarrow:
    """Only deliberate set-aside statuses are preserved. Everything else must
    still be completed by the scan, or a rescan would stop recording that
    files exist -- which is the whole job of Release.add."""

    @pytest.mark.parametrize('status', ['available', 'snatched', 'seeding', 'done', 'downloaded'])
    def test_every_other_status_is_still_completed(self, status):
        written = _run_add(status)

        assert written['status'] == 'done', (
            'a rescan of a %r release must still mark it done; got %r'
            % (status, written['status'])
        )
