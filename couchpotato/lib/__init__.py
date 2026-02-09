# Internal vendored libraries that have no suitable PyPI replacement.
# Add this directory to sys.path so internal imports within these
# libraries (e.g. "from rtorrent.common import ...") continue to work.
import os
import sys

_lib_dir = os.path.dirname(__file__)
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)
