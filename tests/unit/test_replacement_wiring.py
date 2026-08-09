"""The replacement decision is REACHED with real scan data (FEAT-009B B4a).

This is the test attempt #2 never had, and its absence is why that attempt
shipped. It was simultaneously dangerous and inert: the gate would have
destroyed a 2160p remux, but the releases it needed were never attached, so it
refused everything and nobody ever saw it fire. Fixing the inertness would have
activated the destruction.

So the assertions here are about REACHABILITY, not just refusal:

  * the decision runs with releases actually fetched for the group's media;
  * a test asserting `declined_not_better` FAILS if the releases attachment is
    removed -- otherwise it would pass for a gate that never ran at all;
  * the `upgrade_replace` gate is the thing consulted, not the dead key.

Nothing is replaced yet: `_moveRenamedFiles` still skips. This step exists to
prove the decision is live before anything acts on it.
"""
import logging
import os

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes
from couchpotato.core.plugins.renamer.owner import DECLINED_NO_OWNER
from couchpotato.core.plugins.renamer.replacement import (
    DECLINED_ERROR,
    DECLINED_INCOMPLETE_EVIDENCE,
    DECLINED_NOT_BETTER,
    DECLINED_SETTING_OFF,
    REPLACE,
)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    """A real destination file, a real group, and a release that owns it."""
    dst = tmp_path / 'The Thing.mkv'
    dst.write_bytes(b'x' * 5000)

    release = {
        '_id': 'r-existing',
        'files': {'movie': [str(dst)]},
        'copy_id': copy_id_for_sizes([5000]),
        'quality': '720p',
        'is_3d': False,
    }

    state = {
        'releases': [release],
        'for_media_calls': [],
        'conf': {
            'upgrade_replace': True,
            'to': str(tmp_path),          # the library root: see e2e fixture
            'default_file_action': 'move',
        },
    }

    def _fire(event, *args, **kwargs):
        if event == 'release.for_media':
            state['for_media_calls'].append(args[0] if args else None)
            return state['releases']
        if event == 'quality.is_better':
            order = ['2160p', 'bd50', '1080p', '720p']
            try:
                return order.index(args[0]['identifier']) < order.index(args[1]['identifier'])
            except (KeyError, ValueError, TypeError):
                return False
        if event == 'quality.rank':
            order = ['2160p', 'bd50', '1080p', '720p']
            try:
                return order.index(args[0]['identifier'])
            except (KeyError, ValueError, TypeError):
                return None
        return None

    monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent', _fire)

    plugin = Renamer.__new__(Renamer)
    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: state['conf'].get(key, default),
        raising=False,
    )
    # Restored, not just reset. `TestTheDeadSettingIsAnnouncedOnce` leaves it
    # True, and other test files import Renamer in the same process -- a
    # leaked True would silence a warning a later test expects to see.
    monkeypatch.setattr(Renamer, '_warned_dead_setting', False, raising=False)

    def _group(incoming='2160p', movie_files=None):
        return {
            'media': {'_id': 'media-1'},
            'meta_data': {'quality': {'identifier': incoming, 'is_3d': False}},
            'files': {'movie': movie_files if movie_files is not None else [str(dst) + '.new']},
            # How determineMedia identified this movie. Anything other than
            # an ASSERTED source refuses replacement, so a fixture without
            # this would exercise that refusal on every test.
            'identity_source': 'nfo',
        }

    return {'plugin': plugin, 'dst': str(dst), 'state': state, 'group': _group}


class TestTheDecisionIsActuallyReached:
    def test_a_better_copy_reaches_REPLACE_with_real_releases(self, scene):
        """The reachability assertion. If this ever returns a refusal for a
        clearly-better copy, the gate has gone inert again."""
        outcome, _victim = scene['plugin']._replacementOutcome(
            'src.mkv', scene['dst'], scene['group']('2160p')
        )
        assert outcome == REPLACE

    def test_releases_are_fetched_for_the_groups_own_media(self, scene):
        scene['plugin']._replacementOutcome('src.mkv', scene['dst'], scene['group']())
        assert scene['state']['for_media_calls'] == ['media-1']

    def test_declined_not_better_FAILS_if_the_releases_attachment_is_removed(self, scene):
        """AC-QA-11's anti-inertness pin, and the one that matters most.

        A worse copy should be refused as `declined_not_better`. If the
        releases attachment is broken -- exactly attempt #2's bug -- the
        outcome becomes `declined_no_owner` instead. Asserting the SPECIFIC
        refusal is what distinguishes "the gate ran and said no" from "the
        gate never ran".
        """
        outcome, _ = scene['plugin']._replacementOutcome(
            's.mkv', scene['dst'], scene['group']('720p')
        )
        assert outcome == DECLINED_NOT_BETTER

        # A FRESH group: releases are now cached per group (one lookup per
        # group, not one per colliding file), so reusing the dict above would
        # reuse its cached answer and this half would prove nothing.
        scene['state']['releases'] = []          # simulate the inert attempt
        outcome, _ = scene['plugin']._replacementOutcome(
            's.mkv', scene['dst'], scene['group']('720p')
        )
        assert outcome == DECLINED_NO_OWNER


class TestTheRankBoundaryNormalisesFireEventsEmptyList:
    """`fireEvent(single=True)` collects only non-None handler results and
    returns `[]` when there are none.

    So `rankQuality` answering None for an UNRECOGNISED identifier arrives as
    `[]`, and `[] is None` is False -- the unknown-identifier guard in
    decide_replacement never fired through the real wiring. It was dead in
    production while every unit test passed, because the tests injected a
    plain function instead of going through the event bus.

    This test goes through the REAL bus for that reason. Injecting a stand-in
    here would reproduce the blind spot it exists to close.
    """

    def test_an_unknown_identifier_normalises_to_None_not_empty_list(self, monkeypatch):
        from couchpotato.core import event as event_module
        from couchpotato.core.event import addEvent, fireEvent
        from couchpotato.core.plugins.quality.main import QualityPlugin

        # The event registry is module-global and shared by every test in the
        # process. Registering a handler on it without restoring leaks a
        # `quality.rank` responder into whatever runs next, so a later test
        # could pass because THIS one is still answering. Snapshot and restore.
        monkeypatch.setattr(
            event_module, 'events', dict(event_module.events), raising=True,
        )

        quality = QualityPlugin.__new__(QualityPlugin)
        quality.order = []
        quality.addOrder()
        addEvent('quality.rank', quality.rankQuality)

        # Confirm the precondition rather than assuming it: the raw event
        # really does hand back [] rather than None.
        assert fireEvent('quality.rank', {'identifier': 'laserdisc'}, single=True) == []

        assert Renamer._rankViaEvent({'identifier': 'laserdisc'}) is None
        assert Renamer._rankViaEvent({'identifier': '2160p'}) == 0


class TestTheGateConsultsTheNewKey:
    def test_upgrade_replace_off_refuses(self, scene):
        scene['state']['conf'] = {'upgrade_replace': False}
        outcome, _victim = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        assert outcome == DECLINED_SETTING_OFF

    def test_the_dead_key_being_true_does_NOT_enable_anything(self, scene):
        """The whole point of D1: `remove_lower_quality_copies` is already
        persisted True on every existing install. If it could still enable
        replacement, upgrading would start deleting library files."""
        scene['state']['conf'] = {'remove_lower_quality_copies': True}
        outcome, _victim = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        assert outcome == DECLINED_SETTING_OFF


class TestTheDeadSettingIsAnnouncedOnce:
    """Driven against the notice itself, because it is no longer reached from
    the collision path.

    It used to live inside `_replacementOutcome`, which only runs when a
    destination actually collides. An operator who deliberately set the old
    key on a library with nothing colliding therefore got precisely the
    silence D1 exists to prevent, and got it until something happened to
    collide. It is now emitted once per process at the top of a scan.
    """

    def test_an_operator_who_set_it_is_told_it_does_nothing(self, scene, caplog):
        scene['state']['conf'] = {'remove_lower_quality_copies': True}
        with caplog.at_level(logging.WARNING):
            scene['plugin']._warnAboutTheDeadSetting()
        assert any('no longer read' in r.getMessage() for r in caplog.records)

    def test_it_is_said_once_per_process_not_once_per_scan(self, scene, caplog):
        """The renamer runs on a timer. A warning repeated every few minutes
        is one an operator learns to filter out."""
        scene['state']['conf'] = {'remove_lower_quality_copies': True}
        with caplog.at_level(logging.WARNING):
            for _ in range(4):
                scene['plugin']._warnAboutTheDeadSetting()
        said = [r for r in caplog.records if 'no longer read' in r.getMessage()]
        assert len(said) == 1, 'warned %d times' % len(said)

    def test_nothing_is_said_when_the_operator_never_set_it(self, scene, caplog):
        scene['state']['conf'] = {'upgrade_replace': False}
        with caplog.at_level(logging.WARNING):
            scene['plugin']._warnAboutTheDeadSetting()
        assert not any('no longer read' in r.getMessage() for r in caplog.records)

    def test_the_scan_is_what_announces_it_not_a_collision(self, scene):
        """Anti-inertness. The notice reaching nobody is the bug this moved to
        fix, so the call site is pinned rather than assumed."""
        import inspect

        from couchpotato.core.plugins.renamer.main import Renamer

        scan_source = inspect.getsource(Renamer.scan)
        assert '_warnAboutTheDeadSetting()' in scan_source, (
            'the deprecation notice is no longer emitted from a scan, so an '
            'operator whose library has no collisions never hears it'
        )
        decision_source = inspect.getsource(Renamer._replacementOutcome)
        assert '_warnAboutTheDeadSetting()' not in decision_source, (
            'the notice is back on the per-collision path'
        )


class TestTheDecisionNeverBreaksAScan:
    def test_an_exploding_release_lookup_is_swallowed_as_a_refusal(self, scene, monkeypatch):
        """AC-QA-12. This runs inside the ordinary rename path, so an escaping
        exception would abort a scan that was otherwise fine."""
        def _boom(event, *a, **k):
            if event == 'release.for_media':
                raise RuntimeError('database went away')
            return None

        monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent', _boom)
        outcome, _victim = scene['plugin']._replacementOutcome(
            's.mkv', scene['dst'], scene['group']()
        )
        assert outcome == DECLINED_ERROR

    def test_a_group_with_no_media_does_not_raise(self, scene):
        outcome, _victim = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], {'files': {}})
        assert outcome != REPLACE

    def test_an_unstattable_destination_does_not_raise(self, scene):
        outcome, _victim = scene['plugin']._replacementOutcome(
            's.mkv', '/definitely/not/here.mkv', scene['group']()
        )
        assert outcome != REPLACE

    def test_an_unstattable_destination_is_NOT_reported_as_zero_bytes(self, scene, tmp_path):
        """`_sizeOrNone` returns None, not 0, and the difference is real.

        Zero is a SIZE -- a measurement we did not take. A release recorded
        for a zero-byte file (a failed download that was still catalogued)
        would then match an unreadable destination by copy_id and resolve as
        its owner, authorising a comparison against a file nobody could read.

        Mutation testing found this guard unproven: `return None` -> `return 0`
        changed no test, because every other case refuses for a different
        reason anyway. This is the input that distinguishes them.
        """
        empty_dst = tmp_path / 'unreadable.mkv'
        empty_dst.write_bytes(b'')
        zero_release = {
            '_id': 'r-zero',
            'files': {'movie': [str(empty_dst)]},
            'copy_id': copy_id_for_sizes([0]),
            'quality': '720p',
            'is_3d': False,
        }
        scene['state']['releases'] = [zero_release]

        # The destination cannot be stat'ed at all.
        assert scene['plugin']._sizeOrNone('/definitely/not/here.mkv') is None

        outcome, _victim = scene['plugin']._replacementOutcome(
            's.mkv', str(empty_dst), scene['group']('2160p')
        )
        # A real 0-byte file DOES resolve -- that is the control proving the
        # fixture is capable of resolving at all.
        assert outcome == REPLACE

        # But an unreadable one must not borrow that zero.
        outcome, _victim = scene['plugin']._replacementOutcome(
            's.mkv', '/definitely/not/here.mkv', scene['group']('2160p')
        )
        assert outcome != REPLACE


class TestIncompleteReleaseEvidenceIsNotTreatedAsAbsence:
    """A release document that cannot be READ is not a release that is absent.

    `release.forMedia` skips unreadable documents and returns the rest, which
    is right for the UI -- four of five releases beats an error page. It is
    wrong here: the skipped document may be the one that claims this
    destination, and resolving ownership from a partial set can attribute the
    wrong quality to the file about to be deleted. So the renamer asks for a
    complete answer and refuses when it cannot have one.
    """

    def test_an_incomplete_release_list_refuses_rather_than_resolving(self, scene):
        scene['state']['releases'] = None      # forMedia's "I could not read it all"
        outcome, _ = scene['plugin']._replacementOutcome(
            's.mkv', scene['dst'], scene['group']('2160p')
        )
        assert outcome == DECLINED_INCOMPLETE_EVIDENCE

    def test_incomplete_is_distinguished_from_genuinely_having_no_releases(self, scene):
        """The distinction is the whole point: one sends an operator to their
        database, the other to their library. Collapsing them into a single
        refusal would lose the only signal that says which."""
        scene['state']['releases'] = []
        outcome, _ = scene['plugin']._replacementOutcome(
            's.mkv', scene['dst'], scene['group']('2160p')
        )
        assert outcome == DECLINED_NO_OWNER

    def test_the_renamer_actually_asks_for_a_complete_answer(self, scene):
        """Anti-inertness: forMedia defaults to the partial list, so dropping
        `require_complete=True` at the call site would silently restore the
        old behaviour with every other test still green."""
        seen = {}

        def _fire(event, *args, **kwargs):
            if event == 'release.for_media':
                seen.update(kwargs)
                return scene['state']['releases']
            return None

        import couchpotato.core.plugins.renamer.main as renamer_main
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(renamer_main, 'fireEvent', _fire)
            scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())

        assert seen.get('require_complete') is True, (
            'the renamer accepted a possibly-partial release list: %r' % (seen,)
        )


class TestForMediaHonoursRequireComplete:
    """The other half of the boundary, tested on forMedia itself.

    Asserting only the renamer's side would leave the flag free to be a no-op.
    """

    def _plugin(self, docs, raw_ids):
        from couchpotato.core.plugins.release.main import Release

        plugin = Release.__new__(Release)

        class _DB:
            def get_many(self, *a, **k):
                return [{'_id': i} for i in raw_ids]

            def get(self, _index, _id):
                value = docs[_id]
                if isinstance(value, Exception):
                    raise value
                return value

        return plugin, _DB()

    def test_a_complete_read_returns_the_list_under_both_modes(self, monkeypatch):
        import couchpotato.core.plugins.release.main as release_main
        plugin, db = self._plugin({'a': {'_id': 'a'}, 'b': {'_id': 'b'}}, ['a', 'b'])
        monkeypatch.setattr(release_main, 'get_db', lambda: db)

        assert len(plugin.forMedia('m')) == 2
        assert len(plugin.forMedia('m', require_complete=True)) == 2

    def test_an_unreadable_document_makes_the_strict_answer_None(self, monkeypatch):
        import couchpotato.core.plugins.release.main as release_main
        plugin, db = self._plugin(
            {'a': {'_id': 'a'}, 'b': RuntimeError('disk went away')}, ['a', 'b'],
        )
        monkeypatch.setattr(release_main, 'get_db', lambda: db)

        # Default stays best-effort -- the UI callers depend on this.
        assert len(plugin.forMedia('m')) == 1
        # Strict refuses to answer at all.
        assert plugin.forMedia('m', require_complete=True) is None

    def test_a_deleted_document_does_NOT_count_as_incomplete(self, monkeypatch):
        """RecordDeleted means the document genuinely no longer exists, so
        excluding it leaves the set CORRECT. Counting it as incomplete would
        make ordinary deletion refuse every replacement forever."""
        import couchpotato.core.plugins.release.main as release_main
        from CodernityDB.database import RecordDeleted

        plugin, db = self._plugin(
            {'a': {'_id': 'a'}, 'b': RecordDeleted('gone')}, ['a', 'b'],
        )
        monkeypatch.setattr(release_main, 'get_db', lambda: db)

        result = plugin.forMedia('m', require_complete=True)
        assert result is not None and len(result) == 1

    def test_a_corrupt_document_counts_as_incomplete(self, monkeypatch):
        import couchpotato.core.plugins.release.main as release_main
        plugin, db = self._plugin(
            {'a': {'_id': 'a'}, 'b': ValueError('corrupt')}, ['a', 'b'],
        )
        monkeypatch.setattr(release_main, 'get_db', lambda: db)
        monkeypatch.setattr(release_main, 'fireEvent', lambda *a, **k: None)

        assert plugin.forMedia('m', require_complete=True) is None


class TestTheProductionCollisionPathReachesTheDecision:
    """Every other test in this file calls `_replacementOutcome` directly.

    That leaves the suite vulnerable to exactly the inertness it was written to
    prevent: deleting the call from `_moveRenamedFiles` would keep all of them
    green while the gate never ran in production. These drive the real
    collision path instead.
    """

    def test_a_collision_during_a_real_rename_computes_the_outcome(self, scene, caplog):
        src = os.path.join(os.path.dirname(scene['dst']), 'incoming.mkv')
        with open(src, 'wb') as handle:
            handle.write(b'y' * 9000)

        with caplog.at_level(logging.WARNING):
            scene['plugin']._moveRenamedFiles(
                {src: scene['dst']}, scene['group']('2160p'),
            )

        # B4a computed and logged a refusal here. B4b ACTS, so a reachable
        # decision now shows up as the destination holding the incoming bytes
        # -- and the replacement record naming the two rungs. Either is proof
        # the gate ran; asserting both is proof it ran and completed.
        with open(scene['dst'], 'rb') as handle:
            assert handle.read() == b'y' * 9000, (
                'the decision was REPLACE but the library file is unchanged: '
                'the gate is unreachable from the production rename path'
            )
        # AC-OPS-2: the record that must exist BEFORE the irreversible step,
        # because a crash immediately after `os.replace` leaves nothing later
        # in the path having run and the old file already gone.
        announcements = [
            r.getMessage() for r in caplog.records
            if 'About to replace a library copy' in r.getMessage()
        ]
        assert announcements, (
            'the irreversible step was taken with no prior record: a crash '
            'here leaves an unexplained deletion'
        )
        assert 'media-1' in announcements[0]
        assert scene['dst'] not in announcements[0], (
            'the forensic record leaked the library path'
        )

    def test_a_refusal_still_keeps_the_existing_file_and_suppresses_cleanup(self, scene, tmp_path):
        """The other half: when the decision is NOT replace, nothing moves.

        B4a proved this by never acting at all. B4b has to prove it while the
        acting code is right there, which is the version that matters -- a
        gate that refuses correctly is worth nothing if the refusal path can
        still reach the swap.
        """
        parent = tmp_path / 'download'
        parent.mkdir()
        src = parent / 'incoming.mkv'
        src.write_bytes(b'y' * 9000)

        group = scene['group']('720p')          # worse: declined_not_better
        group['parentdir'] = str(parent)
        group['files'] = {'movie': [str(src)]}
        scene['state']['conf']['cleanup'] = True

        scene['plugin']._moveRenamedFiles({str(src): scene['dst']}, group)

        with open(scene['dst'], 'rb') as handle:
            assert handle.read() == b'x' * 5000, 'a refused replacement still swapped'
        assert src.exists(), 'the incoming file was destroyed'
        assert parent.is_dir(), 'cleanup ran despite a skip'


class TestTheReleaseLookupIsBoundedPerGroup:
    """AC-ARCH-5: at most one release lookup per group, none per file.

    `_replacementOutcome` runs per colliding `(src, dst)` pair, so a group with
    more than one existing destination fired a `get_many` plus a `get` per
    release for each of them -- on a timer, to reach the same answer.
    """

    def test_two_collisions_in_one_group_share_a_single_lookup(self, scene):
        group = scene['group']()
        for _ in range(3):
            scene['plugin']._replacementOutcome('s.mkv', scene['dst'], group)

        assert scene['state']['for_media_calls'] == ['media-1'], (
            'the release lookup ran once per colliding file: %r'
            % scene['state']['for_media_calls']
        )

    def test_a_DIFFERENT_group_gets_its_own_lookup(self, scene):
        """The cache is per group, not per plugin. Anything on `self` would
        outlive the scan and go stale between them."""
        scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        assert scene['state']['for_media_calls'] == ['media-1', 'media-1']


class TestAnAbandonedStagingFileIsReported:
    """Killed between staging and `os.replace`, the staged copy survives under
    a hidden name the scanner ignores (`.part` is not a media extension) while
    the library still holds the old file. Unreported, automation says the
    download is missing and nobody can find the complete copy sitting there.
    """

    def _stale_part(self, directory, age_hours):
        import time as time_module
        name = '.cp-upgrade-deadbeef.part'
        path = os.path.join(directory, name)
        with open(path, 'wb') as handle:
            handle.write(b'a complete download nobody can see' * 100)
        old = time_module.time() - age_hours * 3600
        os.utime(path, (old, old))
        return name, path

    def test_an_old_staging_file_is_named_in_the_log(self, scene, caplog, tmp_path):
        from couchpotato.core.logger import reset_log_suppression
        reset_log_suppression()
        name, _ = self._stale_part(str(tmp_path), age_hours=48)

        with caplog.at_level(logging.WARNING):
            scene['plugin']._reportStaleStagingFiles(str(tmp_path))

        messages = [r.getMessage() for r in caplog.records]
        assert any(name in m for m in messages), (
            'an abandoned complete download was never reported: %r' % messages
        )
        assert not any(str(tmp_path) in m for m in messages), (
            'the report leaked the library directory'
        )

    def test_a_transfer_still_in_progress_is_NOT_reported(self, scene, caplog, tmp_path):
        """A 60 GB remux across a slow NAS mount is a long copy. Reporting a
        live transfer as wreckage is worse than reporting nothing."""
        from couchpotato.core.logger import reset_log_suppression
        reset_log_suppression()
        self._stale_part(str(tmp_path), age_hours=0)

        with caplog.at_level(logging.WARNING):
            scene['plugin']._reportStaleStagingFiles(str(tmp_path))

        assert not [
            r for r in caplog.records if 'abandoned' in r.getMessage()
        ], 'a staging file being written right now was reported as abandoned'

    def test_ordinary_library_files_are_not_reported(self, scene, caplog, tmp_path):
        (tmp_path / 'A Real Movie.mkv').write_bytes(b'x' * 10)
        with caplog.at_level(logging.WARNING):
            scene['plugin']._reportStaleStagingFiles(str(tmp_path))
        assert not [r for r in caplog.records if 'abandoned' in r.getMessage()]

    def test_an_unreadable_directory_does_not_break_the_scan(self, scene):
        """A diagnostic that can break a scan is worse than no diagnostic."""
        scene['plugin']._reportStaleStagingFiles('/definitely/not/here')
