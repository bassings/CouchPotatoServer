"""Tests for the default-profile quality-order migration (BUG-016).

`Profile.fill()` only runs on a fresh install, so correcting the seeded
profiles does nothing for existing databases — a user whose 'Best' profile
was created with `['720p', '1080p', ...]` keeps grabbing 720p forever. This
migration repairs those rows on startup.

The safety rule is the whole point: only a profile whose label AND stored
quality order match a known-bad seed exactly is rewritten. A profile the user
renamed, reordered, or otherwise edited is left strictly alone — somebody who
deliberately prefers 720p for disk reasons must not have that silently undone.

See specs/BUG-016-default-profile-quality-order.md.
"""

from unittest.mock import MagicMock

from couchpotato.core.migration.fix_profile_quality_order import (
    fix_profile_quality_order,
)


def _legacy_best():
    """A 'Best' profile exactly as the old fill() would have seeded it."""
    return {
        '_t': 'profile',
        '_id': 'profile-best',
        '_rev': '001',
        'label': 'Best',
        'order': 0,
        'qualities': ['720p', '1080p', 'brrip', 'dvdrip'],
        'finish': [True, True, True, True],
        'wait_for': [0, 0, 0, 0],
        'stop_after': [0, 0, 0, 0],
        '3d': [False, False, False, False],
        'minimum_score': 1,
    }


def _db_with(*docs):
    db = MagicMock()
    db.all.return_value = [{'doc': doc} for doc in docs]
    return db


class TestRepairsLegacyDefaults:

    def test_reorders_legacy_best_profile(self):
        """AC4 (bug repro): the stored 'Best' profile is rewritten
        best-first. Fails against a no-op migration."""
        doc = _legacy_best()
        db = _db_with(doc)

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (1, 1)
        db.update.assert_called_once()
        updated = db.update.call_args[0][0]
        assert updated['qualities'] == ['1080p', '720p', 'brrip', 'dvdrip']

    def test_permutes_positional_lists_with_the_qualities(self):
        """AC4: finish/wait_for/stop_after/3d are positional siblings. If
        they are not permuted by the SAME permutation, a flag silently
        detaches from its quality.

        The seeds are uniform (all finish=True, all waits 0), which would
        hide a bug here — so this fixture uses distinct per-rung values
        while keeping the *qualities* an exact legacy match.
        """
        doc = _legacy_best()
        doc['finish'] = [True, False, True, False]
        doc['wait_for'] = [1, 2, 3, 4]
        doc['stop_after'] = [10, 20, 30, 40]
        db = _db_with(doc)

        fixed, _ = fix_profile_quality_order(db)

        assert fixed == 1
        updated = db.update.call_args[0][0]
        # 'Best' moves index 1 (1080p) to the front: permutation [1, 0, 2, 3]
        assert updated['qualities'] == ['1080p', '720p', 'brrip', 'dvdrip']
        assert updated['finish'] == [False, True, True, False]
        assert updated['wait_for'] == [2, 1, 3, 4]
        assert updated['stop_after'] == [20, 10, 30, 40]

    def test_reorders_legacy_uhd_4k_profile(self):
        """AC4: 'UHD 4K' led with 720p and so could never deliver 4K."""
        doc = _legacy_best()
        doc['label'] = 'UHD 4K'
        doc['qualities'] = ['720p', '1080p', '2160p']
        doc['finish'] = [True, True, True]
        doc['wait_for'] = [0, 0, 0]
        doc['stop_after'] = [0, 0, 0]
        doc['3d'] = [False, False, False]
        db = _db_with(doc)

        fixed, _ = fix_profile_quality_order(db)

        assert fixed == 1
        assert db.update.call_args[0][0]['qualities'] == ['2160p', '1080p', '720p']

    def test_reorders_prefer_3d_hd_keeping_3d_flags_attached(self):
        """AC4: 'Prefer 3D HD' has duplicate identifiers, so the 3D flags are
        the only thing distinguishing rungs. Its 3D head is already correct;
        only the non-3D tail is inverted."""
        doc = _legacy_best()
        doc['label'] = 'Prefer 3D HD'
        doc['qualities'] = ['1080p', '720p', '720p', '1080p']
        doc['3d'] = [True, True, False, False]
        db = _db_with(doc)

        fixed, _ = fix_profile_quality_order(db)

        assert fixed == 1
        updated = db.update.call_args[0][0]
        pairs = list(zip(updated['qualities'], [bool(x) for x in updated['3d']]))
        assert pairs == [
            ('1080p', True),
            ('720p', True),
            ('1080p', False),
            ('720p', False),
        ]

    def test_repairs_multiple_profiles_in_one_pass(self):
        best = _legacy_best()
        hd = _legacy_best()
        hd['_id'] = 'profile-hd'
        hd['label'] = 'HD'
        hd['qualities'] = ['720p', '1080p']
        hd['finish'] = [True, True]
        hd['wait_for'] = [0, 0]
        hd['stop_after'] = [0, 0]
        hd['3d'] = [False, False]
        db = _db_with(best, hd)

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (2, 2)
        assert db.update.call_count == 2


class TestLeavesUserProfilesAlone:
    """AC5 — the safety rule."""

    def test_ignores_customised_quality_list(self):
        """A 'Best' the user edited (here: 2160p added) no longer matches the
        known-bad seed, so it must not be rewritten — we cannot know what
        order they intended."""
        doc = _legacy_best()
        doc['qualities'] = ['720p', '1080p', '2160p', 'brrip', 'dvdrip']
        doc['finish'] = [True] * 5
        doc['wait_for'] = [0] * 5
        doc['stop_after'] = [0] * 5
        doc['3d'] = [False] * 5
        db = _db_with(doc)

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (0, 1)
        db.update.assert_not_called()

    def test_ignores_renamed_profile(self):
        """Matching is on label as well as qualities: a renamed profile is
        the user's, not ours."""
        doc = _legacy_best()
        doc['label'] = 'My Best'
        db = _db_with(doc)

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (0, 1)
        db.update.assert_not_called()

    def test_ignores_profile_the_user_already_reordered(self):
        """Someone who deliberately put 720p last must keep that."""
        doc = _legacy_best()
        doc['qualities'] = ['brrip', 'dvdrip', '1080p', '720p']
        db = _db_with(doc)

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (0, 1)
        db.update.assert_not_called()

    def test_is_idempotent(self):
        """AC5: an already-corrected profile is not a known-bad seed, so a
        second startup is a no-op. Without this the migration would fight a
        user who re-reorders after the first run."""
        doc = _legacy_best()
        doc['qualities'] = ['1080p', '720p', 'brrip', 'dvdrip']
        db = _db_with(doc)

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (0, 1)
        db.update.assert_not_called()

    def test_ignores_3d_variant_that_does_not_match_flags(self):
        """'Prefer 3D HD' with different 3D flags is a different profile;
        the identifiers alone are ambiguous because they repeat."""
        doc = _legacy_best()
        doc['label'] = 'Prefer 3D HD'
        doc['qualities'] = ['1080p', '720p', '720p', '1080p']
        doc['3d'] = [True, False, True, False]
        db = _db_with(doc)

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (0, 1)
        db.update.assert_not_called()

    def test_ignores_3d_hd_which_was_already_correct(self):
        """Regression guard: '3D HD' was never mis-seeded and must not be in
        the known-bad table at all."""
        doc = _legacy_best()
        doc['label'] = '3D HD'
        doc['qualities'] = ['1080p', '720p']
        doc['finish'] = [True, True]
        doc['wait_for'] = [0, 0]
        doc['stop_after'] = [0, 0]
        doc['3d'] = [True, True]
        db = _db_with(doc)

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (0, 1)
        db.update.assert_not_called()


class TestFailureHandling:
    """AC6 — this runs during startup; it must never take the app down."""

    def test_returns_zero_when_the_listing_fails(self):
        db = MagicMock()
        db.all.side_effect = Exception('database is locked')

        assert fix_profile_quality_order(db) == (0, 0)

    def test_one_bad_row_does_not_abort_the_batch(self):
        """A write conflict on one profile must not strand the others."""
        bad = _legacy_best()
        good = _legacy_best()
        good['_id'] = 'profile-hd'
        good['label'] = 'HD'
        good['qualities'] = ['720p', '1080p']
        good['finish'] = [True, True]
        good['wait_for'] = [0, 0]
        good['stop_after'] = [0, 0]
        good['3d'] = [False, False]
        db = _db_with(bad, good)
        db.update.side_effect = [Exception('conflict'), None]

        fixed, checked = fix_profile_quality_order(db)

        assert checked == 2
        assert fixed == 1, 'the second profile should still have been repaired'

    def test_tolerates_profile_missing_positional_lists(self):
        """Very old rows may lack a '3d' list entirely; that must be
        treated as all-non-3D for matching rather than raising."""
        doc = _legacy_best()
        del doc['3d']
        db = _db_with(doc)

        fixed, checked = fix_profile_quality_order(db)

        assert checked == 1
        assert fixed == 1
        assert db.update.call_args[0][0]['qualities'] == [
            '1080p', '720p', 'brrip', 'dvdrip',
        ]

    def test_ignores_non_profile_documents(self):
        db = _db_with({'_t': 'movie', '_id': 'x', 'label': 'Best'})

        fixed, checked = fix_profile_quality_order(db)

        assert (fixed, checked) == (0, 0)
        db.update.assert_not_called()
