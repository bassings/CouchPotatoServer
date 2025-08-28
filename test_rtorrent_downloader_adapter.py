import types

from couchpotato.core.downloaders.rtorrent_ import rTorrent as RTDownloader


class _FakeAdapter:
    def __init__(self):
        self.removed = []

    def remove_torrent(self, torrent_hash):
        self.removed.append(torrent_hash)
        return True


class _FakeTorrent:
    directory = '/tmp'
    name = 'X'
    def get_files(self):
        return []
    def erase(self):
        raise AssertionError('should not be called when adapter present')


def test_downloader_uses_adapter_for_remove(monkeypatch):
    d = RTDownloader()

    # Avoid making a real connection
    monkeypatch.setattr(d, 'connect', lambda reconnect=False: True)

    # Provide fake rt object with find_torrent
    d.rt = types.SimpleNamespace(find_torrent=lambda _id: _FakeTorrent())

    # Inject adapter
    fake = _FakeAdapter()
    d._rt_adapter = fake

    rel = {'id': 'HASH1', 'name': 'n'}
    ok = d.processComplete(rel, delete_files=False)
    assert ok is True
    assert fake.removed == ['HASH1']

