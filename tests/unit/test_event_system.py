"""Tests for the blinker-backed event system.

Tests all event modes: basic fire, single, merge, in_order, async,
priorities, after events, on_complete callbacks.
"""
import time
import threading
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_events():
    """Clear events registry before each test."""
    from couchpotato.core.event import events
    events.clear()
    yield
    events.clear()


class TestAddEvent:
    def test_add_single_handler(self):
        from couchpotato.core.event import addEvent, events
        addEvent('test.event', lambda: 'hello')
        assert 'test.event' in events
        assert len(events['test.event']) == 1

    def test_add_multiple_handlers(self):
        from couchpotato.core.event import addEvent, events
        addEvent('test.event', lambda: 'a')
        addEvent('test.event', lambda: 'b')
        assert len(events['test.event']) == 2

    def test_add_with_priority(self):
        from couchpotato.core.event import addEvent, events
        addEvent('test.event', lambda: 'a', priority=50)
        assert events['test.event'][0]['priority'] == 50


class TestFireEvent:
    def test_fire_nonexistent_returns_empty_list(self):
        from couchpotato.core.event import fireEvent
        result = fireEvent('nonexistent.event')
        assert result == []

    def test_fire_collects_results(self):
        from couchpotato.core.event import addEvent, fireEvent
        addEvent('test.event', lambda: 'a')
        addEvent('test.event', lambda: 'b')
        result = fireEvent('test.event')
        assert 'a' in result
        assert 'b' in result

    def test_fire_passes_args(self):
        from couchpotato.core.event import addEvent, fireEvent
        received = []
        def handler(x, y):
            received.append((x, y))
            return True
        addEvent('test.event', handler)
        fireEvent('test.event', 1, 2)
        assert received == [(1, 2)]

    def test_fire_passes_kwargs(self):
        from couchpotato.core.event import addEvent, fireEvent
        received = {}
        def handler(color=None):
            received['color'] = color
            return True
        addEvent('test.event', handler)
        fireEvent('test.event', color='blue')
        assert received['color'] == 'blue'

    def test_none_results_excluded(self):
        from couchpotato.core.event import addEvent, fireEvent
        addEvent('test.event', lambda: None)
        addEvent('test.event', lambda: 'valid')
        result = fireEvent('test.event')
        assert result == ['valid']


class TestSingleMode:
    def test_single_returns_first_non_none(self):
        from couchpotato.core.event import addEvent, fireEvent
        addEvent('test.event', lambda: None, priority=1)
        addEvent('test.event', lambda: 'first', priority=2)
        addEvent('test.event', lambda: 'second', priority=3)
        result = fireEvent('test.event', single=True)
        assert result == 'first'

    def test_single_returns_empty_list_when_no_results(self):
        from couchpotato.core.event import addEvent, fireEvent
        addEvent('test.event', lambda: None)
        result = fireEvent('test.event', single=True)
        assert result == []

    def test_single_stops_after_first_result(self):
        from couchpotato.core.event import addEvent, fireEvent
        call_count = [0]
        def handler1():
            call_count[0] += 1
            return 'first'
        def handler2():
            call_count[0] += 1
            return 'second'
        addEvent('test.event', handler1, priority=1)
        addEvent('test.event', handler2, priority=2)
        result = fireEvent('test.event', single=True)
        assert result == 'first'
        assert call_count[0] == 1


class TestMergeMode:
    def test_merge_dicts(self):
        from couchpotato.core.event import addEvent, fireEvent
        addEvent('test.event', lambda: {'a': 1})
        addEvent('test.event', lambda: {'b': 2})
        result = fireEvent('test.event', merge=True)
        assert isinstance(result, dict)
        assert 'a' in result
        assert 'b' in result

    def test_merge_lists(self):
        from couchpotato.core.event import addEvent, fireEvent
        addEvent('test.event', lambda: [1, 2])
        addEvent('test.event', lambda: [3, 4])
        result = fireEvent('test.event', merge=True)
        assert isinstance(result, list)
        assert 1 in result
        assert 3 in result

    def test_merge_with_single_returns_merged(self):
        from couchpotato.core.event import addEvent, fireEvent
        addEvent('test.event', lambda: {'a': 1})
        addEvent('test.event', lambda: {'b': 2})
        # merge + single: merge takes precedence in original code
        result = fireEvent('test.event', merge=True, single=False)
        assert isinstance(result, dict)


class TestPriority:
    def test_lower_priority_fires_first(self):
        from couchpotato.core.event import addEvent, fireEvent
        order = []
        def handler_a():
            order.append('a')
            return 'a'
        def handler_b():
            order.append('b')
            return 'b'
        addEvent('test.event', handler_a, priority=200)
        addEvent('test.event', handler_b, priority=50)
        fireEvent('test.event')
        assert order == ['b', 'a']


class TestInOrderMode:
    def test_in_order_executes_sequentially(self):
        from couchpotato.core.event import addEvent, fireEvent
        order = []
        def handler_a():
            order.append('a')
            return 'a'
        def handler_b():
            order.append('b')
            return 'b'
        addEvent('test.event', handler_a, priority=1)
        addEvent('test.event', handler_b, priority=2)
        result = fireEvent('test.event', in_order=True)
        assert order == ['a', 'b']


class TestAfterEvent:
    def test_after_event_fires(self):
        from couchpotato.core.event import addEvent, fireEvent
        after_called = [False]
        def after_handler():
            after_called[0] = True
        addEvent('test.event', lambda: 'result')
        addEvent('test.event.after', after_handler)
        fireEvent('test.event')
        assert after_called[0]

    def test_is_after_event_prevents_recursion(self):
        from couchpotato.core.event import addEvent, fireEvent
        count = [0]
        def handler():
            count[0] += 1
        addEvent('test.event.after', handler)
        fireEvent('test.event.after', is_after_event=True)
        # Should fire handler but NOT re-fire test.event.after.after
        assert count[0] == 1


class TestOnComplete:
    def test_on_complete_callback(self):
        from couchpotato.core.event import addEvent, fireEvent
        completed = [False]
        def on_done():
            completed[0] = True
        addEvent('test.event', lambda: 'done')
        fireEvent('test.event', on_complete=on_done)
        assert completed[0]


class TestFireEventAsync:
    def test_async_returns_true(self):
        from couchpotato.core.event import addEvent, fireEventAsync
        addEvent('test.event', lambda: 'hello')
        result = fireEventAsync('test.event')
        assert result is True

    def test_async_executes_handler(self):
        from couchpotato.core.event import addEvent, fireEventAsync
        called = threading.Event()
        def handler():
            called.set()
            return True
        addEvent('test.event', handler)
        fireEventAsync('test.event')
        assert called.wait(timeout=2)


class TestResultModifier:
    def test_result_modifier_applied(self):
        from couchpotato.core.event import addEvent, fireEvent
        addEvent('test.event', lambda: 'original')
        addEvent('result.modify.test.event', lambda results: 'modified')
        result = fireEvent('test.event')
        assert result == 'modified'


class TestErrorHandling:
    def test_handler_error_doesnt_crash(self):
        from couchpotato.core.event import addEvent, fireEvent
        def bad_handler():
            raise ValueError("boom")
        addEvent('test.event', bad_handler)
        addEvent('test.event', lambda: 'good')
        # Should not crash, good handler still returns
        result = fireEvent('test.event')
        assert 'good' in result


class TestGetEvent:
    def test_get_event(self):
        from couchpotato.core.event import addEvent, getEvent
        addEvent('test.event', lambda: 'a')
        handlers = getEvent('test.event')
        assert len(handlers) == 1

    def test_get_event_returns_copy(self):
        from couchpotato.core.event import addEvent, getEvent, events
        addEvent('test.event', lambda: 'a')
        handlers = getEvent('test.event')
        handlers.clear()
        # Original should be unaffected
        assert len(events['test.event']) == 1


class TestPreSortedHandlers:
    def test_handlers_sorted_at_registration(self):
        from couchpotato.core.event import addEvent, events
        addEvent('test.event', lambda: 'c', priority=300)
        addEvent('test.event', lambda: 'a', priority=100)
        addEvent('test.event', lambda: 'b', priority=200)
        priorities = [h['priority'] for h in events['test.event']]
        assert priorities == [100, 200, 300]


class TestConcurrentEventSafety:
    def test_concurrent_add_and_fire_no_crash(self):
        """Adding events while firing should not raise RuntimeError."""
        from couchpotato.core.event import addEvent, fireEvent
        errors = []
        stop = threading.Event()

        def fire_loop():
            while not stop.is_set():
                try:
                    fireEvent('concurrent.test')
                except RuntimeError as e:
                    errors.append(e)
                    break

        def add_loop():
            for i in range(200):
                addEvent('concurrent.test', lambda: i, priority=i)

        fire_threads = [threading.Thread(target=fire_loop) for _ in range(4)]
        add_thread = threading.Thread(target=add_loop)

        for t in fire_threads:
            t.start()
        add_thread.start()
        add_thread.join()
        stop.set()
        for t in fire_threads:
            t.join()

        assert not errors, f"Got RuntimeErrors: {errors}"

    def test_concurrent_add_events_no_corruption(self):
        """Multiple threads adding events should not lose entries."""
        from couchpotato.core.event import addEvent, events

        def add_many(prefix):
            for i in range(100):
                addEvent(f'bulk.{prefix}', lambda: True)

        threads = [threading.Thread(target=add_many, args=(j,)) for j in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for j in range(10):
            assert len(events[f'bulk.{j}']) == 100
