"""Lightweight SQLite-backed cache replacing diskcache.

Stores values as JSON instead of pickle to avoid CVE-2025-69872
(arbitrary code execution via unsafe deserialization).

API mirrors the subset of diskcache.Cache used by CouchPotato:
  cache.get(key)            -> value or None
  cache.set(key, value, expire=seconds)
  cache.delete(key)
  cache.clear()
  cache.close()
"""

import json
import logging
import os
import sqlite3
import threading
import time

log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cache (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expiry REAL
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache (expiry)
"""


class SQLiteCache:
    """Thread-safe, JSON-serialised SQLite cache with TTL support."""

    def __init__(self, directory, eviction_interval=300):
        os.makedirs(directory, exist_ok=True)
        self._db_path = os.path.join(directory, 'cache.db')
        self._local = threading.local()
        self._eviction_interval = eviction_interval
        self._last_eviction = 0.0
        self._lock = threading.Lock()

        # Initialise schema on the creating thread
        conn = self._conn()
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_INDEX)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.commit()

    def _conn(self):
        """Return a per-thread SQLite connection."""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute('PRAGMA journal_mode=WAL')
            self._local.conn = conn
        return conn

    def get(self, key, default=None):
        """Retrieve a cached value. Returns *default* if missing or expired."""
        self._maybe_evict()
        try:
            row = self._conn().execute(
                'SELECT value, expiry FROM cache WHERE key = ?', (key,)
            ).fetchone()
        except sqlite3.OperationalError:
            return default

        if row is None:
            return default

        value_json, expiry = row
        if expiry is not None and time.time() > expiry:
            # Expired — lazily remove
            self.delete(key)
            return default

        try:
            return json.loads(value_json)
        except (json.JSONDecodeError, TypeError):
            log.warning('Cache: corrupt entry for key %s, removing', key)
            self.delete(key)
            return default

    def set(self, key, value, expire=None):
        """Store a value. *expire* is TTL in seconds (None = no expiry)."""
        expiry = (time.time() + expire) if expire else None
        try:
            value_json = json.dumps(value)
        except (TypeError, ValueError):
            log.debug('Cache: cannot serialise value for key %s, skipping', key)
            return
        conn = self._conn()
        conn.execute(
            'INSERT OR REPLACE INTO cache (key, value, expiry) VALUES (?, ?, ?)',
            (key, value_json, expiry),
        )
        conn.commit()

    def delete(self, key):
        """Remove a single key."""
        conn = self._conn()
        conn.execute('DELETE FROM cache WHERE key = ?', (key,))
        conn.commit()

    def clear(self):
        """Remove all entries."""
        conn = self._conn()
        conn.execute('DELETE FROM cache')
        conn.commit()

    def close(self):
        """Close the current thread's connection."""
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _maybe_evict(self):
        """Periodically purge expired entries to keep the DB tidy."""
        now = time.time()
        if now - self._last_eviction < self._eviction_interval:
            return
        with self._lock:
            if now - self._last_eviction < self._eviction_interval:
                return
            self._last_eviction = now
        try:
            conn = self._conn()
            cursor = conn.execute(
                'DELETE FROM cache WHERE expiry IS NOT NULL AND expiry < ?', (now,)
            )
            if cursor.rowcount > 0:
                log.debug('Cache: evicted %d expired entries', cursor.rowcount)
            conn.commit()
        except sqlite3.OperationalError:
            pass

    def __del__(self):
        self.close()
