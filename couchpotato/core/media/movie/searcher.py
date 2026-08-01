from datetime import date
import random
import re
import threading
import time
import traceback

from CodernityDB.database import RecordDeleted, RecordNotFound

from couchpotato import get_db
from couchpotato.api import addApiView
from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.core.event import addEvent, fireEvent, fireEventAsync
from couchpotato.core.helpers.encoding import simplifyString
from couchpotato.core.helpers.variable import getTitle, possibleTitles, getImdb, getIdentifier, tryInt
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.searcher.base import SearcherBase
from couchpotato.core.media.movie import MovieTypeBase
from couchpotato.environment import Env


log = CPLog(__name__)

autoload = 'MovieSearcher'


class MovieSearcher(SearcherBase, MovieTypeBase):

    in_progress = False
    _progress_lock = None  # initialized in __init__

    def __init__(self):
        self._progress_lock = threading.Lock()
        super().__init__()

        addEvent('movie.searcher.all', self.searchAll)
        addEvent('movie.searcher.all_view', self.searchAllView)
        addEvent('movie.searcher.single', self.single)
        addEvent('movie.searcher.try_next_release', self.tryNextRelease)
        addEvent('movie.searcher.could_be_released', self.couldBeReleased)
        addEvent('searcher.correct_release', self.correctRelease)
        addEvent('searcher.get_search_title', self.getSearchTitle)

        addApiView('movie.searcher.try_next', self.tryNextReleaseView, docs = {
            'desc': 'Marks the snatched results as ignored and try the next best release',
            'params': {
                'media_id': {'desc': 'The id of the media'},
            },
        })

        addApiView('movie.searcher.mark_failed', self.markFailedView, docs = {
            'desc': "Downloaded/review workflow 'Mark Failed & re-search': marks the "
                    "movie's landed release as failed, resets the movie to active, and "
                    "immediately triggers a manual re-search.",
            'params': {
                'media_id': {'desc': 'The id of the media'},
            },
        })

        addApiView('movie.searcher.search_releases', self.searchReleasesView, docs = {
            'desc': "FEAT-005: list the releases currently available for a movie "
                    "WITHOUT downloading any of them. Works on a movie that is "
                    "already 'done' or awaiting review, so a better copy can be "
                    "found later and picked by hand.",
            'params': {
                'media_id': {'desc': 'The id of the media'},
            },
        })

        addApiView('movie.searcher.full_search', self.searchAllView, docs = {
            'desc': 'Starts a full search for all wanted movies',
        })

        addApiView('movie.searcher.progress', self.getProgress, docs = {
            'desc': 'Get the progress of current full search',
            'return': {'type': 'object', 'example': """{
    'progress': False || object, total & to_go,
}"""},
        })

        if self.conf('run_on_launch'):
            addEvent('app.load', self.searchAll)

    def searchAllView(self, **kwargs):

        fireEventAsync('movie.searcher.all', manual = True)

        return {
            'success': not self.in_progress
        }

    def searchAll(self, manual = False):

        with self._progress_lock:
            if self.in_progress:
                log.info('Search already in progress')
                fireEvent('notify.frontend', type = 'movie.searcher.already_started', data = True, message = 'Full search already in progress')
                return
            self.in_progress = True
        fireEvent('notify.frontend', type = 'movie.searcher.started', data = True, message = 'Full search started')

        medias = [x['_id'] for x in fireEvent('media.with_status', 'active', types = 'movie', with_doc = False, single = True)]
        random.shuffle(medias)

        total = len(medias)
        self.in_progress = {
            'total': total,
            'to_go': total,
        }

        try:
            search_protocols = fireEvent('searcher.protocols', single = True)

            for media_id in medias:

                media = fireEvent('media.get', media_id, single = True)
                if not media: continue

                try:
                    # BUG-015 follow-up: manual=True keeps the status-gating /
                    # ignore_eta semantics of a manual search (see single()),
                    # but bypass_cache=False keeps the full-library sweep on
                    # the normal 30-minute provider cache -- otherwise
                    # "Search All" would force a live uncached fetch against
                    # every configured indexer for every movie in the
                    # library, defeating the cache's rate-limit protection.
                    self.single(media, search_protocols, manual = manual, bypass_cache = False)
                except IndexError:
                    log.error('Forcing library update for %s, if you see this often, please report: %s', getIdentifier(media), traceback.format_exc())
                    fireEvent('movie.update', media_id)
                except Exception:
                    log.error('Search failed for %s: %s', getIdentifier(media), traceback.format_exc())

                self.in_progress['to_go'] -= 1

                # Break if CP wants to shut down
                if self.shuttingDown():
                    break

        except SearchSetupError:
            pass

        self.in_progress = False

    def single(self, movie, search_protocols = None, manual = False, force_download = False, bypass_cache = None, list_only = False):

        # BUG-015 follow-up: bypass_cache controls whether the provider HTTP
        # cache (30-minute newznab/torrentpotato cache) is bypassed for this
        # search. It defaults to manual's value, so existing single-movie
        # manual entry points (movie.searcher.single event, tryNextRelease,
        # markFailedView) keep bypassing the cache with no caller changes.
        # searchAll() explicitly passes bypass_cache=False so the full-library
        # sweep never bypasses the cache, even though it still searches with
        # manual=True for the status-gating/ignore_eta behaviour below.
        if bypass_cache is None:
            # list_only is always user-initiated -- it only exists to answer
            # "what is available right now" -- so it bypasses the cache on its
            # own rather than relying on every caller remembering to pair it
            # with manual=True.
            bypass_cache = manual or list_only

        # Find out search type
        try:
            if not search_protocols:
                search_protocols = fireEvent('searcher.protocols', single = True)
        except SearchSetupError:
            return

        # 'downloaded' is the manual-review gate (workflow phase 1): treat it like
        # 'done' for gating purposes so a movie awaiting review is never searched
        # or upgraded, unless a manual/forced search explicitly overrides it.
        #
        # FEAT-008: `not movie['profile_id']` used to be an unconditional
        # clause here -- unlike every OTHER gate in this method it was never
        # threaded with `list_only`, so a movie imported by the library
        # scanner (which never gets a profile) made "Search for releases"
        # silently search nothing, for every done/downloaded movie with no
        # profile. `and not list_only` makes this gate bypass the same way
        # the others already do: when list_only is True this whole `if` is
        # always False (the status clause already ends in `and not list_only`
        # too), so a list-only search is never blocked by either half of it.
        # AC2: this is purely a gate change -- nothing here writes a profile
        # back to the movie; see the profile_id resolution below, which is
        # entirely local.
        if (not movie['profile_id'] and not list_only) or (movie['status'] in ('done', 'downloaded') and not manual and not list_only):
            log.debug('Movie doesn\'t have a profile, is already done, or is awaiting review, assuming in manage tab.')
            fireEvent('media.restatus', movie['_id'], single = True)
            return

        default_title = getTitle(movie)
        if not default_title:
            # A list-only search must never delete anything. This branch is
            # reasonable for the automatic path -- an untitled movie cannot be
            # searched, so it is removed rather than failing every cycle -- but
            # it was previously unreachable for a done/downloaded movie, and
            # the list_only bypass exposed it. Deleting a library record
            # because the user asked "what's available?" is not acceptable.
            if list_only:
                log.debug('No usable title for %s; nothing to search.', movie.get('_id'))
                return
            log.error('No proper info found for movie, removing it from library to stop it from causing more issues.')
            fireEvent('media.delete', movie['_id'], single = True)
            return

        # Update media status and check if it is still not done (due to the stop searching after feature
        #
        # SKIPPED for a list-only search on a movie with no profile. restatus's
        # own `elif not m['profile_id']: m['status'] = 'done'` would persist
        # immediately -- this call fires BEFORE the local default-profile
        # fallback below resolves anything -- so pressing "Search for releases"
        # on an active profile-less movie silently dropped it out of Wanted,
        # then searched and stored hits against a movie that had just left the
        # list. AC2: a list-only search is read-only with respect to library
        # state. The automatic path is untouched.
        skip_restatus = list_only and not movie.get('profile_id')
        restatus_result = None if skip_restatus else fireEvent(
            'media.restatus', movie['_id'], single = True)
        if restatus_result == 'done':
            log.debug('No better quality found, marking movie %s as done.', default_title)
        elif restatus_result == 'downloaded':
            log.debug('Movie %s is awaiting manual review, holding at "downloaded".', default_title)

        pre_releases = fireEvent('quality.pre_releases', single = True)
        release_dates = fireEvent('movie.update_release_dates', movie['_id'], merge = True)

        found_releases = []
        previous_releases = movie.get('releases', [])
        too_early_to_search = []
        outside_eta_results = 0
        always_search = self.conf('always_search')
        wait_days = self.conf('wait_for_release')
        ignore_eta = manual
        total_result_count = 0

        fireEvent('notify.frontend', type = 'movie.searcher.started', data = {'_id': movie['_id']}, message = 'Searching for "%s"' % default_title)

        # Ignore eta once every 7 days
        if not always_search:
            prop_name = 'last_ignored_eta.%s' % movie['_id']
            last_ignored_eta = float(Env.prop(prop_name, default = 0))
            if last_ignored_eta < time.time() - 604800:
                ignore_eta = True
                Env.prop(prop_name, value = time.time())

        db = get_db()

        # FEAT-008: movie['profile_id'] can be None here -- only reachable
        # when the gate above was bypassed by list_only. Resolve a profile
        # the same way movie.add already falls back for a new movie
        # (fireEvent('profile.default'), in MovieBase.add), but PURELY
        # locally: `profile_id` is a local variable, never written back to
        # `movie` or persisted (AC2 -- a list-only search stays read-only).
        profile_id = movie['profile_id']
        if not profile_id:
            default_profile = fireEvent('profile.default', single = True)
            profile_id = (default_profile or {}).get('_id')

        try:
            profile = db.get('id', profile_id)
        except (RecordNotFound, KeyError):
            # A truthy but STALE profile_id -- the profile was deleted since
            # the movie referenced it. Dangling profile refs are real enough on
            # this codebase that MovieBase.existingProfileId exists specifically
            # to screen for them. Without this fallback a list-only search
            # reported "an unexpected error occurred" while a perfectly good
            # default profile sat unused.
            if not list_only:
                raise
            default_profile = fireEvent('profile.default', single = True)
            fallback_id = (default_profile or {}).get('_id')
            if not fallback_id:
                log.debug('Profile %s is missing and no default exists; nothing to search.', profile_id)
                return
            log.debug('Profile %s no longer exists; using the default for this list-only search.', profile_id)
            profile = db.get('id', fallback_id)
        ret = False

        for index, q_identifier in enumerate(profile.get('qualities', [])):
            quality_custom = {
                'index': index,
                'quality': q_identifier,
                'finish': profile['finish'][index],
                'wait_for': tryInt(profile['wait_for'][index]),
                '3d': profile['3d'][index] if profile.get('3d') else False,
                'minimum_score': profile.get('minimum_score', 1),
            }

            could_not_be_released = not self.couldBeReleased(q_identifier in pre_releases, release_dates, movie['info']['year'], wait_days = wait_days)
            if not always_search and could_not_be_released:
                too_early_to_search.append(q_identifier)

                # Skip release, if ETA isn't ignored
                if not ignore_eta:
                    continue

            has_better_quality = 0

            # See if better quality is available
            for release in movie.get('releases', []):
                if release['status'] not in ['available', 'ignored', 'failed']:
                    is_higher = fireEvent('quality.ishigher', \
                            {'identifier': q_identifier, 'is_3d': quality_custom.get('3d', 0)}, \
                            {'identifier': release['quality'], 'is_3d': release.get('is_3d', 0)}, \
                            profile, single = True)
                    if is_higher != 'higher':
                        has_better_quality += 1

            # Don't search for quality lower then already available.
            #
            # FEAT-005: a list-only search skips this. For a movie that already
            # holds its profile's top quality this breaks on the FIRST rung, so
            # honouring it would mean "show me what's available" searched
            # nothing at all -- which is exactly the case the feature is for.
            if has_better_quality > 0 and not list_only:
                log.info('Better quality (%s) already available or snatched for %s', q_identifier, default_title)
                fireEvent('media.restatus', movie['_id'], single = True)
                break

            quality = fireEvent('quality.single', identifier = q_identifier, single = True)
            if not quality or not isinstance(quality, dict):
                log.warning('Quality %s not found in database, skipping search', q_identifier)
                continue
            log.info('Search for %s in %s%s', default_title, quality.get('label', q_identifier), ' ignoring ETA' if always_search or ignore_eta else '')

            # Extend quality with profile customs
            quality['custom'] = quality_custom

            results = fireEvent('searcher.search', search_protocols, movie, quality, manual = bypass_cache, single = True) or []

            # Check if movie isn't deleted while searching
            if not fireEvent('media.get', movie.get('_id'), single = True):
                break

            # Add them to this movie releases list
            found_releases += fireEvent('release.create_from_search', results, movie, quality, single = True)
            results_count = len(found_releases)
            total_result_count += results_count
            if results_count == 0:
                log.debug('Nothing found for %s in %s', default_title, quality.get('label', '?'))

            # Keep track of releases found outside ETA window
            outside_eta_results += results_count if could_not_be_released else 0

            # Don't trigger download, but notify user of available releases
            if could_not_be_released and results_count > 0:
                log.debug('Found %s releases for "%s", but ETA isn\'t correct yet.', results_count, default_title)

            # Try find a valid result and download it.
            # FEAT-005: never in list-only mode -- the results are stored as
            # 'available' by release.create_from_search above, and the user
            # picks one.
            if not list_only and (force_download or not could_not_be_released or always_search) \
                    and fireEvent('release.try_download_result', results, movie, quality_custom, single = True):
                ret = True

            # Remove releases that aren't found anymore.
            #
            # Skipped for a list-only search: providers routinely swallow
            # connection/HTTP errors and simply return no results, and this
            # would then delete the very release list the user opened the page
            # to look at. The automatic path can afford to re-derive the set
            # each cycle because it is followed by a download; an explicit
            # "show me what's available" cannot.
            if not list_only:
                temp_previous_releases = []
                for release in previous_releases:
                    if release.get('status') == 'available' and release.get('identifier') not in found_releases:
                        fireEvent('release.delete', release.get('_id'), single = True)
                    else:
                        temp_previous_releases.append(release)
                previous_releases = temp_previous_releases
                del temp_previous_releases

            # Break if CP wants to shut down
            if self.shuttingDown() or ret:
                break

        if total_result_count > 0:
            # Deliberately NOT gated by list_only, despite list-only being
            # otherwise read-only. release.cleanDone() deletes every
            # 'available' release for any movie whose last_edit is older than
            # a week -- and a 'done' movie's last_edit is typically months
            # old. Without this bump, the releases a list-only search just
            # surfaced would be swept before the user could pick one, which
            # would make FEAT-005 silently useless.
            fireEvent('media.tag', movie['_id'], 'recent', update_edited = True, single = True)

        if len(too_early_to_search) > 0:
            log.info2('Too early to search for %s, %s', too_early_to_search, default_title)

            if outside_eta_results > 0:
                message = 'Found %s releases for "%s" before ETA. Select and download via the dashboard.' % (outside_eta_results, default_title)
                log.info(message)

                if not manual:
                    fireEvent('media.available', message = message, data = {})

        fireEvent('notify.frontend', type = 'movie.searcher.ended', data = {'_id': movie['_id']})

        return ret

    def correctRelease(self, nzb = None, media = None, quality = None, **kwargs):

        if media.get('type') != 'movie': return

        media_title = fireEvent('searcher.get_search_title', media, single = True)

        imdb_results = kwargs.get('imdb_results', False)
        retention = Env.setting('retention', section = 'nzb')

        if nzb.get('seeders') is None and 0 < retention < nzb.get('age', 0):
            log.info2('Wrong: Outside retention, age is %s, needs %s or lower: %s', nzb['age'], retention, nzb['name'])
            return False

        # Check for required and ignored words
        if not fireEvent('searcher.correct_words', nzb['name'], media, single = True):
            return False

        preferred_quality = quality if quality else fireEvent('quality.single', identifier = quality['identifier'], single = True)

        # Contains lower quality string
        contains_other = fireEvent('searcher.contains_other_quality', nzb, movie_year = media['info']['year'], preferred_quality = preferred_quality, single = True)
        if contains_other and isinstance(contains_other, dict):
            log.info2('Wrong: %s, looking for %s, found %s', nzb['name'], quality['label'], [x for x in contains_other] if contains_other else 'no quality')
            return False

        # Contains lower quality string
        if not fireEvent('searcher.correct_3d', nzb, preferred_quality = preferred_quality, single = True):
            log.info2('Wrong: %s, %slooking for %s in 3D', nzb['name'], ('' if preferred_quality['custom'].get('3d') else 'NOT '), quality['label'])
            return False

        # File to small
        if nzb['size'] and tryInt(preferred_quality['size_min']) > tryInt(nzb['size']):
            log.info2('Wrong: "%s" is too small to be %s. %sMB instead of the minimal of %sMB.', nzb['name'], preferred_quality['label'], nzb['size'], preferred_quality['size_min'])
            return False

        # File to large
        if nzb['size'] and tryInt(preferred_quality['size_max']) < tryInt(nzb['size']):
            log.info2('Wrong: "%s" is too large to be %s. %sMB instead of the maximum of %sMB.', nzb['name'], preferred_quality['label'], nzb['size'], preferred_quality['size_max'])
            return False

        # Provider specific functions
        get_more = nzb.get('get_more_info')
        if get_more:
            get_more(nzb)

        extra_check = nzb.get('extra_check')
        if extra_check and not extra_check(nzb):
            return False


        if imdb_results:
            return True

        # Check if nzb contains imdb link
        if getImdb(nzb.get('description', '')) == getIdentifier(media):
            return True

        for raw_title in media['info']['titles']:
            for movie_title in possibleTitles(raw_title):
                movie_words = re.split(r'\W+', simplifyString(movie_title))

                if fireEvent('searcher.correct_name', nzb['name'], movie_title, single = True):
                    # if no IMDB link, at least check year range 1
                    if len(movie_words) > 2 and fireEvent('searcher.correct_year', nzb['name'], media['info']['year'], 1, single = True):
                        return True

                    # if no IMDB link, at least check year
                    if len(movie_words) <= 2 and fireEvent('searcher.correct_year', nzb['name'], media['info']['year'], 0, single = True):
                        return True

        log.info("Wrong: %s, undetermined naming. Looking for '%s (%s)'", nzb['name'], media_title, media['info']['year'])
        return False

    def couldBeReleased(self, is_pre_release, dates, year = None, wait_days = None):
        """Whether a movie is far enough past its release date to download.

        `wait_days` is the configurable hold-off after the release date
        (the `wait_for_release` setting, default 0 = as soon as it is out).
        It is a parameter rather than a `self.conf()` read so this stays a
        pure function -- callers pass the configured value.
        """

        now = int(time.time())
        now_year = date.today().year
        now_month = date.today().month

        # `dates` may arrive as a list: an unhandled fireEvent returns [], and
        # older databases have [] cached in info['release_date']. Normalise
        # once so the .get() calls below are safe without a `not dates`
        # short-circuit -- see BUG-017.
        if not isinstance(dates, dict):
            dates = {}

        # A blank or junk setting means "no wait", never a crash or a hold
        # that never expires.
        wait_seconds = max(tryInt(wait_days, 0), 0) * 86400

        if (year is None or year < now_year - 1 or (year <= now_year - 1 and now_month > 4)) and (not dates or (dates.get('theater', 0) == 0 and dates.get('dvd', 0) == 0)):
            return True
        else:

            # Don't allow movies with years to far in the future
            add_year = 1 if now_month > 10 else 0 # Only allow +1 year if end of the year
            if year is not None and year > (now_year + add_year):
                return False

            # For movies before 1972 (a negative epoch is the sentinel).
            #
            # BUG-017: this used to also match `not dates`, so an UNKNOWN
            # release date was read as "already released" and authorised a
            # download. Unknown dates now fall through every branch below to
            # the closing `return False` -- unknown means not yet released.
            # The similar `not dates` test at the top of this method is a
            # different, deliberate case ("old movie AND no dates"): a film
            # two years in the past cannot be unreleased.
            if dates.get('theater', 0) < 0 or dates.get('dvd', 0) < 0:
                return True

            if is_pre_release:
                # Prerelease 1 week before theaters
                if dates.get('theater', 0) > 0 and dates.get('theater', 0) - 604800 < now:
                    return True
            else:
                # Past the release date, plus the configured hold-off. This
                # was a hardcoded 12 weeks (7257600s), written when waiting
                # for physical media was the point; it is now the
                # `wait_for_release` setting, default 0 -- see BUG-017.
                if dates.get('theater', 0) > 0 and dates.get('theater', 0) + wait_seconds < now:
                    return True

                if dates.get('dvd', 0) > 0:

                    # 4 weeks before dvd release
                    if dates.get('dvd', 0) - 2419200 < now:
                        return True

                    # Dvd should be released
                    if dates.get('dvd', 0) < now:
                        return True


        return False

    def searchReleasesView(self, media_id = None, **kwargs):
        """FEAT-005 "Search for releases": populate the movie's release list
        without snatching anything.

        Unlike every other search entry point this never downloads -- it
        exists so a movie you already have can be re-examined against what
        providers currently offer.

        It does NOT promise to leave `status` alone, and never did: both this
        path and the automatic one fire `media.restatus`, which computes and
        writes a status. What the list-only path guarantees is that it adds no
        status change of its own, and that it never writes `profile_id` back,
        deletes the movie, or deletes existing releases. Pinned by
        tests/unit/test_search_releases_list_only.py::TestListOnlyIsNonDestructive
        and ...::test_list_only_makes_no_status_change_the_automatic_path_would_not.
        """
        try:
            return self._searchReleases(media_id)
        except Exception:
            # Wrapped like tryNextRelease and markFailedAndResearch: single()
            # indexes movie['info']['year'] directly, and a library import can
            # lack it -- exactly the movies this feature targets. A 500 on the
            # detail page is a worse answer than a handled failure.
            log.error('Failed searching releases for %s: %s', media_id, traceback.format_exc())
            # FEAT-008 AC3: an exception means no search actually completed --
            # report it the same way as any other could-not-search outcome
            # (searched=False + reason), not just a bare success=False.
            return {'success': False, 'searched': False, 'found': 0,
                     'reason': 'An unexpected error occurred while searching'}

    def _resolvableProfileId(self, profile_id):
        """The id of the profile this search will ACTUALLY use, or None if it
        cannot produce a search.

        This must mirror single()'s own resolution exactly, or the pre-flight
        approves one profile while the search uses another. In particular:
        single() falls back to the default only when the movie's profile_id is
        missing or does NOT RESOLVE -- never because it resolved to something
        unusable. Checking "movie's profile, else default" in a different order
        meant a healthy default masked a movie whose own profile had no
        qualities, and the view reported a completed search after contacting no
        provider.

        The qualities check is the second half of AC4: single() iterates
        profile['qualities'], so an EMPTY list contacts nothing at all.
        forceDefaults strips ''/'-1' entries (plugins/profile/main.py), so an
        empty qualities list is reachable, not hypothetical.
        """
        db = get_db()

        def _resolve(candidate):
            if not candidate:
                return None
            try:
                return db.get('id', candidate)
            except (RecordNotFound, KeyError):
                return None

        used_id = profile_id
        profile = _resolve(profile_id)

        if profile is None:
            default_profile = fireEvent('profile.default', single = True)
            used_id = (default_profile or {}).get('_id')
            profile = _resolve(used_id)

        if not profile or not profile.get('qualities'):
            return None
        return used_id

    def _searchReleases(self, media_id):
        """FEAT-008 AC3: the response distinguishes three outcomes so the UI
        can tell them apart -- they used to collapse into the same
        {'success': True, 'found': 0} payload, which read as "searched,
        found nothing" even when nothing was ever searched:

          - searched, found N        -> {'success': True,  'searched': True,  'found': N}
          - searched, found nothing  -> {'success': True,  'searched': True,  'found': 0}
          - could not search         -> {'success': False, 'searched': False, 'found': 0, 'reason': <str>}
        """
        media = fireEvent('media.get', media_id, single = True)
        if not media:
            return {'success': False, 'searched': False, 'found': 0,
                     'reason': 'This movie no longer exists'}

        # AC4: pre-flight the SAME profile fallback single() itself will
        # attempt (fireEvent('profile.default'), mirroring movie.add at
        # in MovieBase.add) so a genuinely profile-less install (fresh
        # install, or every profile deleted) is reported as "could not
        # search" with a reason -- rather than calling single(), having it
        # silently do nothing, and this method reporting a misleading
        # 'searched: true, found: 0' for a search that never ran.
        # Note this asks whether the profile RESOLVES, not merely whether the
        # id is truthy. A movie carrying a profile_id that points at a DELETED
        # profile used to skip this check entirely, enter single(), fall
        # through the stale-profile branch, find no default, and return having
        # contacted zero providers -- while this method went on to report
        # 'searched: true, found: 0'. That is AC4's own scenario reported as a
        # completed search, which is the exact lie FEAT-008 exists to remove.
        try:
            usable_profile = self._resolvableProfileId(media.get('profile_id'))
        except Exception:
            # Don't report a database fault as "no profile configured" -- that
            # sends the user off to create a profile they already have.
            log.error('Failed resolving a profile for %s: %s', media_id, traceback.format_exc())
            return {'success': False, 'searched': False, 'found': 0,
                     'reason': 'Could not read your quality profiles, so nothing was searched'}

        if not usable_profile:
            return {
                'success': False,
                'searched': False,
                'found': 0,
                'reason': 'No usable quality profile is configured, so nothing could be searched',
            }

        # No enabled downloader/protocol means single() will call search() with
        # an EMPTY protocol list, which iterates nothing and contacts no
        # provider -- while getSearchProtocols logs "There aren't any
        # downloaders enabled" and returns [] rather than raising. Without this
        # pre-flight the user was told "Searched -- no releases found" after a
        # search that never happened, which is the exact defect FEAT-008 exists
        # to remove; this is simply its most common trigger.
        try:
            protocols = fireEvent('searcher.protocols', single = True)
        except SearchSetupError:
            protocols = None
        if not protocols:
            return {
                'success': False,
                'searched': False,
                'found': 0,
                'reason': 'No enabled downloader matches your enabled providers, '
                          'so there was nothing to search',
            }

        # A title is what every provider searches on. single() bails read-only
        # without one (the list_only branch of the untitled-movie guard), so
        # again: no search happened, do not claim one did.
        if not getTitle(media):
            return {
                'success': False,
                'searched': False,
                'found': 0,
                'reason': 'This movie has no usable title to search for',
            }

        # Count what was already there, so `found` can report what THIS search
        # produced. Counting the total meant a movie with 3 existing available
        # releases reported "Found 3 releases" in green after a search that
        # found none -- a total provider outage looked like success.
        def _available(doc):
            return len([
                r for r in (doc.get('releases') or [])
                if r.get('status') == 'available'
            ])

        before = _available(media)

        # manual=True as well as list_only: single() derives bypass_cache from
        # `manual`, so without it a user pressing "Search for releases" is
        # answered from the 30-minute provider cache -- stale results for an
        # explicitly user-initiated action. It also matches how try_next and
        # mark_failed mark "a human asked for this". It cannot cause a
        # download: list_only short-circuits the download gate regardless.
        self.single(media, manual = True, list_only = True)

        # Re-read so the count reflects what was just stored.
        media = fireEvent('media.get', media_id, single = True) or media
        after = _available(media)

        return {
            'success': True,
            'searched': True,
            'found': max(after - before, 0),
            'available': after,
        }

    def tryNextReleaseView(self, media_id = None, **kwargs):

        trynext = self.tryNextRelease(media_id, manual = True, force_download = True)

        return {
            'success': trynext
        }

    def tryNextRelease(self, media_id, manual = False, force_download = False):

        try:

            rels = fireEvent('release.for_media', media_id, single = True)

            for rel in rels:
                if rel.get('status') in ['snatched', 'done']:
                    fireEvent('release.update_status', rel.get('_id'), status = 'ignored')

            media = fireEvent('media.get', media_id, single = True)
            if media:
                log.info('Trying next release for: %s', getTitle(media))
                self.single(media, manual = manual, force_download = force_download)

                return True

            return False
        except Exception:
            log.error('Failed searching for next release: %s', traceback.format_exc())
            return False

    def markFailedView(self, media_id = None, **kwargs):

        success = self.markFailedAndResearch(media_id)

        return {
            'success': success
        }

    def markFailedAndResearch(self, media_id):
        """Downloaded/review workflow (specs/DOWNLOADED-REVIEW-WORKFLOW.md)
        "Mark Failed & re-search" action: the user rejected the copy that
        landed for a movie awaiting review. Reset the movie back to 'active'
        so the searcher will consider it again, mark the landed release(s)
        'failed' (distinct from tryNextRelease's 'ignored' -- a review-gate
        rejection is a stronger signal than a routine "try the next
        candidate"), and immediately trigger a manual re-search rather than
        waiting for the next scheduled cycle. The 'failed' release is already
        excluded from re-grabbing by the has-better-quality check in single()
        (searcher.py:~191).

        Ordering matters: the movie CAS reset happens FIRST and only its
        success unlocks the release-failing step (mirrors
        MediaPlugin.markDone, which updates the movie before touching
        releases). If the reset were done last and failed, we'd be left in a
        half-done state -- the landed release already marked 'failed' but the
        movie still stuck in 'downloaded' with no landed copy and no
        auto-recovery.

        Scope guard: this action is spec-scoped to a movie *in the review
        gate* ('downloaded'). The reset only proceeds when the current status
        is 'downloaded'; any other status (incl. a confirmed 'done' movie
        reached via a stale tab / double-submit / direct API call) is a
        no-op -- so we never reopen and re-search a movie the user already
        confirmed as finished, nor fail its confirmed release.
        """
        try:
            db = get_db()

            # Read-modify-write on the movie doc -- route through the CAS
            # retry helper (same pattern as MediaPlugin.markDone/markWatched)
            # rather than a bare get()+update() so a lost update can't
            # silently drop a concurrent change to this media doc. The
            # mutator returns False (-> update_with_retry returns None, no
            # write) for any non-'downloaded' movie, enforcing the scope
            # guard atomically against the freshly re-read doc on every retry.
            def _reset_if_downloaded(media):
                if media.get('status') != 'downloaded':
                    return False
                media['status'] = 'active'
                return media

            try:
                updated = db.update_with_retry(_reset_if_downloaded, media_id)
            except (RecordNotFound, RecordDeleted, KeyError):
                log.error('Media not found while resetting to active for re-search: %s', media_id)
                return False
            except ConflictError:
                log.warning('Gave up resetting media %s to active after retries due to persistent contention', media_id)
                return False

            # None => the guard short-circuited (movie was not 'downloaded'):
            # don't touch releases, don't search, report no-op.
            if not updated:
                return False

            # Movie is now 'active'. NOW fail the landed release(s) -- only
            # reached because the reset actually succeeded.
            for rel in fireEvent('release.for_media', media_id, single = True) or []:
                if rel.get('status') in ('downloaded', 'snatched', 'seeding', 'done'):
                    fireEvent('release.update_status', rel.get('_id'), status = 'failed', single = True)

            # Re-fetch the fully-enriched doc (with 'releases' attached) via
            # the same event tryNextRelease uses, so single() sees the
            # just-updated 'failed' status and 'active' movie status.
            media = fireEvent('media.get', media_id, single = True)
            if not media:
                return False

            log.info('Marked failed release(s) for %s, triggering immediate re-search', getTitle(media))
            fireEvent('movie.searcher.single', media, manual = True, single = True)

            return True
        except Exception:
            log.error('Failed marking media %s failed for re-search: %s', media_id, traceback.format_exc())
            return False

    def getSearchTitle(self, media):
        if media['type'] == 'movie':
            return getTitle(media)

class SearchSetupError(Exception):
    pass


config = [{
    'name': 'moviesearcher',
    'order': 20,
    'groups': [
        {
            'tab': 'searcher',
            'name': 'movie_searcher',
            'label': 'Movie search',
            'description': 'Search options for movies',
            'advanced': True,
            'options': [
                {
                    'name': 'always_search',
                    'default': False,
                    'migrate_from': 'searcher',
                    'type': 'bool',
                    'label': 'Always search',
                    'description': 'Search for <em>and download</em> movies even before there is an ETA. This bypasses the release-date gate entirely, not just the search, so you will probably get a lot of fakes and early grabs.',
                },
                {
                    'name': 'wait_for_release',
                    'default': 0,
                    'type': 'int',
                    'label': 'Wait after release',
                    'description': 'Days to wait after a movie\'s release date before downloading it. <strong>0</strong>: as soon as it is out. Raise this if you keep getting fakes or poor early rips; <strong>84</strong> (12 weeks) matches the old built-in behaviour of waiting for a physical release.',
                },
                {
                    'name': 'run_on_launch',
                    'migrate_from': 'searcher',
                    'label': 'Run on launch',
                    'advanced': True,
                    'default': 0,
                    'type': 'bool',
                    'description': 'Force run the searcher after (re)start.',
                },
                {
                    'name': 'search_on_add',
                    'label': 'Search after add',
                    'advanced': True,
                    'default': 1,
                    'type': 'bool',
                    'description': 'Disable this to only search for movies on cron.',
                },
                {
                    'name': 'cron_day',
                    'migrate_from': 'searcher',
                    'label': 'Day',
                    'advanced': True,
                    'default': '*',
                    'type': 'string',
                    'description': '<strong>*</strong>: Every day, <strong>*/2</strong>: Every 2 days, <strong>1</strong>: Every first of the month. See <a href="https://apscheduler.readthedocs.org/en/latest/modules/triggers/cron.html" target="_blank">APScheduler</a> for details.',
                },
                {
                    'name': 'cron_hour',
                    'migrate_from': 'searcher',
                    'label': 'Hour',
                    'advanced': True,
                    'default': random.randint(0, 23),
                    'type': 'string',
                    'description': '<strong>*</strong>: Every hour, <strong>*/8</strong>: Every 8 hours, <strong>3</strong>: At 3, midnight.',
                },
                {
                    'name': 'cron_minute',
                    'migrate_from': 'searcher',
                    'label': 'Minute',
                    'advanced': True,
                    'default': random.randint(0, 59),
                    'type': 'string',
                    'description': "Just keep it random, so the providers don't get DDOSed by every CP user on a 'full' hour."
                },
            ],
        },
    ],
}]
