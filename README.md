# CouchPotato

[![CI](https://github.com/bassings/CouchPotatoServer/actions/workflows/ci.yml/badge.svg)](https://github.com/bassings/CouchPotatoServer/actions/workflows/ci.yml)
[![Docker](https://github.com/bassings/CouchPotatoServer/actions/workflows/docker.yml/badge.svg)](https://github.com/bassings/CouchPotatoServer/actions/workflows/docker.yml)

Automatic NZB and torrent downloader for movies. Maintain a watchlist and CouchPotato will search for releases, then send them to SABnzbd, NZBGet, or your torrent client.

This is a **Python 3 fork** of the [archived original](https://github.com/CouchPotato/CouchPotatoServer), fully modernised and actively maintained.

## What's Changed

- **Python 3.10+** (tested on 3.10 through 3.13)
- **FastAPI** replaces Tornado (with OpenAPI docs at `/docs`)
- **SQLite option** alongside the original CodernityDB
- **Modern dependencies** from PyPI (no more vendored libraries)
- **336 tests** across unit and integration suites
- **Multi-stage Docker build**

## Quick Start

### Docker (recommended)

```bash
docker run -d \
  -p 5050:5050 \
  -v /path/to/config:/config \
  -v /path/to/downloads:/downloads \
  -e TZ=Australia/Brisbane \
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

See [UPGRADING.md](UPGRADING.md) for migration instructions.

## Development

```bash
git clone https://github.com/bassings/CouchPotatoServer.git
cd CouchPotatoServer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q
```

Enable development mode in CP settings to get JS errors in the console instead of the log.

## Documentation

Reference docs are in [`docs/reference/`](docs/reference/):

- [API.md](docs/reference/API.md) -- REST API endpoints
- [DATABASE_SCHEMA.md](docs/reference/DATABASE_SCHEMA.md) -- SQLite schema
- [DATA_MODEL.md](docs/reference/DATA_MODEL.md) -- Document structure
- [PROVIDERS.md](docs/reference/PROVIDERS.md) -- Search providers
- [DOWNLOADERS.md](docs/reference/DOWNLOADERS.md) -- Download clients
- [NOTIFICATIONS.md](docs/reference/NOTIFICATIONS.md) -- Notification services

## Contributing

Contributions welcome. Please ensure compatibility with Python 3.10+ and include tests where practical.

## License

[GPL-3.0](license.txt)
