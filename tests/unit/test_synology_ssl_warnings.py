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
"""
import logging

from couchpotato.core.downloaders.synology import SynologyRPC

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
