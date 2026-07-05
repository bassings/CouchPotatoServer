"""Regression test for REG-003 item 1: global TLS validation must not be disabled.

couchpotato/core/_base/_core.py used to monkeypatch
`ssl._create_default_https_context = ssl._create_unverified_context` inside
`Core.__init__`, disabling certificate + hostname validation for every
stdlib HTTPS call made anywhere in the process for the lifetime of the app.
Instantiating Core must not alter the stdlib default HTTPS context.
"""
import ssl

from couchpotato.environment import Env


def test_instantiating_core_does_not_disable_ssl_verification(monkeypatch):
    from couchpotato.core._base._core import Core

    # Skip registering global SIGINT/SIGTERM handlers (unrelated side effect
    # of Core.__init__ that would clobber pytest's own signal handling).
    monkeypatch.setattr(Env, '_desktop', True)

    original_context_factory = ssl._create_default_https_context
    try:
        Core()

        ctx = ssl._create_default_https_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
    finally:
        ssl._create_default_https_context = original_context_factory
