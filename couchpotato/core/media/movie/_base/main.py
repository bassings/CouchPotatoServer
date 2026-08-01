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
        (MovieSearcher.single's first gate, this feature's other half)
        matters here too: a
        movie moved to wanted with no profile is unsearchable -- it would sit
        in Wanted forever, and single()'s own gate would skip it right back
        out. So this always ensures a real, resolvable profile before writing
        'active' -- preferring, in order, the caller's profile_id, the
        movie's existing one (only if it still resolves to a real profile --
        a stale/deleted reference is not trusted), then the default profile
        -- and refuses (AC2) rather than create an unsearchable entry.

        Nothing is deleted, so a 'done' release survives as AC3 requires --
        but the releases the movie already HOLDS are marked 'ignored', because
        a held release still counts as satisfying the profile in both
        media.restatus and single()'s has_better_quality loop. Until both stop
        counting it the movie is not really wanted: it either bounces straight
        back out of Wanted (with a false "downloaded -- awaiting review"
        notification on a manual_confirmation profile) or sits there
        contacting no providers at all. See the AC3 section of
        specs/FEAT-008-search-feedback-and-back-to-wanted.md.
        """
        if not media_id:
            return {'success': False, 'error': 'No media_id given'}

        # Hold the per-media lock across BOTH writes.
        #
        # This method writes twice: status='active', then the held releases to
        # 'ignored'. MediaPlugin.restatus takes this same lock for its own
        # read-modify-write, so without it a concurrent restatus (the periodic
        # searchAll sweep, a rescan, another search) can land in the window
        # between them. It reads status='active' with the held release still
        # 'done', and since every profile this app creates has finish=True,
        # quality.isfinish is True -- so it finishes the movie straight back to
        # 'done', or to 'downloaded' plus a false "awaiting review"
        # notification. The restore is silently undone and this method still
        # returns success.
        #
        # media_lock uses threading.RLock, so nesting inside anything that
        # already holds it for this key is safe.
        with media_lock(media_id):
            return self._restoreToWantedLocked(media_id, profile_id)

    def _restoreToWantedLocked(self, media_id, profile_id = None):
        try:
            db = get_db()

            try:
                media = db.get('id', media_id)
            except (RecordNotFound, KeyError):
                return {'success': False, 'error': 'Media not found'}

            # The statuses this action is written for. Applied twice, on
            # purpose: once here against the doc we read, and again inside the
            # CAS mutator against the doc actually written -- update_with_retry
            # re-get()s independently, so those are different reads.
            RESTORABLE = ('done', 'downloaded', 'active')

            # AC4 (idempotence) is enforced by the CAS mutator below, which
            # returns False -- no write -- when the movie is already active
            # with a profile. There is deliberately NO early return here.
            #
            # There used to be, and it made this method a status write rather
            # than a REPAIR. "Already active" does not mean "already wanted":
            # the movie can be active while still holding a 'done' release
            # that re-finishes it through media.restatus and blocks the search
            # through single()'s has_better_quality loop. Returning early
            # skipped the release-marking below, so pressing "Move back to
            # wanted" on such a movie reported success and changed nothing --
            # indistinguishable from working, with no way to fix it.
            #
            # That state is reachable: release.add used to resurrect an
            # ignored release on any library rescan, and release.update_status
            # swallows a persistent ConflictError, so the marking can also
            # partially fail. Making every call converge on the intended state
            # is what makes this safe to press twice.

            # Scope guard, mirroring markFailedAndResearch's discipline: only
            # the statuses this feature is written for. Without it ANY status
            # was flipped to 'active' -- in practice the reachable case is a
            # 'chart' or 'suggested' entry (movie/charts/main.py), which would
            # be promoted into the wanted list by an API call that was only
            # ever meant to act on a movie you already have.
            #
            # It is NOT about 'snatched': nothing in this codebase assigns
            # media status 'snatched' -- that is a RELEASE status. An earlier
            # version of this comment (and its test) claimed the guard stopped
            # the searcher grabbing a second copy mid-download, which was
            # fiction; a movie with a snatched release has media status
            # 'active' and is short-circuited by the idempotency check above.
            #
            # 'downloaded' is included deliberately: that is the manual-review
            # gate, and sending a movie awaiting review back to wanted is a
            # reasonable thing to want.
            # 'active' is in the list because reaching here means the movie is
            # active with NO resolvable profile -- i.e. unsearchable. That is
            # the repair path the pre-check above deliberately falls through
            # to, and refusing it would reinstate the very bug this method
            # grew a profile guarantee to fix.
            if media.get('status') not in RESTORABLE:
                return {
                    'success': False,
                    'error': "Only a movie you already have can be moved back to wanted "
                              "(done, downloaded, or already wanted); this one is '%s'"
                              % media.get('status'),
                }

            # An explicit choice from the caller always wins; only the
            # fallback is re-derived per-attempt below.
            caller_profile_id = self.existingProfileId(db, {'profile_id': profile_id})
            resolved_profile_id = caller_profile_id or self.existingProfileId(db, media)
            resolved_profile = None

            if not resolved_profile_id:
                # profile.default returns the DOC, so keep it -- re-fetching by
                # id would be a second read of the same thing.
                resolved_profile = fireEvent('profile.default', single = True)
                resolved_profile_id = resolved_profile.get('_id') if resolved_profile else None

            if not resolved_profile_id:
                # AC2: refuse rather than create an unsearchable Wanted entry.
                return {
                    'success': False,
                    'error': 'No quality profile is available -- create one before '
                              'restoring this movie to wanted',
                }

            # A profile with NO qualities is unsearchable for the same reason a
            # missing one is: single() iterates profile['qualities'], so an
            # empty list contacts no provider at all. profile.save can persist
            # types=[], so this is reachable. The searcher's own pre-flight
            # (_resolvableProfileId) already refuses it; without the same check
            # here, restore reports success and leaves the movie permanently
            # active having never searched.
            if resolved_profile is None:
                try:
                    resolved_profile = db.get('id', resolved_profile_id)
                except (RecordNotFound, KeyError):
                    resolved_profile = None
            if not (resolved_profile or {}).get('qualities'):
                return {
                    'success': False,
                    'error': 'That quality profile has no qualities, so nothing could ever '
                              'be searched for -- add at least one quality to it first',
                }

            # CAS mutator, mirroring markDone/markFailedAndResearch: re-checks
            # the status-guard against the freshly re-read doc on every retry
            # (not just the pre-check above), so a concurrent write that beat
            # us to 'active' between our read and our write is a no-op, not a
            # clobber.
            def _restore(m):
                # Re-derive the scope guard HERE, on the doc actually being
                # written. update_with_retry re-get()s the current document on
                # every attempt including the first, so the pre-check above ran
                # against a DIFFERENT read. A concurrent writer that moved the
                # movie out of scope in that window (say a chart entry) would
                # otherwise be promoted to Wanted regardless -- the exact thing
                # the guard exists to prevent, reachable through the race.
                # markFailedAndResearch's mutator re-checks unconditionally for
                # the same reason.
                if m.get('status') not in RESTORABLE:
                    return False

                # Already active AND already searchable -> genuinely nothing to
                # do. The profile half of the guard matters: an 'active' movie
                # with no usable profile is skipped by single()'s gate, so
                # bailing on status alone left it permanently unsearchable
                # while reporting success. Repair the profile in that case,
                # then the status assignment below is simply a no-op.
                #
                # existingProfileId, NOT a truthiness check on profile_id: this
                # guard has to use the SAME definition of "has a profile" as
                # the pre-check above. When it used `m.get('profile_id')`, an
                # active movie whose profile had since been DELETED passed here
                # on truthiness and was written back unchanged -- reported as
                # success while single()'s gate let it through and
                # db.get('id', profile_id) then raised, so searchAll logged
                # 'Search failed' for it every cycle and never searched it.
                if m.get('status') == 'active' and self.existingProfileId(db, m):
                    return False
                m['status'] = 'active'
                # The caller's explicit pick always wins. Otherwise re-derive
                # against the doc being WRITTEN, for the same reason the status
                # guard above does: this mutator can run against a doc re-read
                # after a CAS retry, and blindly writing a profile_id resolved
                # from the pre-fetch doc would clobber a legitimate profile
                # change that raced this restore.
                m['profile_id'] = (caller_profile_id
                                    or self.existingProfileId(db, m)
                                    or resolved_profile_id)

            try:
                updated = db.update_with_retry(_restore, media_id)
            except (RecordNotFound, RecordDeleted, KeyError):
                return {'success': False, 'error': 'Media not found'}
            except ConflictError:
                log.warning('Gave up restoring media %s to wanted after retries due to persistent contention', media_id)
                return {'success': False, 'error': 'Database busy, please retry'}

            # None means the mutator's CAS re-check found the movie already
            # active on a retry (lost the race to another writer) -- still a
            # success. But `media` is the doc we read BEFORE that race, so
            # returning it (and pushing it to notify.frontend) reported stale
            # pre-race state for a movie that IS now active. Re-read to report
            # the winner's version; keep the stale copy only if the re-read
            # itself fails, which is still better than nothing.
            if updated:
                media = updated
            else:
                # The mutator declined to write. That is a no-op SUCCESS when
                # the movie was already active-and-searchable, but a FAILURE
                # when a concurrent writer moved it out of scope between our
                # pre-check and update_with_retry's own read -- we must not
                # report a restore we deliberately refused to make.
                try:
                    media = db.get('id', media_id)
                except (RecordNotFound, RecordDeleted, KeyError):
                    pass
                if media.get('status') not in RESTORABLE:
                    log.info('Not restoring %s: its status changed to %r before the write',
                             media_id, media.get('status'))
                    return {
                        'success': False,
                        'error': "This movie changed to '%s' while the restore was in "
                                  'flight, so it was not moved back to wanted'
                                  % media.get('status'),
                    }

            # Deliberately fired on the lost-race path too, where
            # update_with_retry returned None. sqlite_adapter's own docstring
            # suggests using that None to SKIP notifying, to avoid a duplicate
            # notify -- markFailedAndResearch does exactly that. This one
            # differs on purpose:
            #   - the re-read above means the payload is the winner's current
            #     state, so a duplicate notify is redundant, never wrong;
            #   - the movie genuinely WAS just edited (by the winner), so the
            #     'recent' tag and last_edit bump are accurate either way;
            #   - this call is user-initiated from the detail page, and that
            #     page has to refresh regardless of which concurrent writer
            #     happened to land the change first. Skipping the notify here
            #     would leave the user who pressed the button looking at stale
            #     UI whenever they lost a race they cannot see.
            # Discount the copy the movie already holds.
            #
            # Setting status='active' is not enough on a real install: every
            # profile this app creates uses finish=True on every rung ("take
            # the best thing available now, then stop"), so quality.isfinish is
            # True for ANY held release. media.restatus would finish the movie
            # again on the next sweep, and single()'s has_better_quality loop
            # would break before contacting a provider. Marking the held
            # releases 'ignored' addresses both -- restatus counts only 'done',
            # and has_better_quality skips ('available', 'ignored', 'failed').
            #
            # 'ignored' rather than 'failed': nothing failed, the user just
            # wants something better. Mirrors tryNextRelease, which marks the
            # snatched/done release 'ignored' for exactly this reason.
            #
            # Durability is release.add's job -- see the per-copy rule there.
            # A rescan used to rewrite this back to 'done', which is a
            # PRE-EXISTING bug that already breaks tryNextRelease and
            # markFailedAndResearch, not something this feature introduced.
            # Known trade-off on 'seeding': checkSnatched watches
            # release.with_status(['snatched','seeding','missing']), so a
            # seeding torrent marked 'ignored' drops out of that queue and is
            # never un-paused or post-processed. It is included anyway because
            # leaving it would let it satisfy the profile and defeat the whole
            # action, and because markFailedAndResearch already makes the same
            # trade with 'failed'. The user has just said they do not want this
            # copy, so abandoning its seed is the lesser harm -- but it does
            # mean the torrent stays in the client until removed by hand.
            # release.update_status returns False when it gives up (persistent
            # CAS contention). Ignoring that reported success while leaving a
            # 'done' release still satisfying the profile -- so the next
            # restatus moves the movie straight back out of Wanted, after the
            # UI has told the user it worked. Surface it instead.
            unset_aside = []
            for rel in fireEvent('release.for_media', media_id, single = True) or []:
                if rel.get('status') in ('done', 'seeding', 'downloaded'):
                    ok = fireEvent('release.update_status', rel.get('_id'),
                                    status = 'ignored', single = True)
                    if ok is False:
                        unset_aside.append(rel.get('_id'))

            if unset_aside:
                log.error('Restored %s but could not set aside releases %s', media_id, unset_aside)
                return {
                    'success': False,
                    'error': 'The movie was moved back to wanted, but a release could not '
                              'be set aside — it may complete again. Please retry.',
                }

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
