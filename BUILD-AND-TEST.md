# Build and Test Instructions

## Quick Start

### 1. Build Both Containers
```bash
# Build Python 2.7 container (current working version)
docker build -f Dockerfile.python2 -t couchpotato:python2 .

# Build Python 3.12 container (for migration testing)
docker build -f Dockerfile -t couchpotato:python3 .
```

### 2. Test Python 2.7 Container
```bash
# Start container
docker run -d --name couchpotato-test -p 5050:5050 -v $(pwd)/data:/data couchpotato:python2

# Wait for startup
sleep 10

# Test web interface
curl -s -o /dev/null -w "HTTP %{http_code} - Response time: %{time_total}s" http://localhost:5050/
# Expected: HTTP 200 - Response time: ~0.006s

# Run health checks
docker exec couchpotato-test python2 couchpotato/simple_healthcheck.py

# Run full test suite
docker exec couchpotato-test python2 run_all_tests.py

# Clean up
docker stop couchpotato-test && docker rm couchpotato-test
```

### 3. Using Docker Compose

#### Production Setup (Python 2.7)
```bash
# Start CouchPotato with Python 2.7
docker-compose -f docker-compose.production.yml up -d couchpotato

# Access at http://localhost:5050
```

#### Development/Testing Setup
```bash
# Start Python 2.7 for development
docker-compose -f docker-compose.python2.yml up -d

# Test Python 3 migration (will fail until code is migrated)
docker-compose -f docker-compose.production.yml --profile testing up -d couchpotato-python3
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5050` | Host port for CouchPotato web interface |
| `PYTHON3_PORT` | `5051` | Host port for Python 3 testing |
| `CONFIG_PATH` | `./data/config` | Configuration directory |
| `DATA_PATH` | `./data/app_data` | Application data directory |
| `DOWNLOADS_PATH` | `./data/downloads` | Downloads directory |
| `MOVIES_PATH` | `./data/movies` | Movies directory |
| `TZ` | `UTC` | Timezone |
| `PUID` | `1000` | User ID |
| `PGID` | `1000` | Group ID |

## Test Results

### Build Status
- ✅ **Python 2.7 Container**: Builds successfully
- ✅ **Python 3.12 Container**: Builds successfully

### Runtime Status  
- ✅ **Python 2.7**: Runs successfully, all tests pass
- ❌ **Python 3.12**: Fails to start (expected - awaiting migration)

### Test Suite Results (Python 2.7)
```
✓ All Unit Tests: 29/29 PASSED
✓ Health Check Tests: 5/5 PASSED  
✓ Coverage Analysis: 27% baseline
✓ Web Interface: HTTP 200, ~0.006s response
✓ API Endpoints: Responding correctly
```

## Local Development Workflow

### Image Management
```bash
# List built images
docker images | grep couchpotato

# Clean up old images if needed
docker image prune -f

# Remove specific images
docker rmi couchpotato:python2
docker rmi couchpotato:python3
```

### Development Workflow
```bash
# Rebuild after code changes
docker build -f Dockerfile.python2 -t couchpotato:python2 .

# Quick test cycle
docker run --rm -p 5050:5050 couchpotato:python2
```

## Troubleshooting

### Container Won't Start
```bash
# Check logs
docker logs container-name

# Common issues:
# - Port already in use: Change PORT environment variable
# - Volume permissions: Ensure data directories exist and are writable
# - Missing dependencies: Rebuild container
```

### Web Interface Not Accessible
```bash
# Check container status
docker ps

# Check port mapping
docker port container-name

# Test internal connectivity
docker exec container-name curl -f http://localhost:5050/
```

### Test Failures
```bash
# Run specific test
docker exec container-name python2 -m nose couchpotato.environment_test

# Check test environment
docker exec container-name sh -c "cd /app && PYTHONPATH=/app/libs python2 -c 'import couchpotato; print(\"OK\")''"
```

## Migration Validation

After Python 3 migration is complete:

```bash
# Build migrated container
docker build -f Dockerfile -t couchpotato:python3-migrated .

# Test side-by-side
docker run -d --name cp-py2 -p 5050:5050 couchpotato:python2
docker run -d --name cp-py3 -p 5051:5050 couchpotato:python3-migrated

# Compare responses
curl -s http://localhost:5050/ > python2_response.html
curl -s http://localhost:5051/ > python3_response.html
diff python2_response.html python3_response.html

# Run test suites
docker exec cp-py2 python2 run_all_tests.py
docker exec cp-py3 python3 run_all_tests.py
```

## Next Steps

1. **Code Migration**: Follow the Python 3 upgrade plan in `PYTHON3-UPGRADE-PLAN.md`
2. **Test Validation**: Use the enhanced test suite during migration
3. **GitHub Workflow**: Push to bassings/CouchPotatoServer repository
4. **Local Deployment**: Use Docker Compose for local development