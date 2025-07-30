from __future__ import absolute_import, division, print_function, unicode_literals
from couchpotato.core.media._base.providers.userscript.base import UserscriptBase

autoload = 'MoviesIO'


class MoviesIO(UserscriptBase):

    includes = ['*://movies.io/m/*']
