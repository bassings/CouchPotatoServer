#!/usr/bin/env python3
"""Static conformance checker for the modern UI templates.

Scans ``couchpotato/ui/templates/**/*.html`` for design-system drift that has
previously regressed into the modern UI (see ``docs/design-system/README.md``,
``docs/design-system/CONFORMANCE.md``, ``specs/UI-CONFORM-01-toggle-normalize.md``
and ``specs/UI-CONFORM-02-ci-guardrail.md``). Pure stdlib, no dependencies, so
it runs fast as a standalone CI gate.

Checks performed:

  1. Off-spec toggle sizing — the only sanctioned toggle is track ``w-8 h-4``,
     knob ``w-3 h-3``, knob offset ``translate-x-4`` (on) / ``translate-x-0.5``
     (off). The old ``w-10 h-5`` track / ``translate-x-5`` knob offset is
     exactly the drift UI-CONFORM-01 fixed in ``wizard.html`` — flag it if it
     ever comes back, whether in a static ``class="..."`` or a dynamic Alpine
     ``:class="..."`` binding.
  2. Legacy icon-font classes — the modern UI uses inline Heroicon SVGs, not
     icon-font classes (``icon-download``, ``icon-emo-coffee``, ...).
  3. Raw hex colors used as Tailwind arbitrary values (``bg-[#ff0000]``) or in
     inline ``style="..."`` declarations — the modern UI uses the ``cp-*``
     design tokens / CSS custom properties defined once in ``base.html``.

Scoping / deliberate non-flags:

  Rules 2 and 3 only look inside ``class="..."``, Alpine ``:class="..."`` /
  ``x-bind:class="..."``, and ``style="..."`` / ``:style="..."`` HTML
  attribute *values* (see ``ATTR_RE``). This is what excludes, for free, the
  legitimate token *definitions* in ``base.html``:
    - the ``tailwind.config = {...}`` ``<script>`` block (JS object literal,
      not a ``class=``/``style=`` attribute),
    - the ``:root`` / ``:root.light`` ``<style>`` block (a ``<style>`` *tag*,
      never a ``style="..."`` *attribute*),
    - ``<meta name="theme-color" content="#...">`` (a ``content=`` attribute),
    - hex inside SVG ``fill="..."``/``stroke="..."`` attributes (neither
      attribute name ends in ``class`` or ``style``).
  No line-based or file-based exclusion list is needed as a result. If a
  legitimate new usage ever trips a rule, narrow the rule (e.g. the attribute
  scoping above) rather than special-casing a template.

Usage:
    python scripts/check_conformance.py [path ...]

With no arguments, scans ``couchpotato/ui/templates`` recursively plus the
ported ``couchpotato/templates/login.html``. Arguments may be individual
``.html`` files or directories (scanned recursively).
Exits 0 with a one-line summary when clean, or non-zero after printing one
``file:line: message`` per finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "couchpotato" / "ui" / "templates"
# The ported login page lives in the legacy templates dir but is now a
# design-system page, so it must be guarded too. We add just this one file
# explicitly rather than scanning the whole couchpotato/templates/ dir (login.html
# is currently the only file there — the legacy index.html was retired in
# UI-CLEANUP-02 — but scoping to the file keeps the intent explicit).
LOGIN_TEMPLATE = REPO_ROOT / "couchpotato" / "templates" / "login.html"
DEFAULT_ROOTS = [DEFAULT_ROOT, LOGIN_TEMPLATE]

# --- Rule 1: off-spec toggle sizing -----------------------------------------
# Literal substrings lifted from the pre-UI-CONFORM-01 wizard toggles. \b
# word boundaries stop e.g. "translate-x-5" from also matching an unrelated
# "translate-x-50"/"translate-x-5xx" style utility, and stop "w-10 h-5" from
# matching inside "w-10 h-50" (not that Tailwind has such a scale, but belt
# and suspenders). Intentionally NOT scoped to class attributes: the
# regression this guards against showed up in a dynamic Alpine
# `:class="cond ? 'translate-x-5' : ...'"` binding just as often as a static
# `class="..."`, so a plain whole-file scan for these specific, unambiguous
# strings is both simpler and more robust than trying to enumerate every
# attribute flavor that could carry a class-like string.
TOGGLE_RE = re.compile(r"\bw-10 h-5\b|\btranslate-x-5\b")

# --- Rules 2 & 3: attribute-scoped checks -----------------------------------
# Matches the *value* of any attribute whose name ends in "class" or "style"
# — class="...", :class="...", x-bind:class="...", style="...",
# :style="..." — static or Alpine-bound alike. Accepts either quote style
# (double or single) so a future single-quoted attribute can't silently bypass
# the icon-font / hex-color rules; the quote char is group(1), the value is
# group(2). See the module docstring for why scoping to these attributes is what
# excludes base.html's legitimate token definitions without an exclusion list.
# re.DOTALL so the value capture spans newlines: multi-line ``:class="{ ... }"``
# Alpine object bindings (e.g. base.html's toast classes) would otherwise fail
# to match at all, silently skipping the icon-font / hex checks for their
# contents. With DOTALL the `(?:(?!\1).)*` still stops at the closing quote.
ATTR_RE = re.compile(
    r"""[:\w.-]*\b(?:class|style)\s*=\s*(["'])((?:(?!\1).)*)\1""", re.DOTALL
)

# Legacy icon-font token: a whole class token starting with "icon-". The
# lookbehind treats anything that isn't a word char or hyphen as a boundary, so
# it catches icon-* whether space-separated (class="a icon-x") OR quoted inside
# an Alpine object binding (:class="{ 'icon-x': cond }"), while still not
# matching a substring like "my-icon-x". Kept from matching legit non-class
# uses (e.g. static/icons/icon-192.png) by ATTR_RE only scanning class/style.
ICON_FONT_RE = re.compile(r"(?<![\w-])icon-[\w-]+")

# Raw hex color literal, e.g. #fff or #35c5f4, as a standalone token.
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return sorted (line_number, message) drift findings for one template."""
    findings: list[tuple[int, str]] = []
    text = path.read_text(encoding="utf-8")

    for match in TOGGLE_RE.finditer(text):
        line_no = text.count("\n", 0, match.start()) + 1
        findings.append((
            line_no,
            f"off-spec toggle sizing {match.group(0)!r} "
            "(only the w-8 h-4 / w-3 h-3 / translate-x-4 toggle is sanctioned; "
            "use partials/settings/toggle.html)",
        ))

    for attr_match in ATTR_RE.finditer(text):
        value = attr_match.group(2)
        line_no = text.count("\n", 0, attr_match.start()) + 1

        icon_match = ICON_FONT_RE.search(value)
        if icon_match:
            findings.append((
                line_no,
                f"legacy icon-font class {icon_match.group(0).strip()!r} "
                "(use an inline Heroicon SVG instead)",
            ))

        hex_match = HEX_RE.search(value)
        if hex_match:
            findings.append((
                line_no,
                f"raw hex color {hex_match.group(0)!r} in a class/style attribute "
                "(use a cp-* design token / CSS variable instead)",
            ))

    findings.sort()
    return findings


def iter_html_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.html")))
    return sorted(set(files))


def main(argv: list[str]) -> int:
    roots = [Path(p) for p in argv] if argv else DEFAULT_ROOTS
    html_files = iter_html_files(roots)

    total_findings = 0
    for path in html_files:
        for line_no, message in check_file(path):
            print(f"{path}:{line_no}: {message}")
            total_findings += 1

    if total_findings:
        print(
            f"\nconformance check FAILED: {total_findings} finding(s) "
            f"across {len(html_files)} template(s) scanned",
            file=sys.stderr,
        )
        return 1

    print(f"conformance check passed ({len(html_files)} template(s) scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
