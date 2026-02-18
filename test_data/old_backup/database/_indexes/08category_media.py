# category_media
# CategoryMediaIndex

# inserted automatically
import os
import marshal

import struct
import shutil

from hashlib import md5

# custom db code start
# db_custom


# custom index code start
# ind_custom
from CodernityDB.tree_index import TreeBasedIndex

# source of classes in index.classes_code
# classes_code


# index code start

class CategoryMediaIndex(TreeBasedIndex):
    _version = 1

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super(CategoryMediaIndex, self).__init__(*args, **kwargs)

    def make_key(self, key):
        return str(key)

    def make_key_value(self, data):
        if data.get('_t') == 'media' and data.get('category_id'):
            return str(data.get('category_id')), None
