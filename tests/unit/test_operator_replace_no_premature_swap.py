"""M22 (branch review 2026-08-31): the operator-replace confirmation used to
swap the detail page's content immediately on `data.success`, but
`data.success` only means the server ACCEPTED the request and started a
background thread -- `operatorReplaceView` answers before a single byte has
moved. The operator was shown the OLD file's details on the one page whose
whole purpose is telling them what is about to be destroyed, right after
being told the replacement had started.

Static source check on the rendered partial rather than driving Alpine
through jsdom: `operatorReplaceModal()` is inline JS embedded in the Jinja
template, with no extracted pure-logic module (unlike
`couchpotato/static/scripts/ui/*.js`, which vitest exercises directly), so a
substring/structure check on the function's own text is the tightest pin
available without a disproportionate refactor for a two-line fix.
"""
import re
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parent.parent.parent
    / 'couchpotato' / 'ui' / 'templates' / 'partials' / 'movie_detail.html'
)


def _confirm_replace_success_branch():
    """The body of `confirmReplace()`'s `if (data.success) { ... }` branch,
    up to (not including) its matching `} else {`."""
    text = TEMPLATE.read_text(encoding='utf-8')
    match = re.search(
        r'async confirmReplace\(\).*?if \(data\.success\) \{(.*?)\} else \{',
        text, re.DOTALL,
    )
    assert match, (
        'could not find confirmReplace()\'s if (data.success) branch in '
        'movie_detail.html -- test setup is broken, not the finding under '
        'test'
    )
    return match.group(1)


class TestTheDetailPageDoesNotSwapOnAMerelyAcceptedReplacement:
    def test_a_successful_accept_does_not_swap_the_page_content(self):
        branch = _confirm_replace_success_branch()
        assert 'cpSwap(' not in branch, (
            'confirmReplace() still swaps #movie-detail-container as soon '
            'as the server ACCEPTS the request, before the background '
            'replacement has done any work -- the operator is shown the '
            'OLD file\'s details on the page whose purpose is to say what '
            'is about to be destroyed (M22, branch review 2026-08-31). '
            'Branch was: %r' % branch
        )

    def test_the_operator_is_told_the_work_is_still_running(self):
        branch = _confirm_replace_success_branch()
        assert re.search(r'background|still running|in progress', branch, re.IGNORECASE), (
            'the success branch does not say the replacement is still '
            'running in the background -- an operator reading "Replacement '
            'started" with no further qualification, on an unchanged page, '
            'has no way to tell a completed swap from one still in flight. '
            'Branch was: %r' % branch
        )
