"""SEC-003 password hashing tests."""

from couchpotato.core.helpers.variable import md5, check_password, hash_password


def test_hash_password_returns_bcrypt_hash():
    hashed = hash_password('secret-md5-value')

    assert isinstance(hashed, str)
    assert hashed.startswith('$2')
    assert hashed != 'secret-md5-value'


def test_hash_password_uses_salt_per_call():
    first = hash_password('same-value')
    second = hash_password('same-value')

    assert first != second


def test_check_password_validates_bcrypt_hash_success():
    hashed = hash_password('md5-value')

    assert check_password('md5-value', hashed) is True


def test_check_password_validates_bcrypt_hash_failure():
    hashed = hash_password('md5-value')

    assert check_password('different-value', hashed) is False


def test_check_password_supports_legacy_md5_cleartext_input():
    legacy_hash = md5('plain-secret')

    assert check_password('plain-secret', legacy_hash) is True


def test_check_password_supports_prehashed_legacy_md5_input():
    legacy_hash = md5('plain-secret')

    assert check_password(legacy_hash, legacy_hash) is True


def test_check_password_rejects_invalid_hash_format():
    assert check_password('secret', 'not-a-valid-hash') is False


def test_check_password_rejects_missing_values():
    assert check_password('', '') is False
    assert check_password('secret', '') is False
    assert check_password('', 'abc') is False
