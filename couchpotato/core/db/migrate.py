"""Migration tool: CodernityDB → SQLite.

Usage:
    python -m couchpotato.core.db.migrate --source /path/to/database --dest /path/to/new.db
    python -m couchpotato.core.db.migrate --source /path/to/database --dest /path/to/new.db --verify
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Dict, List, Tuple

# Ensure libs are importable
libs_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'libs')
if os.path.isdir(libs_path) and libs_path not in sys.path:
    sys.path.insert(0, os.path.abspath(libs_path))


def read_codernity_docs(source_path: str) -> list[dict]:
    """Read all documents from a CodernityDB database.

    Args:
        source_path: Path to the CodernityDB database directory.

    Returns:
        List of document dicts.
    """
    from CodernityDB.database import Database, RecordNotFound, RecordDeleted

    db = Database(source_path)
    db.open()

    docs = []
    for doc in db.all('id'):
        try:
            # all('id') returns full documents in CodernityDB
            # Ensure _id is a string (CodernityDB may return bytes)
            if isinstance(doc.get('_id'), bytes):
                doc['_id'] = doc['_id'].decode('utf-8', errors='replace')
            docs.append(doc)
        except (RecordNotFound, RecordDeleted, KeyError):
            continue
        except Exception as e:
            print(f"  Warning: skipping document {doc.get('_id', '?')}: {e}", file=sys.stderr)
            continue

    db.close()
    return docs


def _decode_bytes(value):
    """Recursively decode bytes values to strings."""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, dict):
        return {_decode_bytes(k): _decode_bytes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_bytes(v) for v in value]
    if isinstance(value, tuple):
        return [_decode_bytes(v) for v in value]
    return value


def clean_doc_for_sqlite(doc: dict) -> dict:
    """Clean a CodernityDB document for SQLite insertion.

    Removes CodernityDB internal fields and ensures JSON-serializable data.
    Decodes bytes values to strings.
    """
    skip_keys = {'_rev', 'key'}  # _rev will be regenerated; 'key' is index artifact

    cleaned = {}
    for k, v in doc.items():
        if k in skip_keys:
            continue
        cleaned[_decode_bytes(k)] = _decode_bytes(v)

    return cleaned


def migrate(source_path: str, dest_path: str, verbose: bool = False) -> tuple[int, Counter]:
    """Migrate a CodernityDB database to SQLite.

    Args:
        source_path: Path to CodernityDB database directory.
        dest_path: Path for new SQLite database (directory or .db file).
        verbose: Print progress.

    Returns:
        Tuple of (total_migrated, type_counts).
    """
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    if verbose:
        print(f"Reading from CodernityDB: {source_path}")

    docs = read_codernity_docs(source_path)
    if verbose:
        print(f"  Found {len(docs)} documents")

    # Clean documents
    cleaned = [clean_doc_for_sqlite(doc) for doc in docs]

    # Count by type
    type_counts = Counter(d.get('_t', 'unknown') for d in cleaned)
    if verbose:
        print(f"  Types: {dict(type_counts)}")

    # Create SQLite database
    adapter = SQLiteAdapter()
    adapter.create(dest_path)

    if verbose:
        print(f"Writing to SQLite: {dest_path}")

    # Bulk insert
    count = adapter.insert_bulk(cleaned)

    if verbose:
        print(f"  Migrated {count} documents")

    adapter.close()
    return count, type_counts


def verify(source_path: str, dest_path: str, verbose: bool = False) -> bool:
    """Verify a migrated SQLite database against the CodernityDB source.

    Checks:
    - Total document counts match
    - Document type counts match
    - All document IDs exist in both
    - Sample document data integrity

    Returns:
        True if verification passes.
    """
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    if verbose:
        print("Verifying migration...")

    # Read source (clean bytes for fair comparison)
    source_docs_raw = read_codernity_docs(source_path)
    source_docs = [clean_doc_for_sqlite(d) for d in source_docs_raw]
    source_by_id = {d['_id']: d for d in source_docs}
    source_types = Counter(d.get('_t', 'unknown') for d in source_docs)

    if verbose:
        print(f"  Source: {len(source_docs)} documents, types: {dict(source_types)}")

    # Read destination
    adapter = SQLiteAdapter()
    adapter.open(dest_path)
    dest_docs = list(adapter.all('id'))
    dest_by_id = {d['_id']: d for d in dest_docs}
    dest_types = Counter(d.get('_t', 'unknown') for d in dest_docs)

    if verbose:
        print(f"  Dest:   {len(dest_docs)} documents, types: {dict(dest_types)}")

    errors = []

    # Check counts
    if len(source_docs) != len(dest_docs):
        errors.append(f"Document count mismatch: source={len(source_docs)}, dest={len(dest_docs)}")

    # Check type counts
    for doc_type in set(list(source_types.keys()) + list(dest_types.keys())):
        s = source_types.get(doc_type, 0)
        d = dest_types.get(doc_type, 0)
        if s != d:
            errors.append(f"Type '{doc_type}' count mismatch: source={s}, dest={d}")

    # Check all IDs exist
    missing_in_dest = set(source_by_id.keys()) - set(dest_by_id.keys())
    if missing_in_dest:
        errors.append(f"Missing in dest: {len(missing_in_dest)} documents")

    extra_in_dest = set(dest_by_id.keys()) - set(source_by_id.keys())
    if extra_in_dest:
        errors.append(f"Extra in dest: {len(extra_in_dest)} documents")

    # Spot-check data integrity on all documents
    skip_fields = {'_rev', 'key'}  # These are expected to differ
    data_mismatches = 0
    for doc_id in source_by_id:
        if doc_id not in dest_by_id:
            continue
        src = source_by_id[doc_id]
        dst = dest_by_id[doc_id]

        for field in src:
            if field in skip_fields:
                continue
            src_val = src.get(field)
            dst_val = dst.get(field)
            if src_val != dst_val:
                # JSON round-trip might change int/float types
                try:
                    if json.dumps(src_val, sort_keys=True, default=str) == json.dumps(dst_val, sort_keys=True, default=str):
                        continue
                except (TypeError, ValueError):
                    pass
                data_mismatches += 1
                if verbose and data_mismatches <= 5:
                    print(f"  Data mismatch in {doc_id}.{field}: {repr(src_val)[:100]} != {repr(dst_val)[:100]}")

    if data_mismatches:
        errors.append(f"Data mismatches in {data_mismatches} fields")

    adapter.close()

    if errors:
        if verbose:
            print("VERIFICATION FAILED:")
            for e in errors:
                print(f"  ✗ {e}")
        return False
    else:
        if verbose:
            print("VERIFICATION PASSED ✓")
        return True


def main():
    parser = argparse.ArgumentParser(description='Migrate CouchPotatoServer database from CodernityDB to SQLite')
    parser.add_argument('--source', required=True, help='Path to CodernityDB database directory')
    parser.add_argument('--dest', required=True, help='Path for SQLite database')
    parser.add_argument('--verify', action='store_true', help='Verify migration after completion')
    parser.add_argument('--verify-only', action='store_true', help='Only verify, do not migrate')
    parser.add_argument('-v', '--verbose', action='store_true', default=True, help='Verbose output')
    parser.add_argument('-q', '--quiet', action='store_true', help='Quiet output')
    args = parser.parse_args()

    verbose = not args.quiet

    if args.verify_only:
        success = verify(args.source, args.dest, verbose=verbose)
        sys.exit(0 if success else 1)

    start = time.time()
    count, types = migrate(args.source, args.dest, verbose=verbose)
    elapsed = time.time() - start

    if verbose:
        print(f"\nMigration complete in {elapsed:.1f}s")

    if args.verify:
        success = verify(args.source, args.dest, verbose=verbose)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
