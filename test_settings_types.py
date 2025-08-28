from couchpotato.core.settings import Settings


def test_types_bool_int_float_and_directories(tmp_path):
    cfg = tmp_path / 'settings.conf'
    s = Settings()
    s.setFile(str(cfg))
    sec = 'core'
    s.addSection(sec)

    # Set specific types
    s.setType(sec, 'flag', 'bool')
    s.setType(sec, 'count', 'int')
    s.setType(sec, 'ratio', 'float')
    s.setType(sec, 'dirs', 'directories')

    # Store raw values in parser
    s.p.set(sec, 'flag', 'true')
    s.p.set(sec, 'count', '42')
    s.p.set(sec, 'ratio', '3.14')
    s.p.set(sec, 'dirs', '/a::/b::/c')
    s.save()

    # Reload and read typed values
    s2 = Settings()
    s2.setFile(str(cfg))
    s2.setType(sec, 'flag', 'bool')
    s2.setType(sec, 'count', 'int')
    s2.setType(sec, 'ratio', 'float')
    s2.setType(sec, 'dirs', 'directories')

    assert s2.get('flag', section=sec) is True
    assert s2.get('count', section=sec) == 42
    assert abs(s2.get('ratio', section=sec) - 3.14) < 1e-6
    assert s2.get('dirs', section=sec) == ['/a', '/b', '/c']

