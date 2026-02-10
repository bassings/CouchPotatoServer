"""Shim replacing the dead `logr` package with stdlib logging."""

import logging

Logr = logging.getLogger('caper')
