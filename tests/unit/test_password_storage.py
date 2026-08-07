"""A password set through the UI or wizard must be stored as bcrypt.

`_core.py:57` wires `setting.save.core.password` to `md5Password`, which was:

    def md5Password(self, value):
        return md5(value) if value else ''

So every password set through the settings UI or the first-run wizard was
written to `config.ini` as an **unsalted MD5** -- instantly reversible for any
password in a rainbow table, which is to say most of them.

bcrypt was reached only by the login-time upgrade at `__init__.py:308`, which
rehashes on a successful login. That path never runs for the cohort that has
never logged in -- and until `auth_required` landed earlier in this PR, the
server never asked anyone to log in. So the users this PR exists to protect are
exactly the ones whose password was still MD5.

`check_password` carries the comment "New passwords are always bcrypt", which
was false at the moment it was written. It is corrected alongside this fix,
because a reassuring sentence the code contradicts is worse than no sentence:
it is the reason nobody looked.

The stored value is bcrypt OVER the MD5 of the plaintext, not over the
plaintext. That is not a design choice made here -- it is what the login path
already computes (`form_password_md5 = md5(form_password)`, then
`check_password(form_password_md5, stored)`), so anything else would silently
lock every user out. Changing that inner encoding is a separate migration with
its own login-time upgrade, not a tidy-up to fold into this fix.
"""
import re

import pytest

from couchpotato.core.helpers.variable import check_password, is_legacy_md5_hash, md5


BCRYPT_PREFIXES = ('$2a$', '$2b$', '$2y$')


@pytest.fixture
def core():
    """A bare Core instance -- md5Password touches no state."""
    from couchpotato.core._base._core import Core
    return Core.__new__(Core)


class TestPasswordsAreStoredAsBcrypt:

    def test_a_saved_password_is_not_a_bare_md5_hash(self, core):
        stored = core.md5Password('hunter2')

        assert not is_legacy_md5_hash(stored), (
            'the password was stored as an unsalted MD5 hash (%r). That is '
            'reversible for any password in a rainbow table, and it sits in '
            'config.ini.' % stored
        )

    def test_a_saved_password_is_a_bcrypt_hash(self, core):
        stored = core.md5Password('hunter2')

        assert stored.startswith(BCRYPT_PREFIXES), (
            'expected a bcrypt hash, got %r' % stored
        )

    def test_the_same_password_hashes_differently_each_time(self, core):
        """Salted. Two identical passwords must not produce identical rows."""
        assert core.md5Password('hunter2') != core.md5Password('hunter2')

    def test_an_empty_password_stays_empty(self, core):
        """Empty means "no password set", and must not become a valid hash."""
        assert core.md5Password('') == ''
        assert core.md5Password(None) == ''


class TestTheStoredHashStillAuthenticates:
    """The fix must not lock anyone out; login is the only consumer."""

    def test_login_accepts_the_password_that_was_saved(self, core):
        stored = core.md5Password('hunter2')

        # Exactly what login_post computes before calling check_password.
        assert check_password(md5('hunter2'), stored) is True

    def test_login_rejects_a_different_password(self, core):
        stored = core.md5Password('hunter2')

        assert check_password(md5('wrong'), stored) is False

    def test_a_legacy_md5_row_still_authenticates(self, core):
        """Existing installs keep working until their next login upgrades them."""
        legacy = md5('hunter2')
        assert is_legacy_md5_hash(legacy)

        assert check_password(md5('hunter2'), legacy) is True


class TestTheCommentMatchesTheCode:

    def test_no_comment_claims_new_passwords_are_always_bcrypt_unless_true(self):
        """Pins the sentence that was false for as long as md5Password existed.

        Not style policing: that comment is precisely why the defect survived.
        It told every reader -- and every reviewer -- that the thing they were
        looking at had already been handled.
        """
        from pathlib import Path

        source = Path(__file__).resolve().parents[2] / 'couchpotato' / 'core' / '_base' / '_core.py'
        text = source.read_text(encoding='utf-8')

        # Slice to the NEXT top-level method, not to the first blank line: the
        # docstring contains blank lines, and an extraction that stops at one
        # reads a fraction of the body and then reports on it confidently.
        start = text.find('    def md5Password(self, value):')
        assert start != -1, 'md5Password not found -- this guard is no longer watching anything'
        rest = text[start + 1:]
        end = rest.find('\n    def ')
        body = rest[:end if end != -1 else len(rest)]

        assert 'hash_password' in body, (
            'md5Password does not call hash_password, so passwords set through '
            'the UI are not bcrypt: %r' % body
        )
