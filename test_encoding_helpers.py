from couchpotato.core.helpers.encoding import toUnicode, ss, sp, tryUrlencode, toSafeString, simplifyString


def test_to_unicode_and_ss_roundtrip():
    b = b"hello\xe2\x9c\x93"  # hello✓
    s = toUnicode(b)
    assert isinstance(s, str)
    assert 'hello' in s
    # ss returns bytes
    back = ss(s)
    assert isinstance(back, (bytes, bytearray))


def test_sp_normalizes_paths():
    assert sp('/tmp//folder/') == '/tmp/folder'


def test_try_urlencode_handles_unicode():
    out = tryUrlencode({'q': '✓ ok'})
    assert 'q=' in out and '%E2%9C%93' in out


def test_safe_and_simplify_string():
    safe = toSafeString('Fïlê Näme (2025).mp4')
    assert ' ' in safe and '(' in safe
    simple = simplifyString('The.Matrix (1999)!')
    assert simple == 'the matrix 1999'

