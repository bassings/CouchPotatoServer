"""Structural + arithmetic checks for the settings toggle switch's WCAG 2.2 AA
1.4.11 (non-text contrast) fix in `base.html`.

Static checks prove the pinned rules exist, unnested, with these literals,
and that those literals meet 3:1; they do not model the cascade or which
declaration wins. tests/e2e/toggle-switch-contrast.a11y.spec.ts measures
what the browser paints and is the authority.
"""
import re

import pytest

from couchpotato.ui import _jinja

MIN_RATIO = 3.0

# The exact selectors this fix pins, normalised (collapsed whitespace,
# stripped). Unquoted attribute values (`role=switch`, not `role="switch"`)
# are deliberate: the quoted spelling is the exact substring
# test_wizard_toggle_conformance.py counts in the rendered page to check
# every toggle's a11y markup, and this stylesheet ships on every page.
TOGGLE_OFF_SELECTOR = '[role=switch][aria-checked=false]'
TOGGLE_ON_LIGHT_SELECTOR = ':root.light [role=switch][aria-checked=true]'
TOGGLE_ON_DARK_KNOB_SELECTOR = ':root:not(.light) [role=switch][aria-checked=true] > span'
FORCED_COLOURS_SELECTORS = {
    '[role=switch]',
    '[role=switch] > span',
    '[role=switch][aria-checked=false]',
    '[role=switch][aria-checked=false] > span',
    '[role=switch][aria-checked=true]',
    '[role=switch][aria-checked=true] > span',
}

# The exact colour literals this fix pins. Measured, real contrast ratios
# against a live-rendered page live in the E2E spec, not here.
TOGGLE_OFF_COLOUR = '#71717a'
TOGGLE_ON_LIGHT_COLOUR = '#0e7490'
TOGGLE_ON_DARK_KNOB_COLOUR = '#0d0d0d'

_ROLE_SWITCH_SELECTOR_RE = re.compile(r'\[role=[\'"]?switch[\'"]?\]', re.I)


def _relative_luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip('#')
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _render_base_html() -> str:
    """Render base.html through the REAL Jinja pipeline, not read its source
    as text -- a rule wrapped in `{% if false %}...{% endif %}` is present
    in the source file but absent from every render, and only rendering
    catches that."""
    ctx = {'api_key': 'test-key', 'api_base': '/api/test-key', 'web_base': '/', 'new_base': '/'}
    return _jinja.get_template('base.html').render(**ctx)


def _strip_comments(css: str) -> str:
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def _style_block_contents(html: str):
    """The raw contents of every `<style>` element in `html`."""
    return re.findall(r'<style\b[^>]*>(.*?)</style>', html, re.S)


def _iter_rules(css: str):
    """Yield (normalised_selector, body, depth) for every brace-delimited
    rule in `css`, via a real brace-depth stack.

    `depth` is 0 for a rule that sits directly in the stylesheet and >0 for
    one nested inside e.g. an `@media` or `@keyframes` block -- which is
    exactly the shape `@media print { <selector> { ... } }` produces: the
    selector text is unchanged, but its depth is 1, not 0.
    """
    stack = []
    depth = 0
    last_end = 0
    for i, ch in enumerate(css):
        if ch == '{':
            selector = re.sub(r'\s+', ' ', css[last_end:i]).strip()
            stack.append((depth, selector, i + 1))
            depth += 1
            last_end = i + 1
        elif ch == '}':
            depth -= 1
            depth_before, selector, body_start = stack.pop()
            yield selector, css[body_start:i], depth_before
            last_end = i + 1


def _all_style_rules():
    html = _render_base_html()
    blocks = _style_block_contents(html)
    assert blocks, 'base.html rendered no <style> element to check'
    rules = []
    for block in blocks:
        rules.extend(_iter_rules(_strip_comments(block)))
    return rules


_BACKGROUND_PROPERTY_RE = re.compile(r'^(background|background-color)\s*:\s*(.*)$', re.I)


def _rule_colour(selector: str):
    """The single top-level rule matching `selector` exactly (asserted to
    be exactly one, at depth 0), returning the plain `#rrggbb` value of its
    FIRST background/background-color declaration for the contrast
    arithmetic. Only that first declaration is checked; which declaration
    the browser actually applies is the E2E spec's job.
    """
    rules = _all_style_rules()
    matches = [r for r in rules if r[0] == selector and r[2] == 0]
    assert len(matches) == 1, (
        'expected exactly one `%s { ... }` rule in the rendered stylesheet, '
        'found %d. Zero can mean the rule was removed, or wrapped in a '
        'Jinja `{%% if %%}...{%% endif %%}` block that always evaluates '
        'false (Jinja strips that from every render, so the source can '
        'still "have" the rule while no render ever does). More than one '
        'means a later rule with the same selector was appended -- it wins '
        'the cascade over the first, silently.' % (selector, len(matches))
    )
    found_selector, body, depth = matches[0]
    assert depth == 0, (
        'the `%s` rule is nested %d level(s) deep (e.g. inside an `@media` '
        'block) instead of sitting directly in the stylesheet -- content '
        'inside `@media print { ... }` never applies on screen, so the '
        'rule "existing" in the file proves nothing about what renders.'
        % (selector, depth)
    )

    declarations = [d.strip() for d in body.split(';') if d.strip()]
    background_decls = [m for d in declarations for m in [_BACKGROUND_PROPERTY_RE.match(d)] if m]
    assert background_decls, 'no background declaration in the `%s` rule body (%r)' % (selector, body.strip())

    value = background_decls[0].group(2).strip()
    m = re.fullmatch(r'#[0-9a-fA-F]{6}', value)
    assert m, (
        'value is not a plain #rrggbb, got %r; the contrast arithmetic needs a literal'
        % value
    )
    return value


def _theme_surface(theme: str, var: str) -> str:
    html = _render_base_html()
    css = '\n'.join(_style_block_contents(html))
    if theme == 'light':
        block = re.search(r':root\.light\s*\{(.*?)\}', css, re.S)
    else:
        block = re.search(r':root\s*\{(.*?)\}', css, re.S)
    assert block, 'could not locate the %s theme variable block' % theme
    m = re.search(var + r':\s*(#[0-9a-fA-F]{6})', block.group(1))
    assert m, 'no %s in the %s theme block' % (var, theme)
    return m.group(1)


def _accent_colour() -> str:
    """The brand accent (`cp.accent`), read from base.html's tailwind.config
    rather than hardcoded, so a future accent change is caught here too."""
    html = _render_base_html()
    m = re.search(r"accent:\s*'(#[0-9a-fA-F]{6})'", html)
    assert m, "no accent: '#rrggbb' found in base.html's tailwind.config"
    return m.group(1)


def test_the_contrast_helper_is_correct():
    """Guard the guard: a broken ratio function would pass everything."""
    assert contrast_ratio('#000000', '#ffffff') == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio('#ffffff', '#ffffff') == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Structural: does each pinned rule exist, once, unnested, with its pinned
# colour -- in the RENDERED page, not merely the source file?
# ---------------------------------------------------------------------------

def test_off_rule_is_a_single_top_level_rule_with_the_pinned_colour():
    colour = _rule_colour(TOGGLE_OFF_SELECTOR)
    assert colour.lower() == TOGGLE_OFF_COLOUR, (
        'OFF-track rule renders background-color: %s, expected %s'
        % (colour, TOGGLE_OFF_COLOUR)
    )


def test_on_light_rule_is_a_single_top_level_rule_with_the_pinned_colour():
    colour = _rule_colour(TOGGLE_ON_LIGHT_SELECTOR)
    assert colour.lower() == TOGGLE_ON_LIGHT_COLOUR, (
        'ON-track light-theme rule renders background-color: %s, expected %s'
        % (colour, TOGGLE_ON_LIGHT_COLOUR)
    )


def test_on_dark_knob_rule_is_a_single_top_level_rule_with_the_pinned_colour():
    colour = _rule_colour(TOGGLE_ON_DARK_KNOB_SELECTOR)
    assert colour.lower() == TOGGLE_ON_DARK_KNOB_COLOUR, (
        'ON-track dark-theme knob rule renders background-color: %s, expected %s'
        % (colour, TOGGLE_ON_DARK_KNOB_COLOUR)
    )


def test_no_other_rule_in_the_stylesheet_targets_the_switch_role():
    """This is a selector-text match for a second `[role=switch]` rule, not
    a cascade check; an override keyed on any other selector is
    tests/e2e/toggle-switch-contrast.a11y.spec.ts's job to catch."""
    rules = _all_style_rules()
    expected = {
        (TOGGLE_OFF_SELECTOR, 0),
        (TOGGLE_ON_LIGHT_SELECTOR, 0),
        (TOGGLE_ON_DARK_KNOB_SELECTOR, 0),
        *((selector, 1) for selector in FORCED_COLOURS_SELECTORS),
    }
    extra = [
        (selector, depth) for selector, _body, depth in rules
        if _ROLE_SWITCH_SELECTOR_RE.search(selector) and (selector, depth) not in expected
    ]
    assert not extra, (
        'found %d additional CSS rule(s) targeting the switch role beyond '
        'the pinned screen and forced-colours selectors: %r' % (len(extra), extra)
    )


# ---------------------------------------------------------------------------
# Arithmetic: do the pinned colour literals clear 3:1 against the theme's
# own CSS custom properties? Real, rendered surfaces (tinted panels, cards
# behind translucency, mid-transition frames) are the E2E spec's job.
# ---------------------------------------------------------------------------

def test_off_track_colour_meets_contrast_against_theme_surfaces():
    for theme in ('dark', 'light'):
        for var in ('--cp-card', '--cp-bg'):
            surface = _theme_surface(theme, var)
            ratio = contrast_ratio(TOGGLE_OFF_COLOUR, surface)
            assert ratio >= MIN_RATIO, (
                'OFF toggle track %s on %s theme %s (%s) = %.2f:1, below %.1f:1'
                % (TOGGLE_OFF_COLOUR, theme, var, surface, ratio, MIN_RATIO)
            )


def test_off_knob_colour_meets_contrast_against_the_off_track():
    ratio = contrast_ratio('#ffffff', TOGGLE_OFF_COLOUR)
    assert ratio >= MIN_RATIO, (
        'OFF toggle knob #ffffff on track %s = %.2f:1, below %.1f:1'
        % (TOGGLE_OFF_COLOUR, ratio, MIN_RATIO)
    )


def test_on_track_colour_meets_contrast_in_light_theme():
    for var in ('--cp-card', '--cp-bg'):
        surface = _theme_surface('light', var)
        ratio = contrast_ratio(TOGGLE_ON_LIGHT_COLOUR, surface)
        assert ratio >= MIN_RATIO, (
            'ON toggle track %s on light theme %s (%s) = %.2f:1, below %.1f:1'
            % (TOGGLE_ON_LIGHT_COLOUR, var, surface, ratio, MIN_RATIO)
        )


def test_on_knob_colour_meets_contrast_in_light_theme():
    ratio = contrast_ratio('#ffffff', TOGGLE_ON_LIGHT_COLOUR)
    assert ratio >= MIN_RATIO, (
        'ON toggle knob #ffffff on light-theme track %s = %.2f:1, below %.1f:1'
        % (TOGGLE_ON_LIGHT_COLOUR, ratio, MIN_RATIO)
    )


def test_on_track_colour_meets_contrast_in_dark_theme():
    """ON track in the dark theme is the unchanged brand accent -- read from
    tailwind.config rather than hardcoded, so a future accent change is
    caught here too."""
    accent = _accent_colour()
    for var in ('--cp-card', '--cp-bg'):
        surface = _theme_surface('dark', var)
        ratio = contrast_ratio(accent, surface)
        assert ratio >= MIN_RATIO, (
            'ON toggle track (accent) %s on dark theme %s (%s) = %.2f:1, '
            'below %.1f:1' % (accent, var, surface, ratio, MIN_RATIO)
        )


def test_on_knob_colour_meets_contrast_in_dark_theme():
    accent = _accent_colour()
    ratio = contrast_ratio(TOGGLE_ON_DARK_KNOB_COLOUR, accent)
    assert ratio >= MIN_RATIO, (
        'ON toggle knob %s on dark-theme track (accent) %s = %.2f:1, below %.1f:1'
        % (TOGGLE_ON_DARK_KNOB_COLOUR, accent, ratio, MIN_RATIO)
    )
