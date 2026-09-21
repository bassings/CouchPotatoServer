import re

from couchpotato.core.media._base.providers.userscript.base import UserscriptBase


autoload = 'YouTheater'


class YouTheater(UserscriptBase):
    id_re = re.compile(r"view\.php\?id=(\d+)")
    includes = ['*://www.youtheater.com/view.php?id=*', '*://youtheater.com/view.php?id=*',
                '*://www.sratim.co.il/view.php?id=*', '*://sratim.co.il/view.php?id=*']

    def getMovie(self, url):
        id = self.id_re.findall(url)[0]
        url = 'https://www.youtheater.com/view.php?id=%s' % id
        return super().getMovie(url)
