"""T17 fix 1 (python:S4830): the Synology downloader's `SYNO.API.Auth` login
carries the operator's username and password to `SynologyRPC._req`, which
hard-coded `requests.post(..., verify=False)` and built its `download_url`/
`auth_url` as literal `http://`. Fixing only `verify` would clear the
scanner finding while leaving the password readable in plaintext, so the
scheme and the verification flag are tested and fixed together.

Reachability (per specs/REMEDIATION-2026-08.md T17): the downloader ships
disabled by default, so this affects operators who have deliberately turned
it on -- exactly the set who typed a password into it.
"""
from unittest.mock import MagicMock, patch

from couchpotato.core.downloaders import synology as synology_module
from couchpotato.core.downloaders.synology import Synology, SynologyRPC


# ===========================================================================
# SynologyRPC -- scheme + verify wiring
# ===========================================================================

class TestSynologyRPCScheme:

    def test_default_is_plain_http_for_backward_compatibility(self):
        """ssl defaults off (matches the config's own default = 0) so an
        existing plaintext NAS setup keeps working unmodified."""
        rpc = SynologyRPC('mynas', 5000)

        assert rpc.download_url.startswith('http://mynas:5000/')
        assert rpc.auth_url.startswith('http://mynas:5000/')

    def test_ssl_true_builds_https_urls(self):
        rpc = SynologyRPC('mynas', 5001, ssl = True)

        assert rpc.download_url == 'https://mynas:5001/webapi/DownloadStation/task.cgi'
        assert rpc.auth_url == 'https://mynas:5001/webapi/auth.cgi'


class TestSynologyRPCVerifyPassedToRequests:
    """The SYNO.API.Auth login is the request that carries the password --
    assert on exactly what reaches `requests.post`, not on an internal
    attribute, so a refactor that silently drops the flag on its way to the
    network call still fails this test."""

    def test_login_passes_verify_true_by_default(self):
        rpc = SynologyRPC('mynas', 5000, username = 'op', password = 'hunter2', verify = True)

        mock_response = MagicMock()
        mock_response.text = '{"success": true, "data": {"sid": "abc"}}'
        with patch.object(synology_module.requests, 'post', return_value = mock_response) as mock_post:
            rpc._login()

        assert mock_post.call_args.kwargs['verify'] is True

    def test_login_passes_verify_false_when_explicitly_configured_off(self):
        rpc = SynologyRPC('mynas', 5000, username = 'op', password = 'hunter2', verify = False)

        mock_response = MagicMock()
        mock_response.text = '{"success": true, "data": {"sid": "abc"}}'
        with patch.object(synology_module.requests, 'post', return_value = mock_response) as mock_post:
            rpc._login()

        assert mock_post.call_args.kwargs['verify'] is False

    def test_login_passes_ca_bundle_path_when_configured(self, tmp_path):
        bundle = tmp_path / 'ca.pem'
        bundle.write_text('cert')
        rpc = SynologyRPC('mynas', 5000, username = 'op', password = 'hunter2', verify = str(bundle))

        mock_response = MagicMock()
        mock_response.text = '{"success": true, "data": {"sid": "abc"}}'
        with patch.object(synology_module.requests, 'post', return_value = mock_response) as mock_post:
            rpc._login()

        assert mock_post.call_args.kwargs['verify'] == str(bundle)

    def test_default_constructor_verify_value_is_true(self):
        """The class default (no verify= passed at all) must itself be safe
        -- a caller that forgets the keyword must not silently disable
        verification."""
        rpc = SynologyRPC('mynas', 5000, username = 'op', password = 'hunter2')

        mock_response = MagicMock()
        mock_response.text = '{"success": true, "data": {"sid": "abc"}}'
        with patch.object(synology_module.requests, 'post', return_value = mock_response) as mock_post:
            rpc._login()

        assert mock_post.call_args.kwargs['verify'] is True


# ===========================================================================
# Synology downloader -- wires conf('ssl') / getVerifySsl() into SynologyRPC
# ===========================================================================

class TestSynologyDownloaderWiresSsl:

    def _conf(self, **overrides):
        values = {
            'host': 'localhost:5000', 'username': 'op', 'password': 'hunter2',
            'destination': '', 'ssl': False, 'ssl_verify': True, 'ssl_ca_bundle': '',
        }
        values.update(overrides)
        return lambda k, **kw: values.get(k, kw.get('default', ''))

    def test_test_builds_synologyrpc_with_resolved_ssl_and_verify(self):
        downloader = Synology.__new__(Synology)

        captured = {}

        class _CapturingRPC(SynologyRPC):
            def __init__(self, *args, **kwargs):
                captured['args'] = args
                captured['kwargs'] = kwargs
                super().__init__(*args, **kwargs)

            def test(self):
                return True

        with patch.object(downloader, 'conf', side_effect = self._conf(ssl = True, ssl_verify = False)), \
             patch.object(synology_module, 'SynologyRPC', _CapturingRPC):
            downloader.test()

        assert captured['kwargs'].get('ssl') is True
        assert captured['kwargs'].get('verify') is False

    def test_test_defaults_to_verifying_plaintext_http(self):
        downloader = Synology.__new__(Synology)

        captured = {}

        class _CapturingRPC(SynologyRPC):
            def __init__(self, *args, **kwargs):
                captured['args'] = args
                captured['kwargs'] = kwargs
                super().__init__(*args, **kwargs)

            def test(self):
                return True

        with patch.object(downloader, 'conf', side_effect = self._conf()), \
             patch.object(synology_module, 'SynologyRPC', _CapturingRPC):
            downloader.test()

        assert captured['kwargs'].get('ssl') is False
        assert captured['kwargs'].get('verify') is True
