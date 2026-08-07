"""Every method that touches the shared connection must be serialised exactly once.

`SQLiteAdapter` holds ONE `sqlite3.Connection` built with
`check_same_thread=False`, and FastAPI runs sync handlers in a threadpool. That
flag disables sqlite3's own thread check; it does not make the connection safe
to share. `@_synchronised` is the whole of the discipline that keeps it safe,
and its correctness is a property of DECORATOR PLACEMENT -- which no behavioural
test can see.

That is not theoretical. A review of this branch found
`_ensure_release_download_index` carrying `@_synchronised` TWICE while
`_ensure_unique_media_identifier_index` had lost its own: a new method was
spliced between an existing decorator and the function it belonged to. Nothing
failed. The double acquisition is harmless (`_conn_lock` is an RLock) and the
stripped method happened to have exactly one caller that already held the lock,
so the REG-004 duplicate-media backstop was running DDL protected only by
coincidence. The next direct caller would have run it unserialised.

This is the third edit to land one line off target in this file, which is why
the rule is now a command that exits non-zero rather than a paragraph.

DELIBERATELY NOT ASSERTED: that generator methods (`query`, `all`) carry the
decorator. They must NOT -- a decorator around a generator function releases the
lock the moment the generator is created and holds nothing during iteration,
which looks correct and is not. They are safe because every connection touch
they make goes through `_query_index` or `get()`, each synchronised itself. The
test below pins that too, so "helpfully" adding one reds it.
"""
import inspect
import re
from pathlib import Path

import pytest

ADAPTER = Path(__file__).resolve().parents[2] / 'couchpotato' / 'core' / 'db' / 'sqlite_adapter.py'

#: Methods that MUST be serialised: they call `self._get_conn()` (or reassign
#: `self._conn`) and then use it.
MUST_BE_SYNCHRONISED = {
    'open', 'create', 'close',
    'get', 'insert', 'update', 'delete',
    '_query_index', '_update_denormalized', '_commit_if_not_transaction',
    '_has_unique_identifier_index',
    '_ensure_unique_media_identifier_index',
    '_ensure_release_download_index',
    'compact', 'get_by_identifier', 'insert_bulk',
}

#: Generators. A decorator here would release the lock before iteration begins.
MUST_NOT_BE_SYNCHRONISED = {'query', 'all'}


def _decorator_counts():
    """Map method name -> number of @_synchronised decorators directly above it.

    Parsed from SOURCE rather than by introspecting the bound method, because
    `functools.wraps` makes a double-wrapped method indistinguishable from a
    single-wrapped one at runtime -- which is precisely how the doubled
    decorator survived.
    """
    lines = ADAPTER.read_text(encoding='utf-8').splitlines()
    counts = {}
    for i, line in enumerate(lines):
        match = re.match(r'    def (\w+)\(', line)
        if not match:
            continue
        n, j = 0, i - 1
        while j >= 0 and lines[j].strip().startswith('@'):
            if '_synchronised' in lines[j]:
                n += 1
            j -= 1
        counts[match.group(1)] = n
    return counts


class TestTheLockingContractHolds:

    def test_the_parser_sees_the_methods_at_all(self):
        """Anti-vacuity: every assertion below is a dict lookup, so a parser
        that silently found nothing would make the whole file pass green."""
        counts = _decorator_counts()
        assert len(counts) > 20, 'only found %d methods; the parser is broken' % len(counts)
        missing = (MUST_BE_SYNCHRONISED | MUST_NOT_BE_SYNCHRONISED) - set(counts)
        assert not missing, 'named methods absent from the adapter: %s' % sorted(missing)

    @pytest.mark.parametrize('name', sorted(MUST_BE_SYNCHRONISED))
    def test_connection_touching_methods_are_synchronised_exactly_once(self, name):
        n = _decorator_counts()[name]
        assert n == 1, (
            '%s carries @_synchronised %d time(s), expected exactly 1. '
            'Zero means it runs DDL/DML on the shared connection unserialised. '
            'More than one means an edit landed between a decorator and its '
            'function -- check what the method ABOVE it lost.' % (name, n)
        )

    def test_the_lazy_methods_really_are_lazy(self):
        """Pins the PREMISE, so the rule below cannot outlive its reason.

        `query` is a generator function. `all` is NOT -- it is a plain function
        whose body is `return self.query(...)`, so it hands back `query`'s
        generator without being one itself. Both are lazy at the call site,
        which is the property that makes decorating either of them wrong, and
        an earlier version of this test asserted `isgeneratorfunction` on both
        and failed on `all` for exactly that reason. If either ever becomes
        eager, the rule below stops applying and should be re-derived rather
        than kept out of habit.
        """
        from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

        assert inspect.isgeneratorfunction(SQLiteAdapter.query), (
            'query is no longer a generator function'
        )
        assert not inspect.isgeneratorfunction(SQLiteAdapter.all), (
            'all is now a generator function itself; it used to delegate to query'
        )
        source = inspect.getsource(SQLiteAdapter.all)
        assert 'return self.query(' in source, (
            'all no longer delegates to query, so it may now touch the '
            'connection directly and need synchronising -- re-derive the rule'
        )

    @pytest.mark.parametrize('name', sorted(MUST_NOT_BE_SYNCHRONISED))
    def test_lazy_methods_are_not_synchronised(self, name):
        assert _decorator_counts()[name] == 0, (
            '%s is LAZY and must NOT be @_synchronised: the lock would be '
            'released as soon as the generator was created and held for none '
            'of the iteration -- which looks correct and is not. It is safe '
            'because every connection touch goes through _query_index or '
            'get(), each synchronised itself.' % name
        )

    def test_no_method_carries_it_twice(self):
        """Catches the splice defect on methods this file does not name."""
        doubled = [n for n, c in _decorator_counts().items() if c > 1]
        assert not doubled, (
            'methods with a duplicated @_synchronised: %s. This is the '
            'signature of an edit inserted between a decorator and its '
            'function -- the method that USED to follow that decorator has '
            'silently lost it.' % doubled
        )
