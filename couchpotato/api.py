"""CouchPotato API module - FastAPI backed.

Provides the dynamic API registration system used by all plugins.
Handlers are registered via addApiView() and dispatched through FastAPI.
"""
import json
import threading
import traceback

from couchpotato.core.helpers.request import getParams
from couchpotato.core.logger import CPLog

log = CPLog(__name__)

# Dynamic API handler registry
api = {}
api_locks = {}
api_nonblock = {}

api_docs = {}
api_docs_missing = []


def addApiView(route, func, static=False, docs=None, **kwargs):
    """Register an API handler for a route.

    This is the main registration function called by all plugins.
    Handlers are stored and dispatched by the FastAPI catch-all route.
    """
    if static:
        func(route)
    else:
        api[route] = func
        api_locks[route] = threading.Lock()

    if docs:
        api_docs[route[4:] if route[0:4] == 'api.' else route] = docs
    else:
        api_docs_missing.append(route)


def addNonBlockApiView(route, func_tuple, docs=None, **kwargs):
    """Register a non-blocking (long-poll/SSE) API handler."""
    api_nonblock[route] = func_tuple

    if docs:
        api_docs[route[4:] if route[0:4] == 'api.' else route] = docs
    else:
        api_docs_missing.append(route)


def callApiHandler(route, **kwargs):
    """Execute a registered API handler by route name."""
    if route not in api:
        return {'success': False, 'error': 'API call doesn\'t exist'}

    lock = api_locks.get(route)
    if lock:
        lock.acquire()

    try:
        kwargs = getParams(kwargs)
        # Remove cache-buster param
        kwargs.pop('t', None)

        result = api[route](**kwargs)
        return result
    except Exception:
        log.error('Failed doing api request "%s": %s', route, traceback.format_exc())
        return {'success': False, 'error': 'Failed returning results'}
    finally:
        if lock:
            try:
                lock.release()
            except Exception:
                pass
