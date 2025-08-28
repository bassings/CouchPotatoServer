"""Compatibility helpers for gradual Python 2 → 3 migration.

This module centralizes imports and small shims to reduce churn while
upgrading code. Keep this file minimal; prefer native Py3 once migration
completes.
"""
from __future__ import annotations

# text/bytes helpers
def to_bytes(s, encoding='utf-8', errors='strict'):
    if isinstance(s, bytes):
        return s
    if s is None:
        return b''
    return str(s).encode(encoding, errors)


def to_text(b, encoding='utf-8', errors='strict'):
    if isinstance(b, str):
        return b
    if b is None:
        return ''
    return bytes(b).decode(encoding, errors)


# renamed stdlib modules
try:  # Py2 name
    import ConfigParser as configparser  # type: ignore
except Exception:  # Py3
    import configparser  # type: ignore

try:
    from urllib import quote as url_quote  # type: ignore
except Exception:
    from urllib.parse import quote as url_quote  # type: ignore

try:
    from Queue import Queue  # type: ignore
except Exception:
    from queue import Queue  # type: ignore


def iteritems(d):
    """Safe dict items iterator that works across Py2/3 style code."""
    return getattr(d, 'items')()

