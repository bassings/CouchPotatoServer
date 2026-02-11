from .main import Charts


def autoload():
    return Charts()


config = [{
    'name': 'charts',
    'groups': [
        {
            'label': 'Charts Overview',
            'description': 'Chart sources shown on the Suggestions page. Configure individual sources below.',
            'type': 'list',
            'name': 'charts_providers',
            'tab': 'display',
            'options': [],
        },
    ],
}]
