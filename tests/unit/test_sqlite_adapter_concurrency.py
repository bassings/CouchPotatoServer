"""The adapter's single connection must be safe under concurrent requests.

Found by reading the per-worker server log this branch started retaining
(tests/e2e/fixtures.ts). The residual E2E flake -- recorded in
docs/technical-debt.md as "host contention on longer runs ... not a code
defect" -- was in fact this, ten times in one run:

    sqlite3.InterfaceError: bad parameter or other API misuse
      File ".../couchpotato/core/db/sqlite_adapter.py", line 308, in get
        row = conn.execute("SELECT ... WHERE _id = ?", (key,)).fetchone()

driving `Failed doing api request "media.list"` and `"profile.list"`, which
is exactly the reported symptom: an empty grid, and a release table that
never appears.

`open()`/`create()` build ONE `sqlite3.Connection` with
`check_same_thread=False`, and FastAPI runs sync route handlers in a
threadpool. That flag disables sqlite3's own thread check; it does not make
the connection safe to use from two threads at once, and the caller is
required to serialise. Reads took no lock at all -- `_write_lock` guarded
only writes -- so any two concurrent requests could interleave on the same
connection.

The write path is the reason this is more than a flaky test: a read on one
thread interleaving with a write on another misuses the same connection.

**There is deliberately no behavioural test for the write path**, and the
reason is worth recording because two attempts at one were both
incidentally passing:

1. A mixed read/write hammer. Review measured it against a PARTIAL fix
   (reads on one lock, writes on another, so a read can still interleave
   with a write): it passed 30 runs out of 30, while the two tests below
   red 12 times out of 12 against the unfixed adapter. It detected nothing
   its siblings did not.
2. A deterministic "a read must wait for an in-flight write". Measured: it
   passes under the split lock too, because CPython's `sqlite3` runs the
   connection in SQLite's *serialized* threading mode, so the C library
   already mutexes each API call. That test was measuring SQLite's internal
   mutex, not this module's lock.

Which also explains the shape of the defect, and the shared object is more
specific than "the connection". The C-level mutex protects a single API call,
but `Connection.execute()` binds, steps and resets a prepared statement across
several of them -- and sqlite3 keeps a per-connection LRU **statement cache**,
so two threads running the SAME SQL text are handed the SAME prepared
statement and reset each other's mid-flight.

Measured, one connection, 5 x 2000 executions per configuration: two threads
on the same SQL produced 334 `InterfaceError`s; two threads on DIFFERENT SQL
produced 0; one reader against one writer produced 0; and the same-SQL case
with `cached_statements=0` produced 0.

That is why a read-vs-read hammer provokes it readily -- `get()` issues one
identical SELECT from every thread -- while read-vs-write raises nothing even
with no lock at all, which is precisely why no behavioural test for the write
path is achievable here.

So the write path is covered **by construction, not by a test**: every
write method carries the same `@_synchronised` decorator, on the same lock,
as every read. If that ever stops being true, the two tests below still
cover reads, and this note is the record that nothing covers the rest.
"""
import threading

import pytest

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def adapter(tmp_path):
    db = SQLiteAdapter()
    db.create(str(tmp_path / 'db'))
    for i in range(60):
        db.insert({
            '_id': 'doc-%03d' % i, '_t': 'media', 'type': 'movie',
            'status': 'active', 'title': 'Movie %d' % i, 'identifiers': {},
        })
    try:
        yield db
    finally:
        db.close()


def _hammer(fn, threads=8, iterations=40):
    """Run `fn` on N threads and return every exception it raised."""
    errors = []
    barrier = threading.Barrier(threads)

    def worker():
        barrier.wait()  # maximise the overlap rather than hoping for it
        for _ in range(iterations):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - the point is to collect them
                errors.append(exc)

    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    return errors


def test_concurrent_reads_do_not_misuse_the_connection(adapter):
    """Two API requests in flight at once is the ordinary case, not an edge."""
    errors = _hammer(lambda: adapter.get('id', 'doc-007'))

    assert not errors, (
        'concurrent get() raised %d error(s), first: %r' % (len(errors), errors[0])
    )


def test_concurrent_index_queries_do_not_misuse_the_connection(adapter):
    """`media.list` and `profile.list` -- the two that failed in the log."""
    errors = _hammer(lambda: list(adapter.query('media_status', 'active', with_doc=True)))

    assert not errors, (
        'concurrent query() raised %d error(s), first: %r' % (len(errors), errors[0])
    )


def test_concurrent_index_queries_hit_query_index_itself(adapter):
    """The same hammer, aimed at `_query_index`, and turned up until it bites.

    Removing `@_synchronised` from `_query_index` alone was caught only
    **3 runs in 5** by `test_concurrent_index_queries_do_not_misuse_the_
    connection` above. A future change dropping that decorator therefore had
    roughly a 40% chance of going green, on a defect whose symptom is
    `media.list` returning the user an empty grid.

    The first attempt at a fix was to call `_query_index` directly, on the
    theory that `query()`'s per-row `get()` takes the same lock and
    desynchronises the threads before they re-enter it. Measured at the
    original 8x40: **also 3 in 5**. The theory was wrong, or at least not the
    binding constraint -- the window is simply narrow, and the fix is
    pressure, not a shorter call path. Recorded because the plausible
    explanation was the one that did not survive being run.

    At 4 threads x 600 iterations, measured on the same tree:

        mutated (no decorator)  -> caught 8 / 8
        unmutated               -> 0 false reds in 8

    Fewer threads and more iterations, not more of both: 8x600 caught 10/10
    in the same probe but took 45s against 5.7s, and a guard nobody will wait
    for gets deleted.

    Same SQL text from every thread, which is what actually provokes it: the
    per-connection statement cache hands them all the same prepared statement
    and they reset each other's mid-flight.
    """
    errors = _hammer(lambda: adapter._query_index('media_status', 'active'),
                     threads=4, iterations=600)

    assert not errors, (
        'concurrent _query_index() raised %d error(s), first: %r'
        % (len(errors), errors[0])
    )
