# notification_unread
# NotificationUnreadIndex

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
import time

# source of classes in index.classes_code
# classes_code


# index code start

class NotificationUnreadIndex(TreeBasedIndex):
    _version = 1

    custom_header = """from CodernityDB.tree_index import TreeBasedIndex
import time"""

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = 'I'
        super(NotificationUnreadIndex, self).__init__(*args, **kwargs)

    def make_key(self, key):
        return key

    def make_key_value(self, data):
        if data.get('_t') == 'notification' and not data.get('read'):
            return data.get('time'), None
