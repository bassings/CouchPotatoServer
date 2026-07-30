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
