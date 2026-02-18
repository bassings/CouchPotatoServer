"""
Fix release quality values in the database.

Prior to this fix, releases were stored with the "searched" quality
(i.e., the quality from the movie's profile) instead of the actual
detected quality from the release name. This migration re-detects
quality for all releases with names available.

Example: A release named "Avatar.2025.2160p.BluRay" was incorrectly
stored as "720p" if the profile searched for 720p first.
"""
from couchpotato.core.event import fireEvent
from couchpotato.core.logger import CPLog

log = CPLog(__name__)


def fix_release_quality(db):
    """
    Re-detect and fix quality for all releases based on their names.
    Returns a tuple of (fixed_count, total_checked).
    """
    try:
        from CodernityDB.database import RecordNotFound
    except ImportError:
        RecordNotFound = Exception

    fixed = 0
    checked = 0

    try:
        log.info('Scanning releases for quality detection fixes...')

        # Scan all release records by iterating through all status types
        statuses = ['available', 'snatched', 'downloaded', 'done', 'ignored', 'failed']
        all_releases = []

        for status in statuses:
            try:
                for record in db.get_many('release_status', status, with_doc=True):
                    doc = record.get('doc', record)
                    if doc and doc.get('_t') == 'release':
                        all_releases.append(doc)
            except Exception:
                pass  # Status may not exist in DB

        log.info('Found %d releases to check', len(all_releases))

        for doc in all_releases:
            try:
                if doc.get('_t') != 'release':
                    continue

                checked += 1

                # Get release info
                info = doc.get('info', {})
                release_name = info.get('name', '')
                if isinstance(release_name, bytes):
                    release_name = release_name.decode('utf-8', errors='replace')

                if not release_name:
                    continue

                current_quality = doc.get('quality', '')
                if isinstance(current_quality, bytes):
                    current_quality = current_quality.decode('utf-8', errors='replace')

                # Detect quality from release name
                detected = fireEvent('quality.guess', [release_name], single=True)
                if not detected:
                    continue

                detected_quality = detected.get('identifier', '')
                detected_is_3d = detected.get('is_3d', False)

                # Check if quality needs fixing
                if detected_quality and detected_quality != current_quality:
                    old_quality = current_quality
                    doc['quality'] = detected_quality
                    doc['is_3d'] = detected_is_3d

                    db.update(doc)
                    fixed += 1

                    # Log significant fixes (e.g., 2160p incorrectly stored as 720p)
                    if old_quality in ('720p', '1080p') and detected_quality == '2160p':
                        log.info('Fixed quality: %s -> %s for "%s"',
                                old_quality, detected_quality, release_name[:60])
                    else:
                        log.debug('Fixed quality: %s -> %s for "%s"',
                                 old_quality, detected_quality, release_name[:40])

            except (RecordNotFound, KeyError, TypeError) as e:
                log.debug('Skipped release: %s', e)
                continue

    except Exception as e:
        log.warning('Could not scan releases for quality fixes: %s (%s)', e, type(e).__name__)
        import traceback
        log.debug('Quality fix traceback: %s', traceback.format_exc())
        return 0, 0

    return fixed, checked
