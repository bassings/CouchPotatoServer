import bcrypt
import hashlib
import hmac
import os
import random
import re
import shutil
import string
import traceback
from pathlib import Path, PurePath

from couchpotato.core.helpers.encoding import simplifyString, toSafeString, ss, sp, toUnicode
from couchpotato.core.logger import CPLog


log = CPLog(__name__)
_MD5_HEX_RE = re.compile(r'^[a-f0-9]{32}$')


def fnEscape(pattern):
    return pattern.replace('[', '[[').replace(']', '[]]').replace('[[', '[[]')


def link(src, dst):
    Path(toUnicode(dst)).hardlink_to(toUnicode(src))


def symlink(src, dst):
    Path(toUnicode(dst)).symlink_to(toUnicode(src))


def getUserDir():
    return sp(str(Path.home()))


def getDownloadDir():
    return str(Path.home() / 'Downloads')


def getDataDir():
    # Windows
    if os.name == 'nt':
        return os.path.join(os.environ['APPDATA'], 'CouchPotato')

    import platform as _platform

    # OSX
    if 'darwin' in _platform.platform().lower():
        return str(Path.home() / 'Library' / 'Application Support' / 'CouchPotato')

    # FreeBSD
    import sys
    if 'freebsd' in sys.platform:
        return '/usr/local/couchpotato/data'

    # Linux
    return str(Path.home() / '.couchpotato')


def isDict(obj):
    return isinstance(obj, dict)


def mergeDicts(a, b, prepend_list = False):
    assert isDict(a), isDict(b)
    dst = a.copy()

    stack = [(dst, b)]
    while stack:
        current_dst, current_src = stack.pop()
        for key in current_src:
            if key not in current_dst:
                current_dst[key] = current_src[key]
            else:
                if isDict(current_src[key]) and isDict(current_dst[key]):
                    stack.append((current_dst[key], current_src[key]))
                elif isinstance(current_src[key], list) and isinstance(current_dst[key], list):
                    current_dst[key] = current_src[key] + current_dst[key] if prepend_list else current_dst[key] + current_src[key]
                    current_dst[key] = removeListDuplicates(current_dst[key])
                else:
                    current_dst[key] = current_src[key]
    return dst


def removeListDuplicates(seq):
    try:
        return list(dict.fromkeys(seq))
    except TypeError:
        # Fallback for unhashable items (dicts, lists)
        seen = []
        for item in seq:
            if item not in seen:
                seen.append(item)
        return seen


def flattenList(l):
    if isinstance(l, list):
        return sum(map(flattenList, l))
    else:
        return l


def md5(text):
    # MD5 used for legacy compatibility (cache keys, existing password hashes).
    # Not used for new security-sensitive operations.
    return hashlib.md5(ss(text), usedforsecurity=False).hexdigest()  # codeql[py/weak-sensitive-data-hashing]


def is_legacy_md5_hash(value):
    if not isinstance(value, str):
        return False
    return _MD5_HEX_RE.match(value) is not None


def hash_password(password):
    if password is None:
        return ''
    # bcrypt 5.0+ raises ValueError for passwords >72 bytes; truncate to
    # match the historical bcrypt behaviour (silently ignored extra bytes).
    pw = ss(password)[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode('utf-8')


def check_password(password, stored_hash):
    if not password or not stored_hash:
        return False

    password_value = toUnicode(password)
    stored_value = toUnicode(stored_hash)

    if stored_value.startswith(('$2a$', '$2b$', '$2y$')):
        try:
            # Truncate to 72 bytes to match hash_password and bcrypt 5.0+ limit
            return bcrypt.checkpw(ss(password_value)[:72], ss(stored_value))
        except Exception:
            return False

    if is_legacy_md5_hash(stored_value):
        # Legacy MD5 migration path: compare against an existing MD5 hash so
        # users can log in and have their password transparently upgraded to
        # bcrypt. MD5 is used here only to verify an already-stored legacy
        # hash, never to create one.
        #
        # This comment used to end "New passwords are always bcrypt." That was
        # FALSE from the day it was written: `_core.py`'s `md5Password`, wired
        # to `setting.save.core.password`, stored `md5(value)` for every
        # password set through the settings UI or the wizard, and bcrypt was
        # reached only by the upgrade below -- which never runs for anyone who
        # has not logged in. Fixed in `md5Password`; the sentence is corrected
        # here because it is why nobody looked. A reassuring comment the code
        # contradicts does not merely fail to help, it actively stops the next
        # reader checking.
        # lgtm[py/weak-sensitive-data-hashing]
        return (
            hmac.compare_digest(password_value, stored_value) or
            hmac.compare_digest(md5(password_value), stored_value)  # noqa: S324
        )

    return False


def sha1(text):
    # SHA1 used for legacy compatibility only, not for security-sensitive hashing.
    return hashlib.sha1(text, usedforsecurity=False).hexdigest()


def sha256(text):
    """SHA-256 hash for security-sensitive operations."""
    return hashlib.sha256(ss(text)).hexdigest()


# Fully end-anchored so a match has to be the WHOLE candidate address, not
# just a recognised prefix -- a start-only anchor let '127.0.0.1.evil.com'
# through, because '^127\.' is satisfied by the first four characters
# regardless of what follows.
_IPV4_LOCAL_RE = re.compile(
    r'^(?:'
    r'127(?:\.\d{1,3}){3}'
    r'|192\.168(?:\.\d{1,3}){2}'
    r'|10(?:\.\d{1,3}){3}'
    r'|172\.(?:1[6-9]|2[0-9]|3[0-1])(?:\.\d{1,3}){2}'
    r')$'
)

# The two forms of IPv6 loopback we recognise: shorthand and its
# uncompressed equivalent. See the comment in isLocalIP() for why only
# these two, not general IPv6 canonicalisation.
_IPV6_LOOPBACK_FORMS = ('::1', '0:0:0:0:0:0:0:1')


def isLocalIP(ip):
    """Return True if ip names a loopback or RFC 1918 private address, or
    the literal hostname 'localhost'.

    The only caller (http_client.py's failure-tracking logic, which exempts
    local hosts from being permanently disabled after repeated failures)
    passes either a bare hostname/address or 'host:port', built from
    urlparse() as f'{hostname}{":"+port if port else ""}'. urlparse()
    strips brackets from an IPv6 host, so an IPv6 URL with a port arrives
    here as e.g. '::1:9117', not '[::1]:9117'. Bracketed forms are also
    handled in case another caller passes a raw URL-style host string.
    """
    # Strip a URL scheme prefix if one is present. This used to be
    # ip.lstrip('htps:/'), but str.lstrip() takes a set of characters, not
    # a prefix, so it stripped any leading run of h/t/p/s/:/ -- which ate
    # the leading '::' off IPv6 loopback ('::1' became '1') and would have
    # truncated any plain hostname starting with h/t/p/s (e.g. 'host.local'
    # became 'ost.local'). Only http:// and https:// are stripped now.
    for prefix in ('https://', 'http://'):
        if ip.startswith(prefix):
            ip = ip[len(prefix):]
            break

    core = ip
    colon_count = core.count(':')

    if core.startswith('[') and ']' in core:
        # Bracketed IPv6 ('[addr]' or '[addr]:port'), the standard URL host
        # form. Unambiguous: the brackets delimit the address, so there is
        # no need to guess where a port might start.
        core = core[1:core.index(']')]

    elif colon_count == 1:
        # Exactly one colon is a hostname/IPv4 'host:port' shape
        # ('127.0.0.1:9117', 'localhost:9117') -- never a bare IPv6
        # address, since even the shortest valid IPv6 form ('::1') has two
        # colons. Only split off the port if what follows really is one.
        host_part, _, port_part = core.rpartition(':')
        if port_part.isdigit():
            core = host_part

    elif colon_count >= 2:
        # Bare, unbracketed, and IPv6-shaped. 'addr:port' is genuinely
        # ambiguous here: does '::1:9117' mean loopback address '::1' with
        # port 9117, or is '::1:9117' the address in its own right? This is
        # exactly the shape http_client.py's host string produces for an
        # IPv6 host with a port, since urlparse().hostname strips brackets.
        #
        # Deliberate rule: read a trailing ':<digits>' as a port ONLY if
        # stripping it leaves one of the two recognised loopback forms.
        # That resolves '::1:9117' to loopback + port (True), while
        # '2001:db8::1:9117' and '2001:db8::1' -- neither of which is a
        # loopback address before OR after stripping a trailing number --
        # are left as-is and correctly stay unmatched (False). Anything
        # else with two or more colons is used exactly as given: it
        # matches only if it IS one of the loopback forms.
        host_part, _, port_part = core.rpartition(':')
        if port_part.isdigit() and host_part in _IPV6_LOOPBACK_FORMS:
            core = host_part

    # `core == 'localhost'`, NOT `'localhost' in core`. The substring form was
    # the same defect as the start-anchored IPv4 alternatives it sat beside,
    # and closing only those left this one open: it exempted ANY hostname
    # containing the word, so `localhost.evil.com`, `evil-localhost.com` and
    # `notlocalhost.net` all read as local. A hostname is attacker-chosen, and
    # this function decides which hosts skip being disabled after repeated
    # failures, so it must match the literal name and nothing around it.
    # `core` has already had any scheme prefix and trailing `:<port>` removed
    # above, so `localhost:9117` still resolves here.
    #
    # `rstrip('.')` accepts the ABSOLUTE DNS spelling `localhost.`, which is a
    # legitimate way to name the host and which `urlparse` preserves, so
    # `http://localhost.:9117` stays exempt. Stripping only trailing dots
    # cannot widen the match: `localhost.evil.com` does not end in a dot, so
    # it is unaffected and still rejected.
    return (
        _IPV4_LOCAL_RE.match(core) is not None
        or core in _IPV6_LOOPBACK_FORMS
        or core.rstrip('.') == 'localhost'
    )


def getExt(filename):
    suffix = Path(filename).suffix
    return suffix[1:] if suffix else ''


def cleanHost(host, protocol = True, ssl = False, username = None, password = None):
    """Return a cleaned up host with given url options set

    Changes protocol to https if ssl is set to True and http if ssl is set to false.
    >>> cleanHost("localhost:80", ssl=True)
    'https://localhost:80/'
    >>> cleanHost("localhost:80", ssl=False)
    'http://localhost:80/'

    Username and password is managed with the username and password variables
    >>> cleanHost("localhost:80", username="user", password="passwd")
    'http://user:passwd@localhost:80/'

    Output without scheme (protocol) can be forced with protocol=False
    >>> cleanHost("localhost:80", protocol=False)
    'localhost:80'
    """

    if not '://' in host and protocol:
        host = ('https://' if ssl else 'http://') + host

    if not protocol:
        host = host.split('://', 1)[-1]

    if protocol and username and password:
        try:
            auth = re.findall('^(?:.+?//)(.+?):(.+?)@(?:.+)$', host)
            if auth:
                log.error('Cleanhost error: auth already defined in url: %s, please remove BasicAuth from url.', host)
            else:
                host = host.replace('://', '://%s:%s@' % (username, password), 1)
        except Exception:
            pass

    host = host.rstrip('/ ')
    if protocol:
        host += '/'

    return host


def getImdb(txt, check_inside = False, multiple = False):

    if not check_inside:
        txt = simplifyString(txt)
    else:
        txt = ss(txt)

    if check_inside and os.path.isfile(txt):
        txt = Path(txt).read_text(errors='replace')

    try:
        ids = re.findall(r'(tt\d{4,8})', txt)

        if multiple:
            return removeDuplicate(['tt%s' % str(tryInt(x[2:])).rjust(7, '0') for x in ids]) if len(ids) > 0 else []

        return 'tt%s' % str(tryInt(ids[0][2:])).rjust(7, '0')
    except IndexError:
        pass

    return False


def tryInt(s, default = 0):
    try: return int(s)
    except Exception: return default


def tryFloat(s):
    try:
        if isinstance(s, str):
            return float(s) if '.' in s else tryInt(s)
        else:
            return float(s)
    except Exception: return 0


def natsortKey(string_):
    """See http://www.codinghorror.com/blog/archives/001018.html"""
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_)]


def toIterable(value):
    try:
        iter(value)
        return value
    except TypeError:
        return [value]


def getIdentifier(media):
    return media.get('identifier') or media.get('identifiers', {}).get('imdb')


def getTitle(media_dict):
    try:
        try:
            return media_dict['title']
        except Exception:
            try:
                return media_dict['titles'][0]
            except Exception:
                try:
                    return media_dict['info']['titles'][0]
                except Exception:
                    try:
                        return media_dict['media']['info']['titles'][0]
                    except Exception:
                        log.error('Could not get title for %s', getIdentifier(media_dict))
                        return None
    except Exception:
        log.error('Could not get title for library item: %s', media_dict)
        return None


def possibleTitles(raw_title):

    titles = [
        toSafeString(raw_title).lower(),
        raw_title.lower(),
        simplifyString(raw_title)
    ]

    # replace some chars
    new_title = raw_title.replace('&', 'and')
    titles.append(simplifyString(new_title))

    return removeDuplicate(titles)


def randomString(size = 8, chars = string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for x in range(size))


def splitString(str, split_on = ',', clean = True):
    # Handle bytes from config (Python 3 compatibility)
    if isinstance(str, bytes):
        str = str.decode('utf-8', errors='replace')
    l = [x.strip() for x in str.split(split_on)] if str else []
    return removeEmpty(l) if clean else l


def removeEmpty(l):
    return list(filter(None, l))


def removeDuplicate(l):
    return list(dict.fromkeys(l))


def dictIsSubset(a, b):
    return all([k in b and b[k] == v for k, v in a.items()])


def isSubFolder(sub_folder, base_folder):
    """Returns True if sub_folder is the same as or inside base_folder"""
    if base_folder and sub_folder:
        try:
            return PurePath(os.path.realpath(sub_folder)).is_relative_to(os.path.realpath(base_folder))
        except (TypeError, ValueError):
            return False
    return False


# A legitimate release name is well under this length (ordinary names
# measured at 30-60 chars). re.findall retries from every start position,
# so parsing a run of brackets below is quadratic in input length: measured
# 124 ms for 8000 unclosed '[' and 496 ms for 16000. A provider controls
# both the length of a candidate name and how many results one search
# response contains (sceneScore() in score/main.py runs this per result),
# so this cap bounds the parse cost regardless of what the provider sends.
BRACKETED_NAME_PARSE_LIMIT = 300


def longestBracketedName(name):
    """Return the longest '[...]' bracketed group in *name*, stripped.

    Equivalent, for input at or under BRACKETED_NAME_PARSE_LIMIT, to:
        max(re.findall(r'[^[]*\\[([^]]*)\\]', name), key = len).strip()
    including raising when there is no bracketed group at all -- callers
    are expected to catch that, same as with the expression this replaces.

    Input longer than the limit is parsed from a capped prefix rather than
    rejected outright, so a merely long (not pathological) name still
    scores; only the cost of the parse is bounded, not the acceptance of
    long input.
    """
    if len(name) > BRACKETED_NAME_PARSE_LIMIT:
        name = name[:BRACKETED_NAME_PARSE_LIMIT]
    return max(re.findall(r'[^[]*\[([^]]*)\]', name), key = len).strip()


# From SABNZBD
re_password = [re.compile(r'(.+){{([^{}]+)}}$'), re.compile(r'(.+)\s+password\s*=\s*(.+)$', re.I)]


def scanForPassword(name):
    # "No name" is an ordinary answer of "no password", not an error. Without
    # this, re.search() raises TypeError on None -- and every release created
    # before v3.17.0 has an empty info dict, because createFromSearch's
    # populate loop died on the Python 2 `unicode`/`long` names before it
    # could store anything. bytes matters too: a str pattern against bytes
    # raises the same TypeError.
    if not name or not isinstance(name, str):
        return None

    m = None
    for reg in re_password:
        m = reg.search(name)
        if m: break

    if m:
        return m.group(1).strip('. '), m.group(2).strip()


under_pat = re.compile(r'_([a-z])')

def underscoreToCamel(name):
    return under_pat.sub(lambda x: x.group(1).upper(), name)


def removePyc(folder, only_excess = True, show_logs = True):

    folder = sp(folder)

    for root, dirs, files in os.walk(folder):

        pyc_files = list(filter(lambda filename: filename.endswith('.pyc'), files))
        py_files = set(filter(lambda filename: filename.endswith('.py'), files))
        excess_pyc_files = list(filter(lambda pyc_filename: pyc_filename[:-1] not in py_files, pyc_files)) if only_excess else pyc_files

        for excess_pyc_file in excess_pyc_files:
            full_path = os.path.join(root, excess_pyc_file)
            if show_logs: log.debug('Removing old PYC file: %s', full_path)
            try:
                os.remove(full_path)
            except Exception:
                log.error('Couldn\'t remove %s: %s', full_path, traceback.format_exc())

        for dir_name in dirs:
            full_path = os.path.join(root, dir_name)
            try:
                is_empty = len(os.listdir(full_path)) == 0
            except FileNotFoundError:
                # T1.7: multiple CouchPotato.py processes (one per E2E
                # worker) can walk and clean this exact tree concurrently.
                # A directory os.walk() already yielded can be removed by
                # ANOTHER process's os.rmdir() (below) between that yield
                # and this listdir() -- not a real error, just this
                # process losing the race to empty the same directory.
                continue
            if is_empty:
                try:
                    os.rmdir(full_path)
                except Exception:
                    log.error('Couldn\'t remove empty directory %s: %s', full_path, traceback.format_exc())


def getFreeSpace(directories):

    single = not isinstance(directories, (tuple, list))
    if single:
        directories = [directories]

    free_space = {}
    for folder in directories:
        size = None
        if os.path.isdir(folder):
            usage = shutil.disk_usage(folder)
            size = [usage.total / (1024 * 1024), usage.free / (1024 * 1024)]

        if single: return size

        free_space[folder] = size

    return free_space


def getSize(paths):

    single = not isinstance(paths, (tuple, list))
    if single:
        paths = [paths]

    total_size = 0
    for path in paths:
        p = Path(sp(path))

        if p.is_dir():
            total_size = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
        elif p.is_file():
            total_size += p.stat().st_size

    return total_size / 1048576  # MB


def find(func, iterable):
    for item in iterable:
        if func(item):
            return item

    return None


def compareVersions(version1, version2):
    from packaging.version import Version
    v1, v2 = Version(version1), Version(version2)
    return (v1 > v2) - (v1 < v2)
