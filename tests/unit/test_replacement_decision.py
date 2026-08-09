"""May the incoming copy replace the library file? (FEAT-009B B3a)

This decision authorises deleting an irreplaceable file. Two previous attempts
at it were withdrawn after destroying a 2160p remux, so the tests here are
written the way the spec demands: every refusal is asserted as a NAMED outcome
rather than inferred from a falsy value, and every "it refuses" case is paired
with a control proving the decision is not simply inert.

Inertness is not a lesser failure here. Withdrawn attempt #2 was simultaneously
dangerous and inert, and the inertness is what hid the danger — the gate never
fired in testing, so nobody saw what it would do when it did.

AC-SEC-1, AC-SEC-2, AC-QA-11, AC-QA-13, D1, D2, D7.
"""
import pytest

from couchpotato.core.plugins.renamer.owner import (
    DECLINED_AMBIGUOUS_OWNER,
    DECLINED_NO_OWNER,
    DECLINED_UNVERIFIED_COPY,
    copy_id_for_sizes,
)
from couchpotato.core.plugins.renamer.replacement import (
    DECLINED_MULTI_FILE_GROUP,
    DECLINED_NOT_BETTER,
    DECLINED_SETTING_OFF,
    DECLINED_UNKNOWN_QUALITY,
    REPLACE,
    decide_replacement,
)

DEST = '/library/Movies/The Thing (1982)/The Thing.mkv'
SIZE = 40_000_000

BETTER = {'identifier': '2160p', 'is_3d': False}
WORSE = {'identifier': '720p', 'is_3d': False}


def _existing(quality='720p', is_3d=False, size=SIZE, paths=(DEST,)):
    return {
        '_id': 'r-existing',
        'files': {'movie': list(paths)},
        'copy_id': copy_id_for_sizes([size]),
        'quality': quality,
        'is_3d': is_3d,
    }


def _rank_is_better(incoming, existing):
    """Stand-in for QualityPlugin.isBetterQuality: 2160p beats 720p."""
    order = ['2160p', 'bd50', '1080p', '720p']
    try:
        return order.index(incoming['identifier']) < order.index(existing['identifier'])
    except (KeyError, ValueError, TypeError):
        return False


def _decide(**over):
    kwargs = dict(
        destination=DEST,
        incoming_quality=BETTER,
        releases=[_existing()],
        size_on_disk=SIZE,
        video_file_count=1,
        setting_enabled=True,
        is_better=_rank_is_better,
    )
    kwargs.update(over)
    return decide_replacement(**kwargs)


class TestTheHappyPathExistsAtAll:
    """The control for every refusal test below. Without it, a decision
    function that returned a refusal unconditionally would pass the entire
    rest of this file — which is exactly the shape attempt #2 shipped."""

    def test_a_strictly_better_copy_replaces(self):
        outcome, existing = _decide()
        assert outcome == REPLACE
        assert existing['_id'] == 'r-existing'

    def test_the_release_to_be_deleted_is_returned_only_on_replace(self):
        """A caller must not be able to reach for the victim on a refusal."""
        for over in ({'setting_enabled': False},
                     {'video_file_count': 2},
                     {'incoming_quality': WORSE}):
            outcome, existing = _decide(**over)
            assert outcome != REPLACE
            assert existing is None, over


class TestTheSettingIsTheFirstGate:
    def test_off_refuses_even_when_everything_else_says_replace(self):
        """AC-SEC-1/AC-SEC-2 and D1. `upgrade_replace` is a NEW key defaulting
        off; the long-declared `remove_lower_quality_copies` is already
        persisted True on every existing install and is no longer read."""
        assert _decide(setting_enabled=False)[0] == DECLINED_SETTING_OFF

    def test_it_is_checked_before_anything_else(self):
        """With the setting off, a group that is ALSO multi-file and has an
        unknown quality still reports the setting — so an operator who has not
        opted in is told that, not something incidental."""
        outcome, _ = _decide(
            setting_enabled=False, video_file_count=3, incoming_quality=None
        )
        assert outcome == DECLINED_SETTING_OFF


class TestMultiFileGroupsAreRefused:
    """D7. If cd1's swap commits and cd2's fails, cd1's bytes are gone, and
    AC-SIMP-11 forbids a set-aside — so the criteria were mutually
    unsatisfiable. Resolved by subtraction: single-file groups only."""

    @pytest.mark.parametrize('count', [2, 3, 7])
    def test_more_than_one_video_file_refuses(self, count):
        assert _decide(video_file_count=count)[0] == DECLINED_MULTI_FILE_GROUP

    def test_zero_video_files_also_refuses(self):
        """Not `> 1`. A group with no video file has nothing to reason about,
        and calling it replaceable would be a decision made on no evidence."""
        assert _decide(video_file_count=0)[0] == DECLINED_MULTI_FILE_GROUP


class TestTheOwnersRefusalIsPassedThroughVerbatim:
    """Flattening these into one outcome would tell an operator that something
    went wrong without saying what, on the one path that deletes files."""

    def test_no_release_claims_the_destination(self):
        assert _decide(releases=[])[0] == DECLINED_NO_OWNER

    def test_the_recorded_size_disagrees_with_the_bytes_on_disk(self):
        assert _decide(size_on_disk=SIZE + 1)[0] == DECLINED_UNVERIFIED_COPY

    def test_two_claimants_and_no_way_to_tell_them_apart(self):
        a = _existing()
        b = dict(_existing(), _id='r-other')
        assert _decide(releases=[a, b], size_on_disk=SIZE)[0] == DECLINED_AMBIGUOUS_OWNER


class TestQualityMustBeKnownOnBothSides:
    def test_an_existing_release_with_no_recorded_quality_refuses(self):
        """D2: the existing quality comes from the release document. A release
        with none is not a licence to guess from the file — the default
        template has no quality token, so guessing rates a remux as brrip."""
        no_quality = dict(_existing(), quality=None)
        assert _decide(releases=[no_quality])[0] == DECLINED_UNKNOWN_QUALITY

    @pytest.mark.parametrize('incoming', [None, {}, {'is_3d': False}, 'not-a-dict'])
    def test_an_unknown_incoming_quality_refuses(self, incoming):
        """AC-QA-13: `quality.guess` returns None at quality/main.py:362 and
        :373, so this is reachable, not defensive."""
        assert _decide(incoming_quality=incoming)[0] == DECLINED_UNKNOWN_QUALITY


class TestOnlyAStrictlyBetterCopyReplaces:
    def test_a_worse_copy_refuses(self):
        assert _decide(incoming_quality=WORSE)[0] == DECLINED_NOT_BETTER

    def test_an_equal_copy_refuses(self):
        equal = {'identifier': '720p', 'is_3d': False}
        assert _decide(incoming_quality=equal)[0] == DECLINED_NOT_BETTER

    def test_the_720p_versus_2160p_case_that_attempt_1_got_wrong(self):
        """Measured failure of the first withdrawn attempt: a 720p download
        overwrote a 2160p remux."""
        existing_remux = _existing(quality='2160p')
        outcome, _ = _decide(incoming_quality=WORSE, releases=[existing_remux])
        assert outcome == DECLINED_NOT_BETTER

    def test_the_comparison_is_delegated_not_reimplemented(self):
        """The verdict must come from the injected comparator, so this cannot
        drift from `QualityPlugin.isBetterQuality` — the single source that
        knows 2160p beats bd50 and that a 3D mismatch is not comparable."""
        calls = []

        def _spy(incoming, existing):
            calls.append((incoming, existing))
            return False

        outcome, _ = _decide(is_better=_spy)
        assert outcome == DECLINED_NOT_BETTER
        assert calls == [(BETTER, {'identifier': '720p', 'is_3d': False})]
