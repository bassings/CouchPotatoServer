"""File type detection and filtering for the Scanner plugin."""

import os
import re

from couchpotato.core.helpers.variable import getExt
from couchpotato.core.logger import CPLog

log = CPLog(__name__)


class FileDetectorMixin:
    """Mixin providing file type detection, filtering, and size checking."""

    ignored_in_path = [
        os.path.sep + 'extracted' + os.path.sep, 'extracting', '_unpack',
        '_failed_', '_unknown_', '_exists_', '_failed_remove_',
        '_failed_rename_', '.appledouble', '.appledb', '.appledesktop',
        os.path.sep + '._', '.ds_store', 'cp.cpnfo',
        'thumbs.db', 'ehthumbs.db', 'desktop.ini',
    ]
    ignore_names = [
        'extract', 'extracting', 'extracted', 'movie', 'movies', 'film',
        'films', 'download', 'downloads', 'video_ts', 'audio_ts', 'bdmv',
        'certificate',
    ]
    ignored_extensions = ['ignore', 'lftp-pget-status']

    extensions = {
        'movie': ['mkv', 'wmv', 'avi', 'mpg', 'mpeg', 'mp4', 'm2ts', 'iso', 'img', 'mdf', 'ts', 'm4v', 'flv'],
        'movie_extra': ['mds'],
        'dvd': ['vts_*', 'vob'],
        'nfo': ['nfo', 'txt', 'tag'],
        'subtitle': ['sub', 'srt', 'ssa', 'ass'],
        'subtitle_extra': ['idx'],
        'trailer': ['mov', 'mp4', 'flv'],
    }

    file_types = {
        'subtitle': ('subtitle', 'subtitle'),
        'subtitle_extra': ('subtitle', 'subtitle_extra'),
        'trailer': ('video', 'trailer'),
        'nfo': ('nfo', 'nfo'),
        'movie': ('video', 'movie'),
        'movie_extra': ('movie', 'movie_extra'),
        'backdrop': ('image', 'backdrop'),
        'poster': ('image', 'poster'),
        'thumbnail': ('image', 'thumbnail'),
        'leftover': ('leftover', 'leftover'),
    }

    file_sizes = {  # in MB
        'movie': {'min': 200},
        'trailer': {'min': 2, 'max': 199},
        'backdrop': {'min': 0, 'max': 5},
    }

    def keepFile(self, filename):
        for i in self.ignored_in_path:
            if i in filename.lower():
                log.debug('Ignored "%s" contains "%s".', filename, i)
                return False
        return True

    def isSampleFile(self, filename):
        is_sample = re.search(r'(^|[\W_])sample\d*[\W_]', filename.lower())
        if is_sample:
            log.debug('Is sample file: %s', filename)
        return is_sample

    def isDVDFile(self, file_name):
        if list(set(file_name.lower().split(os.path.sep)) & set(['video_ts', 'audio_ts'])):
            return True

        for needle in ['vts_', 'video_ts', 'audio_ts', 'bdmv', 'certificate']:
            if needle in file_name.lower():
                return True

        return False

    def filesizeBetween(self, file, file_size=None):
        if not file_size:
            file_size = []
        try:
            return file_size.get('min', 0) < self.getFileSize(file) < file_size.get('max', 100000)
        except:
            log.error('Couldn\'t get filesize of %s.', file)
        return False

    def getFileSize(self, file):
        try:
            return os.path.getsize(file) / 1024 / 1024
        except:
            return None

    def getSamples(self, files):
        return set(filter(lambda s: self.isSampleFile(s), files))

    def getMediaFiles(self, files):
        def test(s):
            return (self.filesizeBetween(s, self.file_sizes['movie'])
                    and getExt(s.lower()) in self.extensions['movie']
                    and not self.isSampleFile(s))
        return set(filter(test, files))

    def getMovieExtras(self, files):
        return set(filter(lambda s: getExt(s.lower()) in self.extensions['movie_extra'], files))

    def getDVDFiles(self, files):
        return set(filter(lambda s: self.isDVDFile(s), files))

    def getSubtitles(self, files):
        return set(filter(lambda s: getExt(s.lower()) in self.extensions['subtitle'], files))

    def getSubtitlesExtras(self, files):
        return set(filter(lambda s: getExt(s.lower()) in self.extensions['subtitle_extra'], files))

    def getNfo(self, files):
        return set(filter(lambda s: getExt(s.lower()) in self.extensions['nfo'], files))

    def getTrailers(self, files):
        def test(s):
            return (re.search(r'(^|[\W_])trailer\d*[\W_]', s.lower())
                    and self.filesizeBetween(s, self.file_sizes['trailer']))
        return set(filter(test, files))

    def getImages(self, files):
        def test(s):
            return getExt(s.lower()) in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tbn']
        files = set(filter(test, files))

        images = {
            'backdrop': set(filter(
                lambda s: (re.search(r'(^|[\W_])fanart|backdrop\d*[\W_]', s.lower())
                           and self.filesizeBetween(s, self.file_sizes['backdrop'])),
                files,
            ))
        }
        images['rest'] = files - images['backdrop']
        return images
