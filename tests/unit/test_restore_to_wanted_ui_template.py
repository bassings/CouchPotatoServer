"""Render tests for FEAT-008's "Move back to wanted" control in
``couchpotato/ui/templates/partials/movie_detail.html``.

Mirrors ``tests/unit/test_review_actions_ui_template.py``: renders the real
Jinja partial (not a copy) with fabricated ``movie`` dicts so the gating --
shown only for a ``done`` movie -- is pinned against the actual template
rather than a description of it.
"""

from couchpotato.environment import Env
from couchpotato.ui import _jinja, _releases_ctx


def _render(movie):
    Env.set('web_base', '/')
    ctx = {
        'api_key': 'test-key',
        'api_base': '/api/test-key',
        'web_base': '/',
        'new_base': '/',
        'movie': movie,
    }
    ctx.update(_releases_ctx(movie, movie.get('_id', ''), {}))
    return _jinja.get_template('partials/movie_detail.html').render(**ctx)


def _movie(status):
    return {
        '_id': 'movie-1',
        'status': status,
        'info': {'titles': ['Fixture Movie'], 'year': 2021},
        'profile': {'label': 'HD', 'qualities': []},
        'releases': [],
    }


class TestRestoreToWantedButtonGating:

    def test_shown_for_a_done_movie(self):
        html = _render(_movie('done'))

        assert 'data-testid="restore-to-wanted"' in html
        assert 'Move back to wanted' in html

    def test_hidden_for_an_active_movie(self):
        """AC6: only 'done' -- an already-wanted movie has nothing to
        restore."""
        html = _render(_movie('active'))

        assert 'data-testid="restore-to-wanted"' not in html

    def test_hidden_for_a_movie_awaiting_review(self):
        """A 'downloaded' movie is mid-workflow (Phase 1 review gate), not
        the terminal 'done' state this control exists to reverse."""
        html = _render(_movie('downloaded'))

        assert 'data-testid="restore-to-wanted"' not in html


class TestRestoreToWantedButtonWiring:

    def _render_done(self):
        return _render(_movie('done'))

    def test_it_calls_the_restore_to_wanted_endpoint(self):
        html = self._render_done()

        assert 'movie.restore_to_wanted' in html

    def test_it_includes_a_profile_picker(self):
        """AC6: a profile picker, not a one-click action -- the movie may
        need a specific profile, not just whatever the default is."""
        html = self._render_done()

        assert '<select' in html
        assert 'selectedProfile' in html

    def test_it_updates_in_place_rather_than_reloading(self):
        """The actual fetch/htmx logic lives in the restoreToWanted() Alpine
        component function (mirroring profileEditor()), not inline on the
        button -- so scope to that function's own body, from its `function
        restoreToWanted()` definition up to the next top-level `function`
        definition (or end of script), the same isolation strategy the
        search-button test above uses for its onclick handler."""
        html = self._render_done()

        start = html.index('function restoreToWanted()')
        rest = html[start:]
        next_fn = rest.find('\nfunction ', 1)
        body = rest[:next_fn] if next_fn != -1 else rest

        assert 'location.reload()' not in body, (
            'AC6: the whole detail body must update in place, not via reload'
        )
        assert 'htmx.ajax' in body


class TestRestoreToWantedAlpineComponent:
    """The restoreToWanted() Alpine component script must exist exactly
    once per render (like profileEditor()/releaseDownloader()) and default
    its picker to the first (default) profile."""

    def test_the_component_function_is_defined(self):
        html = _render(_movie('done'))

        assert 'function restoreToWanted()' in html

    def test_the_component_preselects_a_default_profile(self):
        html = _render(_movie('done'))

        assert 'this.selectedProfile = this.profiles[0]' in html, (
            'AC6: the profile picker must default to the default profile'
        )
