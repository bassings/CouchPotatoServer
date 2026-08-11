"""T17 fix 3 (python:S5247): `Plugin.renderTemplate` builds its Jinja
`Environment` with no `autoescape` argument, which Jinja defaults to False --
so any caller-supplied value lands in the rendered output unescaped.

`renderTemplate` has no in-repo callers (verified across .py/.html/.js), but
it is a public method on `Plugin`, inherited by every in-tree plugin class
and by any installed third-party plugin. An out-of-tree caller is invisible
to every check available from inside this repository, so the fix is to make
the method safe rather than to delete it.
"""
from couchpotato.core.plugins.base import Plugin


def test_render_template_escapes_html_in_params(tmp_path):
    """A `<script>` value passed as a template param must come out escaped,
    not verbatim -- the whole point of S5247. This is the guard: it must be
    provably breakable by reverting `autoescape=True` to no autoescape arg."""
    template_path = tmp_path / 'greeting.html'
    template_path.write_text('Hello {{ payload }}')

    plugin = Plugin()
    # renderTemplate only ever uses Path(parent_file).parent as the template
    # search directory -- the file itself need not exist.
    fake_parent_file = str(tmp_path / 'plugin.py')

    rendered = plugin.renderTemplate(
        fake_parent_file, 'greeting.html', payload = '<script>alert(1)</script>'
    )

    assert '<script>alert(1)</script>' not in rendered
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in rendered
