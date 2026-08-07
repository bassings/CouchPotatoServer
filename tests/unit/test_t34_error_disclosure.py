"""T3.4: an API error must not hand the client the server's internals.

`Database.deleteDocument` and `updateDocument` returned
`traceback.format_exc()` as the response body -- absolute filesystem paths, the
module layout and library versions -- to anyone holding the api_key. That is
every third-party script and the userscript, not just the operator.

Also pins `fireEvent`'s list contract: its documented no-handler path returns
`[]`, but its outer exception handler fell out with an implicit `None`, so a
logged-and-recovered dispatch error became a `TypeError` several frames away in
callers that index the result directly.
"""
import types

import pytest


class TestTheDatabaseViewsDoNotLeakTracebacks:

    def _database(self):
        from couchpotato.core.database import Database

        db = Database.__new__(Database)
        db.indexes = {}
        db.db = None
        return db

    def _boom(self, monkeypatch, plugin):
        """Fail INSIDE the try block, not before it.

        `getDB()` is called before the `try` in both views, so making IT raise
        escapes the handler entirely and tests nothing -- which is what the
        first version of this did. The database operations themselves are what
        the handler wraps, so that is where the failure has to happen.
        """
        class ExplodingDB:
            def get(self, *a, **k):
                raise RuntimeError('/Volumes/Storage/home/someone/secret/path.py exploded')

            def update(self, *a, **k):
                raise RuntimeError('/Volumes/Storage/home/someone/secret/path.py exploded')

            def delete(self, *a, **k):
                raise RuntimeError('/Volumes/Storage/home/someone/secret/path.py exploded')

        monkeypatch.setattr(plugin, 'getDB', lambda: ExplodingDB())

    @pytest.mark.parametrize('view,kwargs', [
        ('deleteDocument', {'id': 'x'}),
        ('updateDocument', {'document': '{"_id": "x"}'}),
    ])
    def test_the_response_carries_no_traceback(self, monkeypatch, view, kwargs):
        plugin = self._database()
        self._boom(monkeypatch, plugin)

        result = getattr(plugin, view)(**kwargs)

        assert result['success'] is False
        body = repr(result)
        for leak in ('Traceback', 'File "', '/Volumes/', 'secret/path.py'):
            assert leak not in body, (
                '%s returned server internals to the client (%r): %r'
                % (view, leak, result)
            )

    def test_the_client_still_learns_the_request_failed(self):
        """Anti-vacuity: silence is not an acceptable substitute for a leak."""
        plugin = self._database()
        result = plugin.deleteDocument(id='')      # validation failure, no exception
        assert result['success'] is False
        assert result['error'], 'the client was told nothing at all'


class TestFireEventHonoursItsListContract:

    def test_a_failing_dispatch_returns_a_list_not_none(self, monkeypatch):
        """Callers index the result directly; None turns a recovered error into
        a TypeError several frames from the cause.

        The failure has to reach the OUTER handler. A first version of this test
        registered `None` as the handler, but `fireEvent` wraps each handler
        call in its own `except Exception` -- so that TypeError was swallowed
        per-handler, the function returned `[]` from its NORMAL path, and the
        test passed with the `return []` deleted. Caught by mutating the source
        and watching it stay green: a guard that cannot fail is worse than none.

        `mergeDicts` runs inside the outer `try` and after the per-handler loop,
        so making it raise is a faithful way to reach the handler under test.
        """
        from couchpotato.core import event as event_module

        def handler(*a, **k):
            return {'some': 'result'}

        def exploding_merge(*a, **k):
            raise RuntimeError('merge blew up inside the outer try')

        monkeypatch.setattr(event_module, 'events',
                            {'boom.event': [{'handler': handler, 'priority': 100}]})
        monkeypatch.setattr(event_module, 'mergeDicts', exploding_merge)

        result = event_module.fireEvent('boom.event', merge=True)

        assert result == [], (
            'fireEvent returned %r after a dispatch error; its no-handler path '
            'returns [] and callers do `[x for x in fireEvent(...)]`' % (result,)
        )
        assert result is not None
