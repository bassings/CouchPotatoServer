# GitHub Actions CI/CD

This document describes the GitHub Actions workflows for CouchPotato Server.

## Overview

We have migrated from Travis CI to GitHub Actions for continuous integration and deployment. The new setup provides better integration with GitHub and more flexible build configurations.

## Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

**Triggers:**
- Push to `master` or `v2-to-v3-upgrade`
- Pull requests targeting these branches

**Features:**
- Python matrix: 3.12 and 3.13
- Tox + pytest with JUnit report artifacts
- Docker E2E smoke job (build + basic healthcheck)
- Optional pip-compile lock artifact (non-blocking)

**Jobs:**
1. tests: Tox matrix with JUnit artifact upload
2. docker-e2e: Build runtime image and run a simple healthcheck
3. build-artifacts: Build sdist/wheel and upload artifacts

### 2. Publish Workflow (`.github/workflows/publish.yml`)

**Triggers:**
- Push of tags:
  - `testpypi-*` → publishes to TestPyPI
  - `v*` → publishes to PyPI

**Features:**
- Injects version from tag into `pyproject.toml`
- Builds and publishes sdist/wheel

### (Deprecated) Docker-specific and Release workflows

Older docs referenced separate Docker and release workflows. The current setup uses a single CI workflow plus a tag-based publish workflow as described above.

## Required Secrets

To use all workflows, configure these repository secrets:

### Docker Hub (Required for Docker workflows)
- `DOCKER_USERNAME`: Docker Hub username
- `DOCKER_PASSWORD`: Docker Hub password or access token

### PyPI / TestPyPI (Optional)
- `PYPI_API_TOKEN`: PyPI API token
- `TEST_PYPI_API_TOKEN`: TestPyPI API token

## Environment Variables

The workflows automatically set these environment variables:

- `CI=true`: Indicates running in CI environment
- `GITHUB_ACTIONS=true`: Indicates running in GitHub Actions
- `PYTHONUNBUFFERED=1`: Ensures Python output is not buffered

## Migration from Travis CI

### Changes Made

1. **Removed Travis CI configuration** (`.travis.yml`)
2. **Updated README badges** to point to GitHub Actions
3. **Updated Gruntfile.js** to detect GitHub Actions environment
4. **Enhanced testing** with our Python 3 compatibility test suite
5. **Added Docker testing** and multi-platform builds
6. **Added automated releases** with Docker Hub integration

### Advantages over Travis CI

- **Faster builds**: Better resource allocation and caching
- **Tighter GitHub integration**: Native GitHub experience
- **More build minutes**: GitHub provides generous free tier
- **Multi-platform Docker builds**: ARM64 support out of the box
- **Better secret management**: GitHub repository secrets
- **Matrix builds**: More flexible build configurations

## Usage Examples

### Running Tests Locally

To run the same tests as CI:

```bash
# Python compatibility tests
python test_python3_compatibility.py

# Integration tests
python test_couchpotato_integration.py

# Run tests with coverage
pytest --cov=couchpotato --cov-report=html

# Grunt tests (requires Node.js and npm)
npm install
npx grunt test
npx grunt coverage
```

### Docker Testing

To test the Docker build locally:

```bash
# Build test image
docker-compose -f docker-compose.test.yml build

# Run tests
./test_docker_python3.sh
```

### Creating Releases

To create a new release:

1. Tag the commit: `git tag v1.0.0`
2. Push the tag: `git push origin v1.0.0`
3. GitHub Actions will automatically:
   - Run all tests
   - Create a GitHub release
   - Build and upload release artifacts
   - Build and push Docker images

## Troubleshooting

### Build Failures

1. **Check the Actions tab** in the GitHub repository
2. **Review the logs** for the failed job
3. **Check dependencies** - ensure all required packages are available
4. **Verify secrets** - ensure Docker Hub credentials are configured correctly

### Docker Build Issues

1. **Check Dockerfile.python3** for syntax errors
2. **Verify base image** availability
3. **Test locally** using `docker-compose -f docker-compose.test.yml build`

### Coverage Issues

1. **Check Coveralls integration** - ensure the service is properly configured
2. **Verify coverage files** are being generated
3. **Check Python coverage configuration**

## Support

For issues with the GitHub Actions setup:

1. Check the [GitHub Actions documentation](https://docs.github.com/en/actions)
2. Review workflow logs in the Actions tab
3. Open an issue in the repository with workflow logs attached 
