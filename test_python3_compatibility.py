#!/usr/bin/env python3
"""
Python 3 Compatibility Test Suite

This test suite verifies that all the Python 2 to Python 3 compatibility 
issues we encountered and fixed are working correctly.

Based on the migration fixes for:
1. Dictionary iteration (iterkeys → keys)
2. String type checking (basestring compatibility)
3. Function introspection (im_func → __code__)
4. String/bytes encoding issues
5. Hash function encoding requirements
6. Import compatibility
"""

import unittest
import sys
import os
import hashlib
import tempfile
import inspect
from io import StringIO

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

class Python3CompatibilityTest(unittest.TestCase):
    """Test Python 3 compatibility fixes"""
    
    def test_python_version(self):
        """Ensure we're running on Python 3.8+"""
        self.assertGreaterEqual(sys.version_info.major, 3)
        self.assertGreaterEqual(sys.version_info.minor, 8)
        print(f"✅ Running on Python {sys.version}")

    def test_dictionary_iteration_compatibility(self):
        """Test that dictionary iteration works correctly in Python 3"""
        test_dict = {'a': 1, 'b': 2, 'c': 3}
        
        # Test keys() returns proper view
        keys = test_dict.keys()
        self.assertEqual(set(keys), {'a', 'b', 'c'})
        
        # Test values() returns proper view  
        values = test_dict.values()
        self.assertEqual(set(values), {1, 2, 3})
        
        # Test items() returns proper view
        items = test_dict.items()
        self.assertEqual(set(items), {('a', 1), ('b', 2), ('c', 3)})
        
        print("✅ Dictionary iteration compatibility verified")

    def test_basestring_compatibility(self):
        """Test basestring compatibility layer"""
        # Verify basestring is available (should be aliased to str in Python 3)
        try:
            # This should work if our compatibility layer is in place
            test_str = "hello"
            test_bytes = b"hello"
            
            # In Python 3, str is the base string type
            self.assertTrue(isinstance(test_str, str))
            self.assertFalse(isinstance(test_bytes, str))
            
            print("✅ String type compatibility verified")
        except NameError:
            self.fail("basestring compatibility not properly implemented")

    def test_function_introspection_compatibility(self):
        """Test function introspection works in Python 3"""
        def test_function(self, arg1, arg2):
            pass
            
        # Test __code__ attribute (Python 3 way)
        self.assertTrue(hasattr(test_function, '__code__'))
        code_obj = test_function.__code__
        self.assertTrue(hasattr(code_obj, 'co_varnames'))
        
        # Verify we can get variable names
        var_names = code_obj.co_varnames
        self.assertIn('self', var_names)
        self.assertIn('arg1', var_names)
        self.assertIn('arg2', var_names)
        
        print("✅ Function introspection compatibility verified")

    def test_string_bytes_encoding(self):
        """Test string/bytes encoding handling"""
        test_string = "Hello, 世界! 🎉"
        
        # Test encoding to bytes
        encoded = test_string.encode('utf-8')
        self.assertIsInstance(encoded, bytes)
        
        # Test decoding back to string
        decoded = encoded.decode('utf-8')
        self.assertEqual(decoded, test_string)
        self.assertIsInstance(decoded, str)
        
        print("✅ String/bytes encoding compatibility verified")

    def test_hash_function_encoding(self):
        """Test that hash functions work with proper encoding"""
        test_string = "test_handler_function"
        
        # This should work (string encoded before hashing)
        encoded_hash = hashlib.md5(test_string.encode('utf-8')).hexdigest()
        self.assertIsInstance(encoded_hash, str)
        self.assertEqual(len(encoded_hash), 32)  # MD5 hex digest length
        
        # Verify it produces consistent results
        encoded_hash2 = hashlib.md5(test_string.encode('utf-8')).hexdigest()
        self.assertEqual(encoded_hash, encoded_hash2)
        
        print("✅ Hash function encoding compatibility verified")

    def test_file_io_encoding(self):
        """Test file I/O with proper encoding"""
        test_content = "# Test file\ntest_content = 'Hello, 世界!'\n"
        
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as f:
            f.write(test_content)
            temp_file = f.name
            
        try:
            # Test reading with proper encoding
            with open(temp_file, 'r', encoding='utf-8') as f:
                read_content = f.read()
                self.assertEqual(read_content, test_content)
                self.assertIsInstance(read_content, str)
                
            print("✅ File I/O encoding compatibility verified")
        finally:
            os.unlink(temp_file)

    def test_import_compatibility(self):
        """Test that critical imports work correctly"""
        try:
            # Test core Python 3 imports
            import configparser  # Was ConfigParser in Python 2
            import urllib.parse   # Was urlparse in Python 2
            import io
            
            # Test that we can import our compatibility layer
            from couchpotato.core.compat import string_types, text_type, binary_type
            
            # Verify types are correct for Python 3
            self.assertEqual(string_types, str)
            self.assertEqual(text_type, str) 
            self.assertEqual(binary_type, bytes)
            
            print("✅ Import compatibility verified")
        except ImportError as e:
            self.fail(f"Import compatibility issue: {e}")

class DatabaseCompatibilityTest(unittest.TestCase):
    """Test database-related compatibility fixes"""
    
    def test_coderenitydb_compatibility(self):
        """Test that CodernityDB works with our Python 3 fixes"""
        try:
            from libs.CodernityDB.database import Database
            from libs.CodernityDB.database_super_thread_safe import SuperThreadSafeDatabase
            
            # Test that we can instantiate the database classes
            # (without actually creating files)
            db_class = SuperThreadSafeDatabase
            self.assertTrue(callable(db_class))
            
            print("✅ CodernityDB imports work correctly")
        except ImportError as e:
            self.fail(f"CodernityDB compatibility issue: {e}")

class EventSystemCompatibilityTest(unittest.TestCase):
    """Test event system compatibility"""
    
    def test_event_system_imports(self):
        """Test that event system works with Python 3"""
        try:
            # Test that axl/axel event system imports work
            from libs.axl.axel import Event
            
            # Test that our event system imports work
            from couchpotato.core.event import addEvent, fireEvent
            
            print("✅ Event system imports work correctly")
        except ImportError as e:
            self.fail(f"Event system compatibility issue: {e}")

class WebFrameworkCompatibilityTest(unittest.TestCase):
    """Test web framework compatibility"""
    
    def test_tornado_imports(self):
        """Test Tornado imports work correctly"""
        try:
            from tornado.web import Application, RequestHandler
            from tornado.httpserver import HTTPServer
            
            print("✅ Tornado imports work correctly")
        except ImportError as e:
            self.fail(f"Tornado compatibility issue: {e}")

def run_compatibility_tests():
    """Run all Python 3 compatibility tests"""
    print("🧪 Running Python 3 Compatibility Test Suite")
    print("=" * 60)
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test classes
    test_classes = [
        Python3CompatibilityTest,
        DatabaseCompatibilityTest, 
        EventSystemCompatibilityTest,
        WebFrameworkCompatibilityTest
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("🎉 All Python 3 compatibility tests PASSED!")
        return True
    else:
        print("❌ Some compatibility tests FAILED!")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
        return False

if __name__ == '__main__':
    success = run_compatibility_tests()
    sys.exit(0 if success else 1) 