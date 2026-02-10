"""Task 16: Race condition tests.

Verify that concurrency fixes from Phase 1-2 hold under stress.
"""
import os
import sys
import threading
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from couchpotato.core.event import addEvent, fireEvent, removeEvent, events, _events_lock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_events():
    """Clear all registered events."""
    with _events_lock:
        events.clear()


# ---------------------------------------------------------------------------
# 1. Concurrent event add + fire (verify no RuntimeError)
# ---------------------------------------------------------------------------

class TestConcurrentEventAddFire:
    """In the old code, iterating over events dict while another thread
    modified it caused RuntimeError: dictionary changed size during iteration."""

    def setup_method(self):
        _clear_events()

    def teardown_method(self):
        _clear_events()

    def test_concurrent_add_and_fire_no_crash(self):
        """Rapidly add events while firing them — should not raise RuntimeError."""
        errors = []
        stop = threading.Event()

        def adder():
            i = 0
            while not stop.is_set():
                try:
                    addEvent(f'race.test.{i}', lambda: None)
                    i += 1
                except Exception as e:
                    errors.append(e)

        def firer():
            while not stop.is_set():
                try:
                    fireEvent('race.test.0')
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=adder) for _ in range(3)]
        threads += [threading.Thread(target=firer) for _ in range(3)]

        for t in threads:
            t.daemon = True
            t.start()

        time.sleep(0.5)
        stop.set()

        for t in threads:
            t.join(timeout=2)

        # No RuntimeError should have occurred
        runtime_errors = [e for e in errors if isinstance(e, RuntimeError)]
        assert len(runtime_errors) == 0, f"Got RuntimeErrors: {runtime_errors}"

    def test_concurrent_add_same_event(self):
        """Multiple threads adding handlers to the same event name."""
        results = []
        barrier = threading.Barrier(10)

        def add_handler(n):
            barrier.wait()
            addEvent('race.shared', lambda: n)

        threads = [threading.Thread(target=add_handler, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)

        # All handlers should be registered
        with _events_lock:
            handler_count = len(events.get('race.shared', []))
        assert handler_count == 10

    def test_fire_during_remove(self):
        """Fire an event while another thread removes events."""
        addEvent('race.remove_test', lambda: 'result')
        errors = []

        def fire_loop():
            for _ in range(100):
                try:
                    fireEvent('race.remove_test')
                except Exception as e:
                    errors.append(e)

        def remove_and_readd():
            for _ in range(100):
                try:
                    removeEvent('race.remove_test')
                    addEvent('race.remove_test', lambda: 'result')
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=fire_loop)
        t2 = threading.Thread(target=remove_and_readd)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(errors) == 0, f"Errors: {errors}"


# ---------------------------------------------------------------------------
# 2. Concurrent HttpClient requests (shared dicts don't corrupt)
# ---------------------------------------------------------------------------

class TestConcurrentHttpClient:
    """HttpClient uses shared dicts (last_use, failed_request, etc.)
    protected by a lock. Verify they don't corrupt under concurrent access."""

    def test_concurrent_rate_limit_tracking(self):
        """Multiple threads updating last_use simultaneously."""
        from couchpotato.core.http_client import HttpClient
        client = HttpClient(time_between_calls=0)

        errors = []

        def update_last_use(host_id):
            try:
                host = f'host{host_id}.example.com'
                for _ in range(100):
                    with client._lock:
                        client.last_use[host] = time.time()
                        client.failed_request[host] = 0
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_last_use, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
        assert len(client.last_use) == 10

    def test_concurrent_failure_recording(self):
        """Multiple threads recording failures for different hosts."""
        from couchpotato.core.http_client import HttpClient
        client = HttpClient()

        errors = []
        barrier = threading.Barrier(5)

        def record_failures(host_id):
            barrier.wait()
            host = f'host{host_id}.example.com'
            try:
                for _ in range(20):
                    client._record_failure(host)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_failures, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
        # Each host should have recorded 20 failures
        for i in range(5):
            host = f'host{i}.example.com'
            assert client.failed_request.get(host) == 20

    def test_concurrent_check_disabled(self):
        """Multiple threads checking disabled status simultaneously."""
        from couchpotato.core.http_client import HttpClient
        client = HttpClient()
        # Pre-disable a host
        with client._lock:
            client.failed_disabled['disabled.example.com'] = time.time()

        errors = []

        def check(i):
            try:
                for _ in range(50):
                    client._check_disabled('disabled.example.com', show_error=True)
                    client._check_disabled('enabled.example.com', show_error=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=check, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0


# ---------------------------------------------------------------------------
# 3. Concurrent Plugin._running modifications
# ---------------------------------------------------------------------------

class TestConcurrentPluginRunning:
    """Plugin._running is a list modified by isRunning(). Must be thread-safe."""

    def test_concurrent_running_add_remove(self):
        """Multiple threads adding and removing running states."""
        from couchpotato.core.plugins.base import Plugin

        # Create a minimal plugin instance without full initialization
        plugin = Plugin.__new__(Plugin)
        plugin._running = []
        plugin._running_lock = threading.Lock()

        errors = []
        barrier = threading.Barrier(10)

        def add_remove(n):
            barrier.wait()
            key = f'task_{n}'
            try:
                for _ in range(50):
                    plugin.isRunning(key, True)
                    time.sleep(0.001)
                    plugin.isRunning(key, False)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_remove, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors: {errors}"
        # All tasks should have been removed
        assert len(plugin._running) == 0

    def test_isRunning_returns_copy(self):
        """isRunning() with no args should return a copy, not the original list."""
        from couchpotato.core.plugins.base import Plugin

        plugin = Plugin.__new__(Plugin)
        plugin._running = ['task_1', 'task_2']
        plugin._running_lock = threading.Lock()

        result = plugin.isRunning()
        assert result == ['task_1', 'task_2']
        # Should be a copy
        result.append('task_3')
        assert 'task_3' not in plugin._running

    def test_concurrent_isRunning_reads(self):
        """Multiple threads reading isRunning() while others modify it."""
        from couchpotato.core.plugins.base import Plugin

        plugin = Plugin.__new__(Plugin)
        plugin._running = []
        plugin._running_lock = threading.Lock()

        errors = []
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                try:
                    plugin.isRunning(f'w_{i}', True)
                    plugin.isRunning(f'w_{i}', False)
                    i += 1
                except Exception as e:
                    errors.append(e)

        def reader():
            while not stop.is_set():
                try:
                    running = plugin.isRunning()
                    assert isinstance(running, list)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]

        for t in threads:
            t.daemon = True
            t.start()

        time.sleep(0.5)
        stop.set()

        for t in threads:
            t.join(timeout=2)

        assert len(errors) == 0, f"Errors: {errors}"
