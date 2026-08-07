"""Tests for MovieSearcher.correctRelease() -- the only filter between
indexer-supplied release metadata and a download being queued.

T1.2 (specs/REMEDIATION-2026-08.md). Two bugs pinned and fixed here:

1. `searcher.py:419` used to read
   `quality if quality else fireEvent('quality.single', identifier =
   quality['identifier'], single = True)` -- the fallback branch dereferences
   the value that was JUST established as falsy. For `quality=None`/`False`
   this raises `TypeError` before `fireEvent` is even called; for
   `quality={}` it raises `KeyError: 'identifier'`. The NATURAL repair,
   `quality.get('identifier')`, is WORSE: `SQLiteAdapter._query_index`
   treats `key is None` as "no filter", so
   `db.get('quality', None, with_doc=True)` silently returns the FIRST
   quality row (measured: 'cam') instead of raising -- resolving a random
   quality's size gates for a release nobody chose, in the function that
   decides what gets downloaded. The fix never resolves a quality from the
   database when `quality` is falsy: it returns False with a logged reason
   instead.

2. Once (1) stops crashing on a falsy `quality`, two more crashes on the
   *same* function become reachable with a legitimately truthy-but-partial
   quality dict, because `custom` is grafted onto the quality dict by the
   CALLER (searcher.py:326) and is never part of what `QualityPlugin.single()`
   itself returns (quality/main.py:128-142):
     - `:429` did `preferred_quality['custom'].get('3d')` -> KeyError when a
       dict from `single()` (no `custom` key) reaches here and 3D doesn't
       match.
     - `:433`/`:438` read `preferred_quality['size_min']`/`['size_max']`
       directly -- safe for every currently-reachable dict (they always come
       from a DB doc written by `QualityPlugin.fill()`, which always sets
       both), but a corrupted/partial doc would still KeyError instead of
       being rejected safely. Guarded defensively; behaviour for a normal
       (complete) doc is unchanged.

Every quality dict used below is built the way `QualityPlugin.single()`
actually builds one: the real static entry (quality/main.py:26-38) merged
with a real DB doc via a real `SQLiteAdapter`, not hand-rolled. A hand-rolled
dict that happens to carry 'custom' would hide bug (2) above, and this repo
has already shipped the "one-row fixture passes against a key-ignoring
lookup" defect class twice (sqlite_adapter.py `_query_index`, see
docs/technical-debt.md).
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.logger import INFO2
from couchpotato.core.media.movie.searcher import MovieSearcher
from couchpotato.core.plugins.quality.main import QualityPlugin


SEARCHER_LOGGER = 'couchpotato.core.media.movie.searcher'


@pytest.fixture
def searcher():
    """Bypass __init__ (addEvent/addApiView plugin registration) the same
    way test_search_releases_list_only.py and test_movie_searcher_eta.py do
    -- correctRelease reads no instance state."""
    return MovieSearcher.__new__(MovieSearcher)


# --- Fixture builders -------------------------------------------------

def _media(year=2020, titles=None, imdb='tt1234567', media_type='movie'):
    return {
        'type': media_type,
        'identifiers': {'imdb': imdb},
        'info': {
            'year': year,
            'titles': titles if titles is not None else ['Some Movie'],
        },
    }


def _nzb(name='Some.Movie.2020.1080p.BluRay.x264-GROUP', size=5000, age=1,
         seeders=10, description='', extra_check=None, get_more_info=None):
    nzb = {
        'name': name,
        'size': size,
        'age': age,
        'seeders': seeders,
        'description': description,
    }
    if extra_check is not None:
        nzb['extra_check'] = extra_check
    if get_more_info is not None:
        nzb['get_more_info'] = get_more_info
    return nzb


def _real_quality(tmp_path, db_name, identifier, size_min, size_max):
    """Build a quality dict exactly the way QualityPlugin.single() does: the
    real static entry merged with a real DB doc via a real SQLiteAdapter.
    Deliberately NOT hand-rolled -- see module docstring."""
    db = SQLiteAdapter()
    db.create(str(tmp_path / db_name))
    try:
        db.insert({
            '_t': 'quality',
            'identifier': identifier,
            'order': 0,
            'size_min': size_min,
            'size_max': size_max,
        })
        plugin = QualityPlugin.__new__(QualityPlugin)
        with patch('couchpotato.core.plugins.quality.main.get_db', return_value=db):
            return plugin.single(identifier)
    finally:
        db.close()


def _real_quality_missing_size(tmp_path, db_name, identifier):
    """A quality doc that exists but was never given size bounds -- the
    corrupted/partial-doc case :433/:438's defensive .get() guards against.
    Every doc written by QualityPlugin.fill() carries both fields; this
    models the doc NOT written that way."""
    db = SQLiteAdapter()
    db.create(str(tmp_path / db_name))
    try:
        db.insert({'_t': 'quality', 'identifier': identifier, 'order': 0})
        plugin = QualityPlugin.__new__(QualityPlugin)
        with patch('couchpotato.core.plugins.quality.main.get_db', return_value=db):
            return plugin.single(identifier)
    finally:
        db.close()


def _unresolvable_quality(tmp_path, db_name):
    """The real single() output for an identifier with no DB row at all:
    {} (quality/main.py:128-142, RecordNotFound/KeyError branch)."""
    db = SQLiteAdapter()
    db.create(str(tmp_path / db_name))
    try:
        plugin = QualityPlugin.__new__(QualityPlugin)
        with patch('couchpotato.core.plugins.quality.main.get_db', return_value=db):
            return plugin.single('does-not-exist-in-db')
    finally:
        db.close()


# --- Driver -------------------------------------------------------------

def _call(searcher, nzb, media, quality, retention=0, overrides=None,
          calls=None, **kwargs):
    """Drive correctRelease with fireEvent/Env patched, mirroring the
    established pattern in test_search_releases_list_only.py's _drive().

    correctRelease delegates several sub-checks (correct_words, correct_3d,
    contains_other_quality, correct_name, correct_year, get_search_title) to
    OTHER plugins via fireEvent; those plugins have their own tests. Here
    they are stubbed so this file exercises correctRelease's OWN gating
    logic (retention, quality-falsy guard, size bounds, verdict routing) in
    isolation.

    Any event name that is neither overridden nor in the defaults below
    raises AssertionError instead of silently returning a MagicMock. This is
    the load-bearing guard for the falsy-quality fix: if a future edit
    reintroduces a DB-resolution fallback (e.g. `quality.get('identifier')`
    -> `fireEvent('quality.single', identifier=None, ...)`), this stub
    catches it loudly instead of letting a real, key-ignoring adapter hand
    back the wrong quality's gates silently.
    """
    overrides = overrides or {}
    record = calls if calls is not None else []

    defaults = {
        'searcher.get_search_title': lambda *a, **k: 'Some Movie',
        'searcher.correct_words': lambda *a, **k: True,
        'searcher.contains_other_quality': lambda *a, **k: False,
        'searcher.correct_3d': lambda *a, **k: True,
        'searcher.correct_name': lambda *a, **k: True,
        'searcher.correct_year': lambda *a, **k: True,
    }

    def fake_fire_event(name, *args, **kw):
        record.append(name)
        if name in overrides:
            handler = overrides[name]
            return handler(*args, **kw) if callable(handler) else handler
        if name in defaults:
            return defaults[name](*args, **kw)
        raise AssertionError(
            "correctRelease fired an unexpected event %r with args=%r "
            "kwargs=%r -- if this is 'quality.single', the DB-resolution "
            "fallback the falsy-quality fix removed has come back." %
            (name, args, kw)
        )

    env = MagicMock()
    env.setting.return_value = retention

    with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event), \
            patch('couchpotato.core.media.movie.searcher.Env', env):
        return searcher.correctRelease(nzb=nzb, media=media, quality=quality, **kwargs)


# --- AC-DATA-18 / AC-QA-29: falsy quality never resolves from the DB ----

class TestFalsyQualityNeverResolvesFromDB:

    @pytest.mark.parametrize('quality_value', [None, {}, False], ids=['none', 'empty_dict', 'false'])
    def test_returns_false_without_querying_the_database(self, searcher, caplog, quality_value):
        nzb = _nzb()
        media = _media()

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            calls = []
            result = _call(searcher, nzb, media, quality_value, calls=calls)

        assert result is False
        # 'quality.single' must never fire for a falsy quality -- that is
        # exactly the trap (db.get('quality', None) returns the first row,
        # 'cam', instead of raising).
        assert 'quality.single' not in calls
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert any('quality' in msg.lower() for msg in reasons), reasons


# --- AC-QA-30: the crash sites made reachable by fixing (1) above -------

class TestFallbackPathDoesNotRaise:

    def test_correct_3d_false_with_quality_missing_custom_does_not_raise(self, searcher, tmp_path, caplog):
        """A quality dict shaped exactly like QualityPlugin.single()'s real
        output (no 'custom' key -- that is grafted on by the caller at
        searcher.py:326, after single() returns) must not KeyError at :429
        when the 3D check fails."""
        quality = _real_quality(tmp_path, 'q3d', 'dvdrip', 600, 2400)
        assert 'custom' not in quality  # sanity: proves this is the real shape

        nzb = _nzb(size=1500)
        media = _media()
        overrides = {'searcher.correct_3d': lambda *a, **k: False}

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            result = _call(searcher, nzb, media, quality, overrides=overrides)

        assert result is False
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert any('3D' in msg for msg in reasons), reasons

    def test_unresolvable_identifier_returns_false_without_raising(self, searcher, tmp_path, caplog):
        """single() on an identifier with no DB row returns {} (the real
        boundary behaviour, not a hand-rolled {}). That is falsy, so it must
        take the AC-DATA-18 path: False, logged reason, no DB re-resolution."""
        quality = _unresolvable_quality(tmp_path, 'qmissing')
        assert quality == {}

        nzb = _nzb()
        media = _media()

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            calls = []
            result = _call(searcher, nzb, media, quality, calls=calls)

        assert result is False
        assert 'quality.single' not in calls


class TestSizeBoundsGuardedAgainstAPartialDoc:

    def test_quality_doc_missing_size_bounds_does_not_raise(self, searcher, tmp_path):
        """:433/:438 defensive guard: a truthy, real quality dict that is
        missing size_min/size_max (a corrupted/partial doc -- every doc
        QualityPlugin.fill() writes has both) must not KeyError. It is
        rejected rather than silently accepted: 0MB is never a real file."""
        quality = _real_quality_missing_size(tmp_path, 'qpartial', 'dvdrip')
        assert 'size_min' not in quality and 'size_max' not in quality

        nzb = _nzb(size=1500)
        media = _media()

        result = _call(searcher, nzb, media, quality)

        assert result is False


# --- AC-QA-23: happy path ------------------------------------------------

class TestHappyPath:

    def test_matching_release_via_imdb_link_is_accepted(self, searcher, tmp_path):
        media = _media(imdb='tt1234567')
        nzb = _nzb(description='http://example.com/title/tt1234567/', size=5000)
        quality = _real_quality(tmp_path, 'happy', '1080p', 3000, 10000)

        result = _call(searcher, nzb, media, quality)

        assert result is True


# --- AC-QA-24 / AC-DATA-19: wrong quality, two fixtures, reason via caplog

class TestWrongQualityRejected:

    def test_wrong_quality_is_rejected_with_reason(self, searcher, tmp_path, caplog):
        """Two fixtures differing only in the key under test (the
        'contains_other_quality' verdict): identical nzb/media/quality
        otherwise, so the outcome can only be tracking that one signal."""
        media = _media()
        nzb = _nzb(size=5000)
        quality = _real_quality(tmp_path, 'wq', '1080p', 3000, 10000)

        accepted = _call(searcher, nzb, media, quality,
                          overrides={'searcher.contains_other_quality': lambda *a, **k: False})
        assert accepted is True

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            rejected = _call(searcher, nzb, media, quality,
                              overrides={'searcher.contains_other_quality': lambda *a, **k: {'720p': {}}})
        assert rejected is False
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert any('Wrong' in msg and quality['label'] in msg for msg in reasons), reasons


# --- AC-QA-25: banned words -----------------------------------------------

class TestBannedWordsRejected:

    def test_banned_word_is_rejected_before_any_quality_check(self, searcher, tmp_path):
        """correct_words has no log.info2 call of its own (searcher.py:416-417),
        so the reason is proven by call sequence instead of caplog: the word
        gate fires and returns False before any later gate (contains_other_quality
        is not in `defaults`/`overrides`, so if it fired the stub would raise)."""
        media = _media()
        nzb = _nzb(size=5000)
        quality = _real_quality(tmp_path, 'words', '1080p', 3000, 10000)
        calls = []

        result = _call(searcher, nzb, media, quality,
                        overrides={'searcher.correct_words': lambda *a, **k: False},
                        calls=calls)

        assert result is False
        assert calls == ['searcher.get_search_title', 'searcher.correct_words']


# --- AC-QA-26 / AC-DATA-19: size gates -------------------------------------

class TestSizeGates:

    def test_below_size_min_is_rejected(self, searcher, tmp_path, caplog):
        """Two quality fixtures differing ONLY in size_min, same nzb size:
        proves the gate reads THIS fixture's size_min, not a fixed/ignored
        value."""
        media = _media()
        nzb = _nzb(size=5000)
        permissive = _real_quality(tmp_path, 'smin_ok', 'dvdrip', 1000, 9000)
        strict = _real_quality(tmp_path, 'smin_bad', 'dvdrip', 6000, 9000)

        accepted = _call(searcher, nzb, media, permissive)
        assert accepted is True

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            rejected = _call(searcher, nzb, media, strict)
        assert rejected is False
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert any('too small' in msg for msg in reasons), reasons

    def test_above_size_max_is_rejected(self, searcher, tmp_path, caplog):
        """Two quality fixtures differing ONLY in size_max, same nzb size."""
        media = _media()
        nzb = _nzb(size=10000)
        permissive = _real_quality(tmp_path, 'smax_ok', 'dvdrip', 100, 20000)
        strict = _real_quality(tmp_path, 'smax_bad', 'dvdrip', 100, 6000)

        accepted = _call(searcher, nzb, media, permissive)
        assert accepted is True

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            rejected = _call(searcher, nzb, media, strict)
        assert rejected is False
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert any('too large' in msg for msg in reasons), reasons

    def test_zero_size_is_not_rejected(self, searcher, tmp_path):
        """size == 0 means 'unknown', not 'zero bytes' -- must NOT be
        rejected, even against tightly-bounded quality (proves the bypass
        genuinely ignores the bounds rather than coincidentally fitting)."""
        media = _media()
        nzb = _nzb(size=0)
        narrow = _real_quality(tmp_path, 'zero_size', 'dvdrip', 99999, 100000)

        result = _call(searcher, nzb, media, narrow)

        assert result is True


# --- AC-QA-27 / AC-DATA-19: retention --------------------------------------

class TestRetention:

    def test_age_over_retention_is_rejected(self, searcher, tmp_path, caplog):
        media = _media()
        nzb = _nzb(seeders=None, age=999)
        quality = _real_quality(tmp_path, 'ret_over', '1080p', 3000, 10000)

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            result = _call(searcher, nzb, media, quality, retention=10)

        assert result is False
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert any('retention' in msg.lower() for msg in reasons), reasons

    def test_age_equal_retention_is_not_rejected(self, searcher, tmp_path, caplog):
        """The boundary at :411 is strict (`retention < age`), so age ==
        retention must NOT be rejected. Two nzb fixtures differing only in
        'age' (10 vs 11) against the same retention (10)."""
        media = _media()
        quality = _real_quality(tmp_path, 'ret_boundary', '1080p', 3000, 10000)

        at_boundary = _nzb(seeders=None, age=10, size=5000)
        over_boundary = _nzb(seeders=None, age=11, size=5000)

        accepted = _call(searcher, at_boundary, media, quality, retention=10)
        assert accepted is True

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            rejected = _call(searcher, over_boundary, media, quality, retention=10)
        assert rejected is False
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert any('retention' in msg.lower() for msg in reasons), reasons

    def test_torrent_with_seeders_is_never_retention_rejected(self, searcher, tmp_path, caplog):
        """seeders is not None => the retention branch is skipped entirely,
        no matter how old. A huge age that would reject an NZB must pass
        clean through for a torrent."""
        media = _media()
        nzb = _nzb(seeders=5, age=999999, size=5000)
        quality = _real_quality(tmp_path, 'ret_torrent', '1080p', 3000, 10000)

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            result = _call(searcher, nzb, media, quality, retention=10)

        assert result is True
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert not any('retention' in msg.lower() for msg in reasons), reasons


# --- AC-QA-28: non-movie media returns None, not False ---------------------

class TestMediaTypeGuard:

    def test_non_movie_media_returns_none_not_false(self, searcher):
        """providers/base.py:361-370 does `if is_correct:` then
        `float(is_correct)` -- None and False both skip the release, but
        only False is a real verdict. float(None) would raise, so the
        distinction is load-bearing, not cosmetic."""
        media = _media(media_type='show')

        result = searcher.correctRelease(nzb=_nzb(), media=media, quality={'identifier': '1080p'})

        assert result is None
        assert result is not False


# --- AC-QA-31: extra_check --------------------------------------------------

class TestExtraCheck:

    def test_extra_check_false_rejects(self, searcher, tmp_path):
        check = MagicMock(return_value=False)
        media = _media()
        nzb = _nzb(size=5000, extra_check=check)
        quality = _real_quality(tmp_path, 'extra', '1080p', 3000, 10000)

        result = _call(searcher, nzb, media, quality)

        assert result is False
        check.assert_called_once_with(nzb)


# --- AC-QA-32: title/year matching -----------------------------------------

class TestTitleYearMatching:

    def test_title_and_year_match_returns_true(self, searcher, tmp_path):
        """No IMDB link in the description, so correctRelease must fall
        through to the title/year loop and rely on the real correct_name/
        correct_year events (stubbed True here as the collaborators under
        test elsewhere) to reach a verdict."""
        media = _media(imdb='tt7654321', titles=['Some Movie'], year=2020)
        nzb = _nzb(name='Some.Movie.2020.1080p.BluRay.x264-GROUP',
                   description='no imdb id in here', size=5000)
        quality = _real_quality(tmp_path, 'title', '1080p', 3000, 10000)

        result = _call(searcher, nzb, media, quality)

        assert result is True

    def test_title_mismatch_returns_false(self, searcher, tmp_path, caplog):
        media = _media(imdb='tt7654321', titles=['Some Movie'], year=2020)
        nzb = _nzb(name='Completely.Different.Thing.2020.1080p',
                   description='no imdb id in here', size=5000)
        quality = _real_quality(tmp_path, 'title_miss', '1080p', 3000, 10000)

        with caplog.at_level(logging.INFO, logger=SEARCHER_LOGGER):
            result = _call(searcher, nzb, media, quality,
                            overrides={'searcher.correct_name': lambda *a, **k: False})

        assert result is False
        assert any('undetermined naming' in r.getMessage() for r in caplog.records)


# --- AC-QA-33: media=None is pinned, not fixed (outside AC-SIMP-1 scope) --

class TestMediaNoneIsPinnedNotFixed:

    def test_media_none_raises_attributeerror(self, searcher):
        """This IS today's (and, deliberately, tomorrow's) behaviour: :419/
        :429/:433 is this task's scope (AC-SIMP-1); media=None crashes one
        line earlier, at :404, and is out of scope. Pinned so a future
        change to this line is a deliberate decision, not an accident."""
        with pytest.raises(AttributeError):
            searcher.correctRelease(nzb=_nzb(), media=None, quality={'identifier': '1080p'})


# --- AC-SEC-13: gates that reject today still reject after the fix --------

class TestSecurityRegressionStillRejects:
    """The quality, word and size gates are exercised (with their rejection
    reasons asserted) by TestWrongQualityRejected, TestBannedWordsRejected
    and TestSizeGates above -- this class exists so AC-SEC-13 has a named
    home, not to duplicate those assertions. correctRelease is the only
    filter between indexer-supplied metadata and a queued download; the
    fix touches the crash paths (falsy quality, missing 'custom'/size
    keys), not this gating logic, and these tests are the proof it still
    rejects what it rejected before."""

    def test_quality_word_and_size_gates_all_still_reject(self, searcher, tmp_path, caplog):
        media = _media()
        quality = _real_quality(tmp_path, 'sec13', '1080p', 3000, 10000)

        with caplog.at_level(INFO2, logger=SEARCHER_LOGGER):
            wrong_quality = _call(
                searcher, _nzb(size=5000), media, quality,
                overrides={'searcher.contains_other_quality': lambda *a, **k: {'720p': {}}},
            )
            too_small = _call(searcher, _nzb(size=1000), media, quality)
            too_large = _call(searcher, _nzb(size=50000), media, quality)

        calls = []
        wrong_word = _call(
            searcher, _nzb(size=5000), media, quality,
            overrides={'searcher.correct_words': lambda *a, **k: False},
            calls=calls,
        )

        assert wrong_quality is False
        assert too_small is False
        assert too_large is False
        assert wrong_word is False
        reasons = [r.getMessage() for r in caplog.records if r.levelno == INFO2]
        assert any('Wrong' in msg for msg in reasons)
        assert any('too small' in msg for msg in reasons)
        assert any('too large' in msg for msg in reasons)
