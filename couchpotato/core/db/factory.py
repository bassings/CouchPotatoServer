"""Database backend factory.

Provides a factory function to create the appropriate database adapter
based on configuration. Supports 'codernity' and 'sqlite' backends.
"""
import os
from typing import Optional

from couchpotato.core.db.interface import DatabaseInterface


# Default backend
DEFAULT_BACKEND = 'codernity'

# Environment variable override
ENV_VAR = 'CP_DATABASE_BACKEND'


def get_backend(backend: Optional[str] = None) -> str:
    """Determine which database backend to use.

    Priority:
    1. Explicit backend parameter
    2. CP_DATABASE_BACKEND environment variable
    3. Default ('codernity')
    """
    if backend:
        return backend.lower()
    return os.environ.get(ENV_VAR, DEFAULT_BACKEND).lower()


def create_adapter(backend: Optional[str] = None) -> DatabaseInterface:
    """Create a database adapter instance.

    Args:
        backend: 'codernity' or 'sqlite'. If None, uses env var or default.

    Returns:
        DatabaseInterface implementation.

    Raises:
        ValueError: If backend is unknown.
    """
    backend = get_backend(backend)

    if backend == 'codernity':
        from couchpotato.core.db.codernity_adapter import CodernityDBAdapter
        return CodernityDBAdapter()
    elif backend == 'sqlite':
        from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
        return SQLiteAdapter()
    else:
        raise ValueError(f"Unknown database backend: '{backend}'. Use 'codernity' or 'sqlite'.")
