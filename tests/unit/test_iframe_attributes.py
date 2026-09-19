"""HTML iframe attributes that must not regress across UI templates."""

from pathlib import Path

from bs4 import BeautifulSoup


PRODUCTION_ROOT = Path(__file__).resolve().parents[2] / 'couchpotato'


def test_ui_templates_do_not_use_the_obsolete_frameborder_attribute():
    assert PRODUCTION_ROOT.is_dir(), (
        f'production template root was not found: {PRODUCTION_ROOT}'
    )
    templates = sorted(PRODUCTION_ROOT.rglob('*.html'))
    assert templates, f'no production HTML templates found under {PRODUCTION_ROOT}'
    offenders = []

    for template in templates:
        soup = BeautifulSoup(template.read_text(), 'html.parser')
        for iframe in soup.find_all('iframe', attrs={'frameborder': True}):
            offenders.append(str(template))

    assert offenders == [], (
        'iframe borders belong in CSS; remove the obsolete frameborder '
        f'attribute from: {offenders}'
    )
