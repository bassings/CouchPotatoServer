"""May the incoming copy replace the one already in the library?

FEAT-009B B3a. A pure decision function: it takes the facts and returns an
outcome. **It performs no filesystem or database operation whatsoever** — the
atomic swap lands separately in B3b, so this layer can be proven exhaustively
before anything acts on it.

That ordering is the whole point. Two previous attempts at upgrade replacement
were withdrawn, and both destroyed an irreplaceable file:

  - the first compared nothing at all, so a 720p download overwrote a 2160p
    remux (measured);
  - the second compared with `quality.isHigher`, a SEARCH heuristic that
    answers "should I keep looking under this profile" rather than "is this
    file better". The default `Best` profile excludes 2160p, so it authorised
    destroying a remux too -- while simultaneously being INERT, because the
    releases it needed were never attached. Fixing the inertness would have
    activated the destruction.

So every "no" below is a named outcome, not a falsy return, and the caller
must treat anything other than `REPLACE` as "leave the library file alone".

The rules, and where each comes from:

  * `upgrade_replace` off  -> refuse. A NEW settings key, defaulting off,
    because the long-declared `remove_lower_quality_copies` is already
    persisted True on every existing install (spec D1).
  * more than one video file in the group -> refuse. If cd1's swap commits and
    cd2's fails, cd1's bytes are gone, and a set-aside is forbidden by
    AC-SIMP-11. Resolved by subtraction rather than rollback machinery (D7).
  * the existing file's quality comes from its RELEASE DOCUMENT, never from
    `quality.guess` -- the default template carries no quality token, so
    guessing collapses to size and rates a 2160p remux as `brrip` (D2).
  * anything unknown, ambiguous or unverifiable -> refuse. On this code path
    "I am not sure" and "delete it" must never be the same branch.
"""

from couchpotato.core.plugins.renamer.owner import (
    OWNER_RESOLVED,
    resolve_owning_release,
)

# The one outcome that authorises deleting from the library.
REPLACE = 'replace'

DECLINED_SETTING_OFF = 'declined_setting_off'
DECLINED_MULTI_FILE_GROUP = 'declined_multi_file_group'
DECLINED_UNKNOWN_QUALITY = 'declined_unknown_quality'
DECLINED_NOT_BETTER = 'declined_not_better'


def decide_replacement(
    destination,
    incoming_quality,
    releases,
    size_on_disk,
    video_file_count,
    setting_enabled,
    is_better,
):
    """Return `(outcome, existing_release)`.

    `existing_release` is the release whose file would be deleted, and is only
    non-None when the outcome is `REPLACE` — so a caller cannot reach for it
    on a refusal.

    `is_better(incoming_quality, existing_quality) -> bool` is injected rather
    than imported so this stays pure and the caller supplies
    `QualityPlugin.isBetterQuality`. `video_file_count` is the number of movie
    files in the group, counted by the caller.
    """
    if not setting_enabled:
        return DECLINED_SETTING_OFF, None

    if video_file_count != 1:
        # Not "> 1": a group with ZERO video files has nothing to reason about
        # either, and treating it as replaceable would be a decision made on no
        # evidence at all.
        return DECLINED_MULTI_FILE_GROUP, None

    existing, owner_outcome = resolve_owning_release(destination, releases, size_on_disk)
    if owner_outcome != OWNER_RESOLVED:
        # The resolver's own refusal is returned verbatim rather than
        # flattened, so an operator learns WHY: no claimant, several, or a
        # recorded size that disagrees with the bytes on disk.
        return owner_outcome, None

    existing_quality = {
        'identifier': existing.get('quality'),
        'is_3d': bool(existing.get('is_3d')),
    }
    if not existing_quality['identifier']:
        return DECLINED_UNKNOWN_QUALITY, None

    if not _has_identifier(incoming_quality):
        # `quality.guess` returns None at quality/main.py:362 and :373, so this
        # is reachable rather than defensive.
        return DECLINED_UNKNOWN_QUALITY, None

    if not is_better(incoming_quality, existing_quality):
        return DECLINED_NOT_BETTER, None

    return REPLACE, existing


def _has_identifier(quality):
    return bool(isinstance(quality, dict) and quality.get('identifier'))
