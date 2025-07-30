#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
Simple CouchPotato Health Check

Basic validation that CouchPotato is running correctly.
"""

import unittest
import socket
import time
import sys
from urllib2 import urlopen, HTTPError, URLError


class SimpleHealthCheck(unittest.TestCase):
    """Simple health checks for running CouchPotato instance"""
    
    def setUp(self):
        """Set up health check tests"""
        self.base_url = "http://localhost:5050"
        self.timeout = 10
    
    def test_server_responds(self):
        """Test that CouchPotato server is responding"""
        try:
            response = urlopen(self.base_url + "/", timeout=self.timeout)
            self.assertEqual(response.getcode(), 200)
            print("✓ Server responds correctly")
        except Exception as e:
            self.fail("Server is not responding: %s" % e)
    
    def test_web_page_content(self):
        """Test that main web page has correct content"""
        try:
            response = urlopen(self.base_url + "/", timeout=self.timeout)
            content = response.read()
            
            # Check for essential elements
            required_elements = [
                "<!doctype html>",
                "<title>CouchPotato</title>", 
                "CouchPotato",
                "Api.setup"
            ]
            
            for element in required_elements:
                self.assertIn(element, content)
                
            print("✓ Web page loads with correct content")
                
        except Exception as e:
            self.fail("Failed to load web page: %s" % e)
    
    def test_no_server_errors(self):
        """Test that common URLs don't return server errors"""
        test_urls = [
            "/",
            "/getkey/",
            "/static/"
        ]
        
        for url in test_urls:
            try:
                response = urlopen(self.base_url + url, timeout=self.timeout)
                self.assertLess(response.getcode(), 500)
            except HTTPError as e:
                self.assertLess(e.code, 500)
            except URLError:
                self.fail("Connection error for URL: %s" % url)
        
        print("✓ No server errors on common URLs")
    
    def test_api_key_endpoint(self):
        """Test that API key endpoint works"""
        try:
            response = urlopen(self.base_url + "/getkey/", timeout=self.timeout)
            self.assertIn(response.getcode(), [200, 302])
            print("✓ API key endpoint accessible")
        except HTTPError as e:
            self.assertNotEqual(e.code, 500)
            print("✓ API key endpoint responds (code: %d)" % e.code)
    
    def test_response_time(self):
        """Test that response time is reasonable"""
        start_time = time.time()
        try:
            response = urlopen(self.base_url + "/", timeout=self.timeout)
            response_time = time.time() - start_time
            
            self.assertLess(response_time, 5.0)
            print("✓ Response time acceptable: %.2f seconds" % response_time)
            
        except Exception as e:
            self.fail("Failed to measure response time: %s" % e)


def run_health_check():
    """Run health check and return results"""
    print("Running CouchPotato Health Check...")
    print("=" * 50)
    
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(SimpleHealthCheck))
    
    runner = unittest.TextTestRunner(verbosity=0, stream=open('/dev/null', 'w'))
    result = runner.run(suite)
    
    print("=" * 50)
    if result.wasSuccessful():
        print("✓ All health checks passed!")
        print("CouchPotato is running correctly.")
        return True
    else:
        print("✗ Some health checks failed:")
        for failure in result.failures + result.errors:
            print("  - %s" % failure[0])
        return False


if __name__ == '__main__':
    success = run_health_check()
    sys.exit(0 if success else 1)