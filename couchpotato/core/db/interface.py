"""Abstract database interface for CouchPotatoServer."""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from collections.abc import Iterator


class DatabaseInterface(ABC):
    """Abstract interface for database backends.

    All database backends (CodernityDB, SQLite, etc.) must implement this.
    """

    @abstractmethod
    def open(self, path: str) -> None:
        """Open an existing database at the given path."""

    @abstractmethod
    def create(self, path: str) -> None:
        """Create a new database at the given path."""

    @abstractmethod
    def close(self) -> None:
        """Close the database."""

    @abstractmethod
    def get(self, index_name: str, key: Any, with_doc: bool = False) -> dict:
        """Get a single document by key from the named index.

        Args:
            index_name: Name of the index to query.
            key: The key to look up.
            with_doc: If True, include the full document from the id index.

        Returns:
            Dict with document data.

        Raises:
            KeyError: If document not found.
        """

    @abstractmethod
    def insert(self, data: dict) -> dict:
        """Insert a new document.

        Args:
            data: Document data. _id will be auto-generated if not present.

        Returns:
            Dict with _id and _rev.
        """

    @abstractmethod
    def update(self, data: dict) -> dict:
        """Update an existing document.

        Args:
            data: Document data. Must contain _id and _rev.

        Returns:
            Dict with _id and new _rev.
        """

    @abstractmethod
    def delete(self, data: dict) -> bool:
        """Delete a document.

        Args:
            data: Must contain _id and _rev.

        Returns:
            True on success.
        """

    @abstractmethod
    def all(self, index_name: str, limit: int = -1, offset: int = 0,
            with_doc: bool = False) -> Iterator[dict]:
        """Iterate over all documents in an index.

        Args:
            index_name: Index to iterate.
            limit: Max records (-1 for unlimited).
            offset: Records to skip.
            with_doc: Include full document data.

        Returns:
            Iterator of document dicts.
        """

    @abstractmethod
    def query(self, index_name: str, key: Any = None,
              start: Any = None, end: Any = None,
              limit: int = -1, offset: int = 0,
              with_doc: bool = False) -> Iterator[dict]:
        """Query an index with optional range parameters.

        Args:
            index_name: Index to query.
            key: Exact key match (for hash indexes).
            start: Range start (for tree indexes).
            end: Range end (for tree indexes).
            limit: Max records.
            offset: Records to skip.
            with_doc: Include full document data.

        Returns:
            Iterator of matching document dicts.
        """

    @abstractmethod
    def add_index(self, index, create: bool = True) -> str:
        """Add an index to the database.

        Args:
            index: Index instance or definition.
            create: Whether to create index files.

        Returns:
            Index name.
        """

    @abstractmethod
    def reindex(self, index_name: str) -> None:
        """Reindex a specific index."""

    @abstractmethod
    def compact(self) -> None:
        """Compact all indexes to reclaim space."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Whether the database is currently open."""
