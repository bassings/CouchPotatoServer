"""T53: the Trakt notifier reads a config section nothing registers, so it
can never authorise.

`couchpotato/core/loader.py::loadSettings` registers every plugin's `config`
block under the top-level ENTRY name (`section['name']`), never under a
group's `name`. The Trakt automation module declares entry name `'trakt'`
with a group named `'trakt_automation'` -- and `couchpotato/core/notifications
/trakt.py` used to override `conf()` to read `automation_client_id`,
`automation_client_secret`, `automation_oauth_token` and
`automation_oauth_refresh` from section `'trakt_automation'`, the GROUP name.
Nothing ever registers that section, so every read came back `''` and the
notifier logged "Trakt not authorized" regardless of how the user had
configured it.

This test drives the REAL loader path, not a stand-in for it: both the
automation module's `config` and the notifier's own `config` go through
`Loader.loadSettings` -- the exact call `Loader.run()` makes for every
discovered plugin -- into a real `Settings` bound to a `tmp_path` config file.
A fixture that called `Settings.registerDefaults` directly, or synthesised its
own `config` dict, would keep passing even if `loadSettings` regressed the
section name again; going through `loadSettings` is the only way this test
can see that class of bug.
"""
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from couchpotato.core import event as cp_event
from couchpotato.core.loader import Loader
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_helper import env_restored  # noqa: E402

pytestmark = pytest.mark.unit

AUTOMATION_MODULE = 'couchpotato.core.media.movie.providers.automation.trakt'
NOTIFIER_MODULE = 'couchpotato.core.notifications.trakt'

# The credentials the automation module's OAuth flow writes, and which the
# notifier must read back under the same names.
CREDENTIALS = {
    'automation_client_id': 'REAL_CLIENT_ID',
    'automation_client_secret': 'REAL_CLIENT_SECRET',
    'automation_oauth_token': 'REAL_OAUTH_TOKEN',
    'automation_oauth_refresh': 'REAL_OAUTH_REFRESH',
}


@contextmanager
def _events_scoped_to(settings):
    """Wire `settings.options` / `settings.register` to `settings` alone for
    the duration of the block, then restore whatever was there before.

    `Settings.setFile()` calls `connectEvents()`, which adds handlers to the
    process-wide registry in `couchpotato.core.event` and never removes them
    -- every earlier test in this session that built a `Settings()` has left
    one sitting there. Firing the real event with all of that attached would
    still be CORRECT (each stale handler only ever touches its own orphaned
    instance), just slow and dependent on collection order. Snapshotting and
    restoring these two names keeps `Loader.loadSettings`'s real
    fireEvent-based path -- nothing about it is stubbed -- while making the
    test deterministic regardless of what ran before it.
    """
    names = ('settings.options', 'settings.register')
    saved = {name: list(cp_event.events.get(name, [])) for name in names}
    for name in names:
        cp_event.events[name] = []
    cp_event.addEvent('settings.options', settings.addOptions)
    cp_event.addEvent('settings.register', settings.registerDefaults)
    try:
        yield
    finally:
        for name, handlers in saved.items():
            cp_event.events[name] = handlers


def _load_via_loader(settings, module):
    """Drive `Loader.loadSettings` for real -- the exact call `Loader.run()`
    makes for every plugin module it discovers -- rather than calling
    `Settings.registerDefaults` by hand. T53 is a bug in what `loadSettings`
    passes as the section name, so a test that bypasses `loadSettings` could
    not see it."""
    with _events_scoped_to(settings):
        ok = Loader().loadSettings(module, module.__name__, save=False)
    assert ok, f'loadSettings reported failure for {module.__name__}'


@pytest.fixture
def wired_settings(tmp_path):
    """A real `Settings`, bound to a real config file on disk holding the
    credentials as the automation module's OAuth flow would have written
    them -- under `[trakt]`, its own top-level entry name -- with both
    plugins' `config` blocks registered through the real loader path, and
    made the active `Env.setting()` target for the duration of the test."""
    cfg = tmp_path / 'config.ini'
    body = '[trakt]\n' + ''.join(
        f'{name} = {value}\n' for name, value in CREDENTIALS.items()
    )
    cfg.write_text(body, encoding='utf-8')

    with env_restored():
        settings = Settings()
        settings.setFile(str(cfg))
        Env.set('settings', settings)

        automation_module = importlib.import_module(AUTOMATION_MODULE)
        notifier_module = importlib.import_module(NOTIFIER_MODULE)
        _load_via_loader(settings, automation_module)
        _load_via_loader(settings, notifier_module)

        yield settings, notifier_module


class TestTraktNotifierReadsWhatAutomationWrote:
    """The regression pin for T53."""

    @pytest.mark.parametrize('credential', sorted(CREDENTIALS))
    def test_notifier_reads_the_credential_automation_wrote(
        self, wired_settings, credential,
    ):
        _settings, notifier_module = wired_settings
        notifier = notifier_module.Trakt.__new__(notifier_module.Trakt)

        got = notifier.conf(credential)

        assert got == CREDENTIALS[credential], (
            f'notifier.conf({credential!r}) -> {got!r}; the automation '
            f'module wrote it to section [trakt] and the notifier must read '
            f'it from the same place -- got an empty/wrong value, which '
            f'means the notifier is still reading a section nothing '
            f'registers'
        )

    def test_the_automation_module_itself_reads_the_same_credential(
        self, wired_settings,
    ):
        """Control: prove the automation side already works, so a failure
        above is provably the notifier's bug and not a fixture mistake."""
        settings, _notifier_module = wired_settings
        automation_module = importlib.import_module(AUTOMATION_MODULE)

        provider = automation_module.Trakt.__new__(automation_module.Trakt)

        assert provider.conf('automation_oauth_token') == 'REAL_OAUTH_TOKEN'
        assert settings.get('automation_oauth_token', 'trakt') == 'REAL_OAUTH_TOKEN'
