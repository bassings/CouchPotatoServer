"""Tests for the profile-independent quality ranking primitive (FEAT-009B, B1).

`QualityPlugin.rankQuality` / `isBetterQuality` answer "is this file
objectively better", never "should I keep searching under this profile".
That confusion is exactly what withdrew attempt #2 of the upgrade-replacement
feature: it used `isHigher`, which looks a quality up *in a profile* and
falls through to "anything beats a rung I do not want" when the rung is
absent. The default 'Best' profile excludes 2160p, so `isHigher` authorised
replacing a 2160p remux with a 720p file.

This primitive must never consult a profile, never fire 'profile.default',
and never call `isHigher` -- see `test_ranking_never_consults_a_profile`,
which proves that by counting calls rather than only checking the answer,
because a lucky answer from a profile-consulting implementation would still
pass a naive assertion.

See specs/FEAT-009B-UPGRADE-REPLACEMENT.md, "Decisions taken after
planning" D2, and the T5.1 entry under "Proposed shape".
"""
import shutil

import pytest

from couchpotato.core.plugins.quality.main import QualityPlugin
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


def _make_plugin(monkeypatch, get_db_return=None):
    """A QualityPlugin instance built the way the existing quality tests
    build one (see test_quality_detection.py): addEvent/addApiView/Env are
    patched so __init__ doesn't touch the global event registry or a real
    Env, but the ranking methods under test run for real -- they are pure
    functions of `self.qualities` / `self.order` and take no DB access.
    """
    monkeypatch.setattr('couchpotato.core.plugins.base.Env', __import__(
        'unittest.mock', fromlist=['MagicMock']).MagicMock())
    monkeypatch.setattr('couchpotato.core.plugins.quality.main.addEvent',
                         lambda *a, **k: None)
    monkeypatch.setattr('couchpotato.core.plugins.quality.main.addApiView',
                         lambda *a, **k: None)
    if get_db_return is not None:
        monkeypatch.setattr('couchpotato.core.plugins.quality.main.get_db',
                             lambda: get_db_return)

    return QualityPlugin()


class TestRankQualityOrder:
    """AC-QA-1: the full ordering, derived from the code list, plus two
    named relationships pinned by literal identifier so a derivation bug (or
    a swap inside `QualityPlugin.qualities`) cannot make the whole test
    vacuous.
    """

    def test_rank_is_the_index_in_QualityPlugin_qualities(self, monkeypatch):
        """Every identifier's rank equals its position in the in-code list.

        Derived, not hardcoded: if a rung is added, removed or reordered in
        `QualityPlugin.qualities`, `expected` moves with it and this test
        still passes -- it is pinning the RELATIONSHIP between the list and
        the rank function, not today's snapshot of the list.
        """
        plugin = _make_plugin(monkeypatch)

        expected = [q['identifier'] for q in QualityPlugin.qualities]
        assert expected, 'QualityPlugin.qualities must not be empty'

        actual = [plugin.rankQuality(identifier) for identifier in expected]
        assert actual == list(range(len(expected)))

    def test_bd50_ranks_better_than_1080p(self, monkeypatch):
        """Named relationship pin: catches a swap that the derived test
        above cannot, because the derived test's expectation moves with the
        list -- this assertion is anchored to the identifiers by name, not
        to whatever order they currently sit in.
        """
        plugin = _make_plugin(monkeypatch)
        assert plugin.rankQuality('bd50') < plugin.rankQuality('1080p')

    def test_brrip_ranks_worse_than_720p(self, monkeypatch):
        """Named relationship pin, see test_bd50_ranks_better_than_1080p."""
        plugin = _make_plugin(monkeypatch)
        assert plugin.rankQuality('brrip') > plugin.rankQuality('720p')


    def test_the_full_order_matches_a_literal_snapshot(self, monkeypatch):
        """The derived check above catches a rung being ADDED. It is blind to
        one being REORDERED, because `expected` moves with the source.

        Measured: swapping `tc` and `ts` in `QualityPlugin.qualities` left all
        20 tests in this file green, while the replacement gate would then
        consider the wrong copy better. That is the incidentally-passing shape
        CLAUDE.md rule 11 is about, and on a delete path it is the shape that
        removes the wrong file.

        So the order is ALSO pinned literally. The two together are the guard:
        derived catches additions, literal catches reordering, neither alone
        is sufficient. Changing this list is meant to be a deliberate act with
        a reason in the commit message.
        """
        plugin = _make_plugin(monkeypatch)
        assert plugin.order == [
            '2160p', 'bd50', '1080p', '720p', 'brrip', 'dvdr',
            'dvdrip', 'scr', 'r5', 'tc', 'ts', 'cam',
        ]


class TestBareIdentifiersAreRefusedNotAssumedNon3D:
    """A release document stores `quality` and `is_3d` as SIBLING fields, so
    the natural call site is `existing['quality']` -- a bare string carrying
    no 3D information at all.

    Defaulting that to non-3D made a 2D 1080p incoming copy compare better
    than an existing 3D 720p copy: measured returning True before the guard.
    On the path that deletes from the library, absent metadata must mean
    refuse, never "assume the convenient value".
    """

    def test_a_string_existing_is_refused(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality({'identifier': '1080p'}, '720p') is False

    def test_a_string_incoming_is_refused(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality('2160p', {'identifier': '720p'}) is False

    def test_a_dict_without_is_3d_is_also_refused(self, monkeypatch):
        """Absent is not the same as False, and both real call sites supply it.

        `quality.guess` always sets `is_3d` (quality/main.py:369 defaults it to
        False), and a release document stores it explicitly. So a dict carrying
        `identifier` and no `is_3d` is a caller that built the dict by hand and
        dropped the field -- most likely from `r['quality']` alone, since the
        release doc holds the two as siblings. Same rule as the bare string:
        absent metadata refuses.
        """
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '2160p'}, {'identifier': '720p'}
        ) is False

    def test_two_full_dicts_still_compare_normally(self, monkeypatch):
        """The control: refusing incomplete operands must not disable the
        feature. This is the shape a real caller passes."""
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '2160p', 'is_3d': False},
            {'identifier': '720p', 'is_3d': False},
        ) is True


class TestRankQualityUnknown:
    """AC-QA-2: unknown input ranks None, never 0 -- 0 is the BEST rank, so
    returning it for "unknown" would let an unrecognised quality masquerade
    as the best copy available and authorise a replacement it never earned.
    """

    @pytest.mark.parametrize('bad_input', [
        'not-a-real-quality',
        '',
        None,
        12345,
        {'label': 'no identifier key here'},
        {},
    ], ids=['unknown-identifier', 'empty-string', 'none', 'non-string',
            'dict-no-identifier', 'empty-dict'])
    def test_returns_none_not_zero_not_an_exception(self, monkeypatch, bad_input):
        plugin = _make_plugin(monkeypatch)
        assert plugin.rankQuality(bad_input) is None


class TestIsBetterQualityUnknown:
    """AC-QA-3: either side ranking None refuses, in both argument orders."""

    def test_unknown_incoming_is_not_better(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality('not-a-quality', '720p') is False

    def test_unknown_existing_is_not_better(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality('720p', 'not-a-quality') is False

    def test_both_unknown_is_not_better(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(None, {}) is False


class Test720pVs2160p:
    """Regression pin for withdrawn attempt #1: this is the exact case
    measured to destroy a remux -- a 720p download overwrote a 2160p one.
    """

    def test_incoming_720p_against_existing_2160p_is_not_better(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '720p', 'is_3d': False},
            {'identifier': '2160p', 'is_3d': False},
        ) is False


class TestEqualRungIsNotBetter:
    """AC-QA-7 (equal-rung half): only a STRICTLY better rung authorises
    replacement.
    """

    def test_equal_rung_equal_3d_is_not_better(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '1080p', 'is_3d': False},
            {'identifier': '1080p', 'is_3d': False},
        ) is False


class TestIs3dRuleRefusesInBothDirections:
    """AC-QA-7: any is_3d difference is not-better, in both directions and
    at two rung relationships -- same rung, and the 3D copy at a worse rung.
    is_3d is not part of the global list ordering, so a 3D and a non-3D copy
    are never comparable, however their rungs relate.
    """

    def test_same_rung_incoming_3d_existing_not_is_not_better(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '1080p', 'is_3d': True},
            {'identifier': '1080p', 'is_3d': False},
        ) is False

    def test_same_rung_existing_3d_incoming_not_is_not_better(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '1080p', 'is_3d': False},
            {'identifier': '1080p', 'is_3d': True},
        ) is False

    def test_worse_rung_3d_incoming_vs_better_rung_non3d_existing_is_not_better(self, monkeypatch):
        """The 3D copy sits at a WORSE rung than the existing file: even
        though the rung comparison alone would already refuse, this pins
        that the 3D mismatch is checked independently rather than only being
        reached when the rungs would otherwise authorise a replacement.
        """
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '720p', 'is_3d': True},
            {'identifier': '1080p', 'is_3d': False},
        ) is False

    def test_better_rung_3d_incoming_vs_worse_rung_non3d_existing_is_not_better(self, monkeypatch):
        """The ONLY case where rank alone would authorise a replacement and
        only the 3D rule stops it -- so it is the only case that can catch an
        ASYMMETRIC implementation.

        A check written as `if existing_is_3d and not incoming_is_3d` passes
        every other 3D test in this class: the same-rung pair is refused by
        rank equality, the worse-incoming pair by rank, and the
        existing-3D pair by the asymmetric branch itself. Only this
        combination -- incoming strictly better AND 3D, existing worse and 2D
        -- reaches the comparison with rank saying "replace".

        Without it the suite is green while a 3D copy silently overwrites a
        2D one at a lower rung, which is a different film for anyone without
        3D playback.
        """
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '2160p', 'is_3d': True},
            {'identifier': '720p', 'is_3d': False},
        ) is False

    def test_worse_rung_3d_existing_vs_better_rung_non3d_incoming_would_be_better_but_for_3d(self, monkeypatch):
        """Here the rung comparison alone WOULD authorise a replacement
        (1080p incoming beats 720p existing) -- the 3D mismatch must still
        refuse it.
        """
        plugin = _make_plugin(monkeypatch)
        assert plugin.isBetterQuality(
            {'identifier': '1080p', 'is_3d': False},
            {'identifier': '720p', 'is_3d': True},
        ) is False


class TestNeverConsultsAProfile:
    """AC-QA-5: regression pin for withdrawn attempt #2, proven by COUNTING
    calls rather than only checking the answer -- a profile-consulting
    implementation could still get lucky on the answer for one input.

    A real SQLite database is seeded with the default 'Best' profile (which
    excludes 2160p, per the spec's D1) so the proof holds even when a real
    profile that WOULD change the answer under `isHigher` is sitting right
    there in the database the plugin's own `get_db()` returns.
    """

    @pytest.fixture
    def seeded_db(self, tmp_path):
        db = SQLiteAdapter()
        db.create(str(tmp_path / 'quality-ranking-db'))

        # The shipped default profile: excludes 2160p entirely, which is
        # exactly the condition that made `isHigher` authorise destroying a
        # remux (spec D1/attempt #2).
        db.insert({
            '_t': 'profile',
            'label': 'Best',
            'core': True,
            'order': 0,
            'qualities': ['1080p', '720p', 'brrip', 'dvdrip'],
            'finish': [True, True, True, True],
            'wait_for': [0, 0, 0, 0],
            'stop_after': [0, 0, 0, 0],
            '3d': [False, False, False, False],
            'minimum_score': 1,
        })

        yield db
        db.close()
        shutil.rmtree(str(tmp_path / 'quality-ranking-db'), ignore_errors=True)

    def test_no_fireEvent_and_no_isHigher_calls(self, monkeypatch, seeded_db):
        plugin = _make_plugin(monkeypatch, get_db_return=seeded_db)

        fire_calls = []

        def _counting_fire(name, *args, **kwargs):
            fire_calls.append(name)
            return []

        monkeypatch.setattr(
            'couchpotato.core.plugins.quality.main.fireEvent', _counting_fire)

        is_higher_calls = []

        def _counting_is_higher(self_, quality, compare_with, profile=None):
            is_higher_calls.append((quality, compare_with, profile))
            return 'lower'

        monkeypatch.setattr(QualityPlugin, 'isHigher', _counting_is_higher)

        result = plugin.isBetterQuality(
            {'identifier': '720p', 'is_3d': False},
            {'identifier': '2160p', 'is_3d': False},
        )

        assert result is False, \
            '720p incoming against 2160p existing must not be better'
        assert fire_calls == [], (
            'the ranking path fired an event -- it must consult nothing, '
            'and firing profile.default is exactly attempt #2\'s bug: %r'
            % fire_calls)
        assert is_higher_calls == [], (
            'the ranking path called QualityPlugin.isHigher -- that answers '
            '"should I keep searching under a profile", not "is this file '
            'objectively better": %r' % is_higher_calls)


class TestIs3dReadFromArgumentNotFromCache:
    """AC-SEC-11: guessing a 3D release earlier in the SAME process leaves
    `is_3d = True` on the cached quality dict for that rung indefinitely
    (`QualityPlugin.guess` mutates the dict it gets from `self.all()`, which
    is cached on `self.cached_qualities` for the process lifetime). The
    comparison must take is_3d from each file's own (release-doc-sourced)
    metadata, never from that shared cache -- otherwise a 3D guess made for
    an unrelated file poisons every later comparison at the same rung.

    This is only a meaningful test if it runs the 3D guess FIRST, in the
    same process, before the comparison -- a fresh process would never
    observe the poisoned cache.
    """

    def test_prior_3d_guess_does_not_poison_a_later_non_3d_comparison(self, monkeypatch):
        plugin = _make_plugin(monkeypatch)

        # Pre-populate self.cached_qualities exactly as self.all() would
        # build it, so guess() below doesn't need a real DB/get_db.
        cached = []
        for q in plugin.qualities:
            q_copy = dict(q)
            q_copy['size_min'] = q.get('size', (0, 0))[0]
            q_copy['size_max'] = q.get('size', (0, 0))[1]
            cached.append(q_copy)
        plugin.cached_qualities = cached

        # scanner.name_year is fired inside guess(); give it a harmless
        # deterministic answer instead of hitting the real scanner plugin
        # (which isn't registered in this fixture).
        def _fake_fire(name, *args, **kwargs):
            if name == 'scanner.name_year':
                return {'name': 'Movie Name', 'year': 2014}
            return []
        monkeypatch.setattr(
            'couchpotato.core.plugins.quality.main.fireEvent', _fake_fire)

        # Guess a 3D 1080p release. This mutates the SHARED cached '1080p'
        # entry's is_3d to True, in place, for the rest of the process.
        threed_result = plugin.guess(
            files=['Movie.Name.2014.3D.1080p.BluRay.x264-Group'],
            size=8500, use_cache=False)
        assert threed_result is not None
        assert threed_result['identifier'] == '1080p'
        assert threed_result['is_3d'] is True, \
            'setup failed to reproduce the cache-poisoning precondition'

        # Confirm the poison actually landed on the shared cache entry --
        # otherwise the assertion below would pass for the wrong reason.
        cached_1080p = next(
            q for q in plugin.cached_qualities if q['identifier'] == '1080p')
        assert cached_1080p['is_3d'] is True, \
            'the cached quality dict was not poisoned -- test setup is wrong'

        # Now compare two FRESH, independent dicts -- the shape a release
        # document actually provides (D2: quality comes from the release
        # doc, never from quality.guess) -- both explicitly non-3D at 1080p
        # and 720p. If the comparison read is_3d from the poisoned cache
        # instead of from these arguments, it would see the incoming side as
        # 3D and wrongly refuse this strictly-better replacement.
        incoming = {'identifier': '1080p', 'is_3d': False}
        existing = {'identifier': '720p', 'is_3d': False}

        assert plugin.isBetterQuality(incoming, existing) is True, (
            'a non-3D 1080p must still beat a non-3D 720p after an unrelated '
            '3D guess poisoned the cached 1080p entry -- is_3d must come '
            'from the argument, not from self.all()/self.cached_qualities')
