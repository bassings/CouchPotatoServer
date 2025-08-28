from couchpotato.clients.rtorrent.adapter import RTorrentAdapter


class FakeTransport:
    def __init__(self):
        self.calls = []

    def call(self, method, *args):
        self.calls.append((method, args))
        # Return dummy values for known calls
        if method == 'download_list':
            return ['HASH1', 'HASH2']
        if method == 'system.client_version':
            return '0.9.8'
        if method == 'd.name':
            return 'Example'
        if method == 'd.state':
            return 1
        return None


def test_add_magnet_and_remove_and_label():
    t = FakeTransport()
    rt = RTorrentAdapter(t)

    rt.add_torrent('magnet:?xt=urn:btih:HASH', start=True)
    assert t.calls[-1][0] == 'load.start'
    assert 'magnet:?xt=urn:btih:HASH' in t.calls[-1][1][0]

    rt.set_label('HASH', 'Movies')
    assert t.calls[-1] == ('d.custom1.set', ('HASH', 'Movies'))

    rt.remove_torrent('HASH')
    assert t.calls[-1] == ('d.erase', ('HASH',))


def test_list_and_stats_and_get():
    t = FakeTransport()
    rt = RTorrentAdapter(t)

    lst = rt.list_torrents()
    assert lst == ['HASH1', 'HASH2']

    stats = rt.get_stats()
    assert stats['version'] == '0.9.8'

    info = rt.get_torrent('HASH1')
    assert info['hash'] == 'HASH1'
    assert info['name'] == 'Example'
    assert info['state'] == 1

