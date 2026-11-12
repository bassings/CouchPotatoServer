"""Source-level guard for the project rule "no secrets, credentials or paths in logs".

The settings, logs and wizard templates swallow several failures. Each swallow
leaves a fixed ``console.debug`` note carrying at most the error's *name*. An
error message can hold a URL, token or filesystem path, so an edit that passes
the whole exception or ``e.message`` instead must fail here.

This only reads source text. The behavioural proof that nothing but the name
reaches the console is the E2E test for the version-info site in
``tests/e2e/settings_complexity.spec.ts``. It deliberately covers only these
``console.debug`` calls, not older ``console.*`` calls elsewhere.
"""
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates'

# (template, fixed context string); one call each, eight in all.
SITES = [
    ('logs.html', 'Log clear failed'),
    ('partials/settings/scripts.html', 'Log clear failed'),
    ('partials/settings/scripts.html', 'Version info unavailable'),
    ('partials/settings/scripts.html', 'Provider test failed'),
    ('partials/settings/scripts.html', 'Restart not confirmed'),
    ('partials/settings/scripts.html', 'Directory listing failed'),
    ('partials/settings/scripts.html', 'Profile list load failed'),
    ('partials/settings/scripts.html', 'Profile reorder failed'),
]


def _debug_calls(template):
    text = (TEMPLATES / template).read_text(encoding='utf-8')
    return [line.strip() for line in text.splitlines() if 'console.debug(' in line]


@pytest.mark.parametrize(('template', 'context'), SITES)
def test_debug_note_logs_only_the_error_name(template, context):
    expected = f"console.debug('{context}', e?.name);"

    assert _debug_calls(template).count(expected) == 1, (
        f'{template}: expected exactly one {expected!r}; a catch block now logs more than the error name'
    )


@pytest.mark.parametrize('template', sorted({template for template, _ in SITES}))
def test_every_debug_call_in_the_template_is_one_of_the_guarded_sites(template):
    guarded = {f"console.debug('{context}', e?.name);" for t, context in SITES if t == template}

    unguarded = [call for call in _debug_calls(template) if call not in guarded]

    assert unguarded == [], f'{template}: console.debug calls outside the guarded set: {unguarded}'


def test_the_eight_sites_are_all_present():
    total = sum(len(_debug_calls(template)) for template in {t for t, _ in SITES})
    assert total == len(SITES) == 8
