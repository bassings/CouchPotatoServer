"""Put `Env` back the way you found it.

`Env` keeps its values as CLASS attributes, so `Env.set('settings', ...)` in one
test module is still in force in the next one. Spec gap 9 recorded that as a
live trap on this branch; this is it happening again, and the second time it
was not subtle: three new test modules here sort alphabetically BEFORE
`test_releases_partial_route.py`, whose fixture sets no `settings` of its own,
so it inherited an install with `auth_required = 1` and a stored password and
its 34 tests were served the login page. Every one of them failed with a
message about a missing release name -- which reads like the route broke.

Nothing here is clever. It exists so a new module can be added to this
directory without deciding, again, which of `Env`'s twenty-odd class attributes
it is quietly borrowing from whoever ran first.
"""
from contextlib import contextmanager

from couchpotato.environment import Env

#: Every attribute a unit-test fixture in this directory is known to set.
#: Restoring a superset is harmless -- the value goes back to whatever it was --
#: so err toward listing too many rather than too few.
ENV_ATTRIBUTES = (
    'app', 'api_base', 'app_dir', 'args', 'cache', 'cache_dir', 'daemonized',
    'database', 'data_dir', 'db', 'debug', 'desktop', 'dev', 'encoding',
    'http_opener', 'loader', 'log_path', 'options', 'quiet', 'settings',
    'softchroot', 'static_path', 'web_base',
)

_MISSING = object()


@contextmanager
def env_restored(attributes=ENV_ATTRIBUTES):
    """Snapshot `Env`'s class attributes and put them back afterwards."""
    saved = {name: getattr(Env, '_' + name, _MISSING) for name in attributes}
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is _MISSING:
                if hasattr(Env, '_' + name):
                    delattr(Env, '_' + name)
            else:
                setattr(Env, '_' + name, value)
