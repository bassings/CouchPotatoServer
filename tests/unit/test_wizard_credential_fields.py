"""T52: the first-run wizard must not render credentials as `type="text"`.

T48 fixed the settings page by declaring `'type': 'password'` on the plugin
options. The wizard does NOT read plugin `config` -- it carries its own
hard-coded field list -- so it was unaffected and kept rendering credentials in
the clear on the one page every new install walks through.

Lower severity than T48 because the wizard only ever shows what the user is
currently typing, never a stored secret. Same shoulder-surf and screenshot
class though, and inconsistent *within a single template*: 16 of its 21
credential inputs already declare `type="password"`, and every tracker
`password` field does. The convention exists; a handful were missed.

TWO SHAPES, and the second is why this is a test rather than a one-off fix:

1. **Direct inputs** -- `<input type="text" x-model="...api_key">`. A regex over
   the input tags finds these.
2. **Data-driven fields** -- the private-tracker list renders through one
   generic input (`:type="field.type || 'text'"`) fed by a `privateTrackers`
   array, so the credential's NAME never appears in the tag at all.

A sweep written for shape 1 alone reports the file clean while
`passthepopcorn.passkey` and `hdbits.passkey` render as plain text. That is
exactly what happened when this task was first scoped: the direct-input sweep
missed both, and they were only found by reading how the tracker loop works.

So this checks both, and a new credential added in either shape fails it.
"""
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

WIZARD = (Path(__file__).resolve().parents[2]
          / 'couchpotato/ui/templates/wizard.html')

# `user_?key` and `auth` are here because review got an untyped
# `entry.user_key` past the first version of this pattern. T48's own docstring
# already listed `user_key` among the differently-named credentials it had to
# fix, so this was a known name the pattern did not know.
CREDENTIAL = re.compile(
    r'(api_?key|user_?key|passkey|pass_key|secret|token|password|cookie|auth)',
    re.I)


def _text() -> str:
    return WIZARD.read_text(encoding='utf-8')


def _direct_inputs():
    """(line, type, identifier) for every credential-ish `<input>` tag."""
    s = _text()
    for m in re.finditer(r'<input\b[^>]*>', s, re.S):
        tag = m.group(0)
        model = re.search(r'x-model="([^"]+)"', tag)
        ph = re.search(r'placeholder="([^"]+)"', tag)
        ident = f'{model.group(1) if model else ""} {ph.group(1) if ph else ""}'
        if not CREDENTIAL.search(ident):
            continue
        t = re.search(r':type="([^"]+)"|type="([^"]+)"', tag)
        typ = (t.group(1) or t.group(2)) if t else None
        yield s[:m.start()].count('\n') + 1, typ, ident.strip()


def _tracker_fields():
    """(tracker, field, declares_password) from the `privateTrackers` array.

    Extracts OBJECTS, not lines. The first version matched the literal
    `"{ name: '"` on a single line, so review got two mutations past it: one
    that removed the space (`{name:`), and one that split the object across
    three lines. Both rendered `hdbits.passkey` as plain text with the suite
    green -- the incidentally-passing shape, inside the class written to
    prevent it. Someone adding a seventh tracker next quarter would format the
    object across lines because it has four properties, and that is all it
    would take.
    """
    s = _text()
    start = s.index('    privateTrackers: [')
    block = s[start:s.index('\n    ],', start)]

    # Split into per-tracker chunks first so a field is attributed correctly
    # however its own object is wrapped.
    chunks = re.split(r"(?=\bid:\s*')", block)
    for chunk in chunks:
        m = re.search(r"id:\s*'([^']+)'", chunk)
        if not m:
            continue
        tracker = m.group(1)
        for obj in re.findall(r'\{[^{}]*\}', chunk, re.S):
            f = re.search(r"name:\s*'([^']+)'", obj)
            if f:
                yield tracker, f.group(1), re.search(
                    r"type:\s*'password'", obj) is not None


class TestNoCredentialRendersAsPlainText:

    def test_direct_inputs_are_password_typed(self):
        leaking = [
            f'{WIZARD.name}:{line} {ident} (type={typ!r})'
            for line, typ, ident in _direct_inputs()
            if typ != 'password'
        ]
        assert not leaking, (
            'credential inputs rendered in the clear:\n  '
            + '\n  '.join(leaking)
            + '\n\nDeclare type="password". Do NOT loosen the pattern.'
        )

    def test_tracker_fields_are_password_typed(self):
        """The shape a tag-level sweep cannot see: these render through one
        generic `:type="field.type || 'text'"` input, so the credential name is
        in the data, not the markup."""
        leaking = [
            f'{tracker}.{field}'
            for tracker, field, typed in _tracker_fields()
            if CREDENTIAL.search(field) and not typed
        ]
        assert not leaking, (
            f'tracker credential fields with no declared type: {leaking}. '
            f"They render as text via `field.type || 'text'`."
        )


class TestTheSweepsCannotPassVacuously:
    """Both assertions above pass trivially if their extraction finds nothing.
    This file exists because the FIRST version of this sweep did exactly that
    for the tracker fields."""

    def test_the_input_sweep_finds_the_known_inputs(self):
        found = list(_direct_inputs())
        assert len(found) > 15, f'only {len(found)} credential inputs found'
        assert any('formData.password' in i for _, _, i in found)

    def test_the_tracker_sweep_sees_every_declared_tracker(self):
        """Counts per tracker rather than asserting membership.

        The first version asked `any(f == 'passkey')`, which passthepopcorn
        alone satisfied -- so an extraction that silently stopped seeing
        hdbits' fields still passed. Review demonstrated exactly that."""
        found = list(_tracker_fields())
        per_tracker = {}
        for tracker, field, _ in found:
            per_tracker.setdefault(tracker, set()).add(field)

        declared = set(re.findall(r"id:\s*'([^']+)'", _text()[
            _text().index('    privateTrackers: ['):]))
        seen = set(per_tracker)
        assert declared <= seen or not declared - seen, (
            f'trackers declared but not extracted: {sorted(declared - seen)}'
        )
        for tracker, fields in per_tracker.items():
            assert fields, f'{tracker} yielded no fields'
        assert len(per_tracker) >= 6, (
            f'only {len(per_tracker)} trackers extracted: {sorted(per_tracker)}'
        )
