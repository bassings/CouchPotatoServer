#!/usr/bin/env python3
"""
Comprehensive tests for couchpotato/api.py
Tests the API handlers, routing, and async functionality.
"""

import unittest
import json
import threading
import sys
from unittest.mock import Mock, patch, MagicMock
import urllib.parse
import os
# UnicodeDecodeError is built-in, no need to import

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

class TestCouchPotatoAPI(unittest.TestCase):
    """Test the couchpotato API module"""

    def setUp(self):
        """Set up test environment"""
        # Import after setting up environment
        from couchpotato.api import (
            api, api_locks, api_nonblock, api_docs, api_docs_missing,
            run_async, run_handler, addNonBlockApiView, addApiView,
            NonBlockHandler, ApiHandler
        )
        
        self.api = api
        self.api_locks = api_locks
        self.api_nonblock = api_nonblock
        self.api_docs = api_docs
        self.api_docs_missing = api_docs_missing
        self.run_async = run_async
        self.run_handler = run_handler
        self.addNonBlockApiView = addNonBlockApiView
        self.addApiView = addApiView
        self.NonBlockHandler = NonBlockHandler
        self.ApiHandler = ApiHandler

    def tearDown(self):
        """Clean up test environment"""
        # Clear API registrations
        self.api.clear()
        self.api_locks.clear()
        self.api_nonblock.clear()
        self.api_docs.clear()
        self.api_docs_missing.clear()

    def test_api_initialization(self):
        """Test that API dictionaries are properly initialized"""
        self.assertIsInstance(self.api, dict)
        self.assertIsInstance(self.api_locks, dict)
        self.assertIsInstance(self.api_nonblock, dict)
        self.assertIsInstance(self.api_docs, dict)
        self.assertIsInstance(self.api_docs_missing, list)

    def test_run_async_decorator(self):
        """Test run_async decorator creates thread for function execution"""
        test_called = False
        
        @self.run_async
        def test_function():
            nonlocal test_called
            test_called = True
        
        # Start the async function
        test_function()
        
        # Wait a bit for thread to execute
        import time
        time.sleep(0.1)
        
        self.assertTrue(test_called)

    @patch('couchpotato.api.log')
    def test_run_handler_success(self, mock_log):
        """Test run_handler with successful API call"""
        test_result = {'success': True, 'data': 'test'}
        
        def test_api_function(**kwargs):
            return test_result
        
        self.api['test.route'] = test_api_function
        
        callback_called = False
        callback_result = None
        callback_route = None
        
        def test_callback(result, route):
            nonlocal callback_called, callback_result, callback_route
            callback_called = True
            callback_result = result
            callback_route = route
        
        # Run the handler
        self.run_handler('test.route', {'param': 'value'}, test_callback)
        
        # Wait for thread to complete
        import time
        time.sleep(0.1)
        
        self.assertTrue(callback_called)
        self.assertEqual(callback_result, test_result)
        self.assertEqual(callback_route, 'test.route')

    @patch('couchpotato.api.log')
    def test_run_handler_exception(self, mock_log):
        """Test run_handler with exception in API function"""
        def failing_api_function(**kwargs):
            raise Exception("Test error")
        
        self.api['failing.route'] = failing_api_function
        
        callback_called = False
        callback_result = None
        
        def test_callback(result, route):
            nonlocal callback_called, callback_result
            callback_called = True
            callback_result = result
        
        # Run the handler
        self.run_handler('failing.route', {}, test_callback)
        
        # Wait for thread to complete
        import time
        time.sleep(0.1)
        
        self.assertTrue(callback_called)
        self.assertEqual(callback_result, {'success': False, 'error': 'Failed returning results'})
        mock_log.error.assert_called_once()

    def test_add_non_block_api_view(self):
        """Test addNonBlockApiView adds non-blocking API routes"""
        test_func_tuple = (lambda: None, lambda: None)
        test_route = 'test.nonblock'
        test_docs = 'Test documentation'
        
        self.addNonBlockApiView(test_route, test_func_tuple, test_docs)
        
        self.assertIn(test_route, self.api_nonblock)
        self.assertEqual(self.api_nonblock[test_route], test_func_tuple)
        self.assertIn(test_route, self.api_docs)
        self.assertEqual(self.api_docs[test_route], test_docs)

    def test_add_non_block_api_view_no_docs(self):
        """Test addNonBlockApiView without documentation"""
        test_func_tuple = (lambda: None, lambda: None)
        test_route = 'test.nonblock.nodocs'
        
        self.addNonBlockApiView(test_route, test_func_tuple)
        
        self.assertIn(test_route, self.api_nonblock)
        self.assertIn(test_route, self.api_docs_missing)

    def test_add_non_block_api_view_with_api_prefix(self):
        """Test addNonBlockApiView with api. prefix"""
        test_func_tuple = (lambda: None, lambda: None)
        test_route = 'api.test.prefix'
        test_docs = 'Test documentation'
        
        self.addNonBlockApiView(test_route, test_func_tuple, test_docs)
        
        self.assertIn(test_route, self.api_nonblock)
        self.assertIn('test.prefix', self.api_docs)
        self.assertEqual(self.api_docs['test.prefix'], test_docs)

    def test_add_api_view(self):
        """Test addApiView adds blocking API routes"""
        def test_api_function(**kwargs):
            return {'success': True}
        
        test_route = 'test.api'
        test_docs = 'Test API documentation'
        
        self.addApiView(test_route, test_api_function, docs=test_docs)
        
        self.assertIn(test_route, self.api)
        self.assertEqual(self.api[test_route], test_api_function)
        self.assertIn(test_route, self.api_locks)
        self.assertIsInstance(self.api_locks[test_route], threading.Lock)
        self.assertIn(test_route, self.api_docs)
        self.assertEqual(self.api_docs[test_route], test_docs)

    def test_add_api_view_no_docs(self):
        """Test addApiView without documentation"""
        def test_api_function(**kwargs):
            return {'success': True}
        
        test_route = 'test.api.nodocs'
        
        self.addApiView(test_route, test_api_function)
        
        self.assertIn(test_route, self.api)
        self.assertIn(test_route, self.api_docs_missing)

    def test_add_api_view_static(self):
        """Test addApiView with static flag"""
        test_called = False
        
        def test_static_function(route):
            nonlocal test_called
            test_called = True
        
        test_route = 'test.static'
        
        self.addApiView(test_route, test_static_function, static=True)
        
        self.assertTrue(test_called)
        self.assertNotIn(test_route, self.api)

    def test_add_api_view_with_api_prefix(self):
        """Test addApiView with api. prefix"""
        def test_api_function(**kwargs):
            return {'success': True}
        
        test_route = 'api.test.prefix'
        test_docs = 'Test documentation'
        
        self.addApiView(test_route, test_api_function, docs=test_docs)
        
        self.assertIn(test_route, self.api)
        self.assertIn('test.prefix', self.api_docs)
        self.assertEqual(self.api_docs['test.prefix'], test_docs)

    def test_non_block_handler_get(self):
        """Test NonBlockHandler GET method"""
        start_called = False
        stop_called = False
        
        def test_start(callback, last_id=None):
            nonlocal start_called
            start_called = True
            callback("test response")
        
        def test_stop(callback):
            nonlocal stop_called
            stop_called = True
        
        test_func_tuple = (test_start, test_stop)
        test_route = 'test.nonblock'
        self.api_nonblock[test_route] = test_func_tuple
        
        handler = self.NonBlockHandler()
        handler.get_argument = Mock(return_value=None)
        handler.finish = Mock()
        handler.request.connection.stream.closed = Mock(return_value=False)
        
        handler.get(test_route)
        
        self.assertTrue(start_called)
        handler.finish.assert_called_with("test response")

    def test_non_block_handler_send_data_stream_closed(self):
        """Test NonBlockHandler sendData when stream is closed"""
        handler = self.NonBlockHandler()
        handler.request.connection.stream.closed = Mock(return_value=True)
        handler.finish = Mock()
        handler.removeStopper = Mock()
        
        handler.sendData("test response")
        
        handler.finish.assert_not_called()
        handler.removeStopper.assert_called_once()

    def test_non_block_handler_send_data_exception(self):
        """Test NonBlockHandler sendData with exception"""
        handler = self.NonBlockHandler()
        handler.request.connection.stream.closed = Mock(return_value=False)
        handler.finish = Mock(side_effect=Exception("Test error"))
        handler.removeStopper = Mock()
        
        with patch('couchpotato.api.log') as mock_log:
            handler.sendData("test response")
            
            mock_log.debug.assert_called_once()
            handler.removeStopper.assert_called_once()

    def test_non_block_handler_remove_stopper(self):
        """Test NonBlockHandler removeStopper method"""
        stop_called = False
        
        def test_stop(callback):
            nonlocal stop_called
            stop_called = True
        
        handler = self.NonBlockHandler()
        handler.stopper = test_stop
        
        handler.removeStopper()
        
        self.assertTrue(stop_called)
        self.assertIsNone(handler.stopper)

    def test_api_handler_get_existing_route(self):
        """Test ApiHandler GET with existing route"""
        def test_api_function(**kwargs):
            return {'success': True, 'data': 'test'}
        
        test_route = 'test.api'
        self.api[test_route] = test_api_function
        self.api_locks[test_route] = threading.Lock()
        
        handler = self.ApiHandler()
        handler.route = test_route
        handler.request.arguments = {'param': ['value']}
        handler.get_argument = Mock(return_value='value')
        handler.write = Mock()
        handler.finish = Mock()
        handler.taskFinished = Mock()
        
        with patch('couchpotato.api.getParams') as mock_get_params:
            mock_get_params.return_value = {'param': 'value', '_request': handler}
            
            handler.get(test_route)
            
            # Wait for async execution
            import time
            time.sleep(0.1)
            
            handler.taskFinished.assert_called_once()

    def test_api_handler_get_missing_route(self):
        """Test ApiHandler GET with missing route"""
        test_route = 'missing.api'
        
        handler = self.ApiHandler()
        handler.write = Mock()
        handler.finish = Mock()
        
        handler.get(test_route)
        
        handler.write.assert_called_with('API call doesn\'t seem to exist')
        handler.finish.assert_called_once()

    def test_api_handler_get_exception(self):
        """Test ApiHandler GET with exception"""
        def failing_api_function(**kwargs):
            raise Exception("Test error")
        
        test_route = 'failing.api'
        self.api[test_route] = failing_api_function
        self.api_locks[test_route] = threading.Lock()
        
        handler = self.ApiHandler()
        handler.route = test_route
        handler.request.arguments = {}
        handler.get_argument = Mock(side_effect=Exception("Test error"))
        handler.write = Mock()
        handler.finish = Mock()
        handler.unlock = Mock()
        
        with patch('couchpotato.api.log') as mock_log:
            handler.get(test_route)
            
            mock_log.error.assert_called()
            handler.write.assert_called_with({'success': False, 'error': 'Failed returning results'})
            handler.finish.assert_called_once()
            handler.unlock.assert_called_once()

    def test_api_handler_post(self):
        """Test ApiHandler POST method calls GET"""
        handler = self.ApiHandler()
        handler.get = Mock()
        
        handler.post('test.route')
        
        handler.get.assert_called_with('test.route')

    def test_api_handler_task_finished(self):
        """Test ApiHandler taskFinished method"""
        handler = self.ApiHandler()
        handler.sendData = Mock()
        handler.unlock = Mock()
        
        test_result = {'success': True}
        test_route = 'test.api'
        
        with patch('couchpotato.api.IOLoop') as mock_ioloop:
            mock_loop = Mock()
            mock_ioloop.current.return_value = mock_loop
            
            handler.taskFinished(test_result, test_route)
            
            mock_loop.add_callback.assert_called_with(handler.sendData, test_result, test_route)
            handler.unlock.assert_called_once()

    def test_api_handler_send_data_jsonp(self):
        """Test ApiHandler sendData with JSONP callback"""
        handler = self.ApiHandler()
        handler.get_argument = Mock(return_value='testCallback')
        handler.set_header = Mock()
        handler.finish = Mock()
        handler.request.connection.stream.closed = Mock(return_value=False)
        
        test_result = {'success': True, 'data': 'test'}
        
        handler.sendData(test_result, 'test.api')
        
        handler.set_header.assert_called_with('Content-Type', 'text/javascript')
        handler.finish.assert_called_with('testCallback(' + json.dumps(test_result) + ')')

    def test_api_handler_send_data_redirect(self):
        """Test ApiHandler sendData with redirect result"""
        handler = self.ApiHandler()
        handler.redirect = Mock()
        handler.request.connection.stream.closed = Mock(return_value=False)
        
        test_result = ('redirect', '/new/location')
        
        handler.sendData(test_result, 'test.api')
        
        handler.redirect.assert_called_with('/new/location')

    def test_api_handler_send_data_normal(self):
        """Test ApiHandler sendData with normal result"""
        handler = self.ApiHandler()
        handler.get_argument = Mock(return_value=None)
        handler.finish = Mock()
        handler.request.connection.stream.closed = Mock(return_value=False)
        
        test_result = {'success': True, 'data': 'test'}
        
        handler.sendData(test_result, 'test.api')
        
        handler.finish.assert_called_with(test_result)

    def test_api_handler_send_data_stream_closed(self):
        """Test ApiHandler sendData when stream is closed"""
        handler = self.ApiHandler()
        handler.request.connection.stream.closed = Mock(return_value=True)
        handler.finish = Mock()
        
        test_result = {'success': True}
        
        handler.sendData(test_result, 'test.api')
        
        handler.finish.assert_not_called()

    def test_api_handler_send_data_unicode_error(self):
        """Test ApiHandler sendData with UnicodeDecodeError"""
        handler = self.ApiHandler()
        handler.get_argument = Mock(return_value=None)
        handler.finish = Mock(side_effect=UnicodeDecodeError('utf-8', b'', 0, 1, 'test'))
        handler.request.connection.stream.closed = Mock(return_value=False)
        
        with patch('couchpotato.api.log') as mock_log:
            handler.sendData({'success': True}, 'test.api')
            
            mock_log.error.assert_called_once()

    def test_api_handler_send_data_general_exception(self):
        """Test ApiHandler sendData with general exception"""
        handler = self.ApiHandler()
        handler.get_argument = Mock(return_value=None)
        handler.finish = Mock(side_effect=Exception("Test error"))
        handler.request.connection.stream.closed = Mock(return_value=False)
        
        with patch('couchpotato.api.log') as mock_log:
            handler.sendData({'success': True}, 'test.api')
            
            mock_log.debug.assert_called_once()

    def test_api_handler_unlock(self):
        """Test ApiHandler unlock method"""
        handler = self.ApiHandler()
        handler.route = 'test.api'
        
        # Test with existing lock
        test_lock = threading.Lock()
        self.api_locks['test.api'] = test_lock
        
        handler.unlock()
        
        # Test with non-existent lock
        handler.route = 'missing.api'
        handler.unlock()  # Should not raise exception


if __name__ == '__main__':
    unittest.main()
