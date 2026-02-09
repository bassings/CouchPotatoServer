from string import ascii_letters, digits
from urllib.parse import quote_plus
import os
import re
import traceback
import unicodedata

from chardet import detect
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
    try:
        # Use six for Python 2/3 compatibility
        if isinstance(original, str):
            return original
        else:
            try:
                return str(original, *args)
            except:
                try:
                    from couchpotato.environment import Env
                    return original.decode(Env.get("encoding"))
                except:
                    try:
                        detected = detect(original)
                        try:
                            if detected.get('confidence') > 0.8:
                                return original.decode(detected.get('encoding'))
                        except:
                            pass

                        return ek(original, *args)
                    except:
                        raise
    except:
        # Avoid logging recursion - print directly to avoid circular dependency
        try:
            print('WARNING: Unable to decode value "%s..."' % repr(original)[:20])
        except:
            pass
        return 'ERROR DECODING STRING'


def ss(original, *args):

    u_original = toUnicode(original, *args)
    try:
        from couchpotato.environment import Env
        return u_original.encode(Env.get('encoding'))
    except Exception as e:
        log.debug('Failed ss encoding char, force UTF8: %s', e)
        try:
            return u_original.encode(Env.get('encoding'), 'replace')
        except:
            return u_original.encode('utf-8', 'replace')


def sp(path, *args):

    # Standardise encoding, normalise case, path and strip trailing '/' or '\'
    if not path or len(path) == 0:
        return path

    # convert windows path (from remote box) to *nix path
    if os.path.sep == '/' and '\\' in path:
        path = '/' + path.replace(':', '').replace('\\', '/')

    # In Python 3, we want string paths, not bytes
    path = os.path.normpath(toUnicode(path, *args))

    # Remove any trailing path separators
    if path != os.path.sep:
        path = path.rstrip(os.path.sep)

    # Add a trailing separator in case it is a root folder on windows (crashes guessit)
    if len(path) == 2 and path[1] == ':':
        path = path + os.path.sep

    # Replace *NIX ambiguous '//' at the beginning of a path with '/' (crashes guessit)
    path = re.sub('^//', '/', path)

    return path


def ek(original, *args):
    if isinstance(original, (str, unicode)):
        try:
            from couchpotato.environment import Env
            return original.decode(Env.get('encoding'), 'ignore')
        except UnicodeDecodeError:
            raise

    return original


def isInt(value):
    try:
        int(value)
        return True
    except ValueError:
        return False


def stripAccents(s):
    return ''.join((c for c in unicodedata.normalize('NFD', toUnicode(s)) if unicodedata.category(c) != 'Mn'))


def tryUrlencode(s):
    new = ''
    if isinstance(s, dict):
        for key, value in s.items():
            new += '&%s=%s' % (key, tryUrlencode(value))

        return new[1:]
    else:
        # ``ss`` returns bytes which results in integers when iterating in
        # Python 3. Iterate over the unicode string instead.
        for letter in toUnicode(s):
            try:
                new += quote_plus(letter)
            except Exception:
                new += letter

    return new
