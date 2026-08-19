"""T48: a registered credential with no declared type comes back in the CLEAR.

Sibling of `test_settings_orphan_masking.py`, not an extension of it. That file
guards options nobody registered (T31); this one guards options that ARE
registered but declare no `type`, which is a different hole reached through a
different door.

`getValues()` masks only when `getType(section, option) == 'password'`, and
`getType` falls back to `'unicode'`. Sixteen options literally named `password`
already declare the type, so the convention exists and is honoured -- the
differently-named credentials (`api_key`, `passkey`, `bot_token`, `token`,
`apikey`, `user_key`, `api_token`, `oauth_token`, `auth_token`) were simply
missed. Measured before this fix:

    pushbullet.api_key       -> 'LIVE_TOKEN_123'
    passthepopcorn.passkey   -> 'TRACKER_PASSKEY_9999'
    getType(pushbullet, api_key) -> 'unicode'

The tempting shortcut -- mask anything absent from `self.types` -- is wrong and
`test_settings_orphan_masking.py::test_registered_plain_string_option_is_not_
masked` already forbids it: ordinary untyped strings like `host` would be
starred out in the UI. So the remedy is per-option typing, and these tests read
the REAL plugin declarations rather than synthetic ones, because a test that
registers its own options would keep passing after someone adds a new
credential without a type.

`core.api_key` is deliberately EXEMPT. It is declared `'ui-meta': 'ro'` and
described as "Used by third-party apps to communicate with CouchPotato" -- it
exists to be read and pasted elsewhere, and the password template has no reveal
or copy control, so masking it would turn a disclosure defect into a lockout.
That exemption is asserted below so it cannot be "tidied up" later without the
test saying why.
"""
import importlib
import pytest

from couchpotato.core.settings import Settings

pytestmark = pytest.mark.unit


# (module path, section, option) for every credential this task covers.
# Read from the live plugin modules below, never hand-copied values.
CREDENTIALS = [
    ('couchpotato.core.downloaders.sabnzbd', 'sabnzbd', 'api_key'),
    ('couchpotato.core.downloaders.putio', 'putio', 'oauth_token'),
    ('couchpotato.core.notifications.pushover', 'pushover', 'user_key'),
    ('couchpotato.core.notifications.pushover', 'pushover', 'api_token'),
    ('couchpotato.core.notifications.join', 'join', 'apikey'),
    ('couchpotato.core.notifications.emby', 'emby', 'apikey'),
    ('couchpotato.core.notifications.telegrambot', 'telegrambot', 'bot_token'),
    ('couchpotato.core.notifications.pushbullet', 'pushbullet', 'api_key'),
    ('couchpotato.core.notifications.slack', 'slack', 'token'),
    ('couchpotato.core.notifications.plex', 'plex', 'auth_token'),
    ('couchpotato.core.media._base.providers.torrent.awesomehd',
     'awesomehd', 'passkey'),
    ('couchpotato.core.media._base.providers.torrent.passthepopcorn',
     'passthepopcorn', 'passkey'),
    ('couchpotato.core.media._base.providers.torrent.hdbits',
     'hdbits', 'passkey'),
    ('couchpotato.core.media.movie.providers.info.themoviedb',
     'themoviedb', 'api_key'),
    ('couchpotato.core.media.movie.providers.automation.trakt',
     'trakt', 'automation_oauth_token'),
]

IDS = [f'{s}.{o}' for _, s, o in CREDENTIALS]


def _find_option(module_path, section, option):
    """Pull the option dict straight out of the plugin's `config` structure.

    Reading the live declaration is the whole point: a test that registered its
    own copy would pass for ever while the real plugin stayed unmasked.
    """
    mod = importlib.import_module(module_path)
    config = getattr(mod, 'config', None)
    assert config, f'{module_path} exposes no `config` to read'
    for entry in config:
        for group in entry.get('groups', []):
            if group.get('name') != section and entry.get('name') != section:
                # `name` lives on the group for most plugins, on the entry for
                # a few; accept either rather than encoding one convention.
                pass
            for opt in group.get('options', []):
                if opt.get('name') == option:
                    return opt
    raise AssertionError(f'no option {option!r} found in {module_path}')


class TestEveryCredentialDeclaresItsType:
    """The declaration is what the fix changes, so assert on the declaration."""

    @pytest.mark.parametrize('module_path,section,option', CREDENTIALS, ids=IDS)
    def test_the_option_declares_type_password(self, module_path, section, option):
        opt = _find_option(module_path, section, option)
        assert opt.get('type') == 'password', (
            f'{section}.{option} declares type={opt.get("type")!r}; without '
            f"'password' getValues() returns it verbatim and the UI renders it "
            f'in an <input type="text">'
        )


class TestMaskingActuallyHappens:
    """A declaration is a claim. This drives `getValues()` for real."""

    @pytest.mark.parametrize('module_path,section,option', CREDENTIALS, ids=IDS)
    def test_the_value_is_masked_in_getvalues(self, tmp_path, module_path,
                                              section, option):
        cfg = tmp_path / 'config.ini'
        cfg.write_text(f'[{section}]\n{option} = SECRET_VALUE_XYZ\n',
                       encoding='utf-8')
        settings = Settings()
        settings.setFile(str(cfg))
        settings.registerDefaults(
            section, {option: _find_option(module_path, section, option)},
            save=False,
        )

        got = settings.getValues()[section][option]

        assert 'SECRET_VALUE_XYZ' not in got, f'{section}.{option} leaked'
        assert set(got) == {'*'}, f'{section}.{option} -> {got!r}'


class TestMaskingIsDisplayOnly:
    """The failure that would matter more than the leak: masking the value the
    PLUGIN reads would break every one of these integrations silently."""

    @pytest.mark.parametrize('module_path,section,option', CREDENTIALS, ids=IDS)
    def test_the_plugin_still_reads_the_real_value(self, tmp_path, module_path,
                                                   section, option):
        cfg = tmp_path / 'config.ini'
        cfg.write_text(f'[{section}]\n{option} = SECRET_VALUE_XYZ\n',
                       encoding='utf-8')
        settings = Settings()
        settings.setFile(str(cfg))
        settings.registerDefaults(
            section, {option: _find_option(module_path, section, option)},
            save=False,
        )

        assert settings.get(option, section) == 'SECRET_VALUE_XYZ', (
            f'{section}.{option} is masked for the plugin too -- the '
            f'integration would break, which is worse than the disclosure'
        )


class TestNewznabIsExemptAndStillLeaks:
    """`newznab.api_key` is the second exemption, for a completely different
    reason from `core.api_key` -- and unlike that one it is NOT safe, it is
    merely not fixable by typing.

    It already declares `'type': 'combined'` and carries
    `'combine': ['use', 'host', 'api_key', 'extra_score', 'custom_tag']`: it is
    one control rendering six configured servers together, and its default is
    `',,,,,'` -- six empty comma-separated slots. Re-typing it `password` would
    not mask it (a dict literal keeps the LAST key, which is how the first
    attempt at this fix silently did nothing) and would break the multi-server
    UI if it did take effect.

    So six indexer API keys still render in the clear. This test exists to keep
    that visible rather than let the exemption read as "handled": it asserts the
    field is still combined AND still unmasked, so whoever fixes the combined
    renderer will see this fail and know to delete it.

    This is exactly why the suite reads the LIVE declaration instead of a
    synthetic copy -- a test that registered its own `api_key` would have gone
    green here and reported a leak as fixed."""

    def test_newznab_api_key_is_combined_not_password(self):
        opt = _find_option('couchpotato.core.media._base.providers.nzb.newznab',
                           'newznab', 'api_key')
        assert opt.get('type') == 'combined', (
            'newznab.api_key is no longer a combined control -- re-decide the '
            'exemption; it may now be maskable by typing like the others'
        )
        assert 'api_key' in opt.get('combine', []), (
            'the combine list no longer includes api_key; the reason for the '
            'exemption has changed'
        )

    def test_newznab_api_key_still_leaks_and_that_is_recorded(self, tmp_path):
        """Not an endorsement. A failing assertion here would mean someone
        fixed it, at which point delete this class and put newznab back in
        CREDENTIALS above."""
        cfg = tmp_path / 'config.ini'
        cfg.write_text('[newznab]\napi_key = KEY1,KEY2,KEY3,,,\n', encoding='utf-8')
        settings = Settings()
        settings.setFile(str(cfg))
        settings.registerDefaults(
            'newznab',
            {'api_key': _find_option(
                'couchpotato.core.media._base.providers.nzb.newznab',
                'newznab', 'api_key')},
            save=False,
        )

        got = settings.getValues()['newznab']['api_key']

        assert 'KEY1' in got, (
            'newznab.api_key is now masked -- good. Delete this class and move '
            'newznab back into CREDENTIALS.'
        )


class TestTheCoreApiKeyExemptionIsDeliberate:
    """`core.api_key` must NOT be password-typed, and the reason is recorded
    here so a future tidy-up cannot quietly reverse it.

    It is `'ui-meta': 'ro'` and exists to be READ and pasted into third-party
    apps. The password template has no reveal or copy control, so masking it
    leaves the operator unable to retrieve or replace their key -- a lockout,
    which is a straight downgrade from a disclosure. It needs a
    reveal-or-regenerate path instead, tracked separately."""

    def test_core_api_key_is_still_readable(self):
        from couchpotato.core._base import _core
        opt = _find_option('couchpotato.core._base._core', 'core', 'api_key')
        assert opt.get('type') != 'password', (
            'core.api_key was password-typed. It is read-only and exists to be '
            'copied into third-party apps; with no reveal control that locks '
            'the operator out of their own key. Give it a reveal/regenerate '
            'path before masking it.'
        )
        assert opt.get('ui-meta') == 'ro', (
            'the exemption above rests on this being read-only; if that '
            'changed, re-decide the exemption rather than assuming it holds'
        )
        assert _core  # module import is part of the assertion
