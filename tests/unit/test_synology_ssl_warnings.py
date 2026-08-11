"""T17 follow-up A: S4830's real-world risk is not closed by making
verification/scheme *configurable* -- `ssl` still defaults to 0 (correct:
Synology DSM listens on 5000 for http, and flipping the default would break
every existing install), so out of the box the SYNO.API.Auth login still
puts the operator's username and password on the wire in clear text, and
nothing said so.

`SynologyRPC.__init__` must now log a WARNING in exactly two situations:

  1. credentials are configured AND the connection is plaintext http --
     the login is about to expose them;
  2. the connection is https AND certificate verification is disabled --
     the connection cannot confirm who it's talking to.

And must NOT warn when there is nothing to warn about: https with
verification on, or plaintext with no credentials configured (nothing to
expose, and a warning that fires when it needn't is one people learn to
ignore).

The message must name the setting that fixes the problem, never the value,
the host, or a filesystem path -- the project's log-privacy floor
(PrivacyFilter, CLAUDE.md) applies even though this text doesn't go through
`%`-args a caller controls.

T17 follow-up A2: both warnings are unbounded per-call, so an operator
running with the unsafe default sees one on every single download -- which
is self-defeating, since it trains them to scroll past the exact line added
so they wouldn't miss it. They now route through `log_suppressed`
(`couchpotato/core/logger.py:140`), keyed independently so plaintext-
credentials and verify-disabled don't mask each other, with `now` injected
through `SynologyRPC`'s own `now=` parameter rather than sleeping or
patching `time.monotonic` (patching the clock has already produced a
recorded false positive on this repo -- it also freezes `date.today()`).

T17 follow-up D (2026-08-11 review, finding 4): the plaintext-credentials
warning told the operator to "Enable the ssl setting", but `host` defaults
to `localhost:5000` -- DSM's PLAINTEXT port -- and DSM serves https on 5001.
Flipping only `ssl` produces `https://host:5000`, which `download()` cannot
reach and swallows as "Exception while adding torrent", returned as a bare
False. An operator who does exactly what the warning says gets broken
downloads with no diagnosis, and the rational response is to turn `ssl`
back off -- landing them back in the state the warning existed to move them
out of. The warning now names the port change explicitly (never the
operator's OWN host value -- 5001 is DSM's documented default, not
configuration read back to them) and that the setting sits behind the
Advanced toggle, which defaults off.

T17 follow-up E (2026-08-11 review, finding 5): `ssl_verify = ` (present but
BLANK in config.ini) coerces to False -- verification OFF -- independently
measured by three review lenses against a REAL `Settings` instance and
`config.ini`, not a fake `conf()` lambda. `Settings.get()` only returns the
caller's `default` on the EXCEPTION path (the option genuinely absent), so
`getVerifySsl()`'s `default = True` fail-open covers a MISSING option but
not a blanked one -- a present-but-empty value reaches
`_coerce_value('', 'bool')`, which maps `''` to `False`.

This is deliberately NOT a bug being fixed here: the warning is the answer
to a blank value ending up unsafe, not more parsing (blank and explicit-off
are indistinguishable after coercion, so there is nothing to parse
differently). What follows PINS that answer against a real Settings/
config.ini, so a future change to `_coerce_value` that flips this in either
direction is caught here rather than discovered in production. The upgrade
path was separately confirmed safe and is not retested here: with all three
keys absent, `ssl` reads None (http, unchanged) and `ssl_verify` reads True.
"""
import logging

import pytest

from couchpotato.core.downloaders.synology import Synology, SynologyRPC

# Deliberately distinctive so a leak can't hide as a substring of unrelated
# log text (a short username/password like 'op'/'x' could coincidentally
# appear inside another word and mask a real failure).
_USERNAME = 'synology_operator_9f3a'
_PASSWORD = 'Tr0ub4dor&3-hunter2'
_HOST = 'my-actual-nas-hostname'


def _warning_records(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


class TestPlaintextCredentialWarning:

    def test_warns_when_credentials_configured_over_plaintext_http(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False)

        assert len(_warning_records(caplog)) == 1

    def test_warning_explains_the_port_must_change_too(self, caplog):
        """The remediation the warning asks for ("enable ssl") breaks
        downloads on its own: host defaults to DSM's plaintext port 5000,
        DSM serves https on 5001, and flipping only `ssl` produces
        `https://host:5000`, which fails. An operator who does exactly what
        the warning says without also changing the port ends up with
        broken downloads and no diagnosis -- worse than the warning never
        having fired."""
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False)

        message = _warning_records(caplog)[0].getMessage()
        assert '5001' in message, 'must name the https port DSM actually needs'
        assert 'port' in message
        assert 'Advanced' in message, (
            'the setting is behind the Advanced toggle (default off) -- '
            '"enable ssl" is not self-evidently findable otherwise'
        )

    def test_no_warning_for_plaintext_with_no_credentials_configured(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, ssl = False)

        assert _warning_records(caplog) == []

    def test_no_warning_for_plaintext_with_only_username_no_password(self, caplog):
        """Matches _login()'s own guard (`if username and password`) --
        half a credential pair can't authenticate, so there's nothing being
        exposed yet either."""
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = None, ssl = False)

        assert _warning_records(caplog) == []

    def test_no_plaintext_warning_when_ssl_is_on(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = True, verify = True)

        assert _warning_records(caplog) == []


class TestVerificationDisabledWarning:

    def test_warns_when_https_verification_disabled(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, ssl = True, verify = False)

        assert len(_warning_records(caplog)) == 1

    def test_no_warning_when_https_verification_enabled(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, ssl = True, verify = True)

        assert _warning_records(caplog) == []

    def test_no_verification_warning_on_plaintext_connections(self, caplog):
        """verify=False is meaningless on a plain http connection (there is
        no certificate to check) -- only the plaintext-credentials warning
        is the right one there, not this one."""
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, ssl = False, verify = False)

        assert _warning_records(caplog) == []

    def test_ca_bundle_path_counts_as_verification_enabled(self, caplog, tmp_path):
        bundle = tmp_path / 'ca.pem'
        bundle.write_text('cert')
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, ssl = True, verify = str(bundle))

        assert _warning_records(caplog) == []


class TestNoSensitiveDataInWarnings:

    def test_credential_values_do_not_appear_in_any_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False)
            SynologyRPC(_HOST, 5000, ssl = True, verify = False)

        assert _USERNAME not in caplog.text
        assert _PASSWORD not in caplog.text

    def test_host_does_not_appear_in_any_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False)
            SynologyRPC(_HOST, 5000, ssl = True, verify = False)

        assert _HOST not in caplog.text


class TestSuppressionOfRepeatedWarnings:
    """An unbounded warning on every download is self-defeating -- the
    operator learns to scroll past the exact line added so they wouldn't
    miss it -- but "only warn once ever" loses the signal that it's an
    ONGOING misconfiguration, not a one-off. `log_suppressed`'s contract
    keeps both: the first occurrence in full, one "further messages
    withheld" notice, silence until the window passes, then the next
    occurrence in full WITH the count withheld.

    `now` is injected via SynologyRPC's own `now=` parameter, which flows
    straight through to `log_suppressed` -- not by sleeping (300s default
    window) and not by patching `time.monotonic` (this repo has a recorded
    false positive from patching a module-level clock: it also freezes
    `date.today()`, per couchpotato/core/logger.py's own docstring).
    """

    def test_first_occurrence_emits_in_full(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False, now = 0)

        records = _warning_records(caplog)
        assert len(records) == 1
        assert 'ssl' in records[0].getMessage()

    def test_burst_within_window_does_not_repeat_the_full_message(self, caplog):
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False, now = 0)

        # 1 full message + 1 "repeating" notice -- not 5 full messages.
        assert len(_warning_records(caplog)) == 2

    def test_withheld_count_reported_after_window_passes(self, caplog):
        with caplog.at_level(logging.WARNING):
            for _ in range(4):
                SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False, now = 0)
            # LOG_SUPPRESSION_WINDOW is 300s -- 301 is past it.
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False, now = 301)

        records = _warning_records(caplog)
        # occurrence 1 (full) + occurrence 2 (repeating notice, occurrences
        # 3-4 silent) + occurrence 5 (full, with the withheld count).
        assert len(records) == 3
        assert 'suppressed' in records[-1].getMessage()

    def test_two_warning_keys_do_not_suppress_each_other(self, caplog):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False, now = 0)
            SynologyRPC(_HOST, 5000, ssl = True, verify = False, now = 0)

        # Both are first occurrences of DIFFERENT keys, so both fire in
        # FULL -- neither key's history should hold the other back. A bare
        # count of 2 does not prove this: sharing one key for both warnings
        # also produces 2 records (one full message + one "repeating"
        # notice), so each record's content is checked explicitly rather
        # than just how many there are.
        records = _warning_records(caplog)
        assert len(records) == 2
        messages = [r.getMessage() for r in records]
        assert any('"ssl"' in m and 'unencrypted' in m for m in messages), (
            'the plaintext-credentials warning must appear in full')
        assert any('"ssl_verify"' in m and 'verification' in m for m in messages), (
            'the verify-disabled warning must appear in full')
        assert not any('repeating' in m for m in messages), (
            'neither warning should have been suppressed by the other key'
        )

    def test_credential_values_do_not_appear_even_in_the_withheld_notice(self, caplog):
        with caplog.at_level(logging.WARNING):
            for _ in range(4):
                SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False, now = 0)
            SynologyRPC(_HOST, 5000, username = _USERNAME, password = _PASSWORD, ssl = False, now = 301)

        assert _USERNAME not in caplog.text
        assert _PASSWORD not in caplog.text
        assert _HOST not in caplog.text


class TestBlankSslVerifyMeansVerificationOff:
    """Finding 5 -- pinned against a REAL Settings instance and config.ini,
    matching how the three review lenses measured it, not a fake conf()
    lambda that could quietly disagree with the real coercion layer."""

    @pytest.fixture
    def synology_with_blank_ssl_verify(self, config_file):
        from couchpotato.core.settings import Settings
        from couchpotato.environment import Env

        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from env_helper import env_restored  # noqa: E402

        with env_restored():
            s = Settings()
            s.setFile(config_file)
            s.addSection('synology')
            s.p.set('synology', 'ssl', '1')
            s.p.set('synology', 'ssl_verify', '')  # present but BLANK
            s.setType('synology', 'ssl', 'bool')
            s.setType('synology', 'ssl_verify', 'bool')
            Env.set('settings', s)

            yield Synology.__new__(Synology)

    def test_blank_ssl_verify_coerces_to_verification_off(self, synology_with_blank_ssl_verify):
        assert synology_with_blank_ssl_verify.getVerifySsl() is False

    def test_blank_ssl_verify_fires_the_verification_disabled_warning(
        self, synology_with_blank_ssl_verify, caplog,
    ):
        with caplog.at_level(logging.WARNING):
            SynologyRPC(
                'mynas', 5001, ssl = True,
                verify = synology_with_blank_ssl_verify.getVerifySsl(),
                now = 0,
            )

        records = _warning_records(caplog)
        assert len(records) == 1
        assert 'ssl_verify' in records[0].getMessage()
