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

    def set_directory(self, torrent_hash: str, directory: str) -> Any:
        return self._t.call('d.directory.set', torrent_hash, directory)

    def pause_torrent(self, torrent_hash: str) -> Any:
        return self._t.call('d.pause', torrent_hash)

    def resume_torrent(self, torrent_hash: str) -> Any:
        return self._t.call('d.resume', torrent_hash)

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

    def list_torrents_full(self) -> List[Dict[str, Any]]:
        """Return detailed info for torrents using multicall.

        Attempts d.multicall2 first, falling back to d.multicall.
        For each torrent, fetches file paths via f.multicall2/f.multicall.
        """
        fields = ['d.hash=', 'd.name=', 'd.directory=', 'd.ratio=', 'd.state=',
                  'd.complete=', 'd.open=', 'd.left_bytes=', 'd.down.rate=']
        try:
            rows = self._t.call('d.multicall2', '', 'main', *fields)
        except Exception:
            # Older API
            rows = self._t.call('d.multicall', 'main', *fields)

        results: List[Dict[str, Any]] = []
        for row in rows or []:
            # row is a list aligned with fields
            try:
                (h, name, directory, ratio, state, complete, open_, left, down_rate) = row
            except Exception:
                # Defensive: skip malformed rows
                continue

            # files
            try:
                files = self._t.call('f.multicall2', h, '', 'f.path=')
            except Exception:
                files = self._t.call('f.multicall', h, 'f.path=')

            file_paths = []
            for f in files or []:
                # f may be a list with first element the path
                if isinstance(f, (list, tuple)) and f:
                    file_paths.append(str(f[0]))
                elif isinstance(f, (str, bytes)):
                    file_paths.append(f.decode('utf-8', 'ignore') if isinstance(f, (bytes, bytearray)) else f)

            results.append({
                'hash': h,
                'name': name,
                'directory': directory,
                'ratio': ratio,
                'state': state,
                'complete': bool(complete),
                'open': bool(open_),
                'left_bytes': int(left) if left is not None else 0,
                'down_rate': int(down_rate) if down_rate is not None else 0,
                'files': file_paths,
            })

        return results
