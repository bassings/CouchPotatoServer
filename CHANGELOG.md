# Changelog

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
