import threading
from pathlib import Path
import os
import os.path
import time
import traceback

from couchpotato.core.event import fireEvent, addEvent
from couchpotato.core.helpers.encoding import toSafeString, \
    toUnicode, sp
from couchpotato.core.helpers.variable import md5, scanForPassword, tryInt, getIdentifier, \
    randomString
from couchpotato.core.http_client import HttpClient
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env
import requests
from jinja2 import Environment as _JinjaEnv, FileSystemLoader as _JinjaFSLoader

log = CPLog(__name__)


class Plugin:

    _class_name = None
    _database = None
    plugin_path = None

    enabled_option = 'enabled'

    _needs_shutdown = False
    _running = None

    http_time_between_calls = 0

    def __new__(cls, *args, **kwargs):
        new_plugin = super().__new__(cls)
        new_plugin.registerPlugin()

        return new_plugin

    def registerPlugin(self):
        addEvent('app.do_shutdown', self.doShutdown)
        addEvent('plugin.running', self.isRunning)
        self._running = []
        self._locks = {}
        self._http_client = None

        # Setup database
        if self._database:
            addEvent('database.setup', self.databaseSetup)

    @property
    def http_client(self):
        if self._http_client is None:
            self._http_client = HttpClient(
                time_between_calls=self.http_time_between_calls,
            )
        return self._http_client

    def databaseSetup(self):

        for index_name in self._database:
            klass = self._database[index_name]

            fireEvent('database.setup_index', index_name, klass)

    def conf(self, attr, value = None, default = None, section = None):
        class_name = self.getName().lower().split(':')[0].lower()
        return Env.setting(attr, section = section if section else class_name, value = value, default = default)

    def deleteConf(self, attr):
        return Env._settings.delete(attr, section = self.getName().lower().split(':')[0].lower())

    def getName(self):
        return self._class_name or self.__class__.__name__

    def setName(self, name):
        self._class_name = name

    def renderTemplate(self, parent_file, templ, **params):
        tmpl_dir = str(Path(parent_file).parent)
        env = _JinjaEnv(loader=_JinjaFSLoader(tmpl_dir))
        t = env.get_template(templ)
        return t.render(**params)

    def createFile(self, path, content, binary = False):
        p = Path(sp(path))

        self.makeDir(str(p.parent))

        if p.exists():
            log.debug('%s already exists, overwriting file with new version', p)

        write_type = 'w+' if not binary else 'w+b'

        # Stream file using response object
        if isinstance(content, requests.models.Response):

            # Write file to temp
            tmp_path = p.with_suffix(p.suffix + '.tmp')
            with open(str(tmp_path), write_type) as f:
                for chunk in content.iter_content(chunk_size = 1048576):
                    if chunk:  # filter out keep-alive new chunks
                        f.write(chunk)
                        f.flush()

            # Rename to destination
            tmp_path.rename(p)

        else:
            try:
                p.write_text(content) if not binary else p.write_bytes(content)

                try:
                    p.chmod(Env.getPermission('file'))
                except Exception:
                    log.error('Failed writing permission to file "%s": %s', p, traceback.format_exc())

            except Exception:
                log.error('Unable to write file "%s": %s', p, traceback.format_exc())
                if p.is_file():
                    p.unlink()

    def makeDir(self, path):
        p = Path(sp(path))
        try:
            if not p.is_dir():
                p.mkdir(parents=True, exist_ok=True)
                p.chmod(Env.getPermission('folder'))
            return True
        except Exception as e:
            log.error('Unable to create folder "%s": %s', p, e)

        return False

    def deleteEmptyFolder(self, folder, show_error = True, only_clean = None):
        folder_path = Path(sp(folder))

        for item in folder_path.iterdir():
            full_folder = Path(sp(str(item)))

            if not only_clean or (item.name in only_clean and full_folder.is_dir()):

                for subfolder, dirs, files in os.walk(str(full_folder), topdown = False):

                    try:
                        Path(subfolder).rmdir()
                    except Exception:
                        if show_error:
                            log.info2('Couldn\'t remove directory %s: %s', subfolder, traceback.format_exc())

        try:
            folder_path.rmdir()
        except Exception:
            if show_error:
                log.error('Couldn\'t remove empty directory %s: %s', folder_path, traceback.format_exc())

    # http request — delegates to HttpClient
    def urlopen(self, url, timeout=30, data=None, headers=None, files=None, show_error=True, stream=False):
        return self.http_client.request(
            url, timeout=timeout, data=data, headers=headers,
            files=files, show_error=show_error, stream=stream,
        )


    def beforeCall(self, handler):
        self.isRunning('%s.%s' % (self.getName(), handler.__name__))

    def afterCall(self, handler):
        self.isRunning('%s.%s' % (self.getName(), handler.__name__), False)

    def doShutdown(self, *args, **kwargs):
        self.shuttingDown(True)
        return True

    def shuttingDown(self, value = None):
        if value is None:
            return self._needs_shutdown

        self._needs_shutdown = value

    def isRunning(self, value = None, boolean = True):

        if value is None:
            return self._running

        if boolean:
            self._running.append(value)
        else:
            try:
                self._running.remove(value)
            except Exception:
                log.error("Something went wrong when finishing the plugin function. Could not find the 'is_running' key")

    def getCache(self, cache_key, url = None, **kwargs):

        use_cache = not len(kwargs.get('data', {})) > 0 and not kwargs.get('files')

        if use_cache:
            cache_key_md5 = md5(cache_key)
            cache = Env.get('cache').get(cache_key_md5)
            if cache:
                if not Env.get('dev'): log.debug('Getting cache %s', cache_key)
                return cache

        if url:
            try:

                cache_timeout = 300
                if 'cache_timeout' in kwargs:
                    cache_timeout = kwargs.get('cache_timeout')
                    del kwargs['cache_timeout']

                data = self.urlopen(url, **kwargs)
                if data and cache_timeout > 0 and use_cache:
                    self.setCache(cache_key, data, timeout = cache_timeout)
                return data
            except Exception:
                if not kwargs.get('show_error', True):
                    raise

                log.debug('Failed getting cache: %s', traceback.format_exc(0))
                return ''

    def setCache(self, cache_key, value, timeout = 300):
        cache_key_md5 = md5(cache_key)
        log.debug('Setting cache %s', cache_key)
        Env.get('cache').set(cache_key_md5, value, expire=timeout)
        return value

    def createNzbName(self, data, media, unique_tag = False):
        release_name = data.get('name')
        tag = self.cpTag(media, unique_tag = unique_tag)

        # Check if password is filename
        name_password = scanForPassword(data.get('name'))
        if name_password:
            release_name, password = name_password
            tag += '{{%s}}' % password
        elif data.get('password'):
            tag += '{{%s}}' % data.get('password')

        max_length = 127 - len(tag)  # Some filesystems don't support 128+ long filenames
        return '%s%s' % (toSafeString(toUnicode(release_name)[:max_length]), tag)

    def createFileName(self, data, filedata, media, unique_tag = False):
        name = self.createNzbName(data, media, unique_tag = unique_tag)
        if data.get('protocol') == 'nzb' and 'DOCTYPE nzb' not in filedata and '</nzb>' not in filedata:
            return '%s.%s' % (name, 'rar')
        return '%s.%s' % (name, data.get('protocol'))

    def cpTag(self, media, unique_tag = False):

        tag = ''
        if Env.setting('enabled', 'renamer') or unique_tag:
            identifier = getIdentifier(media) or ''
            unique_tag = ', ' + randomString() if unique_tag else ''

            tag = '.cp('
            tag += identifier
            tag += ', ' if unique_tag and identifier else ''
            tag += randomString() if unique_tag else ''
            tag += ')'

        return tag if len(tag) > 7 else ''

    def checkFilesChanged(self, files, unchanged_for = 60):
        now = time.time()
        file_too_new = False

        file_time = []
        for cur_file in files:

            # File got removed while checking
            if not os.path.isfile(cur_file):
                file_too_new = now
                break

            # File has changed in last 60 seconds
            file_time = self.getFileTimes(cur_file)
            for t in file_time:
                if t > now - unchanged_for:
                    file_too_new = tryInt(time.time() - t)
                    break

            if file_too_new:
                break

        if file_too_new:
            try:
                time_string = time.ctime(file_time[0])
            except Exception:
                try:
                    time_string = time.ctime(file_time[1])
                except Exception:
                    time_string = 'unknown'

            return file_too_new, time_string

        return False, None

    def getFileTimes(self, file_path):
        return [os.path.getmtime(file_path), os.path.getctime(file_path) if os.name != 'posix' else 0]

    def isDisabled(self):
        return not self.isEnabled()

    def isEnabled(self):
        return self.conf(self.enabled_option) or self.conf(self.enabled_option) is None

    def acquireLock(self, key):

        lock = self._locks.get(key)
        if not lock:
            self._locks[key] = threading.RLock()

        log.debug('Acquiring lock: %s', key)
        self._locks.get(key).acquire()

    def releaseLock(self, key):

        lock = self._locks.get(key)
        if lock:
            log.debug('Releasing lock: %s', key)
            self._locks.get(key).release()
