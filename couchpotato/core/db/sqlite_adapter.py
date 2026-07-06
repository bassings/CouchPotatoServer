"""SQLite adapter implementing DatabaseInterface."""
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from hashlib import md5
from string import ascii_letters
from typing import Any, Dict, List, Optional
from collections.abc import Iterator

from couchpotato.core.db.interface import DatabaseInterface
from couchpotato.core.logger import CPLog


log = CPLog(__name__)


class ConflictError(Exception):
    """Raised by SQLiteAdapter.update() when a compare-and-swap on `_rev`
    fails because another writer updated the document first.

    This is the lost-update signal for read-modify-write callers: the
    caller's in-memory copy is stale (it was read at an older `_rev` than
    what is currently stored), so blindly writing it would silently discard
    the other writer's change. Callers should re-`get()` the document,
    re-apply their change, and retry -- see `SQLiteAdapter.update_with_retry`
    for a ready-made helper that does this.
    """

    def __init__(self, doc_id: str, message: str | None = None):
        self._id = doc_id
        super().__init__(
            message or
            f"Update conflict for document {doc_id!r}: _rev is stale "
            "(document was modified by another writer). Re-read and retry."
        )


def _generate_id():
    return uuid.uuid4().hex


def _generate_rev():
    return uuid.uuid4().hex[:8]


class SQLiteAdapter(DatabaseInterface):
    """SQLite backend implementing the DatabaseInterface.

    Uses a single 'documents' table with JSON data, mirroring CodernityDB's
    document model. Indexes are handled by SQLite indexes on json_extract().
    """

    def __init__(self):
        self._conn: sqlite3.Connection | None = None
        self._path: str | None = None
        self._indexes: dict = {}  # name -> index config (for compat)
        self._write_lock = threading.RLock()
        self._transaction_depth = 0

    @property
    def path(self):
        return self._path

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @property
    def indexes_names(self):
        return self._indexes

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not opened")
        return self._conn

    def _init_schema(self):
        """Initialize the database schema."""
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        with open(schema_path) as f:
            schema_sql = f.read()
        try:
            self._conn.executescript(schema_sql)
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as schema_error:
            # Fail-safe: the full schema (with its UNIQUE identifier index)
            # could not be applied -- fall back to the non-unique index so the
            # rest of the schema still initializes and startup never bricks.
            # Every schema statement uses IF NOT EXISTS, so re-running the
            # (downgraded) script is idempotent. Only an IntegrityError actually
            # implies duplicate rows; an OperationalError (locked DB, I/O, an
            # unrelated schema statement) does not -- keep the diagnosis honest
            # so on-call isn't sent to the dedup migration for a lock error.
            if isinstance(schema_error, sqlite3.IntegrityError):
                log.warning(
                    'Could not apply the full schema (likely duplicate media '
                    'identifiers): retrying without the UNIQUE identifier index. '
                    'Running with in-process-lock duplicate protection only; run '
                    'the dedup migration to enable the DB-level backstop (REG-004).'
                )
            else:
                log.warning(
                    'Could not apply the full schema (%s): retrying without the '
                    'UNIQUE identifier index. This is likely a locked database or '
                    'an unrelated schema error rather than duplicate identifiers '
                    '(REG-004).', schema_error
                )
            safe_sql = schema_sql.replace(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_media_identifiers_lookup',
                'CREATE INDEX IF NOT EXISTS idx_media_identifiers_lookup',
            )
            self._conn.executescript(safe_sql)

    def _has_unique_identifier_index(self) -> bool:
        """Return True if a UNIQUE index on media_identifiers(provider,
        identifier) already exists (fresh installs get one from schema.sql)."""
        conn = self._get_conn()
        for idx in conn.execute("PRAGMA index_list('media_identifiers')").fetchall():
            if not idx['unique']:
                continue
            # Index names here come from our own schema; quote defensively.
            name = str(idx['name']).replace("'", "''")
            cols = [r['name'] for r in
                    conn.execute("PRAGMA index_info('%s')" % name).fetchall()]
            if cols == ['provider', 'identifier']:
                return True
        return False

    def _ensure_unique_media_identifier_index(self) -> None:
        """Idempotently upgrade an existing install to the UNIQUE
        media_identifiers(provider, identifier) index (REG-004).

        Fresh installs already get the UNIQUE index from schema.sql, so this
        is a no-op there. Pre-REG-004 installs have a NON-unique index named
        ``idx_media_identifiers_lookup``; ``CREATE UNIQUE INDEX IF NOT EXISTS``
        with that same name would silently do nothing, so we must DROP the old
        index and recreate it UNIQUE. If historical duplicate rows exist the
        CREATE fails -- in that case we restore the non-unique index, warn
        loudly, and continue running with in-process-lock protection only.
        This never auto-dedups (destructive) and never bricks startup.

        Note: sqlite3 auto-commits DDL, so a failed CREATE cannot be undone by
        a rollback -- we explicitly recreate the non-unique index instead.
        """
        conn = self._get_conn()
        try:
            if self._has_unique_identifier_index():
                return

            dropped = False
            try:
                with self._write_lock:
                    conn.execute("DROP INDEX IF EXISTS idx_media_identifiers_lookup")
                    dropped = True
                    conn.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_media_identifiers_lookup "
                        "ON media_identifiers(provider, identifier)"
                    )
                    conn.commit()
                log.info('Upgraded media_identifiers(provider, identifier) to a '
                         'UNIQUE index (REG-004 duplicate-media backstop).')
            except Exception as create_error:
                # The UNIQUE index could not be created. Restore the original
                # non-unique index on ANY failure once we've dropped it --
                # otherwise media_identifiers is left with NO index at all,
                # a lookup perf cliff on large prod DBs. (This runs for the
                # expected duplicate-rows case AND any unexpected error.)
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                if dropped:
                    try:
                        with self._write_lock:
                            conn.execute(
                                "CREATE INDEX IF NOT EXISTS idx_media_identifiers_lookup "
                                "ON media_identifiers(provider, identifier)"
                            )
                            conn.commit()
                    except sqlite3.Error:
                        pass
                if isinstance(create_error, sqlite3.IntegrityError):
                    # Expected case: duplicate (provider, identifier) rows already
                    # exist (the exact state the prod incident left behind), so the
                    # DB-level backstop can't be enabled yet. Only an IntegrityError
                    # implies duplicates -- an OperationalError (locked DB, I/O) does
                    # not, so it takes the generic message below.
                    log.warning(
                        'Duplicate media identifiers present in the database: could '
                        'not create the UNIQUE (provider, identifier) index. Running '
                        'with in-process-lock duplicate protection only. Run the '
                        'dedup migration to enable the database-level backstop '
                        '(REG-004).'
                    )
                else:
                    log.warning('Failed creating the unique media identifier index '
                                '(%s); restored the non-unique index and continuing '
                                'without the DB-level backstop (REG-004).',
                                create_error)
        except Exception:
            # Absolute fail-safe: index maintenance must never brick startup.
            log.warning('Failed ensuring the unique media identifier index; '
                        'continuing without the DB-level backstop (REG-004).')

    def open(self, path: str) -> None:
        if self._conn is not None:
            self.close()
        self._path = path
        db_file = os.path.join(path, 'couchpotato.db') if os.path.isdir(path) else path
        self._conn = sqlite3.connect(db_file, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        # Existing DBs never re-run schema.sql (open() doesn't call
        # _init_schema), so self-upgrade the duplicate-media backstop here.
        self._ensure_unique_media_identifier_index()

    def create(self, path: str) -> None:
        if self._conn is not None:
            self.close()
        self._path = path
        os.makedirs(path, exist_ok=True)
        db_file = os.path.join(path, 'couchpotato.db') if os.path.isdir(path) else path
        self._conn = sqlite3.connect(db_file, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self):
        """Run multiple writes atomically.

        SQLiteAdapter methods normally commit each write for CodernityDB
        compatibility. Multi-document operations can use this context manager
        to defer those commits until the whole operation succeeds.
        """
        conn = self._get_conn()
        with self._write_lock:
            depth = self._transaction_depth
            savepoint = f"cp_tx_{depth}"

            if depth == 0:
                conn.execute("BEGIN")
            else:
                conn.execute(f"SAVEPOINT {savepoint}")

            self._transaction_depth += 1
            try:
                yield
            except Exception:
                self._transaction_depth -= 1
                if depth == 0:
                    conn.rollback()
                else:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._transaction_depth -= 1
                if depth == 0:
                    conn.commit()
                else:
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")

    def _commit_if_not_transaction(self) -> None:
        if self._transaction_depth == 0:
            self._get_conn().commit()

    def get_db_details(self) -> dict:
        """Get database size and details (CodernityDB compatibility)."""
        if self._path is None:
            return {'size': 0}
        db_file = os.path.join(self._path, 'couchpotato.db') if os.path.isdir(self._path) else self._path
        try:
            size = os.path.getsize(db_file) if os.path.isfile(db_file) else 0
        except OSError:
            size = 0
        return {'size': size}

    def _doc_from_row(self, row) -> dict:
        """Convert a database row back to a document dict."""
        data = json.loads(row['data'])
        data['_id'] = row['_id']
        data['_rev'] = row['_rev']
        return data

    def _doc_to_json(self, data: dict) -> str:
        """Serialize document data to JSON, excluding _id and _rev."""
        d = {k: v for k, v in data.items() if k not in ('_id', '_rev')}
        return json.dumps(d, default=str)

    def get(self, index_name: str, key: Any, with_doc: bool = False) -> dict:
        """Get document(s) by index lookup.

        For the 'id' index, looks up by _id directly.
        For named indexes, translates to appropriate SQL queries.
        """
        conn = self._get_conn()

        if index_name == 'id':
            row = conn.execute(
                "SELECT _id, _rev, data FROM documents WHERE _id = ?",
                (key,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Document not found: {key}")
            return self._doc_from_row(row)

        # Named index lookups
        rows = list(self._query_index(index_name, key=key, limit=1))
        if not rows:
            raise KeyError(f"No document found in index '{index_name}' for key: {key}")

        result = rows[0]
        if with_doc and '_id' in result:
            doc = self.get('id', result['_id'])
            # CodernityDB compat: wrap document in {'doc': ...} format
            return {'doc': doc, '_id': doc['_id']}
        return result

    def insert(self, data: dict) -> dict:
        with self._write_lock:
            conn = self._get_conn()
            doc_id = data.get('_id', _generate_id())
            doc_rev = _generate_rev()
            doc_type = data.get('_t', '')
            now = time.time()

            json_data = self._doc_to_json(data)

            try:
                conn.execute(
                    "INSERT INTO documents (_id, _rev, _t, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (doc_id, doc_rev, doc_type, json_data, now, now)
                )

                # Update denormalized tables
                self._update_denormalized(doc_id, data)
            except sqlite3.IntegrityError:
                # E.g. the UNIQUE(provider, identifier) index on
                # media_identifiers rejected a duplicate media doc (see
                # REG-004). Roll back so the partially-inserted document row
                # doesn't linger uncommitted and get swept into some later,
                # unrelated commit -- then let the caller decide what to do
                # (movie.add() catches this and re-fetches the existing doc
                # instead of duplicating it).
                if self._transaction_depth == 0:
                    conn.rollback()
                raise

            self._commit_if_not_transaction()

            return {'_id': doc_id, '_rev': doc_rev}

    def update(self, data: dict) -> dict:
        """Update an existing document.

        Compare-and-swap: if `data` carries a `_rev` (the normal case --
        every doc read via get()/query() has one), the UPDATE is conditioned
        on that exact `_rev` still being current in the database. This
        closes the read-modify-write race where two concurrent
        read-modify-write cycles on the same document silently clobber each
        other (lost update) -- the second writer's blind UPDATE used to
        overwrite the first writer's change with no error and no trace.

        If the CAS UPDATE affects zero rows, the row either no longer
        exists (KeyError, same as before) or exists with a *different*
        `_rev` -- meaning another writer updated it first. That second case
        raises ConflictError so the caller can re-read, re-apply its
        change, and retry (see `update_with_retry`).

        Backward-compat fallback: if `data` has no `_rev` at all (some
        callers construct a fresh dict rather than mutating a `get()`
        result), there is no rev to condition on, so this falls back to the
        previous unconditional last-writer-wins UPDATE. This preserves
        existing callers that never carried a `_rev` -- converting them is
        opportunistic follow-up work, not a requirement of this CAS
        contract.
        """
        with self._write_lock:
            conn = self._get_conn()
            doc_id = data.get('_id')
            if not doc_id:
                raise ValueError("Document must have _id for update")

            expected_rev = data.get('_rev')
            doc_rev = _generate_rev()
            doc_type = data.get('_t', '')
            now = time.time()
            json_data = self._doc_to_json(data)

            try:
                if expected_rev is not None:
                    cursor = conn.execute(
                        "UPDATE documents SET _rev = ?, _t = ?, data = ?, updated_at = ? "
                        "WHERE _id = ? AND _rev = ?",
                        (doc_rev, doc_type, json_data, now, doc_id, expected_rev)
                    )
                    if cursor.rowcount == 0:
                        # Either the doc doesn't exist, or it exists with a
                        # different _rev (lost the CAS race). Distinguish
                        # the two so callers get KeyError only for genuine
                        # absence, matching prior semantics.
                        if self._transaction_depth == 0:
                            conn.rollback()
                        current = conn.execute(
                            "SELECT _rev FROM documents WHERE _id = ?", (doc_id,)
                        ).fetchone()
                        if current is None:
                            raise KeyError(f"Document not found: {doc_id}")
                        raise ConflictError(doc_id)
                else:
                    log.debug(
                        'update() called without a _rev for document %s -- '
                        'skipping CAS, falling back to an unconditional '
                        '(last-writer-wins) update.', doc_id
                    )
                    existing = conn.execute(
                        "SELECT _rev FROM documents WHERE _id = ?", (doc_id,)
                    ).fetchone()
                    if existing is None:
                        raise KeyError(f"Document not found: {doc_id}")
                    conn.execute(
                        "UPDATE documents SET _rev = ?, _t = ?, data = ?, updated_at = ? WHERE _id = ?",
                        (doc_rev, doc_type, json_data, now, doc_id)
                    )

                # Update denormalized tables
                self._update_denormalized(doc_id, data)
            except sqlite3.IntegrityError:
                # E.g. an edit gave this doc an identifier another media doc
                # already owns. Roll back rather than leaving an uncommitted
                # half-applied update sitting on the connection.
                if self._transaction_depth == 0:
                    conn.rollback()
                raise

            self._commit_if_not_transaction()

            return {'_id': doc_id, '_rev': doc_rev}

    def update_with_retry(self, mutator, doc_id: str, retries: int = 3) -> dict:
        """Safely perform a read-modify-write update with CAS retry.

        This is the safe primitive for read-modify-write callers: it
        re-`get()`s the current document, applies `mutator(doc)` (which
        should mutate `doc` in place), and `update()`s it. If the write
        loses the compare-and-swap race (ConflictError), the document is
        re-read and the mutator re-applied, up to `retries` attempts total.

        `mutator` may return `False` to signal "no change needed" (e.g. the
        document is already in the desired state) -- in that case the
        document is returned as-is without writing, and no retry occurs.
        Any other return value (including `None`) means "write the
        mutated document".

        Raises:
            KeyError: if the document does not exist.
            ConflictError: if `retries` attempts are all lost to concurrent
                writers (persistent contention on this document).
        """
        last_error: ConflictError | None = None
        for _attempt in range(retries):
            doc = self.get('id', doc_id)
            if mutator(doc) is False:
                return doc
            try:
                result = self.update(doc)
                doc['_rev'] = result['_rev']
                return doc
            except ConflictError as exc:
                last_error = exc
                continue
        raise last_error

    def delete(self, data: dict) -> bool:
        with self._write_lock:
            conn = self._get_conn()
            doc_id = data.get('_id')
            if not doc_id:
                raise ValueError("Document must have _id for delete")

            # Clean denormalized tables
            conn.execute("DELETE FROM media_identifiers WHERE media_id = ?", (doc_id,))
            conn.execute("DELETE FROM media_tags WHERE media_id = ?", (doc_id,))

            cursor = conn.execute("DELETE FROM documents WHERE _id = ?", (doc_id,))
            self._commit_if_not_transaction()
            return cursor.rowcount > 0

    def all(self, index_name: str, limit: int = -1, offset: int = 0,
            with_doc: bool = False) -> Iterator[dict]:
        return self.query(index_name, limit=limit, offset=offset, with_doc=with_doc)

    def query(self, index_name: str, key: Any = None,
              start: Any = None, end: Any = None,
              limit: int = -1, offset: int = 0,
              with_doc: bool = False) -> Iterator[dict]:
        results = self._query_index(index_name, key=key, start=start, end=end,
                                     limit=limit, offset=offset)
        for row in results:
            if with_doc and '_id' in row:
                try:
                    doc = self.get('id', row['_id'])
                    # CodernityDB compat: wrap document in {'doc': ...} format
                    yield {'doc': doc, '_id': doc['_id']}
                except KeyError:
                    continue
            else:
                yield row

    def _query_index(self, index_name: str, key: Any = None,
                     start: Any = None, end: Any = None,
                     limit: int = -1, offset: int = 0) -> list[dict]:
        """Translate CodernityDB index queries to SQL."""
        conn = self._get_conn()
        params: list = []
        sql = ""

        if index_name == 'id':
            sql = "SELECT _id, _rev, data FROM documents"
            if key is not None:
                sql += " WHERE _id = ?"
                params.append(key)
            sql += " ORDER BY _id"

        elif index_name == 'media':
            # MediaIndex: lookup by provider-identifier.
            # Callers pass the key as '{provider}-{identifier}', e.g. 'imdb-tt13320622'.
            # We look this up in the denormalised media_identifiers table.
            if key is not None:
                key_str = str(key)
                if '-' in key_str:
                    provider, identifier = key_str.split('-', 1)
                else:
                    provider, identifier = 'imdb', key_str
                sql = """SELECT d._id, d._rev, d.data FROM documents d
                         JOIN media_identifiers mi ON d._id = mi.media_id
                         WHERE mi.provider = ? AND mi.identifier = ?"""
                params = [provider, identifier]
            else:
                sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"

        elif index_name == 'media_status':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"
            if key is not None:
                sql += " AND json_extract(data, '$.status') = ?"
                params.append(key)
            elif start is not None or end is not None:
                if start is not None:
                    sql += " AND json_extract(data, '$.status') >= ?"
                    params.append(start)
                if end is not None:
                    sql += " AND json_extract(data, '$.status') <= ?"
                    params.append(end)
            sql += " ORDER BY json_extract(data, '$.status')"

        elif index_name == 'media_by_type':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"
            if key is not None:
                sql += " AND json_extract(data, '$.type') = ?"
                params.append(key)
            sql += " ORDER BY json_extract(data, '$.type')"

        elif index_name == 'media_watched':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"
            if key is not None:
                watched_key = key if isinstance(key, bool) else str(key).lower() in ('true', '1', 'yes')
                if watched_key:
                    sql += " AND json_extract(data, '$.watched') = 1"
                else:
                    sql += " AND COALESCE(json_extract(data, '$.watched'), 0) != 1"
            sql += " ORDER BY json_extract(data, '$.watched_at') DESC"

        elif index_name == 'media_title':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"
            if key is not None:
                sql += " AND json_extract(data, '$.title') = ?"
                params.append(key)
            elif start is not None or end is not None:
                if start is not None:
                    sql += " AND json_extract(data, '$.title') >= ?"
                    params.append(start)
                if end is not None:
                    sql += " AND json_extract(data, '$.title') <= ?"
                    params.append(end)
            sql += " ORDER BY json_extract(data, '$.title')"

        elif index_name in ('media_title_search', 'media_search_title'):
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"
            if key is not None:
                sql += " AND LOWER(json_extract(data, '$.title')) LIKE ?"
                params.append(f"%{key.strip('_').lower()}%")
            sql += " ORDER BY json_extract(data, '$.title')"

        elif index_name == 'media_startswith':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"
            if key is not None:
                sql += " AND LOWER(SUBSTR(json_extract(data, '$.title'), 1, 1)) = ?"
                params.append(key.lower())
            sql += " ORDER BY json_extract(data, '$.title')"

        elif index_name == 'media_children':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"
            if key is not None:
                sql += " AND json_extract(data, '$.parent_id') = ?"
                params.append(key)
            else:
                sql += " AND json_extract(data, '$.parent_id') IS NOT NULL"

        elif index_name == 'media_tag':
            if key is not None:
                sql = """SELECT d._id, d._rev, d.data FROM documents d
                         JOIN media_tags mt ON d._id = mt.media_id
                         WHERE mt.tag = ?"""
                params.append(key)
            else:
                sql = """SELECT d._id, d._rev, d.data FROM documents d
                         JOIN media_tags mt ON d._id = mt.media_id"""

        elif index_name == 'category_media':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'media'"
            if key is not None:
                sql += " AND json_extract(data, '$.category_id') = ?"
                params.append(key)
            else:
                sql += " AND json_extract(data, '$.category_id') IS NOT NULL"

        elif index_name == 'release':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'release'"
            if key is not None:
                sql += " AND json_extract(data, '$.media_id') = ?"
                params.append(key)
            elif start is not None or end is not None:
                if start is not None:
                    sql += " AND json_extract(data, '$.media_id') >= ?"
                    params.append(start)
                if end is not None:
                    sql += " AND json_extract(data, '$.media_id') <= ?"
                    params.append(end)
            sql += " ORDER BY json_extract(data, '$.media_id')"

        elif index_name == 'release_status':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'release'"
            if key is not None:
                sql += " AND json_extract(data, '$.status') = ?"
                params.append(key)
            sql += " ORDER BY json_extract(data, '$.status')"

        elif index_name in ('release_id', 'release_identifier'):
            # ReleaseIDIndex — keyed by the release identifier string.
            # Both index names map to the same column; 'release_identifier' is the
            # name used in _database and by db.get() call-sites in release/main.py.
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'release'"
            if key is not None:
                sql += " AND json_extract(data, '$.identifier') = ?"
                params.append(key)

        elif index_name == 'release_download':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'release'"
            if key is not None:
                # key is a combined downloader-id string
                sql += """ AND json_extract(data, '$.download_info.downloader') IS NOT NULL
                           AND json_extract(data, '$.download_info.id') IS NOT NULL"""
                # We'd need to match on combined key; for now return all with download_info
            else:
                sql += " AND json_extract(data, '$.download_info') IS NOT NULL"

        elif index_name == 'category':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'category'"
            if key is not None:
                sql += " AND json_extract(data, '$.order') = ?"
                params.append(key)
            sql += " ORDER BY json_extract(data, '$.order')"

        elif index_name == 'collection':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'collection'"
            if key is not None:
                sql += " AND LOWER(json_extract(data, '$.name')) = ?"
                params.append(str(key).lower())
            sql += " ORDER BY LOWER(json_extract(data, '$.name'))"

        elif index_name == 'profile':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'profile'"
            if key is not None:
                sql += " AND json_extract(data, '$.order') = ?"
                params.append(key)
            sql += " ORDER BY json_extract(data, '$.order')"

        elif index_name == 'quality':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'quality'"
            if key is not None:
                sql += " AND json_extract(data, '$.identifier') = ?"
                params.append(key)

        elif index_name == 'notification':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'notification'"
            if key is not None:
                sql += " AND json_extract(data, '$.time') = ?"
                params.append(key)
            elif start is not None or end is not None:
                if start is not None:
                    sql += " AND json_extract(data, '$.time') >= ?"
                    params.append(start)
                if end is not None:
                    sql += " AND json_extract(data, '$.time') <= ?"
                    params.append(end)
            sql += " ORDER BY json_extract(data, '$.time')"

        elif index_name == 'notification_unread':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'notification' AND (json_extract(data, '$.read') IS NULL OR json_extract(data, '$.read') = 0)"
            if key is not None:
                sql += " AND json_extract(data, '$.time') = ?"
                params.append(key)
            elif start is not None or end is not None:
                if start is not None:
                    sql += " AND json_extract(data, '$.time') >= ?"
                    params.append(start)
                if end is not None:
                    sql += " AND json_extract(data, '$.time') <= ?"
                    params.append(end)
            sql += " ORDER BY json_extract(data, '$.time')"

        elif index_name == 'property':
            sql = "SELECT _id, _rev, data FROM documents WHERE _t = 'property'"
            if key is not None:
                sql += " AND json_extract(data, '$.identifier') = ?"
                params.append(key)

        else:
            # Generic: return all documents
            sql = "SELECT _id, _rev, data FROM documents"
            sql += " ORDER BY _id"

        # Apply limit/offset
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        if offset > 0:
            if limit <= 0:
                sql += " LIMIT -1"
            sql += " OFFSET ?"
            params.append(offset)

        rows = conn.execute(sql, params).fetchall()
        return [self._doc_from_row(row) for row in rows]

    def _update_denormalized(self, doc_id: str, data: dict):
        """Update denormalized lookup tables."""
        conn = self._get_conn()

        if data.get('_t') == 'media':
            # Update media_identifiers
            conn.execute("DELETE FROM media_identifiers WHERE media_id = ?", (doc_id,))
            identifiers = data.get('identifiers', {})
            # Legacy: some docs have 'identifier' (imdb only)
            if data.get('identifier') and 'imdb' not in identifiers:
                identifiers['imdb'] = data['identifier']
            for provider, ident in identifiers.items():
                if ident:
                    # Plain INSERT (not OR REPLACE): the DELETE above already
                    # cleared any rows this same doc owned, so the only way
                    # this can violate the UNIQUE(provider, identifier) index
                    # is if a *different* media doc already owns this
                    # identifier -- in which case we want IntegrityError, not
                    # a silent REPLACE that would delete the other doc's row.
                    conn.execute(
                        "INSERT INTO media_identifiers (media_id, provider, identifier) VALUES (?, ?, ?)",
                        (doc_id, provider, str(ident))
                    )

            # Update media_tags
            conn.execute("DELETE FROM media_tags WHERE media_id = ?", (doc_id,))
            for tag in data.get('tags', []):
                if tag:
                    conn.execute(
                        "INSERT OR REPLACE INTO media_tags (media_id, tag) VALUES (?, ?)",
                        (doc_id, tag)
                    )

    def add_index(self, index, create: bool = True) -> str:
        """Register an index name for compatibility. SQLite indexes are pre-created in schema."""
        name = getattr(index, 'name', str(index)) if not isinstance(index, str) else index
        self._indexes[name] = index
        return name

    def destroy_index(self, index) -> None:
        """Remove an index registration. SQLite indexes are schema-managed."""
        name = getattr(index, 'name', str(index)) if not isinstance(index, str) else index
        self._indexes.pop(name, None)

    def reindex(self, index_name: str) -> None:
        """No-op for SQLite; indexes are automatically maintained."""
        pass

    def reindex_index(self, index_name: str) -> None:
        """No-op for SQLite; indexes are automatically maintained."""
        pass

    def count(self, func, *args, **kwargs) -> int:
        """Count results from a query function.

        CodernityDB compatibility - calls func(*args, **kwargs) and counts results.
        """
        results = func(*args, **kwargs)
        return sum(1 for _ in results)

    def compact(self) -> None:
        """Run VACUUM on the database."""
        conn = self._get_conn()
        conn.execute("VACUUM")

    def get_many(self, index_name: str, key: Any, limit: int = -1,
                 offset: int = 0, with_doc: bool = True) -> Iterator[dict]:
        """Get multiple documents by index lookup.

        CodernityDB compatibility method - wraps query() with with_doc=True.
        """
        return self.query(index_name, key=key, limit=limit, offset=offset, with_doc=with_doc)

    def get_by_identifier(self, provider: str, identifier: str) -> dict:
        """Get a media document by provider and identifier.

        This replaces the CodernityDB MediaIndex multi-key lookup.
        """
        conn = self._get_conn()
        row = conn.execute(
            """SELECT d._id, d._rev, d.data FROM documents d
               JOIN media_identifiers mi ON d._id = mi.media_id
               WHERE mi.provider = ? AND mi.identifier = ?""",
            (provider, str(identifier))
        ).fetchone()
        if row is None:
            raise KeyError(f"No media found for {provider}={identifier}")
        return self._doc_from_row(row)

    def insert_bulk(self, documents: list[dict]) -> int:
        """Insert multiple documents efficiently.

        Returns the number of documents inserted.
        """
        conn = self._get_conn()
        count = 0
        for data in documents:
            doc_id = data.get('_id', _generate_id())
            doc_rev = data.get('_rev', _generate_rev())
            doc_type = data.get('_t', '')
            now = time.time()
            json_data = self._doc_to_json(data)

            conn.execute(
                "INSERT OR REPLACE INTO documents (_id, _rev, _t, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, doc_rev, doc_type, json_data, now, now)
            )
            self._update_denormalized(doc_id, data)
            count += 1

        conn.commit()
        return count
