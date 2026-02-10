"""
Clean orphaned movie entries from the database.

Old databases may contain movie records whose IMDB IDs have been
deleted or merged, leaving entries with no title, year, or plot.
These ghost entries are removed during the upgrade process.
"""
from couchpotato.core.logger import CPLog

log = CPLog(__name__)


def clean_orphaned_movies(db):
    """
    Remove movie entries that have no title information.
    Returns the number of entries removed.
    """
    try:
        from CodernityDB.database import RecordNotFound
    except ImportError:
        RecordNotFound = Exception

    removed = 0
    orphan_ids = []

    try:
        log.debug('Scanning database for orphaned movie entries...')
        # Scan all media records
        for record in db.all('media_by_type', with_doc=True):
            try:
                doc = record.get('doc', record)
                doc_type = doc.get('type', b'')
                if isinstance(doc_type, bytes):
                    doc_type = doc_type.decode('utf-8', errors='replace')
                if doc_type != 'movie':
                    continue

                info = doc.get('info', {})
                titles = info.get('titles', [])
                original_title = info.get('original_title', b'')
                year = info.get('year', 0)
                plot = info.get('plot', b'')

                # Decode bytes values
                if isinstance(original_title, bytes):
                    original_title = original_title.decode('utf-8', errors='replace')
                if isinstance(plot, bytes):
                    plot = plot.decode('utf-8', errors='replace')
                decoded_titles = []
                for t in titles:
                    decoded_titles.append(t.decode('utf-8', errors='replace') if isinstance(t, bytes) else t)

                # A movie is orphaned if it has no title AND no year AND no plot
                has_title = bool(decoded_titles and decoded_titles[0]) or bool(original_title)
                has_data = bool(year) or bool(plot)

                if not has_title and not has_data:
                    doc_id = doc.get('_id', '')
                    identifiers = doc.get('identifiers', {})
                    imdb = identifiers.get('imdb', b'unknown')
                    if isinstance(imdb, bytes):
                        imdb = imdb.decode('utf-8', errors='replace')
                    orphan_ids.append((doc_id, imdb))
            except (RecordNotFound, KeyError, TypeError):
                continue
    except Exception as e:
        log.warning('Could not scan for orphaned movies: %s (%s)', e, type(e).__name__)
        import traceback
        log.debug('Orphan scan traceback: %s', traceback.format_exc())
        return 0

    log.debug('Found %d orphaned entries to remove', len(orphan_ids))

    # Delete orphaned records
    for doc_id, imdb in orphan_ids:
        try:
            doc = db.get('id', doc_id)
            db.delete(doc)
            removed += 1
            log.info('Removed orphaned movie entry: %s (IMDB: %s)', doc_id[:8], imdb)

            # Also try to clean up associated child records (releases, etc.)
            try:
                for child in db.get_many('media_children', doc_id, with_doc=True):
                    child_doc = child.get('doc', child)
                    if child_doc.get('_id'):
                        db.delete(child_doc)
            except (RecordNotFound, Exception):
                pass

        except (RecordNotFound, Exception) as e:
            log.warning('Could not remove orphan %s: %s', doc_id[:8], e)

    return removed
