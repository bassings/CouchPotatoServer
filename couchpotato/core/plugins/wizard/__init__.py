from __future__ import absolute_import, division, print_function, unicode_literals
from .main import Wizard


def autoload():
    return Wizard()

config = [{
    'name': 'core',
    'groups': [
        {
            'tab': 'general',
            'name': 'advanced',
            'options': [
                {
                    'name': 'show_wizard',
                    'label': 'Run the wizard',
                    'default': 1,
                    'type': 'bool',
                },
            ],
        },
    ],
}]
