"""A set-aside release must survive a rescan -- without blocking a NEW copy.

FEAT-009 Part A (specs/FEAT-009-durable-set-aside-and-upgrade-replacement.md).

`Release.add` rebuilds the release doc with a hardcoded 'done' and never reads
the current status, so every full library scan resurrects a release that
`tryNextRelease`, `markFailedAndResearch` or `movie.restore_to_wanted`
deliberately set aside.

Two earlier attempts to fix that were unsound, and both directions must be
pinned here because each failure mode shipped once:

  - keyed on `release_identifier` (`<imdb>.<audio>.<quality>`): a quality RUNG,
    so it meant "never record any copy at this quality again" -- a re-downloaded
    1080p was filed 'ignored', the movie never completed, and the searcher
    re-grabbed it weekly;
  - keyed on the scanned FILE SET: `folder_scanner.py:270` builds the list from
    a `set`, so ordering is hash-randomised across processes (one unchanged
    folder produced 9 orderings across 14 processes), AND the default renamer
    naming gives every copy of a movie the same path, so a new copy looked
    identical.

The identity used here is the sorted SIZES of the movie files. Sizes are
immune to both: sorting removes scanner ordering, and two different encodes
essentially never share a byte count even when they land on the same path.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.plugins.release.main import Release


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return str(p)


def _group(files):
    return {
        'identifier': 'tt1234567',
        'meta_data': {'quality': {'identifier': '1080p', 'is_3d': 0}},
        'files': files,
    }


def _run_add(existing_status, existing_copy_id, scanned_files, existing_files=None):
    plugin = Release.__new__(Release)
    media = {'_id': 'movie-1', 'title': 'Some Movie', 'identifiers': {'imdb': 'tt1234567'}}
    existing = {
        '_id': 'rel-1', '_rev': 'rev-1', '_t': 'release',
        'media_id': 'movie-1', 'identifier': 'tt1234567.unknown.1080p',
        'quality': '1080p', 'status': existing_status,
        'files': existing_files if existing_files is not None else {'movie': ['/old/path.mkv']},
        'last_edit': 1000,
    }
    if existing_copy_id is not None:
        existing['copy_id'] = existing_copy_id

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
        plugin.add(_group(scanned_files))

    assert written, 'nothing was written'
    return written[-1]


def _copy_id_of(paths):
    from couchpotato.core.plugins.release.main import copyIdentity
    return copyIdentity({'movie': paths})


class TestTheSetAsideCopySurvivesARescan:

    @pytest.mark.parametrize('status', ['ignored', 'failed'])
    def test_rescanning_the_same_copy_preserves_the_status(self, tmp_path, status):
        movie = _write(tmp_path, 'lib/Some Movie.mkv', 'A' * 5000)
        files = {'movie': [movie]}

        written = _run_add(status, _copy_id_of([movie]), files)

        assert written['status'] == status, (
            'a library rescan resurrected the copy the user set aside, which '
            "silently undoes 'Try next release', 'Mark Failed & re-search' "
            "and 'Move back to wanted'"
        )

    def test_scanner_ordering_does_not_matter(self, tmp_path):
        """folder_scanner builds its list from a set, so the order differs
        between processes. A multi-file (CD1/CD2) release must still match."""
        a = _write(tmp_path, 'lib/Movie.cd1.mkv', 'A' * 4000)
        b = _write(tmp_path, 'lib/Movie.cd2.mkv', 'B' * 7000)

        written = _run_add('ignored', _copy_id_of([a, b]), {'movie': [b, a]})

        assert written['status'] == 'ignored', 'reversed scan order broke the match'

    def test_incidental_files_appearing_alongside_do_not_clear_it(self, tmp_path):
        """Bazarr dropping a .srt, or Plex writing poster.jpg, must not count
        as a different copy -- only the media file defines the copy."""
        movie = _write(tmp_path, 'lib/Some Movie.mkv', 'A' * 5000)
        sub = _write(tmp_path, 'lib/Some Movie.srt', 'subs')
        art = _write(tmp_path, 'lib/poster.jpg', 'jpeg')

        written = _run_add('ignored', _copy_id_of([movie]),
                           {'movie': [movie], 'subtitle': [sub], 'leftover': [art]})

        assert written['status'] == 'ignored', (
            'an unrelated file appearing next to the movie cleared the mark'
        )


class TestANewCopyIsStillRecorded:
    """The direction that shipped a weekly re-download loop TWICE. Under the
    default renamer naming every copy of a movie lands on the SAME path, so
    path equality cannot be the test -- only the size differs."""

    @pytest.mark.parametrize('status', ['ignored', 'failed'])
    def test_a_different_copy_at_the_same_path_completes(self, tmp_path, status):
        path = _write(tmp_path, 'lib/Some Movie.mkv', 'A' * 5000)
        set_aside_id = _copy_id_of([path])

        # The replacement lands at exactly the same path -- a bigger encode.
        with open(path, 'w') as fh:
            fh.write('B' * 9000)

        written = _run_add(status, set_aside_id, {'movie': [path]})

        assert written['status'] == 'done', (
            'a genuinely new copy was filed as %r, so the movie can never '
            'complete and will be downloaded again' % written['status']
        )


class TestItDegradesToTodaysBehaviour:
    """Anything it cannot decide must fall back to master's 'done'."""

    def test_a_release_with_no_stored_copy_id_completes(self, tmp_path):
        """Every release that exists before this change, and every doc created
        by createFromSearch (which stores no files)."""
        movie = _write(tmp_path, 'lib/Some Movie.mkv', 'A' * 5000)

        written = _run_add('ignored', None, {'movie': [movie]})

        assert written['status'] == 'done'

    def test_an_unreadable_file_completes(self, tmp_path):
        written = _run_add('ignored', 'whatever', {'movie': ['/does/not/exist.mkv']})

        assert written['status'] == 'done'

    def test_a_scan_with_no_movie_file_completes(self, tmp_path):
        sub = _write(tmp_path, 'lib/Some Movie.srt', 'subs')

        written = _run_add('ignored', 'whatever', {'subtitle': [sub]})

        assert written['status'] == 'done'

    @pytest.mark.parametrize('status', ['available', 'snatched', 'seeding', 'done', 'downloaded'])
    def test_every_other_status_is_still_completed(self, tmp_path, status):
        movie = _write(tmp_path, 'lib/Some Movie.mkv', 'A' * 5000)

        written = _run_add(status, _copy_id_of([movie]), {'movie': [movie]})

        assert written['status'] == 'done'


class TestTheIdentityIsStored:

    def test_a_scan_records_the_copy_id_for_next_time(self, tmp_path):
        movie = _write(tmp_path, 'lib/Some Movie.mkv', 'A' * 5000)

        written = _run_add('done', None, {'movie': [movie]})

        assert written.get('copy_id') == _copy_id_of([movie]), (
            'without storing it, the next rescan has nothing to compare '
            'against and the guard can never engage'
        )
