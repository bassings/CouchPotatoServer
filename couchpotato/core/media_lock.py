"""Per-key lock manager for serializing DB read-modify-write operations.

Usage:
    from couchpotato.core.media_lock import media_lock

    with media_lock(media_id):
        doc = db.get('id', media_id)
        doc['status'] = 'done'
        db.update(doc)

This prevents concurrent modifications to the same database record from
corrupting data or causing lost updates.
"""

import threading
from contextlib import contextmanager

_global_lock = threading.Lock()
_key_locks: dict[str, threading.RLock] = {}
_key_refcounts: dict[str, int] = {}


@contextmanager
def media_lock(key: str):
    """Acquire a per-key reentrant lock for the duration of the block.

    Uses reference counting to clean up locks for keys that are no longer
    in use, preventing unbounded memory growth.
    """
    with _global_lock:
        if key not in _key_locks:
            _key_locks[key] = threading.RLock()
            _key_refcounts[key] = 0
        _key_refcounts[key] += 1
        lock = _key_locks[key]

    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _global_lock:
            _key_refcounts[key] -= 1
            if _key_refcounts[key] == 0:
                del _key_locks[key]
                del _key_refcounts[key]
