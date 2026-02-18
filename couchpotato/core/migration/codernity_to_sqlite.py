"""Migrate CodernityDB database to SQLite.

This module provides one-way migration from the legacy CodernityDB
document store to the new SQLite database format.
"""
import os
import sys

from CodernityDB.database_super_thread_safe import SuperThreadSafeDatabase


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

            except Exception as e:
                errors += 1
                print(f"  Warning: Failed to migrate document {doc.get('_id', 'unknown')}: {e}")

    except Exception as e:
        print(f"  Error iterating CodernityDB: {e}")
        raise

    finally:
        codernity_db.close()

    # Print summary
    print(f"\n  Migration complete: {migrated} documents, {errors} errors")
    print("  Document types migrated:")
    for doc_type, count in sorted(doc_types.items()):
        print(f"    {doc_type}: {count}")

    return migrated
