#!/usr/bin/env python2
"""
CouchPotato Integration Tests

These tests validate that the web server starts correctly and all key
components are functional after a Python 2 to 3 migration.
"""

import unittest
import threading
import time
import socket
import json
from urllib2 import urlopen, Request, HTTPError, URLError
from urlparse import urljoin

from couchpotato.environment import Env
from couchpotato.runner import runCouchPotato


class TestWebServerIntegration(unittest.TestCase):
    """Integration tests for CouchPotato web server functionality"""
    
    @classmethod
    def setUpClass(cls):
        """Start CouchPotato server in a separate thread for testing"""
        cls.base_url = "http://localhost:5555"  # Use different port for testing
        cls.api_key = None
        cls.server_thread = None
        cls.server_started = False
        
        # Mock options for test server
        class MockOptions:
            def __init__(self):
                self.data_dir = '/tmp/couchpotato_test'
                self.config_file = '/tmp/couchpotato_test/settings.conf'
                self.debug = False
                self.console_log = True
                self.quiet = False
                self.daemon = False
                self.pid_file = '/tmp/couchpotato_test/test.pid'
        
        cls.options = MockOptions()
        
        # Ensure test port is available
        if cls._port_in_use(5555):
            cls.skipTest("Test port 5555 is in use")
            return
        
        # Set test environment
        Env.set('port', 5555)
        Env.set('host', '127.0.0.1')
        Env.set('username', '')
        Env.set('password', '')
        
        # Start server in background thread
        cls.server_thread = threading.Thread(
            target=cls._start_server,
            args=(cls.options,)
        )
        cls.server_thread.daemon = True
        cls.server_thread.start()
        
        # Wait for server to start
        cls._wait_for_server_start()
    
    @classmethod
    def _port_in_use(cls, port):
        """Check if port is already in use"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('127.0.0.1', port))
            sock.close()
            return False
        except socket.error:
            return True
    
    @classmethod
    def _start_server(cls, options):
        """Start CouchPotato server"""
        try:
            import os
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            runCouchPotato(options, base_path, [], 
                         data_dir='/tmp/couchpotato_test',
                         log_dir='/tmp/couchpotato_test/logs',
                         Env=Env)
        except Exception as e:
            print("Failed to start test server: %s" % e)
    
    @classmethod
    def _wait_for_server_start(cls, timeout=30):
        """Wait for server to become available"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = urlopen(cls.base_url + "/", timeout=2)
                if response.getcode() == 200:
                    cls.server_started = True
                    # Extract API key from response if possible
                    cls._extract_api_key()
                    return
            except (HTTPError, URLError, socket.error):
                pass
            time.sleep(1)
        
        raise Exception("Server failed to start within %d seconds" % timeout)
    
    @classmethod
    def _extract_api_key(cls):
        """Extract API key from the application"""
        try:
            cls.api_key = Env.setting('api_key')
        except:
            cls.api_key = None
    
    def setUp(self):
        """Set up for each test"""
        if not self.server_started:
            self.skipTest("Server not started")
    
    def test_web_server_responds(self):
        """Test that web server responds to requests"""
        response = urlopen(self.base_url + "/")
        self.assertEqual(response.getcode(), 200)
        content = response.read()
        self.assertIn("CouchPotato", content)
        self.assertIn("<!doctype html>", content)
    
    def test_web_page_title(self):
        """Test that the main page has correct title"""
        response = urlopen(self.base_url + "/")
        content = response.read()
        self.assertIn("<title>CouchPotato</title>", content)
    
    def test_static_files_accessible(self):
        """Test that static files are accessible"""
        static_urls = [
            "/static/images/icons/favicon.ico",
            "/static/scripts/",
            "/static/style/"
        ]
        
        for url in static_urls:
            try:
                response = urlopen(self.base_url + url, timeout=5)
                # Should get 200 or 403/404 (not 500 server error)
                self.assertIn(response.getcode(), [200, 403, 404])
            except HTTPError as e:
                # Static files might not exist, but should not cause server errors
                self.assertIn(e.code, [403, 404])
    
    def test_api_key_endpoint(self):
        """Test that API key endpoint works"""
        try:
            response = urlopen(self.base_url + "/getkey/")
            self.assertEqual(response.getcode(), 200)
            content = response.read()
            # Should return JSON with API key
            self.assertTrue(len(content) > 0)
        except HTTPError as e:
            # Might be protected, but should not be server error
            self.assertNotEqual(e.code, 500)
    
    def test_login_page_loads(self):
        """Test that login page loads if authentication is enabled"""
        try:
            response = urlopen(self.base_url + "/login/")
            self.assertEqual(response.getcode(), 200)
            content = response.read()
            # Should be HTML content
            self.assertIn("html", content.lower())
        except HTTPError as e:
            # Login might redirect, but should not be server error
            self.assertNotEqual(e.code, 500)
    
    def test_api_endpoints_respond(self):
        """Test that API endpoints respond correctly"""
        if not self.api_key:
            self.skipTest("No API key available")
        
        api_base = "/api/%s/" % self.api_key
        api_urls = [
            api_base,  # Should redirect to docs
            api_base + "app.available",
            api_base + "media.list"
        ]
        
        for url in api_urls:
            try:
                response = urlopen(self.base_url + url, timeout=5)
                # API should respond (200) or require authentication (401/403)
                self.assertIn(response.getcode(), [200, 302, 401, 403])
            except HTTPError as e:
                # API errors should not be server errors
                self.assertNotEqual(e.code, 500)
    
    def test_javascript_api_setup(self):
        """Test that JavaScript API setup is present in main page"""
        response = urlopen(self.base_url + "/")
        content = response.read()
        # Should contain API setup JavaScript
        self.assertIn("Api.setup", content)
        self.assertIn("api_base", content)
    
    def test_application_components_loaded(self):
        """Test that main application components are loaded"""
        response = urlopen(self.base_url + "/")
        content = response.read()
        
        # Should contain main UI elements
        expected_elements = [
            "CouchPotato",
            "api_base",
            "static",
            "domready"
        ]
        
        for element in expected_elements:
            self.assertIn(element, content)
    
    def test_server_error_handling(self):
        """Test that server handles invalid requests gracefully"""
        invalid_urls = [
            "/nonexistent/path/",
            "/api/invalid_key/",
            "/static/nonexistent.js"
        ]
        
        for url in invalid_urls:
            try:
                response = urlopen(self.base_url + url, timeout=5)
                # Should get proper HTTP error codes, not server errors
                self.assertIn(response.getcode(), [200, 302, 404])
            except HTTPError as e:
                # Should be client error (4xx) not server error (5xx)
                self.assertTrue(400 <= e.code < 500, 
                              "URL %s returned server error %d" % (url, e.code))


class TestAPIIntegration(unittest.TestCase):
    """Integration tests for CouchPotato API functionality"""
    
    def setUp(self):
        """Set up API test client"""
        self.base_url = "http://localhost:5555"
        self.api_key = getattr(TestWebServerIntegration, 'api_key', None)
        if not self.api_key:
            self.skipTest("No API key available for testing")
        
        self.api_base = "%s/api/%s/" % (self.base_url, self.api_key)
    
    def _api_request(self, endpoint, method='GET', data=None):
        """Make API request and return response"""
        url = urljoin(self.api_base, endpoint)
        
        if method == 'POST' and data:
            req = Request(url, data=json.dumps(data))
            req.add_header('Content-Type', 'application/json')
        else:
            req = Request(url)
        
        try:
            response = urlopen(req, timeout=10)
            return response.getcode(), response.read()
        except HTTPError as e:
            return e.code, e.read()
    
    def test_api_base_redirect(self):
        """Test that API base redirects to documentation"""
        code, content = self._api_request("")
        # Should redirect (302) or show docs (200)
        self.assertIn(code, [200, 302])
    
    def test_app_available_endpoint(self):
        """Test that app.available endpoint works"""
        code, content = self._api_request("app.available")
        if code == 200:
            # Should return JSON response
            try:
                data = json.loads(content)
                self.assertIsInstance(data, dict)
            except ValueError:
                self.fail("API returned invalid JSON")
    
    def test_media_list_endpoint(self):
        """Test that media.list endpoint works"""
        code, content = self._api_request("media.list")
        # Should respond with data or appropriate error
        self.assertIn(code, [200, 401, 403, 404])
        if code == 200:
            try:
                data = json.loads(content)
                self.assertIsInstance(data, dict)
            except ValueError:
                self.fail("API returned invalid JSON")


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)