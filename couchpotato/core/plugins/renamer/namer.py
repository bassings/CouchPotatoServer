"""Naming pattern replacement for the renamer."""
import re

from couchpotato.core.helpers.encoding import toUnicode, ss
from couchpotato.core.helpers.variable import getExt
from couchpotato.core.logger import CPLog

log = CPLog(__name__)


class NamerMixin:
    """Mixin providing naming/replacement methods for the Renamer class."""

    def getRenameExtras(self, extra_type='', replacements=None, folder_name='',
                        file_name='', destination='', group=None, current_file='',
                        remove_multiple=False):
        if not group:
            group = {}
        if not replacements:
            replacements = {}
        from couchpotato.core.helpers.variable import sp

        replacements = replacements.copy()
        rename_files = {}

        def test(s):
            return current_file[:-len(replacements['ext'])] in sp(s)

        for extra in set(filter(test, group['files'][extra_type])):
            replacements['ext'] = getExt(extra)

            import os
            final_folder_name = self.doReplace(folder_name, replacements,
                                               remove_multiple=remove_multiple, folder=True)
            final_file_name = self.doReplace(file_name, replacements,
                                             remove_multiple=remove_multiple)
            rename_files[extra] = os.path.join(destination, final_folder_name, final_file_name)

        return rename_files

    def doReplace(self, string, replacements, remove_multiple=False, folder=False):
        """Replace config names with the real values."""
        replacements = replacements.copy()
        if remove_multiple:
            replacements['cd'] = ''
            replacements['cd_nr'] = ''

        replaced = toUnicode(string)
        for x, r in replacements.items():
            if x in ['thename', 'namethe']:
                continue
            if r is not None:
                replaced = replaced.replace(f'<%s>' % toUnicode(x), toUnicode(r))
            else:
                replaced = replaced.replace('<' + x + '>', '')

        if self.conf('replace_doubles'):
            replaced = self.replaceDoubles(replaced.lstrip('. '))

        for x, r in replacements.items():
            if x in ['thename', 'namethe']:
                replaced = replaced.replace(f'<%s>' % toUnicode(x), toUnicode(r))
        replaced = re.sub(r"[\x00:\*\?\"<>\|]", '', replaced)

        sep = self.conf('foldersep') if folder else self.conf('separator')
        return ss(replaced.replace(' ', ' ' if not sep else sep))

    def replaceDoubles(self, string):
        replaces = [
            ('\.+', '.'), ('_+', '_'), ('-+', '-'), ('\s+', ' '), (' \\\\', '\\\\'), (' /', '/'),
            ('(\s\.)+', '.'), ('(-\.)+', '.'), ('(\s-[^\s])+', '-'), (' ]', ']'),
        ]

        for r in replaces:
            reg, replace_with = r
            string = re.sub(reg, replace_with, string)

        string = string.rstrip(',_-/\\ ')
        return string
