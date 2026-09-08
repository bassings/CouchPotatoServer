import json
import math
import traceback
import time

from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.event_names import APP_LOAD
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.providers.base import Provider
from couchpotato.core.media.movie.providers.automation.base import Automation
from couchpotato.environment import Env


log = CPLog(__name__)


# M1: bounds for the device-auth poll interval and code expiry Trakt hands
# back. Both are relayed to the browser's poll loop and stored for the next
# poll, and both were previously trusted unchecked -- an interval of -1 or
# 1e9 (which overflows setTimeout's 32-bit millisecond limit and so fires
# immediately) drove hundreds of poll requests in a few seconds, each one
# taking a per-route lock and a blocking 30s outbound call from the server's
# thread pool. Interval bounds mirror Trakt's own documented range; expiry
# bounds keep a legitimate-looking but absurd value from either expiring the
# flow instantly or leaving stale device-code state around for a day.
MIN_POLL_INTERVAL_SECONDS = 5
MAX_POLL_INTERVAL_SECONDS = 60
DEFAULT_POLL_INTERVAL_SECONDS = 5

MIN_DEVICE_EXPIRY_SECONDS = 60
MAX_DEVICE_EXPIRY_SECONDS = 1800
DEFAULT_DEVICE_EXPIRY_SECONDS = 600

# H2: verification_url is bound as an href in trakt_auth.html (`:href`). The
# vendored Alpine does no scheme filtering on x-bind and there is no CSP, so
# anything other than a genuine https:// URL is clickable script or local
# file access if a response is ever forged or intercepted.
DEFAULT_VERIFICATION_URL = 'https://trakt.tv/activate'


def _clamp_seconds(value, low, high, default):
    """Coerce an untrusted numeric field into `[low, high]`, falling back to
    `default` for anything that is not a genuine, finite number: missing,
    non-numeric, boolean (a Python bool is an int subclass, so `True` would
    otherwise sail through as 1), NaN or infinite.

    A value inside the bound the wire actually offered is clamped to the
    nearer edge rather than forced to `default`, since that is still a
    number Trakt asked for -- only the shape of the value, not its size,
    decides whether it gets a default instead of a clamp.
    """
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError is reachable from the wire, not theoretical: json.loads
        # builds an arbitrary-precision int for a long integer literal, and
        # float() raises on one too large to convert. Without it here the
        # method's outer `except Exception` caught it instead, which failed
        # closed but contradicted this function's promise to return `default`
        # for anything that is not a finite number.
        return default
    if not math.isfinite(number):
        return default
    return int(min(max(number, low), high))


def _safe_verification_url(url):
    """Refuse anything that is not an https:// URL, falling back to the
    documented device-auth activation page."""
    if isinstance(url, str) and url.startswith('https://'):
        return url
    return DEFAULT_VERIFICATION_URL


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
    3. Clicking "Start Trakt Authorisation" to start the device code flow
    4. Visiting trakt.tv/activate and entering the code shown
    5. CouchPotato polls for authorisation completion
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
        addEvent(APP_LOAD, self.refreshToken)

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
                    log.error('Failed refreshing Trakt token (HTTP %s), please re-authorise in settings', response.status_code)

            except Exception:
                log.error('Failed refreshing Trakt token: %s', traceback.format_exc())

    def getIMDBids(self):
        """Get IMDB IDs from the user's Trakt watchlist."""
        movies = []

        if not self.get_client_id():
            log.warning('Trakt client_id not configured, skipping watchlist sync')
            return movies

        if not self.conf('automation_oauth_token'):
            log.warning('Trakt not authorised, skipping watchlist sync')
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
            'message': 'Click "Start Authorisation" to begin the device code authentication flow.',
        }

    def startDeviceAuth(self, **kwargs):
        """Start the device code authorisation flow.

        Returns a user_code and verification_url. The user must visit the URL
        and enter the code to authorise CouchPotato.
        """
        client_id = self.get_client_id()
        client_secret = self.get_client_secret()

        # Both, not just the id. pollForToken needs the secret too, and the
        # browser fires its first poll the instant a code arrives, so
        # checking only the id here handed the user a code and then wiped it
        # off the screen about a tenth of a second later, replaced by
        # 'Client ID and Client Secret are required'. They were told to go
        # and type a code that had already been thrown away. Refuse up front
        # instead, and name the field rather than the pair.
        if not client_id or not client_secret:
            missing = 'Client ID' if not client_id else 'Client Secret'
            return {
                'success': False,
                'error': (
                    'Please enter your Trakt %s first, in the fields above. '
                    'Create an app at https://trakt.tv/oauth/applications to get both.'
                ) % missing,
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
                # H2/M1: none of these are trustworthy as-is -- clamp the
                # numeric fields and validate the URL scheme before either
                # storing them for the next poll or handing them to the
                # browser.
                interval = _clamp_seconds(
                    data.get('interval'),
                    MIN_POLL_INTERVAL_SECONDS, MAX_POLL_INTERVAL_SECONDS,
                    DEFAULT_POLL_INTERVAL_SECONDS,
                )
                expires_in = _clamp_seconds(
                    data.get('expires_in'),
                    MIN_DEVICE_EXPIRY_SECONDS, MAX_DEVICE_EXPIRY_SECONDS,
                    DEFAULT_DEVICE_EXPIRY_SECONDS,
                )
                verification_url = _safe_verification_url(data.get('verification_url'))

                # Store device code for polling
                self._device_code = data.get('device_code')
                self._device_expires = time.time() + expires_in
                self._poll_interval = interval

                return {
                    'success': True,
                    'user_code': data.get('user_code'),
                    'verification_url': verification_url,
                    'expires_in': expires_in,
                    'interval': interval,
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
        """Poll Trakt to check if the user has authorised the device code.

        Returns success when the user completes authorisation, or pending/error status.
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
                'error': 'No device code. Start authorisation first.',
            }

        if time.time() > self._device_expires:
            self._device_code = None
            return {
                'success': False,
                'error': 'Device code expired. Please start authorisation again.',
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
                # Success! User authorised
                data = response.json()
                self.conf('automation_oauth_token', value=data.get('access_token'))
                self.conf('automation_oauth_refresh', value=data.get('refresh_token'))
                Env.prop('last_trakt_refresh', value=int(time.time()))
                self._device_code = None

                log.info('Trakt authorisation successful')
                return {
                    'success': True,
                    'message': 'Authorisation successful! Trakt is now connected.',
                }

            elif response.status_code == 400:
                # Pending - user has not authorised yet
                return {
                    'success': False,
                    'pending': True,
                    'interval': self._poll_interval,
                }

            elif response.status_code == 404:
                self._device_code = None
                return {'success': False, 'error': 'Invalid device code. Please restart authorisation.'}

            elif response.status_code == 409:
                return {'success': False, 'error': 'Code already approved. Refresh the page.'}

            elif response.status_code == 410:
                self._device_code = None
                return {'success': False, 'error': 'Code expired. Please restart authorisation.', 'expired': True}

            elif response.status_code == 418:
                self._device_code = None
                return {'success': False, 'error': 'Authorisation denied by user.'}

            elif response.status_code == 429:
                # Slow down. Same clamp as startDeviceAuth: doubling an
                # already-stored interval must not walk it past the same
                # ceiling a hostile initial value was bounded to.
                self._poll_interval = _clamp_seconds(
                    self._poll_interval * 2,
                    MIN_POLL_INTERVAL_SECONDS, MAX_POLL_INTERVAL_SECONDS,
                    DEFAULT_POLL_INTERVAL_SECONDS,
                )
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
