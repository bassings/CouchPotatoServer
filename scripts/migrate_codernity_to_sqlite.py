#!/usr/bin/env python3
"""One-time CodernityDB -> SQLite database migration (REFACTOR-01).

This is a standalone, directly-runnable upgrade tool for people still on an
old CouchPotato install that used the legacy CodernityDB document store.
CodernityDB itself (``libs/CodernityDB``) is kept fully intact as the read
path for this one-time upgrade -- only the *migration* logic lives here,
outside the live application tree (``couchpotato/core/``), because it has no
business running on every startup of an already-migrated install.

``couchpotato/runner.py`` auto-runs this script as a subprocess, exactly
once, the first time it detects a legacy ``database/`` directory with no
``database.bak`` alongside it -- preserving the old zero-touch upgrade
experience. It can also be run manually for disaster recovery:

    python scripts/migrate_codernity_to_sqlite.py --data-dir /path/to/data

On success, the CodernityDB directory is renamed to ``database.bak`` (the
original is never deleted) and the process exits 0. On any failure, nothing
is renamed, the original CodernityDB is left untouched, and the process
exits non-zero so the caller (runner.py) can detect the failure and abort
startup instead of silently creating a fresh, empty database.
"""
import argparse
import marshal
import os
import re
import sqlite3
import sys
import traceback

# --- sys.path bootstrap -----------------------------------------------------
# This script must be runnable completely standalone -- as a subprocess
# invoked by couchpotato/runner.py, or directly by an operator doing manual
# recovery -- so it cannot rely on the caller having already put `libs/` and
# the repo root on sys.path. Mirrors what CouchPotato.py does for the main
# app.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_LIBS_DIR = os.path.join(_REPO_ROOT, 'libs')
for _path in (_REPO_ROOT, _LIBS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from CodernityDB.database_super_thread_safe import SuperThreadSafeDatabase  # noqa: E402
from couchpotato.core.logger import CPLog  # noqa: E402

log = CPLog(__name__)


_TO_BYTES_HELPER = (
    "\ndef _to_bytes(s):\n"
    "    return s.encode('utf-8') if isinstance(s, str) else s\n"
)


def fix_index_files(db_path):
    """
    Scan database index files and fix bare md5() calls that pass
    strings directly (Python 2 legacy). Returns number of files fixed.
    """
    indexes_path = os.path.join(db_path, '_indexes')
    if not os.path.isdir(indexes_path):
        return 0

    fixed = 0
    for fname in sorted(os.listdir(indexes_path)):
        if not fname.endswith('.py'):
            continue

        filepath = os.path.join(indexes_path, fname)
        with open(filepath, 'r') as f:
            content = f.read()

        if 'md5(' not in content:
            continue

        # Already migrated?
        if '_to_bytes' in content:
            continue

        # Check if any md5() call lacks .encode() — i.e. bare md5(key) or md5(data.get(...))
        bare_md5 = re.findall(r'md5\(([^)]+)\)', content)
        needs_fix = any('.encode' not in arg for arg in bare_md5)

        if not needs_fix:
            continue

        # Add _to_bytes helper after hashlib import
        content = content.replace(
            'from hashlib import md5',
            'from hashlib import md5' + _TO_BYTES_HELPER
        )

        # Wrap bare md5() calls: md5(X) -> md5(_to_bytes(X))
        # Use a function to handle nested parentheses properly
        def _wrap_md5_calls(content):
            result = []
            i = 0
            while i < len(content):
                # Look for md5(
                if content[i:i+4] == 'md5(':
                    start = i
                    i += 4
                    # Find matching closing paren, handling nesting
                    depth = 1
                    inner_start = i
                    while i < len(content) and depth > 0:
                        if content[i] == '(':
                            depth += 1
                        elif content[i] == ')':
                            depth -= 1
                        i += 1
                    inner = content[inner_start:i-1]
                    # Only wrap if no .encode() already present
                    if '.encode' in inner:
                        result.append(content[start:i])
                    else:
                        result.append('md5(_to_bytes(%s))' % inner)
                else:
                    result.append(content[i])
                    i += 1
            return ''.join(result)

        content = _wrap_md5_calls(content)

        with open(filepath, 'w') as f:
            f.write(content)
        fixed += 1

    return fixed


def rebuild_after_migration(db, db_path):
    """
    Rebuild all bucket files after the hash function migration.
    Must be called AFTER fix_index_files and BEFORE normal startup.
    The db must NOT be open yet.
    """
    print("INFO: Opening database for bucket rebuild...")
    db.open()

    # Step 1: Read ALL records from id index via sequential iteration.
    # all('id') reads the bucket file entry by entry (not by hash position),
    # so it works even with stale hash positions.
    print("INFO: Reading all records from id storage...")
    all_id_entries = []
    for entry in db.all('id'):
        all_id_entries.append(entry)
    print("INFO: Found %d records." % len(all_id_entries))

    if not all_id_entries:
        print("WARNING: No records found in database.")
        return

    # Step 2: Rebuild the id index bucket.
    # We need to create a new bucket file with entries at the CORRECT
    # hash positions (using the new hashlib.md5 function).
    id_ind = db.id_ind
    print("INFO: Rebuilding id index bucket...")

    # Read all raw entries from the current bucket file
    id_entries_raw = []
    id_ind.buckets.seek(id_ind.data_start)
    while True:
        raw = id_ind.buckets.read(id_ind.entry_line_size)
        if not raw or len(raw) < id_ind.entry_line_size:
            break
        try:
            doc_id, rev, start, size, status, _next = id_ind.entry_struct.unpack(raw)
            if status != b'd':
                id_entries_raw.append((doc_id, rev, start, size, status))
        except Exception:
            continue

    print("INFO: Read %d id entries from bucket file." % len(id_entries_raw))

    # Close the bucket file, destroy it, recreate it empty
    id_ind.buckets.close()
    buck_path = os.path.join(db_path, 'id_buck')

    # Remove old bucket
    os.remove(buck_path)

    # Create new empty bucket file with correct header
    with open(buck_path, 'w+b') as f:
        props = dict(
            name=id_ind.name,
            bucket_line_format=id_ind.bucket_line_format,
            entry_line_format=id_ind.entry_line_format,
            hash_lim=id_ind.hash_lim,
            version=id_ind.__version__,
            storage_class=id_ind.storage_class
        )
        f.write(marshal.dumps(props))

    # Reopen the bucket file
    id_ind.buckets = open(buck_path, 'r+b', buffering=0)
    id_ind._fix_params()

    # Clear any caches
    if hasattr(id_ind, '_find_key') and hasattr(id_ind._find_key, 'clear'):
        id_ind._find_key.clear()
    if hasattr(id_ind, '_locate_doc_id') and hasattr(id_ind._locate_doc_id, 'clear'):
        id_ind._locate_doc_id.clear()

    # Re-insert all entries into the new bucket with correct hash positions
    inserted = 0
    for doc_id, rev, start, size, status in id_entries_raw:
        try:
            id_ind.insert(doc_id, rev, start, size, status)
            inserted += 1
        except Exception:
            # May fail for duplicates or corrupt entries
            pass

    print("INFO: Rebuilt id index with %d/%d entries." % (inserted, len(id_entries_raw)))

    # Step 3: Reindex all secondary indexes.
    # Now that the id index works correctly, we can use the normal reindex.
    for index in db.indexes[1:]:
        index_name = getattr(index, 'name', '?')
        try:
            print("INFO: Reindexing %s..." % index_name)
            db.reindex_index(index)
        except Exception as e:
            print("WARNING: Failed to reindex %s: %s" % (index_name, e))

    print("INFO: Database bucket rebuild complete.")


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


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        prog='migrate_codernity_to_sqlite.py',
        description=(
            'One-time migration of a legacy CodernityDB database to the '
            'SQLite database format used by current CouchPotato. On success '
            'the CodernityDB directory is renamed to database.bak; on '
            'failure it is left untouched and nothing is written.'
        ),
    )
    parser.add_argument(
        '--data-dir', required=True,
        help='CouchPotato data directory. Derives the CodernityDB path as '
             '<data-dir>/database, the SQLite path as <data-dir>/database_v2, '
             'and the post-migration backup path as <data-dir>/database.bak.',
    )
    parser.add_argument(
        '--codernity-path', default=None,
        help='Override the CodernityDB source path (default: <data-dir>/database).',
    )
    parser.add_argument(
        '--sqlite-path', default=None,
        help='Override the SQLite destination path (default: <data-dir>/database_v2).',
    )
    return parser


def main(argv=None):
    args = _build_arg_parser().parse_args(argv)

    data_dir = os.path.abspath(os.path.expanduser(args.data_dir))
    codernity_path = (
        os.path.abspath(os.path.expanduser(args.codernity_path)) if args.codernity_path
        else os.path.join(data_dir, 'database')
    )
    sqlite_path = (
        os.path.abspath(os.path.expanduser(args.sqlite_path)) if args.sqlite_path
        else os.path.join(data_dir, 'database_v2')
    )
    backup_path = os.path.join(data_dir, 'database.bak')

    if not os.path.isdir(codernity_path):
        print(f"ERROR: no CodernityDB database found at {codernity_path}", file=sys.stderr)
        return 1

    if os.path.isdir(backup_path):
        print(
            f"ERROR: {backup_path} already exists -- migration appears to have "
            "already run. Refusing to overwrite it; remove or rename it "
            "manually first if you really need to re-run the migration.",
            file=sys.stderr,
        )
        return 1

    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
    sqlite_db = SQLiteAdapter()

    print(f"INFO: Found CodernityDB database at {codernity_path}, migrating to SQLite...")
    try:
        migrate_codernity_to_sqlite(codernity_path, sqlite_path, sqlite_db)
    except Exception as e:
        print(f"ERROR: migration failed: {e}", file=sys.stderr)
        traceback.print_exc()
        print(
            f"INFO: the original CodernityDB database at {codernity_path} has "
            "NOT been modified or renamed.",
            file=sys.stderr,
        )
        return 1
    finally:
        try:
            sqlite_db.close()
        except Exception:
            pass

    print("INFO: Migration complete. Renaming old database to database.bak...")
    os.rename(codernity_path, backup_path)
    print("INFO: CodernityDB renamed to database.bak. Now using SQLite.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
