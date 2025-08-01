from __future__ import absolute_import, division, print_function, unicode_literals
from hashlib import md5

from CodernityDB.hash_index import HashIndex


class QualityIndex(HashIndex):
    _version = 1

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super(QualityIndex, self).__init__(*args, **kwargs)

    def make_key(self, key):
        return md5(key.encode('utf-8')).hexdigest()

    def make_key_value(self, data):
        if data.get('_t') == 'quality' and data.get('identifier'):
            return md5(data.get('identifier').encode('utf-8')).hexdigest(), None
