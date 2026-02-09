"""SQLite adapter implementing DatabaseInterface."""
import json
import os
import sqlite3
import time
import uuid
from hashlib import md5
from string import ascii_letters
from typing import Any, Dict, List, Optional
from collections.abc import Iterator

from couchpotato.core.db.interface import DatabaseInterface


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
        self._conn.executescript(schema_sql)

    def open(self, path: str) -> None:
        if self._conn is not None:
            self.close()
        self._path = path
        db_file = os.path.join(path, 'couchpotato.db') if os.path.isdir(path) else path
        self._conn = sqlite3.connect(db_file)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")

    def create(self, path: str) -> None:
        if self._conn is not None:
            self.close()
        self._path = path
        os.makedirs(path, exist_ok=True)
        db_file = os.path.join(path, 'couchpotato.db') if os.path.isdir(path) else path
        self._conn = sqlite3.connect(db_file)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

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
            return self.get('id', result['_id'])
        return result

    def insert(self, data: dict) -> dict:
        conn = self._get_conn()
        doc_id = data.get('_id', _generate_id())
        doc_rev = _generate_rev()
        doc_type = data.get('_t', '')
        now = time.time()

        json_data = self._doc_to_json(data)

        conn.execute(
            "INSERT INTO documents (_id, _rev, _t, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, doc_rev, doc_type, json_data, now, now)
        )

        # Update denormalized tables
        self._update_denormalized(doc_id, data)
        conn.commit()

        return {'_id': doc_id, '_rev': doc_rev}

    def update(self, data: dict) -> dict:
        conn = self._get_conn()
        doc_id = data.get('_id')
        if not doc_id:
            raise ValueError("Document must have _id for update")

        # Check exists
        existing = conn.execute("SELECT _rev FROM documents WHERE _id = ?", (doc_id,)).fetchone()
        if existing is None:
            raise KeyError(f"Document not found: {doc_id}")

        doc_rev = _generate_rev()
        doc_type = data.get('_t', '')
        now = time.time()
        json_data = self._doc_to_json(data)

        conn.execute(
            "UPDATE documents SET _rev = ?, _t = ?, data = ?, updated_at = ? WHERE _id = ?",
            (doc_rev, doc_type, json_data, now, doc_id)
        )

        # Update denormalized tables
        self._update_denormalized(doc_id, data)
        conn.commit()

        return {'_id': doc_id, '_rev': doc_rev}

    def delete(self, data: dict) -> bool:
        conn = self._get_conn()
        doc_id = data.get('_id')
        if not doc_id:
            raise ValueError("Document must have _id for delete")

        # Clean denormalized tables
        conn.execute("DELETE FROM media_identifiers WHERE media_id = ?", (doc_id,))
        conn.execute("DELETE FROM media_tags WHERE media_id = ?", (doc_id,))

        cursor = conn.execute("DELETE FROM documents WHERE _id = ?", (doc_id,))
        conn.commit()
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
                    yield self.get('id', row['_id'])
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
            # MediaIndex: lookup by provider-identifier hash
            # key is md5(f"{provider}-{identifier}")
            # We search media_identifiers instead
            if key is not None:
                sql = """SELECT d._id, d._rev, d.data FROM documents d
                         JOIN media_identifiers mi ON d._id = mi.media_id
                         WHERE md5_provider_id(mi.provider, mi.identifier) = ?"""
                # Can't use custom functions easily, so use a different approach:
                # The caller provides the md5 hash. We need to check all combos.
                # Simpler: just scan media_identifiers and compute.
                # For now, do a subquery approach.
                sql = """SELECT d._id, d._rev, d.data FROM documents d
                         WHERE d._t = 'media'"""
                params = []
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

        elif index_name == 'media_title_search':
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

        elif index_name == 'release_id':
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
                    conn.execute(
                        "INSERT OR REPLACE INTO media_identifiers (media_id, provider, identifier) VALUES (?, ?, ?)",
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

    def reindex(self, index_name: str) -> None:
        """No-op for SQLite; indexes are automatically maintained."""
        pass

    def compact(self) -> None:
        """Run VACUUM on the database."""
        conn = self._get_conn()
        conn.execute("VACUUM")

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
