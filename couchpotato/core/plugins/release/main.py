from inspect import ismethod, isfunction
import os
import time
import traceback

from CodernityDB.database import RecordDeleted, RecordNotFound
from couchpotato import md5, get_db
from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.api import addApiView
from couchpotato.core.event import fireEvent, addEvent
from couchpotato.core.helpers.encoding import toUnicode, sp
from couchpotato.core.helpers.protocol import sort_by_protocol_preference
from couchpotato.core.helpers.variable import getTitle, tryFloat, tryInt
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.core.media_lock import media_lock
from .index import ReleaseIndex, ReleaseStatusIndex, ReleaseIDIndex, ReleaseDownloadIndex
from couchpotato.environment import Env


log = CPLog(__name__)


def copyIdentity(files):
    """A stable identity for the COPY a scan found, or None if undecidable.

    Derived from the sorted SIZES of the release's movie files. Two properties
    matter, and each one is why an earlier design failed:

      - SIZE, not path. The default renamer template is
        `<namethe> (<year>)` / `<thename><cd>.<ext>` -- no quality, group or
        source token -- so every copy of a movie renames to the SAME path.
        Comparing paths therefore filed a genuinely new copy as 'ignored', and
        the movie was re-downloaded on every sweep. Two different encodes
        essentially never share a byte count.
      - SORTED, and movie files only. folder_scanner.py builds each bucket with
        `list(<set>)`, so ordering is hash-randomised between processes -- one
        unchanged folder produced nine different orderings across fourteen
        processes. Sorting removes that. Restricting to the 'movie' bucket
        means a subtitle or poster appearing alongside does not read as a
        different copy.

    Returns None when it cannot be computed -- no movie file, or a file that
    cannot be stat'ed. Callers must treat None as "do not know" and fall back
    to the pre-existing behaviour rather than guessing.
    """
    movie_files = (files or {}).get('movie') or []
    sizes = []
    for path in movie_files:
        try:
            sizes.append(os.path.getsize(path))
        except OSError:
            return None
    if not sizes:
        return None
    return ','.join(str(size) for size in sorted(sizes))


class Release(Plugin):

    _database = {
        'release': ReleaseIndex,
        'release_status': ReleaseStatusIndex,
        'release_identifier': ReleaseIDIndex,
        'release_download': ReleaseDownloadIndex
    }

    def __init__(self):
        addApiView('release.manual_download', self.manualDownload, docs = {
            'desc': 'Send a release manually to the downloaders',
            'params': {
                'id': {'type': 'id', 'desc': 'ID of the release object in release-table'}
            }
        })
        addApiView('release.delete', self.deleteView, docs = {
            'desc': 'Delete releases',
            'params': {
                'id': {'type': 'id', 'desc': 'ID of the release object in release-table'}
            }
        })
        addApiView('release.ignore', self.ignore, docs = {
            'desc': 'Toggle ignore, for bad or wrong releases',
            'params': {
                'id': {'type': 'id', 'desc': 'ID of the release object in release-table'}
            }
        })
        addApiView('release.failed', self.failedView, docs = {
            'desc': 'Mark a release as failed (Downloaded/review workflow per-release "Mark failed" action)',
            'params': {
                'id': {'type': 'id', 'desc': 'ID of the release object in release-table'}
            }
        })

        addEvent('release.add', self.add)
        addEvent('release.download', self.download)
        addEvent('release.try_download_result', self.tryDownloadResult)
        addEvent('release.create_from_search', self.createFromSearch)
        addEvent('release.delete', self.delete)
        addEvent('release.clean', self.clean)
        addEvent('release.update_status', self.updateStatus)
        addEvent('release.with_status', self.withStatus)
        addEvent('release.for_media', self.forMedia)

        # Clean releases that didn't have activity in the last week
        addEvent('app.load', self.cleanDone, priority = 1000)
        fireEvent('schedule.interval', 'movie.clean_releases', self.cleanDone, hours = 12)

    def cleanDone(self):
        log.debug('Removing releases from dashboard')

        now = time.time()
        week = 604800

        db = get_db()

        # Get (and remove) parentless releases
        releases = db.all('release', with_doc = False)
        media_exist = []
        # Renamed from `reindex`: the call it used to gate is gone (T3.2), so a
        # variable still called `reindex` reads as a leftover nobody dared
        # delete. It counts releases this pass found corrupt or orphaned, and
        # it is LOGGED below -- an incremented-but-never-read counter is not
        # "worth keeping", it is dead code with a comment claiming otherwise.
        damaged = 0
        for release in releases:
            if release.get('key') in media_exist:
                continue

            try:

                try:
                    doc = db.get('id', release.get('_id'))
                except RecordDeleted:
                    damaged += 1
                    continue

                db.get('id', release.get('key'))
                media_exist.append(release.get('key'))

                try:
                    if doc.get('status') == 'ignore':
                        doc['status'] = 'ignored'
                        db.update(doc)
                except Exception:
                    log.error('Failed fixing mis-status tag: %s', traceback.format_exc())
            except ValueError:
                fireEvent('database.delete_corrupted', release.get('key'), traceback_error = traceback.format_exc(0))
                damaged += 1
            except RecordDeleted:
                try:
                    db.delete(doc)
                    log.debug('Deleted orphaned release: %s', doc)
                except Exception:
                    log.debug('Failed deleting orphaned release (corrupt index), skipping: %s', doc.get('_id', '?'))
                damaged += 1
            except Exception:
                log.debug('Failed cleaning up orphaned releases: %s', traceback.format_exc())

        # The `db.reindex()` this used to gate is gone (T3.2): it is a
        # documented no-op on SQLite, and its signature requires an
        # `index_name` none of the four call sites passed -- so every one was a
        # guaranteed TypeError, which in manage.updateLibrary swallowed the
        # library-scan completion timestamp.
        #
        # The count is REPORTED rather than merely accumulated. Corrupt or
        # orphaned release rows are the visible symptom of the index-family
        # defects this branch exists to fix, so a number that quietly rises
        # while nobody can see it is the least useful place for it.
        #
        # MEASURED CAVEAT, recorded so this line does not read as a working
        # report: on SQLiteAdapter the loop above is currently DEAD, so
        # `damaged` cannot become non-zero and this never fires. Driven against
        # a real adapter seeded with an orphan and a legacy 'ignore' status:
        # `db.all('release', with_doc=False)` returns rows keyed
        # ['_id','_rev','_t','media_id','status'] with NO 'key' field, so
        # `release.get('key')` is always None, `db.get('id', None)` raises
        # KeyError, and every arm below it is unreachable -- `RecordDeleted` is
        # never raised by this adapter at all, and `get` raises KeyError rather
        # than ValueError. The orphan survived, the 'ignore' status was never
        # migrated, and nothing was logged.
        #
        # That is a PRE-EXISTING defect in the CodernityDB-shaped assumptions,
        # not something this branch introduced, and repairing it changes a path
        # that DELETES releases -- which this project's own rules say gets its
        # own change and its own review rather than being folded into a data
        # correctness PR. Tracked in the plan's deferred list.
        if damaged:
            log.info('Cleaned up %s corrupt or orphaned release record(s)', damaged)

        del media_exist

        # get movies last_edit more than a week ago
        # 'downloaded' (workflow phase 2 review gate) is included so a
        # review-gated movie's stale/duplicate releases still get cleaned up
        # like a 'done' movie's would -- it's not being searched, but it's
        # not exempt from this stale-release hygiene pass either.
        medias = fireEvent('media.with_status', ['done', 'active', 'downloaded'], single = True)

        for media in medias:
            if media.get('last_edit', 0) > (now - week):
                continue

            for rel in self.forMedia(media['_id']):

                # Remove all available releases
                if rel['status'] in ['available']:
                    self.delete(rel['_id'])

                # Set all snatched and downloaded releases to ignored to make sure they are ignored when re-adding the media
                elif rel['status'] in ['snatched', 'downloaded']:
                    self.updateStatus(rel['_id'], status = 'ignored')

            if 'recent' in media.get('tags', []):
                fireEvent('media.untag', media.get('_id'), 'recent', single = True)

    def add(self, group, update_info = True, update_id = None):

        with media_lock(group.get('identifier', 'unknown')):
            try:
                db = get_db()

                release_identifier = '%s.%s.%s' % (group['identifier'], group['meta_data'].get('audio') or 'unknown', group['meta_data']['quality']['identifier'])

                # Add movie if it doesn't exist
                try:
                    media = db.get('media', 'imdb-%s' % group['identifier'], with_doc = True)['doc']
                except (RecordNotFound, KeyError):
                    media = fireEvent('movie.add', params = {
                        'identifier': group['identifier'],
                        'profile_id': None,
                    }, search_after = False, update_after = update_info, notify_after = False, status = 'done', single = True)

                scanned_copy_id = copyIdentity(group.get('files'))

                def _scanned_status(existing_doc):
                    """'done', unless this is the very copy that was set aside.

                    A rescan must not resurrect a release deliberately marked
                    'ignored' or 'failed' -- doing so silently undoes 'Try next
                    release', 'Mark Failed & re-search' and 'Move back to
                    wanted', all of which mark by status. The resurrected
                    release then re-finishes the movie via media.restatus and
                    re-blocks the search in single()'s has_better_quality loop.

                    The comparison is per-COPY (see copyIdentity). Keying on
                    `release_identifier` instead would mean "never record any
                    copy at this quality again", because that identifier is
                    `<imdb>.<audio>.<quality>` -- a quality rung, not a copy.

                    Anything undecidable returns 'done', so a release predating
                    this field, or one whose files cannot be read, behaves
                    exactly as it did before.
                    """
                    existing_doc = existing_doc or {}
                    if existing_doc.get('status') not in ('ignored', 'failed'):
                        return 'done'
                    stored = existing_doc.get('copy_id')
                    if not stored or not scanned_copy_id or stored != scanned_copy_id:
                        return 'done'
                    return existing_doc['status']

                release = None
                if update_id:
                    try:
                        release = db.get('id', update_id)
                        release.update({
                            'identifier': release_identifier,
                            'last_edit': int(time.time()),
                            'status': _scanned_status(release),
                        })
                    except Exception:
                        log.error('Failed updating existing release: %s', traceback.format_exc())
                else:

                    # Add Release
                    if not release:
                        release = {
                            '_t': 'release',
                            'media_id': media['_id'],
                            'identifier': release_identifier,
                            'quality': group['meta_data']['quality'].get('identifier'),
                            'is_3d': group['meta_data']['quality'].get('is_3d', 0),
                            'last_edit': int(time.time()),
                            'status': 'done'
                        }

                    try:
                        r = db.get('release_identifier', release_identifier, with_doc = True)['doc']
                        r['media_id'] = media['_id']
                        # `release` was built fresh above with status 'done';
                        # carry a deliberate set-aside status across, but only
                        # when this scan found the same COPY it was set aside
                        # with.
                        release['status'] = _scanned_status(r)
                        # Carry the stored identity too. This branch builds a
                        # FRESH dict and db.update replaces the whole document,
                        # so a field that is not copied is dropped -- and this
                        # is the branch manage.updateLibrary takes. Guarding the
                        # write below with `if scanned_copy_id:` protects
                        # nothing here: not writing it means losing it.
                        if r.get('copy_id'):
                            release['copy_id'] = r['copy_id']
                    except (RecordNotFound, KeyError):
                        log.debug('Failed updating release by identifier "%s". Inserting new.', release_identifier)
                        r = db.insert(release)

                    # Update with ref and _id
                    release.update({
                        '_id': r['_id'],
                        '_rev': r['_rev'],
                    })

                # Empty out empty file groups
                release['files'] = dict((k, [toUnicode(x) for x in v]) for k, v in group['files'].items() if v)
                # Stored so the NEXT rescan has something to compare against;
                # without it the guard above can never engage.
                #
                # Only when we actually computed one. copyIdentity returns None
                # if a file cannot be stat'ed, and writing that None over a
                # previously-stored id would destroy the set-aside identity
                # permanently -- no later scan could recover it, even once the
                # file is readable again. Narrow window (a file that becomes
                # unreadable between enumeration and here), silent and
                # irreversible cost.
                if scanned_copy_id:
                    release['copy_id'] = scanned_copy_id
                db.update(release)

                fireEvent('media.restatus', media['_id'], allowed_restatus = ['done'], single = True)

                return True
            except Exception:
                log.error('Failed: %s', traceback.format_exc())

        return False

    def deleteView(self, id = None, **kwargs):

        return {
            'success': self.delete(id)
        }

    def delete(self, release_id):

        try:
            db = get_db()
            rel = db.get('id', release_id)
            db.delete(rel)
            return True
        except RecordDeleted:
            log.debug('Already deleted: %s', release_id)
            return True
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return False

    def clean(self, release_id):

        try:
            db = get_db()
            rel = db.get('id', release_id)
            raw_files = rel.get('files')

            if len(raw_files) == 0:
                self.delete(rel['_id'])
            else:

                files = {}
                for file_type in raw_files:

                    for release_file in raw_files.get(file_type, []):
                        if os.path.isfile(sp(release_file)):
                            if file_type not in files:
                                files[file_type] = []
                            files[file_type].append(release_file)

                rel['files'] = files
                db.update(rel)

            return True
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return False

    def ignore(self, id = None, **kwargs):

        db = get_db()

        try:
            if id:
                rel = db.get('id', id, with_doc = True)
                self.updateStatus(id, 'available' if rel['status'] in ['ignored', 'failed'] else 'ignored')

            return {
                'success': True
            }
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return {
            'success': False
        }

    def failedView(self, id = None, **kwargs):
        """Downloaded/review workflow per-release "Mark failed" action
        (specs/DOWNLOADED-REVIEW-WORKFLOW.md): exposes updateStatus() as an
        API view for a specific bad release/link, mirroring ignore()'s
        shape. Unlike ignore(), which always reports success once no
        exception is raised, this surfaces updateStatus()'s own True/False
        return value -- updateStatus() already swallows a persistent CAS
        conflict internally and returns False rather than raising, so a
        contended write is reported as {'success': False} instead of a
        false positive.
        """
        try:
            return {
                'success': bool(id) and self.updateStatus(id, 'failed')
            }
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return {
            'success': False
        }

    def manualDownload(self, id = None, **kwargs):

        db = get_db()

        try:
            release = db.get('id', id)
            item = release['info']
            movie = db.get('id', release['media_id'])

            fireEvent('notify.frontend', type = 'release.manual_download', data = True, message = 'Snatching "%s"' % item['name'])

            # Get matching provider
            provider = fireEvent('provider.belongs_to', item['url'], provider = item.get('provider'), single = True)

            if item.get('protocol') != 'torrent_magnet':
                item['download'] = provider.loginDownload if provider.urls.get('login') else provider.download

            success = self.download(data = item, media = movie, manual = True)

            if success:
                fireEvent('notify.frontend', type = 'release.manual_download', data = True, message = 'Successfully snatched "%s"' % item['name'])

            return {
                'success': success == True
            }

        except Exception:
            log.error('Couldn\'t find release with id: %s: %s', id, traceback.format_exc())
            return {
                'success': False
            }

    def download(self, data, media, manual = False):

        # Test to see if any downloaders are enabled for this type
        downloader_enabled = fireEvent('download.enabled', manual, data, single = True)
        if not downloader_enabled:
            log.info('Tried to download, but none of the "%s" downloaders are enabled or gave an error', data.get('protocol'))
            return False

        # Download NZB or torrent file
        filedata = None
        if data.get('download') and (ismethod(data.get('download')) or isfunction(data.get('download'))):
            try:
                filedata = data.get('download')(url = data.get('url'), nzb_id = data.get('id'))
            except Exception:
                log.error('Tried to download, but the "%s" provider gave an error: %s', data.get('protocol'), traceback.format_exc())
                return False

            if filedata == 'try_next':
                return filedata
            elif not filedata:
                return False

        # Send NZB or torrent file to downloader
        download_result = fireEvent('download', data = data, media = media, manual = manual, filedata = filedata, single = True)
        if not download_result:
            log.info('Tried to download, but the "%s" downloader gave an error', data.get('protocol'))
            return False
        log.debug('Downloader result: %s', download_result)

        # Lock on media ID to serialize DB updates for this media item
        with media_lock(media.get('_id', 'unknown')):
            try:
                db = get_db()

                try:
                    rls = db.get('release_identifier', md5(data['url']), with_doc = True)['doc']
                except Exception:
                    log.error('No release found to store download information in')
                    return False

                renamer_enabled = Env.setting('enabled', 'renamer')

                # Save download-id info if returned
                if isinstance(download_result, dict):
                    rls['download_info'] = download_result
                    db.update(rls)

                log_movie = '%s (%s) in %s' % (getTitle(media), media['info'].get('year'), rls['quality'])
                snatch_message = 'Snatched "%s": %s from %s' % (data.get('name'), log_movie, (data.get('provider', '') + data.get('provider_extra', '')))
                log.info(snatch_message)
                fireEvent('%s.snatched' % data['type'], message = snatch_message, data = media)

                # Mark release as snatched
                if renamer_enabled:
                    self.updateStatus(rls['_id'], status = 'snatched')

                # If renamer isn't used, mark media done if finished or release downloaded
                else:

                    if media['status'] == 'active':
                        profile = db.get('id', media['profile_id'])
                        if fireEvent('quality.isfinish', {'identifier': rls['quality'], 'is_3d': rls.get('is_3d', False)}, profile, single = True):
                            log.info('Renamer disabled, marking media as finished: %s', log_movie)

                            # Mark release done
                            self.updateStatus(rls['_id'], status = 'done')

                            # Mark media done
                            fireEvent('media.restatus', media['_id'], single = True)

                            return True

                    # Assume release downloaded
                    self.updateStatus(rls['_id'], status = 'downloaded')

            except Exception:
                log.error('Failed storing download status: %s', traceback.format_exc())
                return False

        return True

    def tryDownloadResult(self, results, media, quality_custom):

        wait_for = False
        let_through = False
        filtered_results = []
        minimum_seeders = tryInt(Env.setting('minimum_seeders', section = 'torrent', default = 1))

        # Filter out ignored and other releases we don't want
        for rel in results:

            if rel.get('status') in ['ignored', 'failed']:
                log.info('Ignored: %s', rel['name'])
                continue

            if rel['score'] < quality_custom.get('minimum_score'):
                log.info('Ignored, score "%s" too low, need at least "%s": %s', rel['score'], quality_custom.get('minimum_score'), rel['name'])
                continue

            if rel['size'] <= 50:
                log.info('Ignored, size "%sMB" too low: %s', rel['size'], rel['name'])
                continue

            if 'seeders' in rel and rel.get('seeders') < minimum_seeders:
                log.info('Ignored, not enough seeders, has %s needs %s: %s', rel.get('seeders'), minimum_seeders, rel['name'])
                continue

            # If a single release comes through the "wait for", let through all
            rel['wait_for'] = False
            if quality_custom.get('index') != 0 and quality_custom.get('wait_for', 0) > 0 and rel.get('age') <= quality_custom.get('wait_for', 0):
                rel['wait_for'] = True
            else:
                let_through = True

            filtered_results.append(rel)

        # Loop through filtered results
        for rel in filtered_results:

            # Only wait if not a single release is old enough
            if rel.get('wait_for') and not let_through:
                log.info('Ignored, waiting %s days: %s', quality_custom.get('wait_for') - rel.get('age'), rel['name'])
                wait_for = True
                continue

            downloaded = fireEvent('release.download', data = rel, media = media, single = True)
            if downloaded is True:
                return True
            elif downloaded != 'try_next':
                break

        return wait_for

    def createFromSearch(self, search_results, media, quality):

        with media_lock(media.get('_id', 'unknown')):
            try:
                db = get_db()

                found_releases = []

                is_3d = False
                try: is_3d = quality['custom']['3d']
                except Exception: pass

                for rel in search_results:

                    rel_identifier = md5(rel['url'])

                    # Detect quality from release name instead of using searched quality
                    release_name = rel.get('name', '')
                    detected_quality = fireEvent('quality.guess', [release_name], single = True)
                    if detected_quality:
                        detected_quality_id = detected_quality.get('identifier', quality.get('identifier'))
                        detected_is_3d = detected_quality.get('is_3d', is_3d)
                    else:
                        # Fall back to searched quality if detection fails
                        detected_quality_id = quality.get('identifier')
                        detected_is_3d = is_3d

                    release = {
                        '_t': 'release',
                        'identifier': rel_identifier,
                        'media_id': media.get('_id'),
                        'quality': detected_quality_id,
                        'is_3d': detected_is_3d,
                        'status': rel.get('status', 'available'),
                        'last_edit': int(time.time()),
                        'info': {}
                    }

                    # Add downloader info if provided
                    try:
                        release['download_info'] = rel['download_info']
                        del rel['download_info']
                    except Exception:
                        pass

                    try:
                        rls = db.get('release_identifier', rel_identifier, with_doc = True)['doc']
                        # Update quality if it was re-detected (fixes historical incorrect quality)
                        if rls.get('quality') != detected_quality_id:
                            log.debug('Updating release quality: %s -> %s for "%s"',
                                     rls.get('quality'), detected_quality_id, release_name[:50])
                            rls['quality'] = detected_quality_id
                            rls['is_3d'] = detected_is_3d
                    except Exception:
                        rls = db.insert(release)
                        rls.update(release)

                    # Update info, but filter out functions
                    for info in rel:
                        try:
                            if not isinstance(rel[info], (str, int, float)):
                                continue

                            rls['info'][info] = toUnicode(rel[info]) if isinstance(rel[info], str) else rel[info]
                        except Exception:
                            log.debug('Couldn\'t add %s to ReleaseInfo: %s', info, traceback.format_exc())

                    try:
                        db.update(rls)
                    except ConflictError as e:
                        # A concurrent writer (e.g. updateStatus() on this
                        # same release doc) won the CAS race between our
                        # read and this write. This is a real, expected
                        # contention outcome for just this one release --
                        # not a code defect -- so skip only this release and
                        # keep processing the rest of search_results, rather
                        # than letting it propagate to the function-level
                        # except below and discard every found_releases
                        # entry already accumulated for the other releases.
                        # This `continue` skips the happy-path `rel['status']
                        # = rls.get('status')` refresh below, so we set it
                        # here explicitly -- but `rls` is the STALE
                        # pre-write copy whose CAS write just lost the race,
                        # precisely BECAUSE another writer already changed
                        # this release's status in the DB (e.g. updateStatus()
                        # concurrently setting it to 'ignored'). Using rls's
                        # stale status would stamp the just-changed release
                        # back to its old value, so re-read the authoritative
                        # current doc from the DB instead and use its status.
                        # If the release was deleted concurrently, fall back
                        # to a harmless 'available' placeholder rather than
                        # crashing -- the caller-owned `rel` entry in
                        # `search_results` is reused as-is by
                        # release.try_download_result right after this event
                        # fires (see searcher.py), and that path used to do
                        # an unguarded `rel['status']` lookup that would
                        # raise KeyError on a rel that never got a status,
                        # aborting the whole try_download_result batch. Now
                        # resolved: this is a crash-prevention fix, not
                        # merely a documented staleness trade-off.
                        log.warning('Skipped release %s due to a concurrent update: %s', rel_identifier, e)
                        try:
                            current = db.get('id', rls['_id'])
                        except (RecordNotFound, KeyError):
                            current = None
                        rel['status'] = current.get('status', 'available') if current else 'available'
                        continue

                    # Update release in search_results
                    rel['status'] = rls.get('status')

                    if rel['status'] == 'available':
                        found_releases.append(rel_identifier)

                return found_releases
            except Exception:
                log.error('Failed: %s', traceback.format_exc())

        return []

    def updateStatus(self, release_id, status = None):
        if not status: return False

        # Read-modify-write on the release doc. This is one of the hottest
        # status-transition paths (search/snatch/download/ignore all funnel
        # through it) and previously had no CAS or lock protection, so a
        # concurrent status change could be silently lost. Route it through
        # the CAS retry helper: it returns the updated doc if this call
        # actually wrote, or None if the mutator short-circuited (already
        # at the target status -- whether on the first read, or on a retry
        # after this call lost the CAS race and re-read a doc a concurrent
        # writer already landed at the same target status). Gate the
        # notify strictly on "this call wrote" so a conflict-then-skip
        # retry never fires a spurious duplicate of the notification the
        # winning writer already sent.
        def _mutate(rel):
            if rel.get('status') == status:
                return False

            release_name = None
            if rel.get('files'):
                for file_type in rel.get('files', {}):
                    if file_type == 'movie':
                        for release_file in rel['files'][file_type]:
                            release_name = os.path.basename(release_file)
                            break

            if not release_name and rel.get('info'):
                release_name = rel['info'].get('name')

            log.debug('Marking release %s as %s', release_name, status)
            rel['status'] = status
            rel['last_edit'] = int(time.time())

            # Backfill the copy identity at the moment a release is
            # deliberately SET ASIDE, so a later library scan can tell "the
            # copy that was set aside" from "a new copy at the same quality".
            #
            # Without this the feature is inert on every existing install:
            # copy_id is only ever written by Release.add, there is no
            # migration, and the set-aside guard needs a STORED id to compare
            # against. Measured on a pre-FEAT-009 release doc -- restore,
            # then a full scan, and the release was back to 'done' with the
            # false "downloaded -- awaiting review" notification.
            #
            # Doing it here rather than in each caller covers all three
            # features that set releases aside: movie.restore_to_wanted,
            # tryNextRelease and markFailedAndResearch.
            if status in ('ignored', 'failed') and not rel.get('copy_id'):
                rel['copy_id'] = copyIdentity(rel.get('files'))

        try:
            db = get_db()
            wrote = db.update_with_retry(_mutate, release_id)

            if wrote is not None:
                #Update all movie info as there is no release update function
                fireEvent('notify.frontend', type = 'release.update_status', data = wrote)

            return True
        except ConflictError:
            log.warning('Gave up updating release %s status after retries due to persistent contention', release_id)
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return False

    def withStatus(self, status, with_doc = True):

        db = get_db()

        status = list(status if isinstance(status, (list, tuple)) else [status])

        for s in status:
            for ms in db.get_many('release_status', s, with_doc = with_doc):
                if with_doc:
                    try:
                        doc = db.get('id', ms['_id'])
                        yield doc
                    except (RecordNotFound, KeyError):
                        log.debug('Record not found, skipping: %s', ms['_id'])
                else:
                    yield ms

    def forMedia(self, media_id):

        db = get_db()
        raw_releases = db.get_many('release', media_id)

        releases = []
        for r in raw_releases:
            try:
                doc = db.get('id', r.get('_id'))
                releases.append(doc)
            except RecordDeleted:
                pass
            except (ValueError, EOFError):
                fireEvent('database.delete_corrupted', r.get('_id'), traceback_error = traceback.format_exc(0))
            except Exception:
                log.debug('Skipping unreadable release %s: %s', r.get('_id', '?'), traceback.format_exc())

        # tryFloat, not tryInt: scores are floats (score/main.py adds
        # seeders * 100 / 15), so truncating would tie releases whose scores
        # differ only in the fraction and lose the real ranking.
        releases = sorted(releases, key = lambda k: tryFloat((k.get('info') or {}).get('score', 0)), reverse = True)

        # Sort based on the preferred download source. Same helper as
        # Searcher.search(), so the list the user sees is ordered the same way
        # the automatic picker orders its candidates.
        download_preference = self.conf('preferred_method', section = 'searcher')
        releases = sort_by_protocol_preference(releases, download_preference, lambda k: (k.get('info') or {}).get('protocol'))

        return releases or []
