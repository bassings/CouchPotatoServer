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


@pytest.fixture(autouse=True)
def _isolate_settings_class_state():
    """`Settings.types` and `Settings.options` are CLASS attributes, so every
    registration in this file mutates state shared with every other test in the
    process. T31's own docstring warns about exactly this, and this file
    registers 23 options.

    Nothing fails today only because the names happen not to collide with
    another suite's. That is luck, not isolation -- so restore the class state
    around each test rather than relying on it."""
    types_before = dict(Settings.types)
    options_before = dict(Settings.options)
    yield
    Settings.types.clear()
    Settings.types.update(types_before)
    Settings.options.clear()
    Settings.options.update(options_before)


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
    # Found by review, NOT by the name-based sweep that produced the list
    # above -- and higher-value than anything it caught. A refresh token mints
    # access tokens indefinitely, so masking the access token six lines above
    # it and not this one bought nothing; the cookie settings are live
    # logged-in sessions, i.e. account takeover on an invite-only tracker.
    ('couchpotato.core.media.movie.providers.automation.trakt',
     'trakt', 'automation_oauth_refresh'),
    ('couchpotato.core.media._base.providers.torrent.torrentday',
     'torrentday', 'cookiesetting'),
    ('couchpotato.core.media._base.providers.torrent.iptorrents',
     'iptorrents', 'cookiesetting'),
    ('couchpotato.core.media._base.providers.torrent.bithdtv',
     'bithdtv', 'cookiesettingsl'),
    ('couchpotato.core.media._base.providers.torrent.bithdtv',
     'bithdtv', 'cookiesettingsp'),
    ('couchpotato.core.media._base.providers.torrent.bithdtv',
     'bithdtv', 'cookiesettingsu'),
    # Capability URLs: issued by a third party, and possession alone grants
    # the ability to act. Distinguished below from an endpoint URL.
    ('couchpotato.core.notifications.discord', 'discord', 'webhook_url'),
    ('couchpotato.core.notifications.homey', 'homey', 'url'),
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
        # `loader.py` registers under the top-level ENTRY name, not the group
        # name, so that is what `section` must match. An earlier version had a
        # dead `if ... pass` here that filtered nothing, which review flagged:
        # it returned the first option with that name in ANY group. Harmless
        # while every lookup happens to be unique, and a trap the moment a
        # module declares the same option name twice -- `_core.py` has two
        # groups and is exactly where a second `api_key` would appear.
        if entry.get('name') != section:
            continue
        for group in entry.get('groups', []):
            for opt in group.get('options', []):
                if opt.get('name') == option:
                    return opt
    raise AssertionError(
        f'no option {section}.{option} in {module_path} -- if the plugin was '
        f'renamed or its section changed, fix the CREDENTIALS list WITH it'
    )


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


class TestSavingTheMaskBackDoesNotDestroyTheCredential:
    """The failure that would make this whole change NEGATIVE value.

    Masking is display-only on the read side, which the tests above pin. But
    the settings form posts field values back, and `saveView` had no idea the
    string it was handed was a mask. Driven end to end before this guard:

        on disk before   'xoxb-REAL-SLACK-TOKEN-8842'
        UI displays      '**************************'
        saveView(mask)   -> {'success': True}
        on disk AFTER    '**************************'

    The credential is destroyed and the save reports success. On this
    project's loss ranking a stored credential is irreplaceable-class: the
    user must go and re-issue it at the provider, and for a tracker passkey
    that can mean contacting staff.

    **It was already reachable before this branch** -- 22 options were
    password-typed -- so this is not a defect introduced here. What the branch
    does is widen the blast radius to 37, while the only thing preventing it
    was that `field_types.html` binds `@change` rather than `@input`, so an
    untouched field posts nothing. That is a client-side accident, not a
    guarantee: a password manager autofilling those inputs dispatches
    `change`, and nothing server-side would object.

    So the guard belongs on the server, where it does not depend on which
    events a browser chooses to fire."""

    def _settings(self, tmp_path, value):
        cfg = tmp_path / 'config.ini'
        cfg.write_text(f'[slack]\ntoken = {value}\n', encoding='utf-8')
        s = Settings()
        s.setFile(str(cfg))
        s.registerDefaults('slack', {'token': {'default': '', 'type': 'password'}},
                           save=False)
        return s

    def test_posting_the_mask_back_is_refused(self, tmp_path):
        settings = self._settings(tmp_path, 'xoxb-REAL-TOKEN-8842')
        masked = settings.getValues()['slack']['token']
        assert set(masked) == {'*'}, 'precondition: the UI is showing a mask'

        settings.saveView(section='slack', name='token', value=masked)

        assert settings.get('token', 'slack') == 'xoxb-REAL-TOKEN-8842', (
            'saving the displayed mask overwrote the real credential'
        )

    def test_a_partially_edited_mask_is_also_refused(self, tmp_path):
        """The operator clicks in and appends rather than clearing first.
        Nothing strips stars anywhere, so `****xyz` would be stored verbatim
        and the credential is still gone."""
        settings = self._settings(tmp_path, 'xoxb-REAL-TOKEN-8842')

        settings.saveView(section='slack', name='token', value='*****xyz')

        assert settings.get('token', 'slack') == 'xoxb-REAL-TOKEN-8842'

    def test_a_genuine_new_credential_still_saves(self, tmp_path):
        """The guard must not become a lockout -- rotating a credential is the
        whole reason the field is writable. Fails in the other direction if the
        refusal is too broad."""
        settings = self._settings(tmp_path, 'xoxb-OLD-TOKEN')

        settings.saveView(section='slack', name='token', value='xoxb-NEW-TOKEN')

        assert settings.get('token', 'slack') == 'xoxb-NEW-TOKEN'

    def test_clearing_a_credential_still_works(self, tmp_path):
        """Emptying the field is how a user removes an integration. An empty
        string is not a mask and must go through."""
        settings = self._settings(tmp_path, 'xoxb-OLD-TOKEN')

        settings.saveView(section='slack', name='token', value='')

        assert settings.get('token', 'slack') == ''

    def test_a_credential_containing_an_asterisk_is_the_accepted_casualty(self, tmp_path):
        """Pinned deliberately rather than left implicit: the guard refuses any
        password value CONTAINING an asterisk, so a credential that genuinely
        has one cannot be saved.

        That is broader than strictly necessary and it is the deliberate trade.
        Matching the mask exactly would need the server to know the current
        length, and would still miss the partial-edit case above; a per-field
        nonce round trip is a far larger change. None of the providers here
        (Slack, Discord, Pushover, Trakt, the trackers) issue values with
        asterisks -- they are alphanumeric with `-_` or URL-safe.

        Recorded so the trade is visible in the suite rather than buried in a
        comment, and so it fails loudly the day someone needs it."""
        settings = self._settings(tmp_path, 'xoxb-OLD-TOKEN')

        settings.saveView(section='slack', name='token', value='****')

        assert settings.get('token', 'slack') == 'xoxb-OLD-TOKEN', (
            'documenting the known limit, not endorsing it'
        )


class TestTwoFieldsAreDeliberatelyNotMasked:
    """Review found ten unmasked fields the name-based sweep missed. Eight are
    now masked. These two are deliberately not, and the reasoning is asserted
    here so a later "you missed some" sweep does not reverse it silently.

    **`webhook.url` is an ENDPOINT, not a capability.** Its description is "URL
    that receives a JSON POST when movies are snatched or downloaded" -- it is
    the address of the user's OWN server. Discord's and Homey's webhook URLs
    are masked because a third party ISSUED them and possession alone grants
    the ability to post; that is a bearer credential wearing a URL's clothes.
    A user's own endpoint is not, and masking it removes their ability to check
    what they typed while protecting nothing. If someone points this at a
    capability URL, that is their choice and it is one they can see.

    **`trakt.automation_client_id` is public by OAuth design.** The client_id
    identifies the application, not the user, and is transmitted in every
    authorisation request; its `client_secret` sibling IS masked. Masking an
    identifier because it sits next to a secret is cargo-cult.

    Both are judgement calls, so they are written down with their reasons
    rather than left as an unexplained gap in the list."""

    def test_the_generic_webhook_url_is_still_readable(self):
        opt = _find_option('couchpotato.core.notifications.webhook',
                           'webhook', 'url')
        assert opt.get('type') != 'password', (
            "webhook.url was masked. It is the user's own endpoint, not an "
            'issued capability -- masking hides their config and protects '
            'nothing. If this changed because the field now carries a token, '
            'update the reasoning here rather than just the declaration.'
        )

    def test_the_trakt_client_id_is_still_readable(self):
        opt = _find_option('couchpotato.core.media.movie.providers.automation.trakt',
                           'trakt', 'automation_client_id')
        assert opt.get('type') != 'password', (
            'trakt.automation_client_id was masked. A client_id is public by '
            'OAuth design and identifies the app, not the user; the '
            'client_secret beside it is the secret.'
        )


class TestTypingDoesNotChangeWhatThePluginReads:
    """The regression this fix could introduce, which matters more than the leak
    it closes: declaring an option `password` changes the READ path.

    `Settings.get()` short-circuits on `password` and returns `raw_value`
    directly, skipping `_coerce_value` -- and `_strip_bytes_literal` lives
    inside `_coerce_value`. That helper exists because an earlier version of
    this fork wrote Python 2 bytes literals into `config.ini`, so a long-lived
    install can hold `token = b'xoxb-...'`.

    Measured before the fix, same config value, type toggled:

        no type    -> 'xoxb-legacy-token'
        password   -> "b'xoxb-legacy-token'"

    So masking a credential would hand the wrapper to the provider and the
    integration would fail silently, with nothing in the UI to explain it. A
    fix that breaks the thing it was protecting is worse than the disclosure.

    Note the fixture is deliberately hostile: the other tests here seed a clean
    `SECRET_VALUE_XYZ`, which cannot provoke this at all. Review flagged that
    those fixtures were gentler than production, and it was right."""

    def test_a_legacy_bytes_literal_still_reaches_the_plugin_unwrapped(self, tmp_path):
        cfg = tmp_path / 'config.ini'
        cfg.write_text("[slack]\ntoken = b'xoxb-legacy-token'\n", encoding='utf-8')
        settings = Settings()
        settings.setFile(str(cfg))
        settings.registerDefaults(
            'slack', {'token': {'default': '', 'type': 'password'}}, save=False,
        )

        assert settings.get('token', 'slack') == 'xoxb-legacy-token', (
            'the password short-circuit skipped _strip_bytes_literal, so the '
            "plugin receives b'...' instead of the token"
        )

    def test_the_same_value_is_still_masked_for_display(self, tmp_path):
        """Both directions: stripping the literal must not un-mask it."""
        cfg = tmp_path / 'config.ini'
        cfg.write_text("[slack]\ntoken = b'xoxb-legacy-token'\n", encoding='utf-8')
        settings = Settings()
        settings.setFile(str(cfg))
        settings.registerDefaults(
            'slack', {'token': {'default': '', 'type': 'password'}}, save=False,
        )

        got = settings.getValues()['slack']['token']
        assert 'xoxb-legacy-token' not in got
        assert set(got) == {'*'}


class TestTorrentpotatoIsTheSecondCombinedLeak:
    """The combined-leak inventory was an UNDERCOUNT, and that mattered.

    An earlier version of this file documented `newznab.api_key` as the sole
    combined exemption, and the commit message said "six indexer API keys still
    render in the clear". Review found `torrentpotato.pass_key` -- a private
    tracker passkey, `'type': 'combined'`, `combine: [use, host, pass_key,
    name, seed_ratio, seed_time, extra_score]`.

    The consequence of the undercount is specific: whoever fixes the combined
    renderer would have deleted the newznab class, seen the suite go green, and
    shipped with tracker passkeys still leaking. An exemption list that is
    wrong is worse than no list, because it reads as an inventory."""

    def test_torrentpotato_pass_key_is_combined_not_password(self):
        opt = _find_option(
            'couchpotato.core.media._base.providers.torrent.torrentpotato',
            'torrentpotato', 'pass_key')
        assert opt.get('type') == 'combined', (
            'torrentpotato.pass_key is no longer combined -- re-decide the '
            'exemption; it may now be maskable by typing'
        )
        assert 'pass_key' in opt.get('combine', [])

    def test_torrentpotato_pass_key_still_leaks_and_that_is_recorded(self, tmp_path):
        cfg = tmp_path / 'config.ini'
        cfg.write_text('[torrentpotato]\npass_key = TP_KEY_A,TP_KEY_B\n',
                       encoding='utf-8')
        settings = Settings()
        settings.setFile(str(cfg))
        settings.registerDefaults(
            'torrentpotato',
            {'pass_key': _find_option(
                'couchpotato.core.media._base.providers.torrent.torrentpotato',
                'torrentpotato', 'pass_key')},
            save=False,
        )

        assert 'TP_KEY_A' in settings.getValues()['torrentpotato']['pass_key'], (
            'torrentpotato.pass_key is now masked -- good. Delete this class '
            'and move it into CREDENTIALS.'
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
