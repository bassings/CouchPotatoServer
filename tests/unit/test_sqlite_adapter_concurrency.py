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


def test_reads_concurrent_with_writes_do_not_misuse_the_connection(adapter):
    """The half that matters beyond the test suite.

    A read interleaving with a write on the same connection is the same
    misuse, and a corrupted write is not recoverable by re-running.
    """
    counter = [0]
    lock = threading.Lock()

    def mixed():
        with lock:
            counter[0] += 1
            n = counter[0]
        if n % 3 == 0:
            adapter.insert({
                '_id': 'w-%05d' % n, '_t': 'media', 'type': 'movie',
                'status': 'active', 'title': 'W%d' % n, 'identifiers': {},
            })
        else:
            list(adapter.query('media_status', 'active'))

    errors = _hammer(mixed, threads=6, iterations=30)

    assert not errors, (
        'mixed read/write raised %d error(s), first: %r' % (len(errors), errors[0])
    )
