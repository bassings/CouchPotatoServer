from couchpotato.core.helpers.request import getParams, dictToList


def test_getparams_nested_and_boolean():
    raw = {
        'a': '1',
        'b[0]': 'X',
        'b[2]': 'Z',
        'b[1]': 'Y',
        'flag': 'true',
    }
    parsed = getParams(raw)
    assert parsed['a'] == '1'
    assert parsed['flag'] is True
    assert parsed['b'] == ['X', 'Y', 'Z']


def test_dict_to_list_numeric_keys():
    obj = {'arr': {'0': 'A', '2': 'C', '1': 'B'}}
    out = dictToList(obj)
    assert out['arr'] == ['A', 'B', 'C']

