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

    state = {'releases': [release], 'for_media_calls': [], 'conf': {'upgrade_replace': True}}

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
        }

    return {'plugin': plugin, 'dst': str(dst), 'state': state, 'group': _group}


class TestTheDecisionIsActuallyReached:
    def test_a_better_copy_reaches_REPLACE_with_real_releases(self, scene):
        """The reachability assertion. If this ever returns a refusal for a
        clearly-better copy, the gate has gone inert again."""
        outcome = scene['plugin']._replacementOutcome(
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
        worse = scene['group']('720p')
        assert scene['plugin']._replacementOutcome('s.mkv', scene['dst'], worse) == DECLINED_NOT_BETTER

        scene['state']['releases'] = []          # simulate the inert attempt
        assert scene['plugin']._replacementOutcome('s.mkv', scene['dst'], worse) == DECLINED_NO_OWNER


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
        outcome = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        assert outcome == DECLINED_SETTING_OFF

    def test_the_dead_key_being_true_does_NOT_enable_anything(self, scene):
        """The whole point of D1: `remove_lower_quality_copies` is already
        persisted True on every existing install. If it could still enable
        replacement, upgrading would start deleting library files."""
        scene['state']['conf'] = {'remove_lower_quality_copies': True}
        outcome = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        assert outcome == DECLINED_SETTING_OFF


class TestTheDeadSettingIsAnnouncedOnce:
    def test_an_operator_who_set_it_is_told_it_does_nothing(self, scene, caplog):
        scene['state']['conf'] = {'remove_lower_quality_copies': True}
        with caplog.at_level('WARNING'):
            scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        assert any('no longer read' in r.getMessage() for r in caplog.records)

    def test_it_is_said_once_per_process_not_once_per_scan(self, scene, caplog):
        """The renamer runs on a timer. A warning repeated every few minutes
        is one an operator learns to filter out."""
        scene['state']['conf'] = {'remove_lower_quality_copies': True}
        with caplog.at_level('WARNING'):
            for _ in range(4):
                scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        said = [r for r in caplog.records if 'no longer read' in r.getMessage()]
        assert len(said) == 1, 'warned %d times' % len(said)

    def test_enabling_it_LATER_in_the_same_process_is_still_announced(self, scene, caplog):
        """The latch must fire when the warning is due, not on the first call.

        `self.conf` reads live, so "Delete Others" can be switched on in the
        settings UI without a restart. Latching on the first call meant a scan
        that ran while the setting was off silenced the notice for the life of
        the process -- the silence D1 exists to prevent, reached by a
        different door.
        """
        scene['state']['conf'] = {'remove_lower_quality_copies': False}
        scene['plugin']._warnAboutTheDeadSetting()

        scene['state']['conf'] = {'remove_lower_quality_copies': True}
        with caplog.at_level(logging.WARNING):
            scene['plugin']._warnAboutTheDeadSetting()

        assert any('no longer read' in r.getMessage() for r in caplog.records), (
            'the operator enabled the dead setting and was never told it does '
            'nothing, because an earlier scan latched the notice off'
        )

    def test_it_is_STILL_only_said_once_after_being_enabled(self, scene, caplog):
        scene['state']['conf'] = {'remove_lower_quality_copies': False}
        scene['plugin']._warnAboutTheDeadSetting()
        scene['state']['conf'] = {'remove_lower_quality_copies': True}
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                scene['plugin']._warnAboutTheDeadSetting()
        said = [r for r in caplog.records if 'no longer read' in r.getMessage()]
        assert len(said) == 1, 'warned %d times' % len(said)

    def test_nothing_is_said_when_the_operator_never_set_it(self, scene, caplog):
        scene['state']['conf'] = {'upgrade_replace': False}
        with caplog.at_level('WARNING'):
            scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        assert not any('no longer read' in r.getMessage() for r in caplog.records)


class TestTheDecisionNeverBreaksAScan:
    def test_an_exploding_release_lookup_is_swallowed_as_a_refusal(self, scene, monkeypatch):
        """AC-QA-12. This runs inside the ordinary rename path, so an escaping
        exception would abort a scan that was otherwise fine."""
        def _boom(event, *a, **k):
            if event == 'release.for_media':
                raise RuntimeError('database went away')
            return None

        monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent', _boom)
        outcome = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())
        assert outcome == DECLINED_ERROR

    def test_a_group_with_no_media_does_not_raise(self, scene):
        outcome = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], {'files': {}})
        assert outcome != REPLACE

    def test_a_group_with_media_but_no_id_declines_as_no_owner(self, scene):
        """AC-QA-12's no-`_id` branch, which nothing reached before.

        `test_a_group_with_no_media_does_not_raise` passes `{'files': {}}`,
        which has ZERO movie files and is refused at
        `declined_multi_file_group` long before the media lookup -- so it
        asserted only that nothing raised, and the branch the AC names was
        never executed. This group has exactly one movie file and a media dict
        with no id, which is the shape the AC is about.
        """
        group = scene['group']()
        group['media'] = {}
        outcome = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], group)
        assert outcome == DECLINED_NO_OWNER
        assert scene['state']['for_media_calls'] == [], (
            'a release lookup was fired for a group with no media id'
        )

    def test_an_unstattable_destination_does_not_raise(self, scene):
        outcome = scene['plugin']._replacementOutcome(
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

        outcome = scene['plugin']._replacementOutcome(
            's.mkv', str(empty_dst), scene['group']('2160p')
        )
        # A real 0-byte file DOES resolve -- that is the control proving the
        # fixture is capable of resolving at all.
        assert outcome == REPLACE

        # But an unreadable one must not borrow that zero.
        outcome = scene['plugin']._replacementOutcome(
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
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET
        scene['state']['releases'] = INCOMPLETE_RELEASE_SET
        outcome = scene['plugin']._replacementOutcome(
            's.mkv', scene['dst'], scene['group']('2160p')
        )
        assert outcome == DECLINED_INCOMPLETE_EVIDENCE

    def test_incomplete_is_distinguished_from_genuinely_having_no_releases(self, scene):
        """The distinction is the whole point: one sends an operator to their
        database, the other to their library. Collapsing them into a single
        refusal would lose the only signal that says which."""
        scene['state']['releases'] = []
        assert scene['plugin']._replacementOutcome(
            's.mkv', scene['dst'], scene['group']('2160p')
        ) == DECLINED_NO_OWNER

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

    def test_an_unreadable_document_makes_the_strict_answer_the_sentinel(self, monkeypatch):
        import couchpotato.core.plugins.release.main as release_main
        plugin, db = self._plugin(
            {'a': {'_id': 'a'}, 'b': RuntimeError('disk went away')}, ['a', 'b'],
        )
        monkeypatch.setattr(release_main, 'get_db', lambda: db)

        # Default stays best-effort -- the UI callers depend on this.
        assert len(plugin.forMedia('m')) == 1
        # Strict refuses to answer at all.
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET
        assert plugin.forMedia('m', require_complete=True) is INCOMPLETE_RELEASE_SET

    def test_a_KeyError_from_the_REAL_backend_is_a_deletion_not_a_failure(self, monkeypatch):
        """`RecordDeleted` is CodernityDB's exception. The production backend
        is SQLiteAdapter, which raises a plain KeyError for a row that is not
        there (sqlite_adapter.py:411).

        Catching only `RecordDeleted` meant an ordinary concurrent deletion
        fell through to the generic handler, was counted as UNREADABLE, and
        made `require_complete` refuse every replacement for that media --
        turning the safety check into a permanent outage of the feature it was
        protecting. The existing test passed because it raised the
        CodernityDB exception, which this backend never produces.
        """
        import couchpotato.core.plugins.release.main as release_main
        plugin, db = self._plugin(
            {'a': {'_id': 'a'}, 'b': KeyError('Document not found: b')}, ['a', 'b'],
        )
        monkeypatch.setattr(release_main, 'get_db', lambda: db)

        result = plugin.forMedia('m', require_complete=True)
        assert result is not None and len(result) == 1, (
            'a deleted row made the whole set look unreadable'
        )
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET
        assert result is not INCOMPLETE_RELEASE_SET

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

        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET
        assert plugin.forMedia('m', require_complete=True) is INCOMPLETE_RELEASE_SET


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

        collision = [
            r.getMessage() for r in caplog.records
            if 'Destination already exists' in r.getMessage()
        ]
        assert collision, 'the collision path was never taken'
        assert REPLACE in collision[0], (
            'the rename path logged a collision without computing the upgrade '
            'decision -- the gate is unreachable in production: %s' % collision[0]
        )

    def test_the_existing_file_is_still_kept_and_cleanup_suppressed(self, scene, tmp_path):
        """B4a computes but does not act. Proving that here means a later step
        that starts acting has to change this test deliberately."""
        parent = tmp_path / 'download'
        parent.mkdir()
        src = parent / 'incoming.mkv'
        src.write_bytes(b'y' * 9000)

        group = scene['group']('2160p')
        group['parentdir'] = str(parent)
        scene['state']['conf']['cleanup'] = True

        scene['plugin']._moveRenamedFiles({str(src): scene['dst']}, group)

        with open(scene['dst'], 'rb') as handle:
            assert handle.read() == b'x' * 5000, 'the existing file was modified'
        assert src.exists(), 'the incoming file was destroyed'
        assert parent.is_dir(), 'cleanup ran despite a skip'


class TestARepeatingFailureDoesNotEraseTheLog:
    """The collided download is deliberately LEFT IN PLACE on a skip.

    So a group whose release documents are malformed raises here, and raises
    again on every scheduled scan, for as long as the file sits there. An
    unbounded full traceback per scan evicts the rotating log, which is the
    only diagnostic a self-hosted install has: the failure would quietly erase
    the evidence of itself, along with everything else that happened.

    The first occurrence must stay complete, or the bound has cost the
    diagnosis it was meant to protect.
    """

    @pytest.fixture(autouse=True)
    def _fresh_windows(self):
        from couchpotato.core.logger import reset_log_suppression
        reset_log_suppression()
        yield
        reset_log_suppression()

    def _exploding(self, scene, monkeypatch):
        def _boom(event, *a, **k):
            if event == 'release.for_media':
                raise RuntimeError('malformed release document')
            return None
        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.main.fireEvent', _boom
        )

    def test_the_first_failure_is_reported_in_full(self, scene, monkeypatch, caplog):
        self._exploding(scene, monkeypatch)
        with caplog.at_level(logging.ERROR):
            scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())

        messages = [r.getMessage() for r in caplog.records]
        assert any('malformed release document' in m for m in messages), (
            'the traceback was suppressed on its FIRST occurrence, so the '
            'bound cost the diagnosis: %r' % messages
        )

    def test_twenty_scans_do_not_write_twenty_tracebacks(self, scene, monkeypatch, caplog):
        self._exploding(scene, monkeypatch)
        with caplog.at_level(logging.ERROR):
            for _ in range(20):
                scene['plugin']._replacementOutcome(
                    's.mkv', scene['dst'], scene['group']()
                )

        tracebacks = [
            r for r in caplog.records
            if 'malformed release document' in r.getMessage()
        ]
        assert len(tracebacks) < 20, (
            'every scan wrote a full traceback (%d of 20); the rotating log '
            'is being evicted by the failure it is meant to record'
            % len(tracebacks)
        )
        assert tracebacks, 'nothing was recorded at all'

    def test_the_suppression_key_carries_no_filesystem_path(self, scene, monkeypatch):
        """PrivacyFilter exists to keep library paths out of logs, and a
        suppression key is retained state, not a transient message. Keying on
        the destination would put a private path somewhere the filter does not
        reach."""
        keys = []
        import couchpotato.core.plugins.renamer.main as renamer_main
        monkeypatch.setattr(
            renamer_main, 'log_suppressed',
            lambda method, key, message, *a, **k: keys.append(key),
        )
        self._exploding(scene, monkeypatch)
        scene['plugin']._replacementOutcome('s.mkv', scene['dst'], scene['group']())

        assert keys, 'the failure did not go through log_suppressed at all'
        assert scene['dst'] not in keys[0]
        assert 'The Thing' not in keys[0]
        assert 'media-1' in keys[0], (
            'the key does not distinguish media, so one broken group would '
            'silence the diagnosis for every other: %r' % keys[0]
        )

    def test_a_different_media_is_not_silenced_by_the_first(self, scene, monkeypatch, caplog):
        self._exploding(scene, monkeypatch)
        with caplog.at_level(logging.ERROR):
            for _ in range(6):
                scene['plugin']._replacementOutcome(
                    's.mkv', scene['dst'], scene['group']()
                )
            other = scene['group']()
            other['media'] = {'_id': 'media-2'}
            caplog.clear()
            scene['plugin']._replacementOutcome('s.mkv', scene['dst'], other)

        assert any(
            'malformed release document' in r.getMessage() for r in caplog.records
        ), 'a second, unrelated broken group was silenced by the first'


class TestTheIncompleteSignalSurvivesTheRealEventBus:
    """The signal is a SENTINEL, not None, and this is why.

    `fireEvent(single=True)` collects only non-None handler results and
    returns `[]` when there are none (event.py:222). So a `forMedia` that
    answered None reached the renamer as `[]`, `[] is None` was False, and the
    refusal never fired: replacement proceeded on evidence known to be
    incomplete, in production, while every unit test passed because they
    injected a stand-in for `fireEvent` instead of using it.

    That is the THIRD dead guard this boundary has produced in this feature.
    The fix is structural rather than another careful check: a sentinel object
    is non-None, so the transport cannot filter it away.

    These tests deliberately go through the real bus. Injecting a stand-in
    here would reproduce the exact blind spot they exist to close.
    """

    def test_None_really_is_swallowed_by_the_bus(self, monkeypatch):
        """The precondition, asserted rather than assumed. If this ever stops
        being true the sentinel is unnecessary -- and the comment explaining
        it becomes a lie."""
        from couchpotato.core import event as event_module
        from couchpotato.core.event import addEvent, fireEvent

        monkeypatch.setattr(event_module, 'events', dict(event_module.events))
        addEvent('probe.answers_none', lambda *a, **k: None)

        assert fireEvent('probe.answers_none', single=True) == []

    def test_the_sentinel_reaches_the_caller_unchanged(self, monkeypatch):
        from couchpotato.core import event as event_module
        from couchpotato.core.event import addEvent, fireEvent
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET

        monkeypatch.setattr(event_module, 'events', dict(event_module.events))
        addEvent('probe.incomplete', lambda *a, **k: INCOMPLETE_RELEASE_SET)

        assert fireEvent('probe.incomplete', single=True) is INCOMPLETE_RELEASE_SET

    def test_the_sentinel_is_falsy_so_a_careless_caller_still_fails_closed(self):
        """Belt and braces. Anyone who forgets the identity check and writes
        `releases or []` gets an empty list -- a refusal -- rather than
        iterating a sentinel or proceeding on partial evidence."""
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET

        assert not INCOMPLETE_RELEASE_SET
        assert (INCOMPLETE_RELEASE_SET or []) == []

    def test_the_renamer_refuses_when_the_bus_delivers_the_sentinel(self, scene):
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET
        scene['state']['releases'] = INCOMPLETE_RELEASE_SET
        outcome = scene['plugin']._replacementOutcome(
            's.mkv', scene['dst'], scene['group']('2160p')
        )
        assert outcome == DECLINED_INCOMPLETE_EVIDENCE


class TestAFailingQueryIsARefusalNotAnEscapingException:
    """`get_many` returns a GENERATOR: `sqlite_adapter.query` yields, so
    `_query_index` does not execute until the first `next()`. That happens at
    the `for` statement, which used to sit outside the guard -- so an
    `OperationalError` from lock contention escaped `forMedia` entirely and a
    caller that had explicitly asked for a complete answer got an exception
    instead of the refusal it asked for.

    Nothing unsafe followed (the renamer's broad except turned it into
    `declined_error`), but a guard that cannot see the failure it exists to
    report is not doing its job.
    """

    def _plugin(self, raiser):
        from couchpotato.core.plugins.release.main import Release

        plugin = Release.__new__(Release)

        class _DB:
            def get_many(self, *a, **k):
                def _gen():
                    raise raiser
                    yield  # pragma: no cover -- makes this a generator
                return _gen()

            def get(self, *a, **k):  # pragma: no cover
                raise AssertionError('should never be reached')

        return plugin, _DB()

    def test_a_query_that_explodes_refuses_under_require_complete(self, monkeypatch):
        import couchpotato.core.plugins.release.main as release_main
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET

        plugin, db = self._plugin(RuntimeError('database is locked'))
        monkeypatch.setattr(release_main, 'get_db', lambda: db)

        assert plugin.forMedia('m', require_complete=True) is INCOMPLETE_RELEASE_SET

    def test_the_lazy_query_really_does_raise_at_iteration(self, monkeypatch):
        """Precondition, asserted rather than assumed: if `get_many` ever
        becomes eager, the guard's placement stops mattering and the comment
        explaining it becomes wrong."""
        plugin, db = self._plugin(RuntimeError('database is locked'))
        gen = db.get_many('release', 'm')          # no raise yet
        try:
            next(gen)
        except RuntimeError:
            pass
        else:  # pragma: no cover
            raise AssertionError('the fixture is not lazy, so it cannot model the bug')

    def test_the_default_caller_still_gets_a_list_not_an_exception(self, monkeypatch):
        """Fifteen other callers want best-effort. An escaping exception would
        be a behaviour change for all of them."""
        import couchpotato.core.plugins.release.main as release_main

        plugin, db = self._plugin(RuntimeError('database is locked'))
        monkeypatch.setattr(release_main, 'get_db', lambda: db)

        assert plugin.forMedia('m') == []
