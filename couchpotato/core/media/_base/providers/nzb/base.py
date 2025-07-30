from __future__ import absolute_import, division, print_function, unicode_literals
import time

from couchpotato.core.media._base.providers.base import YarrProvider


class NZBProvider(YarrProvider):

    protocol = 'nzb'

    def calculateAge(self, unix):
        return int(time.time() - unix) / 24 / 60 / 60
