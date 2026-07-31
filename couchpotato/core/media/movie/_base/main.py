import calendar
import sqlite3
import traceback
import time

from CodernityDB.database import RecordDeleted, RecordNotFound
from couchpotato import get_db
from couchpotato.api import addApiView
from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.core.event import fireEvent, fireEventAsync, addEvent
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.variable import splitString, getTitle, getImdb, getIdentifier
from couchpotato.core.logger import CPLog
from couchpotato.core.media.movie import MovieTypeBase
from couchpotato.core.media_lock import media_lock


log = CPLog(__name__)


def releaseDatesFromInfo(info):
    """Derive the ETA mapping from the release date the info provider already
    stored on the movie document.

    BUG-017: `movie.info.release_date` has no handler anywhere, so the
    mapping the ETA gate reads was always empty and the gate never held
    anything back. The date itself was always present -- the TMDB provider
    writes TMDB's `release_date` to `info['released']`.

    Returns ``{'theater': <utc epoch>, 'dvd': 0}``, or ``{}`` when nothing
    usable is there. `dvd` is deliberately left unknown rather than guessed:
    a fabricated dvd date would unlock the "4 weeks before dvd" early-download
    path in couldBeReleased().
    """
    if not isinstance(info, dict):
        return {}

    released = info.get('released')
    if not isinstance(released, str):
        return {}

    # `str(movie.get('release_date'))` in the TMDB provider turns a missing
    # date into the literal 'None', which is truthy -- reject it explicitly.
    released = released.strip()
    if not released or released.lower() == 'none':
        return {}

    # Some providers append a time component; the date part is what we want.
    date_part = released.split(' ')[0].split('T')[0]

    try:
        year, month, day = (int(x) for x in date_part.split('-'))
    except (ValueError, TypeError, AttributeError):
        return {}

    # Reject impossible dates. timegm() NORMALISES them silently rather than
    # raising -- 2026-02-30 becomes 2026-03-02 -- and a quietly shifted
    # unlock date is worse than a rejected one because nothing surfaces it.
    # monthrange, not `day <= 31`, so Feb 30 and Apr 31 are caught too.
    #
    # The year bound comes first: monthrange() and timegm() both raise
    # ValueError above 9999 ("year must be in 1..9999"), and this function
    # promises never to raise -- a provider returning a nonsense year must
    # degrade to "unknown", not throw once per movie into the search loop.
    if not 1 <= year <= 9999:
        return {}
    if not 1 <= month <= 12:
        return {}
    if not 1 <= day <= calendar.monthrange(year, month)[1]:
        return {}

    # Anything before the epoch is treated as unknown rather than derived.
    # TMDB uses 1900-01-01 to mean "no release date" -- themoviedb.py already
    # nulls `year` for it ("1900 is the same as None") but still writes the
    # placeholder to `released`. Taking it literally would reopen BUG-017:
    # a negative epoch is couldBeReleased()'s pre-1972 "definitely out"
    # sentinel, so an unknown date would authorise an immediate download.
    # Genuinely old films lose nothing -- an old `year` routes them to the
    # "old movie, no dates" heuristic, which already assumes released.
    if year < 1970:
        return {}

    # timegm, not mktime: the gate compares against int(time.time()), which
    # is UTC, so a local-time parse would shift the unlock by up to a day
    # depending on the server's timezone.
    theater = calendar.timegm((year, month, day, 0, 0, 0, 0, 0, 0))

    return {'theater': theater, 'dvd': 0}


class MovieBase(MovieTypeBase):

    _type = 'movie'

    def __init__(self):

        # Initialize this type
        super().__init__()
        self.initType()

        addApiView('movie.add', self.addView, docs = {
            'desc': 'Add new movie to the wanted list',
            'return': {'type': 'object', 'example': """{
    'success': True,
    'movie': object
}"""},
            'params': {
                'identifier': {'desc': 'IMDB id of the movie your want to add.'},
                'profile_id': {'desc': 'ID of quality profile you want the add the movie in. If empty will use the default profile.'},
                'force_readd': {'desc': 'Force re-add even if movie already in wanted or manage. Default: True'},
                'category_id': {'desc': 'ID of category you want the add the movie in. If empty will use no category.'},
                'title': {'desc': 'Movie title to use for searches. Has to be one of the titles returned by movie.search.'},
            }
        })
        addApiView('movie.edit', self.edit, docs = {
            'desc': 'Add new movie to the wanted list',
            'params': {
                'id': {'desc': 'Movie ID(s) you want to edit.', 'type': 'int (comma separated)'},
                'profile_id': {'desc': 'ID of quality profile you want the edit the movie to.'},
                'category_id': {'desc': 'ID of category you want the add the movie in. If empty will use no category.'},
                'default_title': {'desc': 'Movie title to use for searches. Has to be one of the titles returned by movie.search.'},
            }
        })

        addApiView('movie.restore_to_wanted', self.restoreToWantedView, docs = {
            'desc': "FEAT-008: move a 'done' movie back to 'active' (wanted) "
                    "without losing its release history -- today the only "
                    "route back is delete + re-add. Always ensures the movie "
                    "has a real, resolvable profile (the caller's profile_id, "
                    "else the movie's existing one, else the default) before "
                    "writing 'active', and refuses rather than create a "
                    "Wanted entry the searcher can never pick up.",
            'params': {
                'media_id': {'desc': 'The id of the media'},
                'profile_id': {'desc': 'Optional profile id to assign. Defaults to the '
                                        "movie's existing profile, then the default profile."},
            },
        })

        addEvent('movie.add', self.add)
        addEvent('movie.update', self.update)
        addEvent('movie.update_release_dates', self.updateReleaseDate)
        addEvent('movie.restore_to_wanted', self.restoreToWanted)

    def existingProfileId(self, db, m):
        """Return the media doc's current profile_id if it still resolves to a
        real profile, else None.

        Used by add() to preserve an existing (or just-inserted-by-the-race-
        winner) movie's profile across a force_readd instead of overwriting it
        with this call's params/default. Called from BOTH the genuine 'found'
        branch and the IntegrityError race-loss re-fetch branch so race
        recovery behaves identically to a real found re-add.
        """
        try:
            db.get('id', m.get('profile_id'))
            return m.get('profile_id')
        except (RecordNotFound, KeyError):
            return None
        except Exception:
            log.error('Failed getting previous profile: %s', traceback.format_exc())
            return None

    def restoreToWantedView(self, media_id = None, **kwargs):
        return self.restoreToWanted(media_id, profile_id = kwargs.get('profile_id'))

    def restoreToWanted(self, media_id, profile_id = None):
        """FEAT-008: move a movie back to 'active' (wanted) without losing its
        release history -- today the only route back from 'done' is deleting
        and re-adding the movie, which throws that history away.

        The same profile_id=None fact that broke "Search for releases"
        (searcher.py:172, this feature's other half) matters here too: a
        movie moved to wanted with no profile is unsearchable -- it would sit
        in Wanted forever, and single()'s own gate would skip it right back
        out. So this always ensures a real, resolvable profile before writing
        'active' -- preferring, in order, the caller's profile_id, the
        movie's existing one (only if it still resolves to a real profile --
        a stale/deleted reference is not trusted), then the default profile
        -- and refuses (AC2) rather than create an unsearchable entry.

        Releases are never touched: only `status`/`profile_id` change, so a
        'done' release survives exactly as AC3 requires.
        """
        if not media_id:
            return {'success': False, 'error': 'No media_id given'}

        try:
            db = get_db()

            try:
                media = db.get('id', media_id)
            except (RecordNotFound, KeyError):
                return {'success': False, 'error': 'Media not found'}

            # AC4: idempotent -- calling this on an already-active movie is a
            # no-op success (no profile resolution, no write) rather than an
            # error, so a UI that doesn't track local state precisely can
            # call it freely.
            if media.get('status') == 'active':
                return {'success': True, 'media': media}

            resolved_profile_id = (
                self.existingProfileId(db, {'profile_id': profile_id})
                or self.existingProfileId(db, media)
            )

            if not resolved_profile_id:
                default_profile = fireEvent('profile.default', single = True)
                resolved_profile_id = default_profile.get('_id') if default_profile else None

            if not resolved_profile_id:
                # AC2: refuse rather than create an unsearchable Wanted entry.
                return {
                    'success': False,
                    'error': 'No quality profile is available -- create one before '
                              'restoring this movie to wanted',
                }

            # CAS mutator, mirroring markDone/markFailedAndResearch: re-checks
            # the status-guard against the freshly re-read doc on every retry
            # (not just the pre-check above), so a concurrent write that beat
            # us to 'active' between our read and our write is a no-op, not a
            # clobber.
            def _restore(m):
                if m.get('status') == 'active':
                    return False
                m['status'] = 'active'
                m['profile_id'] = resolved_profile_id

            try:
                updated = db.update_with_retry(_restore, media_id)
            except (RecordNotFound, RecordDeleted, KeyError):
                return {'success': False, 'error': 'Media not found'}
            except ConflictError:
                log.warning('Gave up restoring media %s to wanted after retries due to persistent contention', media_id)
                return {'success': False, 'error': 'Database busy, please retry'}

            # None means the mutator's CAS re-check found the movie already
            # active on a retry (lost the race to another writer) -- still a
            # success, just nothing further to report beyond the movie as-is.
            media = updated or media

            fireEvent('media.tag', media_id, 'recent', update_edited = True, single = True)
            fireEvent('notify.frontend', type = 'movie.update', data = media)

            return {'success': True, 'media': media}
        except Exception:
            log.error('Failed restoring media %s to wanted: %s', media_id, traceback.format_exc())
            return {'success': False, 'error': 'Unexpected error'}

    def add(self, params = None, force_readd = True, search_after = True, update_after = True, notify_after = True, status = None):
        if not params: params = {}

        # Make sure it's a correct zero filled imdb id
        params['identifier'] = getImdb(params.get('identifier', ''))

        if not params.get('identifier'):
            msg = 'Can\'t add movie without imdb identifier.'
            log.error(msg)
            fireEvent('notify.frontend', type = 'movie.is_tvshow', message = msg)
            return False
        elif not params.get('info'):
            try:
                is_movie = fireEvent('movie.is_movie', identifier = params.get('identifier'), adding = True, single = True)
                if not is_movie:
                    msg = 'Can\'t add movie, seems to be a TV show.'
                    log.error(msg)
                    fireEvent('notify.frontend', type = 'movie.is_tvshow', message = msg)
                    return False
            except Exception:
                pass

        info = params.get('info')
        if not info or (info and len(info.get('titles', [])) == 0):
            info = fireEvent('movie.info', merge = True, extended = False, identifier = params.get('identifier'))

        # Allow force re-add overwrite from param
        # Tracked separately from the resolved `force_readd` bool: this records
        # whether the CALLER explicitly asked for a (re-)add via params (e.g.
        # the API's force_readd=1), as opposed to the default. Used below to
        # protect an already-completed movie from an implicit re-add (a naked
        # "Add" button click, which never sends force_readd) while still
        # honoring a deliberate, explicit one.
        # NB: "explicit" here means the caller passed force_readd through the
        # params/API surface. An INTERNAL Python caller that passes
        # force_readd=True as a keyword arg (not via params) against a
        # done/downloaded movie would still hit the no-op guard below, because
        # this only inspects params. No such caller exists today (every
        # keyword-arg caller passes force_readd=False or only runs on the
        # new-movie path), but a future contributor adding an internal
        # force-readd of a completed movie must pass it via params (or the
        # guard will silently no-op their call).
        force_readd_explicit = 'force_readd' in params
        if force_readd_explicit:
            fra = params.get('force_readd')
            force_readd = fra.lower() not in ['0', '-1'] if not isinstance(fra, bool) else fra

        # Set default title
        def_title = self.getDefaultTitle(info)

        # Default profile and category
        default_profile = {}
        if (not params.get('profile_id') and status != 'done') or params.get('ignore_previous', False):
            default_profile = fireEvent('profile.default', single = True)
        cat_id = params.get('category_id')

        try:
            db = get_db()

            media = {
                '_t': 'media',
                'type': 'movie',
                'title': def_title,
                'identifiers': {
                    'imdb': params.get('identifier')
                },
                'status': status if status else 'active',
                'profile_id': params.get('profile_id') or default_profile.get('_id'),
                'category_id': cat_id if cat_id is not None and len(cat_id) > 0 and cat_id != '-1' else None,
            }

            # Update movie info
            try: del info['in_wanted']
            except Exception: pass
            try: del info['in_library']
            except Exception: pass
            media['info'] = info

            new = False
            previous_profile = None
            previous_category = None
            identifier_key = 'imdb-%s' % params.get('identifier')

            # Serialize the get-or-insert critical section per imdb id so two
            # concurrent add()s for the same movie can't both decide "not
            # found" and both insert (REG-004: this created 77 duplicate
            # movie entries in production).
            with media_lock(identifier_key):
                try:
                    m = db.get('media', identifier_key, with_doc = True)['doc']
                    previous_profile = self.existingProfileId(db, m)
                    # NB: previous_category is deliberately NOT set here.
                    # profile_id and category_id have intentionally ASYMMETRIC
                    # genuine-found semantics (matching master): a found re-add
                    # keeps the existing profile (existing-wins, via
                    # previous_profile) but HONORS an explicitly-passed
                    # category_id (new-wins, via the else-branch below). Only
                    # the race-loss branch preserves category, to stop a losing
                    # concurrent add() from clobbering the winner's value.
                except (RecordNotFound, KeyError):
                    new = True
                    try:
                        m = db.insert(media)
                    except sqlite3.IntegrityError:
                        # Lost the race anyway (e.g. another process, not
                        # covered by our in-process lock): the unique
                        # (provider, identifier) index rejected our insert
                        # because a concurrent insert already created this
                        # movie. Re-fetch the winner's doc and preserve its
                        # profile/category -- otherwise force_readd below would
                        # stomp the winner's values with this (losing) call's
                        # params/default. previous_category is taken unvalidated
                        # (unlike previous_profile's existingProfileId check):
                        # the just-inserted winner's category is valid by
                        # construction.
                        new = False
                        m = db.get('media', identifier_key, with_doc = True)['doc']
                        previous_profile = self.existingProfileId(db, m)
                        previous_category = m.get('category_id')

            # Capture the pre-existing movie's status BEFORE m.update(media)
            # overwrites it (media['status'] defaults to 'active' above) --
            # needed by the completed-movie re-add guard below. Meaningless
            # (and unused) for a brand-new movie.
            previous_status = m.get('status')

            # Update dict to be usable
            m.update(media)

            added = True
            do_search = False
            search_after = search_after and self.conf('search_on_add', section = 'moviesearcher')
            onComplete = None

            if new:
                if search_after:
                    onComplete = self.createOnComplete(m['_id'])
                search_after = False
            elif force_readd and previous_status in ['done', 'downloaded'] and not force_readd_explicit:
                # Guard (app-wide, not just for the 'downloaded' review gate):
                # a movie that is already complete (done) or awaiting review
                # (downloaded) must not be destructively re-added by an
                # IMPLICIT force_readd -- the live "Add" buttons
                # (search_results.html, movie_info_modal.html) call movie.add
                # with no force_readd at all, defaulting True, so a single
                # stray click used to wipe the completed release(s), reset
                # profile_id/category_id/tags, and reset status to 'active'.
                # Treat this exactly like the non-force_readd no-op below:
                # don't touch releases, don't persist m (db.update is never
                # called), don't re-search. An EXPLICIT force_readd (e.g. the
                # API's force_readd=1) still falls through to the destructive
                # branch and is honored -- this only protects the default.
                log.info(
                    'Movie already complete (%s), not re-adding to protect the existing copy; '
                    'use Mark Failed & re-search to replace it', previous_status
                )
                added = False
            elif force_readd:

                # Clean snatched history
                for release in fireEvent('release.for_media', m['_id'], single = True):
                    if release.get('status') in ['downloaded', 'snatched', 'seeding', 'done']:
                        if params.get('ignore_previous', False):
                            fireEvent('release.update_status', release['_id'], status = 'ignored')
                        else:
                            fireEvent('release.delete', release['_id'], single = True)

                m['profile_id'] = (params.get('profile_id') or default_profile.get('_id')) if not previous_profile else previous_profile
                m['category_id'] = previous_category if previous_category else (cat_id if cat_id is not None and len(cat_id) > 0 else (m.get('category_id') or None))
                m['last_edit'] = int(time.time())
                m['tags'] = []

                do_search = True
                db.update(m)
            else:
                try: del params['info']
                except Exception: pass
                log.debug('Movie already exists, not updating: %s', params)
                added = False

            # Trigger update info
            if added and update_after:
                # Do full update to get images etc
                fireEventAsync('movie.update', m['_id'], default_title = params.get('title'), on_complete = onComplete)

            # Remove releases
            for rel in fireEvent('release.for_media', m['_id'], single = True):
                if rel['status'] == 'available':
                    db.delete(rel)

            movie_dict = fireEvent('media.get', m['_id'], single = True)
            if not movie_dict:
                log.debug('Failed adding media, can\'t find it anymore')
                return False

            if do_search and search_after:
                onComplete = self.createOnComplete(m['_id'])
                onComplete()

            if added and notify_after:

                if params.get('title'):
                    message = 'Successfully added "%s" to your wanted list.' % params.get('title', '')
                else:
                    title = getTitle(m)
                    if title:
                        message = 'Successfully added "%s" to your wanted list.' % title
                    else:
                        message = 'Successfully added to your wanted list.'
                fireEvent('notify.frontend', type = 'movie.added', data = movie_dict, message = message)

            return movie_dict
        except Exception:
            log.error('Failed adding media: %s', traceback.format_exc())

    def addView(self, **kwargs):
        add_dict = self.add(params = kwargs)

        return {
            'success': True if add_dict else False,
            'movie': add_dict,
        }

    def edit(self, id = '', **kwargs):

        try:
            db = get_db()

            ids = splitString(id)
            for media_id in ids:

                try:
                    m = db.get('id', media_id)
                    m['profile_id'] = kwargs.get('profile_id') or m['profile_id']

                    cat_id = kwargs.get('category_id')
                    if cat_id is not None:
                        m['category_id'] = cat_id if len(cat_id) > 0 else m['category_id']

                    # Remove releases
                    for rel in fireEvent('release.for_media', m['_id'], single = True):
                        if rel['status'] == 'available':
                            db.delete(rel)

                    # Default title
                    if kwargs.get('default_title'):
                        m['title'] = kwargs.get('default_title')

                    db.update(m)

                    fireEvent('media.restatus', m['_id'], single = True)

                    m = db.get('id', media_id)

                    movie_dict = fireEvent('media.get', m['_id'], single = True)
                    fireEventAsync('movie.searcher.single', movie_dict, on_complete = self.createNotifyFront(media_id))

                except Exception:
                    print(traceback.format_exc())
                    log.error('Can\'t edit non-existing media')

            return {
                'success': True,
            }
        except Exception:
            log.error('Failed editing media: %s', traceback.format_exc())

        return {
            'success': False,
        }

    def update(self, media_id = None, identifier = None, default_title = None, extended = False):
        """
        Update movie information inside media['doc']['info']

        @param media_id: document id
        @param default_title: default title, if empty, use first one or existing one
        @param extended: update with extended info (parses more info, actors, images from some info providers)
        @return: dict, with media
        """

        if self.shuttingDown():
            return

        lock_key = 'media.get.%s' % media_id if media_id else identifier
        self.acquireLock(lock_key)

        media = {}
        try:
            db = get_db()

            if media_id:
                media = db.get('id', media_id)
            else:
                media = db.get('media', 'imdb-%s' % identifier, with_doc = True)['doc']

            info = fireEvent('movie.info', merge = True, extended = extended, identifier = getIdentifier(media))

            # Don't need those here
            try: del info['in_wanted']
            except Exception: pass
            try: del info['in_library']
            except Exception: pass

            if not info or len(info) == 0:
                log.error('Could not update, no movie info to work with: %s', identifier)
                return False

            # Update basic info
            media['info'] = info

            titles = info.get('titles', [])
            log.debug('Adding titles: %s', titles)

            # Define default title
            if default_title or media.get('title') == 'UNKNOWN' or len(media.get('title', '')) == 0:
                media['title'] = self.getDefaultTitle(info, default_title)

            # Files
            image_urls = info.get('images', [])

            self.getPoster(media, image_urls)

            db.update(media)
        except Exception:
            log.error('Failed update media: %s', traceback.format_exc())

        self.releaseLock(lock_key)
        return media

    def updateReleaseDate(self, media_id):
        """
        Update release_date (eta) info only

        @param media_id: document id
        @return: dict, with dates dvd, theater, bluray, expires
        """

        try:
            db = get_db()

            media = db.get('id', media_id)

            if not media.get('info'):
                media = self.update(media_id)
                dates = media.get('info', {}).get('release_date')
            else:
                dates = media.get('info').get('release_date')

            # A stale `[]` may be cached here: older versions stored whatever
            # the unhandled event returned, on every search.
            if not isinstance(dates, dict):
                dates = None

            if dates and (dates.get('expires', 0) < time.time() or dates.get('expires', 0) > time.time() + (604800 * 4)) or not dates:
                fetched = fireEvent('movie.info.release_date', identifier = getIdentifier(media), merge = True)

                if isinstance(fetched, dict) and fetched:
                    dates = fetched
                    media['info'].update({'release_date': dates})
                    db.update(media)
                else:
                    # No provider implements movie.info.release_date, so this
                    # is the normal path (BUG-017). Derive from the date the
                    # info provider already stored. Not written back: it is
                    # free to recompute, and persisting it would mean a db
                    # write per movie per search cycle for no benefit.
                    dates = releaseDatesFromInfo(media.get('info') or {})

            return dates
        except Exception:
            log.error('Failed updating release dates: %s', traceback.format_exc())

        return {}
