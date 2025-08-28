from __future__ import annotations

"""
Thin database adapter to decouple CouchPotato from the concrete DB backend.

Currently wraps CodernityDB's SuperThreadSafeDatabase instance while exposing
the attributes and methods used across the codebase. Unknown attributes are
proxied to the underlying DB to minimize churn during migration.
"""

from typing import Any


class DBAdapter:
    def __init__(self, backend: Any):
        self._backend = backend

    # Common properties used in the codebase
    @property
    def path(self) -> str:
        return self._backend.path

    @property
    def indexes_names(self):
        return self._backend.indexes_names

    @property
    def opened(self) -> bool:
        return getattr(self._backend, 'opened', False)

    # Commonly used methods
    def create(self, *args, **kwargs):
        return self._backend.create(*args, **kwargs)

    def open(self, *args, **kwargs):
        return self._backend.open(*args, **kwargs)

    def close(self, *args, **kwargs):
        return self._backend.close(*args, **kwargs)

    def exists(self, *args, **kwargs):
        return self._backend.exists(*args, **kwargs)

    def destroy(self, *args, **kwargs):
        return self._backend.destroy(*args, **kwargs)

    # Index management
    def add_index(self, *args, **kwargs):
        return self._backend.add_index(*args, **kwargs)

    def reindex_index(self, *args, **kwargs):
        return self._backend.reindex_index(*args, **kwargs)

    def destroy_index(self, *args, **kwargs):
        return self._backend.destroy_index(*args, **kwargs)

    def reindex(self, *args, **kwargs):
        return self._backend.reindex(*args, **kwargs)

    def get_db_details(self, *args, **kwargs):
        return self._backend.get_db_details(*args, **kwargs)

    # Document access (used in various handlers)
    def get(self, *args, **kwargs):
        return self._backend.get(*args, **kwargs)

    def update(self, *args, **kwargs):
        return self._backend.update(*args, **kwargs)

    def insert(self, *args, **kwargs):
        return self._backend.insert(*args, **kwargs)

    def all(self, *args, **kwargs):
        return self._backend.all(*args, **kwargs)

    # Low-level delete by id index used by deleteCorrupted
    def _delete_id_index(self, *args, **kwargs):
        return self._backend._delete_id_index(*args, **kwargs)

    # Fallback: proxy anything else to the backend
    def __getattr__(self, item: str):
        return getattr(self._backend, item)

