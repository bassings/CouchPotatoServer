"""Render tests for FEAT-011's replacement modal, opened from the
"Replace with this file" trigger already pinned by
``test_operator_replace_trigger_ui_template.py`` (that file's own
gating/label/grammar tests are not repeated here).

Step one of TDD for the modal build only -- the picker's candidate list,
the confirm step's own submission, and the in-flight/outcome states are
each their own later step against these same three contracts. This file
renders the REAL ``partials/movie_detail.html`` Jinja partial (never a
copy) with a fixture that already makes the trigger render, and pins the
three things the task calls out as the ones most likely to ship wrong:

- The confirmation names the film AND states the CURRENT library copy
  will be permanently deleted and replaced -- not only what replaces it.
  (AC-DESIGN-7 / AC-QA-12 / AC-PROD-3.)
- The picker offers no way to type or submit a path: selection can only
  ever come from a server-produced list. (AC-SEC-1, and the task's own
  "WHAT TO BUILD" point 1.)
- The trigger is wired to actually open this modal, not a dead button,
  and what it opens is the design-system modal (``role="dialog"``,
  ``aria-modal="true"``) rather than a native ``confirm()`` -- the option
  ``lens-simplicity`` proposed at planning and was overridden on, per
  AC-DESIGN-6 and the "Vetoed at planning" table in
  ``specs/FEAT-011-replace-with-this-file.md``.

None of the decision layer (``decide_operator_replacement``), the
execution layer (``operatorReplaceView`` / ``_executeOperatorReplacement``)
or a candidate-listing route is touched or driven here -- this pins markup
only, and none of it exists in the template yet, so every test below is
expected to fail on the missing modal markup rather than on a fixture or
import problem.
"""

import re

from couchpotato.environment import Env
from couchpotato.ui import _jinja, _releases_ctx


MODAL_TESTID = 'operator-replace-modal'
TRIGGER_TESTID = 'operator-replace-trigger'

# Deliberately unusual so a pass could only mean the confirmation's text is
# genuinely driven by this fixture's title, never a coincidental match
# against other static copy already on the page (the page's own <h1> also
# renders the title, so a test that did not scope to the confirmation
# region could pass by reading that instead).
FIXTURE_TITLE = 'Zzyzx Road Chronicles'


def _render(movie):
    # _releases_ctx() reads Env.get('web_base') to build sort-link URLs; this
    # module renders the template directly rather than through create_app(),
    # so nothing else sets it up. Mirrors test_operator_replace_trigger_ui_template.py.
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


def _release(status, files=None, rid='rel-1'):
    return {
        '_id': rid,
        'status': status,
        'quality': '720p',
        'info': {'name': 'Fixture.Release.720p'},
        'identifier': 'tt1.unknown.720p',
        'files': files if files is not None else {},
    }


def _movie_with_trigger(title=FIXTURE_TITLE):
    """A movie with a completed release carrying a movie file: the exact
    fixture shape ``test_operator_replace_trigger_ui_template.py`` uses to
    make the trigger render, so the modal it opens has something to assert
    on."""
    return {
        '_id': 'movie-1',
        'status': 'done',
        'info': {'titles': [title], 'year': 2021},
        'profile': {'label': 'HD', 'qualities': []},
        'releases': [
            _release('done', files={
                'movie': ['/library/Fixture/' + title + '.mkv'],
            }),
        ],
    }


def _trigger_tag(html):
    """The trigger's own opening tag, or None. Copied from
    test_operator_replace_trigger_ui_template.py's helper of the same name
    so a whole-page substring check cannot pass on text that appears
    elsewhere on the page."""
    match = re.search(
        r'<button[^>]*data-testid="' + re.escape(TRIGGER_TESTID) + r'"[^>]*>',
        html,
    )
    return match.group(0) if match else None


def _element_region(html, needle):
    """The full markup of the nearest enclosing ``<div ...>`` whose opening
    tag contains ``needle``, matched by counting nested ``<div>``/``</div>``
    pairs out to that div's own close.

    Scoping assertions to this region (rather than "from the match to the
    end of the document") matters here specifically: this modal renders
    inline in the raw Jinja output ahead of ``partials/movie_releases.html``,
    which the SAME page already includes two ``<input type="hidden">``
    elements from (the sort/dir controls at ``movie_releases.html:74-75``).
    An unbounded "to end of document" scope would see those and fail the
    no-free-text-entry assertion for a reason that has nothing to do with
    this feature.
    """
    if needle not in html:
        return None
    idx = html.index(needle)
    tag_start = html.rfind('<div', 0, idx)
    if tag_start == -1:
        return None
    open_tag_end = html.index('>', tag_start) + 1
    depth = 1
    pos = open_tag_end
    div_open_re = re.compile(r'<div\b')
    div_close_re = re.compile(r'</div>')
    while depth > 0:
        next_open = div_open_re.search(html, pos)
        next_close = div_close_re.search(html, pos)
        if next_close is None:
            raise AssertionError(
                'unterminated <div> while scoping the region for %r' % needle
            )
        if next_open and next_open.start() < next_close.start():
            depth += 1
            pos = next_open.end()
        else:
            depth -= 1
            pos = next_close.end()
    return html[tag_start:pos]


def _modal_region(html):
    return _element_region(html, 'data-testid="%s"' % MODAL_TESTID)


class TestOperatorReplaceModalConfirmationNamesTheDestroyedFile:
    """AC-DESIGN-7 / AC-QA-12 / AC-PROD-3, and the task's own framing: "A
    confirmation that says only 'replace with X?' is not sufficient and is
    the single most likely way this ships wrong."
    """

    def test_confirmation_states_the_film_and_that_its_current_copy_is_deleted(self):
        html = _render(_movie_with_trigger())
        region = _modal_region(html)

        assert region is not None, (
            'expected a data-testid="%s" modal in the rendered page' % MODAL_TESTID
        )
        assert FIXTURE_TITLE in region, (
            'the confirmation must name the film -- fixture title %r was not '
            'found inside the modal markup' % FIXTURE_TITLE
        )
        assert 'current library copy' in region.lower(), (
            'the confirmation must say what is about to be destroyed, not '
            'only what replaces it -- no mention of the current library copy'
        )
        assert 'delete' in region.lower(), (
            'the confirmation must state the current copy will be deleted'
        )
        assert 'cannot be undone' in region.lower() or 'permanent' in region.lower(), (
            'the confirmation must state the deletion is irreversible'
        )


class TestOperatorReplaceModalOffersNoFreeTextPathEntry:
    """The operator picks a candidate the server produced; they never type
    or submit a path, and the modal must not offer any way to."""

    def test_modal_contains_no_input_element(self):
        html = _render(_movie_with_trigger())
        region = _modal_region(html)

        assert region is not None, (
            'expected a data-testid="%s" modal in the rendered page' % MODAL_TESTID
        )
        assert '<input' not in region, (
            'the modal must offer no free-text path entry -- found an <input> '
            'inside it: candidates must be chosen from a rendered list, never '
            'typed'
        )


class TestOperatorReplaceTriggerOpensTheDesignSystemModal:
    """The trigger must actually open this modal (not a dead button), and
    what it opens must be the design-system modal, not a stacked native
    confirm() -- AC-DESIGN-6, overridden over lens-simplicity's proposal at
    planning (see "Vetoed at planning" in
    specs/FEAT-011-replace-with-this-file.md).
    """

    def test_trigger_and_modal_share_one_alpine_component_and_open_wiring(self):
        html = _render(_movie_with_trigger())

        trigger_tag = _trigger_tag(html)
        assert trigger_tag is not None, 'the trigger must render for this fixture'
        assert '@click="open()"' in trigger_tag, (
            'the trigger must call an open() method on its Alpine component '
            'to reveal the modal, matching the isOpen/open()/close() '
            'convention already used by partials/movie_info_modal.html. '
            'Trigger tag was: ' + trigger_tag
        )

        component_region = _element_region(html, 'x-data="operatorReplaceModal(')
        assert component_region is not None, (
            'expected an x-data="operatorReplaceModal(...)" component '
            'wrapping the trigger and its modal'
        )
        assert 'data-testid="%s"' % TRIGGER_TESTID in component_region, (
            'the trigger must live inside the operatorReplaceModal component, '
            'not a sibling scope the open() call cannot reach'
        )
        assert 'data-testid="%s"' % MODAL_TESTID in component_region, (
            'the modal must live inside the SAME operatorReplaceModal '
            'component as the trigger that opens it'
        )

    def test_modal_is_the_design_system_dialog_not_a_native_confirm(self):
        html = _render(_movie_with_trigger())
        region = _modal_region(html)

        assert region is not None, (
            'expected a data-testid="%s" modal in the rendered page' % MODAL_TESTID
        )
        assert 'role="dialog"' in region, (
            'the modal must carry role="dialog", per '
            'docs/design-system/CONFORMANCE.md:38'
        )
        assert 'aria-modal="true"' in region, (
            'the modal must carry aria-modal="true", per '
            'docs/design-system/CONFORMANCE.md:38'
        )
        assert 'confirm(' not in region, (
            'no window.confirm() may be stacked over the open dialog -- '
            'lens-simplicity proposed exactly that at planning and it was '
            'overridden (AC-DESIGN-6), because a native confirm() cannot '
            'render a candidate list at all'
        )
