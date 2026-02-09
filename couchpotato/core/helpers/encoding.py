from string import ascii_letters, digits
from urllib.parse import quote_plus
import os
import re
import unicodedata

from couchpotato.core.logger import CPLog


log = CPLog(__name__)


def toSafeString(original):
    valid_chars = "-_.() %s%s" % (ascii_letters, digits)
    cleaned_filename = unicodedata.normalize('NFKD', toUnicode(original)).encode('ASCII', 'ignore').decode('ASCII')
    valid_string = ''.join(c for c in cleaned_filename if c in valid_chars)
    return ' '.join(valid_string.split())


def simplifyString(original):
    string = stripAccents(original.lower())
    string = toSafeString(' '.join(re.split(r'\W+', string)))
    split = re.split(r'\W+|_', string.lower())
    return toUnicode(' '.join(split))


def toUnicode(original, *args):
    """Convert value to str. In Python 3, str is already unicode."""
    if isinstance(original, str):
        return original
    if isinstance(original, bytes):
        try:
            return original.decode(*args) if args else original.decode('utf-8')
        except (UnicodeDecodeError, LookupError):
            return original.decode('utf-8', 'replace')
    try:
        return str(original)
    except Exception:
        return 'ERROR DECODING STRING'


def ss(original, *args):
    """Convert to bytes (system string). Returns UTF-8 encoded bytes."""
    u_original = toUnicode(original, *args)
    return u_original.encode('utf-8', 'replace')


def sp(path, *args):
    """Standardise path encoding and normalise."""
    if not path or len(path) == 0:
        return path

    # convert windows path (from remote box) to *nix path
    if os.path.sep == '/' and '\\' in path:
        path = '/' + path.replace(':', '').replace('\\', '/')

    path = os.path.normpath(toUnicode(path, *args))

    # Remove any trailing path separators
    if path != os.path.sep:
        path = path.rstrip(os.path.sep)

    # Add a trailing separator in case it is a root folder on windows
    if len(path) == 2 and path[1] == ':':
        path = path + os.path.sep

    # Replace *NIX ambiguous '//' at the beginning of a path with '/'
    path = re.sub('^//', '/', path)

    return path


def isInt(value):
    try:
        int(value)
        return True
    except (ValueError, TypeError):
        return False


def stripAccents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', toUnicode(s)) if unicodedata.category(c) != 'Mn')


def tryUrlencode(s):
    if isinstance(s, dict):
        parts = []
        for key, value in s.items():
            parts.append('%s=%s' % (key, tryUrlencode(value)))
        return '&'.join(parts)

    return quote_plus(toUnicode(s))
