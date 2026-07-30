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


def _display_name(release):
    return (_info(release).get('name') or release.get('identifier') or '')


#: sort key -> (extractor, is_numeric). The extractor returns None when the
#: release has nothing to sort on, which sends it to the missing group.
def _numeric(field):
    def extract(release, _profile_qualities):
        value = _info(release).get(field)
        return None if value is None else tryFloat(value)
    return extract


def _quality_key(release, profile_qualities):
    identifier = _quality_identifier(release)
    if not identifier:
        return None
    if profile_qualities:
        # Profile order is best-first, so a lower index is a better quality.
        if identifier in profile_qualities:
            return profile_qualities.index(identifier)
        return None
    return identifier.lower()


_SORT_KEYS = {
    'name': lambda r, _pq: _display_name(r).lower() or None,
    'quality': _quality_key,
    'score': _numeric('score'),
    'size': _numeric('size'),
    'seeders': _numeric('seeders'),
    'age': _numeric('age'),
    'source': lambda r, _pq: protocol_family(_info(r).get('protocol')),
    'status': lambda r, _pq: (r.get('status') or '').lower() or None,
}


def filter_and_sort_releases(releases, controls, profile_qualities = None):
    """Apply `controls` (already normalised) to `releases`.

    Returns a new list; never mutates the input. `profile_qualities` is the
    movie's profile quality list, ordered best-first, used only by the
    quality sort.
    """

    filtered = [r for r in releases if _matches(r, controls)]

    return _sorted(filtered, controls, profile_qualities)


def _sorted(releases, controls, profile_qualities):
    extract = _SORT_KEYS.get(controls['sort'])
    if extract is None:
        # 'default' -- keep the incoming order, which is Part A's output
        # (score, then the user's download-source preference). `dir` is
        # deliberately ignored: reversing here would invert that preference.
        return list(releases)

    present, missing = [], []
    for release in releases:
        try:
            key = extract(release, profile_qualities)
        except Exception:
            key = None
        (present if key is not None else missing).append((key, release))

    # Mixed key types would raise on comparison; only sort when they agree.
    if len({type(key) for key, _ in present}) > 1:
        present.sort(key = lambda pair: str(pair[0]), reverse = controls['dir'] == 'desc')
    else:
        present.sort(key = lambda pair: pair[0], reverse = controls['dir'] == 'desc')

    # Missing values always trail, whichever direction was asked for: absent
    # data must never lead the list.
    return [release for _key, release in present] + [release for _key, release in missing]
