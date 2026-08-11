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
