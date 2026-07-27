"""One malformed release must not abort the whole snatched-status pass.

Found on production running v3.17.0. `renamer.check_snatched` runs every
minute and was failing with:

    File "couchpotato/core/plugins/renamer/scanner.py", line 82, in checkSnatched
        nzbname = self.createNzbName(rel['info'], movie_dict)
    File "couchpotato/core/helpers/variable.py", line 346, in scanForPassword
        m = reg.search(name)
    TypeError: expected string or bytes-like object, got 'NoneType'

Three separate defects chain together:

1. `scanForPassword()` calls `reg.search(name)` with no type guard, so a
   missing name raises TypeError instead of "no password found".
2. `rel['info']['name']` is None for every release created before v3.17.0 —
   the `createFromSearch` loop raised NameError on `unicode`/`long` before it
   could populate `info`, so those documents have an empty dict. 1133 of 1454
   releases on the production box are in that state.
3. **The `try:` in `checkSnatched` wraps the entire `for rel in rels:` loop**,
   so the exception aborts the pass. Releases after the bad one are never
   checked at all — a completed download is never noticed, so renaming and
   post-processing never fire for it.

(3) is the one that costs something: on the affected box a single malformed
release was blocking status checks for the other 16.
"""

from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.helpers.variable import scanForPassword


class TestScanForPassword:

    @pytest.mark.parametrize('value', [None, '', 0, [], {}], ids=repr)
    def test_falsy_input_is_not_a_password(self, value):
        """Bug repro: None raised TypeError out of a helper whose job is to
        answer "is there a password in this name" -- "no name" is a perfectly
        ordinary answer of "no"."""
        assert scanForPassword(value) is None

    @pytest.mark.parametrize('value', [123, object(), b'bytes'], ids=lambda v: type(v).__name__)
    def test_non_string_input_is_not_a_password(self, value):
        """bytes matter specifically: `re.search` with a str pattern against
        bytes raises TypeError too, so this is not hypothetical."""
        assert scanForPassword(value) is None

    def test_curly_brace_password_still_parsed(self):
        """Regression guard: the two real formats must keep working."""
        assert scanForPassword('Some.Movie.2026.1080p{{hunter2}}') == (
            'Some.Movie.2026.1080p', 'hunter2',
        )

    def test_password_keyword_still_parsed(self):
        assert scanForPassword('Some.Movie.2026 password = hunter2') == (
            'Some.Movie.2026', 'hunter2',
        )

    def test_a_plain_name_has_no_password(self):
        assert scanForPassword('Some.Movie.2026.1080p.BluRay') is None


class TestCreateNzbName:
    """The caller, which reaches scanForPassword with whatever `info` holds."""

    def _plugin(self):
        from couchpotato.core.plugins.base import Plugin

        plugin = object.__new__(Plugin)
        return plugin

    def test_a_release_with_no_name_does_not_raise(self):
        """`info` is an empty dict on every pre-v3.17.0 release."""
        plugin = self._plugin()

        with patch.object(type(plugin), 'cpTag', return_value='', create=True):
            name = plugin.createNzbName({}, {'title': 'Some Movie'})

        assert isinstance(name, str)


class TestCheckSnatchedIsolatesBadReleases:
    """The structural fix: a per-release failure must not end the pass."""

    def _scanner(self):
        from couchpotato.core.plugins.renamer.scanner import ScannerMixin

        scanner = object.__new__(ScannerMixin)
        scanner.checking_snatched = False
        return scanner

    def _release(self, rel_id, name):
        """`name=None` reproduces a pre-v3.17.0 release with empty info."""
        return {
            '_id': rel_id,
            'media_id': 'movie-%s' % rel_id,
            'status': 'snatched',
            'info': {'name': name} if name is not None else {},
            'download_info': {'id': 'dl-%s' % rel_id, 'downloader': 'sabnzbd',
                              'status_support': True},
        }

    def test_one_failing_release_does_not_stop_the_others(self):
        """The structural property, tested independently of the specific bug.

        The landmine here is a db.get() failure on the middle release rather
        than the nameless-release TypeError -- that one is fixed at source
        now, so it can no longer demonstrate isolation. What matters is that
        ANY per-release exception is contained: releases behind it must still
        be processed.
        """
        scanner = self._scanner()
        rels = [
            self._release('1', 'Good.One.1080p'),
            self._release('2', 'Boom.1080p'),
            self._release('3', 'Good.Two.1080p'),
        ]
        checked = []

        def fake_fire_event(name, *args, **kwargs):
            if name == 'release.with_status':
                return list(rels)
            if name == 'download.status':
                return [{'id': 'dl-%s' % r['_id'], 'downloader': 'sabnzbd',
                         'name': r['info'].get('name') or '', 'status': 'busy',
                         'timeleft': -1, 'scan': False, 'folder': '/downloads/x'} for r in rels]
            if name == 'release.update_status':
                checked.append(str(args[0]) if args else None)
            return None

        def flaky_get(index, key):
            if key == 'movie-2':
                raise RuntimeError('simulated per-release failure')
            return {'_id': key, 'title': 'Some Movie', 'identifiers': {'imdb': 'tt1'}}

        db = MagicMock()
        db.get.side_effect = flaky_get

        with patch('couchpotato.core.plugins.renamer.scanner.fireEvent', side_effect=fake_fire_event), \
                patch('couchpotato.core.plugins.renamer.scanner.get_db', return_value=db), \
                patch.object(type(scanner), 'conf', return_value=False, create=True), \
                patch.object(type(scanner), 'createNzbName', return_value='x', create=True), \
                patch.object(type(scanner), 'untagRelease', return_value=None, create=True), \
                patch.object(type(scanner), 'scan', return_value=None, create=True):
            scanner.checkSnatched(fire_scan=False)

        assert '3' in checked, (
            'the release after the failing one was never processed -- one bad '
            'document is blocking status checks for everything behind it '
            '(processed: %s)' % checked
        )

    def test_a_downloader_without_status_support_does_not_raise(self):
        """Second instance of the same root cause, found in review.

        When download_info lacks an id/downloader, the code logs which release
        it is skipping using `rel['info']['name']` -- direct key access, which
        KeyErrors on the empty info dict every pre-v3.17.0 release has. The
        raise happens BEFORE `scan_required = True`, so that release's rescan
        signal is lost as well.
        """
        scanner = self._scanner()
        # A MIX is required: with no download ids at all, checkSnatched
        # returns before the loop, so the offending line is unreachable.
        good = self._release('1', 'Good.One.1080p')
        bad = self._release('2', None)
        bad['download_info'] = {'status_support': True}     # no id, no downloader

        errors = []

        def fake_fire_event(name, *args, **kwargs):
            if name == 'release.with_status':
                return [good, bad]
            if name == 'download.status':
                return [{'id': 'dl-1', 'downloader': 'sabnzbd', 'name': 'x',
                         'status': 'busy', 'timeleft': -1, 'scan': False}]
            return None

        db = MagicMock()
        db.get.return_value = {'_id': 'movie-1', 'title': 'Some Movie'}

        with patch('couchpotato.core.plugins.renamer.scanner.fireEvent', side_effect=fake_fire_event), \
                patch('couchpotato.core.plugins.renamer.scanner.get_db', return_value=db), \
                patch('couchpotato.core.plugins.renamer.scanner.log') as mock_log, \
                patch.object(type(scanner), 'conf', return_value=False, create=True), \
                patch.object(type(scanner), 'createNzbName', return_value='x', create=True), \
                patch.object(type(scanner), 'untagRelease', return_value=None, create=True), \
                patch.object(type(scanner), 'scan', return_value=None, create=True):
            scanner.checkSnatched(fire_scan=False)
            # Inspect the real arguments -- str(call) escapes the quotes, so a
            # naive substring search silently never matches.
            errors = [str(a) for c in mock_log.error.call_args_list for a in c.args]

        assert not any("KeyError: 'name'" in e for e in errors), (
            'the no-status-support path raised on the empty info dict instead '
            'of skipping cleanly: %s' % errors
        )

    def test_the_pass_still_completes(self):
        """It must not leave `checking_snatched` latched either, or every
        later run short-circuits."""
        scanner = self._scanner()

        def fake_fire_event(name, *args, **kwargs):
            if name == 'release.with_status':
                return [self._release('1', None)]
            if name == 'download.status':
                return [{'id': 'dl-1', 'downloader': 'sabnzbd', 'name': '',
                         'status': 'busy', 'timeleft': -1, 'scan': False}]
            return None

        db = MagicMock()
        db.get.return_value = {'_id': 'movie-1', 'title': 'Some Movie'}

        with patch('couchpotato.core.plugins.renamer.scanner.fireEvent', side_effect=fake_fire_event), \
                patch('couchpotato.core.plugins.renamer.scanner.get_db', return_value=db), \
                patch.object(type(scanner), 'conf', return_value=False, create=True), \
                patch.object(type(scanner), 'createNzbName', return_value='x', create=True), \
                patch.object(type(scanner), 'untagRelease', return_value=None, create=True), \
                patch.object(type(scanner), 'scan', return_value=None, create=True):
            scanner.checkSnatched(fire_scan=False)

        assert scanner.checking_snatched is False
