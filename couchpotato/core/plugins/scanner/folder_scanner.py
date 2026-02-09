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
             newer_than=0, return_ignored=True, check_file_date=True, on_found=None):

        folder = sp(folder)

        if not folder or not os.path.isdir(folder):
            log.error('Folder doesn\'t exists: %s', folder)
            return {}

        movie_files = {}
        leftovers = []

        if not files:
            try:
                files = []
                for root, dirs, walk_files in os.walk(folder, followlinks=True):
                    files.extend([sp(os.path.join(sp(root), ss(filename))) for filename in walk_files])
                    if self.shuttingDown():
                        break
            except:
                log.error('Failed getting files from %s: %s', folder, traceback.format_exc())

            log.debug('Found %s files to scan and group in %s', len(files), folder)
        else:
            check_file_date = False
            files = [sp(x) for x in files]

        for file_path in files:
            if not os.path.exists(file_path):
                continue

            if self.isSampleFile(file_path):
                leftovers.append(file_path)
                continue
            elif not self.keepFile(file_path):
                continue

            is_dvd_file = self.isDVDFile(file_path)
            if self.filesizeBetween(file_path, self.file_sizes['movie']) or is_dvd_file:
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
            else:
                leftovers.append(file_path)

            if self.shuttingDown():
                break

        del files

        leftovers = set(sorted(leftovers, reverse=True))

        # Group files minus extension
        ignored_identifiers = []
        for identifier, group in movie_files.items():
            if identifier not in group['identifiers'] and len(identifier) > 0:
                group['identifiers'].append(identifier)

            log.debug('Grouping files: %s', identifier)

            has_ignored = 0
            for file_path in list(group['unsorted_files']):
                ext = getExt(file_path)
                wo_ext = file_path[:-(len(ext) + 1)]
                found_files = set([i for i in leftovers if wo_ext in i])
                group['unsorted_files'].extend(found_files)
                leftovers = leftovers - found_files
                has_ignored += 1 if ext in self.ignored_extensions else 0

            if has_ignored == 0:
                for file_path in list(group['unsorted_files']):
                    ext = getExt(file_path)
                    has_ignored += 1 if ext in self.ignored_extensions else 0

            if has_ignored > 0:
                ignored_identifiers.append(identifier)

            if self.shuttingDown():
                break

        # Create identifiers for leftover files
        path_identifiers = {}
        for file_path in leftovers:
            identifier = self.createStringIdentifier(file_path, folder)
            if not path_identifiers.get(identifier):
                path_identifiers[identifier] = []
            path_identifiers[identifier].append(file_path)

        # Group files based on identifier
        delete_identifiers = []
        for identifier, found_files in path_identifiers.items():
            log.debug('Grouping files on identifier: %s', identifier)
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
        del delete_identifiers

        # Group based on folder
        delete_identifiers = []
        for identifier, found_files in path_identifiers.items():
            log.debug('Grouping files on foldername: %s', identifier)
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
            log.debug('Some files are still left over: %s', leftovers)

        for identifier in delete_identifiers:
            if path_identifiers.get(identifier):
                del path_identifiers[identifier]
        del delete_identifiers

        # Filter out old/extracting files
        valid_files = {}
        while True and not self.shuttingDown():
            try:
                identifier, group = movie_files.popitem()
            except:
                break

            if check_file_date:
                files_too_new, time_string = self.checkFilesChanged(group['unsorted_files'])
                if files_too_new:
                    log.info('Files seem to be still unpacking or just unpacked (created on %s), ignoring for now: %s',
                             time_string, identifier)
                    del group['unsorted_files']
                    continue

            if newer_than and newer_than > 0:
                has_new_files = False
                for cur_file in group['unsorted_files']:
                    file_time = self.getFileTimes(cur_file)
                    if file_time[0] > newer_than or file_time[1] > newer_than:
                        has_new_files = True
                        break
                if not has_new_files:
                    log.debug('None of the files have changed since %s for %s, skipping.',
                              time.ctime(newer_than), identifier)
                    del group['unsorted_files']
                    continue

            valid_files[identifier] = group

        del movie_files

        total_found = len(valid_files)

        if release_download and total_found == 0:
            log.info('Download ID provided (%s), but no groups found! Make sure the download contains valid media files (fully extracted).',
                     release_download.get('imdb_id'))
        elif release_download and total_found > 1:
            log.info('Download ID provided (%s), but more than one group found (%s). Ignoring Download ID...',
                     release_download.get('imdb_id'), len(valid_files))
            release_download = None

        # Determine file types
        processed_movies = {}
        while True and not self.shuttingDown():
            try:
                identifier, group = valid_files.popitem()
            except:
                break

            if return_ignored is False and identifier in ignored_identifiers:
                log.debug('Ignore file found, ignoring release: %s', identifier)
                total_found -= 1
                continue

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

            if len(group['files']['movie']) == 0:
                log.error('Couldn\'t find any movie files for %s', identifier)
                total_found -= 1
                continue

            log.debug('Getting metadata for %s', identifier)
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
                if file_type is not 'leftover':
                    group['files']['leftover'] -= set(group['files'][file_type])
                    group['files'][file_type] = list(group['files'][file_type])
            group['files']['leftover'] = list(group['files']['leftover'])

            del group['unsorted_files']

            group['media'] = self.determineMedia(group, release_download=release_download)
            if not group['media']:
                log.error('Unable to determine media: %s', group['identifiers'])
            else:
                group['identifier'] = getIdentifier(group['media']) or group['media']['info'].get('imdb')

            processed_movies[identifier] = group

            if on_found:
                on_found(group, total_found, len(valid_files))

            while threading.activeCount() > 100 and not self.shuttingDown():
                log.debug('Too many threads active, waiting a few seconds')
                time.sleep(10)

        if len(processed_movies) > 0:
            log.info('Found %s movies in the folder %s', len(processed_movies), folder)
        else:
            log.debug('Found no movies in the folder %s', folder)

        return processed_movies

    def determineMedia(self, group, release_download=None):
        imdb_id = release_download and release_download.get('imdb_id')
        if imdb_id:
            log.debug('Found movie via imdb id from it\'s download id: %s', release_download.get('imdb_id'))

        files = group['files']

        if not imdb_id:
            for cur_file in files['movie']:
                imdb_id = self.getCPImdb(cur_file)
                if imdb_id:
                    log.debug('Found movie via CP tag: %s', cur_file)
                    break

        nfo_file = None
        if not imdb_id:
            try:
                for nf in files['nfo']:
                    imdb_id = getImdb(nf, check_inside=True)
                    if imdb_id:
                        log.debug('Found movie via nfo file: %s', nf)
                        nfo_file = nf
                        break
            except:
                pass

        if not imdb_id:
            try:
                for filetype in files:
                    for filetype_file in files[filetype]:
                        imdb_id = getImdb(filetype_file)
                        if imdb_id:
                            log.debug('Found movie via imdb in filename: %s', nfo_file)
                            break
            except:
                pass

        if not imdb_id:
            for identifier in group['identifiers']:
                if len(identifier) > 2:
                    try:
                        filename = list(group['files'].get('movie'))[0]
                    except:
                        filename = None

                    name_year = self.getReleaseNameYear(identifier, file_name=filename if not group['is_dvd'] else None)
                    if name_year.get('name') and name_year.get('year'):
                        search_q = '%(name)s %(year)s' % name_year
                        movie = fireEvent('movie.search', q=search_q, merge=True, limit=1)

                        if len(movie) == 0 and name_year.get('other') and name_year['other'].get('name') and name_year['other'].get('year'):
                            search_q2 = '%(name)s %(year)s' % name_year.get('other')
                            if search_q2 != search_q:
                                movie = fireEvent('movie.search', q=search_q2, merge=True, limit=1)

                        if len(movie) > 0:
                            imdb_id = movie[0].get('imdb')
                            log.debug('Found movie via search: %s', identifier)
                            if imdb_id:
                                break
                else:
                    log.debug('Identifier to short to use for search: %s', identifier)

        if imdb_id:
            try:
                db = get_db()
                return db.get('media', 'imdb-%s' % imdb_id, with_doc=True)['doc']
            except:
                log.debug('Movie "%s" not in library, just getting info', imdb_id)
                return {
                    'identifier': imdb_id,
                    'info': fireEvent('movie.info', identifier=imdb_id, merge=True, extended=False)
                }

        log.error('No imdb_id found for %s. Add a NFO file with IMDB id or add the year to the filename.',
                  group['identifiers'])
        return {}

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
        except:
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
        except:
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
            except:
                pass
        return name

    def getPartNumber(self, name):
        for regex in self.multipart_regex:
            try:
                found = re.search(regex, name)
                if found:
                    return found.group(1)
                return 1
            except:
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
            except:
                log.debug('Could not detect via guessit "%s": %s', file_name, traceback.format_exc())

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
            except:
                pass

        if not cp_guess:
            try:
                movie_name = cleaned.split('  ').pop(0).strip()
                cp_guess = {
                    'name': movie_name,
                    'year': int(year) if movie_name[:4] != year else 0,
                }
            except:
                pass

        if cp_guess.get('year') == guess.get('year') and len(cp_guess.get('name', '')) > len(guess.get('name', '')):
            cp_guess['other'] = guess
            return cp_guess
        elif guess == {}:
            cp_guess['other'] = guess
            return cp_guess

        guess['other'] = cp_guess
        return guess
