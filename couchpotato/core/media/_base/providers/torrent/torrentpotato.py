from urllib.parse import urlparse, urlsplit
import re
import xml.etree.ElementTree as ET

from requests import HTTPError
from urllib3.util import parse_url

from couchpotato.api import addApiView
from couchpotato.core.event import addEvent
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.variable import splitString, tryInt, tryFloat, cleanHost
from couchpotato.core.logger import CPLog
from couchpotato.core.settings import _PASSWORD_SAVE_LOCK, GroupMisaligned, unstorable_cell
from couchpotato.environment import Env
from couchpotato.core.media._base.providers.base import ResultList
from couchpotato.core.media._base.providers.torrent.base import TorrentProvider


log = CPLog(__name__)

# The one stored value that ties a saved Jackett API key to an address: the
# normalised address the key was saved for. Hidden (`ui-meta`), so it is never
# rendered, written or read through the settings routes (SEC-005).
KEY_BINDING_OPTION = 'jackett_key_binding'
_DEFAULT_PORTS = {'http': 80, 'https': 443}
# Whitespace, a control character, a backslash, a "?" or a "#" anywhere in an
# address. The two parsers read each of the first three differently, a backslash
# is the one character that moves a host across the `@` of
# `http://evil\@jackett:9117`, and the address is the base of
# `/torznab/all/api?apikey=...`, so a query or a fragment, even an empty one,
# has no place in it. Spelled as the control range plus the space and the
# Unicode spaces `\s` adds (U+0085, U+00A0, U+1680, U+2000-200A, U+2028,
# U+2029, U+202F, U+205F, U+3000), so that no range overlaps another.
_UNSAFE_ADDRESS = re.compile(
    r'[\x00-\x20\x7f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\\?#]')

# What a Jackett route answers, as the API `error`, when the saved key may not be
# used with the saved address (AC-DESIGN-5). It carries no address and no key.
KEY_REFUSAL_TEXT = ('The saved Jackett API key cannot be used with this Jackett address. '
                    'Check the address is your Jackett server, then enter the API key again '
                    'and press Sync again.')

ROUTE_SYNC = 'torrentpotato.jackett_sync'
ROUTE_TEST = 'torrentpotato.jackett_test'

MISALIGNED_TEXT = ('The saved TorrentPotato rows do not line up, so a sync could pair a key '
                   'with the wrong host. Fix the rows in Settings first. Nothing was changed.')


def _decoded(value):
    """Bytes as UTF-8 text (settings may hand back bytes); anything else as it is."""
    return value.decode('utf-8') if isinstance(value, bytes) else value


def _without_bytes_wrapper(text):
    """Text that looks like a bytes repr, "b'...'", without the wrapper."""
    if text.startswith("b'") and text.endswith("'"):
        return text[2:-1]
    return text


def _address_text(value):
    """The saved address as plain text, or '' when it is not text."""
    value = _decoded(value)
    if not isinstance(value, str):
        return ''
    return _without_bytes_wrapper(value.strip()).strip()


def _agreed_parts(candidate):
    """(scheme, userinfo, host, port, path) when both URL parsers read `candidate` alike, else None.

    `urllib.parse` is what the rest of this module reads an address with;
    `urllib3.util.parse_url` is what the transport uses to decide where a
    request goes. An address on which they differ about the host, the port, the
    userinfo or the path is one whose destination cannot be told from the text,
    so it has no normal form. A query or a fragment is refused outright: the
    address is the base of `/torznab/all/api?apikey=...`, so neither belongs in
    it, and `http://jackett#@evil` is a fragment on one reading and a host on
    another.
    """
    std = urlsplit(candidate)
    ref = parse_url(candidate)
    if std.query or std.fragment or ref.query or ref.fragment:
        return None
    userinfo = std.netloc.rpartition('@')[0] if '@' in std.netloc else None
    host = (std.hostname or '')
    if not host or std.scheme not in _DEFAULT_PORTS:
        return None
    if ref.scheme != std.scheme or (ref.host or '').strip('[]') != host or ref.port != std.port:
        return None
    if ref.auth != userinfo or (ref.path or '').rstrip('/') != std.path.rstrip('/'):
        return None
    return std.scheme, userinfo, host, std.port, std.path.rstrip('/')


def normalise_jackett_address(value):
    """The one normal form of a saved Jackett address, or None when it has none.

    This string is what a Jackett API key is bound to, and it is final: the
    guard that refuses a key sent anywhere else reads what is stored from it.
    The address is read the way a request is sent (`cleanHost` on the stripped,
    unwrapped text, so `jackett.local:9117` is `http://jackett.local:9117`). The scheme and host
    are lower case, the default port and any trailing slash are dropped, and
    userinfo and path keep their case, because the server compares both
    exactly. It never raises: an address either parser rejects returns None,
    which a key save stores as an empty binding.
    """
    try:
        text = _address_text(value)
        candidate = cleanHost(text).rstrip('/') if text else ''
        parts = None if not candidate or _UNSAFE_ADDRESS.search(candidate) else _agreed_parts(candidate)
    except Exception:  # either parser raises on a bad port, a bad bracket or a bad escape
        return None
    if parts is None:
        return None
    scheme, userinfo, host, port, path = parts
    if ':' in host:
        host = '[%s]' % host
    authority = host if port in (None, _DEFAULT_PORTS[scheme]) else '%s:%d' % (host, port)
    return '%s://%s%s%s' % (scheme, '%s@' % userinfo if userinfo else '', authority, path)


class Base(TorrentProvider):

    urls = {}
    limits_reached = {}

    http_time_between_calls = 1  # Seconds

    def __init__(self):
        super().__init__()

        # The value hook of the existing per-option save event, so that the key
        # and the address it belongs to land in one config.ini write (SEC-005).
        addEvent('setting.save.torrentpotato.jackett_api_key', self.bind_saved_key)

        # Register API endpoint for Jackett sync
        addApiView(ROUTE_SYNC, self.jackettSync, docs={
            'desc': 'Sync TorrentPotato indexers from Jackett. Send no parameters to use the saved '
                    'Jackett URL and API key. A jackett_url must be sent with its own jackett_api_key '
                    '(the saved key is never sent to a URL in the request).',
            'params': {
                'jackett_url': {'desc': 'Jackett base URL (optional). Must come with jackett_api_key; '
                                        'if neither is sent the saved pair is used'},
                'jackett_api_key': {'desc': 'Jackett API key (optional). Empty or blank counts as not sent'},
                'replace': {'desc': 'Replaces every stored indexer with the Jackett ones only for '
                                    'boolean true or the text true, 1, yes or on (any case). Anything '
                                    'else merges, including the number 1 in a JSON body, a list and '
                                    'an object. A merge is refused when the stored rows do not line up'},
            },
            'return': {'type': 'object', 'example': '{"success": true, "indexers": [...]}'}
        })

        addApiView(ROUTE_TEST, self.jackettTest, docs={
            'desc': 'Test Jackett connection and list available indexers. Send no parameters to use '
                    'the saved Jackett URL and API key; a jackett_url must come with its own key.',
            'params': {
                'jackett_url': {'desc': 'Jackett base URL (optional). Must come with jackett_api_key'},
                'jackett_api_key': {'desc': 'Jackett API key (optional)'},
            },
            'return': {'type': 'object', 'example': '{"success": true, "indexers": [...]}'}
        })

    def search(self, media, quality, manual = False):
        hosts = self.getHosts()

        # Don't trust imdb_results=True - many indexers ignore IMDB ID and just search by title
        # This causes wrong movies to be matched (e.g., "Sister Act" results for "Sister Act 3")
        results = ResultList(self, media, quality, imdb_results = False)

        for host in hosts:
            if self.isDisabled(host):
                continue

            self._searchOnHost(host, media, quality, results, manual = manual)

        return results

    def _searchOnHost(self, host, media, quality, results, manual = False):
        url = self.buildUrl(media, host)

        # Manual/user-triggered searches bypass the 30-minute cache so a
        # refresh isn't served a stale result from a recent automatic sweep.
        # cache_timeout <= 0 forces a live fetch that isn't stored back into
        # the cache (see Plugin.getCache), so the next automatic search still
        # fetches and caches its own copy.
        cache_timeout = -1 if manual else 1800

        try:
            torrents = self.getJsonData(
                url, cache_timeout=cache_timeout,
                ignore_host_failure_on_400=self._isJackettIndexerHost(host['host']),
            )
        except HTTPError as e:
            # Handle 400 Bad Request gracefully - common for TV/Anime-only indexers
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 400:
                log.warning('Indexer returned 400 Bad Request, possibly because it does not support movie searches')
                return
            raise
        except Exception as error:
            log.error('Failed getting results from indexer: %s', type(error).__name__)
            return

        if torrents:
            try:
                if torrents.get('error'):
                    log.error('Indexer returned an error response')
                elif torrents.get('results'):
                    for torrent in torrents.get('results', []):
                        results.append({
                            'id': torrent.get('torrent_id'),
                            'protocol': 'torrent' if re.match('^(http|https|ftp)://.*$', torrent.get('download_url')) else 'torrent_magnet',
                            'provider_extra': urlparse(host['host']).hostname or host['host'],
                            'name': toUnicode(torrent.get('release_name')),
                            'url': torrent.get('download_url'),
                            'detail_url': torrent.get('details_url'),
                            'size': torrent.get('size'),
                            'score': host['extra_score'],
                            'seeders': torrent.get('seeders'),
                            'leechers': torrent.get('leechers'),
                            'seed_ratio': host['seed_ratio'],
                            'seed_time': host['seed_time'],
                        })

            except Exception as error:
                log.error('Failed getting results from indexer: %s', type(error).__name__)

    def _isJackettIndexerHost(self, host_url):
        """Identify indexer URLs on the configured Jackett service."""
        saved_url = self.conf('jackett_url')
        if not saved_url:
            return False

        base = urlparse(cleanHost(toUnicode(saved_url)))
        candidate = urlparse(host_url)
        indexer_path = base.path.rstrip('/') + '/potato/'
        return (
            candidate.scheme.lower() == base.scheme.lower()
            and candidate.netloc.lower() == base.netloc.lower()
            and candidate.path.startswith(indexer_path)
            and candidate.path.endswith('/api')
        )

    def getHosts(self):

        uses = splitString(str(self.conf('use')), clean = False)
        hosts = splitString(self.conf('host'), clean = False)
        names = splitString(self.conf('name'), clean = False)
        seed_times = splitString(self.conf('seed_time'), clean = False)
        seed_ratios = splitString(self.conf('seed_ratio'), clean = False)
        pass_keys = splitString(self.conf('pass_key'), clean = False)
        extra_score = splitString(self.conf('extra_score'), clean = False)

        host_list = []
        for nr in range(len(hosts)):

            try: key = pass_keys[nr]
            except Exception: key = ''

            try: host = hosts[nr]
            except Exception: host = ''

            try: name = names[nr]
            except Exception: name = ''

            try: ratio = seed_ratios[nr]
            except Exception: ratio = ''

            try: seed_time = seed_times[nr]
            except Exception: seed_time = ''

            host_list.append({
                'use': uses[nr],
                'host': host,
                'name': name,
                'seed_ratio': tryFloat(ratio),
                'seed_time': tryInt(seed_time),
                'pass_key': key,
                'extra_score': tryInt(extra_score[nr]) if len(extra_score) > nr else 0
            })

        return host_list

    def belongsTo(self, url, provider = None, host = None):

        hosts = self.getHosts()

        for configured_host in hosts:
            result = super().belongsTo(url, host = configured_host['host'], provider = provider)
            if result:
                return result

    def isDisabled(self, host = None):
        return not self.isEnabled(host)

    def isEnabled(self, host = None):

    # Return true if at least one is enabled and no host is given
        if host is None:
            for host in self.getHosts():
                if self.isEnabled(host):
                    return True
            return False

        return TorrentProvider.isEnabled(self) and host['host'] and host['pass_key'] and int(host['use'])

    def getJackettIndexers(self, jackett_url, jackett_api_key, movies_only=True):
        """Fetch list of configured indexers from Jackett

        Args:
            jackett_url: Jackett base URL
            jackett_api_key: Jackett API key
            movies_only: If True, only return indexers that support movie searches
        """
        try:
            # `jackett_url` arrives in the form that was checked (`_jackettCredentials`),
            # and is interpolated unchanged: the string checked is the string sent.
            # Use the torznab endpoint with t=indexers to get all indexers
            indexers_url = f'{jackett_url}/torznab/all/api?apikey={jackett_api_key}&t=indexers'

            log.info('Fetching Jackett indexers')

            response = self.urlopen(indexers_url, timeout=30)
            if not response:
                return None, 'No response from Jackett'

            # Parse XML response
            root = ET.fromstring(response)

            # Check for Jackett error response. `find('.//error')` searches the
            # descendants only, and Jackett answers an invalid API key with a
            # document whose ROOT is the `<error>`, so the root is tested too.
            # Nothing from the reply's `code` or `description` is returned or
            # logged: the text below is fixed.
            if root.tag == 'error' or root.find('.//error') is not None:
                log.error('Jackett returned an error response')
                return None, 'Jackett returned an error response'

            indexers = []
            skipped_tv_only = []
            for indexer in root.findall('.//indexer'):
                indexer_id = indexer.get('id')
                configured = indexer.get('configured', 'false').lower() == 'true'

                if not configured:
                    continue

                title_elem = indexer.find('title')
                title = title_elem.text if title_elem is not None else indexer_id

                # Check if indexer supports movie searches
                movie_search = indexer.find('.//movie-search')
                supports_movies = True
                if movie_search is not None:
                    supports_movies = movie_search.get('available', 'yes').lower() == 'yes'

                if movies_only and not supports_movies:
                    skipped_tv_only.append(title)
                    continue

                # Build the TorrentPotato URL for this indexer
                potato_url = f'{jackett_url}/potato/{indexer_id}/api'

                indexers.append({
                    'id': indexer_id,
                    'title': title,
                    'potato_url': potato_url,
                    'configured': configured,
                    'supports_movies': supports_movies
                })

            if skipped_tv_only:
                log.info('Skipped %d TV/Anime-only indexers (no movie support): %s',
                         len(skipped_tv_only), ', '.join(skipped_tv_only))

            log.info('Found %d configured Jackett indexers with movie support', len(indexers))
            return indexers, None

        except ET.ParseError:
            log.error('Failed to parse Jackett response XML')
            return None, 'Failed to parse Jackett response XML'
        except Exception as e:
            log.error('Failed to fetch Jackett indexers: %s', type(e).__name__)
            return None, f'Failed to connect to Jackett: {type(e).__name__}'

    def bind_saved_key(self, value):
        """Value hook for a save of `jackett_api_key`: bind the key to the saved address.

        Runs inside `settings.save`, before the key is stored and before the file
        is written, and sets the binding in memory only, so the key and the
        binding are one write. A non-empty key is bound to the normalised saved
        address, or to nothing when that address has no normal form; an empty
        key clears the binding, so the file never holds a binding with no key.
        An address save never reaches here, so it never moves the binding.

        It returns None, which leaves the submitted key as it was. It must not
        raise for any value the route accepts: `fireEvent` would log the
        exception and discard it, and the key would then be stored with the
        previous key's binding. Nothing here is logged, because every value in
        reach (the key, the address, the binding) is a secret or a private path.
        """
        binding = ''
        try:
            if self._is_non_empty_key(value):
                binding = normalise_jackett_address(self._savedJackettSetting('jackett_url')) or ''
        except Exception:
            binding = ''
        Env.get('settings').set_internal('torrentpotato', KEY_BINDING_OPTION, binding)

    @staticmethod
    def _is_non_empty_key(value):
        """Does a submitted key count as a key? Text must survive stripping; a falsy non-text value is read as none."""
        if isinstance(value, str):
            return bool(value.strip())
        return bool(value)

    def _savedJackettSetting(self, name):
        value = self.conf(name)

        # Ensure values are strings (settings may return bytes), and unwrap a
        # str that looks like a bytes repr: "b'...'"
        value = _decoded(value)
        if isinstance(value, str):
            value = _without_bytes_wrapper(value)
        return value

    @staticmethod
    def _sendable_address(address):
        """The address of a request that brings its own key, as `getJackettIndexers` is handed it."""
        if not isinstance(address, str) or not address:
            return None
        return cleanHost(address).rstrip('/')

    def _jackettCredentials(self, route, jackett_url, jackett_api_key):
        """Pick the Jackett URL and API key a request may use, and the only reader of the saved key.

        A request that supplies its own `jackett_url` must supply its own
        `jackett_api_key` (AC-SEC-9 rule (a)), and neither it nor a request that
        supplies only its own key is checked against anything: the saved key is
        not used by either. The saved key is only sent to the address it was
        bound to. It is used only when the stored binding (written by a key save,
        `bind_saved_key`) is non-empty and equals the normalised saved address;
        otherwise nothing is returned for the route to send and the refusal is
        the one text of `KEY_REFUSAL_TEXT`, whatever the cause. An empty or
        absent binding, and an address with no normal form, are one state,
        unbound, and fail closed. A saved key that is empty after stripping is no
        key at all, so the route answers that the URL and key are required.

        Returns `(url, key, row_base, refusal)`. `url` is the string to send to,
        which for a checked key is the normalised address that was compared.
        `row_base` is what the rows of a sync are built from: the saved address as
        the user saved it, cleaned (`_row_base`: `cleanHost` of the text the
        normaliser was given, or the normalised address where that is not
        ASCII), from the same single read, because
        the merge and `_isJackettIndexerHost` compare host strings exactly and
        must see what a sync wrote before the guard. `refusal` is a response dict
        with no submitted or stored value in it, or None. The saved address is
        read once, so the check and the send cannot disagree, and the three
        reads of a checked key happen in one hold of the settings lock, so a key
        save cannot land between them.
        """
        supplied = (jackett_url, jackett_api_key)
        if any(value and not isinstance(value, str) for value in supplied):
            return None, None, None, {'success': False, 'error': 'Jackett URL and API key must be text'}
        if isinstance(jackett_api_key, str) and not jackett_api_key.strip():
            jackett_api_key = None  # a key that is empty after stripping is absent
        if jackett_url and not jackett_api_key:
            return None, None, None, {
                'success': False,
                'error': 'A Jackett URL must be sent with its own API key. '
                         'The saved API key is only used with the saved URL.'
            }

        if jackett_url:
            sendable = self._sendable_address(jackett_url)
            return sendable, jackett_api_key, sendable, None
        with _PASSWORD_SAVE_LOCK:  # the lock a key save holds; never held across the request
            saved_url = self._savedJackettSetting('jackett_url')
            saved_key = None if jackett_api_key else self._savedJackettSetting('jackett_api_key')
            binding = None if jackett_api_key else self._savedJackettSetting(KEY_BINDING_OPTION)
        sendable = self._sendable_address(saved_url)
        if jackett_api_key:
            return sendable, jackett_api_key, sendable, None
        if not self._is_non_empty_key(saved_key):
            return None, None, None, None
        address = normalise_jackett_address(saved_url)
        reason = self._refusal_reason(address, binding) if isinstance(saved_key, str) else 'unbound'
        if reason:
            log.warning('Refused %s: the saved Jackett API key is not bound to the saved address (reason=%s)',
                        route, reason)
            return None, None, None, {'success': False, 'error': KEY_REFUSAL_TEXT}
        return address, saved_key, self._row_base(saved_url, address), None

    @staticmethod
    def _refusal_reason(address, binding):
        """Why a saved key may not go to `address` ('unbound' or 'mismatch'), or None when it may."""
        if not isinstance(binding, str) or not binding.strip() or not address:
            return 'unbound'
        return None if address == binding else 'mismatch'

    def jackettTest(self, jackett_url=None, jackett_api_key=None, **kwargs):
        """Test Jackett connection and return list of available indexers"""
        jackett_url, jackett_api_key, _, refusal = self._jackettCredentials(
            ROUTE_TEST, jackett_url, jackett_api_key)
        if refusal:
            return refusal

        if not jackett_url or not jackett_api_key:
            return {
                'success': False,
                'error': 'Jackett URL and API key are required'
            }

        indexers, error = self.getJackettIndexers(jackett_url, jackett_api_key)

        if error:
            return {
                'success': False,
                'error': error
            }

        return {
            'success': True,
            'indexers': indexers,
            'count': len(indexers)
        }

    def jackettSync(self, jackett_url=None, jackett_api_key=None, replace=False, **kwargs):
        """Sync TorrentPotato indexers from Jackett

        Args:
            jackett_url: Jackett base URL. Must come with its own jackett_api_key; when
                neither is given the saved pair is used
            jackett_api_key: Jackett API key (empty after stripping counts as not given)
            replace: True (or the text true, 1, yes, on) replaces all existing indexers;
                anything else merges/adds new ones.
        """
        jackett_url, jackett_api_key, row_base, refusal = self._jackettCredentials(
            ROUTE_SYNC, jackett_url, jackett_api_key)
        if refusal:
            return refusal

        if not jackett_url or not jackett_api_key:
            return {
                'success': False,
                'error': 'Jackett URL and API key are required. Please configure them in settings.'
            }

        replace = self._isReplace(replace)
        if not replace and Env.get('settings').group_misaligned(self._section()):
            # Refused before any network request. The builder asks again under the
            # lock, because another writer can land in between.
            log.warning('Refused a Jackett sync: the stored torrentpotato rows do not line up')
            return {'success': False, 'error': MISALIGNED_TEXT}

        # The network is fetched BEFORE the settings lock is taken: a slow Jackett
        # must not stall every other settings write.
        indexers, error = self.getJackettIndexers(jackett_url, jackett_api_key)

        if error:
            return {
                'success': False,
                'error': error
            }

        indexers = self._rows_from_saved_address(indexers, jackett_url, row_base)

        if not indexers:
            return {
                'success': False,
                'error': 'No configured indexers found in Jackett'
            }

        # A Jackett title, id or key the settings file cannot hold (a comma would
        # become a new row; a control character can lose part of a value) skips
        # that one indexer: never a partial row, never the others held up.
        storable = [i for i in indexers if self._isStorableIndexer(i, jackett_api_key)]
        skipped = len(indexers) - len(storable)
        if not storable:
            return {
                'success': False,
                'error': 'None of the %d Jackett indexers could be saved: their address, '
                         'name or the API key contains a comma or a control character' % skipped
            }

        outcome = {}
        result = Env.get('settings').save_group(
            self._section(),
            self._jackettRowsBuilder(storable, jackett_api_key, replace, outcome))
        if not result['success']:
            return {'success': False, 'error': result['error']}

        # The Settings page locks the group's rows until it has re-read them, and treats
        # `success: false` as "nothing was written". So no exception may be raised after
        # `save_group` has succeeded: `callApiHandler` would report it as success false.
        log.info('Synced %d indexers from Jackett (%d new, %d skipped)',
                 len(storable), outcome['added'], skipped)

        message = f'Synced {len(storable)} indexers from Jackett ({outcome["added"]} new)'
        if skipped:
            message += f', {skipped} skipped because of a comma or control character'
        return {
            'success': True,
            'message': message,
            'added': outcome['added'],
            'skipped': skipped,
            'total': outcome['total'],
            'indexers': storable
        }

    @staticmethod
    def _row_base(saved_url, address):
        """What the rows of a sync are built from, for a saved key that passed the check.

        The saved address as the user saved it, cleaned the way a sync always did, but from the
        very text the normaliser was given (stripped, wrapper removed), so that it cannot name
        something other than `address`: a Kelvin-sign host or a trailing no-break space would
        otherwise write a row for a host the key was never bound to. Where that text is not
        ASCII the normalised address stands in for it.
        """
        text = _address_text(saved_url)
        base = cleanHost(text).rstrip('/') if text else ''
        return base if base and base.isascii() else address

    @staticmethod
    def _rows_from_saved_address(indexers, request_base, row_base):
        """Indexers whose `potato_url` starts with `row_base` instead of `request_base`.

        `getJackettIndexers` builds every `potato_url` from the address it was handed, so each one
        starts with `request_base`; the request goes to the normalised address and the rows are
        built from the address as saved, which is what a sync wrote before the guard.
        """
        return [dict(indexer, potato_url=row_base + indexer['potato_url'][len(request_base):])
                for indexer in indexers]

    def _isReplace(self, replace):
        """Replace everything only for boolean True or the text true, 1, yes or on.

        Any other value is false, including a list or dict (`replace[0]=false`
        arrives as `['false']`, which is truthy) and a number. Over HTTP
        `getParams` already turns the text `false` into False; what this adds is
        that `0`, `no` and `off` no longer replace either.
        """
        if isinstance(replace, str):
            return replace.strip().lower() in ('true', '1', 'yes', 'on')
        return replace is True

    def _section(self):
        """The settings section this provider's `conf` reads and writes."""
        return self.getName().lower().split(':')[0]

    def _isStorableIndexer(self, indexer, jackett_api_key):
        cells = (indexer.get('potato_url'), indexer.get('title'), jackett_api_key)
        return all(unstorable_cell(cell) is None for cell in cells)

    def _jackettRowsBuilder(self, indexers, jackett_api_key, replace, outcome):
        """The builder `Settings.save_group` runs under its lock (AC-DATA-9).

        It only reads the stored rows and returns the merged rows: the writer
        validates them, writes every column once, and puts the memory back if
        anything fails. Stored cells are kept exactly as stored.
        """
        def build():
            settings = Env.get('settings')
            if not replace and settings.group_misaligned(self._section()):
                raise GroupMisaligned
            stored = [] if replace else settings.group_stored_rows(
                self._section(), {'use': '0'})
            rows = [row for row in stored if row['host'] or row['pass_key'] or row['name']]
            known = {row['host'] for row in rows}
            added = 0
            for indexer in indexers:
                if indexer['potato_url'] in known:
                    continue
                rows.append({
                    'use': '1',  # Enable by default
                    'host': indexer['potato_url'],
                    'pass_key': jackett_api_key,  # Use Jackett API key as passkey
                    'name': indexer['title'],  # Use title as username
                    'seed_ratio': '1',
                    'seed_time': '40',
                    'extra_score': '0',
                })
                added += 1
            outcome.update(added=added, total=len(rows))
            return rows

        return build

    def test(self):
        """Test connectivity to all enabled TorrentPotato hosts."""
        hosts = self.getHosts()
        enabled_hosts = [
            (index, host)
            for index, host in enumerate(hosts, start=1)
            if self.isEnabled(host)
        ]

        if not enabled_hosts:
            return False, 'No hosts enabled'

        results = []
        for index, host in enabled_hosts:
            host_url = host.get('host', 'unknown')
            try:
                # Build a simple test URL - TorrentPotato providers typically respond to any search
                test_url = cleanHost(host_url) + '?passkey=%s&user=%s&search=test' % (
                    host.get('pass_key', ''),
                    host.get('name', '')
                )
                data = self.urlopen(test_url, timeout=15)
                # Decode bytes to string for Python 3 compatibility
                if isinstance(data, bytes):
                    data = data.decode('utf-8', errors='replace')

                if data:
                    # Try to parse as JSON to verify it's a valid TorrentPotato response
                    import json
                    try:
                        parsed = json.loads(data)
                        if 'error' in parsed:
                            results.append((False, 'Indexer %d: remote error response' % index))
                        else:
                            results.append((True, 'Indexer %d: OK' % index))
                    except json.JSONDecodeError:
                        # Not JSON but got a response, might still be OK
                        results.append((True, 'Indexer %d: Connected' % index))
                else:
                    results.append((False, 'Indexer %d: No response' % index))
            except Exception as e:
                results.append((False, 'Indexer %d: %s' % (index, type(e).__name__)))

        # Return overall success and combined message
        all_success = all(r[0] for r in results)
        messages = [r[1] for r in results]
        return all_success, '; '.join(messages)


config = [{
    'name': 'torrentpotato',
    'groups': [
        {
            'tab': 'searcher',
            'list': 'torrent_providers',
            'name': 'TorrentPotato',
            'order': 10,
            'description': 'CouchPotato torrent provider. Checkout <a href="https://github.com/CouchPotato/CouchPotatoServer/wiki/CouchPotato-Torrent-Provider" target="_blank">the wiki page about this provider</a> for more info. You can also sync indexers from <a href="https://github.com/Jackett/Jackett" target="_blank">Jackett</a> automatically.',
            'wizard': True,
            'icon': 'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAABnRSTlMAAAAAAABupgeRAAABSElEQVR4AZ2Nz0oCURTGv8t1YMpqUxt9ARFxoQ/gQtppgvUKcu/sxB5iBJkogspaBC6iVUplEC6kv+oiiKDNhAtt16roP0HQgdsMLgaxfvy4nHP4Pi48qE2g4v91JOqT1CH/UnA7w7icUlLawyEdj+ZI/7h6YluWbRiddHonHh9M70aj7VTKzuXuikUMci/EO/ACnAI15599oAk8AR/AgxBQNCzreD7bmpl+FOIVuAHqQDUcJo+AK+CZFKLt95/MpSmMt0TiW9POxse6UvYZ6zB2wFgjFiNpOGesR0rZ0PVPXf8KhUCl22CwClz4eN8weoZBb9c0bdPsOWvHx/cYu9Y0CoNoZTJrwAbn5DrnZc6XOV+igVbnsgo0IxEomlJuA1vUIYGyq3PZBChwmExCUSmVZgMBDIUCK4UCFIv5vHIhm/XUDeAf/ADbcpd5+aXSWQAAAABJRU5ErkJggg==',
            'options': [
                {
                    'name': 'enabled',
                    'type': 'enabler',
                    'default': False,
                },
                {
                    'name': 'jackett_url',
                    'label': 'Jackett URL',
                    'default': '',
                    'description': 'Base URL of your Jackett instance (e.g., http://localhost:9117)',
                },
                {
                    'name': 'jackett_api_key',
                    'label': 'Jackett API Key',
                    'type': 'password',
                    'default': '',
                    'description': 'API key from Jackett (found in Jackett settings)',
                },
                {
                    # The address the saved key was saved for (SEC-005). Written
                    # only by the key's value hook; hidden, so never rendered,
                    # read or written through the settings routes.
                    'name': KEY_BINDING_OPTION,
                    'default': '',
                    'ui-meta': 'hidden',
                },
                {
                    'name': 'jackett_sync',
                    'label': 'Sync from Jackett',
                    'type': 'button',
                    'default': '',
                    'description': 'Click to sync all configured indexers from Jackett',
                    'button_action': 'torrentpotato.jackett_sync',
                    'button_text': 'Sync Indexers',
                },
                {
                    'name': 'use',
                    'default': ''
                },
                {
                    'name': 'host',
                    'default': '',
                    'description': 'The url path of your TorrentPotato provider.',
                },
                {
                    'name': 'extra_score',
                    'advanced': True,
                    'label': 'Extra Score',
                    'default': '0',
                    'description': 'Starting score for each release found via this provider.',
                },
                {
                    'name': 'name',
                    'label': 'Username',
                    'default': '',
                },
                {
                    'name': 'seed_ratio',
                    'label': 'Seed ratio',
                    'default': '1',
                    'description': 'Will not be (re)moved until this seed ratio is met.',
                },
                {
                    'name': 'seed_time',
                    'label': 'Seed time',
                    'default': '40',
                    'description': 'Will not be (re)moved until this seed time (in hours) is met.',
                },
                {
                    'name': 'pass_key',
                    'default': ',',
                    'label': 'Pass Key',
                    'description': 'Can be found on your profile page',
                    'type': 'combined',
                    'combine': ['use', 'host', 'pass_key', 'name', 'seed_ratio', 'seed_time', 'extra_score'],
                    'pairing': ['host', 'pass_key', 'use', 'name'],
                },
            ],
        },
    ],
}]
