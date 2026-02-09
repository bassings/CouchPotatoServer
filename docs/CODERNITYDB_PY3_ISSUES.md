# CodernityDB Python 3 Compatibility Issues

## Overview

CodernityDB was written for Python 2. The main Python 3 incompatibilities stem from the bytes/str split and integer division changes.

## Issues Found and Fixed

### 1. `struct.pack` with `'c'` format requires bytes (all files)

**Symptom:** `struct.error: char format requires a bytes object of length 1`

In Python 2, `struct.pack('<c', 'o')` works fine. In Python 3, the `c` format requires a `bytes` object.

**Files affected:**
- `hash_index.py` — status fields in `insert()`, `update()`, `delete()` (previously fixed with encode logic)
- `tree_index.py` — status fields `'o'`, `'d'`, flag fields `'l'`, `'n'` throughout
- `storage.py` — version string in `create()`

**Fix:** Use `b'o'`, `b'd'`, `b'l'`, `b'n'` literals everywhere, or encode strings to bytes before packing.

### 2. `struct.unpack` with `'c'` format returns bytes

**Symptom:** Comparisons like `status == 'd'` always return `False`

In Python 3, `struct.unpack('<c', data)` returns `b'd'` not `'d'`.

**Files affected:**
- `hash_index.py` — `_find_key()`, `_find_key_many()`, `all()`, `_find_place()`, `_locate_key()`
- `tree_index.py` — all status comparisons (`== 'd'`, `!= 'o'`), flag comparisons (`== 'n'`, `== 'l'`)
- `database.py` — `get()` method status check, `_single_reindex_index()`
- `storage.py` — `get()` method status check

**Fix:** Compare against byte literals: `status == b'd'`, `root_flag == b'l'`, etc.

### 3. Integer division (tree_index.py)

**Symptom:** `TypeError` when using division result as index or struct count

Python 3 `/` returns float, Python 2 returns int for int operands.

**Locations:**
- `node_capacity / 2` → `node_capacity // 2` (in `_split_leaf`, `_split_node`)
- `(imin + imax) / 2` → `(imin + imax) // 2` (in binary search methods)

**Fix:** Use `//` for integer division.

### 4. `.next()` method removed (database.py, tree_index.py)

**Symptom:** `AttributeError: 'generator' object has no attribute 'next'`

**Locations:**
- `database.py` — `all()` method: `gen.next()`, `count()` method: `iter_.next()`
- `tree_index.py` — `compact()` method: `gen.next()`

**Fix:** Use `next(gen)` builtin instead.

### 5. `dict.iteritems()` removed (database.py)

**Symptom:** `AttributeError: 'dict' object has no attribute 'iteritems'`

**Location:** `database.py` `get_index_details()`

**Fix:** Use `dict.items()`.

### 6. `filter()` returns iterator (database.py)

**Symptom:** Iterator consumed or index access fails

**Location:** `database.py` `__write_index()` — `previous_index[0]` fails on filter iterator

**Fix:** Wrap with `list()`.

### 7. String multiplication for null bytes (tree_index.py)

**Symptom:** `TypeError: can't concat str to bytes`

**Locations:** All padding/blank creation like `self.node_capacity * '\x00'`

**Fix:** Use `b'\x00'` byte literal.

### 8. `basestring` removed (database.py)

**Symptom:** `NameError: name 'basestring' is not defined`

**Fix:** Already handled with `try/except` shim at top of database.py.

### 9. `marshal.loads` returns bytes for keys (index.py)

**Symptom:** Properties loaded from marshal may have bytes keys in some Python versions.

**Fix:** The `_fix_params` in `index.py` already uses `.items()` (Py3 compatible).

## Files Modified

| File | Issues Fixed |
|------|-------------|
| `hash_index.py` | Status comparisons (bytes), status literals in pack calls, `'u'` return values |
| `tree_index.py` | Status/flag comparisons (bytes), integer division, `.next()`, null byte padding, struct.pack char literals, default params |
| `database.py` | `.next()`, `.iteritems()`, `filter()` wrapping, status comparisons |
| `storage.py` | Status comparison in `get()`, version bytes in `create()` |
| `index.py` | Already Py3 compatible (`.items()` used) |

## Testing Strategy

- Unit tests in `tests/unit/test_codernitydb_compat.py` verify byte handling
- Unit tests in `tests/unit/test_tree_index_py3.py` verify tree operations
- Integration tests in `tests/integration/test_real_database.py` verify against real data
