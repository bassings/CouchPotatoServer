#!/usr/bin/env python3
"""Compute the next beta version string for the beta/prod release-channel
split (specs/FEAT-release-channels.md, Component 1).

Pure version arithmetic — this is the only real logic in the release
pipeline; the GitHub Actions workflows are YAML glue that call this script.

Algorithm:
    1. Parse every tag matching ``v?MAJOR.MINOR.PATCH(-beta.N)?``; ignore
       non-conforming tags.
    2. ``max_major`` = highest MAJOR across all parsed tags.
    3. Among tags with ``MAJOR == max_major``, ``max_minor`` = highest MINOR.
    4. ``next = (max_major, max_minor + 1, 0)``.
    5. If a tag ``vMAJOR.(max_minor+1).0-beta.N`` already exists (workflow
       re-run on an unchanged HEAD), emit ``-beta.(maxN+1)``; otherwise
       ``-beta.1``.
    6. If no conforming tags exist at all, emit ``0.1.0-beta.1``.
"""
import re
import subprocess
import sys

_TAG_RE = re.compile(
    r'^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-beta\.(?P<beta>\d+))?$'
)


def next_beta_version(tags: list[str]) -> str:
    """Return the next beta version string (no leading ``v``) given a list
    of existing tag names, per the algorithm documented above."""
    parsed = []
    for tag in tags:
        match = _TAG_RE.match(tag.strip())
        if not match:
            continue
        parsed.append((
            int(match.group('major')),
            int(match.group('minor')),
            int(match.group('patch')),
            int(match.group('beta')) if match.group('beta') else None,
        ))

    if not parsed:
        return '0.1.0-beta.1'

    max_major = max(major for major, _, _, _ in parsed)

    # Only stable tags advance the target minor: a beta tag already
    # represents the in-flight "next" version, so it must not push the
    # target past itself (otherwise a workflow re-run would skip a minor
    # instead of incrementing the beta suffix).
    stable_minors = [minor for major, minor, _, beta in parsed if major == max_major and beta is None]
    max_minor = max(stable_minors) if stable_minors else -1

    next_minor = max_minor + 1

    existing_betas = [
        beta for major, minor, patch, beta in parsed
        if major == max_major and minor == next_minor and patch == 0 and beta is not None
    ]

    next_beta = max(existing_betas) + 1 if existing_betas else 1

    return f'{max_major}.{next_minor}.0-beta.{next_beta}'


def _read_tags_from_git() -> list[str]:
    result = subprocess.run(
        ['git', 'tag'],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    if argv:
        tags = argv
    elif not sys.stdin.isatty():
        tags = [line for line in sys.stdin.read().splitlines() if line.strip()]
    else:
        tags = _read_tags_from_git()

    print(next_beta_version(tags))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
