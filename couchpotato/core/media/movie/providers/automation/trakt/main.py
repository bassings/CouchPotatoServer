import json
import traceback
import time

from couchpotato import Env, fireEvent
from couchpotato.api import addApiView
from couchpotato.core.event import addEvent
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.providers.base import Provider
from couchpotato.core.media.movie.providers.automation.base import Automation


log = CPLog(__name__)


class TraktBase(Provider):
    """Base class for Trakt API v2 integration with direct OAuth device code flow.

    Users must create their own Trakt application at https://trakt.tv/oauth/applications
    and enter their client_id and client_secret in the settings.
    """

    api_url = 'https://api.trakt.tv/'

    def get_client_id(self):
        """Get the user's Trakt client_id from settings."""
        return self.conf('automation_client_id') or ''

    def get_client_secret(self):
        """Get the user's Trakt client_secret from settings."""
        return self.conf('automation_client_secret') or ''

    def call(self, method_url, post_data=None):
        """Make an authenticated API call to Trakt."""
        client_id = self.get_client_id()
        oauth_token = self.conf('automation_oauth_token')

        if not client_id:
            log.warning('Trakt client_id not configured')
            return []

        headers = {
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': client_id,
        }

        if oauth_token:
            headers['Authorization'] = 'Bearer %s' % oauth_token

        if post_data:
            post_data = json.dumps(post_data)

        data = self.getJsonData(self.api_url + method_url, data=post_data or {}, headers=headers)
        return data if data else []


class Trakt(Automation, TraktBase):
    """Trakt watchlist automation with direct OAuth 2.0 device code authentication.

    This implementation uses the OAuth device code flow which is ideal for server
    applications. Users authenticate by:
    1. Creating a Trakt app at https://trakt.tv/oauth/applications
    2. Entering client_id and client_secret in CouchPotato settings
    3. Clicking "Authorize" to start device code flow
    4. Visiting trakt.tv/activate and entering the code shown
    5. CouchPotato polls for authorization completion
    """

    urls = {
        'watchlist': 'sync/watchlist/movies?extended=full',
        'device_code': 'oauth/device/code',
        'device_token': 'oauth/device/token',
        'token_refresh': 'oauth/token',
    }

    # Device code polling state (stored temporarily during auth flow)
    _device_code = None
    _device_expires = 0
    _poll_interval = 5

    def __init__(self):
        super().__init__()

        # API endpoints for device code OAuth flow
        addApiView('automation.trakt.auth_url', self.getAuthorizationUrl)
        addApiView('automation.trakt.device_code', self.startDeviceAuth)
        addApiView('automation.trakt.poll_token', self.pollForToken)
        addApiView('automation.trakt.credentials', self.getCredentials)

        # Schedule token refresh
        fireEvent('schedule.interval', 'trakt.refresh_token', self.refreshToken, hours=24)
        addEvent('app.load', self.refreshToken)

    def refreshToken(self):
        """Refresh the OAuth token if it's close to expiring."""
        token = self.conf('automation_oauth_token')
        refresh_token = self.conf('automation_oauth_refresh')
        client_id = self.get_client_id()
        client_secret = self.get_client_secret()

        if not all([token, refresh_token, client_id, client_secret]):
            return

        prop_name = 'last_trakt_refresh'
        last_refresh = int(Env.prop(prop_name, default=0))

        # Refresh every 8 weeks (tokens expire in 3 months)
        if last_refresh < time.time() - 4838400:
            log.debug('Refreshing Trakt token')

            try:
                import requests
                response = requests.post(
                    self.api_url + self.urls['token_refresh'],
                    json={
                        'refresh_token': refresh_token,
                        'client_id': client_id,
                        'client_secret': client_secret,
                        'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
                        'grant_type': 'refresh_token',
                    },
                    headers={
                        'Content-Type': 'application/json',
                    },
                    timeout=30
                )

                if response.status_code == 200:
                    data = response.json()
                    log.debug('OAuth refresh successful')
                    self.conf('automation_oauth_token', value=data.get('access_token'))
                    self.conf('automation_oauth_refresh', value=data.get('refresh_token'))
                    Env.prop(prop_name, value=int(time.time()))
                else:
                    log.error('Failed refreshing Trakt token (HTTP %s), please re-authorize in settings', response.status_code)

            except Exception:
                log.error('Failed refreshing Trakt token: %s', traceback.format_exc())

    def getIMDBids(self):
        """Get IMDB IDs from the user's Trakt watchlist."""
        movies = []

        if not self.get_client_id():
            log.warning('Trakt client_id not configured, skipping watchlist sync')
            return movies

        if not self.conf('automation_oauth_token'):
            log.warning('Trakt not authorized, skipping watchlist sync')
            return movies

        for movie in self.getWatchlist():
            m = movie.get('movie')
            if not m:
                continue
            m['original_title'] = m.get('title', '')
            log.debug("Movie: %s", m)
            if self.isMinimalMovie(m):
                imdb_id = m.get('ids', {}).get('imdb')
                if imdb_id:
                    log.info("Trakt automation: %s satisfies requirements, added", m.get('title'))
                    movies.append(imdb_id)

        return movies

    def getWatchlist(self):
        """Fetch the user's Trakt watchlist."""
        return self.call(self.urls['watchlist'])

    def getAuthorizationUrl(self, **kwargs):
        """Legacy endpoint - redirect to device code flow instructions.

        The old proxy-based OAuth redirect is dead. We now use device code flow
        which doesn't require a redirect URL.
        """
        return {
            'success': False,
            'error': 'OAuth proxy is no longer available. Use the device code flow instead.',
            'message': 'Click "Start Authorization" to begin the device code authentication flow.',
        }

    def startDeviceAuth(self, **kwargs):
        """Start the device code authorization flow.

        Returns a user_code and verification_url. The user must visit the URL
        and enter the code to authorize CouchPotato.
        """
        client_id = self.get_client_id()

        if not client_id:
            return {
                'success': False,
                'error': 'Please enter your Trakt Client ID first. Create an app at https://trakt.tv/oauth/applications',
            }

        try:
            import requests
            response = requests.post(
                self.api_url + self.urls['device_code'],
                json={'client_id': client_id},
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                # Store device code for polling
                self._device_code = data.get('device_code')
                self._device_expires = time.time() + data.get('expires_in', 600)
                self._poll_interval = data.get('interval', 5)

                return {
                    'success': True,
                    'user_code': data.get('user_code'),
                    'verification_url': data.get('verification_url'),
                    'expires_in': data.get('expires_in'),
                    'interval': data.get('interval'),
                }
            else:
                log.error('Failed to get device code: HTTP %s - %s', response.status_code, response.text)
                return {
                    'success': False,
                    'error': 'Failed to get device code from Trakt (HTTP %s). Check your Client ID.' % response.status_code,
                }

        except Exception as e:
            log.error('Device code request failed: %s', traceback.format_exc())
            return {
                'success': False,
                'error': 'Request failed: %s' % str(e),
            }

    def pollForToken(self, **kwargs):
        """Poll Trakt to check if the user has authorized the device code.

        Returns success when the user completes authorization, or pending/error status.
        """
        client_id = self.get_client_id()
        client_secret = self.get_client_secret()

        if not client_id or not client_secret:
            return {
                'success': False,
                'error': 'Client ID and Client Secret are required',
            }

        if not self._device_code:
            return {
                'success': False,
                'error': 'No device code. Start authorization first.',
            }

        if time.time() > self._device_expires:
            self._device_code = None
            return {
                'success': False,
                'error': 'Device code expired. Please start authorization again.',
                'expired': True,
            }

        try:
            import requests
            response = requests.post(
                self.api_url + self.urls['device_token'],
                json={
                    'code': self._device_code,
                    'client_id': client_id,
                    'client_secret': client_secret,
                },
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            if response.status_code == 200:
                # Success! User authorized
                data = response.json()
                self.conf('automation_oauth_token', value=data.get('access_token'))
                self.conf('automation_oauth_refresh', value=data.get('refresh_token'))
                Env.prop('last_trakt_refresh', value=int(time.time()))
                self._device_code = None

                log.info('Trakt authorization successful')
                return {
                    'success': True,
                    'message': 'Authorization successful! Trakt is now connected.',
                }

            elif response.status_code == 400:
                # Pending - user hasn't authorized yet
                return {
                    'success': False,
                    'pending': True,
                    'interval': self._poll_interval,
                }

            elif response.status_code == 404:
                self._device_code = None
                return {'success': False, 'error': 'Invalid device code. Please restart authorization.'}

            elif response.status_code == 409:
                return {'success': False, 'error': 'Code already approved. Refresh the page.'}

            elif response.status_code == 410:
                self._device_code = None
                return {'success': False, 'error': 'Code expired. Please restart authorization.', 'expired': True}

            elif response.status_code == 418:
                self._device_code = None
                return {'success': False, 'error': 'Authorization denied by user.'}

            elif response.status_code == 429:
                # Slow down
                self._poll_interval = min(self._poll_interval * 2, 30)
                return {
                    'success': False,
                    'pending': True,
                    'interval': self._poll_interval,
                    'slow_down': True,
                }

            else:
                return {
                    'success': False,
                    'error': 'Unexpected response: HTTP %s' % response.status_code,
                }

        except Exception as e:
            log.error('Token poll failed: %s', traceback.format_exc())
            return {
                'success': False,
                'error': 'Request failed: %s' % str(e),
            }

    def getCredentials(self, **kwargs):
        """Legacy callback endpoint for proxy-based OAuth (no longer used).

        Kept for backwards compatibility in case old tokens need to be handled.
        """
        try:
            oauth_token = kwargs.get('oauth')
            refresh_token = kwargs.get('refresh')

            if oauth_token:
                log.debug('Received OAuth token via legacy callback')
                self.conf('automation_oauth_token', value=oauth_token)
                if refresh_token:
                    self.conf('automation_oauth_refresh', value=refresh_token)
                Env.prop('last_trakt_refresh', value=int(time.time()))

        except Exception:
            log.error('Failed setting trakt token: %s', traceback.format_exc())

        return 'redirect', Env.get('web_base') + 'settings/automation/'
