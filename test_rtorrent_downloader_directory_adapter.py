import types

from couchpotato.core.downloaders.rtorrent_ import rTorrent as RTDownloader


class _FakeAdapter:
    def __init__(self):
        self.setdir = []
        self.setlabel = []

    def add_torrent_file(self, data, start=True):
        return True

    def set_label(self, h, label):
        self.setlabel.append((h, label))
        return True

    def set_directory(self, h, directory):
        self.setdir.append((h, directory))
        return True


def test_directory_set_uses_adapter(monkeypatch):
    d = RTDownloader()
    monkeypatch.setattr(d, 'connect', lambda reconnect=False: True)

    conf = {'paused': 0, 'label': 'Movies', 'directory': '/downloads'}
    d.conf = lambda name, default=None: conf.get(name, default)

    d.rt = types.SimpleNamespace(load_torrent=lambda *args, **kw: None)

    fake = _FakeAdapter()
    d._rt_adapter = fake

    # Minimal bencoded structure sufficient to compute hash
    from couchpotato.core.downloaders.rtorrent_ import bencode
    info = {'name': 'X', 'length': 1, 'piece length': 16384, 'pieces': ''}
    filedata = bencode({'info': info})

    data = {'protocol': 'torrent', 'url': 'file://dummy', 'name': 'X'}
    ok = d.download(data=data, media={}, filedata=filedata)
    assert ok

    # Directory and label set via adapter
    assert fake.setdir and fake.setdir[0][1] == '/downloads'
    assert fake.setlabel and fake.setlabel[0][1] == 'Movies'

