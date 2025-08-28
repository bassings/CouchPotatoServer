from __future__ import annotations

"""
RTorrent adapter and transport abstraction.

This decouples CouchPotato from the concrete rTorrent XML-RPC/SCGI client.
Callers use RTorrentAdapter while the underlying Transport handles RPC.
"""

from typing import Any, Dict, List, Optional, Protocol


class Transport(Protocol):
    def call(self, method: str, *args: Any) -> Any:  # pragma: no cover - interface
        ...


class RTorrentAdapter:
    def __init__(self, transport: Transport):
        self._t = transport

    def add_torrent(self, magnet_or_url: str, start: bool = True, label: Optional[str] = None) -> Any:
        method = 'load.start' if start else 'load'
        res = self._t.call(method, magnet_or_url)
        if label:
            # In rTorrent, custom1 is commonly used as label
            # The caller is expected to set label later using set_label when hash is known
            pass
        return res

    def add_torrent_file(self, data: bytes, start: bool = True) -> Any:
        """Add a torrent file by raw bytes using rTorrent's raw methods.

        - start=True uses 'load.raw_start'
        - start=False uses 'load.raw'
        """
        method = 'load.raw_start' if start else 'load.raw'
        return self._t.call(method, data)

    def remove_torrent(self, torrent_hash: str, delete_data: bool = False) -> Any:
        # d.erase removes the torrent; deletion of data is often done via 'd.delete_tied' or manual file ops
        return self._t.call('d.erase', torrent_hash)

    def set_label(self, torrent_hash: str, label: str) -> Any:
        return self._t.call('d.custom1.set', torrent_hash, label)

    def get_torrent(self, torrent_hash: str) -> Dict[str, Any]:
        # Minimal info via individual calls; real impl can use d.multicall2
        name = self._t.call('d.name', torrent_hash)
        state = self._t.call('d.state', torrent_hash)
        return {'hash': torrent_hash, 'name': name, 'state': state}

    def list_torrents(self) -> List[str]:
        return self._t.call('download_list')

    def get_stats(self) -> Dict[str, Any]:
        version = self._t.call('system.client_version')
        return {'version': version}
