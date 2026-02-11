from .main import Trakt


def autoload():
    return Trakt()


config = [{
    'name': 'trakt',
    'groups': [
        {
            'tab': 'automation',
            'list': 'watchlist_providers',
            'name': 'trakt_automation',
            'label': 'Trakt Watchlist',
            'description': 'Auto-add movies from your Trakt watchlist. Requires a Trakt application.',
            'options': [
                {
                    'name': 'automation_enabled',
                    'default': False,
                    'type': 'enabler',
                },
                {
                    'name': 'automation_client_id',
                    'label': 'Client ID',
                    'description': 'Create a Trakt app at trakt.tv/oauth/applications and copy the Client ID here.',
                },
                {
                    'name': 'automation_client_secret',
                    'label': 'Client Secret',
                    'description': 'The Client Secret from your Trakt application.',
                    'type': 'password',
                },
                {
                    'name': 'automation_oauth_token',
                    'label': 'Auth Token',
                    'advanced': True,
                    'description': 'OAuth access token (set automatically after authorization).',
                },
                {
                    'name': 'automation_oauth_refresh',
                    'label': 'Refresh Token',
                    'advanced': True,
                    'description': 'OAuth refresh token for automatic token renewal.',
                },
            ],
        },
    ],
}]
