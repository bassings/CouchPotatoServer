"""Renamer plugin package.

Split from the monolithic renamer.py into focused modules:
- main.py: Renamer class (core scan logic)
- mover.py: File moving/linking operations
- namer.py: Naming pattern replacement
- extractor.py: Archive extraction
- cleanup.py: Tag/untag/cleanup operations
- api.py: API endpoints and configuration
"""
from couchpotato.core.plugins.renamer.main import Renamer  # noqa: F401
from couchpotato.core.plugins.renamer.api import config, rename_options  # noqa: F401

autoload = 'Renamer'
