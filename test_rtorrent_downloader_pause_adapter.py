import types

from couchpotato.core.downloaders.rtorrent_ import rTorrent as RTDownloader


class _FakeAdapter:
    def __init__(self):
        self.paused = []
        self.resumed = []

    def pause_torrent(self, h):
        self.paused.append(h)
        return True

    def resume_torrent(self, h):
        self.resumed.append(h)
        return True


def test_pause_resume_use_adapter(monkeypatch):
    d = RTDownloader()
    monkeypatch.setattr(d, 'connect', lambda reconnect=False: True)
    d.rt = types.SimpleNamespace(find_torrent=lambda _id: None)
    fake = _FakeAdapter()
    d._rt_adapter = fake

    rel = {'id': 'HASH1', 'name': 'n'}
    assert d.pause(rel, pause=True) is True
    assert fake.paused == ['HASH1']
    assert d.pause(rel, pause=False) is True
    assert fake.resumed == ['HASH1']

