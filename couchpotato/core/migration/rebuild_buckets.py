"""
Rebuild database bucket files after hash function change (Py2->Py3).

The core hash index changed _calculate_position from Python 2's hash()
to hashlib.md5(), making all existing bucket positions invalid. This
module rebuilds all bucket files by:

1. Opening the database (bucket files exist with old hash positions)
2. Reading ALL records via sequential bucket iteration (all() method)
3. For each non-id index: destroy + recreate + re-insert all records
4. For the id index: create new bucket file and re-insert all entries
"""
import os
import io
import shutil
import struct
from couchpotato.core.logger import CPLog

log = CPLog(__name__)


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
    stor_path = os.path.join(db_path, 'id_stor')

    # Remove old bucket
    os.remove(buck_path)

    # Create new empty bucket file with correct header
    import marshal
    with io.open(buck_path, 'w+b') as f:
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
    id_ind.buckets = io.open(buck_path, 'r+b', buffering=0)
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
        except Exception as e:
            # May fail for duplicates or corrupt entries
            pass

    print("INFO: Rebuilt id index with %d/%d entries." % (inserted, len(id_entries_raw)))

    # Step 3: Reindex all secondary indexes.
    # Now that the id index works correctly, we can use the normal reindex.
    for index in db.indexes[1:]:
        try:
            index_name = getattr(index, 'name', '?')
            print("INFO: Reindexing %s..." % index_name)
            db.reindex_index(index)
        except Exception as e:
            print("WARNING: Failed to reindex %s: %s" % (index_name, e))

    print("INFO: Database bucket rebuild complete.")
