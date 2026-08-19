"""T48: the settings template must never render a credential's mask into a field.

These were E2E tests first, and that was the wrong level. Asserting "the field
is empty" in a browser only means something when a credential is STORED --
otherwise `getVal` returns `''` and the field is empty whether or not the
template binds the mask. All three passed against a template mutated back to
the old design, which is a guard that cannot fail.

Storing one to fix that is not available either: writing `core.password` fires
`Core.md5Password`, which turns `auth_required` on, so the next page load is a
sign-in screen. The feature working correctly made the test unrunnable.

These are properties of the template text, so they are asserted against the
template text -- deterministic, no browser, no app state, and they fail the
moment someone reintroduces the binding.

What the value binding cost, and why this is worth pinning:

  - PARTIAL EDIT. With the mask as the value, clicking in puts the cursor
    after it, so pasting stores `********xoxb-NEW`: the old credential is
    destroyed and the new one is corrupt, while the UI reports success.
  - LENGTH DISCLOSURE. `getValues()` masks as `len(value) * '*'`, so the
    rendered field told anyone looking at the screen exactly how long the
    stored credential is.
  - The earlier mitigation (`@focus` clearing the field) worked but wiped it
    the instant focus landed, including via Tab -- a screen reader announced
    "twenty asterisks" and was then on an empty field with no announcement.
    Review raised that as an accessibility nit; it is better read as evidence
    the mask should never have been in the DOM.
"""
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TEMPLATE = (Path(__file__).resolve().parents[2]
            / 'couchpotato/ui/templates/partials/settings/field_types.html')


def _password_input():
    """The `<input type="password">` tag, as shipped."""
    text = TEMPLATE.read_text(encoding='utf-8')
    m = re.search(r'<input type="password"(.*?)>', text, re.S)
    assert m, 'no password input found in field_types.html -- if the field '\
              'moved, move this test with it rather than deleting it'
    return m.group(1)


class TestThePasswordFieldNeverRendersTheMask:

    def test_the_value_is_not_bound_to_the_stored_setting(self):
        attrs = _password_input()
        assert ':value=' not in attrs, (
            'the password field binds :value, so the mask is rendered into the '
            'DOM again. That restores partial-edit corruption (paste after the '
            'mask stores ****NEW) and discloses the credential length.'
        )

    def test_the_value_is_pinned_empty(self):
        attrs = _password_input()
        assert re.search(r'\bvalue=""', attrs), (
            'the password field no longer pins value="" -- without it a '
            'browser may repopulate the field from autofill or a bfcache '
            'restore, which is the state this design exists to avoid'
        )

    def test_the_stored_state_is_still_communicated(self):
        """Removing the mask must not remove the INFORMATION it carried. A
        sighted user could see that something was set; that has to survive, and
        reach assistive tech too, which the asterisks never did."""
        attrs = _password_input()
        assert ':placeholder=' in attrs, (
            'the field renders empty with no placeholder, so the operator '
            'cannot tell a configured credential from an unset one'
        )
        assert 'getVal(' in attrs, (
            'the placeholder does not consult the stored value, so it cannot '
            'distinguish "saved" from "not set"'
        )

    def test_the_extraction_is_not_vacuous(self):
        """Guards the guard: every assertion above passes trivially if the
        regex stops matching. This suite has already shipped three guards that
        could not fail, so pin the extraction itself."""
        attrs = _password_input()
        assert 'type="password"' in TEMPLATE.read_text(encoding='utf-8')
        assert '@change=' in attrs, (
            'the password input has no @change handler; either the field '
            'changed shape or the regex is matching the wrong tag'
        )
