"""Directory traversal and file grouping for the Scanner plugin."""

import os
import re
import threading
import time
import traceback

from couchpotato import get_db
from couchpotato.core.event import fireEvent
from couchpotato.core.helpers.encoding import simplifyString, sp, ss, toUnicode
from couchpotato.core.helpers.variable import getExt, getImdb, splitString, getIdentifier
from couchpotato.core.logger import CPLog
from guessit import guessit as guess_movie_info

log = CPLog(__name__)

# BUG-018: the fifth `determineMedia` fallback used to ask the search
# provider for exactly one result and take it, so a remake sorted ahead of
# its original (all four measured cases were only two results deep) was
# never even offered as an alternative. 5 gives enough headroom to see past
# a remake pair without an unbounded fetch.
#
# This is pinned as a result COUNT only. `search_type` is pinned separately,
# below the fallback's two `movie.search` calls, so raising this limit can
# never silently change the query TheMovieDb is asked (see FIX 6, round-one
# review of 0dc9e9a78).
SEARCH_YEAR_DISAMBIGUATION_LIMIT = 5

# A provider's release year can legitimately differ from the year parsed out
# of a filename by one (region release dates, festival versus wide release).
# 0 would treat every honest off-by-one provider year as a non-match and
# always fall back to the first result.
#
# The binding constraint on raising this above 1 is not the remake pairs --
# computed from the spec's own seven merged records, the year gaps are
# 1, 1, 3, 36, 27, 22, 20: the closest of the four MEASURED remake pairs
# (Mulan, Aladdin, Mean Girls, Lion King) is 20 years apart, comfortably
# clear of any tolerance this constant could sanely hold. The real
# constraint is the two CONSECUTIVE-YEAR SEQUEL pairs in the same catalogue
# (Deathly Hallows Part 1/2, Mockingjay Part 1/2), a gap of 1.
#
# Round two tried closing that gap by scoring candidates on closest year
# rather than taking the first in-tolerance one, and reverted it: measured
# live, the query this fallback sends carries `year=<parsed year>`, so an
# exact-year decoy is a near-certain second result whenever the correct
# film differs from the parsed year by one -- closest-wins hands the win
# to that decoy every time (Wicked, Nosferatu and Anora's 2025 reissues
# all beat the correct 2024 film this way; see `pickSearchYearMatch` and
# the spec's Recorded debt item 1). `pickSearchYearMatch` is back to
# first-within-tolerance, which means the sequel pairs stay UNFIXED at
# tolerance 1 whenever the provider lists the earlier part first -- that
# risk is accepted, not eliminated. Raising tolerance above 1 would not
# fix the sequel pairs either; it would only admit candidates two years
# off, widening the same collision to non-adjacent sequels and prequels.
SEARCH_YEAR_TOLERANCE = 1


class FolderScannerMixin:
    """Mixin providing directory scanning, file grouping, and identifier creation."""

    clean = (r'([ _\,\.\(\)\[\]\-]|^)(3d|hsbs|sbs|half.sbs|full.sbs|ou|half.ou|full.ou|extended|extended.cut|directors.cut|french|fr|swedisch|sw|danish|dutch|nl|swesub|subs|spanish|german|ac3|dts|custom|dc|divx|divx5|dsr|dsrip|dutch|dvd|dvdr|dvdrip|dvdscr|dvdscreener|screener|dvdivx|cam|fragment|fs|hdtv|hdrip'
            r'|hdtvrip|webdl|web.dl|webrip|web.rip|internal|limited|multisubs|ntsc|ogg|ogm|pal|pdtv|proper|repack|rerip|retail|r3|r5|bd5|se|svcd|swedish|german|read.nfo|nfofix|unrated|ws|telesync|ts|telecine|tc|brrip|bdrip|video_ts|audio_ts|480p|480i|576p|576i|720p|720i|1080p|1080i|hrhd|hrhdtv|hddvd|bluray|x264|h264|x265|h265|xvid|xvidvd|xxx|www.www|hc|\[.*\])(?=[ _\,\.\(\)\[\]\-]|$)')

    multipart_regex = [
        r'[ _\.-]+cd[ _\.-]*([0-9a-d]+)',
        r'[ _\.-]+dvd[ _\.-]*([0-9a-d]+)',
        r'[ _\.-]+part[ _\.-]*([0-9a-d]+)',
        r'[ _\.-]+dis[ck][ _\.-]*([0-9a-d]+)',
        r'cd[ _\.-]*([0-9a-d]+)$',
        r'dvd[ _\.-]*([0-9a-d]+)$',
        r'part[ _\.-]*([0-9a-d]+)$',
        r'dis[ck][ _\.-]*([0-9a-d]+)$',
        r'()[ _\.-]+([0-9]*[abcd]+)(\.....?)$',
        r'([a-z])([0-9]+)(\.....?)$',
        r'()([ab])(\.....?)$',
    ]

    cp_imdb = r'\.cp\((?P<id>tt[0-9]+),?\s?(?P<random>[A-Za-z0-9]+)?\)'

    def scan(self, folder=None, files=None, release_download=None, simple=False,
             newer_than=0, return_ignored=True, check_file_date=True, on_found=None,
             require_complete=False):

        folder = sp(folder)

        if not folder or not os.path.isdir(folder):
            self._log_diagnostic(log.error, 'Folder doesn\'t exists: %s', folder)
            return None if require_complete else {}

        gathering_complete = True

        if not files:
            files, gathering_complete = self._gatherFiles(folder)

            self._log_diagnostic(log.debug, 'Found %s files to scan and group in %s', len(files), folder)
        else:
            check_file_date = False
            files = [sp(x) for x in files]

        movie_files, leftovers, qualified_movie_files, classification_complete = (
            self._classify_scan_files(files, folder, require_complete)
        )
        gathering_complete = gathering_complete and classification_complete
        del files

        leftovers, ignored_identifiers = self._attach_matching_sidecars(movie_files, set(leftovers))
        leftovers, path_identifiers = self._attach_leftovers_by_identifier(movie_files, leftovers, folder)
        self._attach_leftovers_by_folder(movie_files, leftovers, path_identifiers, folder)

        valid_files = self._filter_scan_groups(movie_files, check_file_date, newer_than)

        release_download = self._scan_release_download(release_download, len(valid_files))

        processed_movies, groups_complete = self._process_scan_groups(
            valid_files, ignored_identifiers, folder, release_download, simple,
            on_found, return_ignored, require_complete, qualified_movie_files,
        )
        gathering_complete = gathering_complete and groups_complete

        if len(processed_movies) > 0:
            self._log_diagnostic(log.info, 'Found %s movies in the folder %s', len(processed_movies), folder)
        else:
            self._log_diagnostic(log.debug, 'Found no movies in the folder %s', folder)

        # A library scan must not infer absence from a partial walk.
        # Keep callbacks for files already found, but withhold a success result.
        return processed_movies if (gathering_complete and not self.shuttingDown()) or not require_complete else None

    def _scan_release_download(self, release_download, total_found):
        """Retain a download identity only when it belongs to one group."""
        if release_download and total_found == 0:
            self._log_diagnostic(log.info,
                                 'Download ID provided (%s), but no groups found! Make sure the download contains valid media files (fully extracted).',
                                 release_download.get('imdb_id'))
        elif release_download and total_found > 1:
            self._log_diagnostic(log.info,
                                 'Download ID provided (%s), but more than one group found (%s). Ignoring Download ID...',
                                 release_download.get('imdb_id'), total_found)
            return None
        return release_download

    def _classify_scan_files(self, files, folder, require_complete):
        """Separate movie candidates from sidecars without losing stat failures."""
        movie_files = {}
        leftovers = []
        qualified_movie_files = set()
        complete = True
        for file_path in files:
            if not os.path.exists(file_path):
                complete = False
                continue

            if self.isSampleFile(file_path):
                leftovers.append(file_path)
                continue
            elif not self.keepFile(file_path):
                continue

            is_dvd_file = self.isDVDFile(file_path)
            is_movie_extension = getExt(file_path.lower()) in self.extensions['movie']
            movie_size_ok, size_failed = self._scan_movie_size(
                file_path, require_complete, is_movie_extension,
            )
            if size_failed:
                complete = False
                continue

            if movie_size_ok or is_dvd_file:
                self._add_movie_candidate(
                    movie_files, qualified_movie_files, file_path, folder, is_dvd_file,
                    require_complete and is_movie_extension and movie_size_ok,
                )
            else:
                leftovers.append(file_path)

            if self.shuttingDown():
                break
        return movie_files, leftovers, qualified_movie_files, complete

    def _scan_movie_size(self, file_path, require_complete, is_movie_extension):
        """Return size eligibility and whether a required stat failed."""
        if require_complete and is_movie_extension:
            # Use the size we actually checked for classification. A second
            # stat can fail after an earlier one succeeds on NFS.
            file_size = self.getFileSize(file_path)
            if file_size is None:
                return False, True
            return (self.file_sizes['movie'].get('min', 0) < file_size
                    < self.file_sizes['movie'].get('max', 100000)), False
        return self.filesizeBetween(file_path, self.file_sizes['movie']), False

    def _add_movie_candidate(self, movie_files, qualified_movie_files, file_path,
                             folder, is_dvd_file, qualified):
        """Add one candidate without changing its quality or identifier order."""
        if qualified:
            qualified_movie_files.add(file_path)
        identifier = self.createStringIdentifier(file_path, folder, exclude_filename=is_dvd_file)
        identifiers = [identifier]

        quality = fireEvent('quality.guess', files=[file_path], size=self.getFileSize(file_path), single=True) if not is_dvd_file else {'identifier': 'dvdr'}
        if quality:
            identifier_with_quality = '%s %s' % (identifier, quality.get('identifier', ''))
            identifiers = [identifier_with_quality, identifier]

        if not movie_files.get(identifier):
            movie_files[identifier] = {
                'unsorted_files': [],
                'identifiers': identifiers,
                'is_dvd': is_dvd_file,
            }
        movie_files[identifier]['unsorted_files'].append(file_path)

    def _attach_matching_sidecars(self, movie_files, leftovers):
        """Attach files sharing a movie basename and note ignored extensions."""
        ignored_identifiers = []
        for identifier, group in movie_files.items():
            if identifier not in group['identifiers'] and len(identifier) > 0:
                group['identifiers'].append(identifier)

            self._log_diagnostic(log.debug, 'Grouping files: %s', identifier)

            leftovers, has_ignored = self._match_group_sidecars(group, leftovers)
            if not has_ignored:
                has_ignored = self._group_has_ignored_extension(group)

            if has_ignored:
                ignored_identifiers.append(identifier)

            if self.shuttingDown():
                break
        return leftovers, ignored_identifiers

    def _match_group_sidecars(self, group, leftovers):
        """Attach basename matches using the original group-file snapshot."""
        has_ignored = 0
        for file_path in list(group['unsorted_files']):
            ext = getExt(file_path)
            wo_ext = file_path[:-(len(ext) + 1)]
            found_files = set([item for item in leftovers if wo_ext in item])
            group['unsorted_files'].extend(found_files)
            leftovers = leftovers - found_files
            has_ignored += 1 if ext in self.ignored_extensions else 0
        return leftovers, has_ignored

    def _group_has_ignored_extension(self, group):
        """Check sidecars attached after the first extension pass."""
        has_ignored = 0
        for file_path in list(group['unsorted_files']):
            ext = getExt(file_path)
            has_ignored += 1 if ext in self.ignored_extensions else 0
        return has_ignored

    def _attach_leftovers_by_identifier(self, movie_files, leftovers, folder):
        """Attach remaining files whose derived identifier matches a movie."""
        path_identifiers = {}
        for file_path in leftovers:
            identifier = self.createStringIdentifier(file_path, folder)
            if not path_identifiers.get(identifier):
                path_identifiers[identifier] = []
            path_identifiers[identifier].append(file_path)

        delete_identifiers = []
        for identifier, found_files in path_identifiers.items():
            self._log_diagnostic(log.debug, 'Grouping files on identifier: %s', identifier)
            group = movie_files.get(identifier)
            if group:
                group['unsorted_files'].extend(found_files)
                delete_identifiers.append(identifier)
                leftovers = leftovers - set(found_files)
            if self.shuttingDown():
                break

        for identifier in delete_identifiers:
            if path_identifiers.get(identifier):
                del path_identifiers[identifier]
        return leftovers, path_identifiers

    def _attach_leftovers_by_folder(self, movie_files, leftovers, path_identifiers, folder):
        """Preserve the legacy folder-name fallback for unmatched sidecars."""
        delete_identifiers = []
        for identifier, found_files in path_identifiers.items():
            self._log_diagnostic(log.debug, 'Grouping files on foldername: %s', identifier)
            for ff in found_files:
                new_identifier = self.createStringIdentifier(os.path.dirname(ff), folder)
                group = movie_files.get(new_identifier)
                if group:
                    group['unsorted_files'].extend([ff])
                    delete_identifiers.append(identifier)
                    leftovers -= leftovers - set([ff])
            if self.shuttingDown():
                break

        if leftovers:
            self._log_diagnostic(log.debug, 'Some files are still left over: %s', leftovers)

        for identifier in delete_identifiers:
            if path_identifiers.get(identifier):
                del path_identifiers[identifier]

    def _process_scan_groups(self, valid_files, ignored_identifiers, folder,
                             release_download, simple, on_found, return_ignored,
                             require_complete, qualified_movie_files):
        """Process groups in legacy pop order and retain callback counts."""
        total_found = len(valid_files)
        processed_movies = {}
        complete = True
        while not self.shuttingDown():
            try:
                identifier, group = valid_files.popitem()
            except Exception:
                break

            if return_ignored is False and identifier in ignored_identifiers:
                self._log_diagnostic(log.debug, 'Ignore file found, ignoring release: %s', identifier)
                total_found -= 1
                continue

            if not self._categorise_scan_group(group, require_complete, qualified_movie_files):
                complete = False

            if len(group['files']['movie']) == 0:
                complete = False
                self._log_diagnostic(log.error, 'Couldn\'t find any movie files for %s', identifier)
                total_found -= 1
                continue

            self._finish_scan_group(identifier, group, folder, release_download, simple)
            processed_movies[identifier] = group

            if on_found:
                on_found(group, total_found, len(valid_files))

            while threading.activeCount() > 100 and not self.shuttingDown():
                self._log_diagnostic(log.debug, 'Too many threads active, waiting a few seconds')
                time.sleep(10)
        return processed_movies, complete

    def _categorise_scan_group(self, group, require_complete, qualified_movie_files):
        """Build file buckets and report a lost, previously qualified movie."""
        group['files'] = {
            'movie_extra': self.getMovieExtras(group['unsorted_files']),
            'subtitle': self.getSubtitles(group['unsorted_files']),
            'subtitle_extra': self.getSubtitlesExtras(group['unsorted_files']),
            'nfo': self.getNfo(group['unsorted_files']),
            'trailer': self.getTrailers(group['unsorted_files']),
            'leftover': set(group['unsorted_files']),
        }

        if group['is_dvd']:
            group['files']['movie'] = self.getDVDFiles(group['unsorted_files'])
        else:
            group['files']['movie'] = self.getMediaFiles(group['unsorted_files'])

        # getMediaFiles performs another size check. If it lost a previously
        # qualified movie, this is not absence evidence.
        return not (require_complete and (qualified_movie_files & set(group['unsorted_files']))
                    - set(group['files']['movie']))

    def _finish_scan_group(self, identifier, group, folder, release_download, simple):
        """Add metadata and an identity to a group with at least one movie."""
        self._log_diagnostic(log.debug, 'Getting metadata for %s', identifier)
        group['meta_data'] = self.getMetaData(group, folder=folder, release_download=release_download)
        group['subtitle_language'] = self.getSubtitleLanguage(group) if not simple else {}

        for movie_file in group['files']['movie']:
            group['parentdir'] = os.path.dirname(movie_file)
            group['dirname'] = None

            folder_names = group['parentdir'].replace(folder, '').split(os.path.sep)
            folder_names.reverse()

            for folder_name in folder_names:
                if folder_name.lower() not in self.ignore_names and len(folder_name) > 2:
                    group['dirname'] = folder_name
                    break
            break

        for file_type in group['files']:
            if file_type != 'leftover':
                group['files']['leftover'] -= set(group['files'][file_type])
                group['files'][file_type] = list(group['files'][file_type])
        group['files']['leftover'] = list(group['files']['leftover'])

        del group['unsorted_files']

        group['media'] = self.determineMedia(group, release_download=release_download)
        if not group['media']:
            self._log_diagnostic(log.error, 'Unable to determine media: %s', group['identifiers'])
        else:
            group['identifier'] = getIdentifier(group['media']) or group['media']['info'].get('imdb')

    def _filter_scan_groups(self, movie_files, check_file_date, newer_than):
        """Keep only groups ready for this scan, retaining pop order."""
        valid_files = {}
        while not self.shuttingDown():
            try:
                identifier, group = movie_files.popitem()
            except Exception:
                break

            if not self._scan_group_is_current(identifier, group, check_file_date, newer_than):
                del group['unsorted_files']
                continue

            valid_files[identifier] = group
        return valid_files

    def _scan_group_is_current(self, identifier, group, check_file_date, newer_than):
        """Apply unpacking and incremental filters in their original order."""
        if check_file_date:
            files_too_new, time_string = self.checkFilesChanged(group['unsorted_files'])
            if files_too_new:
                self._log_diagnostic(log.info,
                                     'Files seem to be still unpacking or just unpacked (created on %s), ignoring for now: %s',
                                     time_string, identifier)
                return False

        if newer_than and newer_than > 0 and not self._group_has_new_files(group, newer_than):
            self._log_diagnostic(log.debug,
                                 'None of the files have changed since %s for %s, skipping.',
                                 time.ctime(newer_than), identifier)
            return False
        return True

    def _group_has_new_files(self, group, newer_than):
        for cur_file in group['unsorted_files']:
            file_time = self.getFileTimes(cur_file)
            if file_time[0] > newer_than or file_time[1] > newer_than:
                return True
        return False

    def _gatherFiles(self, folder):
        """Walk `folder` and return every file found inside it.

        Any entry (whether reached directly or via a symlinked directory)
        whose real path resolves outside `folder` is skipped. Without this,
        a symlink planted inside a release folder can point at an arbitrary
        file elsewhere on disk (e.g. a large host file); once "scanned" as
        a movie file, the renamer would move/delete the real target instead
        of the symlink. `os.walk`'s `followlinks` flag does not help here --
        it only controls recursion into symlinked *directories*, symlinked
        *files* are listed regardless of that flag -- so containment has to
        be checked per file. REG-003 item 2.

        Escaping symlinked *directories* are additionally pruned in place
        (`dirs[:] = ...`) BEFORE os.walk recurses into them. Filtering only
        per-file would let os.walk fully enumerate the escape target first
        (an NFS mount, /proc, another library) -- a scan-time perf/DoS hit --
        and, since `followlinks=True` has no loop detection, a dir symlink
        chain could otherwise be followed until the OS symlink limit. Pruning
        keeps the "whole scanned folder is itself a symlink" case working
        (its own realpath is the containment boundary) while stopping descent
        into inner escaping symlinked dirs. The per-file check is retained as
        belt-and-braces for file symlinks. PR #151 review.

        Return the files gathered and whether the walk completed. On an error,
        keep files already found for normal scanner callers, but let a full
        library scan refuse to use the partial result as cleanup evidence.
        """
        real_folder = os.path.realpath(folder)

        found_files = []
        complete = True

        def record_walk_error(error):
            # Let os.walk continue into accessible siblings, while library
            # scans still know the directory was not completely examined.
            nonlocal complete
            complete = False
            self._log_diagnostic(log.error, 'Failed gathering files (%s); scan incomplete.',
                                 type(error).__name__)

        try:
            for root, dirs, walk_files in os.walk(folder, followlinks=True,
                                                 onerror=record_walk_error):
                # Prune escaping symlinked subdirs before descending into them.
                dirs[:] = [d for d in dirs
                           if self._isWithinFolder(os.path.join(root, d), real_folder)]

                for filename in walk_files:
                    file_path = sp(os.path.join(sp(root), sp(filename)))

                    if not self._isWithinFolder(file_path, real_folder):
                        self._log_diagnostic(log.debug,
                                             'Skipping file that resolves outside the scanned folder (symlink escape): %s',
                                             file_path)
                        continue

                    found_files.append(file_path)

                if self.shuttingDown():
                    break
        except Exception as error:
            complete = False
            self._log_diagnostic(log.error, 'Failed gathering files (%s); scan incomplete.',
                                 type(error).__name__)

        return found_files, complete

    @staticmethod
    def _isWithinFolder(file_path, real_folder):
        try:
            real_path = os.path.realpath(file_path)
            return os.path.commonpath([real_folder, real_path]) == real_folder
        except ValueError:
            # e.g. paths on different drives on Windows
            return False

    @staticmethod
    def _log_diagnostic(logger, message, *args):
        # A failed logger must not turn a directory scan into a partial result.
        try:
            logger(message, *args)
        except Exception:
            pass

    def _imdb_from_cp_tag(self, group):
        for cur_file in group['files']['movie']:
            imdb_id = self.getCPImdb(cur_file)
            if imdb_id:
                group['identity_source'] = 'cp_tag'
                self._log_diagnostic(log.debug, 'Found movie via CP tag: %s', cur_file)
                return imdb_id
        return None

    def _imdb_from_nfo(self, group):
        for nf in group['files'].get('nfo', ()):
            try:
                imdb_id = getImdb(nf, check_inside=True)
            except Exception:
                continue
            if imdb_id:
                group['identity_source'] = 'nfo'
                self._log_diagnostic(log.debug, 'Found movie via nfo file: %s', nf)
                return imdb_id
        return None

    def _imdb_from_filename(self, group):
        # Stop at the first hit across all file types. A later file must not
        # erase the ID or replace it with a different movie's ID.
        for filetype in group['files']:
            for filetype_file in group['files'][filetype]:
                try:
                    found = getImdb(filetype_file)
                except Exception:
                    continue
                if found:
                    group['identity_source'] = 'filename'
                    self._log_diagnostic(log.debug,
                                       'Found movie via imdb in filename: %s',
                                       filetype_file)
                    return found
        return None

    @staticmethod
    def _search_year_candidates(name_year):
        search_q = '%(name)s %(year)s' % name_year
        movie = fireEvent('movie.search', q=search_q, merge=True,
                          limit=SEARCH_YEAR_DISAMBIGUATION_LIMIT,
                          search_type='phrase')
        parsed_year = name_year.get('year')

        if len(movie) == 0:
            other = name_year.get('other')
            if other and other.get('name') and other.get('year'):
                search_q2 = '%(name)s %(year)s' % other
                if search_q2 != search_q:
                    movie = fireEvent('movie.search', q=search_q2, merge=True,
                                      limit=SEARCH_YEAR_DISAMBIGUATION_LIMIT,
                                      search_type='phrase')
                    # The alternate parse can imply a different year.
                    parsed_year = other.get('year')

        return movie, parsed_year

    def _search_identifier(self, identifier, group):
        try:
            filename = next(iter(group['files'].get('movie') or ()), None)
        except Exception:
            filename = None

        name_year = self.getReleaseNameYear(
            identifier, file_name=filename if not group['is_dvd'] else None,
        )
        if not name_year.get('name') or not name_year.get('year'):
            return None

        movie, parsed_year = self._search_year_candidates(name_year)
        if len(movie) == 0:
            return None

        chosen = self.pickSearchYearMatch(movie, parsed_year, filename)
        imdb_id = chosen.get('imdb')
        # A searched identity is a guess, never authority to replace a file.
        group['identity_source'] = 'search'
        self._log_diagnostic(log.debug, 'Found movie via search: %s', identifier)
        return imdb_id

    def _imdb_from_search(self, group):
        for identifier in group['identifiers']:
            if len(identifier) > 2:
                try:
                    imdb_id = self._search_identifier(identifier, group)
                    if imdb_id:
                        return imdb_id
                except Exception:
                    # A provider failure must not abort the directory scan:
                    # a partial scan can make library cleanup delete movies.
                    self._log_diagnostic(log.debug,
                                       'Search-based identification failed for %s: %s',
                                       identifier, traceback.format_exc())
            else:
                self._log_diagnostic(log.debug,
                                   'Identifier to short to use for search: %s',
                                   identifier)
        return None

    def determineMedia(self, group, release_download=None):
        """Identify the movie this group is, and record HOW it was identified.

        `group['identity_source']` is written on every path. Four of the five
        sources are assertions about this exact release -- the downloader's
        own imdb id, a CP tag, an NFO, an id in the filename. The fifth is a
        fuzzy title-and-year search, which is a GUESS: it returns the best
        match for a parsed name, not a verified identity.

        That distinction did not matter while the scanner only ever added
        files. Upgrade replacement made it matter, because a wrong guess there
        does not mis-file a download, it destroys a different movie's library
        copy. The renamer refuses to replace on a searched identity for that
        reason, so this field is load-bearing rather than informational.
        """
        group['identity_source'] = None
        imdb_id = release_download and release_download.get('imdb_id')
        if imdb_id:
            group['identity_source'] = 'download_id'
            self._log_diagnostic(log.debug, 'Found movie via imdb id from it\'s download id: %s',
                               release_download.get('imdb_id'))

        if not imdb_id:
            imdb_id = self._imdb_from_cp_tag(group)

        if not imdb_id:
            imdb_id = self._imdb_from_nfo(group)

        if not imdb_id:
            imdb_id = self._imdb_from_filename(group)

        if not imdb_id:
            imdb_id = self._imdb_from_search(group)

        if imdb_id:
            try:
                db = get_db()
                return db.get('media', 'imdb-%s' % imdb_id, with_doc=True)['doc']
            except Exception:
                self._log_diagnostic(log.debug, 'Movie "%s" not in library, just getting info', imdb_id)
                return {
                    'identifier': imdb_id,
                    'info': fireEvent('movie.info', identifier=imdb_id, merge=True, extended=False)
                }

        self._log_diagnostic(log.error,
                           'No imdb_id found for %s. Add a NFO file with IMDB id or add the year to the filename.',
                           group['identifiers'])
        return {}

    def pickSearchYearMatch(self, candidates, parsed_year, filename):
        """BUG-018: choose which search result to trust as the identity.

        The provider does not rank on year, so it routinely returns a
        remake's original release ahead of the film actually named in the
        filename (measured live: Mulan 2020, Aladdin 2019, Mean Girls 2024
        and Lion King 2019 were all in second place). Return the FIRST
        candidate whose year is within `SEARCH_YEAR_TOLERANCE` of the parsed
        year, in list order, among candidates that carry an id.

        Round two tried scoring every candidate and taking the CLOSEST one
        within tolerance instead of the first, to close the two
        consecutive-year sequel merges recorded as debt below -- and
        reverted it after measuring it live. The query this fallback sends
        carries `year=<parsed year>`, so the result set is routinely stuffed
        with exact-parsed-year candidates. Closest-wins hands the win to
        that exact-year candidate whenever the CORRECT film is the one an
        honest one-year discrepancy applies to -- which is exactly the case
        `SEARCH_YEAR_TOLERANCE` exists to absorb, not a rare edge:

            search "Wicked 2025"     -> 0. Wicked (2024) CORRECT   1. Wicked: For Good (2025)
            search "Nosferatu 2025"  -> 0. Nosferatu (2024) CORRECT 1. Nosferatu (2025)
            search "Anora 2025"      -> 0. Anora (2024) CORRECT     1. Anora: Stripped Down (2025)

        Under closest-wins the position-1 exact-year decoy beats the correct
        film at position 0 in all three. First-within-tolerance gets all
        three right, and is what this function does again. The consecutive-
        year sequel merges closest-wins was meant to fix stay UNFIXED at
        tolerance 1 whenever the provider lists the earlier part first --
        see the spec's Recorded debt item 1.

        Round-one review of 0dc9e9a78 (FIX 1): having an id is part of the
        SELECTION PREDICATE, not a property checked on the result
        afterwards. A candidate is only eligible to be chosen for its year
        at all if it also carries a non-empty `imdb`, so this function is
        structurally unable to return a candidate with no id, an empty id,
        or `imdb: None` -- there is no code path that returns one. Without
        that filter, a year-matching candidate lacking an id (a live hazard:
        TMDB's own `movie.get('imdb_id')` is `None` for some records) would
        starve `imdb_id` in the caller even though a DIFFERENT, id-bearing
        candidate was available in the same list.

        `candidates` is assumed non-empty; the caller only reaches here
        after checking `len(movie) > 0`. When nothing both has an id AND
        matches within tolerance, `candidates[0]` is returned UNCHANGED --
        exactly what the pre-BUG-018 code always returned, id or no id.
        This is the safety property the withdrawn first design broke:
        returning `None` here, where the old code returned an id, makes
        `manage.updateLibrary` believe a still-owned film is gone and
        delete it. The result of this function is therefore never worse
        than taking `candidates[0]` unconditionally; it can only ever
        differ by choosing a BETTER identifier for the same input. A
        mismatched guess is logged so the operator can see it; it is
        never refused.
        """
        def _imdb(candidate):
            try:
                return candidate.get('imdb')
            except Exception:
                # Round-two review of 0dc9e9a78 (FIX 4b): the comment above
                # this function already justifies the guard as "the moment
                # a second provider is registered", which is broader than
                # AttributeError alone -- a malformed candidate could raise
                # anything out of `.get`, not only from lacking the method.
                return None

        def _year(candidate):
            try:
                return candidate.get('year')
            except Exception:
                return None

        for candidate in candidates:
            if not _imdb(candidate):
                continue
            year = _year(candidate)
            # No separate `year is None` check: `int(None)` raises
            # TypeError, already caught below, so the check would be dead
            # code -- it can never short-circuit anything the except clause
            # does not already handle.
            try:
                diff = abs(int(year) - int(parsed_year))
            except (TypeError, ValueError):
                continue
            if diff <= SEARCH_YEAR_TOLERANCE:
                return candidate

        first = candidates[0]
        offered_years = [_year(c) for c in candidates]
        try:
            # Round-two review of 0dc9e9a78 (FIX 4a): this used to sit
            # unguarded inside the caller's `except Exception:` (determineMedia's
            # search try/except). A non-str/bytes/PathLike `filename` makes
            # `os.path.basename` raise TypeError, which that outer guard then
            # swallows -- aborting identification for this identifier
            # entirely, exactly the data-loss shape the guard exists to
            # prevent, just triggered from inside this warning instead of
            # the search itself.
            logged_filename = os.path.basename(filename) if filename else filename
        except TypeError:
            # `filename` is not str/bytes/PathLike, so there is no basename
            # to take -- and the value itself might still be, or contain, a
            # full path (round-two review of BUG-018, FIX 5). Log only the
            # type, never the raw value, to honour the basename-only
            # promise below.
            logged_filename = type(filename).__name__
        self._log_diagnostic(log.warning,
            'No search result for "%s" matched the parsed year %s within '
            'tolerance (years offered: %s) -- taking the first result %s. '
            'This guess is not destructive on its own, but is worth '
            'checking.',
            # A basename, not the full path: matches the DEBUG-level path
            # logging elsewhere in this module, and this is the one path in
            # the fallback that reaches WARNING (project security floor: no
            # private filesystem paths in logs). The filename is still
            # enough for an operator to find the release; the download
            # folder structure around it is not needed to do that.
            logged_filename,
            parsed_year, offered_years, _imdb(first),
        )
        return first

    def getCPImdb(self, string):
        try:
            m = re.search(self.cp_imdb, string.lower())
            id = m.group('id')
            if id:
                return id
        except AttributeError:
            pass
        return False

    def removeCPTag(self, name):
        try:
            return re.sub(self.cp_imdb, '', name).strip()
        except Exception:
            pass
        return name

    def createStringIdentifier(self, file_path, folder='', exclude_filename=False):
        identifier = file_path.replace(folder, '').lstrip(os.path.sep)
        identifier = os.path.splitext(identifier)[0]

        if exclude_filename:
            identifier = identifier[:len(identifier) - len(os.path.split(identifier)[-1])]

        identifier = identifier.lower()

        try:
            path_split = splitString(identifier, os.path.sep)
            identifier = path_split[-2] if len(path_split) > 1 and len(path_split[-2]) > len(path_split[-1]) else path_split[-1]
        except Exception:
            pass

        identifier = self.removeMultipart(identifier)
        identifier = self.removeCPTag(identifier)
        identifier = simplifyString(identifier)

        year = self.findYear(file_path)

        identifier = re.sub(self.clean, '::', identifier).strip(':')

        if year and identifier[:4] != year:
            split_by = ':::' if ':::' in identifier else year
            identifier = '%s %s' % (identifier.split(split_by)[0].strip(), year)
        else:
            identifier = identifier.split('::')[0]

        out = []
        for word in identifier.split():
            if not word in out:
                out.append(word)

        identifier = ' '.join(out)
        return simplifyString(identifier)

    def removeMultipart(self, name):
        for regex in self.multipart_regex:
            try:
                found = re.sub(regex, '', name)
                if found != name:
                    name = found
            except Exception:
                pass
        return name

    def getPartNumber(self, name):
        for regex in self.multipart_regex:
            try:
                found = re.search(regex, name)
                if found:
                    return found.group(1)
                return 1
            except Exception:
                pass
        return 1

    def findYear(self, text):
        matches = re.findall(r'(\(|\[)(?P<year>19[0-9]{2}|20[0-9]{2})(\]|\))', text)
        if matches:
            return matches[-1][1]

        matches = re.findall('(?P<year>19[0-9]{2}|20[0-9]{2})', text)
        if matches:
            return matches[-1]
        return ''

    def getReleaseNameYear(self, release_name, file_name=None):
        release_name = release_name.strip(' .-_')

        guess = {}
        if file_name:
            try:
                guessit = guess_movie_info(toUnicode(file_name))
                if guessit.get('title') and guessit.get('year'):
                    guess = {
                        'name': guessit.get('title'),
                        'year': guessit.get('year'),
                    }
            except Exception:
                self._log_diagnostic(log.debug, 'Could not detect via guessit "%s": %s',
                                     file_name, traceback.format_exc())

        release_name = os.path.basename(release_name.replace('\\', '/'))
        cleaned = ' '.join(re.split(r'\W+', simplifyString(release_name)))
        cleaned = re.sub(self.clean, ' ', cleaned)

        year = None
        for year_str in [file_name, release_name, cleaned]:
            if not year_str:
                continue
            year = self.findYear(year_str)
            if year:
                break

        cp_guess = {}

        if year:
            try:
                movie_name = cleaned.rsplit(year, 1).pop(0).strip()
                if movie_name:
                    cp_guess = {
                        'name': movie_name,
                        'year': int(year),
                    }
            except Exception:
                pass

        if not cp_guess:
            try:
                movie_name = cleaned.split('  ').pop(0).strip()
                cp_guess = {
                    'name': movie_name,
                    'year': int(year) if movie_name[:4] != year else 0,
                }
            except Exception:
                pass

        if cp_guess.get('year') == guess.get('year') and len(cp_guess.get('name', '')) > len(guess.get('name', '')):
            cp_guess['other'] = guess
            return cp_guess
        elif guess == {}:
            cp_guess['other'] = guess
            return cp_guess

        guess['other'] = cp_guess
        return guess
