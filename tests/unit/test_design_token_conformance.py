"""M20 (branch review 2026-08-31): a Tailwind colour-utility class naming a
`cp-*` token that `base.html`'s `tailwind.config` does not define generates
NO rule at all, so the control silently loses its colour with nothing in CI
noticing. Measured concretely on `wanted.html`'s bulk Delete button, the
Wanted page's most destructive control: `bg-cp-error/10 text-cp-error
hover:bg-cp-error/20` names a token, `error`, that is not one of the twelve
keys `base.html`'s `cp: { ... }` block actually defines (`bg`, `card`,
`surface`, `border`, `accent`, `accentHover`, `text`, `muted`, `success`,
`warning`, `danger`, `blue`) -- so Tailwind's CDN build generates no CSS rule
for any of the three classes and the button renders as plain unstyled text.

`scripts/check_conformance.py` passed on this exact file: its rules cover
off-spec toggle sizing, legacy icon-font classes and raw hex literals, but
nothing checks a `cp-*` utility against the palette that actually exists.
This test is the general form the review calls for -- "a token allowlist
derived from base.html's cp.* block would make it mechanical" -- rather than
one hardcoded to the single known offender, so a second undefined token
introduced anywhere else in the template tree is caught the same way.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_ROOT = REPO_ROOT / "couchpotato" / "ui" / "templates"
BASE_HTML = TEMPLATES_ROOT / "base.html"

# The same attribute-value scoping check_conformance.py already uses (class=,
# :class=, x-bind:class=, style=, :style=, either quote style, DOTALL so a
# multi-line Alpine :class="{ ... }" object binding is still scanned).
ATTR_RE = re.compile(
    r"""[:\w.-]*\b(?:class|style)\s*=\s*(["'])((?:(?!\1).)*)\1""", re.DOTALL
)

# A Tailwind colour utility naming a cp-* token, with an optional opacity
# suffix (bg-cp-danger/10) and an optional leading variant (hover:, dark:,
# ...), which ATTR_RE's DOTALL value capture already includes verbatim.
CP_COLOR_UTILITY_RE = re.compile(
    r"\b(?:bg|text|border|ring(?:-offset)?|outline|placeholder|from|via|to|"
    r"fill|stroke|decoration|divide|accent|caret|shadow)-cp-([A-Za-z][A-Za-z0-9]*)"
    r"(?:/\d+)?\b"
)


def _defined_cp_tokens() -> set[str]:
    """The keys of `base.html`'s `cp: { ... }` Tailwind palette block --
    the only names for which Tailwind's CDN build generates a `*-cp-<key>`
    rule at all."""
    text = BASE_HTML.read_text(encoding="utf-8")
    block_match = re.search(r"\bcp:\s*\{(.*?)\n\s*\}", text, re.DOTALL)
    assert block_match, (
        "could not find base.html's `cp: { ... }` palette block -- test "
        "setup is broken, not the finding under test"
    )
    return set(re.findall(r"(\w+)\s*:", block_match.group(1)))


def _cp_color_usages(path: Path):
    """Yield (line_number, token) for every `*-cp-<token>` colour utility
    used in a class/style attribute in the given template."""
    text = path.read_text(encoding="utf-8")
    for attr_match in ATTR_RE.finditer(text):
        value = attr_match.group(2)
        line_no = text.count("\n", 0, attr_match.start()) + 1
        for token_match in CP_COLOR_UTILITY_RE.finditer(value):
            yield line_no, token_match.group(1)


class TestEveryCpColorUtilityNamesADefinedToken:
    def test_the_defined_palette_is_the_expected_twelve_keys(self):
        # Sanity check on the parser itself, independent of any template:
        # if base.html's palette shape ever changes, this fails clearly
        # rather than the real assertion silently checking against an
        # empty or partial set.
        assert _defined_cp_tokens() == {
            "bg", "card", "surface", "border", "accent", "accentHover",
            "text", "muted", "success", "warning", "danger", "blue",
        }

    def test_no_template_uses_an_undefined_cp_color_token(self):
        defined = _defined_cp_tokens()
        undefined_usages = []

        for path in sorted(TEMPLATES_ROOT.rglob("*.html")):
            for line_no, token in _cp_color_usages(path):
                if token not in defined:
                    undefined_usages.append(
                        "%s:%d: uses '...-cp-%s', which base.html's cp.* "
                        "palette does not define -- Tailwind generates no "
                        "rule for it, so the element silently loses its "
                        "colour" % (path.relative_to(REPO_ROOT), line_no, token)
                    )

        assert not undefined_usages, (
            "undefined cp-* colour token(s) found (M20, branch review "
            "2026-08-31):\n" + "\n".join(undefined_usages)
        )
