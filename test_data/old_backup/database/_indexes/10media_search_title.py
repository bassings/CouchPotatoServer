# media_search_title
# TitleSearchIndex

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
from CodernityDB.tree_index import MultiTreeBasedIndex
from itertools import izip
from couchpotato.core.helpers.encoding import simplifyString

# source of classes in index.classes_code
# classes_code


# index code start

class TitleSearchIndex(MultiTreeBasedIndex):
    _version = 1

    custom_header = """from CodernityDB.tree_index import MultiTreeBasedIndex
from itertools import izip
from couchpotato.core.helpers.encoding import simplifyString"""

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super(TitleSearchIndex, self).__init__(*args, **kwargs)
        self.__l = kwargs.get('w_len', 2)

    def make_key_value(self, data):

        if data.get('_t') == 'media' and len(data.get('title', '')) > 0:

            out = set()
            title = str(simplifyString(data.get('title').lower()))
            l = self.__l
            title_split = title.split()

            for x in range(len(title_split)):
                combo = ' '.join(title_split[x:])[:32].strip()
                out.add(combo.rjust(32, '_'))
                combo_range = max(l, min(len(combo), 32))

                for cx in range(1, combo_range):
                    ccombo = combo[:-cx].strip()
                    if len(ccombo) > l:
                        out.add(ccombo.rjust(32, '_'))

            return out, None

    def make_key(self, key):
        return key.rjust(32, '_').lower()
