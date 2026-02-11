import os

from .main import Updater
from couchpotato.environment import Env


def autoload():
    return Updater()

config = [{
    'name': 'updater',
    'groups': [
        {
            'tab': 'general',
            'name': 'updater',
            'label': 'Updates',
            'git_only': True,
            'description': 'Keep CouchPotato up to date automatically.',
            'options': [
                {
                    'name': 'enabled',
                    'default': True,
                    'type': 'enabler',
                },
                {
                    'name': 'automatic',
                    'default': True,
                    'type': 'bool',
                    'label': 'Auto-Update',
                    'description': 'Automatically install updates when available.',
                },
                {
                    'name': 'notification',
                    'type': 'bool',
                    'default': True,
                    'label': 'Notify on Update',
                    'description': 'Send a notification when a new update is available.',
                },
                {
                    'name': 'check_interval',
                    'default': 24,
                    'type': 'int',
                    'label': 'Check Every (hours)',
                    'description': 'How often to check for updates.',
                },
                {
                    'name': 'git_command',
                    'default': 'git',
                    'hidden': not os.path.isdir(os.path.join(Env.get('app_dir'), '.git')),
                    'advanced': True
                },
            ],
        },
    ],
}]
