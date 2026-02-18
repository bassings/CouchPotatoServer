# media_startswith
# StartsWithIndex

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
from string import ascii_letters
from couchpotato.core.helpers.encoding import toUnicode, simplifyString

# source of classes in index.classes_code
# classes_code


# index code start

class StartsWithIndex(TreeBasedIndex):
    _version = 3

    custom_header = """from CodernityDB.tree_index import TreeBasedIndex
from string import ascii_letters
from couchpotato.core.helpers.encoding import toUnicode, simplifyString"""

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '1s'
        super(StartsWithIndex, self).__init__(*args, **kwargs)

    def make_key(self, key):
        return self.first(key)

    def make_key_value(self, data):
        if data.get('_t') == 'media' and data.get('title') is not None:
            return self.first(data['title']), None

    def first(self, title):
        title = toUnicode(title)
        title = simplifyString(title)

        for prefix in ['the ', 'an ', 'a ']:
            if prefix == title[:len(prefix)]:
                title = title[len(prefix):]
                break

        return str(title[0] if title and len(title) > 0 and title[0] in ascii_letters else '#').lower()
