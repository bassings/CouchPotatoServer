import hashlib
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
    return list(dict.fromkeys(seq))


def flattenList(l):
    if isinstance(l, list):
        return sum(map(flattenList, l))
    else:
        return l


def md5(text):
    return hashlib.md5(ss(text)).hexdigest()


def sha1(text):
    return hashlib.sha1(text).hexdigest()


def isLocalIP(ip):
    ip = ip.lstrip('htps:/')
    regex = r'/(^127\.)|(^192\.168\.)|(^10\.)|(^172\.1[6-9]\.)|(^172\.2[0-9]\.)|(^172\.3[0-1]\.)|(^::1)$/'
    return re.search(regex, ip) is not None or 'localhost' in ip or ip[:4] == '127.'


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
        except:
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
    except: return default


def tryFloat(s):
    try:
        if isinstance(s, str):
            return float(s) if '.' in s else tryInt(s)
        else:
            return float(s)
    except: return 0


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
        except:
            try:
                return media_dict['titles'][0]
            except:
                try:
                    return media_dict['info']['titles'][0]
                except:
                    try:
                        return media_dict['media']['info']['titles'][0]
                    except:
                        log.error('Could not get title for %s', getIdentifier(media_dict))
                        return None
    except:
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


# From SABNZBD
re_password = [re.compile(r'(.+){{([^{}]+)}}$'), re.compile(r'(.+)\s+password\s*=\s*(.+)$', re.I)]


def scanForPassword(name):
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
            except:
                log.error('Couldn\'t remove %s: %s', full_path, traceback.format_exc())

        for dir_name in dirs:
            full_path = os.path.join(root, dir_name)
            if len(os.listdir(full_path)) == 0:
                try:
                    os.rmdir(full_path)
                except:
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
