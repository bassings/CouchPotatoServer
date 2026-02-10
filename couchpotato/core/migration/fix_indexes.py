"""
Fix CodernityDB index files for Python 3 compatibility.

Old databases created under Python 2 have md5(key) calls in their
index files which fail in Python 3 because hashlib requires bytes.
This migration rewrites affected index files to use a _to_bytes()
helper that handles both str and bytes inputs.
"""
import os
import re


_TO_BYTES_HELPER = (
    "\ndef _to_bytes(s):\n"
    "    return s.encode('utf-8') if isinstance(s, str) else s\n"
)


def fix_index_files(db_path):
    """
    Scan database index files and fix bare md5() calls that pass
    strings directly (Python 2 legacy). Returns number of files fixed.
    """
    indexes_path = os.path.join(db_path, '_indexes')
    if not os.path.isdir(indexes_path):
        return 0

    fixed = 0
    for fname in sorted(os.listdir(indexes_path)):
        if not fname.endswith('.py'):
            continue

        filepath = os.path.join(indexes_path, fname)
        with open(filepath, 'r') as f:
            content = f.read()

        if 'md5(' not in content:
            continue

        # Already migrated?
        if '_to_bytes' in content:
            continue

        # Check if any md5() call lacks .encode() — i.e. bare md5(key) or md5(data.get(...))
        bare_md5 = re.findall(r'md5\(([^)]+)\)', content)
        needs_fix = any('.encode' not in arg for arg in bare_md5)

        if not needs_fix:
            continue

        # Add _to_bytes helper after hashlib import
        content = content.replace(
            'from hashlib import md5',
            'from hashlib import md5' + _TO_BYTES_HELPER
        )

        # Wrap bare md5() calls: md5(X) -> md5(_to_bytes(X))
        def _wrap_md5(match):
            inner = match.group(1)
            if '.encode' in inner:
                return match.group(0)  # already safe
            return 'md5(_to_bytes(%s))' % inner

        content = re.sub(r'md5\(([^)]+)\)', _wrap_md5, content)

        with open(filepath, 'w') as f:
            f.write(content)
        fixed += 1

    return fixed
