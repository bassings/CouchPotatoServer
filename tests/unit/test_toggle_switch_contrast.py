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
browser to compute what can be measured directly. The E2E suite
(`tests/e2e/toggle-switch-contrast.a11y.spec.ts`) covers that a real,
rendered toggle actually gets these computed styles.
"""
import re
from pathlib import Path

import pytest

BASE_HTML = Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates' / 'base.html'
WIZARD_HTML = Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates' / 'wizard.html'

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


def _composite(top_hex: str, alpha: float, base_hex: str) -> str:
    """Alpha-composite `top_hex` (at `alpha`) over the opaque `base_hex`."""
    t = top_hex.lstrip('#')
    b = base_hex.lstrip('#')
    tr, tg, tb = (int(t[i:i + 2], 16) for i in (0, 2, 4))
    br, bgc, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    r = round(alpha * tr + (1 - alpha) * br)
    g = round(alpha * tg + (1 - alpha) * bgc)
    bl = round(alpha * tb + (1 - alpha) * bb)
    return '#%02x%02x%02x' % (r, g, bl)


def _css() -> str:
    return BASE_HTML.read_text(encoding='utf-8')


def _strip_comments(css: str) -> str:
    """Remove `/* ... */` CSS comments.

    Comments contain no braces, so left in place they merge into whatever
    selector text precedes the next rule -- and every toggle rule here sits
    right after a long explanatory comment, so `_split_rules` without this
    would capture "…that same rendered output, so … [role=switch]…" as the
    "selector" and never fullmatch anything.
    """
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def _split_rules(css: str):
    """Yield (selector, body) for each flat CSS rule in `css`.

    This only stays correct up to the first NESTED block (base.html has one:
    the `@media (prefers-reduced-motion: reduce)` query, well after every
    selector this module cares about) -- every rule these tests look up sits
    earlier in the stylesheet than that, so it is never reached.
    """
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', _strip_comments(css), re.S):
        yield m.group(1).strip(), m.group(2)


def _rule_by_exact_selector(selector_pattern: str, prop: str, css: str = None):
    """Find the CSS rule whose selector -- once outer whitespace is
    collapsed -- FULLMATCHES `selector_pattern`, and return `prop`'s hex
    value from its body, or None.

    Anchoring matters: a plain substring search (`re.search`) matches
    `:root.light SELECTOR { ... }` exactly as happily as bare
    `SELECTOR { ... }`, so a rule accidentally mis-scoped to one theme (e.g.
    the OFF-state rule, which must apply in BOTH themes, scoped down to only
    `:root.light`) would still "find" a value and get validated against the
    wrong theme's surfaces without ever noticing the scope was wrong. A
    fullmatch on the normalised selector is what makes that mistake fail
    loudly instead of silently passing.
    """
    css = css if css is not None else _css()
    for selector, body in _split_rules(css):
        normalized = re.sub(r'\s+', ' ', selector).strip()
        if re.fullmatch(selector_pattern, normalized):
            m = re.search(prop + r':\s*(#[0-9a-fA-F]{6})', body)
            if m:
                return m.group(1)
    return None


def _theme_surface(theme: str, var: str) -> str:
    if theme == 'light':
        block = re.search(r':root\.light\s*\{(.*?)\}', _css(), re.S)
    else:
        block = re.search(r':root\s*\{(.*?)\}', _css(), re.S)
    assert block, 'could not locate the %s theme variable block' % theme
    m = re.search(var + r':\s*(#[0-9a-fA-F]{6})', block.group(1))
    assert m, 'no %s in the %s theme block' % (var, theme)
    return m.group(1)


def _accent_colour() -> str:
    """The brand accent (`cp.accent`), read from base.html's tailwind.config
    rather than hardcoded, so a future accent change is caught here too."""
    m = re.search(r"accent:\s*'(#[0-9a-fA-F]{6})'", _css())
    assert m, "no accent: '#rrggbb' found in base.html's tailwind.config"
    return m.group(1)


def _wizard_tinted_row_alpha() -> float:
    """The white tint (`bg-white/[0.0x]`) wizard.html uses on its row/panel
    backgrounds, read from the template rather than hardcoded so a future
    tint change is picked up automatically."""
    source = WIZARD_HTML.read_text(encoding='utf-8')
    m = re.search(r'bg-white/\[(0\.\d+)\]', source)
    assert m, 'wizard.html no longer tints its row panels with bg-white/[0.0x]'
    return float(m.group(1))


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
ON_LIGHT_SELECTOR = r':root\.light ' + SWITCH_ON_SELECTOR
ON_DARK_KNOB_SELECTOR = r':root:not\(\.light\) ' + SWITCH_ON_SELECTOR + r' > span'


def test_the_contrast_helper_is_correct():
    """Guard the guard: a broken ratio function would pass everything."""
    assert contrast_ratio('#000000', '#ffffff') == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio('#ffffff', '#ffffff') == pytest.approx(1.0, abs=0.01)


def test_the_composite_helper_is_correct():
    """Guard the guard: a broken compositor would validate the wrong colour
    for the wizard's tinted-surface check below."""
    assert _composite('#ffffff', 1.0, '#000000') == '#ffffff'
    assert _composite('#ffffff', 0.0, '#123456') == '#123456'
    # 2% white over --cp-bg's dark theme card (#161618) ~= #1b1b1d, the
    # number this module's own docstring/tests were measured against.
    assert _composite('#ffffff', 0.02, '#161618') == '#1b1b1d'


def test_off_track_colour_has_a_light_theme_override():
    """OFF track must not rely on `bg-white/[0.08]`, which is unstyled in the
    light theme and composites to white-on-white (1.0:1). The rule must be
    UNSCOPED (apply in both themes) -- fullmatch, not substring search, so a
    rule accidentally scoped to only one theme is caught rather than quietly
    validated against both."""
    off_track = _rule_by_exact_selector(SWITCH_OFF_SELECTOR, 'background-color')
    assert off_track, (
        'no unscoped `%s { background-color: #rrggbb }` rule found in '
        'base.html -- either missing, or present but scoped under a '
        '`:root.light`/`:root:not(.light)` ancestor, which would leave the '
        'other theme with no OFF-track override at all.' % SWITCH_OFF_SELECTOR
    )

    for theme in ('dark', 'light'):
        for var in ('--cp-card', '--cp-bg'):
            surface = _theme_surface(theme, var)
            ratio = contrast_ratio(off_track, surface)
            assert ratio >= MIN_RATIO, (
                'OFF toggle track %s on %s theme %s (%s) = %.2f:1, below the '
                '%.1f:1 WCAG 1.4.11 requires for a UI component.'
                % (off_track, theme, var, surface, ratio, MIN_RATIO)
            )


def test_off_track_meets_contrast_on_the_wizards_tinted_row_surface():
    """wizard.html renders its toggles inside a lightly-tinted panel
    (`bg-white/[0.0x]` over the dark card), not the flat --cp-card colour --
    a slightly lighter, less forgiving real surface the plain --cp-card
    check above does not exercise."""
    off_track = _rule_by_exact_selector(SWITCH_OFF_SELECTOR, 'background-color')
    assert off_track, 'no unscoped OFF-track rule found (see the test above)'

    dark_card = _theme_surface('dark', '--cp-card')
    tinted_surface = _composite('#ffffff', _wizard_tinted_row_alpha(), dark_card)
    ratio = contrast_ratio(off_track, tinted_surface)
    assert ratio >= MIN_RATIO, (
        'OFF toggle track %s on the wizard row panel surface %s (dark card '
        '%s tinted %.0f%% white) = %.2f:1, below %.1f:1'
        % (off_track, tinted_surface, dark_card, _wizard_tinted_row_alpha() * 100, ratio, MIN_RATIO)
    )


def test_off_knob_colour_meets_contrast_against_the_off_track():
    """OFF knob is the unchanged white span -- confirm it still clears 3:1
    against the new OFF-track colour (both themes share one OFF track)."""
    off_track = _rule_by_exact_selector(SWITCH_OFF_SELECTOR, 'background-color')
    assert off_track, 'no unscoped OFF-track rule found (see the test above)'

    ratio = contrast_ratio('#ffffff', off_track)
    assert ratio >= MIN_RATIO, (
        'OFF toggle knob #ffffff on track %s = %.2f:1, below %.1f:1'
        % (off_track, ratio, MIN_RATIO)
    )


def test_on_track_colour_meets_contrast_in_light_theme():
    """ON track in the light theme must not be the raw #35c5f4 accent (2.0:1
    on a white card); it needs a darker, light-theme-specific override,
    scoped exactly under `:root.light` (fullmatch, not substring search)."""
    on_track_light = _rule_by_exact_selector(ON_LIGHT_SELECTOR, 'background-color')
    assert on_track_light, (
        'no `%s { background-color: ... }` override found -- the ON track '
        "defaults to #35c5f4, which is only 2.0:1 on the light theme's "
        'white card.' % ON_LIGHT_SELECTOR
    )

    for var in ('--cp-card', '--cp-bg'):
        surface = _theme_surface('light', var)
        ratio = contrast_ratio(on_track_light, surface)
        assert ratio >= MIN_RATIO, (
            'ON toggle track %s on light theme %s (%s) = %.2f:1, below %.1f:1'
            % (on_track_light, var, surface, ratio, MIN_RATIO)
        )


def test_on_track_colour_meets_contrast_in_dark_theme():
    """ON track in the dark theme is the unchanged brand accent -- it always
    cleared 3:1, but is checked explicitly (and read from tailwind.config,
    not hardcoded) so a future accent change is caught here too."""
    accent = _accent_colour()
    for var in ('--cp-card', '--cp-bg'):
        surface = _theme_surface('dark', var)
        ratio = contrast_ratio(accent, surface)
        assert ratio >= MIN_RATIO, (
            'ON toggle track (accent) %s on dark theme %s (%s) = %.2f:1, '
            'below %.1f:1' % (accent, var, surface, ratio, MIN_RATIO)
        )


def test_on_knob_colour_meets_contrast_in_dark_theme():
    """ON knob in the dark theme must not be the plain white knob (2.0:1 on
    the accent track); it needs a dark-theme-specific override, scoped
    exactly under `:root:not(.light) ... > span` (fullmatch)."""
    on_knob_dark = _rule_by_exact_selector(ON_DARK_KNOB_SELECTOR, 'background-color')
    assert on_knob_dark, (
        'no `%s { background-color: ... }` override found -- the ON knob '
        'defaults to white, which is only 2.0:1 on the dark-theme accent '
        'track.' % ON_DARK_KNOB_SELECTOR
    )
    on_track_dark = _accent_colour()  # unchanged in the dark theme
    ratio = contrast_ratio(on_knob_dark, on_track_dark)
    assert ratio >= MIN_RATIO, (
        'ON toggle knob %s on dark-theme track %s = %.2f:1, below %.1f:1'
        % (on_knob_dark, on_track_dark, ratio, MIN_RATIO)
    )


def test_on_knob_colour_meets_contrast_in_light_theme():
    """ON knob in the light theme is the unchanged white span -- confirm it
    clears 3:1 against the light-theme ON-track override."""
    on_track_light = _rule_by_exact_selector(ON_LIGHT_SELECTOR, 'background-color')
    assert on_track_light, 'no light-theme ON-track override found (see the test above)'

    ratio = contrast_ratio('#ffffff', on_track_light)
    assert ratio >= MIN_RATIO, (
        'ON toggle knob #ffffff on light-theme track %s = %.2f:1, below %.1f:1'
        % (on_track_light, ratio, MIN_RATIO)
    )


@pytest.mark.parametrize('template_path', TOGGLE_TEMPLATES)
def test_toggle_markup_still_renders_a_boolean_aria_checked_binding(template_path):
    """The CSS fix above is only reachable if `aria-checked` is actually
    rendered as the literal string "true"/"false" -- it selects on
    `[aria-checked=true]`/`[aria-checked=false]`, so a toggle instance that
    started rendering some other value (or dropped `role="switch"` /
    `:aria-checked` entirely) would silently stop being styled by it. This
    does not check the pinned Tailwind SIZE classes (`w-8 h-4` etc.) --
    those are guarded by test_wizard_toggle_conformance.py."""
    template_dir = Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates'
    source = (template_dir / template_path).read_text(encoding='utf-8')
    assert 'role="switch"' in source
    assert ':aria-checked="' in source
    assert '.toString()"' in source, (
        '%s renders :aria-checked from something other than a JS boolean '
        '.toString() -- the CSS fix assumes the DOM attribute is the literal '
        'string "true"/"false".' % template_path
    )
