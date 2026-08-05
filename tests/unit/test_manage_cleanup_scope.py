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


def _run_cleanup():
    """Drive updateLibrary's cleanup and return the media ids it deleted.

    Deliberately does NOT swallow exceptions. An early failure would leave the
    delete list empty and make every assertion below pass without the code under
    test ever running, which is what made the first draft of this file useless.
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
         patch.object(Manage, 'directories', lambda self: []), \
         patch.object(Manage, 'isDisabled', lambda self: False), \
         patch.object(Manage, 'shuttingDown', lambda self: False), \
         patch('couchpotato.core.plugins.manage.fireEvent', side_effect=fake_fire), \
         patch('couchpotato.core.plugins.manage.Env') as env:
        env.prop.return_value = 0
        plugin.updateLibrary(full=True)

    return deleted


class TestCleanupOnlyDeletesTerminalMovies:

    def test_the_delete_path_actually_ran(self):
        """Guards the other two assertions from passing vacuously.

        No seeded movie is in `added_identifiers` (directories() is empty), so a
        cleanup that reaches the loop MUST delete the genuinely-done movie. If
        this fails, the scenario never exercised the code and the assertions
        below prove nothing.
        """
        assert 'terminal' in _run_cleanup(), (
            'the cleanup loop did not run: the rest of this file is vacuous'
        )

    def test_an_active_movie_with_a_done_release_is_not_deleted(self):
        assert 'upgrading' not in _run_cleanup(), (
            "'active' with a done release is the ordinary upgrade-hunt state, "
            'not an offline movie: deleting it destroys the library entry, '
            'watch state, tags and profile assignment'
        )

    def test_a_movie_awaiting_review_is_not_deleted(self):
        assert 'reviewing' not in _run_cleanup(), (
            'a movie in the manual-review gate is not offline'
        )
