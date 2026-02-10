"""Media metadata extraction for the Scanner plugin."""

import os
import re
import traceback

from couchpotato.core.event import fireEvent
from couchpotato.core.helpers.encoding import sp, ss, toUnicode
from couchpotato.core.helpers.variable import tryInt
from couchpotato.core.logger import CPLog

try:
    import enzyme
except ImportError:
    enzyme = None

try:
    from couchpotato.lib.subliminal.videos import Video
except ImportError:
    Video = None

log = CPLog(__name__)


class MediaParserMixin:
    """Mixin providing media metadata extraction, codec detection, and resolution parsing."""

    threed_types = {
        'Half SBS': [('half', 'sbs'), ('h', 'sbs'), 'hsbs'],
        'Full SBS': [('full', 'sbs'), ('f', 'sbs'), 'fsbs'],
        'SBS': ['sbs'],
        'Half OU': [('half', 'ou'), ('h', 'ou'), ('half', 'tab'), ('h', 'tab'), 'htab', 'hou'],
        'Full OU': [('full', 'ou'), ('f', 'ou'), ('full', 'tab'), ('f', 'tab'), 'ftab', 'fou'],
        'OU': ['ou', 'tab'],
        'Frame Packed': ['mvc', ('complete', 'bluray')],
        '3D': ['3d'],
    }

    codecs = {
        'audio': ['DTS', 'AC3', 'AC3D', 'MP3'],
        'video': ['x264', 'H264', 'x265', 'H265', 'DivX', 'Xvid'],
    }

    resolutions = {
        '2160p': {'resolution_width': 3840, 'resolution_height': 2160, 'aspect': 1.78},
        '1080p': {'resolution_width': 1920, 'resolution_height': 1080, 'aspect': 1.78},
        '1080i': {'resolution_width': 1920, 'resolution_height': 1080, 'aspect': 1.78},
        '720p': {'resolution_width': 1280, 'resolution_height': 720, 'aspect': 1.78},
        '720i': {'resolution_width': 1280, 'resolution_height': 720, 'aspect': 1.78},
        '480p': {'resolution_width': 640, 'resolution_height': 480, 'aspect': 1.33},
        '480i': {'resolution_width': 640, 'resolution_height': 480, 'aspect': 1.33},
        'default': {'resolution_width': 0, 'resolution_height': 0, 'aspect': 1},
    }

    audio_codec_map = {
        0x2000: 'AC3',
        0x2001: 'DTS',
        0x0055: 'MP3',
        0x0050: 'MP2',
        0x0001: 'PCM',
        0x003: 'WAV',
        0x77a1: 'TTA1',
        0x5756: 'WAV',
        0x6750: 'Vorbis',
        0xF1AC: 'FLAC',
        0x00ff: 'AAC',
    }

    source_media = {
        'Blu-ray': ['bluray', 'blu-ray', 'brrip', 'br-rip'],
        'HD DVD': ['hddvd', 'hd-dvd'],
        'DVD': ['dvd'],
        'HDTV': ['hdtv'],
    }

    def getMetaData(self, group, folder='', release_download=None):
        data = {}
        files = list(group['files']['movie'])

        for cur_file in files:
            if not self.filesizeBetween(cur_file, self.file_sizes['movie']):
                continue

            if not data.get('audio'):
                meta = self.getMeta(cur_file)
                try:
                    data['titles'] = meta.get('titles', [])
                    data['video'] = meta.get('video', self.getCodec(cur_file, self.codecs['video']))
                    data['audio'] = meta.get('audio', self.getCodec(cur_file, self.codecs['audio']))
                    data['audio_channels'] = meta.get('audio_channels', 2.0)
                    if meta.get('resolution_width'):
                        data['resolution_width'] = meta.get('resolution_width')
                        data['resolution_height'] = meta.get('resolution_height')
                        data['aspect'] = round(float(meta.get('resolution_width')) / meta.get('resolution_height', 1), 2)
                    else:
                        data.update(self.getResolution(cur_file))
                except Exception:
                    log.debug('Error parsing metadata: %s %s', cur_file, traceback.format_exc())

            data['size'] = data.get('size', 0) + self.getFileSize(cur_file)

        data['quality'] = None
        quality = fireEvent('quality.guess', size=data.get('size'), files=files, extra=data, single=True)

        if release_download and release_download.get('quality'):
            data['quality'] = fireEvent('quality.single', release_download.get('quality'), single=True)
            data['quality']['is_3d'] = release_download.get('is_3d', 0)
            if data['quality']['identifier'] != quality['identifier']:
                log.info('Different quality snatched than detected for %s: %s vs. %s. Assuming snatched quality is correct.',
                         files[0], data['quality']['identifier'], quality['identifier'])
            if data['quality']['is_3d'] != quality['is_3d']:
                log.info('Different 3d snatched than detected for %s: %s vs. %s. Assuming snatched 3d is correct.',
                         files[0], data['quality']['is_3d'], quality['is_3d'])

        if not data['quality']:
            data['quality'] = quality
            if not data['quality']:
                data['quality'] = fireEvent('quality.single', 'dvdr' if group['is_dvd'] else 'dvdrip', single=True)

        data['quality_type'] = 'HD' if data.get('resolution_width', 0) >= 1280 or data['quality'].get('hd') else 'SD'

        filename = re.sub(self.cp_imdb, '', files[0])
        data['group'] = self.getGroup(filename[len(folder):])
        data['source'] = self.getSourceMedia(filename)
        if data['quality'].get('is_3d', 0):
            data['3d_type'] = self.get3dType(filename)
        return data

    def get3dType(self, filename):
        filename = toUnicode(filename)
        words = re.split(r'\W+', filename.lower())

        for key in self.threed_types:
            tags = self.threed_types.get(key, [])
            for tag in tags:
                if ((isinstance(tag, tuple) and '.'.join(tag) in '.'.join(words))
                        or (isinstance(tag, str) and tag.lower() in words)):
                    log.debug('Found %s in %s', tag, filename)
                    return key
        return ''

    def getMeta(self, filename):
        if not enzyme:
            return {}

        try:
            with open(filename, 'rb') as f:
                p = enzyme.MKV(f)
            info = p.info or object()
            video_tracks = p.video_tracks or []
            audio_tracks = p.audio_tracks or []

            if not video_tracks:
                return {}

            vt = video_tracks[0]
            vc = ('H264' if getattr(vt, 'codec_id', '') == 'V_MPEG4/ISO/AVC'
                  else 'x265' if getattr(vt, 'codec_id', '') == 'V_MPEGH/ISO/HEVC'
                  else getattr(vt, 'codec_id', ''))

            ac = ''
            if audio_tracks:
                at = audio_tracks[0]
                ac = self.audio_codec_map.get(getattr(at, 'codec_id', ''), getattr(at, 'codec_id', ''))

            titles = []
            try:
                title = getattr(info, 'title', None)
                if title and self.findYear(title):
                    titles.append(ss(title))
            except Exception:
                log.error('Failed getting title from meta: %s', traceback.format_exc())

            for vt2 in video_tracks:
                try:
                    vname = getattr(vt2, 'name', None)
                    if vname and self.findYear(vname):
                        titles.append(ss(vname))
                except Exception:
                    log.error('Failed getting title from meta: %s', traceback.format_exc())

            return {
                'titles': list(set(titles)),
                'video': vc,
                'audio': ac,
                'resolution_width': tryInt(getattr(vt, 'width', 0)),
                'resolution_height': tryInt(getattr(vt, 'height', 0)),
                'audio_channels': getattr(audio_tracks[0], 'channels', 0) if audio_tracks else 0,
            }
        except enzyme.exceptions.ParserError:
            log.debug('Failed to parse meta for %s', filename)
        except Exception:
            log.debug('Failed parsing %s', filename)

        return {}

    def getSubtitleLanguage(self, group):
        detected_languages = {}

        paths = None
        try:
            paths = group['files']['movie']
            scan_result = []
            for p in paths:
                if not group['is_dvd'] and Video:
                    video = Video.from_path(toUnicode(sp(p)))
                    video_result = [(video, video.scan())]
                    scan_result.extend(video_result)

            for video, detected_subtitles in scan_result:
                for s in detected_subtitles:
                    if s.language and s.path not in paths:
                        detected_languages[s.path] = [s.language]
        except Exception:
            log.debug('Failed parsing subtitle languages for %s: %s', paths, traceback.format_exc())

        for extra in group['files']['subtitle_extra']:
            try:
                if os.path.isfile(extra):
                    output = open(extra, 'r')
                    txt = output.read()
                    output.close()

                    idx_langs = re.findall('\nid: (\\w+)', txt)

                    sub_file = '%s.sub' % os.path.splitext(extra)[0]
                    if len(idx_langs) > 0 and os.path.isfile(sub_file):
                        detected_languages[sub_file] = idx_langs
            except Exception:
                log.error('Failed parsing subtitle idx for %s: %s', extra, traceback.format_exc())

        return detected_languages

    def getCodec(self, filename, codecs):
        codecs = map(re.escape, codecs)
        try:
            codec = re.search('[^A-Z0-9](?P<codec>' + '|'.join(codecs) + ')[^A-Z0-9]', filename, re.I)
            return (codec and codec.group('codec')) or ''
        except Exception:
            return ''

    def getResolution(self, filename):
        try:
            for key in self.resolutions:
                if key in filename.lower() and key != 'default':
                    return self.resolutions[key]
        except Exception:
            pass
        return self.resolutions['default']

    def getGroup(self, file):
        try:
            match = re.findall(r'\-([A-Z0-9]+)[\.\/]', file, re.I)
            return match[-1] or ''
        except Exception:
            return ''

    def getSourceMedia(self, file):
        for media in self.source_media:
            for alias in self.source_media[media]:
                if alias in file.lower():
                    return media
        return None
