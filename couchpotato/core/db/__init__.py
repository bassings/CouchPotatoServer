"""Database abstraction layer for CouchPotatoServer.

Provides a common interface for database backends, enabling future
migration from CodernityDB to SQLite without changing application code.
"""

from couchpotato.core.db.interface import DatabaseInterface
from couchpotato.core.db.codernity_adapter import CodernityDBAdapter

__all__ = ['DatabaseInterface', 'CodernityDBAdapter']
