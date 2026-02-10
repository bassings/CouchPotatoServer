import os.path
import time
import traceback

from couchpotato import get_db
from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.encoding import toUnicode, ss, sp
from couchpotato.core.helpers.variable import md5, getExt, isSubFolder
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.environment import Env
from fastapi.staticfiles import StaticFiles


log = CPLog(__name__)

autoload = 'FileManager'


class FileManager(Plugin):

    def __init__(self):
        addEvent('file.download', self.download)

        addApiView('file.cache/(.*)', self.showCacheFile, static = True, docs = {
            'desc': 'Return a file from the cp_data/cache directory',
            'params': {
                'filename': {'desc': 'path/filename of the wanted file'}
            },
            'return': {'type': 'file'}
        })

        fireEvent('schedule.interval', 'file.cleanup', self.cleanup, hours = 24)
        fireEvent('schedule.interval', 'file.repair_posters', self.repairPosters, hours = 12)

        addApiView('file.repair_posters', self.repairPostersView)

        addEvent('app.test', self.doSubfolderTest)

    def repairPostersView(self, **kwargs):
        repaired = self.repairPosters()
        return {'success': True, 'repaired': repaired}

    def _posterExists(self, poster_path, cache_dir):
        """Check if a poster file exists, accounting for stale path prefixes."""
        if os.path.isfile(poster_path):
            return True
        # The DB may store paths with an old data_dir prefix. Check if the
        # filename exists in the current cache directory instead.
        basename = os.path.basename(poster_path)
        return os.path.isfile(os.path.join(cache_dir, basename))

    def _fixStalePosterPath(self, poster_path, cache_dir):
        """Return the corrected path if the file exists in the current cache dir."""
        if os.path.isfile(poster_path):
            return poster_path
        basename = os.path.basename(poster_path)
        candidate = os.path.join(cache_dir, basename)
        if os.path.isfile(candidate):
            return candidate
        return None

    def repairPosters(self):
        """Check all movies for missing poster files and re-fetch them.

        Fixes two issues:
        1. Stale paths pointing to an old data_dir (updates the DB path)
        2. Genuinely missing poster files (re-fetches from TMDB)
        """
        log.info('Checking for missing poster files...')
        try:
            db = get_db()
            cache_dir = toUnicode(Env.get('cache_dir'))
            path_fixes = 0
            refetched = 0

            for media in db.all('media', with_doc = True):
                doc = media['doc']
                files = doc.get('files', {})
                posters = files.get('image_poster', [])

                if not posters:
                    # No poster at all, try to re-fetch from TMDB
                    identifier = doc.get('identifier') or doc.get('identifiers', {}).get('imdb')
                    if identifier:
                        self._refetchPoster(db, doc, identifier)
                        refetched += 1
                        time.sleep(1)  # Be kind to TMDB rate limits
                    continue

                # Check if any poster path resolves to an existing file
                if any(self._posterExists(p, cache_dir) for p in posters):
                    # File exists but path may be stale, fix it
                    new_posters = []
                    changed = False
                    for p in posters:
                        fixed = self._fixStalePosterPath(p, cache_dir)
                        if fixed and fixed != p:
                            new_posters.append(toUnicode(fixed))
                            changed = True
                        else:
                            new_posters.append(p)
                    if changed:
                        doc['files']['image_poster'] = new_posters
                        db.update(doc)
                        path_fixes += 1
                        log.info('Fixed stale poster path for: %s', doc.get('title', '?'))
                else:
                    # File genuinely missing, re-fetch
                    identifier = doc.get('identifier') or doc.get('identifiers', {}).get('imdb')
                    if identifier:
                        if self._refetchPoster(db, doc, identifier):
                            refetched += 1
                        time.sleep(1)  # Be kind to TMDB rate limits

            log.info('Poster repair complete: %d path fixes, %d re-fetched from TMDB', path_fixes, refetched)
            return path_fixes + refetched
        except Exception:
            log.error('Failed repairing posters: %s', traceback.format_exc())
            return 0

    def _refetchPoster(self, db, doc, identifier):
        """Re-fetch a poster from TMDB for the given media document."""
        try:
            info = fireEvent('movie.info', identifier = identifier, merge = True) or {}
            images = info.get('images', {})
            poster_urls = images.get('poster', [])

            for url in poster_urls:
                if url:
                    file_path = fireEvent('file.download', url = url, single = True)
                    if file_path:
                        doc.setdefault('files', {})['image_poster'] = [toUnicode(file_path)]
                        db.update(doc)
                        log.info('Re-fetched poster for: %s', doc.get('title', identifier))
                        return True
        except Exception:
            log.error('Failed re-fetching poster for %s: %s', identifier, traceback.format_exc())
        return False

    def cleanup(self):

        # Wait a bit after starting before cleanup
        log.debug('Cleaning up unused files')

        try:
            db = get_db()
            cache_dir = Env.get('cache_dir')
            medias = db.all('media', with_doc = True)

            files = []
            for media in medias:
                file_dict = media['doc'].get('files', {})
                for x in file_dict.keys():
                    files.extend(file_dict[x])

            for f in os.listdir(cache_dir):
                if os.path.splitext(f)[1] in ['.png', '.jpg', '.jpeg']:
                    file_path = os.path.join(cache_dir, f)
                    if toUnicode(file_path) not in files:
                        os.remove(file_path)
        except Exception:
            log.error('Failed removing unused file: %s', traceback.format_exc())

    def showCacheFile(self, route, **kwargs):
        # Cache file serving is handled directly in the API catch-all route
        # (see couchpotato/__init__.py). The old StaticFiles mount conflicted
        # with FastAPI's route matching (mounts intercept GET before routes).
        pass

    def download(self, url = '', dest = None, overwrite = False, urlopen_kwargs = None):
        if not urlopen_kwargs: urlopen_kwargs = {}

        # Return response object to stream download
        urlopen_kwargs['stream'] = True

        if not dest:  # to Cache
            dest = os.path.join(toUnicode(Env.get('cache_dir')), '%s.%s' % (md5(url), getExt(url)))

        dest = sp(dest)

        if not overwrite and os.path.isfile(dest):
            return dest

        try:
            filedata = self.urlopen(url, **urlopen_kwargs)
        except Exception:
            log.error('Failed downloading file %s: %s', url, traceback.format_exc())
            return False

        self.createFile(dest, filedata, binary = True)
        return dest

    def doSubfolderTest(self):

        tests = {
            ('/test/subfolder', '/test/sub'): False,
            ('/test/sub/folder', '/test/sub'): True,
            ('/test/sub/folder', '/test/sub2'): False,
            ('/sub/fold', '/test/sub/fold'): False,
            ('/sub/fold', '/test/sub/folder'): False,
            ('/opt/couchpotato', '/var/opt/couchpotato'): False,
            ('/var/opt', '/var/opt/couchpotato'): False,
            ('/CapItaLs/Are/OK', '/CapItaLs/Are/OK'): True,
            ('/CapItaLs/Are/OK', '/CapItaLs/Are/OK2'): False,
            ('/capitals/are/not/OK', '/capitals/are/NOT'): False,
            ('\\\\Mounted\\Volume\\Test', '\\\\Mounted\\Volume'): True,
            ('C:\\\\test\\path', 'C:\\\\test2'): False
        }

        failed = 0
        for x in tests:
            if isSubFolder(x[0], x[1]) is not tests[x]:
                log.error('Failed subfolder test %s %s', x)
                failed += 1

        if failed > 0:
            log.error('Subfolder test failed %s tests', failed)
        else:
            log.info('Subfolder test succeeded')

        return failed == 0
