# Downloaders Status

## Supported Downloaders

| Downloader | Type | Status | Notes |
|------------|------|--------|-------|
| SABnzbd | NZB | ✅ Active | Primary NZB downloader |
| NZBGet | NZB | ✅ Active | Alternative NZB downloader |
| Transmission | Torrent | ✅ Active | Primary torrent client |
| Deluge | Torrent | ✅ Active | Popular alternative |
| qBittorrent | Torrent | ✅ Active | Modern torrent client |
| rTorrent | Torrent | ✅ Active | Advanced torrent client |
| uTorrent | Torrent | ⚠️ Legacy | Still works but uTorrent itself is controversial |
| Blackhole | Both | ✅ Active | Watch-folder based, works with any client |

## Deprecated/Legacy Downloaders

| Downloader | Type | Status | Notes |
|------------|------|--------|-------|
| NZBVortex | NZB | ⚠️ Legacy | macOS-only, rarely updated |
| Pneumatic | NZB | ⚠️ Legacy | XBMC/Kodi addon, outdated |
| Synology | Both | ⚠️ Legacy | Synology Download Station |
| Put.io | Torrent | ⚠️ Legacy | Cloud download service |

## Removed Downloaders

| Downloader | Type | Status | Notes |
|------------|------|--------|-------|
| Hadouken | Torrent | 🗑️ Removed (2026-08-12) | Project abandoned since v5.2 (Aug 2015), GitHub org archived, `hdkn.net` dead. In this fork it never worked: five guaranteed crashes were found and fixed one at a time (T24, T27, T28, T29, T30) before the last one showed that no RPC call could ever succeed, on either protocol version — no configuration was reachable. Removed rather than repaired indefinitely for a client nobody could have been using. An existing install's `[hadouken]` section in `config.ini` is not migrated or deleted; it is left in place and never read by the running app. |

## Python 3 Changes

The following Python 3 compatibility fixes were applied across all downloaders:

- `import httplib` → `import http.client as httplib`
- `import cookielib` → `import http.cookiejar as cookielib`
- `import xmlrpclib` → `import xmlrpc.client as xmlrpclib`
- `from urlparse import urlparse` → `from urllib.parse import urlparse`
- `urllib2.HTTPPasswordMgrWithDefaultRealm` → `urllib.request.HTTPPasswordMgrWithDefaultRealm`
- `urllib2.HTTPBasicAuthHandler` → `urllib.request.HTTPBasicAuthHandler`
- `urllib2.HTTPCookieProcessor` → `urllib.request.HTTPCookieProcessor`
- `urllib.quote()` → `urllib.parse.quote()`
- Regex patterns converted to raw strings (`r'...'`)
- `is 'string'` → `== 'string'` comparisons fixed
- `distutils.version.LooseVersion` → `packaging.version.Version` (with fallback)

## Configuration

All downloaders are configured via the web UI under Settings → Downloaders.
Each downloader supports:

- **Enabled/Disabled** toggle
- **Host** and **Port** configuration
- **Authentication** (username/password)
- **Directory** settings
- **Remove on complete** options
- **Paused** mode (add paused)
- **Manual** mode (only for manual sends)
