# Contributing to CouchPotato

Contributions are welcome! Please ensure compatibility with Python 3.10+ and include tests where practical.

## Getting Started

1. Fork the repo and clone locally
2. Create a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt -r requirements-dev.txt`
4. Run tests: `python -m pytest tests/ -q`
5. Run linter: `ruff check .`

## Pull Requests

- Keep PRs focused on a single change
- Include tests for new functionality
- Ensure all existing tests pass
- Follow the existing code style

## Reporting Issues

Open a [GitHub issue](https://github.com/bassings/CouchPotatoServer/issues) with:
- Steps to reproduce
- Expected vs actual behaviour
- Python version and OS
- Relevant log output
