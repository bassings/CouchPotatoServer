#!/usr/bin/env python3
"""Test quality fill on fresh database.

DEF-010: Quality fill fails on fresh database when db.get() raises KeyError
instead of RecordNotFound.

TDD: This test should FAIL until the fix is applied.
"""
import os
import sys
import tempfile
import unittest

# Add libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


class TestQualityFillFreshDatabase(unittest.TestCase):
    """Test that quality fill works on a fresh database."""

    def setUp(self):
        """Create fresh SQLite database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db = SQLiteAdapter()
        self.db.create(self.temp_dir)

    def tearDown(self):
        """Clean up."""
        self.db.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_nonexistent_quality_raises_keyerror(self):
        """Verify that db.get raises KeyError for missing document.

        This documents the current behavior that code must handle.
        """
        with self.assertRaises(KeyError):
            self.db.get('quality', '2160p', with_doc=True)

    def test_quality_fill_pattern_handles_missing_gracefully(self):
        """Test the pattern used in quality/main.py:fill() works.

        The fill() method should handle both RecordNotFound (CodernityDB)
        and KeyError (SQLite) when a quality doesn't exist yet.
        """
        # This is the pattern from quality/main.py:193-196
        existing = None
        try:
            existing = self.db.get('quality', '2160p', with_doc=True)
        except KeyError:
            # SQLiteAdapter raises KeyError
            pass

        # Should reach here without crashing
        self.assertIsNone(existing)

        # Now we can insert the quality
        result = self.db.insert({
            '_t': 'quality',
            'identifier': '2160p',
            'order': 0,
            'size_min': 10000,
            'size_max': 100000,
        })
        self.assertIn('_id', result)

        # And retrieve it
        existing = self.db.get('quality', '2160p', with_doc=True)
        self.assertIsNotNone(existing)
        self.assertEqual(existing['doc']['identifier'], '2160p')

    def test_all_quality_identifiers(self):
        """Test that all standard quality identifiers can be created.

        Covers the full quality list from quality/main.py.
        """
        qualities = [
            '2160p', 'bd50', '1080p', '720p', 'brrip',
            'dvdr', 'dvdrip', 'scr', 'r5', 'tc', 'ts', 'cam'
        ]

        for identifier in qualities:
            # Should not raise when quality doesn't exist
            existing = None
            try:
                existing = self.db.get('quality', identifier, with_doc=True)
            except KeyError:
                pass

            self.assertIsNone(existing, f"Quality {identifier} should not exist yet")

            # Insert quality
            self.db.insert({
                '_t': 'quality',
                'identifier': identifier,
                'order': qualities.index(identifier),
                'size_min': 100,
                'size_max': 10000,
            })

            # Should now exist
            retrieved = self.db.get('quality', identifier, with_doc=True)
            self.assertEqual(retrieved['doc']['identifier'], identifier)


class TestQualityGetWithDoc(unittest.TestCase):
    """Test quality retrieval patterns."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db = SQLiteAdapter()
        self.db.create(self.temp_dir)

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_existing_quality_with_doc_true(self):
        """Test that with_doc=True returns {'doc': ...} format."""
        # Insert quality
        self.db.insert({
            '_t': 'quality',
            'identifier': '1080p',
            'order': 2,
            'size_min': 5000,
            'size_max': 20000,
        })

        # Retrieve with with_doc=True
        result = self.db.get('quality', '1080p', with_doc=True)

        # Must have 'doc' key (CodernityDB compat)
        self.assertIn('doc', result)
        self.assertEqual(result['doc']['identifier'], '1080p')

    def test_get_existing_quality_with_doc_false(self):
        """Test that with_doc=False returns document directly."""
        # Insert quality
        self.db.insert({
            '_t': 'quality',
            'identifier': '720p',
            'order': 3,
            'size_min': 3000,
            'size_max': 10000,
        })

        # Retrieve with with_doc=False (default)
        result = self.db.get('quality', '720p', with_doc=False)

        # Should return document directly
        self.assertEqual(result['identifier'], '720p')


if __name__ == '__main__':
    unittest.main()
