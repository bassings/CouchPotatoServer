"""Regression tests for UI-CONFORM-01 (toggle switch normalization).

The design system's canonical toggle switch is track `w-8 h-4`, knob
`w-3 h-3`, `translate-x-4`/`translate-x-0.5`, with `role="switch"`,
`:aria-checked`, and an `aria-label`.

`couchpotato/ui/templates/wizard.html` used to render 8 toggles with a
larger, undocumented `w-10 h-5` / `w-4 h-4` / `translate-x-5` variant, and
those toggles were missing `role="switch"`, `:aria-checked`, and
`aria-label` entirely (a real accessibility gap). These tests render the
actual Jinja templates (not a copy) so they fail if the non-conformant
markup, or the missing a11y attributes, ever comes back.
"""

import glob
import os
import re

import pytest

from couchpotato.ui import _jinja, _template_dir


def _render(template_name, **extra_ctx):
    ctx = {
        'api_key': 'test-key',
        'api_base': '/api/test-key',
        'web_base': '/',
        'new_base': '/',
    }
    ctx.update(extra_ctx)
    return _jinja.get_template(template_name).render(**ctx)


def test_wizard_renders_no_non_conformant_toggle_markup():
    """wizard.html must not emit the legacy w-10 h-5 / translate-x-5 toggle."""
    rendered = _render('wizard.html', current_page='wizard')

    assert 'w-10 h-5' not in rendered, (
        'wizard.html still renders the non-conformant w-10 h-5 toggle track; '
        'toggles must use the canonical w-8 h-4 size (see '
        'partials/settings/toggle.html).'
    )
    assert 'translate-x-5' not in rendered, (
        'wizard.html still renders the non-conformant translate-x-5 knob '
        'offset; toggles must use translate-x-4 (on) / translate-x-0.5 (off).'
    )
    assert 'w-4 h-4 bg-white rounded-full' not in rendered, (
        'wizard.html still renders the non-conformant w-4 h-4 toggle knob; '
        'the canonical knob size is w-3 h-3.'
    )


def test_wizard_toggles_carry_full_accessibility_attributes():
    """Every wizard toggle must be a role=switch with :aria-checked + a label."""
    rendered = _render('wizard.html', current_page='wizard')

    switch_count = rendered.count('role="switch"')
    # Spec: 8 wizard toggles were identified as non-conformant.
    assert switch_count >= 8, (
        f'expected at least 8 role="switch" toggles in wizard.html, found {switch_count}'
    )
    assert rendered.count('w-8 h-4 rounded-full transition-colors shrink-0') == switch_count, (
        'every role="switch" toggle in wizard.html must use the canonical '
        'w-8 h-4 track size'
    )
    assert rendered.count(':aria-checked=') == switch_count, (
        'every role="switch" toggle in wizard.html must have :aria-checked'
    )

    # Every switch must carry either a static aria-label or a dynamic
    # :aria-label with non-empty content (never an empty aria-label="").
    label_pattern = re.compile(r'(?:aria-label|:aria-label)="([^"]*)"')
    labels = label_pattern.findall(rendered)
    assert len(labels) >= switch_count
    empty_labels = [l for l in labels if l.strip() in ('', '&#39;&#39;')]
    assert not empty_labels, f'found toggle(s)/controls with an empty aria-label: {empty_labels}'


def test_toggle_partial_matches_canonical_reference_markup():
    """The shared toggle.html partial must render the exact canonical markup."""
    tmpl = _jinja.get_template('partials/settings/toggle.html')
    rendered = tmpl.render(
        toggle_click="formData.example.enabled = !formData.example.enabled",
        toggle_model="formData.example.enabled",
        toggle_label="Enable Example",
        toggle_label_expr="",
    )

    assert 'class="relative w-8 h-4 rounded-full transition-colors shrink-0"' in rendered
    assert 'role="switch"' in rendered
    assert ':aria-checked="(formData.example.enabled).toString()"' in rendered
    assert 'aria-label="Enable Example"' in rendered
    assert "'translate-x-4' : 'translate-x-0.5'" in rendered
    assert 'class="block w-3 h-3 bg-white rounded-full transition-transform absolute top-0.5"' in rendered


def test_toggle_partial_supports_dynamic_aria_label():
    """Dynamic (Alpine-expression) aria-labels render as :aria-label, not aria-label."""
    tmpl = _jinja.get_template('partials/settings/toggle.html')
    rendered = tmpl.render(
        toggle_click="tracker.enabled = !tracker.enabled",
        toggle_model="tracker.enabled",
        toggle_label="",
        toggle_label_expr="'Enable ' + tracker.name",
    )

    assert ':aria-label=' in rendered
    assert 'aria-label="' not in rendered.replace(':aria-label="', '')


@pytest.mark.parametrize('template_path', [
    'partials/settings/field_types.html',
    'partials/settings/header.html',
    'partials/settings/provider_card.html',
])
def test_already_conformant_settings_toggles_stay_canonical(template_path):
    """Guard the three toggles the spec calls out as already-conformant."""
    with open(os.path.join(_template_dir, template_path)) as f:
        source = f.read()

    if 'role="switch"' not in source:
        pytest.skip(f'{template_path} has no toggle switch markup')

    assert 'w-10 h-5' not in source
    assert 'translate-x-5' not in source
    assert 'w-8 h-4' in source


def test_no_template_in_new_ui_renders_non_conformant_toggle_size():
    """Static sweep: no *.html under couchpotato/ui/templates emits w-10 h-5."""
    offenders = []
    for path in glob.glob(os.path.join(_template_dir, '**', '*.html'), recursive=True):
        with open(path) as f:
            source = f.read()
        if 'w-10 h-5' in source or 'translate-x-5' in source:
            offenders.append(os.path.relpath(path, _template_dir))

    assert not offenders, f'non-conformant toggle markup found in: {offenders}'
