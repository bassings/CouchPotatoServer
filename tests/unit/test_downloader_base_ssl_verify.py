"""T17 fix 1 (python:S4830), base-class half: `getVerifySsl` is hoisted from
`rtorrent_.py` to `DownloaderBase` (`_base/downloader/main.py`) so Synology
(and any future downloader) shares one implementation instead of growing its
own copy that can silently drift.

The critical requirement, called out explicitly in the remediation spec: a
downloader with NO `ssl_verify` config option at all must get a VERIFYING
value back, not a disabled one. rtorrent's original implementation was
`if not self.conf('ssl_verify'): return False` -- for a downloader with no
such setting, `self.conf('ssl_verify')` returns None (falsy), so hoisting
that as-is would have silently turned off certificate verification for
every downloader that inherits it and never defines the option. The base
implementation must treat "unset" as verify-on and only an explicit false
value as off.
"""
from couchpotato.core._base.downloader.main import DownloaderBase


class _FakeSettingsDownloader(DownloaderBase):
    """A downloader stub whose `conf()` mimics Plugin.conf()'s real contract:
    a setting absent from `_settings` returns whatever `default` conf() was
    called with (exactly what Env.setting()/Settings.get() do for a
    downloader with no matching config option) -- it does NOT unconditionally
    return None regardless of `default`, which would make this test pass for
    the wrong reason."""

    def __init__(self, settings = None):
        # Deliberately skip DownloaderBase.__init__ -- it calls addEvent()
        # and friends, none of which getVerifySsl() needs.
        self._settings = settings or {}

    def conf(self, attr, value = None, default = None, section = None):
        return self._settings.get(attr, default)


class TestGetVerifySslFailsOpen:

    def test_downloader_with_no_ssl_settings_at_all_verifies(self):
        """The load-bearing case: a downloader that never defines ssl_verify
        must still verify certificates by default."""
        downloader = _FakeSettingsDownloader(settings = {})

        assert downloader.getVerifySsl() is True

    def test_ssl_verify_explicitly_true_verifies(self):
        downloader = _FakeSettingsDownloader(settings = {'ssl_verify': True})

        assert downloader.getVerifySsl() is True


class TestGetVerifySslExplicitOff:

    def test_ssl_verify_explicitly_false_disables_verification(self):
        downloader = _FakeSettingsDownloader(settings = {'ssl_verify': False})

        assert downloader.getVerifySsl() is False


class TestGetVerifySslCaBundle:

    def test_existing_ca_bundle_path_is_returned(self, tmp_path):
        bundle = tmp_path / 'ca-bundle.pem'
        bundle.write_text('-----BEGIN CERTIFICATE-----')
        downloader = _FakeSettingsDownloader(settings = {
            'ssl_verify': True, 'ssl_ca_bundle': str(bundle),
        })

        assert downloader.getVerifySsl() == str(bundle)

    def test_missing_ca_bundle_path_falls_back_to_true(self, tmp_path):
        missing = tmp_path / 'does-not-exist.pem'
        downloader = _FakeSettingsDownloader(settings = {
            'ssl_verify': True, 'ssl_ca_bundle': str(missing),
        })

        assert downloader.getVerifySsl() is True

    def test_ca_bundle_ignored_when_verify_is_off(self, tmp_path):
        bundle = tmp_path / 'ca-bundle.pem'
        bundle.write_text('-----BEGIN CERTIFICATE-----')
        downloader = _FakeSettingsDownloader(settings = {
            'ssl_verify': False, 'ssl_ca_bundle': str(bundle),
        })

        assert downloader.getVerifySsl() is False
