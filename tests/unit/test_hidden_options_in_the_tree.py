"""SEC-005, AC-SEC-16's second known limit: no option is `hidden` but the Jackett key binding.

At start-up `registerDefaults` empties the stored value of a `hidden` option
whose flag config.ini does not yet hold (it assumes a planted value). That is
wrong for an option that was declared with no `ui-meta` in an earlier release
and is now marked `hidden`: a value a user entered would be emptied on every
upgraded install. This test reads the real declarations, the ones the loader
registers, so that marking another option `hidden` cannot go unnoticed.
"""
import os

import pytest

from couchpotato.core.loader import Loader

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALLOWED = {('torrentpotato', 'jackett_key_binding')}

MESSAGE = (
    'An option is now declared with "ui-meta": "hidden": %s. At start-up Settings.registerDefaults '
    'EMPTIES the stored value of a hidden option whose flag config.ini does not yet hold, because it '
    'assumes such a value was planted. If this option existed in an earlier release without a ui-meta, '
    'every upgraded install would silently lose the value a user entered. Do not just add it to ALLOWED: '
    'migrate the value. Declaring the option "rw" or "ro" for one release first protects only installs that '
    'ran that release; an install that skips it still loses the value. Then update this test and AC-SEC-16.')


def declared_hidden_options():
    """Every (section, option) the loader would register with a `hidden` flag, read from the modules."""
    loader = Loader()
    loader.preload(root=ROOT)
    found, seen_config, metas = set(), 0, set()
    for priority in sorted(loader.modules):
        for module_name, plugin in sorted(loader.modules[priority].items()):
            if plugin.get('name', '')[:2] == '__':
                continue
            module = loader.loadModule(module_name)
            for section in getattr(module, 'config', None) or []:
                seen_config += 1
                for group in section['groups']:
                    for option in group['options']:
                        metas.add(str(option.get('ui-meta', '')).lower())
                        if str(option.get('ui-meta', '')).lower() == 'hidden':
                            found.add((section['name'], option['name']))
    return found, seen_config, metas


def test_the_only_hidden_option_is_the_jackett_key_binding():
    found, _, _ = declared_hidden_options()

    unexpected = sorted(found - ALLOWED)
    assert not unexpected, MESSAGE % unexpected
    assert found == ALLOWED


def test_the_walk_reads_the_real_declarations_not_a_short_list():
    """The walk visits the loader's own modules and sees every `ui-meta` value that exists in the
    tree today (`rw` and `ro` in core, `hidden` on the binding), so an empty walk cannot pass above."""
    found, seen_config, metas = declared_hidden_options()

    assert seen_config > 50
    assert {'rw', 'ro', 'hidden'} <= metas
    assert found == ALLOWED
