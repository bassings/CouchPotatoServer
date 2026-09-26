"""Keep the documented, reusable theme layer aligned with the application.

Component-scoped rules deliberately remain in ``base.html`` and are not part
of this contract.  In particular, the ``data-testid`` danger overrides are
application implementation details rather than reusable design-system rules.
"""

import re
from pathlib import Path

import pytest

from couchpotato.ui import _jinja


SHARED_START = '/* DESIGN-SYSTEM-SHARED:START */'
SHARED_END = '/* DESIGN-SYSTEM-SHARED:END */'


def _normalise(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip()


def _strip_comments(css: str) -> str:
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def _rendered_app_css() -> str:
    context = {'api_key': 'test-key', 'api_base': '/api/test-key', 'web_base': '/', 'new_base': '/'}
    html = _jinja.get_template('base.html').render(**context)
    blocks = re.findall(r'<style\b[^>]*>(.*?)</style>', html, re.S)
    assert blocks, 'base.html rendered no <style> element'
    return '\n'.join(blocks)


def _shared_application_css(css: str) -> str:
    starts = [match.end() for match in re.finditer(re.escape(SHARED_START), css)]
    ends = [match.start() for match in re.finditer(re.escape(SHARED_END), css)]
    assert len(starts) == len(ends) == 2, 'base.html must contain exactly two shared CSS regions'
    assert all(start < end for start, end in zip(starts, ends, strict=True))
    return '\n'.join(css[start:end] for start, end in zip(starts, ends, strict=True))


def _leaf_rule_map(css: str) -> dict[tuple[str, ...], list[str]]:
    rules = {}
    stack = []
    depth = 0
    last_end = 0
    css = _strip_comments(css)
    for index, character in enumerate(css):
        if character == '{':
            selector = _normalise(css[last_end:index])
            stack.append((depth, selector, index + 1))
            depth += 1
            last_end = index + 1
        elif character == '}':
            depth -= 1
            _rule_depth, selector, body_start = stack.pop()
            body = _normalise(css[body_start:index])
            if '{' not in body:
                path = tuple(item[1] for item in stack) + (selector,)
                rules.setdefault(path, []).append(body)
            last_end = index + 1
    assert not stack, 'unclosed CSS rule in shared theme contract'
    return rules


def _leaf_rule_order(css: str) -> list[tuple[str, ...]]:
    ordered_paths = []
    css = _strip_comments(css)
    stack = []
    last_end = 0
    for index, character in enumerate(css):
        if character == '{':
            stack.append((_normalise(css[last_end:index]), index + 1))
            last_end = index + 1
        elif character == '}':
            selector, body_start = stack.pop()
            body = _normalise(css[body_start:index])
            if '{' not in body:
                ordered_paths.append(tuple(item[0] for item in stack) + (selector,))
            last_end = index + 1

    assert not stack, 'unclosed CSS rule in shared theme contract'
    return ordered_paths


def _assert_same_rules(documented: dict[tuple[str, ...], list[str]], application: dict[tuple[str, ...], list[str]]) -> None:
    missing = sorted(application.keys() - documented.keys())
    extra = sorted(documented.keys() - application.keys())
    changed = sorted(
        selector for selector in application.keys() & documented.keys()
        if application[selector] != documented[selector]
    )
    display = lambda paths: ', '.join(' > '.join(path) for path in paths)
    assert not missing, 'documented theme is missing shared selector(s): %s' % display(missing)
    assert not extra, 'documented theme has stale shared selector(s): %s' % display(extra)
    assert not changed, 'shared declaration(s) differ for selector(s): %s' % display(changed)


def _assert_same_theme(documented_css: str, application_css: str) -> None:
    _assert_same_rules(_leaf_rule_map(documented_css), _leaf_rule_map(application_css))
    documented_order = _leaf_rule_order(documented_css)
    application_order = _leaf_rule_order(application_css)
    assert documented_order == application_order, 'cascade order differs for shared selector(s)'


def test_documented_theme_mirrors_every_shared_application_rule():
    app_css = _shared_application_css(_rendered_app_css())
    documented_css = _strip_comments(Path('docs/design-system/theme.css').read_text())
    _assert_same_theme(documented_css, app_css)


def test_mirror_comparison_preserves_cascade_order_across_contexts():
    application = '.fade-in { animation: fadeIn 1s; } @media (reduce) { .fade-in { animation: none; } }'
    reordered = '@media (reduce) { .fade-in { animation: none; } } .fade-in { animation: fadeIn 1s; }'
    with pytest.raises(AssertionError, match='cascade order differs'):
        _assert_same_theme(reordered, application)


def test_mirror_comparison_preserves_order_for_overlapping_selectors():
    application = ':root.light .text-white { color: #1a1a1a; } :root.light .text-cp-accent { color: #0e7490; }'
    reordered = ':root.light .text-cp-accent { color: #0e7490; } :root.light .text-white { color: #1a1a1a; }'
    with pytest.raises(AssertionError, match='cascade order differs'):
        _assert_same_theme(reordered, application)


def test_component_scoped_application_rules_are_explicitly_outside_the_mirror():
    app_css = _rendered_app_css()
    shared_css = _shared_application_css(app_css)
    assert '[data-testid=' in app_css, 'the documented component-scoped exclusion no longer matches'
    assert '[data-testid=' not in shared_css
