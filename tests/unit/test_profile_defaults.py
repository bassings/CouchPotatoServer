"""Tests for the seeded default quality profiles (BUG-016).

The built-in profiles were ordered worst-first: `Best` was
`['720p', '1080p', 'brrip', 'dvdrip']`, and index 0 of a profile is the
*most preferred* quality (`quality/main.py`: "a lower number means higher
quality"). Since `MovieSearcher.single()` breaks out of the quality loop on
the first successful download, `Best` grabbed 720p and never reached 1080p.
`UHD 4K` was `['720p', '1080p', '2160p']`, so it could never fetch 2160p.

These tests assert the ordering against the canonical ranking derived from
`QualityPlugin.qualities` rather than a hardcoded copy of the expected lists,
so they keep meaning something if a quality is added or the seeds change.

See specs/BUG-016-default-profile-quality-order.md.
"""

import pytest

from couchpotato.core.plugins.profile.main import DEFAULT_PROFILES, build_profile_doc
from couchpotato.core.plugins.quality.main import QualityPlugin

# Canonical best-first ranking: position in QualityPlugin.qualities.
# Lower number == higher quality, matching the profile ordering contract.
CANONICAL_RANK = {
    quality['identifier']: index
    for index, quality in enumerate(QualityPlugin.qualities)
}


def _expanded(profile):
    """The stored document a seeded profile turns into."""
    return build_profile_doc(profile, order=0)


def _rank_groups(doc):
    """Split a profile's qualities into runs by their 3D flag, preserving
    order, and map each to its canonical rank.

    Grouping matters for `Prefer 3D HD`, which is deliberately "all 3D
    first, then all non-3D". Ordering is only required to be best-first
    *within* each group; a 3D 720p outranking a non-3D 1080p is the whole
    point of that profile.
    """
    groups = {}
    for identifier, is_3d in zip(doc['qualities'], doc['3d']):
        groups.setdefault(bool(is_3d), []).append(CANONICAL_RANK[identifier])
    return groups


@pytest.mark.parametrize('profile', DEFAULT_PROFILES, ids=lambda p: p['label'])
class TestDefaultProfileOrdering:

    def test_qualities_are_best_first(self, profile):
        """AC1 (bug repro): every seeded profile lists its qualities
        best-first. Fails against the unfixed seeds for Best, HD, SD,
        UHD 4K and Prefer 3D HD."""
        doc = _expanded(profile)

        for is_3d, ranks in _rank_groups(doc).items():
            assert ranks == sorted(ranks), (
                "%s: %s qualities are not best-first (canonical ranks %s, "
                "expected ascending)" % (
                    profile['label'],
                    '3D' if is_3d else 'non-3D',
                    ranks,
                )
            )

    def test_positional_lists_match_qualities_length(self, profile):
        """AC2: finish/wait_for/stop_after/3d are positional siblings of
        qualities — a length mismatch silently detaches a flag from its
        quality (or IndexErrors in MovieSearcher.single())."""
        doc = _expanded(profile)
        expected = len(doc['qualities'])

        for key in ('finish', 'wait_for', 'stop_after', '3d'):
            assert len(doc[key]) == expected, (
                "%s: '%s' has %d entries, expected %d" % (
                    profile['label'], key, len(doc[key]), expected,
                )
            )

    def test_every_quality_identifier_is_real(self, profile):
        """A typo'd identifier is silently skipped by the searcher
        (`quality.single` returns nothing), quietly disabling that rung of
        the profile."""
        doc = _expanded(profile)

        for identifier in doc['qualities']:
            assert identifier in CANONICAL_RANK, (
                "%s: unknown quality identifier %r" % (profile['label'], identifier)
            )


class TestSpecificDefaultProfiles:
    """Targeted assertions for the profiles whose *names* make a promise the
    ordering has to keep. The parametrised suite above proves ordering is
    self-consistent; these pin the intent."""

    def _by_label(self, label):
        for profile in DEFAULT_PROFILES:
            if profile['label'] == label:
                return _expanded(profile)
        raise AssertionError('no seeded profile labelled %r' % label)

    def test_best_prefers_1080p_over_720p(self):
        """AC1: the reported bug — 'Best' must not grab 720p first."""
        doc = self._by_label('Best')
        qualities = doc['qualities']

        assert qualities.index('1080p') < qualities.index('720p'), (
            "'Best' must prefer 1080p over 720p, got %s" % qualities
        )

    def test_best_does_not_silently_add_2160p(self):
        """Deliberate scope limit: reordering must not change which
        qualities are in the set. Adding 2160p to 'Best' would switch
        existing users onto 20-60GB downloads without them asking."""
        doc = self._by_label('Best')

        assert '2160p' not in doc['qualities'], (
            "'Best' gained 2160p — that is a behaviour change, not a reorder"
        )

    def test_uhd_4k_prefers_2160p_first(self):
        """AC1: 'UHD 4K' led with 720p, so it could never deliver 4K while
        any 720p release existed."""
        doc = self._by_label('UHD 4K')

        assert doc['qualities'][0] == '2160p', (
            "'UHD 4K' must lead with 2160p, got %s" % doc['qualities']
        )

    def test_sd_prefers_dvdr_over_dvdrip(self):
        """AC1: DVD-R (full disc) outranks DVD-Rip in the canonical list."""
        doc = self._by_label('SD')
        qualities = doc['qualities']

        assert qualities.index('dvdr') < qualities.index('dvdrip'), (
            "'SD' must prefer dvdr over dvdrip, got %s" % qualities
        )

    def test_prefer_3d_hd_keeps_3d_first_then_ordered_non_3d(self):
        """AC3: the 3D head must stay 1080p-3D then 720p-3D, and the non-3D
        tail must itself be 1080p then 720p. The flags come from
        `threed.pop()`, so a careless reorder detaches them."""
        doc = self._by_label('Prefer 3D HD')
        pairs = list(zip(doc['qualities'], [bool(x) for x in doc['3d']]))

        assert pairs == [
            ('1080p', True),
            ('720p', True),
            ('1080p', False),
            ('720p', False),
        ], "'Prefer 3D HD' quality/3D pairing is wrong: %s" % pairs

    def test_3d_hd_is_all_3d_and_ordered(self):
        """Regression guard: '3D HD' was already correct and must stay so."""
        doc = self._by_label('3D HD')
        pairs = list(zip(doc['qualities'], [bool(x) for x in doc['3d']]))

        assert pairs == [('1080p', True), ('720p', True)], (
            "'3D HD' pairing is wrong: %s" % pairs
        )


class TestBuildProfileDoc:
    """`build_profile_doc` is the seam that makes the seeds testable without
    a database; pin its contract."""

    def test_order_is_passed_through(self):
        doc = build_profile_doc({'label': 'X', 'qualities': ['720p']}, order=7)
        assert doc['order'] == 7

    def test_defaults_are_finish_true_and_no_waiting(self):
        """The seeds are 'take the best thing available now, then stop'."""
        doc = build_profile_doc(
            {'label': 'X', 'qualities': ['1080p', '720p']}, order=0,
        )

        assert doc['finish'] == [True, True]
        assert doc['wait_for'] == [0, 0]
        assert doc['stop_after'] == [0, 0]
        assert doc['3d'] == [False, False]

    def test_is_marked_as_a_profile_document(self):
        doc = build_profile_doc({'label': 'X', 'qualities': ['720p']}, order=0)
        assert doc['_t'] == 'profile'
