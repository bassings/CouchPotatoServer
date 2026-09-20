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
from bs4 import BeautifulSoup, NavigableString, Tag

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
LABEL_TEMPLATE_FILES = sorted(
    path for path in TEMPLATES_DIR.rglob('*.html')
    if '<label' in path.read_text()
)

FIELD_TAGS = ('input', 'select', 'textarea')
LABELABLE_TAGS = ('button', 'input', 'meter', 'output', 'progress', 'select', 'textarea')

#: Jinja comments (`{# ... #}`) are not HTML comments, so an HTML parser does
#: not know to skip them. One exists in movie_cards.html whose prose mentions
#: "<label>" in plain English -- left in, that reads as a real, empty <label>
#: tag opening in the middle of a sentence and can distort the tree around
#: it. Strip Jinja comments before parsing, the same way a real browser would
#: never see them (Jinja removes them before the response is ever sent).
_JINJA_COMMENT = re.compile(r'{#.*?#}', re.S)

#: A JS template-literal string, inside a <script> block, that contains form
#: markup -- see the getDownloaderFields() note above.
_JS_HTML_MARKUP = re.compile(r'<(?:input|label|select|textarea)\b')
_JS_TEMPLATE_LITERAL = re.compile(r'`((?:\\.|[^`])*)`', re.S)
#: Script bodies are extracted with the HTML parser, NOT a regex. CodeQL's
#: py/bad-tag-filter flagged the regex form on PR 301 and was right about the
#: code even though the severity does not apply here (this parses the
#: project's own templates, there is no untrusted input). A regex
#: `</script>` matcher misses `</script >` and `</SCRIPT>`, and a missed
#: closing tag means the fields inside that block are never checked, which is
#: a blind spot in the one guard whose whole job is not to have any.
def _script_bodies(html_text):
    """Every <script> element's text, via the parser rather than a pattern."""
    soup = BeautifulSoup(html_text, 'html.parser')
    return [script.string or script.get_text() or '' for script in soup.find_all('script')]


def _js_html_strings(script):
    """Yield every markup-bearing backtick span, including comment prose.

    This deliberately fails closed instead of partially lexing JavaScript.
    URLs and regular-expression literals can contain comment-like tokens, so
    trying to skip comments without a real parser risks silently missing the
    later generated markup that this guard exists to inspect.
    """
    template_spans = list(_JS_TEMPLATE_LITERAL.finditer(script))
    uncovered_markup = [
        match.start()
        for match in _JS_HTML_MARKUP.finditer(script)
        if not any(
            template.start(1) <= match.start() < template.end(1)
            for template in template_spans
        )
    ]
    assert not uncovered_markup, (
        'form markup appears outside a paired backtick span at offsets %r; '
        'refusing to let malformed or mispaired script source bypass the '
        'label audit' % uncovered_markup
    )

    for match in template_spans:
        content = match.group(1)
        if _JS_HTML_MARKUP.search(content):
            yield content


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


def _association_value(tag, name):
    """Normalize one static or Alpine-bound label association value.

    Alpine expressions containing only a quoted blank render no usable ID,
    even though their source text is non-empty.
    """
    value = tag.get(name)
    if value is None:
        return ''
    value = value.strip()
    if (len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]
            and not value[1:-1].strip()):
        return ''
    return value


def _wrapped_by_label(tag):
    for parent in tag.parents:
        if isinstance(parent, Tag) and parent.name == 'label':
            if not parent.has_attr('for') and not parent.has_attr(':for'):
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

    for_targets = {'id': set(), ':id': set()}
    for label in soup.find_all('label'):
        has_static_for = label.has_attr('for')
        has_bound_for = label.has_attr(':for')
        if has_static_for == has_bound_for:
            continue
        for_attr = 'for' if has_static_for else ':for'
        id_attr = 'id' if has_static_for else ':id'
        value = _association_value(label, for_attr)
        if value:
            for_targets[id_attr].add(value)

    violations = []
    for field in soup.find_all(FIELD_TAGS):
        field_type = (field.get('type') or '').strip().lower()
        if field_type == 'hidden':
            continue

        field_id = _association_value(field, 'id')
        bound_id = _association_value(field, ':id')

        has_for_id = bool(field_id and field_id in for_targets['id'])
        has_bound_for = bool(bound_id and bound_id in for_targets[':id'])
        has_wrap = _wrapped_by_label(field)
        has_aria = _non_empty_attr(field, 'aria-label', 'aria-labelledby')

        if not (has_for_id or has_bound_for or has_wrap or has_aria):
            violations.append('%s: %s has no accessible name' % (source, _describe(field)))
    return violations


def _script_fragment_violations(html_text, filename):
    violations = []
    for script_idx, script in enumerate(_script_bodies(html_text)):
        for string_idx, fragment in enumerate(_js_html_strings(script)):
            source = '%s (script %d, template string %d)' % (filename, script_idx, string_idx)
            violations.extend(_fragment_violations(fragment, source))
    return violations


def _label_semantics_violations(fragment_html, source):
    """Return labels without exactly one named, associated control.

    An icon-only wrapper may take its text alternative from the sole control's
    explicit ARIA name. This is the existing movie-card/boolean-toggle pattern,
    and is distinct from an empty label around an unnamed control.
    """
    soup = BeautifulSoup(fragment_html, 'html.parser')
    violations = []

    for label in soup.find_all('label'):
        has_text = any(
            isinstance(child, NavigableString) and str(child).strip()
            for child in label.descendants
        ) or any(
            child.get('x-text') or child.get('x-html')
            for child in [label, *label.find_all(True)]
        )

        static_for = _association_value(label, 'for')
        bound_for = _association_value(label, ':for')
        has_static_for = label.has_attr('for')
        has_bound_for = label.has_attr(':for')
        has_explicit_for = has_static_for or has_bound_for
        nested_controls = [
            control for control in label.find_all(LABELABLE_TAGS)
            if not (control.name == 'input' and
                    (control.get('type') or '').strip().lower() == 'hidden')
        ]
        if has_explicit_for:
            id_attr = 'id' if has_static_for else ':id'
            target = static_for or bound_for
            target_controls = [
                control for control in soup.find_all(LABELABLE_TAGS)
                if target and _association_value(control, id_attr) == target
                and not (control.name == 'input' and
                         (control.get('type') or '').strip().lower() == 'hidden')
            ]
            controls = target_controls + [
                control for control in nested_controls
                if not any(control is target_control for target_control in target_controls)
            ]
            has_one_associated_control = (
                has_static_for != has_bound_for
                and len(target_controls) == 1 and len(controls) == 1
            )
        else:
            controls = nested_controls
            has_one_associated_control = len(controls) == 1

        if not has_text and len(controls) == 1:
            has_text = _non_empty_attr(controls[0], 'aria-label', 'aria-labelledby')

        if not has_text or not has_one_associated_control:
            violations.append(
                '%s: label text=%r target=%r resolves to %d labelable controls'
                % (source, label.get_text(' ', strip=True) or label.get('x-text'),
                   static_for or bound_for, len(controls))
            )

    return violations


def find_label_semantics_violations(path):
    """Find invalid label elements in template and script-generated markup."""
    text = _strip_jinja_comments(path.read_text())
    violations = _label_semantics_violations(text, path.name)
    for script_idx, script in enumerate(_script_bodies(text)):
        for string_idx, fragment in enumerate(_js_html_strings(script)):
            source = '%s (script %d, template string %d)' % (
                path.name, script_idx, string_idx)
            violations.extend(_label_semantics_violations(fragment, source))
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
    static one.

    Deduped by element identity (round 2 review, C4): `soup.find_all` on an
    OUTER `<template x-for>` also walks any INNER one nested inside it (the
    real shape at wizard.html:297/:311, a tracker loop containing a
    per-tracker field loop), and the outer `for loop in ...` here visits the
    inner loop a second time as its own top-level match -- so one real
    static-id defect was reported twice, not once. `seen` tracks which
    elements have already been checked, by object identity, across every
    loop level."""
    text = _strip_jinja_comments(path.read_text())
    soup = BeautifulSoup(text, 'html.parser')

    violations = []
    seen = set()
    for loop in soup.find_all('template', attrs={'x-for': True}):
        for el in loop.find_all(list(FIELD_TAGS) + ['label']):
            if id(el) in seen:
                continue
            seen.add(id(el))
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


def test_the_label_checker_accepts_explicit_and_implicit_associations():
    fixtures = (
        '<label for="name">Name</label><input id="name">',
        '<label :for="\'field-\' + item.id" x-text="item.label"></label>'
        '<input :id="\'field-\' + item.id">',
        '<label><button role="switch">Advanced</button></label>',
        '<label><input aria-label="Select movie"></label>',
    )

    for good in fixtures:
        assert _label_semantics_violations(good, 'fixture') == []


@pytest.mark.parametrize(
    'bad',
    [
        '<label>Name</label><input aria-label="Name">',
        '<label for="missing">Name</label><input id="other">',
        '<label><input></label>',
        '<label>Name<input><button>Browse</button></label>',
    ],
)
def test_the_label_checker_rejects_orphan_empty_and_ambiguous_labels(bad):
    assert len(_label_semantics_violations(bad, 'fixture')) == 1


def test_an_explicit_label_cannot_also_hide_an_orphan_nested_control():
    mixed = '<label for="x">Name<input id="y"></label><input id="x">'

    assert len(_label_semantics_violations(mixed, 'fixture')) == 1
    assert len(_fragment_violations(mixed, 'fixture')) == 1


@pytest.mark.parametrize(
    'empty_explicit',
    [
        '<label for="">Name<input></label>',
        '<label :for="">Name<input></label>',
        '<label :for="\'\'">Name</label><input :id="\'\'">',
        '<label :for="\'   \'">Name</label><input :id="\'   \'">',
    ],
)
def test_an_empty_explicit_for_never_becomes_an_implicit_label(empty_explicit):

    assert len(_label_semantics_violations(empty_explicit, 'fixture')) == 1
    assert len(_fragment_violations(empty_explicit, 'fixture')) == 1


def test_static_and_bound_associations_cannot_be_combined_on_one_label():
    ambiguous = (
        '<label for="x" :for="missing">Name</label><input id="x">'
    )

    assert len(_label_semantics_violations(ambiguous, 'fixture')) == 1
    assert len(_fragment_violations(ambiguous, 'fixture')) == 1


@pytest.mark.parametrize(
    'mixed_modes',
    [
        '<label for="x">Name</label><input :id="x">',
        '<label :for="x">Name</label><input id="x">',
    ],
)
def test_static_and_bound_association_modes_do_not_cross_match(mixed_modes):
    assert len(_label_semantics_violations(mixed_modes, 'fixture')) == 1
    assert len(_fragment_violations(mixed_modes, 'fixture')) == 1


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


def test_script_markup_extraction_fails_closed_on_backtick_examples_in_comments():
    comment_markup = '<label for="example">Example</label><input id="example">'
    rendered_markup = '<label for="name">Name</label><input id="name">'
    script = (
        f'// Example only: `{comment_markup}`\n'
        f'const rendered = `{rendered_markup}`;'
    )

    assert list(_js_html_strings(script)) == [comment_markup, rendered_markup]


def test_script_markup_extraction_fails_loudly_on_an_unmatched_comment_backtick():
    script = (
        '// prose uses one ` delimiter\n'
        'const rendered = `<label for="name">Name</label><input id="name">`;'
    )

    with pytest.raises(AssertionError, match='outside a paired backtick span'):
        list(_js_html_strings(script))


def test_script_markup_extraction_respects_comment_markers_inside_strings():
    markup = '<label for="name">Name</label><input id="name">'
    scripts = (
        f'const docs = "https://example.test"; const rendered = `{markup}`;',
        f'const token = "/*"; const rendered = `{markup}`; const end = "*/";',
        f'const quote = "escaped \\\" // text"; const rendered = `{markup}`;',
        f'const protocol = /^https?:\\/\\//; const rendered = `{markup}`;',
        f'const slashes = /\\/\\//; const rendered = `{markup}`;',
    )

    for script in scripts:
        assert list(_js_html_strings(script)) == [markup]


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


def test_the_loop_checker_does_not_double_count_a_nested_loop():
    """Round 2 review (C4): `find_all('template', attrs={'x-for': True})`
    matches BOTH the outer and the inner loop in wizard.html's real shape (a
    tracker loop containing a per-tracker field loop, wizard.html:297/:311).
    Walking the outer loop's subtree with `find_all` also walks the inner
    loop's elements, and the inner loop is then walked a second time as its
    own top-level match -- so one real static-id defect was reported twice,
    which would have doubled every count a caller relied on. Two distinct
    violations (one label, one input) must be reported as exactly two, not
    four."""
    nested_bad = (
        '<template x-for="tracker in trackers" :key="tracker.id">'
        '<div>'
        '<template x-for="field in tracker.fields" :key="field.name">'
        '<div><label for="field-id">X</label><input id="field-id"></div>'
        '</template>'
        '</div>'
        '</template>'
    )
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False) as f:
        f.write(nested_bad)
        nested_path = Path(f.name)

    try:
        violations = find_static_id_in_loop_violations(nested_path)
        assert len(violations) == 2, (
            'one static-id label and one static-id input inside a nested '
            'x-for must be reported once each, not once per loop level they '
            'sit inside -- got %r' % violations)
    finally:
        nested_path.unlink()


# --- the guard, run against the real templates -------------------------------

def test_wizard_uses_native_fieldsets_for_control_groups():
    wizard = TEMPLATES_DIR / 'wizard.html'
    soup = BeautifulSoup(_strip_jinja_comments(wizard.read_text()), 'html.parser')
    fieldsets = soup.find_all('fieldset')

    assert [fieldset.get(':aria-label') for fieldset in fieldsets] == [
        'tracker.name', None, None
    ]
    assert [fieldset.get('aria-labelledby') for fieldset in fieldsets] == [
        None, 'wizard-usenet-client-heading', 'wizard-torrent-client-heading'
    ]
    assert soup.find_all(attrs={'role': 'group'}) == []


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


@pytest.mark.parametrize(
    'path', LABEL_TEMPLATE_FILES,
    ids=lambda p: str(p.relative_to(TEMPLATES_DIR)),
)
def test_every_label_has_text_and_exactly_one_associated_control(path):
    """A label is semantic, not merely visual: its one control must resolve."""
    violations = find_label_semantics_violations(path)

    assert violations == [], (
        'found %d invalid label(s) in %s (need non-empty text and exactly one '
        'matching for/id target or one wrapped labelable control):\n%s'
        % (len(violations), path.name, '\n'.join(violations))
    )
