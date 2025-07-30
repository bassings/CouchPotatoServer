from __future__ import absolute_import, division, print_function, unicode_literals
config = [{
    'name': 'automation_providers',
    'groups': [
        {
            'label': 'Watchlists',
            'description': 'Check watchlists for new movies',
            'type': 'list',
            'name': 'watchlist_providers',
            'tab': 'automation',
            'options': [],
        },
        {
            'label': 'Automated',
            'description': 'Uses minimal requirements',
            'type': 'list',
            'name': 'automation_providers',
            'tab': 'automation',
            'options': [],
        },
    ],
}]
