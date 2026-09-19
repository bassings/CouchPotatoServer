"""Native ordered-list semantics for ordered settings collections."""

from pathlib import Path

from bs4 import BeautifulSoup


TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[2]
    / 'couchpotato'
    / 'ui'
    / 'templates'
    / 'partials'
    / 'settings'
)

ORDERED_COLLECTIONS = (
    (
        'categories.html',
        'Categories',
        '(category, ci) in categories',
        'category._id',
        ['space-y-2'],
        ['bg-cp-card', 'border', 'border-white/[0.05]', 'rounded-lg', 'px-4', 'py-3'],
    ),
    (
        'profiles.html',
        'Quality profiles',
        '(profile, pi) in profiles',
        'profile._id',
        ['space-y-2'],
        ['bg-cp-card', 'border', 'border-white/[0.05]', 'rounded-lg', 'px-4', 'py-3'],
    ),
    (
        'profiles.html',
        'Qualities in this profile',
        '(type, ti) in formState.types',
        'ti',
        ['space-y-1.5', 'mb-3'],
        [
            'flex',
            'items-center',
            'gap-2',
            'bg-white/[0.02]',
            'border',
            'border-white/[0.04]',
            'rounded-md',
            'px-2.5',
            'py-2',
        ],
    ),
)


def _template(name):
    path = TEMPLATE_ROOT / name
    assert path.is_file(), f'settings template was not found: {path}'
    return BeautifulSoup(path.read_text(), 'html.parser')


def test_ordered_settings_collections_use_native_lists_and_items():
    soups = {}
    expected_role_lists = {}

    for filename, label, expression, key, list_classes, item_classes in ORDERED_COLLECTIONS:
        soup = soups.setdefault(filename, _template(filename))
        expected_role_lists.setdefault(filename, []).append(('ol', label))
        ordered_list = soup.find('ol', attrs={'aria-label': label})
        assert ordered_list is not None, f'{label}: expected a native <ol>'
        assert ordered_list.get('role') == 'list', (
            f'{label}: markerless <ol> needs role=list for Safari/VoiceOver'
        )
        assert ordered_list.get('class') == list_classes

        loop = ordered_list.find('template', attrs={'x-for': expression}, recursive=False)
        assert loop is not None, f'{label}: expected the existing Alpine loop'
        assert loop.get(':key') == key

        item = loop.find('li', recursive=False)
        assert item is not None, f'{label}: expected a native <li> in the loop'
        assert item.get('role') is None, f'{label}: native <li> must not repeat role=listitem'
        assert item.get('class') == item_classes

    for filename, soup in soups.items():
        actual_role_lists = [
            (element.name, element.get('aria-label'))
            for element in soup.find_all(attrs={'role': 'list'})
        ]
        assert actual_role_lists == expected_role_lists[filename], (
            f'{filename}: role=list is reserved for the three markerless native lists'
        )
        assert soup.find(attrs={'role': 'listitem'}) is None, (
            f'{filename}: explicit role=listitem remains'
        )
