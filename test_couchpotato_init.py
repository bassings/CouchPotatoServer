#!/usr/bin/env python3
"""
Comprehensive tests for couchpotato/__init__.py
Tests the main application initialization, web handlers, and core functionality.
"""

import unittest
import os
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
import sys

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

class TestCouchPotatoInit(unittest.TestCase):
    """Test the main couchpotato initialization module"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_env = os.environ.copy()
        
        # Mock environment variables
        os.environ['PYTHONPATH'] = f"{os.environ.get('PYTHONPATH', '')}:./libs"
        
        # Import after setting up environment
        from couchpotato import (
            views, template_loader, BaseHandler, WebHandler, 
            addView, get_db, index, robots, manifest, 
            apiDocs, databaseManage, KeyHandler, LoginHandler, 
            LogoutHandler, page_not_found
        )
        
        self.views = views
        self.template_loader = template_loader
        self.BaseHandler = BaseHandler
        self.WebHandler = WebHandler
        self.addView = addView
        self.get_db = get_db
        self.index = index
        self.robots = robots
        self.manifest = manifest
        self.apiDocs = apiDocs
        self.databaseManage = databaseManage
        self.KeyHandler = KeyHandler
        self.LoginHandler = LoginHandler
        self.LogoutHandler = LogoutHandler
        self.page_not_found = page_not_found

    def tearDown(self):
        """Clean up test environment"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_views_initialization(self):
        """Test that views dictionary is properly initialized"""
        self.assertIsInstance(self.views, dict)
        self.assertIn('', self.views)  # Index route
        self.assertIn('robots.txt', self.views)
        self.assertIn('couchpotato.appcache', self.views)
        self.assertIn('docs', self.views)
        self.assertIn('database', self.views)

    def test_template_loader_initialization(self):
        """Test template loader is properly initialized"""
        self.assertIsNotNone(self.template_loader)
        self.assertTrue(hasattr(self.template_loader, 'load'))

    def test_add_view_function(self):
        """Test addView function adds routes correctly"""
        test_func = lambda: "test"
        test_route = "test_route"
        
        # Add a test route
        self.addView(test_route, test_func)
        
        # Verify it was added
        self.assertIn(test_route, self.views)
        self.assertEqual(self.views[test_route], test_func)
        
        # Clean up
        del self.views[test_route]

    @patch('couchpotato.Env')
    def test_get_db_function(self, mock_env):
        """Test get_db function returns database from environment"""
        mock_db = Mock()
        mock_env.get.return_value = mock_db
        
        result = self.get_db()
        
        mock_env.get.assert_called_with('db')
        self.assertEqual(result, mock_db)

    def test_index_function(self):
        """Test index function returns template"""
        with patch('couchpotato.template_loader') as mock_loader:
            mock_template = Mock()
            mock_loader.load.return_value = mock_template
            mock_template.generate.return_value = "index content"
            
            result = self.index()
            
            mock_loader.load.assert_called_with('index.html')
            mock_template.generate.assert_called_once()
            self.assertEqual(result, "index content")

    def test_robots_function(self):
        """Test robots function sets correct headers and returns content"""
        mock_handler = Mock()
        
        result = self.robots(mock_handler)
        
        mock_handler.set_header.assert_called_with('Content-Type', 'text/plain')
        self.assertIn('User-agent: *', result)
        self.assertIn('Disallow: /', result)

    @patch('couchpotato.Env')
    @patch('couchpotato.fireEvent')
    def test_manifest_function(self, mock_fire_event, mock_env):
        """Test manifest function generates correct cache manifest"""
        # Mock environment settings
        mock_env.get.side_effect = lambda key: {
            'web_base': '/',
            'static_path': '/static/',
            'app_dir': '/app',
            'dev': False
        }.get(key, None)
        mock_env.setting.return_value = False  # dark_theme setting
        
        # Mock fireEvent responses
        mock_fire_event.side_effect = lambda event, single: {
            'clientscript.get_styles': ['/css/style.css'],
            'clientscript.get_scripts': ['/js/app.js']
        }.get(event, [])
        
        mock_handler = Mock()
        
        with patch('os.path.join') as mock_join, \
             patch('os.walk') as mock_walk, \
             patch('os.path.getmtime') as mock_mtime:
            
            mock_join.return_value = '/app/couchpotato/static/fonts'
            mock_walk.return_value = [('/fonts', [], ['font.woff'])]
            mock_mtime.return_value = 123456789
            
            result = self.manifest(mock_handler)
            
            mock_handler.set_header.assert_called_with('Content-Type', 'text/cache-manifest')
            self.assertIn('CACHE MANIFEST', result)
            self.assertIn('CACHE:', result)
            self.assertIn('NETWORK:', result)
            self.assertIn('*', result)

    @patch('couchpotato.Env')
    @patch('couchpotato.api')
    @patch('couchpotato.api_docs')
    @patch('couchpotato.api_docs_missing')
    def test_api_docs_function(self, mock_api_docs_missing, mock_api_docs, mock_api, mock_env):
        """Test apiDocs function generates API documentation"""
        # Mock API structure
        mock_api.keys.return_value = ['test.api', 'another.api']
        mock_api_docs.get.return_value = True
        
        with patch('couchpotato.template_loader') as mock_loader:
            mock_template = Mock()
            mock_loader.load.return_value = mock_template
            mock_template.generate.return_value = "api docs content"
            
            result = self.apiDocs()
            
            mock_loader.load.assert_called_with('api.html')
            mock_template.generate.assert_called_once()
            self.assertEqual(result, "api docs content")

    def test_database_manage_function(self):
        """Test databaseManage function returns database template"""
        with patch('couchpotato.template_loader') as mock_loader:
            mock_template = Mock()
            mock_loader.load.return_value = mock_template
            mock_template.generate.return_value = "database content"
            
            result = self.databaseManage()
            
            mock_loader.load.assert_called_with('database.html')
            mock_template.generate.assert_called_once()
            self.assertEqual(result, "database content")

    @patch('couchpotato.Env')
    @patch('couchpotato.md5')
    def test_key_handler_success(self, mock_md5, mock_env):
        """Test KeyHandler with successful authentication"""
        mock_env.setting.side_effect = lambda key: {
            'username': 'testuser',
            'password': 'testpass',
            'api_key': 'test_api_key'
        }.get(key, None)
        
        mock_md5.return_value = 'hashed_username'
        
        handler = self.KeyHandler()
        handler.get_argument = Mock(side_effect=lambda key: {
            'u': 'hashed_username',
            'p': 'testpass'
        }.get(key, ''))
        handler.write = Mock()
        
        handler.get()
        
        handler.write.assert_called_with({
            'success': True,
            'api_key': 'test_api_key'
        })

    @patch('couchpotato.Env')
    def test_key_handler_failure(self, mock_env):
        """Test KeyHandler with failed authentication"""
        mock_env.setting.side_effect = lambda key: {
            'username': 'testuser',
            'password': 'testpass',
            'api_key': 'test_api_key'
        }.get(key, None)
        
        handler = self.KeyHandler()
        handler.get_argument = Mock(side_effect=lambda key: {
            'u': 'wrong_hash',
            'p': 'wrong_pass'
        }.get(key, ''))
        handler.write = Mock()
        
        handler.get()
        
        handler.write.assert_called_with({
            'success': False,
            'api_key': None
        })

    @patch('couchpotato.Env')
    def test_login_handler_get_authenticated(self, mock_env):
        """Test LoginHandler GET when user is already authenticated"""
        mock_env.get.return_value = '/'
        
        handler = self.LoginHandler()
        handler.get_current_user = Mock(return_value=True)
        handler.redirect = Mock()
        
        handler.get()
        
        handler.redirect.assert_called_with('/')

    @patch('couchpotato.Env')
    def test_login_handler_get_not_authenticated(self, mock_env):
        """Test LoginHandler GET when user is not authenticated"""
        mock_env.get.return_value = '/'
        
        with patch('couchpotato.template_loader') as mock_loader:
            mock_template = Mock()
            mock_loader.load.return_value = mock_template
            mock_template.generate.return_value = "login form"
            
            handler = self.LoginHandler()
            handler.get_current_user = Mock(return_value=False)
            handler.write = Mock()
            
            handler.get()
            
            mock_loader.load.assert_called_with('login.html')
            handler.write.assert_called_with("login form")

    @patch('couchpotato.Env')
    @patch('couchpotato.md5')
    @patch('couchpotato.tryInt')
    def test_login_handler_post_success(self, mock_try_int, mock_md5, mock_env):
        """Test LoginHandler POST with successful login"""
        mock_env.setting.side_effect = lambda key: {
            'username': 'testuser',
            'password': 'hashed_password',
            'api_key': 'test_api_key'
        }.get(key, None)
        mock_env.get.return_value = '/'
        
        mock_md5.return_value = 'hashed_password'
        mock_try_int.return_value = 1
        
        handler = self.LoginHandler()
        handler.get_argument = Mock(side_effect=lambda key, default=None: {
            'username': 'testuser',
            'password': 'testpass',
            'remember_me': '1'
        }.get(key, default))
        handler.set_secure_cookie = Mock()
        handler.redirect = Mock()
        
        handler.post()
        
        handler.set_secure_cookie.assert_called_with('user', 'test_api_key', expires_days=30)
        handler.redirect.assert_called_with('/')

    @patch('couchpotato.Env')
    def test_logout_handler(self, mock_env):
        """Test LogoutHandler clears cookie and redirects"""
        mock_env.get.return_value = '/'
        
        handler = self.LogoutHandler()
        handler.clear_cookie = Mock()
        handler.redirect = Mock()
        
        handler.get()
        
        handler.clear_cookie.assert_called_with('user')
        handler.redirect.assert_called_with('/login/')

    @patch('couchpotato.Env')
    def test_page_not_found_api_route(self, mock_env):
        """Test page_not_found with API route"""
        mock_env.get.return_value = '/'
        mock_env.get.side_effect = lambda key: {
            'web_base': '/',
            'dev': False
        }.get(key, None)
        
        mock_handler = Mock()
        mock_handler.request.uri = '/api/test'
        
        self.page_not_found(mock_handler)
        
        mock_handler.set_status.assert_called_with(404)
        mock_handler.write.assert_called_with('Wrong API key used')

    @patch('couchpotato.Env')
    @patch('couchpotato.time')
    def test_page_not_found_non_api_route(self, mock_time, mock_env):
        """Test page_not_found with non-API route"""
        mock_env.get.return_value = '/'
        mock_env.get.side_effect = lambda key: {
            'web_base': '/',
            'dev': False
        }.get(key, None)
        
        mock_handler = Mock()
        mock_handler.request.uri = '/some/other/route'
        
        self.page_not_found(mock_handler)
        
        mock_handler.redirect.assert_called_with('/#some/other/route')

    def test_base_handler_get_current_user_no_auth(self):
        """Test BaseHandler get_current_user when no username/password set"""
        with patch('couchpotato.Env') as mock_env:
            mock_env.setting.side_effect = lambda key: None
            
            handler = self.BaseHandler()
            handler.get_secure_cookie = Mock()
            
            result = handler.get_current_user()
            
            self.assertTrue(result)
            handler.get_secure_cookie.assert_not_called()

    def test_base_handler_get_current_user_with_auth(self):
        """Test BaseHandler get_current_user when username/password are set"""
        with patch('couchpotato.Env') as mock_env:
            mock_env.setting.side_effect = lambda key: 'test' if key == 'username' else 'test'
            
            handler = self.BaseHandler()
            handler.get_secure_cookie = Mock(return_value='user_cookie')
            
            result = handler.get_current_user()
            
            self.assertEqual(result, 'user_cookie')
            handler.get_secure_cookie.assert_called_with('user')

    @patch('couchpotato.views')
    def test_web_handler_get_existing_route(self, mock_views):
        """Test WebHandler GET with existing route"""
        mock_views.get.return_value = lambda handler: "test response"
        
        handler = self.WebHandler()
        handler.write = Mock()
        handler.strip = Mock(return_value='test_route')
        
        handler.get('test_route')
        
        mock_views.get.assert_called_with('test_route')
        handler.write.assert_called_with("test response")

    @patch('couchpotato.views')
    def test_web_handler_get_missing_route(self, mock_views):
        """Test WebHandler GET with missing route"""
        mock_views.get.return_value = None
        
        handler = self.WebHandler()
        handler.strip = Mock(return_value='missing_route')
        
        with patch('couchpotato.page_not_found') as mock_page_not_found:
            handler.get('missing_route')
            
            mock_page_not_found.assert_called_with(handler)

    @patch('couchpotato.views')
    def test_web_handler_get_exception(self, mock_views):
        """Test WebHandler GET with exception in view function"""
        def failing_view(handler):
            raise Exception("Test error")
        
        mock_views.get.return_value = failing_view
        
        handler = self.WebHandler()
        handler.write = Mock()
        handler.strip = Mock(return_value='failing_route')
        
        with patch('couchpotato.log') as mock_log:
            handler.get('failing_route')
            
            mock_log.error.assert_called_once()
            handler.write.assert_called_with({
                'success': False, 
                'error': 'Failed returning results'
            })


if __name__ == '__main__':
    unittest.main()
