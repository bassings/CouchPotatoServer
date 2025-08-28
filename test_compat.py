from couchpotato.compat import to_bytes, to_text, url_quote, iteritems


def test_to_bytes_and_to_text_roundtrip():
    assert to_bytes('abc') == b'abc'
    assert to_text(b'abc') == 'abc'
    assert to_text(to_bytes('✓')) == '✓'


def test_url_quote_basic():
    assert url_quote('a b/c') in ('a%20b/c', 'a%20b/c')


def test_iteritems_dict():
    d = {'x': 1, 'y': 2}
    items = dict(iteritems(d))
    assert items == d

