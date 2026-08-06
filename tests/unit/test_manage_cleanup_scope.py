"""The unattended cleanup scan must only delete genuinely terminal movies.

`Manage.updateLibrary`'s cleanup queries `media.list` as a status_or union of
`status='done'` and `release_status='done'`. The second half admits movies whose
MEDIA status is not 'done' at all:

  'downloaded'  the workflow phase 2 review gate, awaiting manual review
  'active'      the ordinary upgrade-hunt state, a movie holding a finished
                release that does not satisfy quality.isFinish (grabbed the
                720p, still hunting the 1080p)

Neither is offline. Both used to reach `media.delete(delete_from='all')`, which
removes every release document and the media document.

This was survivable only because the release_status half of the union returned
nothing: `Release.withStatus` dropped `with_doc`, so `media_id` was always None
and the filter set was {None}. T1.9 fixed that lookup and made the half live,
which turned a latent gap into a real delete on a movie the user is upgrading.

Driven against the real `Manage.updateLibrary`, not a mocked `media.list`. The
pre-existing test for this path mocks the query and feeds `done_movies` in
directly, which is exactly why it stayed green through the whole period the real
lookup returned nothing.
"""
import threading
from unittest.mock import patch


MOVIES = [
    {'_id': 'terminal', 'status': 'done', 'identifiers': {'imdb': 'tt1'}, 'releases': []},
    {'_id': 'upgrading', 'status': 'active', 'identifiers': {'imdb': 'tt2'}, 'releases': []},
    {'_id': 'reviewing', 'status': 'downloaded', 'identifiers': {'imdb': 'tt3'}, 'releases': []},
]


def _run_cleanup(directories=None):
    """Drive updateLibrary's cleanup and return the media ids it deleted.

    Deliberately does NOT swallow exceptions. An early failure would leave the
    delete list empty and make every assertion below pass without the code under
    test ever running, which is what made the first draft of this file useless.

    `directories` defaults to `[]` -- NO configured library at all. That is the
    shape the original version of this file hard-coded, and it is worth naming:
    it meant every assertion here was made about a scan that never looked at a
    library, which is precisely the case that must NOT delete anything.
    """
    from couchpotato.core.plugins.manage import Manage

    deleted = []

    def fake_fire(event, *args, **kwargs):
        if event == 'media.list':
            return (len(MOVIES), MOVIES)
        if event == 'media.delete':
            deleted.append(kwargs.get('media_id'))
        return []

    plugin = Manage.__new__(Manage)
    plugin._progress_lock = threading.Lock()
    plugin.in_progress = False

    with patch.object(Manage, 'conf', lambda self, key, **kw: True if key == 'cleanup' else None), \
         patch.object(Manage, 'directories', lambda self: list(directories or [])), \
         patch.object(Manage, 'isDisabled', lambda self: False), \
         patch.object(Manage, 'shuttingDown', lambda self: False), \
         patch('couchpotato.core.plugins.manage.fireEvent', side_effect=fake_fire), \
         patch('couchpotato.core.plugins.manage.Env') as env:
        env.prop.return_value = 0
        plugin.updateLibrary(full=True)

    return deleted


class TestCleanupOnlyDeletesTerminalMovies:
    """Every test here supplies a VISIBLE directory, deliberately.

    These originally ran with `directories() == []`, which now correctly
    disarms the cleanup entirely -- so the two "is not deleted" assertions
    would pass without the cleanup loop ever running, and prove nothing. A
    visible directory keeps the delete path live so the exemptions are what is
    actually being measured. `test_the_delete_path_actually_ran` is the guard
    that proves it.
    """

    def test_the_delete_path_actually_ran(self, tmp_path):
        """Guards the other two assertions from passing vacuously.

        No seeded movie is in `added_identifiers` (nothing is scanned into it),
        so a cleanup that reaches the loop MUST delete the genuinely-done
        movie. If this fails, the scenario never exercised the code and the
        assertions below prove nothing.
        """
        library = tmp_path / 'library'
        library.mkdir()
        assert 'terminal' in _run_cleanup(directories=[str(library)]), (
            'the cleanup loop did not run: the rest of this file is vacuous'
        )

    def test_an_active_movie_with_a_done_release_is_not_deleted(self, tmp_path):
        library = tmp_path / 'library'
        library.mkdir()
        assert 'upgrading' not in _run_cleanup(directories=[str(library)]), (
            "'active' with a done release is the ordinary upgrade-hunt state, "
            'not an offline movie: deleting it destroys the library entry, '
            'watch state, tags and profile assignment'
        )

    def test_a_movie_awaiting_review_is_not_deleted(self, tmp_path):
        library = tmp_path / 'library'
        library.mkdir()
        assert 'reviewing' not in _run_cleanup(directories=[str(library)]), (
            'a movie in the manual-review gate is not offline'
        )


class TestCleanupNeverRunsOnALibraryItCouldNotSee:
    """A scan that did not see the library must not conclude the library is gone.

    `updateLibrary` builds `added_identifiers` by scanning each configured
    directory. A directory that fails `os.path.isdir` is logged and SKIPPED
    (`manage.py:124-127`) -- and nothing records that it was skipped. The
    cleanup pass below then deletes every `status == 'done'` movie that is not
    in `added_identifiers`, with `delete_from='all'`: the media document, every
    release document, library entry, watch state, tags, profile and review
    state. Unrecoverable without a backup, and nobody takes one before a
    scheduled library scan.

    So an unmounted NAS at scan time purges the library. That is not
    hypothetical on the hardware this project runs on: the library lives on an
    NFS mount that is known to stall and drop, and `full` scans are scheduled
    (`manage.py`'s cron), so the two coincide unattended.

    The `status != 'done'` guard added earlier in this PR narrowed the blast
    radius to genuinely-terminal movies. It does not close this: those are
    exactly the movies a mounted library would have re-found.
    """

    def test_a_missing_directory_cancels_the_cleanup_entirely(self, tmp_path):
        missing = str(tmp_path / 'nas-not-mounted')
        assert not _run_cleanup(directories=[missing]), (
            'the library was unreachable and the cleanup deleted anyway: a '
            'mount flap during a scheduled scan destroys the library'
        )

    def test_one_missing_directory_among_several_still_cancels_it(self, tmp_path):
        present = tmp_path / 'mounted'
        present.mkdir()
        assert not _run_cleanup(directories=[str(present), str(tmp_path / 'gone')]), (
            'a partially-visible library is still a library this scan did not '
            'fully see; deleting on it is the same defect with extra steps'
        )

    def test_no_configured_directory_at_all_cancels_it(self):
        # The default shape of the harness above, and the one the original
        # version of this file asserted was correct.
        assert not _run_cleanup(directories=[]), (
            'with no library configured there is nothing to compare against, '
            'so every done movie looks missing'
        )

    def test_a_fully_visible_library_still_cleans_up(self, tmp_path):
        """The guard must not buy safety by disabling the feature.

        With every configured directory present, cleanup runs exactly as
        before -- the seeded 'terminal' movie is not in `added_identifiers`
        (nothing is scanned into it here) and is deleted.
        """
        present = tmp_path / 'mounted'
        present.mkdir()
        assert 'terminal' in _run_cleanup(directories=[str(present)]), (
            'the guard disabled cleanup even when the whole library was '
            'visible: that is not a fix, it is a removal'
        )
