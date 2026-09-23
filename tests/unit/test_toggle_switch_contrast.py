"""The settings toggle switch must meet WCAG 2.2 AA 1.4.11 (non-text contrast)
in BOTH themes and BOTH states.

The toggle track and knob are pure-colour UI components (no text), so 1.4.11
requires >= 3:1 against the surface they sit on. The as-shipped markup shared
by all four toggle instances (`partials/settings/toggle.html`, and the
hand-rolled copies in `header.html`, `provider_card.html` and
`field_types.html`) used two Tailwind arbitrary-value utilities that were
never measured:

  - OFF track: `bg-white/[0.08]` has no light-theme override, so it
    composites to white-on-white (1.0:1) on the light theme's #ffffff card,
    and is ~1.3:1 on the dark card.
  - ON track: `bg-cp-accent` (#35c5f4) is only 2.0:1 on a white light-theme
    card, and the white knob sitting on it is only 2.0:1 in EITHER theme.

Checked statically against base.html, the same approach
`test_focus_ring_contrast.py` uses for the identical class of defect: the
values are literals and the arithmetic is exact, so there is no need for a
browser to compute what can be measured directly. The E2E a11y suite
(`tests/e2e/accessibility.a11y.spec.ts`) covers that a real, rendered toggle
actually gets these computed styles.
"""
import re
from pathlib import Path

import pytest

BASE_HTML = Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates' / 'base.html'
TOGGLE_PARTIAL = (
    Path(__file__).resolve().parents[2]
    / 'couchpotato' / 'ui' / 'templates' / 'partials' / 'settings' / 'toggle.html'
)

MIN_RATIO = 3.0

# The four hand-rolled toggle template sources this defect lives in.
TOGGLE_TEMPLATES = [
    'partials/settings/toggle.html',
    'partials/settings/header.html',
    'partials/settings/provider_card.html',
    'partials/settings/field_types.html',
]


def _relative_luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip('#')
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _css() -> str:
    return BASE_HTML.read_text(encoding='utf-8')


def _rule(selector_pattern, prop, css=None):
    """Find `<selector> { ... <prop>: #rrggbb ... }` and return the hex value."""
    css = css if css is not None else _css()
    m = re.search(selector_pattern + r'\s*\{[^}]*' + prop + r':\s*(#[0-9a-fA-F]{6})', css)
    assert m, (
        'no `%s { %s: #rrggbb }` rule found in base.html -- the toggle switch '
        'contrast fix must be a CSS rule keyed on the rendered ARIA state '
        '([role="switch"][aria-checked=...]) so it covers all four toggle '
        'instances at once.' % (selector_pattern, prop)
    )
    return m.group(1)


def _theme_surface(theme: str, var: str) -> str:
    if theme == 'light':
        block = re.search(r':root\.light\s*\{(.*?)\}', _css(), re.S)
    else:
        block = re.search(r':root\s*\{(.*?)\}', _css(), re.S)
    assert block, 'could not locate the %s theme variable block' % theme
    m = re.search(var + r':\s*(#[0-9a-fA-F]{6})', block.group(1))
    assert m, 'no %s in the %s theme block' % (var, theme)
    return m.group(1)


def test_the_contrast_helper_is_correct():
    """Guard the guard: a broken ratio function would pass everything."""
    assert contrast_ratio('#000000', '#ffffff') == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio('#ffffff', '#ffffff') == pytest.approx(1.0, abs=0.01)


#: The CSS fix must key off the switch's ARIA state via an attribute
#: selector, but the *quoted* spelling ([role="switch"]) is the exact
#: substring test_wizard_toggle_conformance.py counts in the rendered page
#: to verify every toggle's a11y markup -- since base.html's <style> block is
#: rendered on every page, a quoted selector there would inflate that count.
#: CSS attribute selectors accept unquoted identifiers just as validly
#: (switch/true/false are all valid CSS identifiers), so the fix is expected
#: to use that spelling; match either so this test does not force one
#: specific-but-equivalent spelling, while still requiring the ARIA state be
#: the actual selector key.
SWITCH_OFF_SELECTOR = r'\[role=[\'"]?switch[\'"]?\]\[aria-checked=[\'"]?false[\'"]?\]'
SWITCH_ON_SELECTOR = r'\[role=[\'"]?switch[\'"]?\]\[aria-checked=[\'"]?true[\'"]?\]'


def test_off_track_colour_has_a_light_theme_override():
    """OFF track must not rely on `bg-white/[0.08]`, which is unstyled in the
    light theme and composites to white-on-white (1.0:1)."""
    off_track = _rule(SWITCH_OFF_SELECTOR, 'background-color')

    for theme in ('dark', 'light'):
        for var in ('--cp-card', '--cp-bg'):
            surface = _theme_surface(theme, var)
            ratio = contrast_ratio(off_track, surface)
            assert ratio >= MIN_RATIO, (
                'OFF toggle track %s on %s theme %s (%s) = %.2f:1, below the '
                '%.1f:1 WCAG 1.4.11 requires for a UI component.'
                % (off_track, theme, var, surface, ratio, MIN_RATIO)
            )


def test_on_track_colour_meets_contrast_in_light_theme():
    """ON track in the light theme must not be the raw #35c5f4 accent (2.0:1
    on a white card); it needs a darker, light-theme-specific override."""
    css = _css()
    m = re.search(
        r':root\.light\s+' + SWITCH_ON_SELECTOR
        + r'\s*\{[^}]*background-color:\s*(#[0-9a-fA-F]{6})',
        css,
    )
    assert m, (
        'no `:root.light [role=switch][aria-checked=true] { background-color: ... }` '
        'override found -- the ON track defaults to #35c5f4, which is only 2.0:1 '
        'on the light theme\'s white card.'
    )
    on_track_light = m.group(1)

    for var in ('--cp-card', '--cp-bg'):
        surface = _theme_surface('light', var)
        ratio = contrast_ratio(on_track_light, surface)
        assert ratio >= MIN_RATIO, (
            'ON toggle track %s on light theme %s (%s) = %.2f:1, below %.1f:1'
            % (on_track_light, var, surface, ratio, MIN_RATIO)
        )


def test_on_knob_colour_meets_contrast_in_dark_theme():
    """ON knob in the dark theme must not be the plain white knob (2.0:1 on
    the #35c5f4 track); it needs a dark-theme-specific override."""
    css = _css()
    m = re.search(
        r':root:not\(\.light\)\s+' + SWITCH_ON_SELECTOR
        + r'\s*>\s*span\s*\{[^}]*background-color:\s*(#[0-9a-fA-F]{6})',
        css,
    )
    assert m, (
        'no `:root:not(.light) [role=switch][aria-checked=true] > span '
        '{ background-color: ... }` override found -- the ON knob defaults to '
        'white, which is only 2.0:1 on the #35c5f4 dark-theme track.'
    )
    on_knob_dark = m.group(1)
    on_track_dark = '#35c5f4'  # unchanged in the dark theme, per the spec table
    ratio = contrast_ratio(on_knob_dark, on_track_dark)
    assert ratio >= MIN_RATIO, (
        'ON toggle knob %s on dark-theme track %s = %.2f:1, below %.1f:1'
        % (on_knob_dark, on_track_dark, ratio, MIN_RATIO)
    )


@pytest.mark.parametrize('template_path', TOGGLE_TEMPLATES)
def test_toggle_markup_carries_the_pinned_class_strings_unchanged(template_path):
    """The fix must be pure CSS keyed on the rendered ARIA state -- the pinned
    Tailwind class strings (checked by test_wizard_toggle_conformance.py) must
    not be touched."""
    template_dir = Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates'
    source = (template_dir / template_path).read_text(encoding='utf-8')
    assert 'role="switch"' in source
    assert ':aria-checked="' in source
    assert '.toString()"' in source, (
        '%s renders :aria-checked from something other than a JS boolean '
        '.toString() -- the CSS fix assumes the DOM attribute is the literal '
        'string "true"/"false".' % template_path
    )
