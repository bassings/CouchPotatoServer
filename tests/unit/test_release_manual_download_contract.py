"""Public route and notification contracts for manual release downloads."""

from importlib import import_module
from types import SimpleNamespace

import pytest


release_main = import_module('couchpotato.core.plugins.release.main')


def test_release_registers_the_manual_download_route_with_its_documented_id(monkeypatch):
    routes = []
    events = []
    scheduled = []

    def register_route(name, handler, docs):
        routes.append((name, handler, docs))

    def register_event(name, handler, **kwargs):
        events.append((name, handler, kwargs))

    def schedule(event, *args, **kwargs):
        scheduled.append((event, args, kwargs))

    monkeypatch.setattr(release_main, 'addApiView', register_route)
    monkeypatch.setattr(release_main, 'addEvent', register_event)
    monkeypatch.setattr(release_main, 'fireEvent', schedule)

    release = release_main.Release()

    manual = [(name, handler, docs) for name, handler, docs in routes if name == 'release.manual_download']
    assert len(manual) == 1
    assert manual[0][1] == release.manualDownload
    assert manual[0][2]['params']['id'] == {
        'type': 'id',
        'desc': 'ID of the release object in release-table',
    }
    assert len(events) == 11
    assert scheduled == [
        ('schedule.interval', ('movie.clean_releases', release.cleanDone), {'hours': 12}),
    ]


@pytest.mark.parametrize('success', [False, True])
def test_manual_download_emits_exact_notifications(monkeypatch, success):
    item = {
        'name': 'Example Release',
        'url': 'https://indexer.example/release',
        'protocol': 'nzb',
    }
    movie = {'_id': 'media-1'}
    release = {'_id': 'release-1', 'media_id': movie['_id'], 'info': item}

    class FakeDB:
        def get(self, index, document_id):
            assert index == 'id'
            assert document_id in {'release-1', 'media-1'}
            return release if document_id == 'release-1' else movie

    provider = SimpleNamespace(urls={}, download=lambda **_kwargs: b'data')
    notifications = []
    provider_lookups = []
    downloads = []

    def fire_event(event, *args, **kwargs):
        if event == release_main.NOTIFY_FRONTEND:
            assert args == ()
            assert kwargs['type'] == 'release.manual_download'
            assert kwargs['data'] is True
            notifications.append(kwargs['message'])
            return None
        assert event == 'provider.belongs_to'
        assert args == (item['url'],)
        assert kwargs == {'provider': None, 'single': True}
        provider_lookups.append(True)
        return provider

    def download(_self, *, data, media, manual):
        assert data is item
        assert media is movie
        assert manual is True
        assert data['download'] is provider.download
        downloads.append(True)
        return success

    monkeypatch.setattr(release_main, 'get_db', lambda: FakeDB())
    monkeypatch.setattr(release_main, 'fireEvent', fire_event)
    monkeypatch.setattr(release_main.Release, 'download', download)

    result = release_main.Release.manualDownload(object.__new__(release_main.Release), id='release-1')

    assert result == {'success': success}
    assert provider_lookups == [True]
    assert downloads == [True]
    assert notifications == (
        ['Snatching "Example Release"', 'Successfully snatched "Example Release"']
        if success else ['Snatching "Example Release"']
    )
