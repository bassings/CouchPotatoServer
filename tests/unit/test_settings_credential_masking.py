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
import ast
import importlib
import re
from pathlib import Path

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
    ('couchpotato.core.notifications.webhook', 'webhook', 'url'),
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

    def test_a_partially_edited_mask_is_NOT_caught_and_that_is_deliberate(self, tmp_path):
        """The limit of a server-side guard, pinned rather than left implicit.

        If the operator clicks into a masked field and appends instead of
        clearing, `*****xyz` is stored verbatim and the credential is gone.
        An earlier version of the guard DID catch this, by refusing any value
        containing an asterisk -- and that was a security regression.

        Review measured why: 19 pre-existing password options hold HUMAN-CHOSEN
        passwords (`core.password`, `proxy_password`, every downloader and
        tracker login, `smtp_pass`), `*` is in the default symbol set of every
        mainstream password generator, and `wizard.html` fires `saveSetting`
        without reading the response. So an operator picking a password with an
        asterisk at first run was told authentication was configured while the
        save was refused and the instance stayed public.

        Any predicate loose enough to catch a partial edit can also reject a
        real password, and that failure mode is far worse than this one: this
        loses one credential the user is actively editing and can see went
        wrong; that one silently leaves the server unauthenticated.

        So the guard matches the mask's EXACT shape and nothing else. The
        partial edit is left to the client, which is the layer that actually
        knows the field was touched."""
        settings = self._settings(tmp_path, 'xoxb-REAL-TOKEN-8842')

        settings.saveView(section='slack', name='token', value='*****xyz')

        assert settings.get('token', 'slack') == '*****xyz', (
            'if this now passes the credential through unchanged, the guard '
            'was broadened -- re-read the reasoning above before keeping it'
        )

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

    def test_core_password_with_an_asterisk_still_saves(self, tmp_path):
        """The regression the first version of this guard caused, pinned so it
        cannot come back.

        `core.password` is the LOGIN password and is password-typed. A guard
        refusing any value containing `*` refused it -- and `wizard.html` calls
        `saveSetting` without reading the response, so a first-run operator
        picking a generated password with an asterisk was told authentication
        was on while `Core.md5Password` never fired, `auth_required` was never
        set, and the instance stayed public.

        This is the highest-severity thing this branch touched, and it was
        introduced BY the fix, not found by it."""
        cfg = tmp_path / 'config.ini'
        cfg.write_text('[core]\npassword = old_hash\n', encoding='utf-8')
        settings = Settings()
        settings.setFile(str(cfg))
        settings.registerDefaults(
            'core', {'password': {'default': '', 'type': 'password'}}, save=False)

        settings.saveView(section='core', name='password', value='Tr0ub4dor&3*x')

        assert settings.get('password', 'core') == 'Tr0ub4dor&3*x', (
            'a routine generated password was refused -- see the wizard path, '
            'this silently leaves the server unauthenticated'
        )

    def test_a_downloader_password_with_an_asterisk_still_saves(self, tmp_path):
        """Same shape, second surface: 19 pre-existing password options hold
        human-chosen passwords, not issued tokens. One example is asserted so
        the reasoning is not carried only by `core.password`."""
        cfg = tmp_path / 'config.ini'
        cfg.write_text('[sabnzbd]\npassword = old\n', encoding='utf-8')
        settings = Settings()
        settings.setFile(str(cfg))
        settings.registerDefaults(
            'sabnzbd', {'password': {'default': '', 'type': 'password'}}, save=False)

        settings.saveView(section='sabnzbd', name='password', value='my*pass')

        assert settings.get('password', 'sabnzbd') == 'my*pass'

    def test_a_fresh_all_asterisk_credential_saves(self, tmp_path):
        """The guard must not RESERVE a valid credential value.

        An earlier version refused anything that was entirely asterisks, which
        reserved `****` as a sentinel. Review ranked that P1 and was right: the
        field it hurts most is `core.password`, and combined with the wizard
        discarding the save response (T51) a user choosing that password would
        be told authentication was on while the server stayed public. A silent
        failure mode is exactly where you must not reserve values.

        The guard now compares against the mask that WOULD be rendered for the
        currently stored value, so this saves."""
        settings = self._settings(tmp_path, 'xoxb-REAL-TOKEN-8842')

        settings.saveView(section='slack', name='token', value='****')

        assert settings.get('token', 'slack') == '****'

    def test_the_only_residue_is_an_exact_length_match(self, tmp_path):
        """What is left, pinned so the trade stays visible: changing an
        N-character credential to exactly N asterisks is indistinguishable from
        echoing the mask, because it IS the mask. Getting below this needs a
        round-trip token per field, which is a much larger change for a case
        that does not occur."""
        settings = self._settings(tmp_path, 'abcd')       # 4 characters

        settings.saveView(section='slack', name='token', value='****')

        assert settings.get('token', 'slack') == 'abcd', (
            'documenting the known limit, not endorsing it'
        )

    def test_the_mask_is_still_refused_at_the_real_length(self, tmp_path):
        """And the guard still does its job: the actual rendered mask for the
        stored value is refused."""
        settings = self._settings(tmp_path, 'xoxb-REAL-TOKEN-8842')
        masked = settings.getValues()['slack']['token']

        settings.saveView(section='slack', name='token', value=masked)

        assert settings.get('token', 'slack') == 'xoxb-REAL-TOKEN-8842'


class TestOneFieldIsDeliberatelyNotMasked:
    """One field is deliberately not masked, and the reasoning is asserted here
    so a later "you missed some" sweep does not reverse it silently.

    **`trakt.automation_client_id` is public by OAuth design.** The client_id
    identifies the application, not the user, and is transmitted in every
    authorisation request; its `client_secret` sibling IS masked. Masking an
    identifier because it sits next to a secret is cargo-cult.

    **`webhook.url` was on this list and has been REMOVED from it.** The
    argument was that it is the address of the user's own server rather than an
    issued capability, unlike Discord's and Homey's. Review pointed out that
    nothing in the code constrains what goes in that field: a Slack
    `hooks.slack.com/services/...`, a second Discord webhook, an IFTTT
    `.../with/key/...` or a Home Assistant `/api/webhook/<id>` are all valid
    values and every one is a bearer capability. So the distinction rested on
    an assumption the code does not enforce, while the SAME string is masked
    one plugin over. It is masked now. The cost -- not being able to re-read
    what you typed -- was already accepted for Discord, so accepting it here is
    consistency rather than a new trade."""

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
    wrong is worse than no list, because it reads as an inventory.

    **And this leak DEFEATS a mask on the same page.** `torrentpotato`'s Jackett
    sync writes `jackett_api_key` straight into `pass_key`
    (`torrentpotato.py`: "Use Jackett API key as passkey"). `jackett_api_key`
    IS password-typed, so for any user who has pressed Sync -- the documented
    happy path -- the same Jackett key is masked in one field and printed in
    clear six options below it. Anyone reading the exemption list would
    otherwise conclude the Jackett key is handled."""

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


class TestTheNextCredentialCannotShipUntyped:
    """The gap the rest of this file cannot close, and the reason it matters.

    Every test above names a credential explicitly. Review proved the
    consequence by adding a brand-new untyped `discord.bot_secret_token` to the
    live config: the whole suite stayed green. So the suite pins the 23 known
    ones and is structurally blind to the 24th -- which is exactly how this task
    was created in the first place, and how its own first pass missed ten more.

    The file's docstring claimed that reading LIVE declarations solved this. It
    does not: reading live declarations stops a listed option silently losing
    its type, and does nothing about an option nobody listed.

    So this sweeps the tree instead of trusting a list. It is deliberately
    name-based -- the same heuristic that missed ten fields last time -- because
    a heuristic that fires on the obvious cases is still worth having as a
    tripwire, PROVIDED nobody mistakes it for completeness. It is not
    completeness. `cookiesetting`, `passkey` and `webhook_url` are all in the
    pattern now only because review found them by reading labels and
    descriptions, which no regex would have done.

    Anything genuinely exempt goes in EXEMPT below with its reason, so the
    decision is recorded rather than the pattern being quietly loosened.
    """

    # name -> why it is not masked. Every entry is a decision someone made.
    EXEMPT = {
        'core.api_key': 'read-only, exists to be copied into third-party apps; '
                        'masking with no reveal control is a lockout (see above)',
        'core.ssl_key': 'a filesystem path to a key file, not the key',
        'newznab.api_key': "'type': 'combined' -- one control for six servers; "
                           'typing it does nothing and would break the UI',
        'torrentpotato.pass_key': "'type': 'combined', same as newznab",
        # NOT here: trakt.automation_client_id. The sweep never flags it
        # (`client_id` matches no credential pattern), so an exemption would be
        # dead weight -- which is what the new assertion below now forbids. The
        # decision that it stays readable is asserted on its own, in
        # TestOneFieldIsDeliberatelyNotMasked, where it belongs: this dict is
        # "things the sweep WOULD flag and we have decided against", not a
        # general register of opinions.
    }

    # `token` already subsumes auth_token/oauth_token/bot_token/api_token, so
    # they are not listed separately -- review caught them as dead
    # alternatives. Kept deliberately flat rather than "documenting" the names
    # that motivated the sweep: a pattern that lists redundant branches invites
    # the reader to assume each one is load-bearing.
    CREDENTIAL_NAME = re.compile(
        r'(api_?key|_key|passkey|secret|token|password|cookiesetting'
        r'|webhook_url)', re.I)

    @staticmethod
    def _literal(node):
        """The constant string entries of a dict literal, ignoring the rest."""
        got = {}
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
                    and isinstance(k.value, str)):
                got[k.value] = v.value
        return got

    def _all_options(self):
        """Every option under `couchpotato/`, WITH the section that owns it.

        Descends the real `config = [{name, groups: [{options: [...]}]}]` shape
        rather than walking every dict in the file. An earlier version did the
        flat walk, which yielded options with no section attached -- and the
        exemption check then compared bare option names, so `core.api_key`
        silently exempted EVERY option called `api_key` in every plugin.
        Review caught it: a future `newplugin.api_key` would have sailed
        through the tripwire built to catch exactly that.

        Parsed rather than imported so a plugin that raises on import is still
        swept -- the point is to see declarations, not to run them."""
        root = Path(__file__).resolve().parents[2] / 'couchpotato'
        for path in sorted(root.rglob('*.py')):
            try:
                tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
            except SyntaxError:                       # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                entry = self._literal(node)
                section = entry.get('name')
                if not isinstance(section, str):
                    continue
                # An ENTRY is a dict with a name and a `groups` list; anything
                # else is an option, a group, or unrelated.
                groups = None
                for k, v in zip(node.keys, node.values):
                    if (isinstance(k, ast.Constant) and k.value == 'groups'
                            and isinstance(v, ast.List)):
                        groups = v
                if groups is None:
                    continue
                for g in groups.elts:
                    if not isinstance(g, ast.Dict):
                        continue
                    for gk, gv in zip(g.keys, g.values):
                        if not (isinstance(gk, ast.Constant)
                                and gk.value == 'options'
                                and isinstance(gv, ast.List)):
                            continue
                        for o in gv.elts:
                            if isinstance(o, ast.Dict):
                                opt = self._literal(o)
                                if isinstance(opt.get('name'), str):
                                    yield path, section, opt

    def test_every_credential_shaped_option_is_masked_or_exempt(self):
        unmasked = []
        for path, section, opt in self._all_options():
            name = opt['name']
            if not self.CREDENTIAL_NAME.search(name):
                continue
            if opt.get('type') == 'password':
                continue
            # Full section.option identity. Comparing the bare name here was
            # the bug review found: it exempted every `api_key` everywhere.
            if f'{section}.{name}' in self.EXEMPT:
                continue
            unmasked.append(f'{section}.{name} ({path.name}, type={opt.get("type")!r})')

        assert not unmasked, (
            'credential-shaped options with no password type and no recorded '
            'exemption:\n  ' + '\n  '.join(sorted(set(unmasked))) +
            '\n\nEither declare "type": "password", or add it to EXEMPT with '
            'the reason. Do NOT loosen the pattern to make this pass.'
        )

    def test_the_sweep_can_actually_fail(self):
        """Guards the guard: the assertion above passes trivially if the AST
        walk finds nothing or the pattern matches nothing. Both are pinned."""
        found = list(self._all_options())
        assert len(found) > 300, f'AST walk found only {len(found)} options'

        names = [o['name'] for _, _, o in found]
        matched = [n for n in names if self.CREDENTIAL_NAME.search(n)]
        assert len(matched) > 20, (
            f'the credential pattern matched only {len(matched)} names; if the '
            f'naming convention changed, this tripwire has stopped working'
        )

    def test_no_exemption_is_dead_weight(self):
        """An exemption doing no work is worse than no exemption, because it
        reads as coverage. Two ways it can happen, and BOTH are asserted --
        the first version checked only the first and review found the second.

        1. The option no longer exists. Removed plugins have already caused
           that here: hadouken's options outlived its module.
        2. **The pattern never matches it**, so the sweep would not have
           flagged it and the exemption was never reachable. `core.ssl_key`
           was exactly this: `CREDENTIAL_NAME` had no `_key` alternative, so
           the entry sat in the list looking like a considered decision while
           protecting nothing. Fixed by widening the pattern rather than
           deleting the entry -- `ssl_key` SHOULD be swept, so that a future
           `something_key` credential is caught; the exemption then does real
           work, which is the point."""
        declared = {f'{sec}.{o["name"]}' for _, sec, o in self._all_options()}
        for entry in sorted(self.EXEMPT):
            assert entry in declared, (
                f'EXEMPT names {entry}, but no such section.option is declared '
                f'anywhere under couchpotato/ -- delete the exemption'
            )
            option = entry.split('.', 1)[1]
            assert self.CREDENTIAL_NAME.search(option), (
                f'EXEMPT names {entry}, but CREDENTIAL_NAME never matches '
                f'{option!r}, so the sweep would not have flagged it and this '
                f'exemption protects nothing. Either widen the pattern so the '
                f'exemption is load-bearing, or delete the entry -- do not '
                f'leave it looking like a decision.'
            )
