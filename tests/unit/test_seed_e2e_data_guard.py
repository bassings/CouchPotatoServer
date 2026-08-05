"""Guard against scripts/seed_e2e_data.py being pointed at a real library.

`ci.yml` invokes the script with `--data_dir=.config`, and `.config` is also
the conventional (gitignored) name for a developer's OWN local CouchPotato
data dir -- copy-pasting that exact invocation locally, against a `.config`
that already holds a real settings/library, is the realistic mistake
`_is_safe_seed_target` exists to catch before it silently writes fixture rows
into it.

Mirrors tests/unit/test_migrate_codernity_script.py's import pattern: scripts/
is not a package, so bootstrap sys.path the same way the script itself does.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "libs"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import seed_e2e_data  # noqa: E402


class TestIsSafeSeedTarget:

    def test_a_directory_that_does_not_exist_yet_is_safe(self, tmp_path):
        """The normal CI case: a fresh checkout, nothing at --data_dir yet."""
        target = tmp_path / "brand-new"
        assert seed_e2e_data._is_safe_seed_target(str(target)) is True

    def test_an_empty_existing_directory_is_safe(self, tmp_path):
        assert seed_e2e_data._is_safe_seed_target(str(tmp_path)) is True

    def test_a_non_empty_directory_with_an_unrelated_name_is_refused(self, tmp_path):
        """The core protection: a populated, arbitrarily-named directory (a
        stand-in for a real media library / NAS mount / production data dir)
        must never be silently seeded into.
        """
        real_library = tmp_path / "my-real-movies"
        real_library.mkdir()
        (real_library / "settings.conf").write_text("this is not a fixture")

        assert seed_e2e_data._is_safe_seed_target(str(real_library)) is False

    def test_a_non_empty_e2e_named_directory_under_the_repo_is_safe(self, monkeypatch):
        """The normal local dev loop: re-running the seed script against an
        already-seeded (non-empty) .e2e-data must keep working -- the script
        is idempotent by design (fixed _ids, see `_upsert`).
        """
        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", str(REPO_ROOT))
        target = REPO_ROOT / ".e2e-guard-test-data"
        target.mkdir(exist_ok=True)
        (target / "database_v2").mkdir(exist_ok=True)
        try:
            assert seed_e2e_data._is_safe_seed_target(str(target)) is True
        finally:
            (target / "database_v2").rmdir()
            target.rmdir()

    def test_a_non_empty_dot_config_under_the_repo_is_accepted_by_name(self, monkeypatch):
        """Documents the guard's accepted residual risk: `.config` under the
        repo is allowed by name/location even when non-empty, because it is
        ALSO the conventional dev data dir name and re-seeding into one a
        developer is deliberately using for E2E work must keep working. This
        guard stops an arbitrary/real library PATH, not a correctly-named
        directory that happens to hold real data -- see
        _is_safe_seed_target's docstring.
        """
        import os

        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", str(REPO_ROOT))
        target = REPO_ROOT / ".config"
        preexisting = os.path.isdir(target)
        if not preexisting:
            target.mkdir()
            (target / "marker").write_text("x")
        try:
            assert seed_e2e_data._is_safe_seed_target(str(target)) is True
        finally:
            if not preexisting:
                (target / "marker").unlink()
                target.rmdir()

    def test_a_non_empty_e2e_named_directory_outside_the_repo_is_refused(self, tmp_path, monkeypatch):
        """The name alone isn't enough -- it must also resolve under this
        repo's root, so an unrelated `.e2e-something` directory elsewhere on
        disk (a coincidence, or a copy-pasted path from a different project)
        isn't treated as ours.
        """
        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", str(REPO_ROOT))
        outside = tmp_path / ".e2e-elsewhere"
        outside.mkdir()
        (outside / "marker").write_text("x")

        assert seed_e2e_data._is_safe_seed_target(str(outside)) is False


class TestDoneReleaseIsolation:
    """T1.7a (2026-08-05).

    `MOVIE_ID` and `DESTRUCTIVE_MOVIE_ID` used to carry an identical
    already-'done' release. The app's own `app.load` -> `searchAll` restatus
    pass (`couchpotato/core/media/_base/media/main.py::restatus`) promotes
    any 'active' movie holding a finished 'done' release straight to media
    status 'done' -- which drops it out of the Wanted page's server-side
    `status=active` query. With both movies carrying the release, a single
    run could promote both at once: measured during T1.4 at roughly 1 run in
    2, and it is exactly what made `tests/e2e/interactions.e2e.spec.ts`'s
    Wanted-grid tests fail with "no movie card in the Wanted grid".

    Fix: the already-'done' release moves onto its own dedicated movie
    (`DONE_RELEASE_MOVIE_ID`), which nothing else refers to by id, so
    `MOVIE_ID` and `DESTRUCTIVE_MOVIE_ID` can no longer self-promote via
    restatus. This pins the fixture shape directly, at the level `restatus`
    actually reads it -- not just "the E2E suite happened to pass", which a
    lucky run could satisfy either way.
    """

    def _seed_and_open(self, tmp_path):
        data_dir = str(tmp_path / "seed-fixture-data")
        seed_e2e_data.seed(data_dir)
        return seed_e2e_data._open_adapter(data_dir)

    def _releases_for(self, db, media_id):
        return [
            row['doc'] for row in db.all('id', with_doc=True)
            if row['doc'].get('_t') == 'release' and row['doc'].get('media_id') == media_id
        ]

    def test_the_wanted_page_movies_carry_no_done_release(self, tmp_path):
        db = self._seed_and_open(tmp_path)
        try:
            for movie_id in (seed_e2e_data.MOVIE_ID, seed_e2e_data.DESTRUCTIVE_MOVIE_ID):
                releases = self._releases_for(db, movie_id)
                assert releases, 'expected releases seeded for %s' % movie_id

                statuses = {r['status'] for r in releases}
                assert 'done' not in statuses, (
                    "%s carries a 'done' release -- this is exactly what let the "
                    "app's restatus pass promote it out of the Wanted page's "
                    "active query (T1.7a)" % movie_id
                )
        finally:
            db.close()

    def test_the_done_release_lives_on_its_own_dedicated_movie(self, tmp_path):
        db = self._seed_and_open(tmp_path)
        try:
            done_movie_id = seed_e2e_data.DONE_RELEASE_MOVIE_ID
            movie = db.get('id', done_movie_id)
            assert movie is not None

            releases = self._releases_for(db, done_movie_id)
            statuses = {r['status'] for r in releases}
            assert 'done' in statuses, (
                'the dedicated movie must actually carry the done release, '
                'not just exist'
            )
        finally:
            db.close()

    def test_the_done_release_movie_starts_already_done(self, tmp_path):
        """It must not rely on the app's restatus pass to get there.

        Measured (2026-08-05): seeding this movie 'active', with only its
        release carrying status 'done', leaves it 'active' -- and therefore a
        THIRD card in the Wanted grid -- for as long as it takes the app's own
        app.load -> searchAll restatus pass to notice and promote it, which is
        not deterministic within a single test run. That broke two unrelated
        assertions in interactions.e2e.spec.ts that assume exactly two
        Wanted-page cards (arrow-key card-to-card focus, and a plain
        visibility check that happened to race the promotion). Seeding the
        media doc's own status as 'done' directly removes the timing
        dependency instead of relocating it.
        """
        db = self._seed_and_open(tmp_path)
        try:
            movie = db.get('id', seed_e2e_data.DONE_RELEASE_MOVIE_ID)
            assert movie['status'] == 'done', (
                "DONE_RELEASE_MOVIE_ID must be seeded already 'done', not left "
                "'active' for the restatus pass to promote later"
            )
        finally:
            db.close()

    def test_the_done_release_movie_is_not_referenced_by_any_other_seeded_id(self, tmp_path):
        """It must be genuinely unreferenced -- if a spec ever starts
        navigating to it directly, the isolation this fixture buys stops
        meaning anything."""
        assert seed_e2e_data.DONE_RELEASE_MOVIE_ID not in (
            seed_e2e_data.MOVIE_ID, seed_e2e_data.DESTRUCTIVE_MOVIE_ID,
        )
        assert seed_e2e_data.DONE_RELEASE_IMDB_ID not in (
            seed_e2e_data.IMDB_ID, seed_e2e_data.DESTRUCTIVE_IMDB_ID,
        )


class TestWantedOnlyMovieHasNoReleases:
    """T1.9 (2026-08-05).

    couchpotato/core/plugins/release/main.py's `Release.withStatus(status,
    with_doc=False)` used to drop the `with_doc` argument when calling
    `db.get_many('release_status', s)`, so `SQLiteAdapter.get_many`'s own
    default (`with_doc=True`) always won regardless of what the caller
    asked for -- every row came back wrapped as `{'doc': {...}, '_id':
    ...}`. media/main.py's `has_releases` filter builds its set from
    `r.get('media_id')` on exactly those rows, which was always None, so
    the filter never filtered: `has_releases=False` (the Wanted page)
    matched every active movie and `has_releases=True` (the Available
    page) matched none.

    MOVIE_ID and DESTRUCTIVE_MOVIE_ID both carry releases (RELEASES,
    above), so with the filter actually working neither belongs on the
    Wanted page any more -- they belong on Available. Every E2E spec that
    navigated to '/' or '/wanted/' and grabbed "the first movie card" was
    unknowingly depending on the has_releases bug to find one of those two
    movies there.

    WANTED_MOVIE_ID is a fourth, dedicated movie seeded 'active' with NO
    releases at all, so it genuinely satisfies has_releases=False and is
    the only movie the fixed filter puts on the Wanted page. This test
    pins that invariant directly against the seeded database rather than
    trusting that the E2E suite happens to find a card.
    """

    def _seed_and_open(self, tmp_path):
        data_dir = str(tmp_path / "seed-fixture-data")
        seed_e2e_data.seed(data_dir)
        return seed_e2e_data._open_adapter(data_dir)

    def _releases_for(self, db, media_id):
        return [
            row['doc'] for row in db.all('id', with_doc=True)
            if row['doc'].get('_t') == 'release' and row['doc'].get('media_id') == media_id
        ]

    def test_wanted_movie_is_active_with_zero_releases(self, tmp_path):
        db = self._seed_and_open(tmp_path)
        try:
            movie = db.get('id', seed_e2e_data.WANTED_MOVIE_ID)
            assert movie is not None
            assert movie['status'] == 'active'

            releases = self._releases_for(db, seed_e2e_data.WANTED_MOVIE_ID)
            assert releases == [], (
                'WANTED_MOVIE_ID must carry no releases at all -- a single '
                'release of any status would make has_releases=False '
                'legitimately exclude it, which is exactly the failure mode '
                'this fixture exists to avoid'
            )
        finally:
            db.close()

    def test_wanted_movie_is_not_referenced_by_any_other_seeded_id(self, tmp_path):
        """Genuinely a fourth, distinct movie -- not an alias for one of the
        existing three."""
        assert seed_e2e_data.WANTED_MOVIE_ID not in (
            seed_e2e_data.MOVIE_ID,
            seed_e2e_data.DESTRUCTIVE_MOVIE_ID,
            seed_e2e_data.DONE_RELEASE_MOVIE_ID,
        )
        assert seed_e2e_data.WANTED_MOVIE_IMDB_ID not in (
            seed_e2e_data.IMDB_ID,
            seed_e2e_data.DESTRUCTIVE_IMDB_ID,
            seed_e2e_data.DONE_RELEASE_IMDB_ID,
        )

    def test_verify_checks_the_wanted_movie_is_active(self, tmp_path):
        """verify() (called by main() after every seed) must catch a future
        regression that leaves WANTED_MOVIE_ID in the wrong status, the same
        way it already does for the other three seeded movies."""
        data_dir = str(tmp_path / "seed-fixture-data")
        seed_e2e_data.seed(data_dir)

        db = seed_e2e_data._open_adapter(data_dir)
        try:
            db.update({**db.get('id', seed_e2e_data.WANTED_MOVIE_ID), 'status': 'done'})
        finally:
            db.close()

        problems = seed_e2e_data.verify(data_dir)
        assert any(seed_e2e_data.WANTED_MOVIE_ID in p for p in problems), (
            'verify() did not notice WANTED_MOVIE_ID was left in the wrong '
            'status: %r' % (problems,)
        )
