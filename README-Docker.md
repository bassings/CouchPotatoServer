# CouchPotato Docker Setup

This setup provides a containerized version of CouchPotato that can run with either Python 2 (current) or Python 3.12 (after upgrade).

## Quick Start

1. **Clone and build**:
   ```bash
   git clone <your-repo>
   cd CouchPotatoServer
   docker-compose up -d
   ```

2. **Access the web interface**:
   - Open http://localhost:5050 in your browser
   - Complete the setup wizard

## Configuration

### Environment Variables

- `PUID` - User ID (default: 1000)
- `PGID` - Group ID (default: 1000)  
- `TZ` - Timezone (default: UTC)

### Volume Mounts

- `/config` - Configuration files and database
- `/data` - Application data, logs, cache
- `/downloads` - Download directory (from your download client)
- `/movies` - Movies directory (where completed movies go)

### Directory Structure

```
./data/
├── config/          # Configuration files
│   └── settings.conf
├── app_data/        # Database, logs, cache
│   ├── database/
│   ├── logs/
│   └── cache/
├── downloads/       # Mount your download client's completed folder here
└── movies/          # Mount your movies library here
```

## Docker Compose

The included `docker-compose.yml` provides:
- CouchPotato service
- Proper volume mounts
- Network isolation
- Restart policies

### Customization

1. **Update paths in docker-compose.yml**:
   ```yaml
   volumes:
     - /path/to/your/downloads:/downloads
     - /path/to/your/movies:/movies
   ```

2. **Set your timezone**:
   ```yaml
   environment:
     - TZ=America/New_York
   ```

## Building

### Current (Python 2)
```bash
docker build -t couchpotato:python2 .
```

### After Python 3 Upgrade
```bash
docker build -t couchpotato:python3 .
```

## Upgrading to Python 3.12

This Docker setup is designed to work with both Python 2 and Python 3.12. The upgrade process will involve:

1. Updating the shebang in `CouchPotato.py`
2. Fixing Python 2/3 compatibility issues
3. Testing with the Docker container
4. Updating the Dockerfile to use Python 3.12

## Troubleshooting

### Permissions Issues
If you encounter permission issues:
```bash
# Check your host user ID
id $(whoami)

# Update PUID/PGID in docker-compose.yml to match
```

### Port Conflicts
If port 5050 is in use:
```bash
# Change the port mapping in docker-compose.yml
ports:
  - "8080:5050"  # Access via http://localhost:8080
```

### Logs
View container logs:
```bash
docker-compose logs couchpotato
```

### Shell Access
Access the container shell:
```bash
docker-compose exec couchpotato /bin/bash
```

## Development

For development, you can mount the source code:
```yaml
volumes:
  - .:/app
  - ./data/config:/config
  - ./data/app_data:/data
```

This allows you to make changes without rebuilding the image.