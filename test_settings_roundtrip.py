import os
from couchpotato.core.settings import Settings


def test_settings_roundtrip(tmp_path):
    cfg = tmp_path / 'settings.conf'

    s = Settings()
    s.setFile(str(cfg))
    s.addSection('core')
    s.set('core', 'test_option', 'hello')
    s.save()

    # Reload
    s2 = Settings()
    s2.setFile(str(cfg))
    assert s2.get('test_option', section='core') == 'hello'

