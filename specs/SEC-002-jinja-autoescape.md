# SEC-002: Jinja2 Autoescape for Classic UI

## Problem
CodeQL alert #69 — Reflected XSS in `couchpotato/__init__.py`.

The classic UI Jinja2 environment is created WITHOUT autoescape:
```python
# couchpotato/__init__.py line 42
_jinja_env = JinjaEnv(loader=FileSystemLoader(_template_dir))
```

Compared to the new UI which correctly sets autoescape:
```python
# couchpotato/ui/__init__.py line 17
_jinja = JinjaEnv(loader=FileSystemLoader(_template_dir), autoescape=True)
```

Templates rendered without autoescape could output unescaped user-controlled data as HTML.

## Templates Affected
The classic `_jinja_env` renders:
- `index.html` — old UI root
- `api.html` — API docs
- `database.html` — database browser
- `login.html` — login form

## Fix

1. Add `autoescape=select_autoescape(['html', 'xml'])` to the classic Jinja env:

```python
from jinja2 import Environment as JinjaEnv, FileSystemLoader, select_autoescape

_jinja_env = JinjaEnv(
    loader=FileSystemLoader(_template_dir),
    autoescape=select_autoescape(['html', 'xml'])
)
```

2. Audit the 4 affected templates for any variables rendered as raw HTML that must be
   marked `{{ var | safe }}` to preserve intentional HTML rendering.
   - Variables like `sep`, `routes`, `Env` are unlikely to need `| safe`
   - Any variable intentionally containing HTML markup MUST use `| safe`

3. If existing templates use patterns like `{{ some_html_var }}` expecting raw HTML output,
   add `| safe` filter to those specific variables only. Do NOT use `| safe` on user-supplied data.

## TDD Approach

Write a test FIRST that verifies the Jinja env has autoescape enabled:

```python
# tests/unit/test_jinja_autoescape.py
def test_classic_jinja_env_has_autoescape():
    """Classic UI Jinja2 environment must have autoescape enabled."""
    from couchpotato import _jinja_env
    # Verify autoescape is enabled for HTML files
    from jinja2 import escape
    tmpl = _jinja_env.from_string('{{ value }}')
    rendered = tmpl.render(value='<script>alert(1)</script>')
    assert '<script>' not in rendered
    assert '&lt;script&gt;' in rendered

def test_new_ui_jinja_env_has_autoescape():
    """New UI Jinja2 environment must have autoescape enabled."""
    from couchpotato.ui import _jinja
    tmpl = _jinja.from_string('{{ value }}')
    rendered = tmpl.render(value='<script>alert(1)</script>')
    assert '<script>' not in rendered
```

## Acceptance Criteria
- [ ] `_jinja_env` in `couchpotato/__init__.py` has autoescape enabled for HTML files
- [ ] All 4 classic UI templates render correctly after the change (no broken pages)
- [ ] XSS test passes: `<script>` tags in template variables are escaped
- [ ] `pytest tests/unit/ -q` — ALL tests pass
- [ ] `ruff check .` — clean
- [ ] Commit message: `fix: enable Jinja2 autoescape for classic UI templates (SEC-002)`
