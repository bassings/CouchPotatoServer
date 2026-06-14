# Changelog

## v3.4.0 — Security Hardening & Alpine Image

### 🔒 Security

- **Container image migrated to Alpine** (`python:3.14-alpine`) — Trivy now reports **0 known CVEs** (the Debian base carried ~119 OS-package vulnerabilities, including HIGH/CRITICAL with no upstream fix). Image size roughly halved.
- **Removed `curl` from the image** — the Docker `HEALTHCHECK` now uses Python's stdlib `urllib`, eliminating `libcurl` and its recurring CVEs.
- **Reject malformed authentication cookies** — fixes the `hmac.compare_digest` non-ASCII `TypeError` path by comparing UTF-8 bytes.
- Reviewed and triaged all open CodeQL alerts (path-injection, clear-text-storage, weak-hash) — confirmed mitigated or false-positive and documented.

### ⬆️ Dependencies

- `cryptography` 48.0.0 → 49.0.0, `starlette` 1.2.1 → 1.3.1, `uvicorn` 0.48.0 → 0.49.0, `python-multipart` 0.0.30 → 0.0.32, `beautifulsoup4` 4.14.3 → 4.15.0, `filelock` 3.29.0 → 3.29.4; pinned `pyOpenSSL` 26.3.0.
- Dev: `ruff` ≥0.15.16, `vitest` 4.1.8.

### 🛠️ Other

- Respect URL base for new UI assets.
- Preserve empty JSON POST compatibility.
- Entrypoint now uses `su-exec` (Alpine) for privilege drop; removed dead `docker/entrypoint.sh`; `scripts/test-local.sh` aligned to the Alpine base.

## v3.0.0 — Python 3 Migration

Complete modernisation of CouchPotato Server, forked and upgraded from the original Python 2 codebase.

### 🚀 Major Changes

- **Python 2 → 3 migration** — Full codebase port to Python 3.10+, fixing bytes/str handling throughout
- **FastAPI replaces Tornado** — Modern async web framework with automatic API docs
- **Docker support** — Multi-stage Dockerfile with CI-driven builds and docker-compose examples

### 🔒 Security Hardening

- SSL verification enabled by default (per-provider opt-out)
- CORS middleware with configurable allowed origins
- Replaced all bare `except:` with `except Exception:`
- Thread-safe media locking (per-media-id lock manager)
- Thread-safe plugin running list with `threading.Lock`
- Fixed mutable default arguments

### 🗄️ Database

- CodernityDB Python 3 compatibility — deterministic hashing, bytes/str comparisons
- Fixed `tree_index` delete/update for bytes comparison
- Proper `RecordNotFound` handling in quality queries

### 🧹 Cleanup

- Removed dead providers and services
- Removed legacy Grunt build tooling
- Trimmed and modernised requirements
- Cleaned up legacy files and updated `.gitignore`

### 🛠️ Infrastructure

- GitHub Actions CI/CD — test, lint (ruff), and Docker build workflows
- Ruff linter configuration
- Modernised README documentation

### 🐛 Bug Fixes

- IMDB chart scraper fixes
- OMDB/TMDB API bytes/str handling
- File download path joining
- Log viewer display
- Poster image serving via `file.cache`
- Provider protocol detection
- Notification long-poll support
- Updater module loading and settings page rendering
