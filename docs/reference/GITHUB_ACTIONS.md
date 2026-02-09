# GitHub Actions CI/CD

This document describes the GitHub Actions workflows for CouchPotato Server.

## Overview

We have migrated from Travis CI to GitHub Actions for continuous integration and deployment. The new setup provides better integration with GitHub and more flexible build configurations.

## Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

**Triggers:**
- Push to `master` or `develop` branches
- Pull requests to `master` or `develop` branches

**Features:**
- **Multi-version testing**: Tests Python 3.8, 3.9, 3.10, 3.11, and 3.13
- **Node.js testing**: Tests with Node.js 18 and 20
- **Dependency caching**: Caches pip and npm dependencies for faster builds
- **Python compatibility tests**: Runs our comprehensive Python 3 compatibility test suite
- **Integration tests**: Tests the full application startup and web interface
- **Grunt tests**: Runs existing JavaScript/CSS build and test processes
- **Coverage reporting**: Uploads coverage to Coveralls (master branch only)

**Jobs:**
1. **test**: Main testing matrix across Python and Node.js versions
2. **docker-test**: Tests Docker container builds and functionality
3. **coverage**: Generates and uploads coverage reports

### 2. Docker Workflow (`.github/workflows/docker.yml`)

**Triggers:**
- Push to `master` branch (excluding documentation changes)
- Weekly scheduled builds (Sundays at 6 AM UTC)

**Features:**
- **Multi-platform builds**: Builds for `linux/amd64` and `linux/arm64`
- **Docker Hub integration**: Pushes images to Docker Hub
- **Build caching**: Uses GitHub Actions cache for faster builds
- **Container testing**: Tests the built container before pushing

**Images produced:**
- `bassings/couchpotato:develop` - Latest development build
- `bassings/couchpotato:master` - Latest master branch build

### 3. Release Workflow (`.github/workflows/release.yml`)

**Triggers:**
- Push of tags starting with `v` (e.g., `v1.0.0`)

**Features:**
- **Automated releases**: Creates GitHub releases with changelogs
- **Release artifacts**: Builds and uploads `.tar.gz` and `.zip` archives
- **Docker releases**: Builds and pushes tagged Docker images
- **Multi-platform Docker**: Supports AMD64 and ARM64 architectures

**Release artifacts:**
- Source code archives (tar.gz, zip)
- Docker images: `bassings/couchpotato:vX.X.X` and `bassings/couchpotato:latest`

## Required Secrets

To use all workflows, configure these repository secrets:

### Docker Hub (Required for Docker workflows)
- `DOCKER_USERNAME`: Docker Hub username
- `DOCKER_PASSWORD`: Docker Hub password or access token

### Coveralls (Optional, for coverage reporting)
- `COVERALLS_REPO_TOKEN`: Coveralls repository token (GitHub token is used by default)

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