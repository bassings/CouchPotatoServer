"""Filtering and sorting for the movie-detail release list.

Pure functions only: a list of release documents in, a list out. No FastAPI,
no Jinja, no database -- so the behaviour is unit-testable directly and the
route and template stay thin.

Control values arrive from the query string, which can be bookmarked, shared
or hand-edited, so `normalise_controls` coerces anything unrecognised to a
default instead of raising.
"""

from couchpotato.core.helpers.protocol import protocol_family
from couchpotato.core.helpers.variable import tryFloat

#: The no-op view: exactly what the page rendered before Part B existed.
DEFAULT_CONTROLS = {
    'source': 'all',
    'quality': 'all',
    'status': 'all',
    'sort': 'default',
    'dir': 'desc',
}

SOURCES = ('all', 'nzb', 'torrent')
STATUSES = ('all', 'available', 'snatched', 'downloaded', 'done', 'seeding', 'ignored', 'failed')
SORTS = ('default', 'name', 'quality', 'score', 'source', 'status', 'age', 'size', 'seeders')
DIRECTIONS = ('asc', 'desc')

_WHITELISTS = {
    'source': SOURCES,
    'status': STATUSES,
    'sort': SORTS,
    'dir': DIRECTIONS,
}


def _clean(value):
    return value.strip().lower() if isinstance(value, str) else None


def normalise_controls(params):
    """Coerce raw query params into a valid, complete control set."""

    controls = dict(DEFAULT_CONTROLS)

    for field, allowed in _WHITELISTS.items():
        value = _clean(params.get(field))
        if value in allowed:
            controls[field] = value

    # Quality is deliberately NOT whitelisted: identifiers come from the
    # library, so a value this code has never heard of is legitimate and
    # should match nothing rather than be rewritten to 'all' (which would
    # show everything and look like the filter was ignored).
    quality = params.get('quality')
    if isinstance(quality, str) and quality.strip():
        controls['quality'] = quality.strip()

    return controls


def _quality_identifier(release):
    """Read the quality identifier out of either shape a release may hold."""

    quality = release.get('quality')
    if isinstance(quality, str):
        return quality
    if isinstance(quality, dict):
        return quality.get('identifier') or quality.get('label') or ''
    return ''


def _info(release):
    return release.get('info') or {}


def _matches(release, controls):
    if controls['source'] != 'all':
        if protocol_family(_info(release).get('protocol')) != controls['source']:
            return False

    if controls['quality'] != 'all':
        if _quality_identifier(release) != controls['quality']:
            return False

    if controls['status'] != 'all':
        if (release.get('status') or '') != controls['status']:
            return False

    return True


def filter_and_sort_releases(releases, controls):
    """Apply `controls` (already normalised) to `releases`.

    Returns a new list; never mutates the input.
    """

    filtered = [r for r in releases if _matches(r, controls)]

    return _sorted(filtered, controls)


def _sorted(releases, controls):
    # Filled in by Task 4; ordering is a separate concern from filtering.
    return list(releases)
