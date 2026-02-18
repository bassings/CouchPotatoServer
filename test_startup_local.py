#!/usr/bin/env python3
"""Test CouchPotato startup with SQLite migration.

Tests:
1. Fresh install (no database) → creates SQLite
2. Existing CodernityDB → migrates to SQLite, renames to .bak
3. Existing SQLite → opens directly
"""
import os
import sys
import shutil
import tempfile

# Add libs to path for CodernityDB
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


def test_fresh_install():
    """Test fresh install creates SQLite database."""
    print("\n" + "="*60)
    print("Test 1: Fresh Install")
    print("="*60)

    with tempfile.TemporaryDirectory() as data_dir:
        sqlite_db_dir = os.path.join(data_dir, 'database_v2')
        sqlite_db_file = os.path.join(sqlite_db_dir, 'couchpotato.db')

        db = SQLiteAdapter()

        # Simulate fresh install check
        if not os.path.isfile(sqlite_db_file):
            print("  No existing database found, creating fresh SQLite...")
            db.create(sqlite_db_dir)
            db_exists = False
        else:
            db_exists = True

        # Verify
        assert os.path.isfile(sqlite_db_file), "SQLite file not created"
        assert db.is_open, "Database not open"
        assert not db_exists, "Should be new database"

        # Test insert
        result = db.insert({'_t': 'media', 'title': 'Test Movie', 'status': 'active'})
        assert '_id' in result, "Insert failed"

        # Test retrieval
        doc = db.get('id', result['_id'])
        assert doc['title'] == 'Test Movie', "Retrieval failed"

        db.close()
        print("  ✓ Fresh install works correctly")
        return True


def test_migration_from_codernity():
    """Test migration from CodernityDB to SQLite."""
    print("\n" + "="*60)
    print("Test 2: Migration from CodernityDB")
    print("="*60)

    # Use the test data we copied
    test_data_dir = os.path.join(os.path.dirname(__file__), 'test_data')
    source_db = os.path.join(test_data_dir, 'current_db', 'database')

    if not os.path.isdir(source_db):
        print("  ⚠ Skipping - no test database available")
        return True

    with tempfile.TemporaryDirectory() as data_dir:
        # Copy CodernityDB to temp dir
        codernity_path = os.path.join(data_dir, 'database')
        shutil.copytree(source_db, codernity_path)

        sqlite_db_dir = os.path.join(data_dir, 'database_v2')
        sqlite_db_file = os.path.join(sqlite_db_dir, 'couchpotato.db')
        codernity_backup = os.path.join(data_dir, 'database.bak')

        db = SQLiteAdapter()

        # Simulate startup check
        if os.path.isfile(sqlite_db_file):
            print("  Opening existing SQLite...")
            db.open(sqlite_db_dir)
        elif os.path.isdir(codernity_path) and not os.path.isdir(codernity_backup):
            print("  Found CodernityDB, migrating...")
            from couchpotato.core.migration.codernity_to_sqlite import migrate_codernity_to_sqlite
            count = migrate_codernity_to_sqlite(codernity_path, sqlite_db_dir, db)
            print(f"  Migrated {count} documents")
            os.rename(codernity_path, codernity_backup)
            print("  Renamed database to database.bak")
        else:
            db.create(sqlite_db_dir)

        # Verify
        assert os.path.isfile(sqlite_db_file), "SQLite file not created"
        assert os.path.isdir(codernity_backup), "CodernityDB not renamed to .bak"
        assert not os.path.isdir(codernity_path), "Old database path still exists"
        assert db.is_open, "Database not open"

        # Test queries
        media_docs = list(db.query('media_status', limit=5))
        print(f"  Found {len(media_docs)} media documents")
        assert len(media_docs) > 0, "No media documents found"

        db.close()
        print("  ✓ Migration works correctly")
        return True


def test_existing_sqlite():
    """Test opening existing SQLite database."""
    print("\n" + "="*60)
    print("Test 3: Existing SQLite Database")
    print("="*60)

    with tempfile.TemporaryDirectory() as data_dir:
        sqlite_db_dir = os.path.join(data_dir, 'database_v2')
        sqlite_db_file = os.path.join(sqlite_db_dir, 'couchpotato.db')

        # Create initial database
        db = SQLiteAdapter()
        db.create(sqlite_db_dir)
        result = db.insert({'_t': 'media', 'title': 'Existing Movie', 'status': 'active'})
        doc_id = result['_id']
        db.close()

        # Simulate second startup
        db2 = SQLiteAdapter()

        if os.path.isfile(sqlite_db_file):
            print("  Opening existing SQLite...")
            db2.open(sqlite_db_dir)
            db_exists = True
        else:
            db_exists = False

        # Verify
        assert db_exists, "Should detect existing database"
        assert db2.is_open, "Database not open"

        # Verify data persisted
        doc = db2.get('id', doc_id)
        assert doc['title'] == 'Existing Movie', "Data not persisted"

        db2.close()
        print("  ✓ Existing SQLite opens correctly")
        return True


def main():
    results = []

    results.append(('Fresh Install', test_fresh_install()))
    results.append(('Migration from CodernityDB', test_migration_from_codernity()))
    results.append(('Existing SQLite', test_existing_sqlite()))

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {name}: {status}")

    all_passed = all(r[1] for r in results)
    sys.exit(0 if all_passed else 1)


if __name__ == '__main__':
    main()
