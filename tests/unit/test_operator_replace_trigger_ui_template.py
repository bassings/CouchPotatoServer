"""Render tests for FEAT-011's "Replace with this file" trigger in
``couchpotato/ui/templates/partials/movie_detail.html``.

Step one of the UI layer only: this pins the entry point itself (AC-DESIGN-1,
AC-DESIGN-2), nothing about the picker, the confirmation or progress. The
decision layer (``decide_operator_replacement``) and the execution layer
(``operatorReplaceView`` / ``_executeOperatorReplacement``) already exist and
are mutation-proven; this file does not touch either.

Mirrors ``tests/unit/test_review_actions_ui_template.py`` and
``tests/unit/test_restore_to_wanted_ui_template.py``: renders the real Jinja
partial (not a copy) with fabricated ``movie`` dicts so the gating is pinned
against the actual template rather than a description of it.

AC-DESIGN-1 requires the trigger to render only when the movie has a
completed release (status in done/seeding/downloaded) carrying at least one
movie file, and to reuse the existing danger button grammar verbatim
(``bg-cp-danger/10 text-cp-danger hover:bg-cp-danger/15 rounded-md text-xs``,
as at the existing Delete and Mark Failed &amp; Re-search buttons) rather than
introducing a new colour token.
"""

import re

from couchpotato.environment import Env
from couchpotato.ui import _jinja, _releases_ctx


TRIGGER_TESTID = 'operator-replace-trigger'
TRIGGER_LABEL = 'Replace with this file'

# The exact class string the existing danger buttons already carry (Delete
# at movie_detail.html:346-347, Mark Failed & Re-search at :283-284). AC-DESIGN-1
# requires the new trigger to reuse this verbatim rather than mint a new one.
EXISTING_DANGER_BUTTON_GRAMMAR = 'bg-cp-danger/10 text-cp-danger hover:bg-cp-danger/15'


def _render(movie):
    # _releases_ctx() reads Env.get('web_base') to build sort-link URLs; this
    # module renders the template directly rather than through create_app(),
    # so nothing else sets it up.
    Env.set('web_base', '/')
    ctx = {
        'api_key': 'test-key',
        'api_base': '/api/test-key',
        'web_base': '/',
        'new_base': '/',
        'movie': movie,
        # T8a: the trigger only renders when this mirrors production's
        # `Renamer.conf('operator_replace_enabled', default=False)` --
        # this module renders the template directly rather than through
        # `_ctx()`, so the fixture sets it explicitly. The feature's own
        # OFF-by-default gating is pinned separately by
        # test_operator_replace_feature_flag.py and
        # test_fastapi_web.py; this file's contract is what renders once
        # the feature is on.
        'operator_replace_enabled': True,
    }
    ctx.update(_releases_ctx(movie, movie.get('_id', ''), {}))
    return _jinja.get_template('partials/movie_detail.html').render(**ctx)


def _movie(status, releases=None):
    return {
        '_id': 'movie-1',
        'status': status,
        'info': {'titles': ['Fixture Movie'], 'year': 2021},
        'profile': {'label': 'HD', 'qualities': []},
        'releases': releases or [],
    }


def _trigger_tag(html):
    """The trigger's own opening tag, or None if it is not present.

    Ties an assertion about the trigger's classes to the trigger ELEMENT
    itself rather than to the page as a whole -- the danger button grammar
    string is already present on the pre-existing Delete and Mark Failed &
    Re-search buttons regardless of whether the new trigger exists, so a
    plain `EXISTING_DANGER_BUTTON_GRAMMAR in html` substring check would
    pass even with no trigger at all. Non-greedy up to the first `>` is
    safe here because none of this template's button attributes contain a
    literal `>` character.
    """
    match = re.search(
        r'<button[^>]*data-testid="' + re.escape(TRIGGER_TESTID) + r'"[^>]*>',
        html,
    )
    return match.group(0) if match else None


def _release(status, files=None, rid='rel-1'):
    return {
        '_id': rid,
        'status': status,
        'quality': '720p',
        'info': {'name': 'Fixture.Release.720p'},
        'identifier': 'tt1.unknown.720p',
        'files': files if files is not None else {},
    }


class TestOperatorReplaceTriggerGating:

    def test_shown_for_a_done_movie_with_a_completed_release_carrying_a_movie_file(self):
        """AC-DESIGN-1: the whole point of the release -- a completed release
        that actually names a library file is exactly the case FEAT-011
        exists to reach."""
        movie = _movie('done', releases=[
            _release('done', files={'movie': ['/library/Fixture Movie (2021)/Fixture Movie.mkv']}),
        ])
        html = _render(movie)

        assert f'data-testid="{TRIGGER_TESTID}"' in html
        assert TRIGGER_LABEL in html

    def test_hidden_for_an_active_movie_with_no_releases(self):
        """No completed release at all -- there is nothing yet to replace."""
        html = _render(_movie('active', releases=[]))

        assert f'data-testid="{TRIGGER_TESTID}"' not in html

    def test_hidden_when_the_completed_release_carries_no_movie_file(self):
        """AC-DESIGN-1 requires 'carrying at least one movie file', not just
        a qualifying status. A release document written before a file ever
        landed (files={}) is the ordinary shape for a movie that is
        completed on paper but has nothing on disk yet -- an implementation
        that gates on status alone would show the trigger here and let the
        operator open a picker with nothing to replace behind it.
        """
        movie = _movie('done', releases=[_release('done', files={})])
        html = _render(movie)

        assert f'data-testid="{TRIGGER_TESTID}"' not in html

    def test_shown_for_a_seeding_movie_with_a_completed_release_carrying_a_movie_file(self):
        """'seeding' is one of the three completed statuses the trigger's
        gating condition names (done/seeding/downloaded)."""
        movie = _movie('active', releases=[
            _release('seeding', files={'movie': ['/library/Fixture Movie (2021)/Fixture Movie.mkv']}),
        ])
        html = _render(movie)

        assert f'data-testid="{TRIGGER_TESTID}"' in html

    def test_trigger_reuses_the_existing_danger_button_grammar_verbatim(self):
        """AC-DESIGN-1: no new colour token, no new class pattern -- the
        trigger ELEMENT itself must carry the exact class string the Delete
        and Mark Failed & Re-search buttons already use.

        Checked against the trigger's own tag, not the page as a whole: the
        grammar string is already present on those pre-existing buttons
        regardless of this feature, so a whole-page substring check would
        pass even if the trigger were missing or used a different class
        string entirely.
        """
        movie = _movie('done', releases=[
            _release('done', files={'movie': ['/library/Fixture Movie (2021)/Fixture Movie.mkv']}),
        ])
        html = _render(movie)
        tag = _trigger_tag(html)

        assert tag is not None, 'the trigger button must render for this fixture'
        assert EXISTING_DANGER_BUTTON_GRAMMAR in tag, (
            'the trigger must reuse the danger button grammar verbatim '
            '(bg-cp-danger/10 text-cp-danger hover:bg-cp-danger/15), matching '
            'the existing Delete and Mark Failed & Re-search buttons, rather '
            'than introducing a new colour token. Trigger tag was: ' + tag
        )

    def test_trigger_label_is_distinguishable_from_delete_and_mark_failed(self):
        """AC-DESIGN-2: the trigger's label must not read as a synonym of
        the neighbouring Delete or Mark Failed controls, so the three
        destructive-looking controls in one row stay distinguishable by
        label alone."""
        movie = _movie('done', releases=[
            _release('done', files={'movie': ['/library/Fixture Movie (2021)/Fixture Movie.mkv']}),
        ])
        html = _render(movie)

        assert TRIGGER_LABEL in html
        assert TRIGGER_LABEL.lower() not in ('delete', 'mark failed & re-search')


# M24 (branch review 2026-08-31). The Heroicon `arrow-path` glyph -- this
# exact SVG path data -- is what `docs/design-system/README.md`'s legacy
# glyph table maps to `icon-refresh`, and it is what the Wanted page's own
# "Refresh Library" button (`wanted.html`) and the per-card refresh button
# (`movie_cards.html`) both render. The trigger under test is the one
# control in the action row that PERMANENTLY DELETES the film's current
# library file; wearing the same glyph as two genuinely non-destructive
# refresh actions elsewhere in this same UI tells a distracted operator the
# opposite of what the button does.
REFRESH_ICON_PATH_D = (
    'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 '
    '3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 '
    '13.803-3.7l3.181 3.182m0-4.991v4.99'
)


def _trigger_html(html):
    """The trigger's full rendered markup, opening tag through `</button>`,
    so the assertion below can inspect the icon actually nested inside it
    rather than the page as a whole -- the refresh glyph is legitimately
    present elsewhere on this same page (the per-card refresh button)."""
    match = re.search(
        r'<button[^>]*data-testid="' + re.escape(TRIGGER_TESTID)
        + r'"[^>]*>.*?</button>',
        html, re.DOTALL,
    )
    return match.group(0) if match else None


class TestOperatorReplaceTriggerIconIsNotTheRefreshGlyph:
    def test_the_refresh_glyph_really_is_used_elsewhere_in_this_ui(self):
        """Sanity check on the constant itself, independent of the trigger:
        if this ever stopped matching a real refresh control the assertion
        below would be meaningless -- comparing against a string nothing
        else uses either."""
        from pathlib import Path

        templates_root = Path(__file__).resolve().parent.parent.parent / (
            'couchpotato/ui/templates'
        )
        wanted_html = (templates_root / 'wanted.html').read_text(encoding='utf-8')
        cards_html = (templates_root / 'partials/movie_cards.html').read_text(
            encoding='utf-8',
        )
        assert REFRESH_ICON_PATH_D in wanted_html, (
            "the Wanted page's Refresh Library button no longer uses this "
            'path -- update the constant, this is not the finding under test'
        )
        assert REFRESH_ICON_PATH_D in cards_html, (
            "the per-card refresh button no longer uses this path -- update "
            'the constant, this is not the finding under test'
        )

    def test_the_delete_triggers_icon_is_not_the_refresh_glyph(self):
        movie = _movie('done', releases=[
            _release('done', files={'movie': ['/library/Fixture Movie (2021)/Fixture Movie.mkv']}),
        ])
        html = _render(movie)
        trigger_html = _trigger_html(html)

        assert trigger_html is not None, 'the trigger button must render for this fixture'
        assert REFRESH_ICON_PATH_D not in trigger_html, (
            'the control that PERMANENTLY DELETES the current library file '
            'wears the same glyph as the Refresh Library and per-card '
            'refresh buttons elsewhere in this UI (M24, branch review '
            '2026-08-31). Rendered trigger markup was: ' + trigger_html
        )
