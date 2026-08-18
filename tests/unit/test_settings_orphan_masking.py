"""T31: `Settings.getValues()` must mask a section/option nobody registered.

`getType()` falls back to `'unicode'` for any section/option that is not in
`self.types`, and `getValues()` masks a value ONLY when that type is exactly
`'password'`. So any option present in `config.ini` but not registered by a
live plugin -- typically because the plugin that used to own it was removed,
like Hadouken on this branch -- comes back through the `settings` API
VERBATIM.

Measured before this fix, with a config holding an orphaned `[hadouken]`
section and a registered `core.api_key` of type `password`:

    orphan section -> {'api_key': 'SUPERSECRET_KEY', 'auth_pass': 'hunter2'}
    registered     -> *****************

The obvious shortcut -- "mask anything missing from `self.types`" -- is wrong
and is exercised deliberately below (`test_registered_plain_string_option_is_
not_masked`): `registerDefaults` only calls `setType` `if option.get('type')`,
so a great many legitimately registered options are plain strings with no
declared type. Masking on "absent from `self.types`" would blank those out in
the UI. The fix has to key off whether
`registerDefaults` was ever called for that section/option, not off the type
registry.
"""
import pytest

from couchpotato.core.settings import Settings

pytestmark = pytest.mark.unit


def _settings(path):
    """A Settings bound to `path`, nothing registered yet."""
    s = Settings()
    s.setFile(str(path))
    return s


def _write_config(path, text):
    path.write_text(text, encoding='utf-8')


class TestOrphanSectionIsMasked:
    """Options in config.ini that no live plugin ever registered."""

    def test_orphan_secret_looking_option_is_masked(self, tmp_path):
        cfg = tmp_path / 'config.ini'
        _write_config(cfg, '[hadouken]\napi_key = SUPERSECRET_KEY\n')
        settings = _settings(cfg)
        # Nothing calls registerDefaults('hadouken', ...) -- the plugin that
        # used to own this section is gone, exactly like Hadouken on this
        # branch.

        values = settings.getValues()

        assert values['hadouken']['api_key'] != 'SUPERSECRET_KEY'
        assert 'SUPERSECRET_KEY' not in values['hadouken']['api_key']
        assert set(values['hadouken']['api_key']) == {'*'}

    def test_orphan_innocuous_option_is_also_masked(self, tmp_path):
        """Masking is keyed on REGISTRATION, not on the option looking like a
        secret. An orphaned `host` value is just as unaccounted-for as an
        orphaned `api_key` -- a name denylist would miss it and the next
        secret with a boring name."""
        cfg = tmp_path / 'config.ini'
        _write_config(cfg, '[hadouken]\nhost = http://10.0.0.5:7070\n')
        settings = _settings(cfg)

        values = settings.getValues()

        assert values['hadouken']['host'] != 'http://10.0.0.5:7070'
        assert set(values['hadouken']['host']) == {'*'}


class TestRegisteredOptionsAreUnaffected:

    def test_registered_plain_string_option_is_not_masked(self, tmp_path):
        """The regression guard for the obvious-but-wrong shortcut: mask
        anything absent from `self.types`. `registerDefaults` only calls
        `setType` when the option declares a `type`, so a registered option
        with no declared type (an ordinary string setting) has no entry in
        `self.types` either -- exactly like an orphan does. If masking keyed
        off `self.types` instead of actual registration, this plain string
        would come back starred out in the UI."""
        cfg = tmp_path / 'config.ini'
        _write_config(cfg, '[sabnzbd]\nhost = 192.168.1.10\n')
        settings = _settings(cfg)
        settings.registerDefaults('sabnzbd', {
            'host': {'default': ''},  # no 'type' key -- deliberate
        }, save=False)

        values = settings.getValues()

        assert values['sabnzbd']['host'] == '192.168.1.10'

    def test_registered_password_option_is_still_masked(self, tmp_path):
        cfg = tmp_path / 'config.ini'
        _write_config(cfg, '[core]\napi_key = REGISTERED_SECRET\n')
        settings = _settings(cfg)
        settings.registerDefaults('core', {
            'api_key': {'default': '', 'type': 'password'},
        }, save=False)

        values = settings.getValues()

        assert values['core']['api_key'] != 'REGISTERED_SECRET'
        assert set(values['core']['api_key']) == {'*'}


class TestHadoukenUpgradeScenario:
    """The scenario this fix exists for: an install that once configured
    Hadouken, on a build where the plugin has been deleted. Before this
    branch `hadouken.api_key`/`auth_pass` were registered as type `password`
    and masked; after the plugin removal they become orphans, and without
    this fix the settings API starts returning them in the clear -- turning
    a code deletion into a live credential disclosure."""

    def test_leftover_hadouken_credentials_stay_masked_after_removal(self, tmp_path):
        cfg = tmp_path / 'config.ini'
        _write_config(
            cfg,
            '[hadouken]\n'
            'api_key = SUPERSECRET_KEY\n'
            'auth_pass = hunter2\n'
            '\n'
            '[core]\n'
            'api_key = REGISTERED_SECRET\n',
        )
        settings = _settings(cfg)
        # Only core registers -- hadouken.py no longer exists on this branch,
        # so nothing calls registerDefaults('hadouken', ...).
        settings.registerDefaults('core', {
            'api_key': {'default': '', 'type': 'password'},
        }, save=False)

        values = settings.getValues()

        assert 'SUPERSECRET_KEY' not in values['hadouken']['api_key']
        assert 'hunter2' not in values['hadouken']['auth_pass']
        assert values['core']['api_key'] != 'REGISTERED_SECRET'


class TestRegistrationDoesNotBleedBetweenInstances:
    """`Settings.options` and `Settings.types` are class attributes and
    mutate shared state across every instance in the process. The
    registration record backing this fix must NOT repeat that mistake, or
    one test's registerDefaults call would make an orphan look registered in
    a completely unrelated Settings() / test."""

    def test_a_second_settings_instance_does_not_inherit_registration(self, tmp_path):
        cfg_a = tmp_path / 'a.ini'
        _write_config(cfg_a, '[plugin_x]\ntoken = tok\n')
        settings_a = _settings(cfg_a)
        settings_a.registerDefaults('plugin_x', {'token': {'default': ''}}, save=False)
        assert settings_a.getValues()['plugin_x']['token'] == 'tok'

        cfg_b = tmp_path / 'b.ini'
        _write_config(cfg_b, '[plugin_x]\ntoken = tok\n')
        settings_b = _settings(cfg_b)
        # settings_b never registers plugin_x itself.

        values_b = settings_b.getValues()

        assert values_b['plugin_x']['token'] != 'tok'
        assert set(values_b['plugin_x']['token']) == {'*'}
