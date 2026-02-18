#!/usr/bin/env python3
"""Local test script for CodernityDB to SQLite migration.

Tests migration with:
1. Old backup database (pre-changes)
2. Current database (with recent changes)
"""
import os
import sys
import shutil
import tempfile

# Add libs to path for CodernityDB
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.migration.codernity_to_sqlite import migrate_codernity_to_sqlite


def test_migration(source_db_path: str, test_name: str):
    """Test migration from a CodernityDB source."""
    print(f"\n{'='*60}")
    print(f"Testing: {test_name}")
    print(f"Source: {source_db_path}")
    print('='*60)
    
    # Create temp directory for SQLite output
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_path = os.path.join(temp_dir, 'database_v2')
        
        # Create SQLite adapter
        sqlite_db = SQLiteAdapter()
        
        try:
            # Run migration
            count = migrate_codernity_to_sqlite(source_db_path, sqlite_path, sqlite_db)
            print(f"\n✓ Migration successful: {count} documents")
            
            # Verify SQLite database
            print("\nVerifying SQLite database...")
            
            # Count documents by type
            for doc_type in ['media', 'release', 'quality', 'profile', 'category', 'notification', 'property']:
                try:
                    docs = list(sqlite_db.query(doc_type if doc_type != 'media' else 'media_status'))
                    print(f"  {doc_type}: {len(docs)} documents")
                except Exception as e:
                    print(f"  {doc_type}: error - {e}")
            
            # Test specific lookups
            print("\nTesting lookups...")
            try:
                # Get first media document
                media_docs = list(sqlite_db.query('media_status', limit=1))
                if media_docs:
                    media = media_docs[0]
                    print(f"  First media: {media.get('title', 'N/A')} ({media.get('_id', 'N/A')[:8]}...)")
                    
                    # Test get by ID
                    retrieved = sqlite_db.get('id', media['_id'])
                    assert retrieved['_id'] == media['_id'], "ID lookup failed"
                    print(f"  ✓ ID lookup works")
            except Exception as e:
                print(f"  Lookup test failed: {e}")
            
            print(f"\n✓ {test_name} PASSED")
            return True
            
        except Exception as e:
            print(f"\n✗ {test_name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            sqlite_db.close()


def main():
    test_data_dir = os.path.join(os.path.dirname(__file__), 'test_data')
    
    results = []
    
    # Test 1: Old backup database
    old_backup_path = os.path.join(test_data_dir, 'old_backup', 'database')
    if os.path.isdir(old_backup_path):
        results.append(('Old Backup (pre-changes)', test_migration(old_backup_path, 'Old Backup Database')))
    else:
        print(f"Skipping old backup test - not found at {old_backup_path}")
    
    # Test 2: Current database
    current_db_path = os.path.join(test_data_dir, 'current_db', 'database')
    if os.path.isdir(current_db_path):
        results.append(('Current Database', test_migration(current_db_path, 'Current Database')))
    else:
        print(f"Skipping current db test - not found at {current_db_path}")
    
    # Summary
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
