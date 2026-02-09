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
| Hadouken | Torrent | ❌ Dead | Project abandoned |
| NZBVortex | NZB | ⚠️ Legacy | macOS-only, rarely updated |
| Pneumatic | NZB | ⚠️ Legacy | XBMC/Kodi addon, outdated |
| Synology | Both | ⚠️ Legacy | Synology Download Station |
| Put.io | Torrent | ⚠️ Legacy | Cloud download service |

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
