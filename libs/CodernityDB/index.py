#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2011-2013 Codernity (http://codernity.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import marshal

import struct
import shutil

from CodernityDB.storage import IU_Storage, DummyStorage


def _compat_marshal_loads(data):
    """Load marshal data, with fallback for Python 2 marshal format.
    
    Python 2 marshal uses type codes like 't' (TYPE_INTERNED) and 'R'
    (TYPE_STRINGREF) that Python 3's marshal doesn't understand.
    Falls back to a minimal Python 2 marshal parser for these cases.
    """
    try:
        return marshal.loads(data)
    except (ValueError, TypeError):
        return _parse_py2_marshal(data)[0]


def _parse_py2_marshal(data, pos=0):
    """Minimal Python 2 marshal parser for index property dicts."""
    interned_strings = []
    
    def _read(data, pos):
        code = data[pos]
        pos += 1
        
        if code == 0x7b:  # '{' TYPE_DICT
            result = {}
            while data[pos] != 0x30:  # '0' TYPE_NULL = end of dict
                key, pos = _read(data, pos)
                val, pos = _read(data, pos)
                if isinstance(key, bytes):
                    key = key.decode('utf-8', errors='replace')
                result[key] = val
            pos += 1  # skip TYPE_NULL
            return result, pos
        
        elif code == 0x74:  # 't' TYPE_INTERNED (Py2)
            length = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            s = data[pos:pos + length]
            pos += length
            interned_strings.append(s)
            return s, pos
        
        elif code == 0x73:  # 's' TYPE_STRING
            length = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            s = data[pos:pos + length]
            pos += length
            return s, pos
        
        elif code == 0x75:  # 'u' TYPE_UNICODE
            length = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            s = data[pos:pos + length].decode('utf-8', errors='replace')
            pos += length
            return s, pos
        
        elif code == 0x52:  # 'R' TYPE_STRINGREF
            idx = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            return interned_strings[idx], pos
        
        elif code == 0x69:  # 'i' TYPE_INT
            val = struct.unpack_from('<i', data, pos)[0]
            pos += 4
            return val, pos
        
        elif code == 0x4e:  # 'N' TYPE_NONE
            return None, pos
        
        elif code == 0x54:  # 'T' TYPE_TRUE
            return True, pos
        
        elif code == 0x46:  # 'F' TYPE_FALSE
            return False, pos
        
        elif code == 0x5b:  # '[' TYPE_LIST
            length = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            result = []
            for _ in range(length):
                val, pos = _read(data, pos)
                result.append(val)
            return result, pos
        
        elif code == 0x28:  # '(' TYPE_TUPLE (small)
            length = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            result = []
            for _ in range(length):
                val, pos = _read(data, pos)
                result.append(val)
            return tuple(result), pos
        
        elif code == 0x29:  # ')' TYPE_SMALL_TUPLE
            length = data[pos]
            pos += 1
            result = []
            for _ in range(length):
                val, pos = _read(data, pos)
                result.append(val)
            return tuple(result), pos
        
        elif code == 0x67:  # 'g' TYPE_BINARY_FLOAT (8 bytes IEEE 754)
            val = struct.unpack_from('<d', data, pos)[0]
            pos += 8
            return val, pos
        
        elif code == 0x66:  # 'f' TYPE_FLOAT (ASCII text representation)
            length = data[pos]
            pos += 1
            s = data[pos:pos + length]
            pos += length
            return float(s), pos
        
        elif code == 0x6c:  # 'l' TYPE_LONG
            ndigits = struct.unpack_from('<i', data, pos)[0]
            pos += 4
            if ndigits == 0:
                return 0, pos
            negative = ndigits < 0
            ndigits = abs(ndigits)
            result = 0
            for i in range(ndigits):
                digit = struct.unpack_from('<H', data, pos)[0]
                pos += 2
                result |= digit << (i * 15)
            if negative:
                result = -result
            return result, pos
        
        elif code == 0x30:  # '0' TYPE_NULL (shouldn't appear standalone)
            return None, pos
        
        elif code == 0xfb:  # Py3 small dict
            # This shouldn't happen in Py2 data, but handle it
            return marshal.loads(data[pos - 1:]), len(data)

        elif code == 0xe9:  # Py3 TYPE_INT (long form)
            val = struct.unpack_from('<i', data, pos)[0]
            pos += 4
            return val, pos
        
        else:
            raise ValueError(
                "Unsupported Python 2 marshal type code: 0x%02x at pos %d" % (code, pos - 1))
    
    return _read(data, pos)

try:
    from CodernityDB import __version__
except ImportError:
    from __init__ import __version__


import io


class IndexException(Exception):
    pass


class IndexNotFoundException(IndexException):
    pass


class ReindexException(IndexException):
    pass


class TryReindexException(ReindexException):
    pass


class ElemNotFound(IndexException):
    pass


class DocIdNotFound(ElemNotFound):
    pass


class IndexConflict(IndexException):
    pass


class IndexPreconditionsException(IndexException):
    pass


class Index(object):

    __version__ = __version__

    custom_header = ""  # : use it for imports required by your index

    def __init__(self,
                 db_path,
                 name):
        self.name = name
        self._start_ind = 500
        self.db_path = db_path

    def open_index(self):
        if not os.path.isfile(os.path.join(self.db_path, self.name + '_buck')):
            raise IndexException("Doesn't exists")
        self.buckets = io.open(
            os.path.join(self.db_path, self.name + "_buck"), 'r+b', buffering=0)
        self._fix_params()
        self._open_storage()

    def _close(self):
        self.buckets.close()
        self.storage.close()

    def close_index(self):
        self.flush()
        self.fsync()
        self._close()

    def create_index(self):
        raise NotImplementedError()

    def _fix_params(self):
        self.buckets.seek(0)
        props = _compat_marshal_loads(self.buckets.read(self._start_ind))
        for k, v in props.items():  # Python 3 compatible
            # Decode bytes values that should be strings (Python 2 marshal compat)
            if isinstance(v, bytes) and k in ('name', 'storage_class', 'key_format',
                                               'meta_format', 'pointer_format',
                                               'flag_format', 'elements_counter_format',
                                               'bucket_line_format', 'entry_line_format',
                                               'version'):
                v = v.decode('utf-8')
            self.__dict__[k] = v
        self.buckets.seek(0, 2)

    def _save_params(self, in_params={}):
        self.buckets.seek(0)
        props = _compat_marshal_loads(self.buckets.read(self._start_ind))
        props.update(in_params)
        self.buckets.seek(0)
        data = marshal.dumps(props)
        if len(data) > self._start_ind:
            raise IndexException("To big props")
        self.buckets.write(data)
        self.flush()
        self.buckets.seek(0, 2)
        self.__dict__.update(props)

    def _open_storage(self, *args, **kwargs):
        pass

    def _create_storage(self, *args, **kwargs):
        pass

    def _destroy_storage(self, *args, **kwargs):
        self.storage.destroy()

    def _find_key(self, key):
        raise NotImplementedError()

    def update(self, doc_id, key, start, size):
        raise NotImplementedError()

    def insert(self, doc_id, key, start, size):
        raise NotImplementedError()

    def get(self, key):
        raise NotImplementedError()

    def get_many(self, key, start_from=None, limit=0):
        raise NotImplementedError()

    def all(self, start_pos):
        raise NotImplementedError()

    def delete(self, key, start, size):
        raise NotImplementedError()

    def make_key_value(self, data):
        raise NotImplementedError()

    def make_key(self, data):
        raise NotImplementedError()

    def compact(self, *args, **kwargs):
        raise NotImplementedError()

    def destroy(self, *args, **kwargs):
        self._close()
        bucket_file = os.path.join(self.db_path, self.name + '_buck')
        os.unlink(bucket_file)
        self._destroy_storage()
        self._find_key.clear()

    def flush(self):
        try:
            self.buckets.flush()
            self.storage.flush()
        except:
            pass

    def fsync(self):
        try:
            os.fsync(self.buckets.fileno())
            self.storage.fsync()
        except:
            pass

    def update_with_storage(self, doc_id, key, value):
        if value:
            start, size = self.storage.insert(value)
        else:
            start = 1
            size = 0
        return self.update(doc_id, key, start, size)

    def insert_with_storage(self, doc_id, key, value):
        if value:
            start, size = self.storage.insert(value)
        else:
            start = 1
            size = 0
        return self.insert(doc_id, key, start, size)
