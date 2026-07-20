#!/usr/bin/env python3
"""Compute the next beta version string for the beta/prod release-channel
split (specs/FEAT-release-channels.md, Component 1).

Pure version arithmetic — this is the only real logic in the release
pipeline; the GitHub Actions workflows are YAML glue that call this script.

Minor bump per commit: every build is strictly higher than the last, so beta
testers always see a new version. Algorithm:
    1. Parse every tag matching ``v?MAJOR.MINOR.PATCH(-beta.N)?``; ignore
       non-conforming tags.
    2. ``max_major`` = highest MAJOR across all parsed tags.
    3. ``max_minor`` = highest MINOR among tags with ``MAJOR == max_major``,
       counting BOTH stable and beta tags (a beta already occupies its minor,
       so the next build must go past it).
    4. Emit ``{max_major}.{max_minor + 1}.0-beta.1`` (suffix always ``.1``;
       minor numbers climb quickly by design). A re-run on an unchanged HEAD
       harmlessly bumps the minor again — never a collision.
    5. If no conforming tags exist at all, emit ``0.1.0-beta.1``.
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

    # Highest minor within the top major, counting BOTH stable and beta tags:
    # every commit must produce a strictly higher version (minor bump per
    # commit), so an in-flight beta advances the target past itself.
    max_minor = max(minor for major, minor, _, _ in parsed if major == max_major)

    return f'{max_major}.{max_minor + 1}.0-beta.1'


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
