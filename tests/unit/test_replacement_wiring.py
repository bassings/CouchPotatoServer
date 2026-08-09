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
import os

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import copy_id_for_sizes
from couchpotato.core.plugins.renamer.owner import DECLINED_NO_OWNER
from couchpotato.core.plugins.renamer.replacement import (
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
    Renamer._warned_dead_setting = False

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
        from couchpotato.core.event import addEvent, fireEvent  # noqa: F401
        from couchpotato.core.plugins.quality.main import QualityPlugin

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
        assert outcome == 'declined_error'

    def test_a_group_with_no_media_does_not_raise(self, scene):
        outcome = scene['plugin']._replacementOutcome('s.mkv', scene['dst'], {'files': {}})
        assert outcome != REPLACE

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
