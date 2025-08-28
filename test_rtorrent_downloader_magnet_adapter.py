import types

from couchpotato.core.downloaders.rtorrent_ import rTorrent as RTDownloader


class _FakeAdapter:
    def __init__(self):
        self.add_calls = []
        self.set_label_calls = []

    def add_torrent(self, url, start=True, label=None):
        self.add_calls.append((url, start, label))
        return True

    def set_label(self, h, label):
        self.set_label_calls.append((h, label))
        return True


def test_magnet_download_uses_adapter(monkeypatch):
    d = RTDownloader()

    # Avoid real connection
    monkeypatch.setattr(d, 'connect', lambda reconnect=False: True)

    # Inject conf behavior
    conf = {'paused': 0, 'label': 'Movies'}
    d.conf = lambda name, default=None: conf.get(name, default)

    # Provide fake rt object (should not be used on adapter path)
    d.rt = types.SimpleNamespace(load_magnet=lambda *args, **kw: None)

    # Inject adapter
    fake = _FakeAdapter()
    d._rt_adapter = fake

    data = {
        'protocol': 'torrent_magnet',
        'url': 'magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567',
        'name': 'X'
    }

    ok = d.download(data=data, media={}, filedata=None)
    assert ok

    # Adapter add_torrent should be called with start=True
    assert fake.add_calls and fake.add_calls[0][1] is True
    # Label set on computed torrent hash
    assert fake.set_label_calls and fake.set_label_calls[0][0] == '0123456789ABCDEF0123456789ABCDEF01234567'

