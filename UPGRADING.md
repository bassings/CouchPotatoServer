# Upgrading to CouchPotato Python 3

This guide covers migrating from the legacy Python 2 version to the modernized Python 3 version.

## Requirements

- **Python 3.9+** (3.12+ recommended)
- All dependencies installed from `requirements.txt`

## Before You Start

### 1. Back Up Everything

```bash
# Back up your database and settings
cp -r ~/.couchpotato ~/.couchpotato.backup

# Or if using Docker volumes:
docker cp couchpotato:/config ./config-backup
docker cp couchpotato:/data ./data-backup
```

### 2. Note Your Settings

Record your current configuration, especially:
- API key (Settings → General)
- Downloader settings (host, port, credentials)
- Notification settings
- Quality profiles
- Library paths

## Upgrade Steps

### From Source

```bash
# Stop the running instance
kill $(cat ~/.couchpotato/couchpotato.pid)

# Back up (if not done already)
cp -r ~/.couchpotato ~/.couchpotato.backup

# Pull the latest code
cd /path/to/CouchPotatoServer
git pull

# Create a virtual environment with Python 3
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start CouchPotato
python3 CouchPotato.py
```

### Docker

```bash
# Pull the new image
docker pull couchpotato/couchpotatoserver:latest

# Stop and remove the old container
docker stop couchpotato
docker rm couchpotato

# Start with the same volumes
docker run -d \
  --name couchpotato \
  -p 5050:5050 \
  -v /path/to/config:/config \
  -v /path/to/data:/data \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=America/New_York \
  couchpotato/couchpotatoserver:latest
```

## Database Migration

The SQLite database (`couchpotato.db`) is compatible between versions. No manual migration
is needed. On first run, any necessary schema updates are applied automatically.

If you were using the legacy CodernityDB, the migration to SQLite happens automatically
on first startup. **Do not delete your old database files** until you've verified the
migration was successful.

## Breaking Changes

### Removed Python 2 Dependencies
- `urllib2` → `urllib.request` / `urllib.error`
- `httplib` → `http.client`
- `cookielib` → `http.cookiejar`
- `xmlrpclib` → `xmlrpc.client`
- `urlparse` → `urllib.parse`

These are internal changes and don't affect the API or settings.

### Dead Providers Removed/Deprecated
The following providers are no longer functional (sites shut down):
- RARBG, KickAssTorrents, TorrentShack, SceneAccess, BitSoup, MoreThanTV
- NZBClub, OmgWtfNzbs
- See `docs/PROVIDERS.md` for the full status matrix

### Web Framework
- Tornado replaced with FastAPI (Uvicorn)
- API endpoints remain the same
- OpenAPI docs available at `/docs`

## Rollback

If something goes wrong:

```bash
# Stop the new version
kill $(cat ~/.couchpotato/couchpotato.pid)

# Restore backup
rm -rf ~/.couchpotato
mv ~/.couchpotato.backup ~/.couchpotato

# Switch back to the old code
cd /path/to/CouchPotatoServer
git checkout <previous-branch-or-tag>

# Run with Python 2
python CouchPotato.py
```

## Troubleshooting

### "Module not found" errors
Make sure you've installed all dependencies:
```bash
pip install -r requirements.txt
```

### Database locked
Stop any other CouchPotato instances before starting.

### API key changed
The API key is preserved in `settings.conf`. If it changed, check the web UI
under Settings → General.

### Provider not working
Check `docs/PROVIDERS.md` — many torrent/NZB sites have shut down.
Consider using Jackett or Prowlarr with the TorrentPotato/Newznab provider.
