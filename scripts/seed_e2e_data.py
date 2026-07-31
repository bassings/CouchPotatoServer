#!/usr/bin/env python3
"""Seed a deterministic movie + releases for the E2E suite (FEAT-007 Part B).

`tests/e2e/release_controls.spec.ts` and the movie-detail case in
`tests/e2e/accessibility.a11y.spec.ts` exercise the release list's htmx
filter/sort controls -- but CI and local E2E runs always start the server
against a fresh, empty `--data_dir` (`.config` in CI), so there is no movie
in the library, let alone one with releases. Every one of those 7 tests
`test.skip()`s for that reason and never actually runs.

This script seeds exactly one movie with a handful of releases, deliberately
spanning the axes the controls filter and sort on (protocol, quality, status,
size/seeders/score/age/name), so those tests run instead of skipping.

It uses the app's own `SQLiteAdapter` (`couchpotato/core/db/sqlite_adapter.py`)
against the exact on-disk layout `couchpotato/runner.py` expects
(`<data_dir>/database_v2/couchpotato.db`) -- never hand-written SQL DDL -- so
the schema is whatever the app itself creates, and a normal server start
against the same `--data_dir` opens (not recreates) this database.

Run BEFORE starting the server (see docs at the CI call site for why):

    python scripts/seed_e2e_data.py --data_dir=.e2e-seed-data

Idempotent: every document uses a fixed `_id`, and re-running skips (does
not duplicate) anything already present.
"""
import argparse
import os
import sys
import time

# --- sys.path bootstrap -----------------------------------------------------
# Mirrors scripts/migrate_codernity_to_sqlite.py: this script must be
# runnable standalone (CI step, or a developer running it directly) without
# relying on the caller having put the repo root / libs/ on sys.path already.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_LIBS_DIR = os.path.join(_REPO_ROOT, 'libs')
for _path in (_REPO_ROOT, _LIBS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter  # noqa: E402

#: Fixed IDs -- deterministic so re-running this script is idempotent and so
#: the E2E specs (and this script's own console output) can refer to a known
#: movie/profile/release set.
PROFILE_ID = 'e2e-seed-profile-001'
MOVIE_ID = 'e2e-seed-movie-001'
IMDB_ID = 'tt9999901'

#: Two distinct qualities, both present in the seeded profile's `qualities`
#: list -- otherwise the profile-matching filter in
#: `couchpotato/ui/__init__.py::_releases_ctx` would hide them (`r.get(
#: 'quality') in profile_qualities`).
PROFILE_QUALITIES = ['2160p', '1080p', '720p']

#: Six releases spanning: protocol (nzb / torrent / torrent_magnet), quality
#: (1080p / 720p), and status (available / ignored / downloaded / snatched).
#: `size`, `score`, `age`, `info.name` are unique across every release (so
#: sort-order assertions are unambiguous); `seeders` is present only on the
#: non-nzb releases and is also unique among those.
RELEASES = [
    {
        'suffix': '1',
        'protocol': 'nzb',
        'quality': '1080p',
        'status': 'available',
        'size': 15000,
        'seeders': None,
        'score': 92.5,
        'age': 2,
        'name': 'E2E.Seed.Movie.2024.1080p.NZB.PROPER-GRP1',
    },
    {
        'suffix': '2',
        'protocol': 'torrent',
        'quality': '720p',
        'status': 'ignored',
        'size': 8200,
        'seeders': 14,
        'score': 55.0,
        'age': 30,
        'name': 'E2E.Seed.Movie.2024.720p.HDTV-GRP2',
    },
    {
        'suffix': '3',
        'protocol': 'torrent_magnet',
        'quality': '1080p',
        'status': 'available',
        'size': 21000,
        'seeders': 87,
        'score': 98.0,
        'age': 1,
        'name': 'E2E.Seed.Movie.2024.1080p.BluRay-GRP3',
    },
    # Deliberately NOT 'downloaded': that status puts the movie in the
    # manual-review gate, which renders a per-release "Mark failed" button and
    # breaks tests/e2e/movie-detail.spec.ts's "review-gate buttons are absent
    # for a non-downloaded movie" -- the seeded movie must stay a plain
    # non-downloaded movie. 'done' gives the status filter the same variety
    # without changing what the movie IS.
    {
        'suffix': '4',
        'protocol': 'torrent',
        'quality': '720p',
        'status': 'done',
        'size': 6400,
        'seeders': 3,
        'score': 40.0,
        'age': 45,
        'name': 'E2E.Seed.Movie.2024.720p.WEBRip-GRP4',
    },
    {
        'suffix': '5',
        'protocol': 'nzb',
        'quality': '1080p',
        'status': 'snatched',
        'size': 17000,
        'seeders': None,
        'score': 75.0,
        'age': 10,
        'name': 'E2E.Seed.Movie.2024.1080p.WEB-DL-GRP5',
    },
    {
        'suffix': '6',
        'protocol': 'torrent_magnet',
        'quality': '720p',
        'status': 'ignored',
        'size': 5000,
        'seeders': 1,
        'score': 20.0,
        'age': 60,
        'name': 'E2E.Seed.Movie.2024.720p.DVDRip-GRP6',
    },
]


def _sqlite_db_dir(data_dir):
    """Match couchpotato/runner.py::_open_or_create_database exactly: the
    SQLite database lives at <data_dir>/database_v2/couchpotato.db."""
    return os.path.join(data_dir, 'database_v2')


def _open_adapter(data_dir):
    """Create the database if this is a fresh data_dir, else open the
    existing one -- same branch runner.py itself takes, so a normal server
    start afterwards opens (never recreates) what this script wrote."""
    db_dir = _sqlite_db_dir(data_dir)
    db_file = os.path.join(db_dir, 'couchpotato.db')

    adapter = SQLiteAdapter()
    if os.path.isfile(db_file):
        adapter.open(db_dir)
    else:
        os.makedirs(db_dir, exist_ok=True)
        adapter.create(db_dir)
    return adapter


def _upsert(db, doc_id, doc):
    """Insert `doc` under `doc_id` if it doesn't already exist; otherwise
    leave the existing document untouched. Returns True if an insert
    happened, so callers can report what actually changed.

    This is the idempotency mechanism: every document this script writes has
    a fixed `_id`, so re-running the script is a no-op rather than a
    duplicate.
    """
    try:
        db.get('id', doc_id)
        return False
    except KeyError:
        pass

    doc = dict(doc)
    doc['_id'] = doc_id
    db.insert(doc)
    return True


def seed(data_dir):
    """Seed the profile, movie, and releases. Returns a summary dict."""
    db = _open_adapter(data_dir)
    try:
        now = time.time()
        created = {'profile': False, 'movie': False, 'releases': []}

        created['profile'] = _upsert(db, PROFILE_ID, {
            '_t': 'profile',
            'label': 'E2E Seed Profile',
            'order': 999,
            'core': False,
            'hide': False,
            'qualities': PROFILE_QUALITIES,
            'wait_for': [0, 0, 0],
            'finish': [True, True, True],
            'manual_confirmation': False,
        })

        created['movie'] = _upsert(db, MOVIE_ID, {
            '_t': 'media',
            'status': 'active',
            'title': 'E2E Seed Movie',
            'type': 'movie',
            'profile_id': PROFILE_ID,
            'category_id': None,
            'identifiers': {'imdb': IMDB_ID},
            'info': {
                'imdb': IMDB_ID,
                'titles': ['E2E Seed Movie'],
                'original_title': 'E2E Seed Movie',
                'year': 2024,
                'type': 'movie',
                'genres': ['Action'],
                'plot': 'A deterministic fixture movie seeded for E2E tests '
                        '(scripts/seed_e2e_data.py) -- not a real release.',
                'runtime': 100,
                'mpaa': None,
                'images': {
                    'poster': [], 'backdrop': [], 'poster_original': [],
                    'backdrop_original': [], 'disc_art': [], 'extra_thumbs': [],
                    'actors': {}, 'clear_art': [], 'logo': [], 'banner': [],
                    'landscape': [], 'extra_fanart': [],
                },
                'actors': [],
                'actor_roles': {},
                'via_tmdb': False,
            },
            'files': {},
            'tags': [],
            'last_edit': now,
        })

        for r in RELEASES:
            release_id = 'e2e-seed-release-%s' % r['suffix']
            info = {
                'name': r['name'],
                'protocol': r['protocol'],
                'provider': 'E2ESeedProvider',
                'size': r['size'],
                'score': r['score'],
                'age': r['age'],
            }
            if r['seeders'] is not None:
                info['seeders'] = r['seeders']

            inserted = _upsert(db, release_id, {
                '_t': 'release',
                'status': r['status'],
                'media_id': MOVIE_ID,
                'identifier': '%s.%s.%s' % (IMDB_ID, r['suffix'], r['quality']),
                'quality': r['quality'],
                'is_3d': False,
                'last_edit': now,
                'files': {},
                'info': info,
            })
            created['releases'].append((release_id, inserted))

        return created
    finally:
        db.close()


def _is_safe_seed_target(data_dir):
    """Refuse to seed into anything that isn't obviously disposable test
    data, so this can't quietly write fixture rows into a real media
    library. `ci.yml` invokes this with `--data_dir=.config`; `.config` is
    also the conventional name for a developer's OWN local CouchPotato data
    dir (it's gitignored specifically so people can run a real instance
    from a checkout), so a bare "just don't run against a populated dir"
    check isn't enough -- copy-pasting that exact CI invocation locally is
    the realistic mistake this guards against.

    Allowed:
      - the directory doesn't exist yet, or exists and is empty (a fresh CI
        checkout, or a first local run) -- nothing to clobber either way;
      - OR its name matches the disposable-test-data convention (`.e2e*` or
        exactly `.config`) AND it resolves under this repo's root -- needed
        so re-running the seed script against an already-seeded, non-empty
        `.e2e-data` (the normal local dev loop; see the docstring above)
        keeps working.

    Residual risk, accepted rather than silently overclaimed: a developer's
    OWN already-populated `.config`, used for real local testing, is -- by
    this same name/location check -- indistinguishable from disposable test
    data, and is still accepted. This stops an arbitrary or real library
    path (a NAS mount, a production data dir) from being seeded into by
    mistake; it cannot detect "this populated, correctly-named directory
    happens to hold real data" without asking the user.
    """
    path = os.path.abspath(data_dir)

    if not os.path.exists(path):
        return True
    if os.path.isdir(path) and not os.listdir(path):
        return True

    basename = os.path.basename(path.rstrip(os.sep))
    name_is_disposable = basename == '.config' or basename.startswith('.e2e')
    under_repo_root = path == _REPO_ROOT or path.startswith(_REPO_ROOT + os.sep)
    return name_is_disposable and under_repo_root


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Seed a deterministic movie + releases for the E2E suite '
                     '(FEAT-007 Part B release-list controls).',
    )
    parser.add_argument(
        '--data_dir', required=True,
        help='CouchPotato data directory (same value passed to '
             'CouchPotato.py --data_dir). The SQLite database is created/'
             'opened at <data_dir>/database_v2/couchpotato.db, matching '
             'couchpotato/runner.py exactly.',
    )
    args = parser.parse_args(argv)

    if not _is_safe_seed_target(args.data_dir):
        print(
            'ERROR: refusing to seed %r -- it already exists, is not empty, '
            'and its name/location does not look like disposable test data '
            '(an empty/absent dir, or .e2e*/.config under the repo). Point '
            '--data_dir at an empty or absent directory to avoid seeding '
            'fixture data into a real library by mistake.' % args.data_dir,
            file=sys.stderr,
        )
        return 1

    try:
        result = seed(args.data_dir)
    except Exception as exc:  # noqa: BLE001 -- report and exit non-zero, don't traceback-spam CI
        print('ERROR: failed to seed E2E data: %s' % exc, file=sys.stderr)
        return 1

    print('Seeded E2E data at %s:' % args.data_dir)
    print('  profile %s: %s' % (PROFILE_ID, 'created' if result['profile'] else 'already present'))
    print('  movie   %s (imdb %s): %s' % (
        MOVIE_ID, IMDB_ID, 'created' if result['movie'] else 'already present',
    ))
    for release_id, inserted in result['releases']:
        print('  release %s: %s' % (release_id, 'created' if inserted else 'already present'))

    return 0


if __name__ == '__main__':
    sys.exit(main())
