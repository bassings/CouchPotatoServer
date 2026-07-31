"""A rescan must not resurrect the exact copy the user set aside -- but must
still record a genuinely NEW copy at the same quality.

`Release.add` is the library scanner's entry point. It rebuilds the release doc
with a hardcoded `'status': 'done'`, never reading the current status, so any
release deliberately set aside is returned to 'done' by an unrelated
maintenance action ("Update Library", or the `library_refresh_interval` cron).

That silently breaks three features:
  - `tryNextRelease` ("Try next release") marks the snatched/done release
    'ignored' so the searcher picks something else;
  - `markFailedAndResearch` ("Mark Failed & re-search") marks it 'failed';
  - FEAT-008's `movie.restore_to_wanted` marks the held releases 'ignored'.
The first two are already in production.

The subtlety that made an earlier attempt a BLOCKER: `release_identifier` is
`<imdb>.<audio>.<quality>` -- a quality RUNG, not a per-copy key. Preserving
the status on that key alone means "never record ANY copy at this quality
again", so a re-downloaded 1080p lands on disk and is filed as 'ignored'; the
movie sits in Wanted forever and the searcher eventually re-snatches it, in a
loop. Worse for `markFailedAndResearch`, whose 'failed' rows render no action
button at all, leaving no way out.

So the rule keys on the COPY: the deliberate status is preserved only while the
scanned file set is the one that was set aside. Different files means a
different copy, which completes normally.
"""
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.plugins.release.main import Release

SET_ASIDE_FILES = {'movie': ['/movies/Some.Movie.1080p-OLD.mkv']}
NEW_COPY_FILES = {'movie': ['/movies/Some.Movie.1080p-NEW.mkv']}


def _group(files):
    return {
        'identifier': 'tt1234567',
        'meta_data': {'quality': {'identifier': '1080p', 'is_3d': 0}},
        'files': files,
    }


def _run_add(existing_status, existing_files, scanned_files, update_id=None):
    plugin = Release.__new__(Release)
    media = {'_id': 'movie-1', 'title': 'Some Movie', 'identifiers': {'imdb': 'tt1234567'}}
    existing = {
        '_id': 'rel-1', '_rev': 'rev-1', '_t': 'release',
        'media_id': 'movie-1', 'identifier': 'tt1234567.unknown.1080p',
        'quality': '1080p', 'status': existing_status,
        'files': existing_files, 'last_edit': 1000,
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
        plugin.add(_group(scanned_files), update_id=update_id)

    assert written, 'nothing was written'
    return written[-1]


PATHS = ['identifier-match', 'update_id']


def _update_id(path):
    return 'rel-1' if path == 'update_id' else None


class TestTheSetAsideCopyStaysSetAside:

    @pytest.mark.parametrize('path', PATHS)
    @pytest.mark.parametrize('status', ['ignored', 'failed'])
    def test_rescanning_the_same_file_preserves_the_status(self, path, status):
        written = _run_add(status, SET_ASIDE_FILES, SET_ASIDE_FILES, _update_id(path))

        assert written['status'] == status, (
            'a library rescan resurrected the very copy the user set aside, '
            "which silently undoes 'Try next release', 'Mark Failed & "
            "re-search' and 'Move back to wanted'"
        )


class TestANewCopyIsStillRecorded:
    """The half that makes this safe. Keying on the quality rung alone meant a
    re-downloaded copy was filed as 'ignored' -- the movie never completed and
    the searcher re-grabbed it on a weekly cadence."""

    @pytest.mark.parametrize('path', PATHS)
    @pytest.mark.parametrize('status', ['ignored', 'failed'])
    def test_a_different_file_at_the_same_quality_completes(self, path, status):
        written = _run_add(status, SET_ASIDE_FILES, NEW_COPY_FILES, _update_id(path))

        assert written['status'] == 'done', (
            'a genuinely new copy at the same quality was filed as %r, so the '
            'movie can never complete and will be downloaded again' % written['status']
        )

    @pytest.mark.parametrize('path', PATHS)
    @pytest.mark.parametrize('status', ['available', 'snatched', 'seeding', 'done', 'downloaded'])
    def test_every_other_status_is_still_completed(self, path, status):
        """Only deliberate set-aside statuses are preserved -- otherwise a
        rescan would stop recording that files exist, which is its whole job."""
        written = _run_add(status, SET_ASIDE_FILES, SET_ASIDE_FILES, _update_id(path))

        assert written['status'] == 'done'
