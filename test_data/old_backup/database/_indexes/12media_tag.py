# media_tag
# MediaTagIndex

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
from CodernityDB.tree_index import MultiTreeBasedIndex

# source of classes in index.classes_code
# classes_code


# index code start

class MediaTagIndex(MultiTreeBasedIndex):
    _version = 2

    custom_header = """from CodernityDB.tree_index import MultiTreeBasedIndex"""

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super(MediaTagIndex, self).__init__(*args, **kwargs)

    def make_key_value(self, data):
        if data.get('_t') == 'media' and data.get('tags') and len(data.get('tags', [])) > 0:

            tags = set()
            for tag in data.get('tags', []):
                tags.add(self.make_key(tag))

            return list(tags), None

    def make_key(self, key):
        return md5(_to_bytes(key)).hexdigest()
