"""Tests for .gitleaks.toml and .gitleaksignore — the secret-scanning gate's config.

A secret scanner is only as good as its allowlist, and an allowlist is the
easiest place in a repo for a gate to quietly stop gating: every pattern you add
subtracts coverage, and nothing tells you what it subtracted. Two real defects
motivated this file:

  * `reports/` was unanchored, so it also matched `couchpotato/reports/` —
    excluding application code from the scan. `(^|/)` did NOT fix it (the `/`
    branch matches the interior slash); only a root `^` does.
  * A fingerprint in `.gitleaksignore` with no comment is indistinguishable from
    a suppressed real leak, so the "every entry must be justified" rule is
    enforced here rather than left to review.

These tests are pure-python — no docker, no network — so they run in the normal
unit suite. The end-to-end behaviour (gitleaks actually exiting non-zero) is
covered by `make check-secrets` in the gate and the `secrets` CI job.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".gitleaks.toml"
IGNORE = REPO_ROOT / ".gitleaksignore"

# Paths that MUST always be scanned. Anything matching an allowlist pattern here
# is a hole in the gate.
APPLICATION_PATHS = [
    "couchpotato/core/app.py",
    "couchpotato/api.py",
    "couchpotato/core/db/sqlite_adapter.py",
    "couchpotato/ui/templates/base.html",
    "couchpotato/static/scripts/ui/movie-filter.js",
    # Directory names that collide with build-output names — the actual bug.
    "couchpotato/reports/app.py",
    "couchpotato/coverage/app.py",
    "couchpotato/core/mutants/thing.py",
    "couchpotato/test-results/thing.py",
    "tests/unit/test_api_auth.py",
    "scripts/backup.sh",
    ".github/workflows/ci.yml",
]

# Paths that SHOULD be excluded: real local secrets, or vendored/generated noise.
EXCLUDED_PATHS = [
    ".config/config.ini",
    ".config/media.key",
    ".config/data/logs/CouchPotato.log",
    "data/config/media.key",
    ".e2e-data/config.ini",
    "test_data/sample.nfo",
    "node_modules/foo/index.js",
    "couchpotato/ui/node_modules/nested/index.js",
    ".venv/lib/python3.12/site-packages/x.py",
    "reports/mutation/stryker.html",
    "coverage/index.html",
    ".claude/worktrees/agent-abc/couchpotato/api.py",
]


LITERAL_STRING_RE = re.compile(r"'{3}(.*?)'{3}", re.DOTALL)


def allowlist_patterns() -> list[str]:
    """Extract the `paths = [...]` entries from the [allowlist] table.

    Matches TOML literal strings AND ordinary basic/single-quoted strings.
    Extracting only the literal form left a real hole: adding a plain
    `paths = ["couchpotato/reports/"]` — perfectly valid gitleaks config — widened
    the allowlist to exclude application code with every test still green.
    """
    text = CONFIG.read_text(encoding="utf-8")
    match = re.search(r"^paths\s*=\s*\[(.*?)^\]", text, re.MULTILINE | re.DOTALL)
    assert match, "could not find a `paths = [...]` array in .gitleaks.toml"

    body = match.group(1)
    patterns = LITERAL_STRING_RE.findall(body)
    # Blank the literal strings out first so the two styles cannot double-count.
    remainder = LITERAL_STRING_RE.sub("", body)
    patterns += re.findall(r'"([^"\n]*)"', remainder)
    patterns += re.findall(r"'([^'\n]*)'", remainder)
    return [p for p in patterns if p.strip()]


def test_no_other_suppression_mechanism_slips_in_unnoticed():
    """`paths` is not the only way to suppress findings.

    A `commits = [...]` allowlist, a `regexes`/`stopwords` entry, or a per-rule
    `[[rules.allowlists]]` block all silence findings without appearing in
    `paths`, so this file's application-code assertions would not see them. Fail
    loudly if one appears — not because it is necessarily wrong, but so it gets
    reviewed and the assertions extended.
    """
    text = CONFIG.read_text(encoding="utf-8")
    for mechanism, pattern in (
        ("commits", r"^\s*commits\s*="),
        ("regexes", r"^\s*regexes\s*="),
        ("stopwords", r"^\s*stopwords\s*="),
        ("per-rule allowlists", r"^\s*\[\[rules"),
    ):
        assert not re.search(pattern, text, re.MULTILINE), (
            f"a `{mechanism}` suppression was added to .gitleaks.toml. It bypasses "
            f"the application-code assertions in this file — extend them to cover "
            f"it, then update this test."
        )


def test_config_and_ignore_files_exist():
    assert CONFIG.is_file(), f"{CONFIG} missing — the secrets gate has no config"
    assert IGNORE.is_file(), f"{IGNORE} missing"


def test_uses_the_full_default_ruleset():
    text = CONFIG.read_text(encoding="utf-8")
    assert re.search(r"useDefault\s*=\s*true", text), (
        "the config must extend gitleaks' default rules; without it the scan "
        "only applies whatever custom rules are defined here (none)"
    )


def test_allowlist_is_not_empty_but_is_also_not_a_free_for_all():
    patterns = allowlist_patterns()
    assert patterns, "no allowlist patterns parsed — check the extraction regex"
    for pattern in patterns:
        assert pattern not in (".*", ".", "/", ""), f"catch-all allowlist pattern: {pattern!r}"


@pytest.mark.parametrize("path", APPLICATION_PATHS)
def test_application_code_is_never_allowlisted(path):
    """The gate must scan our own source, including dirs that share a name with
    build output (`couchpotato/reports/`, `couchpotato/coverage/`)."""
    for pattern in allowlist_patterns():
        assert not re.search(pattern, path), (
            f"allowlist pattern {pattern!r} excludes application path {path!r} — "
            f"secrets committed there would not be reported. Anchor it with `^` "
            f"(note `(^|/)` does NOT restrict to the repo root)."
        )


@pytest.mark.parametrize("path", EXCLUDED_PATHS)
def test_local_runtime_and_vendored_paths_are_allowlisted(path):
    """These hold genuine local secrets or vendored noise; without them a local
    `make check-secrets` drowns in hits from your own dev instance."""
    assert any(re.search(pattern, path) for pattern in allowlist_patterns()), (
        f"{path!r} is not covered by any allowlist pattern"
    )


def test_allowlisted_runtime_paths_are_actually_gitignored_and_untracked():
    """The allowlist is only safe because these can never reach the remote.

    If one of them ever becomes tracked, excluding it from the scan turns into
    hiding a live leak — so assert the premise rather than trusting the comment.
    """
    import subprocess

    for path in (".config", "data/config", ".e2e-data", "test_data"):
        target = REPO_ROOT / path
        if not target.exists():
            continue
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", path],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            f"{path} is TRACKED by git but allowlisted from secret scanning — "
            f"that combination hides real secrets. Untrack it or drop the allowlist entry."
        )


def test_every_gitleaksignore_fingerprint_is_justified_by_a_comment():
    """An unexplained fingerprint is indistinguishable from a suppressed real leak.

    Enforced mechanically rather than left to review discipline (global standard
    #9: prefer an enforced check over a remembered rule).
    """
    lines = IGNORE.read_text(encoding="utf-8").split("\n")
    unjustified = []

    for index, raw in enumerate(lines):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        # Walk back over blank lines to find a comment immediately above.
        justified = False
        for prev in range(index - 1, -1, -1):
            candidate = lines[prev].strip()
            if not candidate:
                continue
            justified = candidate.startswith("#")
            break
        if not justified:
            unjustified.append((index + 1, entry))

    assert not unjustified, (
        "these .gitleaksignore entries have no explanatory comment above them:\n"
        + "\n".join(f"  line {n}: {e}" for n, e in unjustified)
        + "\nEvery suppression needs a stated reason — otherwise a real leak can be "
        "silenced by adding one line."
    )


def test_gitleaksignore_fingerprints_are_well_formed_and_point_at_real_files():
    """A stale fingerprint suppresses nothing and hides that coverage moved.

    Format is `path:rule-id:line`.
    """
    entries = [
        ln.strip()
        for ln in IGNORE.read_text(encoding="utf-8").split("\n")
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert entries, "no fingerprints in .gitleaksignore (fine if truly none are needed)"

    for entry in entries:
        parts = entry.rsplit(":", 2)
        assert len(parts) == 3, f"malformed fingerprint (want path:rule:line): {entry!r}"
        path, _rule, line_no = parts
        assert line_no.isdigit(), f"fingerprint line number is not numeric: {entry!r}"
        target = REPO_ROOT / path
        assert target.is_file(), (
            f"fingerprint points at a file that no longer exists: {path} — remove the "
            f"suppression, or update it if the finding moved"
        )
        total_lines = len(target.read_text(encoding="utf-8", errors="replace").split("\n"))
        assert int(line_no) <= total_lines, (
            f"fingerprint {entry!r} names line {line_no} but {path} has only "
            f"{total_lines} lines — the suppression is stale"
        )
