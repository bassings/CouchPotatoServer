#!/usr/bin/env python3
"""Test SQLite adapter CodernityDB compatibility methods.

Tests the methods that were causing production issues:
- get_many() 
- with_doc=True format (returns {'doc': ...})
- count()
- Thread safety (check_same_thread=False)
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


def test_get_many():
    """Test get_many returns iterator of documents."""
    print("\n" + "="*60)
    print("Test: get_many()")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as data_dir:
        db = SQLiteAdapter()
        db.create(data_dir)
        
        # Insert test releases with different statuses
        for i in range(5):
            db.insert({'_t': 'release', 'media_id': 'movie1', 'status': 'snatched', 'name': f'Release {i}'})
        for i in range(3):
            db.insert({'_t': 'release', 'media_id': 'movie1', 'status': 'done', 'name': f'Done {i}'})
        
        # Test get_many with status filter
        snatched = list(db.get_many('release_status', 'snatched'))
        assert len(snatched) == 5, f"Expected 5 snatched, got {len(snatched)}"
        
        # Test get_many with media_id filter
        releases = list(db.get_many('release', 'movie1'))
        assert len(releases) == 8, f"Expected 8 releases, got {len(releases)}"
        
        db.close()
        print("  ✓ get_many() works correctly")
        return True


def test_with_doc_format():
    """Test that with_doc=True returns {'doc': document} format."""
    print("\n" + "="*60)
    print("Test: with_doc=True format")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as data_dir:
        db = SQLiteAdapter()
        db.create(data_dir)
        
        # Insert test data
        result = db.insert({'_t': 'media', 'title': 'Test Movie', 'status': 'active'})
        doc_id = result['_id']
        
        # Test get() with with_doc=True
        # First insert into an index we can query
        db.insert({'_t': 'release', 'media_id': doc_id, 'status': 'wanted', 'identifier': 'test-release-1'})
        
        got = db.get('release_status', 'wanted', with_doc=True)
        assert 'doc' in got, f"Expected 'doc' key in result, got: {got.keys()}"
        assert got['doc']['status'] == 'wanted', "Document content incorrect"
        
        # Test query() with with_doc=True
        results = list(db.query('release_status', key='wanted', with_doc=True))
        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        assert 'doc' in results[0], f"Expected 'doc' key in query result"
        
        # Test get_many() with with_doc=True
        many = list(db.get_many('release_status', 'wanted', with_doc=True))
        assert len(many) == 1, f"Expected 1 result from get_many"
        assert 'doc' in many[0], f"Expected 'doc' key in get_many result"
        
        db.close()
        print("  ✓ with_doc=True returns {'doc': ...} format")
        return True


def test_count():
    """Test count() method."""
    print("\n" + "="*60)
    print("Test: count()")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as data_dir:
        db = SQLiteAdapter()
        db.create(data_dir)
        
        # Insert test profiles
        for i in range(5):
            db.insert({'_t': 'profile', 'name': f'Profile {i}', 'order': i})
        
        # Test count
        count = db.count(db.all, 'profile')
        assert count == 5, f"Expected 5 profiles, got {count}"
        
        # Test count with empty result (use quality which has 0 entries)
        count_empty = db.count(db.all, 'quality')
        assert count_empty == 0, f"Expected 0 qualities, got {count_empty}"
        
        db.close()
        print("  ✓ count() works correctly")
        return True


def test_thread_safety():
    """Test that SQLite works across threads."""
    print("\n" + "="*60)
    print("Test: Thread Safety")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as data_dir:
        db = SQLiteAdapter()
        db.create(data_dir)
        
        # Insert initial data
        result = db.insert({'_t': 'media', 'title': 'Main Thread Movie', 'status': 'active'})
        main_id = result['_id']
        
        errors = []
        results = []
        
        def worker_read():
            """Worker that reads from another thread."""
            try:
                time.sleep(0.1)  # Slight delay to ensure main thread is done
                doc = db.get('id', main_id)
                results.append(doc['title'])
            except Exception as e:
                errors.append(f"Read error: {e}")
        
        def worker_write():
            """Worker that writes from another thread."""
            try:
                time.sleep(0.05)
                db.insert({'_t': 'media', 'title': 'Worker Thread Movie', 'status': 'active'})
                results.append('write_ok')
            except Exception as e:
                errors.append(f"Write error: {e}")
        
        # Start threads
        t1 = threading.Thread(target=worker_read)
        t2 = threading.Thread(target=worker_write)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        if errors:
            print(f"  ✗ Thread errors: {errors}")
            return False
        
        assert 'Main Thread Movie' in results, "Read from other thread failed"
        assert 'write_ok' in results, "Write from other thread failed"
        
        db.close()
        print("  ✓ Thread safety works (check_same_thread=False)")
        return True


def test_destroy_index():
    """Test destroy_index() method."""
    print("\n" + "="*60)
    print("Test: destroy_index()")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as data_dir:
        db = SQLiteAdapter()
        db.create(data_dir)
        
        # Add an index
        db.add_index('test_index')
        assert 'test_index' in db.indexes_names
        
        # Destroy it
        db.destroy_index('test_index')
        assert 'test_index' not in db.indexes_names
        
        db.close()
        print("  ✓ destroy_index() works correctly")
        return True


def test_category_media_pattern():
    """Test the exact pattern used in category/main.py that was failing."""
    print("\n" + "="*60)
    print("Test: Category Media Pattern")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as data_dir:
        db = SQLiteAdapter()
        db.create(data_dir)
        
        # Insert category
        cat_result = db.insert({'_t': 'category', 'label': 'Action', 'order': 1})
        category_id = cat_result['_id']
        
        # Insert media in that category
        for i in range(3):
            db.insert({
                '_t': 'media', 
                'title': f'Action Movie {i}',
                'category_id': category_id,
                'status': 'active'
            })
        
        # This is the exact pattern from category/main.py:147
        movies = [x['doc'] for x in db.get_many('category_media', category_id, with_doc=True)]
        
        assert len(movies) == 3, f"Expected 3 movies, got {len(movies)}"
        assert all('title' in m for m in movies), "Movies missing title"
        
        db.close()
        print("  ✓ Category media pattern works correctly")
        return True


if __name__ == '__main__':
    tests = [
        ('get_many', test_get_many),
        ('with_doc format', test_with_doc_format),
        ('count', test_count),
        ('thread safety', test_thread_safety),
        ('destroy_index', test_destroy_index),
        ('category media pattern', test_category_media_pattern),
    ]
    
    results = {}
    for name, test_fn in tests:
        try:
            results[name] = test_fn()
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    sys.exit(0 if all_passed else 1)
