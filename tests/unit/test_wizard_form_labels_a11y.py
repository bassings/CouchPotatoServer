"""A11Y-001: every interactive field in the templates listed in Scope must
have an accessible name. AC-A11Y-1/AC-A11Y-2/AC-QA-4.

`specs/A11Y-001-form-labels-not-associated.md` measured wizard.html at 61
`<label>`s, 63 inputs, 0 `for=`, 0 `aria-label`. axe-core never sees most of
it: the wizard is a multi-step form, later steps are `x-show`-gated so axe
correctly skips them as hidden, and
`tests/e2e/accessibility.a11y.spec.ts:247` only scans the first step. SonarQube
reads the template source instead and reports 118 findings.

This guard reads the template source too, the same way SonarQube does, so it
does not depend on which step happens to be visible when it runs.

Three routes give a field an accessible name and all three are accepted, on
purpose (AC-A11Y-1): an explicit `for`/`id` pair (static OR Alpine-bound,
`:for`/`:id`, matched by comparing the two expression strings), the field
wrapped by its `<label>`, or a non-empty `aria-label`/`aria-labelledby`
(static or `:aria-label`/`:aria-labelledby`). A guard that only accepted the
first would be wrong and would force bad markup onto the three fields that
live inside `x-for` loops, where a static id would create duplicate ids
instead (AC-A11Y-2) -- `partials/settings/profiles.html` already does this
correctly (`:for="'profile-name-' + _uid"` paired with
`:id="'profile-name-' + _uid"`) and is the exemplar the wizard fix should
copy.

A field discovered while writing this guard and NOT mentioned by name in the
spec: `wizard.html`'s `getDownloaderFields()` builds each download client's
host/username/password/API-key fields as HTML inside a JS template-literal
string and injects it with `x-html`. That markup is real and reachable (it is
what a user actually sees once they pick a download client), but it is
invisible to a plain BeautifulSoup parse of the file, because the parser
correctly treats `<script>` content as text, not tags -- the same blind spot
that hides it from axe, for a different reason. `_script_fragment_violations`
below pulls those strings out and checks them the same way, or the exact
fields the spec calls out by name ("every download client's API key and
token field") stay unchecked by this guard too.
"""
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / 'couchpotato' / 'ui' / 'templates'

#: specs/A11Y-001-form-labels-not-associated.md, Scope section.
SCOPE_FILES = [
    TEMPLATES_DIR / 'wizard.html',
    TEMPLATES_DIR / 'partials' / 'movie_cards.html',
    TEMPLATES_DIR / 'partials' / 'settings' / 'field_types.html',
    TEMPLATES_DIR / 'partials' / 'settings' / 'combined_basics_card.html',
    TEMPLATES_DIR / 'partials' / 'settings' / 'header.html',
    TEMPLATES_DIR / 'partials' / 'settings' / 'provider_card.html',
    TEMPLATES_DIR / 'partials' / 'settings' / 'profiles.html',
    TEMPLATES_DIR / 'partials' / 'settings' / 'logs_tab.html',
    TEMPLATES_DIR / 'logs.html',
]

FIELD_TAGS = ('input', 'select', 'textarea')

#: Jinja comments (`{# ... #}`) are not HTML comments, so an HTML parser does
#: not know to skip them. One exists in movie_cards.html whose prose mentions
#: "<label>" in plain English -- left in, that reads as a real, empty <label>
#: tag opening in the middle of a sentence and can distort the tree around
#: it. Strip Jinja comments before parsing, the same way a real browser would
#: never see them (Jinja removes them before the response is ever sent).
_JINJA_COMMENT = re.compile(r'{#.*?#}', re.S)

#: A JS template-literal string, inside a <script> block, that contains form
#: markup -- see the getDownloaderFields() note above.
_JS_HTML_STRING = re.compile(r'`([^`]*<(?:input|label|select|textarea)[^`]*)`', re.S)
_SCRIPT_BLOCK = re.compile(r'<script\b[^>]*>(.*?)</script>', re.S)


def _strip_jinja_comments(text):
    return _JINJA_COMMENT.sub('', text)


def _non_empty_attr(tag, *names):
    """True if any of `names`, static or Alpine-bound (`:name`), is present
    with a non-blank value. A quoted empty-string expression (`''`, `""`) is
    treated as blank, the same as a bare `aria-label=""`."""
    for name in names:
        for attr in (name, ':' + name):
            value = tag.get(attr)
            if value is None:
                continue
            if value.strip().strip("'\"").strip():
                return True
    return False


def _wrapped_by_label(tag):
    for parent in tag.parents:
        if isinstance(parent, Tag) and parent.name == 'label':
            return True
    return False


def _describe(tag):
    bits = [tag.name]
    for attr in ('type', ':type', 'id', ':id', 'name', 'x-model', 'placeholder'):
        value = tag.get(attr)
        if value:
            bits.append('%s=%r' % (attr, value))
    return '<%s>' % ' '.join(bits)


def _fragment_violations(fragment_html, source):
    """Accessible-name violations in one parsed HTML fragment.

    A fragment is either a whole template file, or one JS template-literal
    string pulled out of a <script> block -- each is checked as its own
    little document, which is correct here: every id/for pair this codebase
    uses is scoped to a single fragment (one tracker's fields, one downloader
    client's fields), never referencing across the boundary.
    """
    soup = BeautifulSoup(fragment_html, 'html.parser')

    for_targets = set()
    for label in soup.find_all('label'):
        for attr in ('for', ':for'):
            value = label.get(attr)
            if value:
                for_targets.add(value.strip())

    violations = []
    for field in soup.find_all(FIELD_TAGS):
        field_type = (field.get('type') or '').strip().lower()
        if field_type == 'hidden':
            continue

        field_id = (field.get('id') or '').strip()
        bound_id = (field.get(':id') or '').strip()

        has_for_id = bool(field_id and field_id in for_targets)
        has_bound_for = bool(bound_id and bound_id in for_targets)
        has_wrap = _wrapped_by_label(field)
        has_aria = _non_empty_attr(field, 'aria-label', 'aria-labelledby')

        if not (has_for_id or has_bound_for or has_wrap or has_aria):
            violations.append('%s: %s has no accessible name' % (source, _describe(field)))
    return violations


def _script_fragment_violations(html_text, filename):
    violations = []
    for script_idx, script in enumerate(_SCRIPT_BLOCK.findall(html_text)):
        for string_idx, match in enumerate(_JS_HTML_STRING.finditer(script)):
            source = '%s (script %d, template string %d)' % (filename, script_idx, string_idx)
            violations.extend(_fragment_violations(match.group(1), source))
    return violations


def find_accessible_name_violations(path):
    """Every accessible-name violation in `path`, across both its own markup
    and any JS-template-literal HTML it injects via x-html."""
    text = _strip_jinja_comments(path.read_text())
    violations = _fragment_violations(text, path.name)
    violations.extend(_script_fragment_violations(text, path.name))
    return violations


def find_static_id_in_loop_violations(path):
    """AC-A11Y-2: a static `id`/`for` inside an Alpine `x-for` loop is a worse
    defect than the missing label it would "fix" -- every iteration renders
    the same id, so the DOM ends up with duplicates. Fields in a loop must use
    a bound `:id` (unique per iteration, e.g. from the loop item), not a
    static one."""
    text = _strip_jinja_comments(path.read_text())
    soup = BeautifulSoup(text, 'html.parser')

    violations = []
    for loop in soup.find_all('template', attrs={'x-for': True}):
        for el in loop.find_all(list(FIELD_TAGS) + ['label']):
            if el.get('id'):
                violations.append(
                    '%s: %s inside an x-for loop has a static id -- this '
                    'produces duplicate ids at runtime, one per iteration'
                    % (path.name, _describe(el)))
            if el.name == 'label' and el.get('for'):
                violations.append(
                    '%s: <label for=%r> inside an x-for loop has a static '
                    'for -- every iteration points at the same id'
                    % (path.name, el.get('for')))
    return violations


# --- guard the guard ---------------------------------------------------------
# Pure logic, checked against synthetic fixtures rather than the real
# templates, the same role test_login_page_a11y.py's
# test_the_arithmetic_is_right() plays for contrast_ratio(): if this fails,
# nothing below can be trusted, whichever way it fails.

def test_the_checker_accepts_all_three_accessible_name_routes():
    for_id_pair = '<div><label for="x">Name</label><input id="x"></div>'
    bound_for_id_pair = '<div><label :for="\'f-\' + i">Name</label><input :id="\'f-\' + i"></div>'
    wrapped = '<label>Name<input></label>'
    static_aria_label = '<input aria-label="Name">'
    bound_aria_label = '<input :aria-label="opt.label || opt.name">'
    aria_labelledby = '<div id="hint">Name</div><input aria-labelledby="hint">'

    for good in (for_id_pair, bound_for_id_pair, wrapped, static_aria_label,
                 bound_aria_label, aria_labelledby):
        assert _fragment_violations(good, 'fixture') == [], (
            'a compliant fixture was rejected: %r' % good)


def test_the_checker_rejects_a_field_with_no_accessible_name():
    naked = '<div><label>Username</label><input x-model="formData.username"></div>'

    violations = _fragment_violations(naked, 'fixture')

    assert len(violations) == 1, (
        'an unassociated visible label + input must be flagged exactly once, got %r'
        % violations)
    assert 'no accessible name' in violations[0]


def test_the_checker_treats_an_empty_aria_label_as_no_name():
    """An empty aria-label is worse than none: it suppresses the fallback
    name-from-content a reader would otherwise get, and announces nothing."""
    empty_static = '<input aria-label="">'
    empty_bound = "<input :aria-label=\"''\">"

    for bad in (empty_static, empty_bound):
        violations = _fragment_violations(bad, 'fixture')
        assert violations, 'an empty aria-label must not count as a name: %r' % bad


def test_the_checker_ignores_jinja_comment_text_that_looks_like_a_tag():
    """movie_cards.html's own comment prose ('the wrapping <label> holds
    only...') must not be parsed as a real element, or it can pull a real
    input inside it and hide a genuine violation."""
    html = (
        '{# The wrapping <label> holds only an icon. #}\n'
        '<input x-model="formData.selected">'
    )
    violations = _fragment_violations(_strip_jinja_comments(html), 'fixture')
    assert len(violations) == 1, (
        'stripping the Jinja comment should leave exactly one real, '
        'unassociated input -- got %r' % violations)


def test_the_loop_checker_flags_a_static_id_inside_x_for():
    bad = (
        '<template x-for="field in tracker.fields" :key="field.name">'
        '<div><label for="field-id">X</label><input id="field-id"></div>'
        '</template>'
    )
    good = (
        '<template x-for="field in tracker.fields" :key="field.name">'
        '<div><label :for="\'field-\' + field.name">X</label>'
        '<input :id="\'field-\' + field.name"></div>'
        '</template>'
    )

    soup_helper_violations = find_static_id_in_loop_violations
    # Exercise the real function against an in-memory file-like path is
    # unnecessary plumbing here; call the parsing it wraps directly via a
    # throwaway file so the test still drives the real function, not a copy
    # of its logic.
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False) as f:
        f.write(bad)
        bad_path = Path(f.name)
    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False) as f:
        f.write(good)
        good_path = Path(f.name)

    try:
        assert soup_helper_violations(bad_path), 'a static id inside x-for must be flagged'
        assert soup_helper_violations(good_path) == [], (
            'a bound :id/:for pair inside x-for must NOT be flagged: %r'
            % soup_helper_violations(good_path))
    finally:
        bad_path.unlink()
        good_path.unlink()


# --- the guard, run against the real templates -------------------------------

@pytest.mark.parametrize('path', SCOPE_FILES, ids=lambda p: p.name)
def test_every_interactive_field_has_an_accessible_name(path):
    """AC-A11Y-1 / AC-QA-4. Currently RED for wizard.html: 61 labels, 63
    inputs, none associated by any of the three valid routes."""
    violations = find_accessible_name_violations(path)

    assert violations == [], (
        'found %d field(s) in %s with no accessible name (need one of: an '
        'explicit for/id pair -- static or Alpine-bound, wrapping by a '
        '<label>, or a non-empty aria-label/aria-labelledby):\n%s'
        % (len(violations), path.name, '\n'.join(violations))
    )


@pytest.mark.parametrize('path', SCOPE_FILES, ids=lambda p: p.name)
def test_no_static_id_inside_an_alpine_loop(path):
    """AC-A11Y-2, forward guard. Passes trivially today (wizard.html has zero
    ids of any kind yet, static or bound) -- it exists so the fix that adds
    ids cannot reintroduce a static one inside the three fields the spec
    identifies as living in x-for loops. See
    test_the_loop_checker_flags_a_static_id_inside_x_for for proof this logic
    itself can fail."""
    violations = find_static_id_in_loop_violations(path)

    assert violations == [], (
        'static id/for inside an x-for loop in %s (must be a bound :id/:for '
        'instead, or every iteration renders the same id):\n%s'
        % (path.name, '\n'.join(violations))
    )
