from couchpotato.core.helpers.variable import md5, cleanHost, natsortKey, dictIsSubset


def test_md5_basic():
    assert md5('abc') == '900150983cd24fb0d6963f7d28e17f72'


def test_clean_host_protocol_and_auth():
    assert cleanHost('localhost:80', ssl=True) == 'https://localhost:80/'
    assert cleanHost('localhost:80', ssl=False) == 'http://localhost:80/'
    out = cleanHost('localhost:80', username='u', password='p')
    assert out.startswith('http://u:p@localhost:80')
    assert out.endswith('/')


def test_natsort_key_orders_numbers():
    keys = ['item2', 'item10', 'item1']
    keys_sorted = sorted(keys, key=natsortKey)
    assert keys_sorted == ['item1', 'item2', 'item10']


def test_dict_is_subset():
    a = {'x': 1}
    b = {'x': 1, 'y': 2}
    assert dictIsSubset(a, b) is True
    assert dictIsSubset({'x': 2}, b) is False

