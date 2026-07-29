"""Ordering releases by the user's preferred download source.

`searcher.preferred_method` ('both' | 'nzb' | 'torrent') is a HARD preference
that FALLS BACK: every release of the preferred protocol outranks every release
of the other one, but nothing is excluded, so when the preferred protocol has
no usable release the other one is still downloaded.

Both call sites — `Searcher.search()` (what gets downloaded) and
`Release.forMedia()` (what the UI lists) — sort by score first and then apply
this, relying on a stable sort to keep score order inside each protocol group.
"""

NO_PREFERENCE = 'both'

_NZB_PROTOCOLS = ('nzb',)
_TORRENT_PROTOCOLS = ('torrent', 'torrent_magnet')

#: Ranks, low sorts first.
_PREFERRED = 0
_OTHER = 1
_UNKNOWN = 2


def protocol_rank(protocol, preference):
    """Rank `protocol` against `preference`.

    Returns 0 for the preferred family, 1 for the other known family, and 2 for
    anything unrecognised. Unknown ranks last in BOTH directions: a release
    whose protocol we cannot identify must never outrank one we can, whichever
    way the preference points.
    """

    if not isinstance(protocol, str):
        return _UNKNOWN

    normalised = protocol.strip().lower()

    if normalised in _NZB_PROTOCOLS:
        family = 'nzb'
    elif normalised in _TORRENT_PROTOCOLS:
        family = 'torrent'
    else:
        return _UNKNOWN

    return _PREFERRED if family == preference else _OTHER


def sort_by_protocol_preference(items, preference, get_protocol):
    """Stable-sort `items` so the preferred protocol comes first.

    `preference` is 'both' | 'nzb' | 'torrent'; anything else (including None,
    as a config read can yield before defaults are applied) is treated as no
    preference and the incoming order is returned unchanged.

    `get_protocol` maps an item to its protocol string — the two call sites
    hold it at different key paths.
    """

    if preference not in ('nzb', 'torrent'):
        return list(items)

    return sorted(items, key = lambda item: protocol_rank(get_protocol(item), preference))
