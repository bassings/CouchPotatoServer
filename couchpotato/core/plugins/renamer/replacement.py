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


# FEAT-011. Which library file does an OPERATOR's replacement act on, for a
# film the operator has already named. This is a second, separate decision
# from `decide_replacement` above and shares none of its call sites: the
# operator has already asserted identity by naming a specific film and a
# specific source file, which is what makes bypassing the automatic path's
# quality comparison and `_identityIsAsserted` legitimate here and nowhere
# else (spec owner decision 1). Nothing below reads `identity_source`,
# `is_better` or `rank`, and nothing in `decide_replacement` calls this.
#
# The one outcome that names a library file to destroy.
OPERATOR_REPLACE = 'operator_replace'

# No release recorded for this film has a completed copy on disk to replace.
# The ordinary case this feature exists for -- a hand-placed file has nothing
# recorded about it at all -- must refuse exactly the same way: nothing to
# replace is not permission to guess a destination from the naming template.
OPERATOR_DECLINED_NO_FILE_TO_REPLACE = 'operator_declined_no_file_to_replace'

# More than one release for this film has a completed copy on disk. Picking
# either risks destroying the copy the operator did NOT mean, which is
# indistinguishable on the wire from picking the wrong film entirely
# (AC-PROD-4). Refuse rather than choose, and refuse regardless of list order.
OPERATOR_DECLINED_AMBIGUOUS_FILE = 'operator_declined_ambiguous_file'

# A second operator activation while one is already running. A per-route
# lock would QUEUE the retry behind the first instead of refusing it -- the
# exact trap the spec calls out: the operator sees no progress on a 20.3 GB
# cross-mount copy, clicks again, and the retry silently waits its turn
# rather than being told plainly that one is already in flight. This reuses
# the same re-entrancy guard the automatic scan already holds, never a
# second lock.
OPERATOR_REFUSED_ALREADY_RUNNING = 'operator_refused_already_running'

# The operator's chosen source name does not resolve, once symlinks are
# followed, to somewhere inside the configured watch folder. A relative
# traversal, an absolute path elsewhere on disk, a name containing a NUL
# byte and a symlink whose target escapes the folder all return this SAME
# value, deliberately: refuse, never clamp, and never let the refusal tell
# an attacker which hostile shape they tried, exactly as
# `softchroot.chroot2abs` is proven (`couchpotato/core/softchroot.py:167-205`).
OPERATOR_REFUSED_SOURCE_OUTSIDE_WATCH_FOLDER = 'operator_refused_source_outside_watch_folder'

# H8 (branch review 2026-08-31). An unhandled exception anywhere inside the
# operator's worker -- `release.for_media` raising, a database hiccup, an
# unexpected shape in a release document -- is caught rather than left to
# propagate to the bare `threading.Thread` target that runs it, which would
# otherwise land the traceback on stderr only, invisible to CPLog and the
# PrivacyFilter. Never means the library was touched: it is returned only
# from a caught exception, always paired with a `None` destination.
OPERATOR_REFUSED_ERROR = 'operator_refused_error'

# M6 (branch review 2026-08-31). A stale retry against a destination this
# SAME plugin instance already replaced -- a network resend, a doubled
# click, or a retry issued because the operator never saw a response (H1).
# `replace_atomically`'s own `destination_identity` check cannot catch this:
# both the value captured before the call and the value re-checked inside it
# are taken AFTER the first call already finished, so within the second call
# they always agree with each other, whatever they disagree with from
# before. Refused only when the destination still looks EXACTLY as it did
# immediately after the earlier replacement; a destination a THIRD party has
# since touched is a different situation and is not refused by this check.
OPERATOR_REFUSED_ALREADY_REPLACED = 'operator_refused_already_replaced'

# Only a release that actually landed in the library has a file on disk to be
# a replacement target. A snatched or ignored release recorded a path it
# expects to reach, not one that exists yet.
_COMPLETED_RELEASE_STATUSES = frozenset({'done', 'seeding', 'downloaded'})


def decide_operator_replacement(releases):
    """Return `(outcome, existing_release)` for an operator-named film.

    `releases` is every release document already recorded for the film the
    operator named -- the caller resolves that scoping, this function does
    not. `existing_release` is the release whose recorded file would be
    replaced, and is only non-None when the outcome is `OPERATOR_REPLACE`, so
    a caller cannot reach for it on a refusal.

    The destination is never computed here: it is `existing_release`'s own
    `files['movie']` entry, exactly as recorded. Recomputing it from the
    naming template is the one thing this function exists to forbid --
    measured on production, the real template renders the identical path for
    two different films that both lack a year.
    """
    completed = [
        release
        for release in (releases or [])
        if release.get('status') in _COMPLETED_RELEASE_STATUSES
        and (release.get('files') or {}).get('movie')
    ]

    if not completed:
        return OPERATOR_DECLINED_NO_FILE_TO_REPLACE, None

    if len(completed) > 1:
        return OPERATOR_DECLINED_AMBIGUOUS_FILE, None

    return OPERATOR_REPLACE, completed[0]
