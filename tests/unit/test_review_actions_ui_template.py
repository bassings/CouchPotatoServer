"""Render tests for the Downloaded/review-workflow action buttons (Phase 3c).

These lock the *gating* of the review-action UI in
``couchpotato/ui/templates/partials/movie_detail.html`` — which buttons appear
for which movie/release status — that the E2E suite cannot exercise. The E2E
tests (``tests/e2e/movie-detail.spec.ts``) can only reach ``active`` movies
because CI/local runs start from a fresh, empty ``.e2e-data`` with no way to
seed a ``downloaded``-status movie (see the coverage-gap note there and in
``specs/DOWNLOADED-REVIEW-WORKFLOW.md``). So instead we render the *actual*
Jinja partial (not a copy) with fabricated ``movie`` dicts and assert the
gating directly.

Buttons under test (per spec Phase 3c):
- Movie-level **Mark Done** and **Mark Failed & Re-search** — shown only when
  the movie ``status == 'downloaded'``.
- Per-release **Mark failed** — shown only for a release row whose
  ``status == 'downloaded'``.
- The pre-existing generic **Mark as Done** — shown for any movie that is not
  ``done`` and not ``downloaded`` (i.e. it must NOT double up with the
  review-gate Mark Done, and must NOT regress for ``active`` movies).
"""

from couchpotato.ui import _jinja


# Distinctive rendered substrings. Each is the visible ``<span>`` label so it
# can't collide with an attribute value or another button's text. Note the
# review "Mark Done" (capital D, no "as") is deliberately distinct from the
# generic "Mark as Done", and the movie-level "Mark Failed" (capital F) is
# distinct from the per-release "Mark failed" (lowercase f).
REVIEW_MARK_DONE = '>Mark Done<'
REVIEW_MARK_FAILED = 'Mark Failed &amp; Re-search'
RELEASE_MARK_FAILED = '>Mark failed<'
GENERIC_MARK_AS_DONE = '>Mark as Done<'


def _render(movie):
    ctx = {
        'api_key': 'test-key',
        'api_base': '/api/test-key',
        'web_base': '/',
        'new_base': '/',
        'movie': movie,
    }
    return _jinja.get_template('partials/movie_detail.html').render(**ctx)


def _movie(status, releases=None):
    return {
        '_id': 'movie-1',
        'status': status,
        'info': {'titles': ['Fixture Movie'], 'year': 2021},
        # A profile with no qualities means matching_releases == releases, so
        # every fabricated release row is rendered.
        'profile': {'label': 'HD', 'qualities': []},
        'releases': releases or [],
    }


def _release(status, rid='rel-1'):
    return {
        '_id': rid,
        'status': status,
        'quality': '720p',
        'info': {'name': 'Fixture.Release.720p'},
        'identifier': 'tt1.unknown.720p',
        'files': {},
    }


def test_downloaded_movie_shows_all_three_review_buttons():
    """status='downloaded' + a 'downloaded' release row -> all review actions,
    and NOT the generic 'Mark as Done'."""
    html = _render(_movie('downloaded', releases=[_release('downloaded')]))

    assert REVIEW_MARK_DONE in html, 'Mark Done (review) must render for a downloaded movie'
    assert REVIEW_MARK_FAILED in html, 'Mark Failed & Re-search must render for a downloaded movie'
    assert RELEASE_MARK_FAILED in html, 'per-release Mark failed must render for a downloaded release'
    assert GENERIC_MARK_AS_DONE not in html, (
        'the generic "Mark as Done" must be suppressed for a downloaded movie '
        '(the review-gate Mark Done replaces it) to avoid a duplicate button'
    )


def test_done_movie_hides_all_review_buttons():
    """status='done' -> none of the three review buttons, and no generic
    'Mark as Done' (a done movie is terminal)."""
    html = _render(_movie('done', releases=[_release('done')]))

    assert REVIEW_MARK_DONE not in html
    assert REVIEW_MARK_FAILED not in html
    assert RELEASE_MARK_FAILED not in html
    assert GENERIC_MARK_AS_DONE not in html


def test_active_movie_hides_review_buttons_but_keeps_generic_mark_as_done():
    """status='active' -> no review buttons; the pre-existing generic
    'Mark as Done' must still render (no regression). An 'available' release
    row must not surface the per-release Mark failed action."""
    html = _render(_movie('active', releases=[_release('available')]))

    assert REVIEW_MARK_DONE not in html
    assert REVIEW_MARK_FAILED not in html
    assert RELEASE_MARK_FAILED not in html
    assert GENERIC_MARK_AS_DONE in html, (
        'the generic "Mark as Done" button must remain for an active movie'
    )


def test_per_release_mark_failed_is_gated_on_release_status_not_movie_status():
    """The per-release Mark failed button keys off the *release* status: a
    non-'downloaded' release under a downloaded movie must not show it, and a
    'downloaded' release only surfaces it for that specific row."""
    # Downloaded movie, but its (only) release is 'done' -> no per-release
    # Mark failed button, though the movie-level buttons still show.
    html = _render(_movie('downloaded', releases=[_release('done')]))
    assert RELEASE_MARK_FAILED not in html
    assert REVIEW_MARK_DONE in html

    # Two releases, only one 'downloaded' -> exactly one per-release button.
    html = _render(_movie('downloaded', releases=[
        _release('available', rid='rel-a'),
        _release('downloaded', rid='rel-b'),
    ]))
    assert html.count(RELEASE_MARK_FAILED) == 1
