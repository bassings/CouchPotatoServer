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

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "libs"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import seed_e2e_data  # noqa: E402


def _resolved(path):
    """`_REPO_ROOT` is realpath'd in the module, so a fake root must be too.

    `_is_safe_seed_target` realpaths the candidate and compares it against
    `_REPO_ROOT`. On macOS `tmp_path` sits under a symlinked `/var`, so an
    unresolved fake root makes every one of these tests compare a resolved
    path against an unresolved prefix and report the wrong answer.
    """
    return os.path.realpath(str(path))


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

    def test_a_non_empty_e2e_named_directory_under_the_repo_is_safe(self, tmp_path, monkeypatch):
        """The normal local dev loop: re-running the seed script against an
        already-seeded (non-empty) .e2e-data must keep working -- the script
        is idempotent by design (fixed _ids, see `_upsert`).
        """
        # Built under tmp_path, not under the real checkout. These fixtures
        # used to be created in REPO_ROOT itself and removed in a `finally`,
        # which a SIGKILL or a hard timeout skips: the unit suite could leave
        # `.e2e-guard-test-data/` behind in someone's working tree. The
        # monkeypatch was already here; only the value it points at changed.
        fake_root = _resolved(tmp_path)
        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", fake_root)
        target = tmp_path / ".e2e-guard-test-data"
        (target / "database_v2").mkdir(parents=True)

        assert seed_e2e_data._is_safe_seed_target(str(target)) is True

    def test_a_non_empty_dot_config_under_the_repo_is_accepted_by_name(self, tmp_path, monkeypatch):
        """Documents the guard's accepted residual risk: `.config` under the
        repo is allowed by name/location even when non-empty, because it is
        ALSO the conventional dev data dir name and re-seeding into one a
        developer is deliberately using for E2E work must keep working. This
        guard stops an arbitrary/real library PATH, not a correctly-named
        directory that happens to hold real data -- see
        _is_safe_seed_target's docstring.
        """
        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", _resolved(tmp_path))
        target = tmp_path / ".config"
        target.mkdir()
        (target / "marker").write_text("x")

        assert seed_e2e_data._is_safe_seed_target(str(target)) is True

    def test_a_non_empty_e2e_named_directory_outside_the_repo_is_refused(self, tmp_path, monkeypatch):
        """The name alone isn't enough -- it must also resolve under this
        repo's root, so an unrelated `.e2e-something` directory elsewhere on
        disk (a coincidence, or a copy-pasted path from a different project)
        isn't treated as ours.
        """
        fake_root = tmp_path / "checkout"
        fake_root.mkdir()
        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", _resolved(fake_root))
        outside = tmp_path / ".e2e-elsewhere"
        outside.mkdir()
        (outside / "marker").write_text("x")

        assert seed_e2e_data._is_safe_seed_target(str(outside)) is False

    def test_a_symlinked_e2e_name_pointing_at_a_real_library_is_refused(self, tmp_path, monkeypatch):
        """The name/location check resolves symlinks.

        A `.e2e-*` entry inside the repo that is a SYMLINK to a populated
        directory elsewhere passed this guard while it used `abspath`, which
        does not follow links: basename said `.e2e-...`, and the unresolved
        path did start with the repo root. `e2e_worker_data.py`'s delete-side
        guard already resolved symlinks and refused the same path, so the two
        checks either side of one computed path disagreed -- and the one that
        disagreed in the permissive direction is the one that writes.

        The stand-in here is deliberately populated with a settings file: the
        realistic shape is a link left pointing at a real data dir, not an
        empty directory (an empty one is safe by the earlier branch anyway,
        which is why the fixture must not be empty for this to mean anything).
        """
        fake_root = tmp_path / "checkout"
        fake_root.mkdir()
        monkeypatch.setattr(seed_e2e_data, "_REPO_ROOT", _resolved(fake_root))

        real_library = tmp_path / "real-library"
        real_library.mkdir()
        (real_library / "config.ini").write_text("[core]\napi_key = live\n")

        link = fake_root / ".e2e-symlink-guard-test"
        link.symlink_to(real_library, target_is_directory=True)

        assert seed_e2e_data._is_safe_seed_target(str(link)) is False


class TestBindToLoopback:
    """The seeded server must not be reachable from the LAN.

    `runner.py` reads `Env.setting('host', default='0.0.0.0')`, there is no
    `host` in the settings list and no CLI flag for it, so a freshly seeded
    data dir always resolves to the wildcard address. Under per-worker
    isolation that is not one listener: a `--workers=4` run opens four
    unauthenticated CouchPotato instances on 5150-5153, each with its own
    generated api_key and no password (`get_current_user` returns True when
    neither is set), all reachable from the network.

    Fixed in the seed script rather than by adding a `--host` argument,
    because AC-SEC-16 exists to stop `--port` widening exposure and solving
    this by widening the CLI would defeat the criterion it satisfies.
    """

    def _host(self, data_dir):
        import configparser

        parser = configparser.RawConfigParser()
        parser.read(str(data_dir / "config.ini"), encoding="utf-8")
        return parser.get("core", "host", fallback=None)

    def _e2e_dir(self, tmp_path):
        """A `.e2e*`-named dir: the pin is scoped to the disposable convention."""
        d = tmp_path / ".e2e-w0-data"
        d.mkdir()
        return d

    def test_a_fresh_data_dir_is_pinned_to_loopback(self, tmp_path):
        d = self._e2e_dir(tmp_path)
        assert seed_e2e_data._bind_to_loopback(str(d)) is True
        assert self._host(d) == "127.0.0.1"

    def test_seed_actually_calls_it(self, tmp_path):
        """The wiring, not the helper.

        Two review lenses independently deleted `_bind_to_loopback(data_dir)`
        from `seed()` and ran the whole suite: 2013 and 2108 tests passed,
        nothing failed. Every other test in this class calls the helper
        directly, so they proved it works and nothing proved it is called --
        the same shape as the criterion it exists to satisfy. AC-SEC-16
        guarded the argument instead of the exposure; AC-SEC-16b was written
        to fix that and then guarded the helper instead of the call site.

        This is the assertion that reddens when the line is removed, so the
        exposure it closes cannot be silently reopened by a refactor of
        `seed()`.
        """
        d = self._e2e_dir(tmp_path)

        seed_e2e_data.seed(str(d))

        assert self._host(d) == "127.0.0.1", (
            "seed() must pin the host before the server can be started -- "
            "without it every worker binds 0.0.0.0 with a generated api_key "
            "and no password"
        )

    def test_it_declines_outside_the_disposable_naming_convention(self, tmp_path):
        """`_is_safe_seed_target` accepts a developer's own populated
        `.config`, and its residual-risk note is about seeding fixture ROWS.
        Writing a settings value into a real local instance is a different and
        larger thing: settings are on the irreplaceable tier, and the operator
        would find their instance stopped answering on the LAN after the next
        restart with nothing printed to say why.
        """
        real = tmp_path / ".config"
        real.mkdir()
        (real / "config.ini").write_text(
            "[core]\nport = 5050\napi_key = live-key\n", encoding="utf-8",
        )

        assert seed_e2e_data._bind_to_loopback(str(real)) is False
        assert self._host(real) is None, "a real .config must be left alone"

    def test_it_never_clobbers_a_host_the_operator_already_set(self, tmp_path):
        """Idempotent and non-destructive.

        The seed script runs before every worker starts, so it must be safe to
        re-run. It also must not overwrite a deliberate choice: someone driving
        the suite against a data dir they configured themselves owns that
        value, and silently rewriting settings is the behaviour this repo
        treats as data loss, not as a fix.
        """
        d = self._e2e_dir(tmp_path)
        (d / "config.ini").write_text(
            "[core]\nhost = 192.168.1.50\n", encoding="utf-8",
        )

        assert seed_e2e_data._bind_to_loopback(str(d)) is False
        assert self._host(d) == "192.168.1.50"

    def test_it_leaves_other_settings_alone(self, tmp_path):
        """The rewrite goes through configparser, so unrelated keys survive."""
        d = self._e2e_dir(tmp_path)
        (d / "config.ini").write_text(
            "[core]\nport = 5150\napi_key = seeded-key\n", encoding="utf-8",
        )

        assert seed_e2e_data._bind_to_loopback(str(d)) is True

        import configparser

        parser = configparser.RawConfigParser()
        parser.read(str(d / "config.ini"), encoding="utf-8")
        assert parser.get("core", "host") == "127.0.0.1"
        assert parser.get("core", "port") == "5150"
        assert parser.get("core", "api_key") == "seeded-key"


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
