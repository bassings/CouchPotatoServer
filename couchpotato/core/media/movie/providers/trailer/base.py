from __future__ import absolute_import, division, print_function, unicode_literals
from couchpotato.core.event import addEvent
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.providers.base import Provider

log = CPLog(__name__)


class TrailerProvider(Provider):

    type = 'trailer'

    def __init__(self):
        addEvent('trailer.search', self.search)

    def search(self, *args, **kwargs):
        pass
