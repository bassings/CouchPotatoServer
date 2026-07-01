"""Tests for scripts/check_conformance.py (UI-CONFORM-02).

The conformance checker is the CI guardrail that stops design-system drift
(off-spec toggle sizing, legacy icon-font classes, raw hex colors) from
creeping back into the modern UI templates — see UI-CONFORM-01, which fixed
exactly this drift once already. These tests exercise the checker itself:
that it is currently clean on the real template tree, that it actually
catches each drift pattern the spec calls out, and that it does not flag the
canonical equivalents (including the legitimate token *definitions* in
base.html, which must stay exempt without any template changes).
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER = REPO_ROOT / "scripts" / "check_conformance.py"
TEMPLATES_ROOT = REPO_ROOT / "couchpotato" / "ui" / "templates"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_conformance  # noqa: E402


def run_checker(*args):
    """Run the checker as a subprocess, the way CI invokes it."""
    result = subprocess.run(
        [sys.executable, str(CHECKER), *[str(a) for a in args]],
        capture_output=True,
        text=True,
    )
    return result


def write_html(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestRealRepoTree:
    def test_passes_on_the_real_template_tree(self):
        """The checker must be clean on the current (post-cleanup) tree."""
        result = run_checker(TEMPLATES_ROOT)
        assert result.returncode == 0, (
            f"conformance check found drift in the real template tree:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "passed" in result.stdout

    def test_passes_with_no_arguments_using_the_default_root(self):
        """With no args the script defaults to couchpotato/ui/templates."""
        result = subprocess.run(
            [sys.executable, str(CHECKER)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_base_html_token_definitions_are_not_flagged(self):
        """base.html's tailwind.config script + :root style block + the
        theme-color meta tag are legitimate token *definitions*, not drift,
        and must stay exempt without editing the template."""
        result = run_checker(TEMPLATES_ROOT / "base.html")
        assert result.returncode == 0, result.stdout + result.stderr


class TestDriftIsDetected:
    def test_off_spec_toggle_track_size_fails(self, tmp_path):
        path = write_html(
            tmp_path,
            "toggle.html",
            '<button class="relative w-10 h-5 rounded-full transition-colors shrink-0"></button>\n',
        )
        result = run_checker(path)
        assert result.returncode != 0
        assert "w-10 h-5" in result.stdout
        assert f"{path}:1" in result.stdout

    def test_off_spec_toggle_knob_offset_fails(self, tmp_path):
        path = write_html(
            tmp_path,
            "toggle.html",
            "<span :class=\"on ? 'translate-x-5' : 'translate-x-0.5'\" "
            'class="block w-4 h-4 bg-white rounded-full"></span>\n',
        )
        result = run_checker(path)
        assert result.returncode != 0
        assert "translate-x-5" in result.stdout

    def test_legacy_icon_font_class_fails(self, tmp_path):
        path = write_html(
            tmp_path, "icon.html", '<i class="icon-emo-coffee text-lg"></i>\n'
        )
        result = run_checker(path)
        assert result.returncode != 0
        assert "icon-emo-coffee" in result.stdout

    def test_raw_hex_in_tailwind_arbitrary_value_fails(self, tmp_path):
        path = write_html(
            tmp_path, "hex.html", '<div class="bg-[#abcdef] p-2"></div>\n'
        )
        result = run_checker(path)
        assert result.returncode != 0
        assert "#abcdef" in result.stdout

    def test_single_quoted_attributes_are_also_checked(self, tmp_path):
        """Drift in single-quoted class=/style= attributes must not bypass the
        icon-font / hex-color rules (regression for the review nit that ATTR_RE
        was double-quote-only)."""
        path = write_html(
            tmp_path,
            "single_quote.html",
            "<i class='icon-download'></i>\n<div style='color: #ff0000'></div>\n",
        )
        result = run_checker(path)
        assert result.returncode != 0
        assert "icon-download" in result.stdout
        assert "#ff0000" in result.stdout

    def test_raw_hex_in_inline_style_fails(self, tmp_path):
        path = write_html(
            tmp_path, "hex_style.html", '<div style="color: #ff0000;"></div>\n'
        )
        result = run_checker(path)
        assert result.returncode != 0
        assert "#ff0000" in result.stdout


class TestCanonicalEquivalentsPass:
    def test_canonical_toggle_size_passes(self, tmp_path):
        path = write_html(
            tmp_path,
            "toggle.html",
            '<button class="relative w-8 h-4 rounded-full transition-colors shrink-0">'
            "<span :class=\"on ? 'translate-x-4' : 'translate-x-0.5'\" "
            'class="block w-3 h-3 bg-white rounded-full"></span></button>\n',
        )
        result = run_checker(path)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_inline_svg_icon_passes(self, tmp_path):
        path = write_html(
            tmp_path,
            "icon.html",
            '<svg aria-hidden="true" class="w-4 h-4" fill="none" viewBox="0 0 24 24">'
            '<path stroke-linecap="round" d="M12 4.5v15"></path></svg>\n',
        )
        result = run_checker(path)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_design_token_class_passes(self, tmp_path):
        path = write_html(
            tmp_path, "token.html", '<div class="bg-cp-accent text-cp-text p-2"></div>\n'
        )
        result = run_checker(path)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_theme_color_meta_and_svg_stroke_hex_are_not_flagged(self, tmp_path):
        """hex in a `content=` meta attribute or an SVG `stroke=`/`fill=`
        attribute is not a class/style arbitrary value and must pass."""
        path = write_html(
            tmp_path,
            "meta_and_svg.html",
            '<meta name="theme-color" content="#35c5f4">\n'
            '<svg fill="#35c5f4" stroke="#35c5f4"><path d="M1 1"/></svg>\n',
        )
        result = run_checker(path)
        assert result.returncode == 0, result.stdout + result.stderr


class TestCheckFileUnit:
    """Directly exercise check_file()/main() for finer-grained assertions."""

    def test_check_file_returns_line_numbers_for_multiple_findings(self, tmp_path):
        path = write_html(
            tmp_path,
            "multi.html",
            "<div>\n"
            '  <button class="w-10 h-5"></button>\n'
            '  <i class="icon-download"></i>\n'
            '  <div class="bg-[#123456]"></div>\n'
            "</div>\n",
        )
        findings = check_conformance.check_file(path)
        line_numbers = sorted(line for line, _ in findings)
        assert line_numbers == [2, 3, 4]

    def test_main_returns_zero_exit_code_on_clean_dir(self, tmp_path):
        write_html(tmp_path, "clean.html", '<div class="bg-cp-accent"></div>\n')
        assert check_conformance.main([str(tmp_path)]) == 0

    def test_main_returns_nonzero_exit_code_on_dirty_dir(self, tmp_path):
        write_html(tmp_path, "dirty.html", '<i class="icon-x"></i>\n')
        assert check_conformance.main([str(tmp_path)]) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
