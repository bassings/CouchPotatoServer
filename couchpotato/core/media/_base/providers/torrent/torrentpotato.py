from urllib.parse import urlparse
import re
import traceback
import xml.etree.ElementTree as ET

from requests import HTTPError

from couchpotato.api import addApiView
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.variable import splitString, tryInt, tryFloat, cleanHost
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.providers.base import ResultList
from couchpotato.core.media._base.providers.torrent.base import TorrentProvider


log = CPLog(__name__)


class Base(TorrentProvider):

    urls = {}
    limits_reached = {}

    http_time_between_calls = 1  # Seconds

    def __init__(self):
        super().__init__()

        # Register API endpoint for Jackett sync
        addApiView('torrentpotato.jackett_sync', self.jackettSync, docs={
            'desc': 'Sync TorrentPotato indexers from Jackett',
            'params': {
                'jackett_url': {'desc': 'Jackett base URL (optional, uses saved setting if not provided)'},
                'jackett_api_key': {'desc': 'Jackett API key (optional, uses saved setting if not provided)'},
            },
            'return': {'type': 'object', 'example': '{"success": true, "indexers": [...]}'}
        })

        addApiView('torrentpotato.jackett_test', self.jackettTest, docs={
            'desc': 'Test Jackett connection and list available indexers',
            'params': {
                'jackett_url': {'desc': 'Jackett base URL'},
                'jackett_api_key': {'desc': 'Jackett API key'},
            },
            'return': {'type': 'object', 'example': '{"success": true, "indexers": [...]}'}
        })

    def search(self, media, quality):
        hosts = self.getHosts()

        # Don't trust imdb_results=True - many indexers ignore IMDB ID and just search by title
        # This causes wrong movies to be matched (e.g., "Sister Act" results for "Sister Act 3")
        results = ResultList(self, media, quality, imdb_results = False)

        for host in hosts:
            if self.isDisabled(host):
                continue

            self._searchOnHost(host, media, quality, results)

        return results

    def _searchOnHost(self, host, media, quality, results):
        url = self.buildUrl(media, host)

        try:
            torrents = self.getJsonData(url, cache_timeout=1800)
        except HTTPError as e:
            # Handle 400 Bad Request gracefully - common for TV/Anime-only indexers
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 400:
                host_name = host.get('name') or urlparse(host['host']).hostname or host['host']
                log.warning('Indexer %s returned 400 Bad Request - likely a TV/Anime-only indexer that does not support movie searches',
                           host_name)
                return
            raise
        except Exception:
            log.error('Failed getting results from %s: %s', host['host'], traceback.format_exc())
            return

        if torrents:
            try:
                if torrents.get('error'):
                    log.error('%s: %s', torrents.get('error'), host['host'])
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

            except Exception:
                log.error('Failed getting results from %s: %s', host['host'], traceback.format_exc())

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

        for host in hosts:
            result = super().belongsTo(url, host = host['host'], provider = provider)
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
            jackett_url = cleanHost(jackett_url).rstrip('/')
            # Use the torznab endpoint with t=indexers to get all indexers
            indexers_url = f'{jackett_url}/torznab/all/api?apikey={jackett_api_key}&t=indexers'

            log.info('Fetching Jackett indexers from: %s', indexers_url.replace(jackett_api_key, '***'))

            response = self.urlopen(indexers_url, timeout=30)
            if not response:
                return None, 'No response from Jackett'

            # Parse XML response
            root = ET.fromstring(response)

            # Check for Jackett error response
            error = root.find('.//error')
            if error is not None:
                error_desc = error.get('description', 'Unknown error')
                log.error('Jackett returned error: %s', error_desc)
                return None, f'Jackett error: {error_desc}'

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

        except ET.ParseError as e:
            log.error('Failed to parse Jackett response: %s', e)
            return None, f'Failed to parse Jackett response: {e}'
        except Exception as e:
            log.error('Failed to fetch Jackett indexers: %s', traceback.format_exc())
            return None, f'Failed to connect to Jackett: {e}'

    def jackettTest(self, jackett_url=None, jackett_api_key=None, **kwargs):
        """Test Jackett connection and return list of available indexers"""
        saved_url = self.conf('jackett_url')
        saved_key = self.conf('jackett_api_key')

        # Ensure values are strings (settings may return bytes)
        if isinstance(saved_url, bytes):
            saved_url = saved_url.decode('utf-8')
        if isinstance(saved_key, bytes):
            saved_key = saved_key.decode('utf-8')

        # Also handle str that looks like bytes repr: "b'...'"
        if isinstance(saved_key, str) and saved_key.startswith("b'") and saved_key.endswith("'"):
            saved_key = saved_key[2:-1]
        if isinstance(saved_url, str) and saved_url.startswith("b'") and saved_url.endswith("'"):
            saved_url = saved_url[2:-1]

        jackett_url = jackett_url or saved_url
        jackett_api_key = jackett_api_key or saved_key

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
            jackett_url: Jackett base URL (uses saved setting if not provided)
            jackett_api_key: Jackett API key (uses saved setting if not provided)
            replace: If True, replace all existing indexers. If False, merge/add new ones.
        """
        saved_url = self.conf('jackett_url')
        saved_key = self.conf('jackett_api_key')

        log.debug('jackettSync: saved_url type=%s, repr=%r', type(saved_url).__name__, saved_url)
        log.debug('jackettSync: saved_key type=%s, repr=%r', type(saved_key).__name__, saved_key[:10] if saved_key else None)

        # Ensure values are strings (settings may return bytes)
        if isinstance(saved_url, bytes):
            saved_url = saved_url.decode('utf-8')
        if isinstance(saved_key, bytes):
            saved_key = saved_key.decode('utf-8')

        # Also handle str that looks like bytes repr: "b'...'"
        if isinstance(saved_key, str) and saved_key.startswith("b'") and saved_key.endswith("'"):
            saved_key = saved_key[2:-1]
        if isinstance(saved_url, str) and saved_url.startswith("b'") and saved_url.endswith("'"):
            saved_url = saved_url[2:-1]

        jackett_url = jackett_url or saved_url
        jackett_api_key = jackett_api_key or saved_key

        if not jackett_url or not jackett_api_key:
            return {
                'success': False,
                'error': 'Jackett URL and API key are required. Please configure them in settings.'
            }

        indexers, error = self.getJackettIndexers(jackett_url, jackett_api_key)

        if error:
            return {
                'success': False,
                'error': error
            }

        if not indexers:
            return {
                'success': False,
                'error': 'No configured indexers found in Jackett'
            }

        # Get existing hosts
        existing_hosts = self.getHosts() if not replace else []
        existing_urls = {h['host'] for h in existing_hosts}

        # Build new configuration
        new_uses = []
        new_hosts = []
        new_names = []
        new_pass_keys = []
        new_seed_ratios = []
        new_seed_times = []
        new_extra_scores = []

        # Keep existing entries first (if not replacing)
        for host in existing_hosts:
            new_uses.append(str(host.get('use', '1')))
            new_hosts.append(host['host'])
            new_names.append(host.get('name', ''))
            new_pass_keys.append(host.get('pass_key', ''))
            new_seed_ratios.append(str(host.get('seed_ratio', '1')))
            new_seed_times.append(str(host.get('seed_time', '40')))
            new_extra_scores.append(str(host.get('extra_score', '0')))

        # Add new indexers from Jackett
        added_count = 0
        for indexer in indexers:
            potato_url = indexer['potato_url']

            # Skip if already exists
            if potato_url in existing_urls:
                continue

            new_uses.append('1')  # Enable by default
            new_hosts.append(potato_url)
            new_names.append(indexer['title'])  # Use title as username
            new_pass_keys.append(jackett_api_key)  # Use Jackett API key as passkey
            new_seed_ratios.append('1')
            new_seed_times.append('40')
            new_extra_scores.append('0')
            added_count += 1

        # Save the configuration
        self.conf('use', value=','.join(new_uses))
        self.conf('host', value=','.join(new_hosts))
        self.conf('name', value=','.join(new_names))
        self.conf('pass_key', value=','.join(new_pass_keys))
        self.conf('seed_ratio', value=','.join(new_seed_ratios))
        self.conf('seed_time', value=','.join(new_seed_times))
        self.conf('extra_score', value=','.join(new_extra_scores))

        log.info('Synced %d indexers from Jackett (%d new)', len(indexers), added_count)

        return {
            'success': True,
            'message': f'Synced {len(indexers)} indexers from Jackett ({added_count} new)',
            'added': added_count,
            'total': len(new_hosts),
            'indexers': indexers
        }

    def test(self):
        """Test connectivity to all enabled TorrentPotato hosts."""
        hosts = self.getHosts()
        enabled_hosts = [h for h in hosts if self.isEnabled(h)]

        if not enabled_hosts:
            return False, 'No hosts enabled'

        results = []
        for host in enabled_hosts:
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

                hostname = urlparse(host_url).hostname or host_url
                if data:
                    # Try to parse as JSON to verify it's a valid TorrentPotato response
                    import json
                    try:
                        parsed = json.loads(data)
                        if 'error' in parsed:
                            results.append((False, '%s: %s' % (hostname, parsed.get('error', 'Unknown error'))))
                        else:
                            results.append((True, '%s: OK' % hostname))
                    except json.JSONDecodeError:
                        # Not JSON but got a response, might still be OK
                        results.append((True, '%s: Connected' % hostname))
                else:
                    results.append((False, '%s: No response' % hostname))
            except Exception as e:
                hostname = urlparse(host_url).hostname or host_url
                results.append((False, '%s: %s' % (hostname, str(e)[:50])))

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
                },
            ],
        },
    ],
}]
