# media
# MediaIndex

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

class MediaIndex(MultiTreeBasedIndex):
    _version = 3

    custom_header = """from CodernityDB.tree_index import MultiTreeBasedIndex"""

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super().__init__(*args, **kwargs)

    def make_key(self, key):
        return md5(key.encode('utf-8')).hexdigest()

    def make_key_value(self, data):
        if data.get('_t') == 'media' and (data.get('identifier') or data.get('identifiers')):

            identifiers = data.get('identifiers', {})
            if data.get('identifier') and 'imdb' not in identifiers:
                identifiers['imdb'] = data.get('identifier')

            ids = []
            for x in identifiers:
                ids.append(md5(('%s-%s' % (x, identifiers[x])).encode('utf-8')).hexdigest())

            return ids, None
