"""Ordering releases by the user's preferred download source.

`searcher.preferred_method` ('both' | 'nzb' | 'torrent') is a HARD preference
that orders every release of the preferred protocol before every release of
the other one; nothing is excluded by this ordering step. Falls back to the
other protocol if no acceptable release of the preferred one is found --
"acceptable" meaning it passes `Release.tryDownloadResult`'s FILTERS (status /
minimum_score / size / seeders). If the preferred release passes those filters
but the download itself then fails (downloader disabled/unreachable,
provider error), `tryDownloadResult` does not advance to the next candidate --
that is a pre-existing, separate limitation of this ordering, not something
this module can fix. See tests/unit/test_protocol_preference.py::
TestFallbackToTheOtherProtocol for both the covered and the known-gap cases.

Both call sites — `Searcher.search()` (what gets downloaded) and
`Release.forMedia()` (what the UI lists) — sort by score first and then apply
this, relying on a stable sort to keep score order inside each protocol group.
"""

_NZB_PROTOCOLS = ('nzb',)
_TORRENT_PROTOCOLS = ('torrent', 'torrent_magnet')

#: Ranks, low sorts first.
_PREFERRED = 0
_OTHER = 1
_UNKNOWN = 2


def protocol_family(protocol):
    """Classify `protocol` as 'nzb', 'torrent', or None if unrecognised.

    Public because two features depend on the same answer: the preference
    ordering below, and the release list's source filter
    (`couchpotato/ui/releases_view.py`). They must not drift apart.
    """

    if not isinstance(protocol, str):
        return None

    normalised = protocol.strip().lower()

    if normalised in _NZB_PROTOCOLS:
        return 'nzb'
    if normalised in _TORRENT_PROTOCOLS:
        return 'torrent'
    return None


def _protocol_rank(protocol, preference):
    """Rank `protocol` against `preference`.

    Returns 0 for the preferred family, 1 for the other known family, and 2 for
    anything unrecognised. Unknown ranks last in BOTH directions: a release
    whose protocol we cannot identify must never outrank one we can, whichever
    way the preference points.
    """

    family = protocol_family(protocol)

    if family is None:
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

    return sorted(items, key = lambda item: _protocol_rank(get_protocol(item), preference))
