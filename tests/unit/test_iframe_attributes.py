"""HTML iframe attributes that must not regress across UI templates."""

from pathlib import Path

from bs4 import BeautifulSoup


PRODUCTION_ROOT = Path('couchpotato')


def test_ui_templates_do_not_use_the_obsolete_frameborder_attribute():
    offenders = []

    for template in sorted(PRODUCTION_ROOT.rglob('*.html')):
        soup = BeautifulSoup(template.read_text(), 'html.parser')
        for iframe in soup.find_all('iframe', attrs={'frameborder': True}):
            offenders.append(str(template))

    assert offenders == [], (
        'iframe borders belong in CSS; remove the obsolete frameborder '
        f'attribute from: {offenders}'
    )
