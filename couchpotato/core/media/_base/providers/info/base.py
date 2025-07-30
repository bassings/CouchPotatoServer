from __future__ import absolute_import, division, print_function, unicode_literals
from couchpotato.core.media._base.providers.base import Provider


class BaseInfoProvider(Provider):
    type = 'unknown'
