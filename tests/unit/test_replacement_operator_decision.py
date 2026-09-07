"""Which library file does the OPERATOR's replacement act on? (FEAT-011)

The owner's fifth decision, derived rather than asked, because it follows from
the safety requirement and eight of nine planning lenses raised it as High:
**the destination is resolved from the media's EXISTING file record, and NEVER
recomputed from the naming template.** A lens executed the real naming
template and got `The Thing ()/The Thing.mkv` for two different films that
both lack a year, so a template-resolved destination can name a DIFFERENT
film's file -- precisely what `_identityIsAsserted` (`renamer/main.py:767`)
exists to prevent on the automatic path, and reintroducing it here would be
the third incident (`replacement.py`'s own module docstring records the first
two).

This module tests only the pure resolution-and-decision step: given the
release documents already recorded for one film, which single one of them
names the file now in the library, and what happens when that cannot be
answered. It performs no filesystem or database operation, exactly like
`decide_replacement` beside it -- the operator-initiated swap is separate
work, out of scope here.

Every "no" is a named outcome, never a falsy return, matching this module's
established shape: a caller must be able to tell "nothing recorded to
replace" apart from "more than one candidate, refusing to guess" apart from
"here is the file". Nothing to replace is not permission to fall back to a
computed name.
"""
import pytest

from couchpotato.core.plugins.renamer.replacement import (
    OPERATOR_DECLINED_AMBIGUOUS_FILE,
    OPERATOR_DECLINED_NO_FILE_TO_REPLACE,
    OPERATOR_REPLACE,
    decide_operator_replacement,
)


def _release(status='done', paths=('/library/A (2020)/A.mkv',), _id='r-1'):
    return {
        '_id': _id,
        'status': status,
        'files': {'movie': list(paths)},
    }


class TestTheHappyPathExistsAtAll:
    """The control for every refusal below. Without it, a function that
    refused unconditionally would pass the rest of this file -- the exact
    shape withdrawn attempt #2 shipped, per `replacement.py`'s docstring."""

    @pytest.mark.parametrize('status', ['done', 'seeding', 'downloaded'])
    def test_a_single_qualifying_release_resolves_to_its_recorded_file(self, status):
        release = _release(status=status)
        outcome, existing = decide_operator_replacement([release])
        assert outcome == OPERATOR_REPLACE
        assert existing is release


class TestTheDestinationIsNeverRecomputedFromTheTemplate:
    """Measured on production: with an empty year, the real naming template
    (`namer.py`) renders `The Thing ()/The Thing.mkv` for two DIFFERENT
    films. A destination resolved from each film's own release record must
    not reproduce that collision -- it must read the path that was actually
    recorded for that film, not a name computed from title and year.
    """

    def test_two_films_that_would_collide_under_the_template_still_resolve_to_their_own_recorded_files(self):
        film_a = _release(_id='r-a', paths=('/library/The Thing ()/The Thing.mkv',))
        film_b = _release(_id='r-b', paths=('/library/The Other Thing ()/The Other Thing.mkv',))

        outcome_a, existing_a = decide_operator_replacement([film_a])
        outcome_b, existing_b = decide_operator_replacement([film_b])

        assert (outcome_a, existing_a) == (OPERATOR_REPLACE, film_a)
        assert (outcome_b, existing_b) == (OPERATOR_REPLACE, film_b)
        assert existing_a['files']['movie'][0] != existing_b['files']['movie'][0], (
            'two different films resolved to the same destination -- the '
            'exact collision the naming template produces, and the exact '
            'failure the release record must not reproduce'
        )


class TestNothingRecordedRefusesRatherThanGuessing:
    """D5. A hand-placed file has nothing recorded about it at all; that is
    the ordinary case this feature exists for, not an edge case. Falling back
    to a computed name here is the bug this whole decision exists to forbid.
    """

    def test_no_releases_at_all_refuses(self):
        outcome, existing = decide_operator_replacement([])
        assert outcome == OPERATOR_DECLINED_NO_FILE_TO_REPLACE
        assert existing is None

    def test_a_release_with_no_recorded_movie_file_does_not_count_as_owning_one(self):
        release = _release(paths=())
        outcome, existing = decide_operator_replacement([release])
        assert outcome == OPERATOR_DECLINED_NO_FILE_TO_REPLACE
        assert existing is None

    @pytest.mark.parametrize('status', ['snatched', 'ignored', 'available', None])
    def test_a_release_whose_status_is_not_a_completed_one_does_not_count(self, status):
        """Only a release that actually landed in the library (done, seeding
        or downloaded, per AC-DESIGN-1) can be the current copy. A snatched
        or ignored release has no file on disk to be the destination."""
        release = _release(status=status)
        outcome, existing = decide_operator_replacement([release])
        assert outcome == OPERATOR_DECLINED_NO_FILE_TO_REPLACE
        assert existing is None


class TestTwoCandidatesRefuseRatherThanPickingOne:
    """AC-PROD-4: where the existing library file cannot be named uniquely
    from the movie's own records, the action refuses and says so rather than
    choosing between candidates. Picking either one here risks destroying the
    copy the operator did NOT mean, which is indistinguishable on the wire
    from picking the wrong film entirely.
    """

    def test_two_qualifying_releases_refuse(self):
        a = _release(_id='r-a', paths=('/library/A (2020)/A-1080p.mkv',))
        b = _release(_id='r-b', paths=('/library/A (2020)/A-2160p.mkv',))
        outcome, existing = decide_operator_replacement([a, b])
        assert outcome == OPERATOR_DECLINED_AMBIGUOUS_FILE
        assert existing is None

    def test_ambiguity_is_not_resolved_by_release_order(self):
        """A permissive implementation could quietly return 'the first
        qualifying release' and every test above would still pass. This pins
        that the SAME two releases refuse regardless of which is listed
        first, so 'first in the list' cannot be standing in for a real
        resolution."""
        a = _release(_id='r-a', paths=('/library/A (2020)/A-1080p.mkv',))
        b = _release(_id='r-b', paths=('/library/A (2020)/A-2160p.mkv',))
        outcome_ab, existing_ab = decide_operator_replacement([a, b])
        outcome_ba, existing_ba = decide_operator_replacement([b, a])
        assert outcome_ab == outcome_ba == OPERATOR_DECLINED_AMBIGUOUS_FILE
        assert existing_ab is None, 'a-then-b order left a stray existing release'
        assert existing_ba is None, 'b-then-a order left a stray existing release'
