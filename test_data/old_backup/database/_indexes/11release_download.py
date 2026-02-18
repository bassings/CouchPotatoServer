# release_download
# ReleaseDownloadIndex

# inserted automatically
import os
import marshal

import struct
import shutil

from hashlib import md5
def _to_bytes(s):
    return s.encode('utf-8') if isinstance(s, str) else s


# custom db code start
# db_custom


# custom index code start
# ind_custom


# source of classes in index.classes_code
# classes_code


# index code start

class ReleaseDownloadIndex(HashIndex):
    _version = 2

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super(ReleaseDownloadIndex, self).__init__(*args, **kwargs)

    def make_key(self, key):
        return md5(_to_bytes(key.lower())).hexdigest()

    def make_key_value(self, data):
        if data.get('_t') == 'release' and data.get('download_info') and data['download_info']['id'] and data['download_info']['downloader']:
            return md5(_to_bytes(('%s-%s' % (data['download_info']['downloader'], data['download_info']['id'])).lower())).hexdigest(), None
