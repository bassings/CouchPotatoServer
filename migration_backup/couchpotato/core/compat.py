"""
Python 2/3 Compatibility Module for CouchPotato

This module provides compatibility functions and imports to make CouchPotato
work with both Python 2 and Python 3 during the migration process.
"""

import sys

# Python version detection
PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

if PY3:
    # Python 3 imports and compatibility
    import urllib.request
    import urllib.error
    import urllib.parse
    import configparser
    from io import StringIO
    
    # Alias for compatibility
    urllib2 = urllib.request
    urllib2.HTTPError = urllib.error.HTTPError
    urllib2.URLError = urllib.error.URLError
    ConfigParser = configparser
    
    # String types
    string_types = str
    text_type = str
    binary_type = bytes
    integer_types = int
    
    # Dictionary iteration
    def iteritems(d):
        return d.items()
    
    def iterkeys(d):
        return d.keys()
    
    def itervalues(d):
        return d.values()
    
    # Unicode handling
    def ensure_text(s, encoding='utf-8', errors='strict'):
        """Ensure that a string is a text string (unicode in Python 2, str in Python 3)"""
        if isinstance(s, binary_type):
            return s.decode(encoding, errors)
        elif isinstance(s, text_type):
            return s
        else:
            return text_type(s)
    
    def ensure_binary(s, encoding='utf-8', errors='strict'):
        """Ensure that a string is a binary string (str in Python 2, bytes in Python 3)"""
        if isinstance(s, text_type):
            return s.encode(encoding, errors)
        elif isinstance(s, binary_type):
            return s
        else:
            return text_type(s).encode(encoding, errors)
    
    # URL handling
    from urllib.parse import quote as url_quote
    from urllib.parse import unquote as url_unquote
    from urllib.parse import urlencode as url_encode
    
else:
    # Python 2 imports and compatibility
    import urllib2
    import ConfigParser
    from StringIO import StringIO
    
    # String types
    string_types = basestring
    text_type = unicode
    binary_type = str
    integer_types = (int, long)
    
    # Dictionary iteration
    def iteritems(d):
        return d.iteritems()
    
    def iterkeys(d):
        return d.iterkeys()
    
    def itervalues(d):
        return d.itervalues()
    
    # Unicode handling
    def ensure_text(s, encoding='utf-8', errors='strict'):
        """Ensure that a string is a text string (unicode in Python 2, str in Python 3)"""
        if isinstance(s, binary_type):
            return s.decode(encoding, errors)
        elif isinstance(s, text_type):
            return s
        else:
            return text_type(s)
    
    def ensure_binary(s, encoding='utf-8', errors='strict'):
        """Ensure that a string is a binary string (str in Python 2, bytes in Python 3)"""
        if isinstance(s, text_type):
            return s.encode(encoding, errors)
        elif isinstance(s, binary_type):
            return s
        else:
            return binary_type(s)
    
    # URL handling
    from urllib import quote as url_quote
    from urllib import unquote as url_unquote
    from urllib import urlencode as url_encode


# Common utility functions
def is_string(obj):
    """Check if object is a string type"""
    return isinstance(obj, string_types)

def is_text(obj):
    """Check if object is a text string type"""
    return isinstance(obj, text_type)

def is_binary(obj):
    """Check if object is a binary string type"""
    return isinstance(obj, binary_type)

def to_native_str(s):
    """Convert to native string type (str in both Python 2 and 3)"""
    if PY3:
        return ensure_text(s)
    else:
        return ensure_binary(s)


# Exception compatibility for common urllib errors
class CompatHTTPError(Exception):
    """Compatibility wrapper for HTTP errors"""
    pass

class CompatURLError(Exception):
    """Compatibility wrapper for URL errors"""
    pass

# Map exceptions for consistent handling
if PY3:
    HTTPError = urllib.error.HTTPError
    URLError = urllib.error.URLError
else:
    HTTPError = urllib2.HTTPError
    URLError = urllib2.URLError