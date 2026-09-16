#!/usr/bin/env python3
"""Small standalone health probe for a local CouchPotato instance."""

import sys
import time
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import urlopen


DEFAULT_BASE_URL = "http://localhost:5050"
DEFAULT_TIMEOUT = 10
DEFAULT_MAX_RESPONSE_TIME = 5.0
MAX_RESPONSE_BYTES = 64 * 1024
READ_CHUNK_BYTES = 8 * 1024


def _read_page_prefix(response, clock, deadline):
    """Read a bounded prefix until the latency deadline is observed."""
    content = bytearray()
    while len(content) < MAX_RESPONSE_BYTES:
        if clock() >= deadline:
            break
        remaining = MAX_RESPONSE_BYTES - len(content)
        chunk = response.read1(min(READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        content.extend(chunk)
        if b"CouchPotato" in content:
            break
    return bytes(content)


def check_health(
    base_url=DEFAULT_BASE_URL,
    timeout=DEFAULT_TIMEOUT,
    max_response_time=DEFAULT_MAX_RESPONSE_TIME,
    opener=urlopen,
    clock=time.monotonic,
):
    """Return human-readable failures for the one production-relevant probe."""
    started = clock()
    deadline = started + max_response_time
    try:
        with opener(
            f"{base_url.rstrip('/')}/",
            timeout=min(timeout, max_response_time),
        ) as response:
            status = response.getcode()
            content = _read_page_prefix(response, clock, deadline)
    except HTTPError as exc:
        status = exc.code
        content = b""
        exc.close()
    except (OSError, HTTPException):
        return ["root endpoint could not be reached"]

    elapsed = clock() - started
    failures = []
    if status != 200:
        failures.append(f"root endpoint returned HTTP {status}")
    elif b"CouchPotato" not in content:
        failures.append("root endpoint did not return a CouchPotato page")
    if elapsed >= max_response_time:
        failures.append(
            f"root endpoint took {elapsed:.2f}s (limit {max_response_time:.2f}s)"
        )
    return failures


def run_health_check():
    """Run the localhost probe and report a process-friendly result."""
    print("Running CouchPotato Health Check...")
    failures = check_health()
    if not failures:
        print("✓ CouchPotato is responding correctly.")
        return True

    print("✗ Health check failed:")
    for failure in failures:
        print(f"  - {failure}")
    return False


if __name__ == "__main__":
    sys.exit(0 if run_health_check() else 1)
