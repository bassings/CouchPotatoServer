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
# The release list could not be read in full. Distinct from "this media has no
# releases" (declined_no_owner): an unreadable document may be the very one
# that claims the destination, so the difference decides whether an operator
# looks at their database or at their library.
DECLINED_INCOMPLETE_EVIDENCE = 'declined_incomplete_evidence'

# The decision itself blew up. Named for the same reason as every other
# outcome here: a raw string duplicated at the call site and again in a test
# has no shared symbol, so a typo in either survives a rename and nothing
# catches it.
DECLINED_ERROR = 'declined_error'

# The destination resolves outside the configured library root. Refusing to
# move a file INTO an odd place would be over-reach; refusing to DESTROY one
# outside the library the operator gave us is not.
DECLINED_OUTSIDE_LIBRARY = 'declined_outside_library'

# The source is not the size the scanner measured, so the quality rung on it
# describes an earlier version of the file. Usually a downloader still
# appending.
DECLINED_SOURCE_CHANGED = 'declined_source_changed'

# The group's movie identity came from a fuzzy title-and-year search rather
# than from an assertion about this release. A wrong guess would not mis-file
# a download here; it would destroy a DIFFERENT movie's library copy.
DECLINED_UNVERIFIED_IDENTITY = 'declined_unverified_identity'

# The source's byte size is nowhere near the band its claimed quality rung
# occupies. The scanner prefers a snatched release's CLAIMED quality over its
# own detection, so a small file labelled 2160p outranks a genuine 1080p copy
# on paper alone.
DECLINED_SIZE_CONTRADICTS_QUALITY = 'declined_size_contradicts_quality'
DECLINED_NOT_BETTER = 'declined_not_better'


def decide_replacement(
    destination,
    incoming_quality,
    releases,
    size_on_disk,
    video_file_count,
    setting_enabled,
    is_better,
    rank,
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

    if not existing.get('quality'):
        return DECLINED_UNKNOWN_QUALITY, None

    # `is_3d` must be PRESENT on the release document, not defaulted here.
    #
    # B1 deliberately refuses a quality dict whose `is_3d` is absent, because
    # absent is not the same as False -- a 3D copy and a 2D one at the same
    # rung are not comparable, and guessing "not 3D" authorises replacing one
    # with the other. Building the dict with `bool(existing.get('is_3d'))`
    # fabricated the key and handed B1 something that LOOKED complete,
    # defeating that protection entirely from one layer up. Measured: a
    # release recorded without the field returned `replace`.
    if 'is_3d' not in existing:
        return DECLINED_UNKNOWN_QUALITY, None

    existing_quality = {
        'identifier': existing['quality'],
        'is_3d': existing['is_3d'],
    }

    # Symmetric with the existing side above: identifier AND is_3d must both
    # be present. `_has_identifier` alone accepted a dict carrying only an
    # identifier, which the real `isBetterQuality` then refuses for a missing
    # is_3d -- reporting `declined_not_better`, i.e. "the copy on disk is
    # fine", when the truth is "we could not read the incoming quality".
    # `quality.guess` returns None at quality/main.py:362 and :373, so the
    # unknown case is reachable rather than defensive.
    if not _is_complete_quality(incoming_quality):
        return DECLINED_UNKNOWN_QUALITY, None

    # An identifier the ranking does not recognise is UNKNOWN, not "not
    # better". Both refuse, but they send an operator to different places: one
    # says the copy on disk is fine, the other says we could not read the
    # quality at all.
    #
    # `rank` is a REQUIRED argument, not an optional one defaulting to None.
    # As an optional it was a safety check that a caller could silently omit,
    # which is the fail-OPEN shape this whole task exists to avoid -- and the
    # wiring step is exactly where it would have been forgotten.
    if rank(incoming_quality) is None or rank(existing_quality) is None:
        return DECLINED_UNKNOWN_QUALITY, None

    if not is_better(incoming_quality, existing_quality):
        return DECLINED_NOT_BETTER, None

    return REPLACE, existing


def _is_complete_quality(quality):
    """Both fields present. `is_3d` is checked for PRESENCE, not truth: absent
    is not False, and a 3D copy is not comparable with a 2D one at the same
    rung."""
    return bool(
        isinstance(quality, dict)
        and quality.get('identifier')
        and 'is_3d' in quality
    )
