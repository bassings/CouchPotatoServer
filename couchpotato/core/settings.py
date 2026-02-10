import configparser as ConfigParser
import traceback
from hashlib import md5
from typing import Any, Optional

from pydantic import TypeAdapter
from CodernityDB.hash_index import HashIndex
from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.variable import mergeDicts

# Pydantic type adapters for automatic coercion
_type_adapters = {
    'bool': TypeAdapter(bool),
    'enabler': TypeAdapter(bool),
    'int': TypeAdapter(int),
    'float': TypeAdapter(float),
}


def _coerce_value(value: Any, type_name: str) -> Any:
    """Use Pydantic's type coercion to convert config values."""
    if type_name in _type_adapters:
        # Handle string booleans that ConfigParser doesn't handle
        if type_name in ('bool', 'enabler') and isinstance(value, str):
            if value.lower() in ('true', '1', 'yes', 'on'):
                return True
            if value.lower() in ('false', '0', 'no', 'off', ''):
                return False
        return _type_adapters[type_name].validate_python(value)
    return value


class Settings:

    options = {}
    types = {}

    def __init__(self):
        addApiView('settings', self.view, docs={
            'desc': 'Return the options and its values of settings.conf.',
            'return': {'type': 'object', 'example': '{}'}
        })

        addApiView('settings.save', self.saveView, docs={
            'desc': 'Save setting to config file (settings.conf)',
            'params': {
                'section': {'desc': 'The section name'},
                'name': {'desc': 'The option name'},
                'value': {'desc': 'The value to save'},
            }
        })

        addEvent('database.setup', self.databaseSetup)

        self.file = None
        self.p = None
        self.log = None
        self.directories_delimiter = '::'

    def setFile(self, config_file):
        self.file = config_file
        self.p = ConfigParser.RawConfigParser()
        self.p.read(config_file)

        from couchpotato.core.logger import CPLog
        self.log = CPLog(__name__)
        self.connectEvents()

    def databaseSetup(self):
        fireEvent('database.setup_index', 'property', PropertyIndex)

    def parser(self):
        return self.p

    def sections(self):
        return filter(self.isSectionReadable, self.p.sections())

    def connectEvents(self):
        addEvent('settings.options', self.addOptions)
        addEvent('settings.register', self.registerDefaults)
        addEvent('settings.save', self.save)

    def registerDefaults(self, section_name, options=None, save=True):
        if not options:
            options = {}

        self.addSection(section_name)

        for option_name, option in options.items():
            self.setDefault(section_name, option_name, option.get('default', ''))

            # Set UI-meta for option (hidden/ro/rw)
            if option.get('ui-meta'):
                value = option.get('ui-meta').lower()
                if value in ['hidden', 'rw', 'ro']:
                    meta_option_name = option_name + self.optionMetaSuffix()
                    self.setDefault(section_name, meta_option_name, value)
                else:
                    self.log.warning('Wrong ui-meta value for %s.%s: "%s"', section_name, option_name, value)

            # Migrate old settings
            if option.get('migrate_from'):
                if self.p.has_option(option.get('migrate_from'), option_name):
                    previous_value = self.p.get(option.get('migrate_from'), option_name)
                    self.p.set(section_name, option_name, previous_value)
                    self.p.remove_option(option.get('migrate_from'), option_name)

            if option.get('type'):
                self.setType(section_name, option_name, option.get('type'))

        if save:
            self.save()

    def set(self, section, option, value):
        if not self.isOptionWritable(section, option):
            self.log.warning('set::option "%s.%s" isn\'t writable', section, option)
            return None
        if self.isOptionMeta(section, option):
            self.log.warning('set::option "%s.%s" cancelled (META option)', section, option)
            return None
        return self.p.set(section, option, value)

    def get(self, option='', section='core', default=None, type=None):
        if self.isOptionMeta(section, option):
            self.log.warning('get::option "%s.%s" cancelled (META option)', section, option)
            return None

        tp = type or self.getType(section, option)
        try:
            if tp == 'directories':
                return self.getDirectories(section, option)

            raw_value = self.p.get(section, option)

            if tp == 'password':
                return raw_value

            # Use Pydantic coercion for typed values
            return _coerce_value(raw_value, tp)
        except Exception:
            return default

    def delete(self, option='', section='core'):
        if not self.isOptionWritable(section, option):
            self.log.warning('delete::option "%s.%s" isn\'t writable', section, option)
            return None
        if self.isOptionMeta(section, option):
            self.log.warning('delete::option "%s.%s" cancelled (META option)', section, option)
            return None
        self.p.remove_option(section, option)
        self.save()

    # Legacy typed getters (kept for backward compatibility, now use Pydantic internally)
    def getEnabler(self, section, option):
        return self.getBool(section, option)

    def getBool(self, section, option):
        try:
            return _coerce_value(self.p.get(section, option), 'bool')
        except Exception:
            return False

    def getInt(self, section, option):
        try:
            return _coerce_value(self.p.get(section, option), 'int')
        except Exception:
            return 0

    def getFloat(self, section, option):
        try:
            return _coerce_value(self.p.get(section, option), 'float')
        except Exception:
            return 0.0

    def getDirectories(self, section, option):
        value = self.p.get(section, option)
        if value:
            return list(map(str.strip, str.split(value, self.directories_delimiter)))
        return []

    def getUnicode(self, section, option):
        value = self.p.get(section, option)
        if isinstance(value, bytes):
            value = value.decode('unicode_escape')
        return toUnicode(value).strip()

    def getValues(self):
        from couchpotato.environment import Env

        values = {}
        soft_chroot = Env.get('softchroot')

        for section in self.sections():
            values[section] = {}
            for option_name, option_value in self.p.items(section):
                if self.isOptionMeta(section, option_name):
                    continue

                value = self.get(option_name, section)

                if self.getType(section, option_name) == 'password' and value:
                    value = len(value) * '*'

                if self.getType(section, option_name) == 'directory' and value:
                    try:
                        value = soft_chroot.abs2chroot(value)
                    except Exception:
                        value = ""

                if self.getType(section, option_name) == 'directories':
                    if not value:
                        value = []
                    try:
                        value = list(map(soft_chroot.abs2chroot, value))
                    except Exception:
                        value = []

                values[section][option_name] = value

        return values

    def save(self):
        with open(self.file, 'w', encoding='utf-8') as configfile:
            self.p.write(configfile)

    def addSection(self, section):
        if self.p and not self.p.has_section(section):
            self.p.add_section(section)

    def setDefault(self, section, option, value):
        if self.p and not self.p.has_option(section, option):
            self.p.set(section, option, value)

    def setType(self, section, option, type):
        if not self.types.get(section):
            self.types[section] = {}
        self.types[section][option] = type

    def getType(self, section, option):
        try:
            return self.types[section][option]
        except Exception:
            return 'unicode'

    def addOptions(self, section_name, options):
        if not self.options.get(section_name):
            self.options[section_name] = options
        else:
            self.options[section_name] = mergeDicts(self.options[section_name], options)

    def getOptions(self):
        """Returns dict of UI-readable options, filtering hidden and marking readonly."""
        res = {}

        for section_key, section_orig in self.options.items():
            section_name = section_orig.get('name', section_key)
            if not self.isSectionReadable(section_name):
                continue

            section_copy = {k: v for k, v in section_orig.items() if k.lower() != 'groups'}
            section_copy_groups = []

            for group_orig in section_orig.get('groups', []):
                group_copy = {k: v for k, v in group_orig.items() if k.lower() != 'options'}
                group_copy_options = []

                for option in group_orig.get('options', []):
                    option_name = option.get('name')
                    if self.isOptionReadable(section_name, option_name):
                        group_copy_options.append(option)
                        if not self.isOptionWritable(section_name, option_name):
                            option['readonly'] = True

                if group_copy_options:
                    group_copy['options'] = group_copy_options
                    section_copy_groups.append(group_copy)

            if section_copy_groups:
                section_copy['groups'] = section_copy_groups
                res[section_key] = section_copy

        return res

    def view(self, **kwargs):
        return {
            'options': self.getOptions(),
            'values': self.getValues()
        }

    def saveView(self, **kwargs):
        section = kwargs.get('section')
        option = kwargs.get('name')
        value = kwargs.get('value')

        if not self.isOptionWritable(section, option):
            self.log.warning('Option "%s.%s" isn\'t writable', section, option)
            return {'success': False}

        from couchpotato.environment import Env
        soft_chroot = Env.get('softchroot')

        if self.getType(section, option) == 'directory':
            value = soft_chroot.chroot2abs(value)

        if self.getType(section, option) == 'directories':
            import json
            value = json.loads(value)
            if not (value and isinstance(value, list)):
                value = []
            value = self.directories_delimiter.join(map(soft_chroot.chroot2abs, value))

        new_value = fireEvent('setting.save.%s.%s' % (section, option), value, single=True)
        self.set(section, option, (new_value if new_value else value).encode('unicode_escape'))
        self.save()

        fireEvent('setting.save.%s.%s.after' % (section, option), single=True)
        fireEvent('setting.save.%s.*.after' % section, single=True)

        return {'success': True}

    # Meta option helpers
    def optionMetaSuffix(self):
        return '_internal_meta'

    def isOptionMeta(self, section, option):
        return option.endswith(self.optionMetaSuffix())

    def isSectionReadable(self, section):
        meta = 'section_hidden' + self.optionMetaSuffix()
        try:
            return not self.p.getboolean(section, meta)
        except Exception:
            return True

    def isOptionReadable(self, section, option):
        meta = option + self.optionMetaSuffix()
        if self.p.has_option(section, meta):
            meta_v = self.p.get(section, meta).lower()
            return meta_v in ('rw', 'ro')
        return True

    def isOptionWritable(self, section, option):
        meta = option + self.optionMetaSuffix()
        if self.p.has_option(section, meta):
            return self.p.get(section, meta).lower() == 'rw'
        return True

    # Database-backed properties (separate from INI config)
    def getProperty(self, identifier):
        from couchpotato import get_db

        db = get_db()
        prop = None
        try:
            propert = db.get('property', identifier, with_doc=True)
            prop = propert['doc']['value']
        except ValueError:
            propert = db.get('property', identifier)
            fireEvent('database.delete_corrupted', propert.get('_id'))
        except Exception:
            self.log.debug('Property "%s" not yet stored, will use default' % identifier)

        return prop

    def setProperty(self, identifier, value=''):
        from couchpotato import get_db

        db = get_db()

        try:
            p = db.get('property', identifier, with_doc=True)
            p['doc'].update({
                'identifier': identifier,
                'value': toUnicode(value),
            })
            db.update(p['doc'])
        except Exception:
            db.insert({
                '_t': 'property',
                'identifier': identifier,
                'value': toUnicode(value),
            })


class PropertyIndex(HashIndex):
    _version = 1

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '32s'
        super().__init__(*args, **kwargs)

    def make_key(self, key):
        return md5(key.encode('utf-8')).hexdigest()

    def make_key_value(self, data):
        if data.get('_t') == 'property':
            return md5(data['identifier'].encode('utf-8')).hexdigest(), None
