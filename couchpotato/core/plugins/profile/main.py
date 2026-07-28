import traceback

from couchpotato import get_db, tryInt
from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from .index import ProfileIndex


log = CPLog(__name__)


# Seeded on a fresh install by ProfilePlugin.fill().
#
# ORDER MATTERS: index 0 is the MOST preferred quality (see QualityPlugin
# .isHigher -- "a lower number means higher quality"), and MovieSearcher
# .single() walks this list in order and stops at the first successful
# download. So the first entry is effectively what a profile fetches.
#
# BUG-016: these used to be seeded worst-first -- 'Best' led with 720p and so
# never reached 1080p, and 'UHD 4K' led with 720p and so could never deliver
# 4K. Keep every list ordered best-first per the canonical ranking in
# QualityPlugin.qualities. Existing databases are repaired separately by
# couchpotato/core/migration/fix_profile_quality_order.py.
#
# The '3d' entries are consumed back-to-front by build_profile_doc(), so a
# profile's 3D rungs must come first in its qualities list.
DEFAULT_PROFILES = [{
    'label': 'Best',
    # Deliberately no 2160p: adding it here would silently switch existing
    # users onto 20-60GB downloads. Users who want 4K have 'UHD 4K'.
    'qualities': ['1080p', '720p', 'brrip', 'dvdrip']
}, {
    'label': 'HD',
    'qualities': ['1080p', '720p']
}, {
    'label': 'SD',
    'qualities': ['dvdr', 'dvdrip']
}, {
    'label': 'Prefer 3D HD',
    'qualities': ['1080p', '720p', '1080p', '720p'],
    '3d': [True, True]
}, {
    'label': '3D HD',
    'qualities': ['1080p', '720p'],
    '3d': [True, True]
}, {
    'label': 'UHD 4K',
    'qualities': ['2160p', '1080p', '720p']
}]


def build_profile_doc(profile, order):
    """Expand a DEFAULT_PROFILES entry into the document stored in the db.

    `finish`/`wait_for`/`stop_after`/`3d` are positional siblings of
    `qualities` -- entry N of each describes rung N -- so they are always
    built to the same length. Defaults are "take the best thing available
    now, then stop" (finish, no waiting).
    """
    doc = {
        '_t': 'profile',
        'label': toUnicode(profile.get('label')),
        'order': order,
        'qualities': profile.get('qualities'),
        'minimum_score': 1,
        # FEAT-004: the review gate is ON for seeded profiles. A completed
        # download waits for confirmation instead of auto-promoting to 'done'
        # -- the decision DOWNLOADED-REVIEW-WORKFLOW.md made, which the
        # original compatibility default (off) inverted in practice.
        'manual_confirmation': True,
        'finish': [],
        'wait_for': [],
        'stop_after': [],
        '3d': []
    }

    threed = list(profile.get('3d', []))
    for _ in profile.get('qualities'):
        doc['finish'].append(True)
        doc['wait_for'].append(0)
        doc['stop_after'].append(0)
        doc['3d'].append(threed.pop() if threed else False)

    return doc


class ProfilePlugin(Plugin):

    _database = {
        'profile': ProfileIndex
    }

    def __init__(self):
        addEvent('profile.all', self.all)
        addEvent('profile.default', self.default)

        addApiView('profile.save', self.save)
        addApiView('profile.save_order', self.saveOrder)
        addApiView('profile.delete', self.delete)
        addApiView('profile.list', self.allView, docs = {
            'desc': 'List all available profiles',
            'return': {'type': 'object', 'example': """{
            'success': True,
            'list': array, profiles
}"""}
        })

        addEvent('app.initialize', self.fill, priority = 90)
        addEvent('app.load', self.forceDefaults, priority = 110)

    def forceDefaults(self):

        db = get_db()

        # Fill qualities and profiles if they are empty somehow..
        if db.count(db.all, 'profile') == 0:

            if db.count(db.all, 'quality') == 0:
                fireEvent('quality.fill', single = True)

            self.fill()

        # Get all active (or review-gated) movies without a valid profile.
        # 'downloaded' (workflow phase 2) movies still carry a profile_id that
        # restatus() and the future "mark failed & re-search" action depend
        # on, so a dangling reference needs the same repair-to-default an
        # 'active' movie gets -- otherwise a review-gated movie whose profile
        # was deleted would be stuck with an unusable profile_id forever.
        try:
            medias = fireEvent('media.with_status', ['active', 'downloaded'], single = True)

            profile_ids = [x.get('_id') for x in self.all()]
            default_id = profile_ids[0]

            for media in medias:
                if media.get('profile_id') not in profile_ids:
                    media['profile_id'] = default_id
                    db.update(media)
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        # Cleanup profiles that have empty qualites
        profiles = self.all()
        for profile in profiles:
            try:
                if '' in profile.get('qualities') or '-1' in profile.get('qualities'):
                    log.warning('Found profile with empty qualities, cleaning it up')
                    p = db.get('id', profile.get('_id'))
                    p['qualities'] = [x for x in p['qualities'] if (x != '' and x != '-1')]
                    db.update(p)
            except Exception:
                log.error('Failed: %s', traceback.format_exc())

    def allView(self, **kwargs):

        return {
            'success': True,
            'list': self.all()
        }

    def all(self):

        db = get_db()
        profiles = db.all('profile', with_doc = True)

        return [x['doc'] for x in profiles]

    def save(self, **kwargs):

        try:
            db = get_db()

            profile = {
                '_t': 'profile',
                'label': toUnicode(kwargs.get('label')),
                'order': tryInt(kwargs.get('order', 999)),
                'core': kwargs.get('core', False),
                'minimum_score': tryInt(kwargs.get('minimum_score', 1)),
                # Workflow phase 2 (specs/DOWNLOADED-REVIEW-WORKFLOW.md): when
                # truthy, a completing download for a movie on this profile is
                # routed to the 'downloaded' review gate instead of 'done'
                # (see MediaPlugin.restatus).
                #
                # FEAT-004: NEW profiles default this ON -- the original
                # compatibility default of off inverted the workflow's own
                # decision, and in practice meant installs never reviewed
                # anything. The edit path below deliberately overrides this
                # with the PERSISTED value when the key is omitted: the live
                # profile editor does not resend it, and without that fallback
                # an existing profile's gate would flip on every save.
                'manual_confirmation': tryInt(kwargs.get('manual_confirmation', 1)) == 1,
                'qualities': [],
                'wait_for': [],
                'stop_after': [],
                'finish': [],
                '3d': []
            }

            # Update types
            order = 0
            for type in kwargs.get('types', []):
                profile['qualities'].append(type.get('quality'))
                profile['wait_for'].append(tryInt(kwargs.get('wait_for', 0)))
                profile['stop_after'].append(tryInt(kwargs.get('stop_after', 0)))
                profile['finish'].append((tryInt(type.get('finish')) == 1) if order > 0 else True)
                profile['3d'].append(tryInt(type.get('3d')))
                order += 1

            id = kwargs.get('id')
            try:
                p = db.get('id', id)
                profile['order'] = tryInt(kwargs.get('order', p.get('order', 999)))
                # Same fallback idiom as 'order' and 'manual_confirmation'
                # below, and for the same reason: the profile editor sends
                # id/label/minimum_score/wait_for/stop_after/types and never
                # 'core'. Without this, every edit of a built-in profile
                # cleared the flag -- which is what marks it non-deletable in
                # the settings UI -- so a routine rename made it deletable.
                profile['core'] = kwargs.get('core', p.get('core', False))
                # Fall back to the persisted value when the key is omitted, same
                # idiom as 'order' above. Without this, editing an existing
                # profile without resending manual_confirmation (as the live
                # profile editor always does today) silently resets it to False
                # on every save -- a blocking bug (workflow phase 2 review).
                profile['manual_confirmation'] = tryInt(kwargs.get('manual_confirmation', 1 if p.get('manual_confirmation') else 0)) == 1
            except Exception:
                p = db.insert(profile)

            p.update(profile)
            db.update(p)

            return {
                'success': True,
                'profile': p
            }
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return {
            'success': False
        }

    def default(self):
        db = get_db()
        return list(db.all('profile', limit = 1, with_doc = True))[0]['doc']

    def saveOrder(self, **kwargs):

        try:
            db = get_db()

            order = 0

            for profile_id in kwargs.get('ids', []):
                p = db.get('id', profile_id)
                p['hide'] = tryInt(kwargs.get('hidden')[order]) == 1
                p['order'] = order
                db.update(p)

                order += 1

            return {
                'success': True
            }
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return {
            'success': False
        }

    def delete(self, id = None, **kwargs):

        try:
            db = get_db()

            success = False
            message = ''

            try:
                p = db.get('id', id)
                db.delete(p)

                # Force defaults on all empty profile movies
                self.forceDefaults()

                success = True
            except Exception as e:
                message = log.error('Failed deleting Profile: %s', e)

            return {
                'success': success,
                'message': message
            }
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return {
            'success': False
        }

    def fill(self):

        try:
            db = get_db()

            # Create default quality profiles
            for order, profile in enumerate(DEFAULT_PROFILES):
                log.info('Creating default profile: %s', profile.get('label'))
                db.insert(build_profile_doc(profile, order))

            return True
        except Exception:
            log.error('Failed: %s', traceback.format_exc())

        return False
