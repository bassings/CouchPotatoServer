"""Regression tests for the REG-002 review finding: Suggestion._ignored races.

``Suggestion._ignored`` is shared state mutated by ``ignoreSuggestion``
(route ``suggestion.ignore``) and read by ``getSuggestions`` (route
``suggestion.view``). ``callApiHandler``'s per-route ``api_locks`` only
serialize same-route calls, and REG-002 moved API dispatch into the
threadpool, so cross-route interleavings are now reachable from ordinary
web traffic.

The concrete lost-update mode tested deterministically here: without a lock
held across add + snapshot + persist, request A can join its (stale)
snapshot of the set, get pre-empted while request B adds an id and persists
a newer snapshot, and then write its stale snapshot last — silently
dropping B's ignore from the persisted value.

(The classic ``RuntimeError: Set changed size during iteration`` mode is
not deterministically reproducible under the GIL — ``str.join`` iterates
the set inside a single C call — so it is covered only incidentally by the
stress test below.)
"""
import threading

from couchpotato.core.plugins.suggestion import Suggestion
from couchpotato.environment import Env


def _bare_suggestion():
    """A Suggestion instance without __init__ side effects.

    __init__ registers API views and events in module-global registries;
    bypassing it keeps these tests hermetic. Instance attributes shadow the
    class-level ``_ignored``/``_cache`` so the class object stays clean.
    """
    inst = object.__new__(Suggestion)
    inst._ignored = set()
    inst._cache = None
    return inst


def test_stale_ignore_snapshot_cannot_be_persisted_last(monkeypatch):
    """A racing second ignore must not be overwritten by a stale snapshot.

    Orchestrated interleaving (deterministic, mirrors the
    TestConcurrentChartIgnore fake-Env.prop pattern in
    test_race_conditions.py):

    - Thread A ignores 'aaa'; its persist call is held open by fake_prop,
      giving thread B the chance to slip in.
    - Thread B ignores 'bbb'.
    - Pre-fix (no lock): B's complete snapshot {'aaa','bbb'} lands first,
      then A wakes and overwrites it with its stale {'aaa'} — 'bbb' is
      silently lost from the persisted value.
    - Post-fix: ignoreSuggestion holds the lock across add + persist, so B
      cannot even reach fake_prop until A's write has landed; A's gate wait
      simply times out and both ids survive.
    """
    stored = {}
    a_inside_persist = threading.Event()
    second_write_landed = threading.Event()
    write_count = [0]

    def fake_prop(identifier, value=None, default=None):
        if value is None:
            return stored.get(identifier, default)
        write_count[0] += 1
        if write_count[0] == 1:
            a_inside_persist.set()
            # Hold the first write open so a concurrent ignore can persist
            # first (pre-fix it can; post-fix the lock keeps it out and
            # this wait just times out).
            second_write_landed.wait(timeout=0.5)
            stored[identifier] = value
        else:
            stored[identifier] = value
            second_write_landed.set()

    monkeypatch.setattr(Env, 'prop', staticmethod(fake_prop))
    inst = _bare_suggestion()

    thread_a = threading.Thread(target=inst.ignoreSuggestion, kwargs={'imdb': 'aaa'})
    thread_b = threading.Thread(target=inst.ignoreSuggestion, kwargs={'imdb': 'bbb'})

    thread_a.start()
    assert a_inside_persist.wait(timeout=2), 'thread A never reached the persist call'
    thread_b.start()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)
    assert not thread_a.is_alive() and not thread_b.is_alive()

    persisted = set(stored['suggestion.ignored'].split(','))
    assert persisted == {'aaa', 'bbb'}, (
        'final persisted ignore list %r lost a concurrent ignore '
        '(stale snapshot written last)' % sorted(persisted)
    )


def test_concurrent_ignore_stress_no_errors_and_no_lost_updates(monkeypatch):
    """Many parallel ignoreSuggestion calls: no exception, nothing lost."""
    stored = {}

    def fake_prop(identifier, value=None, default=None):
        if value is None:
            return stored.get(identifier, default)
        stored[identifier] = value

    monkeypatch.setattr(Env, 'prop', staticmethod(fake_prop))

    inst = _bare_suggestion()
    # Pre-seed with many ids so the ','.join snapshot in the persist path is
    # long enough for concurrent adds to interleave with it.
    inst._ignored.update('seed%06d' % i for i in range(20000))

    n_threads = 8
    per_thread = 200
    barrier = threading.Barrier(n_threads)
    errors = []

    def worker(tid):
        try:
            barrier.wait()
            for i in range(per_thread):
                inst.ignoreSuggestion(tmdb='t%d-%d' % (tid, i))
        except Exception as e:  # pragma: no cover - only on regression
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    # Bounded join so a reintroduced deadlock (e.g. a lock-ordering bug)
    # fails fast with a clear signal instead of hanging until the blunt
    # suite-wide pytest-timeout fires.
    for t in threads:
        t.join(timeout=30)
    stuck = [t.name for t in threads if t.is_alive()]
    assert not stuck, 'worker threads deadlocked / never finished: %r' % stuck

    assert not errors, 'concurrent ignoreSuggestion raised: %r' % errors

    expected = {'t%d-%d' % (t, i) for t in range(n_threads) for i in range(per_thread)}

    # In-memory set must contain every ignored id.
    assert expected <= inst._ignored

    # And so must the final persisted write: with add + snapshot + persist
    # serialized under one lock, the chronologically last save necessarily
    # contains every id added before it — i.e. all of them once the
    # threads have finished.
    persisted = set(stored['suggestion.ignored'].split(','))
    missing = expected - persisted
    assert not missing, 'last persisted write lost %d ignored ids' % len(missing)
