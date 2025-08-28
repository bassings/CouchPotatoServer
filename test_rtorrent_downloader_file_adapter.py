import types

from couchpotato.core.downloaders.rtorrent_ import rTorrent as RTDownloader


class _FakeAdapter:
    def __init__(self):
        self.add_file_calls = []
        self.set_label_calls = []

    def add_torrent_file(self, data, start=True):
        self.add_file_calls.append((data, start))
        return True

    def set_label(self, h, label):
        self.set_label_calls.append((h, label))
        return True


def test_file_download_uses_adapter(monkeypatch):
    d = RTDownloader()

    # Avoid real connection
    monkeypatch.setattr(d, 'connect', lambda reconnect=False: True)

    # Inject conf behavior
    conf = {'paused': 0, 'label': 'Movies'}
    d.conf = lambda name, default=None: conf.get(name, default)

    # Provide fake rt object (should not be used on adapter path)
    d.rt = types.SimpleNamespace(load_torrent=lambda *args, **kw: None)

    # Inject adapter
    fake = _FakeAdapter()
    d._rt_adapter = fake

    # Minimal bencoded structure sufficient to compute hash
    from couchpotato.core.downloaders.rtorrent_ import bencode
    info = {'name': 'X', 'length': 1, 'piece length': 16384, 'pieces': ''}
    filedata = bencode({'info': info})

    data = {
        'protocol': 'torrent',
        'url': 'file://dummy',
        'name': 'X'
    }

    ok = d.download(data=data, media={}, filedata=filedata)
    assert ok
    # Adapter add_torrent_file should be called
    assert fake.add_file_calls and fake.add_file_calls[0][1] is True
    # Label should have been set via adapter with computed hash
    assert fake.set_label_calls

