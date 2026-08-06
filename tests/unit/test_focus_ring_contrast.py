"""The focus ring must meet WCAG 2.2 AA 1.4.11 in BOTH themes.

A focus indicator is a UI component, so it needs 3:1 against its background --
a separate requirement from 2.4.7 (focus visible), which only asks that one
exists. The two are easy to confuse, and this codebase shipped exactly that
confusion: `:focus-visible { outline: 2px solid #35c5f4 }` with no light-theme
override measured **9.40:1** on the dark background and **1.85:1** on the light
one. Present, and practically invisible.

Checked statically against the stylesheet rather than in a browser because the
values are literals in `base.html` and the arithmetic is exact; the E2E a11y
suite covers whether the ring actually appears on focus. axe-core does NOT
catch this -- it has no automated check for focus-indicator contrast, which is
why a green a11y run said nothing about it.
"""
import re
from pathlib import Path

import pytest

BASE_HTML = Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates' / 'base.html'

#: WCAG 2.2 AA, success criterion 1.4.11 Non-text Contrast.
MIN_RATIO = 3.0


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


def _dark_outline() -> str:
    m = re.search(r':focus-visible\s*\{[^}]*outline:\s*\d+px\s+solid\s+(#[0-9a-fA-F]{6})', _css())
    assert m, 'no `:focus-visible { outline: Npx solid #rrggbb }` rule found in base.html'
    return m.group(1)


def _light_outline() -> str:
    m = re.search(r':root\.light\s+:focus-visible\s*\{[^}]*outline-color:\s*(#[0-9a-fA-F]{6})', _css())
    assert m, (
        'no `:root.light :focus-visible { outline-color: … }` override found. '
        'The dark-theme accent measures 1.85:1 on the light background, so '
        'without this override the light theme fails WCAG 1.4.11.'
    )
    return m.group(1)


def _theme_background(theme: str) -> str:
    """`--cp-bg` for the given theme, read from base.html rather than hardcoded."""
    if theme == 'light':
        block = re.search(r':root\.light\s*\{(.*?)\}', _css(), re.S)
    else:
        block = re.search(r':root\s*\{(.*?)\}', _css(), re.S)
    assert block, 'could not locate the %s theme variable block' % theme
    m = re.search(r'--cp-bg:\s*(#[0-9a-fA-F]{6})', block.group(1))
    assert m, 'no --cp-bg in the %s theme block' % theme
    return m.group(1)


def test_the_contrast_helper_is_correct():
    """Guard the guard: a broken ratio function would pass everything."""
    assert contrast_ratio('#000000', '#ffffff') == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio('#ffffff', '#ffffff') == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_the_focus_ring_meets_non_text_contrast(theme):
    outline = _light_outline() if theme == 'light' else _dark_outline()
    background = _theme_background(theme)
    ratio = contrast_ratio(outline, background)

    assert ratio >= MIN_RATIO, (
        'the %s-theme focus ring is %s on %s = %.2f:1, below the %.1f:1 that '
        'WCAG 2.2 AA 1.4.11 requires for a UI component. A keyboard user '
        'cannot see where they are.' % (theme, outline, background, ratio, MIN_RATIO)
    )
