"""Tests for classic UI Jinja2 autoescape behavior."""

from couchpotato import _jinja_env


def test_classic_jinja_env_autoescape_enabled_for_html_and_xml():
    """Classic UI templates should autoescape HTML/XML by extension."""
    assert callable(_jinja_env.autoescape)
    assert _jinja_env.autoescape("index.html") is True
    assert _jinja_env.autoescape("feed.xml") is True
    assert _jinja_env.autoescape("data.txt") is False


def test_classic_jinja_env_escapes_variables_in_rendered_templates():
    """Raw HTML from variables should be escaped by default."""
    template = _jinja_env.from_string("{{ value }}")
    rendered = template.render(value="<script>alert('xss')</script>")
    assert rendered == "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;"
