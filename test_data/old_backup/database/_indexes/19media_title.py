# media_title
# TitleIndex

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

class TitleIndex(TreeBasedIndex):
    _version = 4

    custom_header = """from CodernityDB.tree_index import TreeBasedIndex
from string import ascii_letters
from couchpotato.core.helpers.encoding import toUnicode, simplifyString"""

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super(TitleIndex, self).__init__(*args, **kwargs)

    def make_key(self, key):
        return self.simplify(key)

    def make_key_value(self, data):
        if data.get('_t') == 'media' and data.get('title') is not None and len(data.get('title')) > 0:
            return self.simplify(data['title']), None

    def simplify(self, title):

        title = toUnicode(title)

        nr_prefix = '' if title and len(title) > 0 and title[0] in ascii_letters else '#'
        title = simplifyString(title)

        for prefix in ['the ', 'an ', 'a ']:
            if prefix == title[:len(prefix)]:
                title = title[len(prefix):]
                break

        return str(nr_prefix + title).ljust(32, ' ')[:32]
