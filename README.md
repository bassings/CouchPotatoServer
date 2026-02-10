# CouchPotato

[![CI](https://github.com/bassings/CouchPotatoServer/actions/workflows/ci.yml/badge.svg)](https://github.com/bassings/CouchPotatoServer/actions/workflows/ci.yml)
[![Docker](https://github.com/bassings/CouchPotatoServer/actions/workflows/docker.yml/badge.svg)](https://github.com/bassings/CouchPotatoServer/actions/workflows/docker.yml)
[![Lint](https://github.com/bassings/CouchPotatoServer/actions/workflows/lint.yml/badge.svg)](https://github.com/bassings/CouchPotatoServer/actions/workflows/lint.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

Automatic NZB and torrent downloader for movies. Maintain a watchlist and CouchPotato will search for releases, then send them to SABnzbd, NZBGet, or your torrent client.

This is a **Python 3 fork** of the [archived original](https://github.com/CouchPotato/CouchPotatoServer), fully modernised and actively maintained.

## What's New in v3.0.0

- **Python 3.10+** (tested on 3.10 through 3.13)
- **Complete Python 2 to 3 migration** — every module updated, all legacy `unicode`/`bytes` issues resolved
- **457 tests** covering database operations, web framework, settings, events, concurrency, security, and performance
- **Security hardened** — rate limiting (300 req/min), API key validation, input sanitisation, directory traversal protection
- **Race condition fixes** — thread-safe database operations, proper locking, connection pool management
- **Dead provider cleanup** — removed 37+ defunct torrent/NZB providers and the dead `couchpotatoapi` service
- **TMDB-powered suggestions** — replaced the defunct couchpota.to API with local TMDB suggestions engine
- **Modern dependencies** from PyPI (no more vendored libraries)
- **Multi-stage Docker build** with NFS volume support
- **Ruff linting** with CI enforcement
- **CodernityDB fully patched** for Python 3 — `tree_index`, `hash_index`, `rr_cache`, bytes/str handling all fixed

## Quick Start

### Docker (recommended)

```bash
docker run -d \
  --name couchpotato \
  -p 5050:5050 \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -v /path/to/movies:/movies \
  -e TZ=Australia/Brisbane \
  -e PUID=1000 \
  -e PGID=1000 \
  bassings/couchpotato:latest
```

Or with Docker Compose:

```bash
curl -O https://raw.githubusercontent.com/bassings/CouchPotatoServer/master/docker-compose.yml
docker compose up -d
```

### From Source

```bash
git clone https://github.com/bassings/CouchPotatoServer.git
cd CouchPotatoServer
pip install -r requirements.txt
python3 CouchPotato.py
```

Open `http://localhost:5050/` in your browser.

## Migrating from Python 2

If you have an existing CouchPotato installation:

1. Back up your `data_dir` (database and settings)
2. Clone this repo and install dependencies
3. Point it at your existing config: `python3 CouchPotato.py --data_dir /path/to/data`
4. CodernityDB index files will be patched automatically on first run

See [UPGRADING.md](UPGRADING.md) for detailed migration instructions.

## Supported Integrations

### Download Clients
SABnzbd, NZBGet, Transmission, Deluge, qBittorrent, rTorrent, uTorrent, Synology Download Station

### Search Providers
**Torrent:** AlphaRatio, AwesomeHD, BitHDTV, HDBits, IPTorrents, PassThePopcorn, SceneTime, ThePirateBay, TorrentBytes, TorrentDay, TorrentLeech, TorrentPotato (Jackett), YTS
**NZB:** BinSearch, Newznab (compatible indexers)

### Notifications
Discord, Email, Emby, Kodi/XBMC, Plex, Pushbullet, Pushover, Slack, Telegram, Trakt, Webhook, and more

## Development

```bash
git clone https://github.com/bassings/CouchPotatoServer.git
cd CouchPotatoServer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Run tests
python -m pytest tests/ -q

# Run linter
ruff check .
```

## Documentation

Reference docs are in [`docs/reference/`](docs/reference/):

- [API.md](docs/reference/API.md) — REST API endpoints
- [DATABASE_SCHEMA.md](docs/reference/DATABASE_SCHEMA.md) — SQLite schema
- [DATA_MODEL.md](docs/reference/DATA_MODEL.md) — Document structure
- [PROVIDERS.md](docs/reference/PROVIDERS.md) — Search providers
- [DOWNLOADERS.md](docs/reference/DOWNLOADERS.md) — Download clients
- [NOTIFICATIONS.md](docs/reference/NOTIFICATIONS.md) — Notification services

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. Please ensure compatibility with Python 3.10+ and include tests where practical.

## License

[GPL-3.0](license.txt)
