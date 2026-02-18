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
        # Use a function to handle nested parentheses properly
        def _wrap_md5_calls(content):
            result = []
            i = 0
            while i < len(content):
                # Look for md5(
                if content[i:i+4] == 'md5(':
                    start = i
                    i += 4
                    # Find matching closing paren, handling nesting
                    depth = 1
                    inner_start = i
                    while i < len(content) and depth > 0:
                        if content[i] == '(':
                            depth += 1
                        elif content[i] == ')':
                            depth -= 1
                        i += 1
                    inner = content[inner_start:i-1]
                    # Only wrap if no .encode() already present
                    if '.encode' in inner:
                        result.append(content[start:i])
                    else:
                        result.append('md5(_to_bytes(%s))' % inner)
                else:
                    result.append(content[i])
                    i += 1
            return ''.join(result)

        content = _wrap_md5_calls(content)

        with open(filepath, 'w') as f:
            f.write(content)
        fixed += 1

    return fixed
