"""Database abstraction layer for CouchPotatoServer.

Provides a common interface for database backends, enabling future
migration from CodernityDB to SQLite without changing application code.

Usage:
    from couchpotato.core.db import create_adapter

    # Uses default backend (codernity) or CP_DATABASE_BACKEND env var
    db = create_adapter()

    # Explicit backend selection
    db = create_adapter('sqlite')
"""

from couchpotato.core.db.interface import DatabaseInterface
from couchpotato.core.db.codernity_adapter import CodernityDBAdapter
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.db.factory import create_adapter, get_backend

__all__ = ['DatabaseInterface', 'CodernityDBAdapter', 'SQLiteAdapter', 'create_adapter', 'get_backend']
