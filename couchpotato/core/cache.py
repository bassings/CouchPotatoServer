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

import base64
import binascii
import json
import logging
import os
import sqlite3
import threading
import time

log = logging.getLogger(__name__)

# Marker key for a bytes value wrapped for JSON storage. Deliberately long and
# namespaced so it cannot collide with a real application dict that happens to
# be the value being cached -- see SQLiteCache.set / SQLiteCache.get below.
_BYTES_MARKER = '__couchpotato_cache_bytes_b64__'

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
        # M2 (branch review 2026-08-31): what actually reaches cache.set is
        # HTTP response bodies, and Torznab/Jackett responses routinely
        # embed the indexer's own API key in a <link> element. The cache
        # directory and cache.db were created at whatever mode the process
        # umask left them (0644/0755, world-readable), which turned a fix
        # for a dead store into a new, world-readable, on-disk credential
        # surface. chmod is explicit here rather than relying on umask,
        # which is process-wide and not this cache's to assume.
        #
        # T7d item 5 (round two on M2): a chmod failure is logged at
        # WARNING rather than swallowed -- on a filesystem that ignores or
        # refuses chmod, every one of these protections silently does not
        # apply, and an operator has no way to know unless something says
        # so.
        try:
            os.chmod(directory, 0o700)
        except OSError as error:
            log.warning(
                'Cache: could not chmod the cache directory %s to 0700 -- '
                'if this filesystem ignores or refuses chmod, cached files '
                'may be readable by other users: %s', directory, error,
            )
        self._directory = directory
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
        self._secure_cache_files()

    def _secure_cache_files(self):
        """Chmod every file currently in the cache directory to 0600 (M2,
        round two on T7d item 5).

        The cache runs in WAL mode (`journal_mode=WAL` above), and SQLite
        creates `cache.db-wal` and `cache.db-shm` LAZILY -- on the first
        write after WAL mode is enabled, not when the pragma is set -- so
        neither existed for a chmod call made only once, in `__init__`,
        to protect. A just-cached Torznab/Jackett response embedding the
        indexer's own API key can sit in `cache.db-wal` rather than
        `cache.db` itself until the next checkpoint. Chmoding every file
        the directory actually contains, called again after each write,
        covers whichever file SQLite wrote the value into, whatever it is
        named, rather than naming `cache.db` alone and missing its
        siblings.
        """
        try:
            entries = os.listdir(self._directory)
        except OSError:
            return
        for name in entries:
            path = os.path.join(self._directory, name)
            try:
                if not os.path.isfile(path):
                    continue
            except OSError:
                continue
            try:
                os.chmod(path, 0o600)
            except OSError as error:
                log.warning(
                    'Cache: could not chmod %s to 0600 -- if this '
                    'filesystem ignores or refuses chmod, this cached '
                    'file may be readable by other users: %s',
                    name, error,
                )

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
            loaded = json.loads(value_json)
        except (json.JSONDecodeError, TypeError):
            log.warning('Cache: corrupt entry for key %s, removing', key)
            self.delete(key)
            return default

        if isinstance(loaded, dict) and set(loaded.keys()) == {_BYTES_MARKER}:
            try:
                return base64.b64decode(loaded[_BYTES_MARKER], validate=True)
            except (TypeError, ValueError, binascii.Error):
                log.warning('Cache: corrupt bytes entry for key %s, removing', key)
                self.delete(key)
                return default

        return loaded

    def set(self, key, value, expire=None):
        """Store a value. *expire* is TTL in seconds (None = no expiry).

        Values are stored as JSON (never pickle) to avoid CVE-2025-69872 --
        see the module docstring. HTTP response bodies (what HTTPClient.request
        and therefore getJsonData/getRSSData actually hand this cache) come in
        as *bytes*, which json.dumps cannot represent, and are not guaranteed
        to be UTF-8 text -- decoding them to str would silently corrupt any
        body that is not valid UTF-8. So a bytes value is base64-encoded and
        wrapped in a small marker dict before being JSON-encoded, and unwrapped
        again in get(). This keeps the stored form plain, inspectable JSON
        text (no arbitrary object deserialisation) while round-tripping the
        exact bytes.
        """
        expiry = (time.time() + expire) if expire else None
        if isinstance(value, bytes):
            value_json = json.dumps({_BYTES_MARKER: base64.b64encode(value).decode('ascii')})
        else:
            try:
                value_json = json.dumps(value)
            except (TypeError, ValueError):
                log.warning(
                    'Cache: cannot serialise value of type %s for key %r, not caching it',
                    type(value).__name__, key,
                )
                return
        conn = self._conn()
        conn.execute(
            'INSERT OR REPLACE INTO cache (key, value, expiry) VALUES (?, ?, ?)',
            (key, value_json, expiry),
        )
        conn.commit()
        # T7d item 5: this is the write that can create `cache.db-wal` for
        # the first time (SQLite creates it lazily, on first write, not
        # when WAL mode is enabled) -- re-secure after every write rather
        # than only once in __init__.
        self._secure_cache_files()

    def delete(self, key):
        """Remove a single key."""
        conn = self._conn()
        conn.execute('DELETE FROM cache WHERE key = ?', (key,))
        conn.commit()
        self._secure_cache_files()

    def clear(self):
        """Remove all entries."""
        conn = self._conn()
        conn.execute('DELETE FROM cache')
        conn.commit()
        self._secure_cache_files()

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
            self._secure_cache_files()
        except sqlite3.OperationalError:
            pass

    def __del__(self):
        self.close()
