"""Repair the quality order of default profiles seeded before BUG-016.

The built-in profiles used to be seeded worst-first: 'Best' was
``['720p', '1080p', 'brrip', 'dvdrip']``. Index 0 of a profile is the *most
preferred* quality and ``MovieSearcher.single()`` stops at the first
successful download, so 'Best' fetched 720p and never reached 1080p, and
'UHD 4K' (``['720p', '1080p', '2160p']``) could never deliver 4K.

``ProfilePlugin.fill()`` only runs on a fresh install, so correcting the
seeds does nothing for existing databases. This migration repairs them.

**Only a profile whose label AND stored quality order match a known-bad seed
exactly is rewritten.** Anything the user renamed, reordered, or edited is
left strictly alone -- someone who deliberately prefers 720p (disk space, a
slow line) must not have that silently undone. That also makes the migration
idempotent: once repaired, a profile no longer matches a known-bad seed.

See specs/BUG-016-default-profile-quality-order.md.
"""
from couchpotato.core.logger import CPLog

log = CPLog(__name__)


# Each entry describes one mis-seeded default.
#
# 'permutation' holds indices into the OLD lists, in their new order:
# new[i] = old[permutation[i]]. Explicit indices rather than a sort key
# because 'Prefer 3D HD' repeats identifiers, so only position distinguishes
# its rungs.
#
# '3d' is part of the match, not just the payload -- for the 3D profiles the
# identifiers alone are ambiguous.
LEGACY_DEFAULTS = [{
    'label': 'Best',
    'qualities': ['720p', '1080p', 'brrip', 'dvdrip'],
    '3d': [False, False, False, False],
    'permutation': [1, 0, 2, 3],
}, {
    'label': 'HD',
    'qualities': ['720p', '1080p'],
    '3d': [False, False],
    'permutation': [1, 0],
}, {
    'label': 'SD',
    'qualities': ['dvdrip', 'dvdr'],
    '3d': [False, False],
    'permutation': [1, 0],
}, {
    'label': 'UHD 4K',
    'qualities': ['720p', '1080p', '2160p'],
    '3d': [False, False, False],
    'permutation': [2, 1, 0],
}, {
    # Only the non-3D tail was inverted; the 3D head was already correct.
    'label': 'Prefer 3D HD',
    'qualities': ['1080p', '720p', '720p', '1080p'],
    '3d': [True, True, False, False],
    'permutation': [0, 1, 3, 2],
}]

# Kept in step with the lists build_profile_doc() produces.
POSITIONAL_KEYS = ('qualities', 'finish', 'wait_for', 'stop_after', '3d')


def _match(doc):
    """Return the LEGACY_DEFAULTS entry this profile is an untouched copy
    of, or None."""
    label = doc.get('label')
    qualities = doc.get('qualities')
    if not label or not qualities:
        return None

    # Very old rows may have no '3d' list at all; that means "no 3D rungs".
    stored_3d = [bool(x) for x in (doc.get('3d') or [])]
    if not stored_3d:
        stored_3d = [False] * len(qualities)

    for legacy in LEGACY_DEFAULTS:
        if (label == legacy['label']
                and list(qualities) == legacy['qualities']
                and stored_3d == legacy['3d']):
            return legacy

    return None


def _permute(doc, legacy):
    """Apply the permutation to every positional list present on the doc.

    All five lists are permuted identically -- permuting 'qualities' alone
    would detach each rung's finish/wait_for/stop_after/3d flags from the
    quality they describe.
    """
    permutation = legacy['permutation']

    for key in POSITIONAL_KEYS:
        values = doc.get(key)
        # A row missing a positional list (or with a truncated one) is left
        # as-is for that key rather than being padded with guesses.
        if not values or len(values) != len(permutation):
            continue
        doc[key] = [values[i] for i in permutation]


def fix_profile_quality_order(db):
    """Reorder mis-seeded default profiles best-first.

    Returns a tuple of (fixed_count, checked_count).
    """
    fixed = 0
    checked = 0

    try:
        profiles = [x['doc'] for x in db.all('profile', with_doc=True)]
    except Exception as e:
        log.warning('Could not list profiles for quality-order fix: %s (%s)',
                    e, type(e).__name__)
        return 0, 0

    for doc in profiles:
        try:
            if doc.get('_t') != 'profile':
                continue

            checked += 1

            legacy = _match(doc)
            if not legacy:
                continue

            before = list(doc.get('qualities') or [])
            _permute(doc, legacy)

            db.update(doc)
            fixed += 1
            log.info('Reordered default profile %r best-first: %s -> %s',
                     doc.get('label'), before, doc.get('qualities'))

        except Exception as e:
            # One bad row (a write conflict, a malformed document) must not
            # strand the rest of the batch -- keep going.
            log.debug('Skipped profile during quality-order fix: %s (%s)',
                      e, type(e).__name__)
            continue

    return fixed, checked
