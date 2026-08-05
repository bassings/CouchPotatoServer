# Contributing to CouchPotato Server

## Requirements

- Python 3.10+
- Docker (recommended for local development)

## Getting Started

```bash
# Clone and install
git clone https://github.com/bassings/CouchPotatoServer.git
cd CouchPotatoServer
pip install -r requirements.txt

# Or use Docker
docker compose up
```

`docker compose up` picks its compose file from `.env` (`COMPOSE_FILE=...`),
which is a local dev toggle, not a secret — it is gitignored and not tracked,
so a fresh clone starts without it and falls back to the default compose file
(the published image, not a local build). Restore it with:

```bash
echo COMPOSE_FILE=docker-compose.local.yml > .env
```

## Running Tests

```bash
pytest
```

## Code Style

- Linted with [ruff](https://github.com/astral-sh/ruff) — run `ruff check .` before submitting
- [Conventional commits](https://www.conventionalcommits.org/) preferred (`feat:`, `fix:`, `chore:`, etc.)

## Pull Requests

1. Fork the repo and create a feature branch
2. Make your changes with clear, conventional commit messages
3. Ensure `pytest` and `ruff check` pass
4. Open a PR against `master`
