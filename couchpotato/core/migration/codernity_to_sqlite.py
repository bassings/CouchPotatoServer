"""Migrate CodernityDB database to SQLite.

This module provides one-way migration from the legacy CodernityDB
document store to the new SQLite database format.
"""
import os
import sqlite3
import sys

from CodernityDB.database_super_thread_safe import SuperThreadSafeDatabase
from couchpotato.core.logger import CPLog


log = CPLog(__name__)


def migrate_codernity_to_sqlite(codernity_path: str, sqlite_path: str, sqlite_db) -> int:
    """Migrate all documents from CodernityDB to SQLite.

    Args:
        codernity_path: Path to the CodernityDB database directory
        sqlite_path: Path for the new SQLite database directory
        sqlite_db: An SQLiteAdapter instance (will be created/opened)

    Returns:
        Number of documents migrated
    """
    # Fix any Python 2 index files first
    from couchpotato.core.migration.fix_indexes import fix_index_files
    n_fixed = fix_index_files(codernity_path)
    if n_fixed:
        print(f"  Fixed {n_fixed} CodernityDB index file(s) for Python 3 compatibility.")

    # Open CodernityDB for reading
    codernity_db = SuperThreadSafeDatabase(codernity_path)
    if not codernity_db.exists():
        raise RuntimeError(f"CodernityDB not found at {codernity_path}")

    try:
        codernity_db.open()
    except Exception as e:
        # May need to rebuild buckets after index fix
        print(f"  Warning: Error opening CodernityDB: {e}")
        print("  Attempting to rebuild indexes...")
        from couchpotato.core.migration.rebuild_buckets import rebuild_after_migration
        rebuild_after_migration(codernity_db, codernity_path)

    # Create fresh SQLite database
    sqlite_db.create(sqlite_path)

    # Migrate all documents
    migrated = 0
    errors = 0
    duplicates = 0
    doc_types = {}

    print("  Reading documents from CodernityDB...")
    try:
        # Iterate through all documents using the 'id' index
        for doc in codernity_db.all('id'):
            try:
                # Track document types for reporting
                doc_type = doc.get('_t', 'unknown')
                doc_types[doc_type] = doc_types.get(doc_type, 0) + 1

                # Insert into SQLite
                sqlite_db.insert(doc)
                migrated += 1

                # Progress indicator
                if migrated % 100 == 0:
                    print(f"  Migrated {migrated} documents...", end='\r')

            except sqlite3.IntegrityError as e:
                doc_id = doc.get('_id', 'unknown')
                # insert() can raise IntegrityError from TWO distinct
                # constraints: the UNIQUE (provider, identifier) index
                # (REG-004, a real duplicate movie) OR the documents._id
                # PRIMARY KEY (a duplicate/malformed _id in the source
                # CodernityDB). Only the former is an "already-migrated
                # identifier" -- attribute by the error text so a different
                # corruption isn't mislabeled as a duplicate identifier.
                if 'media_identifiers' in str(e):
                    # DATA-LOSS event on a disaster-recovery path -- the source
                    # DB contained duplicate media and this row is NOT carried
                    # into SQLite. Make it loud; the original CodernityDB is
                    # preserved in database.bak.
                    duplicates += 1
                    print(f"  DUPLICATE: skipping document {doc_id} (identifier already migrated): {e}")
                    log.warning(
                        'Migration DROPPED a duplicate-identifier document %s '
                        '(_t=%s): its media identifier was already migrated, and '
                        'the UNIQUE index rejected it (REG-004). This row was NOT '
                        'migrated (data loss); the original is preserved in '
                        'database.bak. Error: %s',
                        doc_id, doc.get('_t', 'unknown'), e,
                    )
                else:
                    # A different integrity violation (e.g. duplicate _id
                    # PRIMARY KEY): treat as a generic migration error, not an
                    # already-migrated identifier.
                    errors += 1
                    print(f"  Warning: Failed to migrate document {doc_id}: {e}")
                    log.warning('Failed to migrate document %s: %s', doc_id, e)

            except Exception as e:
                errors += 1
                doc_id = doc.get('_id', 'unknown')
                print(f"  Warning: Failed to migrate document {doc_id}: {e}")
                log.warning('Failed to migrate document %s: %s', doc_id, e)

    except Exception as e:
        print(f"  Error iterating CodernityDB: {e}")
        raise

    finally:
        codernity_db.close()

    # Print summary
    print(f"\n  Migration complete: {migrated} documents, {errors} errors, "
          f"{duplicates} duplicate-identifier documents skipped")
    if duplicates:
        log.warning(
            '%s duplicate-identifier document(s) were skipped during migration '
            'and are NOT present in the SQLite database. The original CodernityDB '
            'is preserved in database.bak. Run the dedup migration to recover '
            'them (REG-004).',
            duplicates,
        )
    print("  Document types migrated:")
    for doc_type, count in sorted(doc_types.items()):
        print(f"    {doc_type}: {count}")

    return migrated
