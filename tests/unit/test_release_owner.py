"""Which release owns the file at a destination path (FEAT-009B B2).

The resolver this covers decides WHOSE quality is compared against an incoming
copy, on the one code path in the project that deletes files from the user's
library. Getting it wrong does not produce a wrong answer, it produces a
deleted 2160p remux — so every "no" here is asserted as a named outcome rather
than inferred from a falsy return.

AC-SEC-9, AC-QA-9, AC-QA-10, AC-DATA-6.
"""
import os

import pytest

from couchpotato.core.plugins.release.main import copyIdentity
from couchpotato.core.plugins.renamer.owner import (
    DECLINED_AMBIGUOUS_OWNER,
    DECLINED_NO_OWNER,
    DECLINED_UNVERIFIED_COPY,
    OWNER_RESOLVED,
    copy_id_for_sizes,
    resolve_owning_release,
)

DEST = '/library/Movies/The Thing (1982)/The Thing.mkv'


def _release(_id, paths, size=None):
    """A release document shaped the way `release/main.py` writes one."""
    doc = {'_id': _id, '_t': 'release', 'files': {'movie': list(paths)}}
    if size is not None:
        doc['copy_id'] = copy_id_for_sizes([size])
    return doc


class TestTheCopyIdFormatCannotDriftFromTheRealOne:
    """The resolver rebuilds a `copy_id` from a known size instead of stat'ing
    the disk, so its format has to match `copyIdentity` exactly.

    This is not hypothetical tidiness. The first version of `copy_id_for_sizes`
    joined with `|` while `copyIdentity` joins with `,`, so it would have
    matched NO release ever written — `_copy_matches` false everywhere, every
    replacement refused. The gate would have been completely inert while
    looking perfectly safe, which is exactly how withdrawn attempt #2 hid.
    """

    def test_it_matches_copyIdentity_on_a_real_file(self, tmp_path):
        movie = tmp_path / 'movie.mkv'
        movie.write_bytes(b'x' * 4321)
        real = copyIdentity({'movie': [str(movie)]})
        assert real is not None, 'copyIdentity could not stat a file it just wrote'
        assert copy_id_for_sizes([os.path.getsize(movie)]) == real

    def test_it_matches_for_a_multi_file_copy_in_any_order(self, tmp_path):
        a = tmp_path / 'cd1.mkv'
        a.write_bytes(b'x' * 900)
        b = tmp_path / 'cd2.mkv'
        b.write_bytes(b'y' * 100)
        # copyIdentity sorts, because the scanner's bucket ordering is
        # hash-randomised between processes.
        assert copyIdentity({'movie': [str(b), str(a)]}) == copy_id_for_sizes([900, 100])


class TestNoReleaseClaimsThePath:
    def test_a_manually_placed_file_is_refused(self):
        """AC-QA-10: unknown never means replaceable."""
        other = _release('r1', ['/library/Movies/Alien (1979)/Alien.mkv'], size=10)
        release, outcome = resolve_owning_release(DEST, [other], size_on_disk=10)
        assert release is None
        assert outcome == DECLINED_NO_OWNER

    def test_an_empty_release_list_is_refused(self):
        release, outcome = resolve_owning_release(DEST, [], size_on_disk=10)
        assert (release, outcome) == (None, DECLINED_NO_OWNER)

    def test_none_instead_of_a_release_list_is_refused(self):
        release, outcome = resolve_owning_release(DEST, None, size_on_disk=10)
        assert (release, outcome) == (None, DECLINED_NO_OWNER)


class TestOneReleaseClaimsThePath:
    def test_it_wins_when_the_size_confirms_it(self):
        only = _release('r1', [DEST], size=5000)
        release, outcome = resolve_owning_release(DEST, [only], size_on_disk=5000)
        assert outcome == OWNER_RESOLVED
        assert release['_id'] == 'r1'

    def test_a_size_mismatch_is_refused_even_though_it_is_the_only_claimant(self):
        """AC-DATA-6. A single claimant proves which release was scanned from
        this path, NOT that the bytes there now are the ones it described.

        The file may have been replaced by hand since the scan. Deleting it on
        the strength of a stale record is the failure this criterion exists for.
        """
        only = _release('r1', [DEST], size=5000)
        release, outcome = resolve_owning_release(DEST, [only], size_on_disk=9999)
        assert (release, outcome) == (None, DECLINED_UNVERIFIED_COPY)

    def test_a_release_with_no_copy_id_is_refused(self):
        """Releases written before FEAT-009 Part A have no copy_id at all."""
        legacy = _release('r1', [DEST])          # no copy_id
        release, outcome = resolve_owning_release(DEST, [legacy], size_on_disk=5000)
        assert (release, outcome) == (None, DECLINED_UNVERIFIED_COPY)

    def test_an_unstattable_destination_is_refused(self):
        """size_on_disk=None means "could not stat", which must read as no."""
        only = _release('r1', [DEST], size=5000)
        release, outcome = resolve_owning_release(DEST, [only], size_on_disk=None)
        assert (release, outcome) == (None, DECLINED_UNVERIFIED_COPY)


class TestSeveralReleasesClaimTheSamePath:
    """The NORMAL case, not an edge case: the default rename template carries
    no quality token, so every copy of a movie renames to the same path.
    """

    def test_the_one_matching_by_size_wins(self):
        small = _release('r-720p', [DEST], size=3_000_000)
        large = _release('r-2160p', [DEST], size=40_000_000)
        release, outcome = resolve_owning_release(
            DEST, [small, large], size_on_disk=40_000_000
        )
        assert outcome == OWNER_RESOLVED
        assert release['_id'] == 'r-2160p'

    def test_it_still_picks_correctly_in_the_other_order(self):
        """Guards against a resolver that just returns the first candidate."""
        small = _release('r-720p', [DEST], size=3_000_000)
        large = _release('r-2160p', [DEST], size=40_000_000)
        release, outcome = resolve_owning_release(
            DEST, [large, small], size_on_disk=3_000_000
        )
        assert outcome == OWNER_RESOLVED
        assert release['_id'] == 'r-720p'

    def test_no_candidate_matching_by_size_is_refused(self):
        a = _release('r1', [DEST], size=1000)
        b = _release('r2', [DEST], size=2000)
        release, outcome = resolve_owning_release(DEST, [a, b], size_on_disk=7777)
        assert (release, outcome) == (None, DECLINED_AMBIGUOUS_OWNER)

    def test_two_candidates_matching_by_size_is_refused(self):
        """Two encodes of identical byte length is vanishingly unlikely and
        therefore exactly the case to refuse rather than guess between."""
        a = _release('r1', [DEST], size=5000)
        b = _release('r2', [DEST], size=5000)
        release, outcome = resolve_owning_release(DEST, [a, b], size_on_disk=5000)
        assert (release, outcome) == (None, DECLINED_AMBIGUOUS_OWNER)


class TestOnlyTheMovieBucketIsEvidence:
    def test_a_subtitle_sharing_the_path_does_not_make_a_release_a_claimant(self):
        """`copyIdentity` restricts itself to the movie bucket for the same
        reason: a poster or .srt alongside says nothing about which encode is
        on disk."""
        sub_only = {
            '_id': 'r1',
            'files': {'subtitle': [DEST]},
            'copy_id': copy_id_for_sizes([5000]),
        }
        release, outcome = resolve_owning_release(DEST, [sub_only], size_on_disk=5000)
        assert (release, outcome) == (None, DECLINED_NO_OWNER)

    def test_a_release_with_no_files_key_does_not_crash(self):
        release, outcome = resolve_owning_release(DEST, [{'_id': 'r1'}], size_on_disk=5000)
        assert (release, outcome) == (None, DECLINED_NO_OWNER)


@pytest.mark.parametrize('variant', [
    DEST,
    DEST.replace('/', os.sep) if os.sep != '/' else DEST,
])
def test_paths_are_compared_after_sp_normalisation(variant):
    """AC-SEC-9 specifies `sp()` normalisation on both sides, so a recorded
    path and a destination that differ only cosmetically still match."""
    only = _release('r1', [variant], size=5000)
    release, outcome = resolve_owning_release(DEST, [only], size_on_disk=5000)
    assert outcome == OWNER_RESOLVED, (variant, outcome)
    assert release['_id'] == 'r1'
