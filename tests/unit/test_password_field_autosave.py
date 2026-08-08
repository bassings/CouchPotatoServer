"""The password field must not autosave a half-typed value.

Every other settings field uses `@input` + a 500ms debounce, and that is fine
for them: an intermediate value is silently rewritten by the next keystroke.

The password field is different, and this PR is what made it dangerous.
`Core.md5Password` now rotates the session signing secret on every save of
`core.password` (D6/AC-SEC-38), so an operator who pauses for more than 500ms
while typing a new password gets:

  1. `hash_password(md5(<partial value>))` stored as their REAL password, and
  2. every session on every device ended -- including the tab they are still
     typing in.

They are then signed out, and the password they thought they were setting does
not work. That is a lockout, produced by the interaction between a pre-existing
autosave and a behaviour this PR added. Before the rotation existed the same
partial save was wasteful but recoverable, because the operator stayed logged
in and could simply finish typing.

`@change` fires on blur/commit rather than per keystroke, so no intermediate
value is ever persisted.

A structural test because the behaviour lives in a Jinja/Alpine template: the
E2E suite cannot reach the settings password field without a password-protected
fixture, and this is the assertion that would have caught the interaction.
"""
import re
from pathlib import Path

FIELD_TYPES = (Path(__file__).resolve().parents[2]
               / 'couchpotato' / 'ui' / 'templates' / 'partials' / 'settings'
               / 'field_types.html')


def _password_block(text):
    start = text.index("opt.type === 'password'")
    return text[start:text.index('</template>', start)]


class TestThePasswordFieldDoesNotAutosaveEveryKeystroke:

    def test_it_does_not_bind_to_input(self):
        block = _password_block(FIELD_TYPES.read_text(encoding='utf-8'))

        assert '@input=' not in block, (
            'the password field autosaves on every keystroke. With the D6 '
            'rotation in place, a pause longer than the 500ms debounce stores '
            'a TRUNCATED password and signs the operator out of every device, '
            'including the tab they are typing in:\n%s' % block)

    def test_it_saves_on_change_instead(self):
        block = _password_block(FIELD_TYPES.read_text(encoding='utf-8'))

        assert '@change=' in block, (
            'the password field no longer saves at all; it must still persist '
            'on blur/commit: %s' % block)

    def test_other_fields_still_autosave(self):
        """The counterweight. Per-keystroke autosave is correct for every
        other field and must not be collaterally removed."""
        text = FIELD_TYPES.read_text(encoding='utf-8')

        assert text.count('@input=') >= 1, (
            'no field autosaves on input any more, so this change was applied '
            'far more broadly than the password field')
