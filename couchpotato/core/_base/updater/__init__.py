from .main import Updater


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
                    'name': 'include_beta',
                    'default': False,
                    'type': 'bool',
                    'label': 'Include Beta Releases',
                    'description': 'Also check for beta/pre-release versions. Not recommended for production use.',
                    'advanced': True,
                },
            ],
        },
    ],
}]
