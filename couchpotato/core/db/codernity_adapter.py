"""CodernityDB adapter implementing DatabaseInterface."""
import os
import sys
from typing import Any, Dict
from collections.abc import Iterator

from couchpotato.core.db.interface import DatabaseInterface

# Add libs to path if needed
libs_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'libs')
if libs_path not in sys.path:
    sys.path.insert(0, os.path.abspath(libs_path))

from CodernityDB.database import (
    Database,
    RecordNotFound,
    RecordDeleted,
    RevConflict,
    DatabaseConflict,
)
from CodernityDB.index import IndexNotFoundException


class CodernityDBAdapter(DatabaseInterface):
    """Adapter wrapping CodernityDB's Database class."""

    def __init__(self):
        self._db = None
        self._path = None

    @property
    def db(self) -> Database:
        """Access the underlying CodernityDB Database instance."""
        if self._db is None:
            raise RuntimeError("Database not opened")
        return self._db

    def open(self, path: str) -> None:
        if self._db and self._db.opened:
            self._db.close()
        self._path = path
        self._db = Database(path)
        self._db.open()

    def create(self, path: str) -> None:
        self._path = path
        self._db = Database(path)
        self._db.create()

    def close(self) -> None:
        if self._db and self._db.opened:
            self._db.close()

    def get(self, index_name: str, key: Any, with_doc: bool = False) -> dict:
        try:
            return self._db.get(index_name, key, with_doc=with_doc)
        except (RecordNotFound, RecordDeleted) as e:
            raise KeyError(str(e)) from e

    def insert(self, data: dict) -> dict:
        return self._db.insert(data)

    def update(self, data: dict) -> dict:
        return self._db.update(data)

    def delete(self, data: dict) -> bool:
        return self._db.delete(data)

    def all(self, index_name: str, limit: int = -1, offset: int = 0,
            with_doc: bool = False) -> Iterator[dict]:
        return self._db.all(index_name, limit=limit, offset=offset,
                           with_doc=with_doc)

    def query(self, index_name: str, key: Any = None,
              start: Any = None, end: Any = None,
              limit: int = -1, offset: int = 0,
              with_doc: bool = False) -> Iterator[dict]:
        if key is not None:
            return self._db.get_many(index_name, key=key, limit=limit,
                                     offset=offset, with_doc=with_doc)
        elif start is not None or end is not None:
            return self._db.get_many(index_name, start=start, end=end,
                                     limit=limit, offset=offset,
                                     with_doc=with_doc)
        else:
            return self.all(index_name, limit=limit, offset=offset,
                           with_doc=with_doc)

    def add_index(self, index, create: bool = True) -> str:
        return self._db.add_index(index, create=create)

    def reindex(self, index_name: str) -> None:
        self._db.reindex_index(index_name)

    def compact(self) -> None:
        self._db._compact_indexes()

    @property
    def is_open(self) -> bool:
        return self._db is not None and self._db.opened

    # Convenience: expose indexes_names for compatibility
    @property
    def indexes_names(self):
        return self._db.indexes_names if self._db else {}

    @property
    def path(self):
        return self._path
