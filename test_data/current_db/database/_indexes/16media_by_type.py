# media_by_type
# MediaTypeIndex

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
from CodernityDB.tree_index import TreeBasedIndex

# source of classes in index.classes_code
# classes_code


# index code start

class MediaTypeIndex(TreeBasedIndex):
    _version = 1

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super().__init__(*args, **kwargs)

    def make_key(self, key):
        return md5(key.encode('utf-8')).hexdigest()

    def make_key_value(self, data):
        if data.get('_t') == 'media' and data.get('type'):
            return md5(data.get('type').encode('utf-8')).hexdigest(), None
