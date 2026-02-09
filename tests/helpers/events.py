"""Event system mocking helpers."""
from unittest.mock import MagicMock, patch


class MockEventBus:
    """A test double for the CouchPotato event system.

    Tracks all fired events and registered listeners, allowing tests
    to verify event-driven behavior without the full app running.
    """

    def __init__(self):
        self.fired = []
        self.listeners = {}

    def add(self, name, handler, priority=100):
        if name not in self.listeners:
            self.listeners[name] = []
        self.listeners[name].append({'handler': handler, 'priority': priority})

    def fire(self, name, *args, **kwargs):
        self.fired.append({'name': name, 'args': args, 'kwargs': kwargs})
        results = []
        for listener in sorted(self.listeners.get(name, []), key=lambda x: x['priority']):
            try:
                results.append(listener['handler'](*args, **kwargs))
            except Exception:
                pass
        if kwargs.get('single'):
            return results[0] if results else None
        return results

    def was_fired(self, name):
        return any(e['name'] == name for e in self.fired)

    def fire_count(self, name):
        return sum(1 for e in self.fired if e['name'] == name)

    def reset(self):
        self.fired.clear()
        self.listeners.clear()


def patch_events(event_bus=None):
    """Return context manager patches for addEvent and fireEvent."""
    bus = event_bus or MockEventBus()
    return (
        patch('couchpotato.core.event.addEvent', side_effect=bus.add),
        patch('couchpotato.core.event.fireEvent', side_effect=bus.fire),
        bus
    )
