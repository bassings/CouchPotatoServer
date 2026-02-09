import importlib
import os
import pkgutil
import sys
import traceback

from couchpotato.core.event import fireEvent
from couchpotato.core.logger import CPLog


log = CPLog(__name__)


class Loader(object):

    def __init__(self):
        self.plugins = {}
        self.providers = {}
        self.modules = {}
        self.paths = {}

    def preload(self, root=''):
        core = os.path.join(root, 'couchpotato', 'core')

        self.paths.update({
            'core': (0, 'couchpotato.core._base', os.path.join(core, '_base')),
            'plugin': (1, 'couchpotato.core.plugins', os.path.join(core, 'plugins')),
            'notifications': (20, 'couchpotato.core.notifications', os.path.join(core, 'notifications')),
            'downloaders': (20, 'couchpotato.core.downloaders', os.path.join(core, 'downloaders')),
        })

        # Add media to loader
        self.addPath(root, ['couchpotato', 'core', 'media'], 25, recursive=True)

        # Add custom plugin folder
        from couchpotato.environment import Env
        custom_plugin_dir = os.path.join(Env.get('data_dir'), 'custom_plugins')
        if os.path.isdir(custom_plugin_dir):
            sys.path.insert(0, custom_plugin_dir)
            self.paths['custom_plugins'] = (30, '', custom_plugin_dir)

        # Discover modules from all registered paths
        for plugin_type, plugin_tuple in self.paths.items():
            priority, module, dir_name = plugin_tuple
            self.addFromDir(plugin_type, priority, module, dir_name)

    def run(self):
        did_save = 0

        for priority in sorted(self.modules):
            for module_name, plugin in sorted(self.modules[priority].items()):
                try:
                    if plugin.get('name', '')[:2] == '__':
                        continue

                    m = self.loadModule(module_name)
                    if m is None:
                        continue

                    did_save += self.loadSettings(m, module_name, save=False)
                    self.loadPlugins(m, plugin.get('type'), plugin.get('name'))
                except ImportError as e:
                    msg = str(e)
                    if msg.lower().startswith("missing"):
                        log.error(msg)
                    log.error('Import error, remove the empty folder: %s', plugin.get('module'))
                    log.debug('Can\'t import %s: %s', module_name, traceback.format_exc())
                except Exception:
                    log.error('Can\'t import %s: %s', module_name, traceback.format_exc())

        if did_save:
            fireEvent('settings.save')

    def addPath(self, root, base_path, priority, recursive=False):
        root_path = os.path.join(root, *base_path)
        module_prefix = '.'.join(base_path)

        for importer, name, ispkg in pkgutil.iter_modules([root_path]):
            if name.startswith('__'):
                continue
            if ispkg:
                full_module = f'{module_prefix}.{name}'
                full_path = os.path.join(root_path, name)
                self.paths[full_module.replace('.', '_')] = (priority, full_module, full_path)

                if recursive:
                    self.addPath(root, base_path + [name], priority, recursive=True)

    def addFromDir(self, plugin_type, priority, module, dir_name):
        # Register the directory's own module
        if module:
            self.addModule(priority, plugin_type, module, os.path.basename(dir_name))

        if not os.path.isdir(dir_name):
            return

        for importer, name, ispkg in pkgutil.iter_modules([dir_name]):
            if name.startswith('__') or name == 'static' or name.endswith('_test'):
                continue

            module_name = f'{module}.{name}' if module else name
            self.addModule(priority, plugin_type, module_name, name)

    def loadSettings(self, module, name, save=True):
        if not hasattr(module, 'config'):
            return False

        try:
            for section in module.config:
                fireEvent('settings.options', section['name'], section)
                options = {}
                for group in section['groups']:
                    for option in group['options']:
                        options[option['name']] = option
                fireEvent('settings.register', section_name=section['name'], options=options, save=save)
            return True
        except Exception:
            log.debug('Failed loading settings for "%s": %s', name, traceback.format_exc())
            return False

    def loadPlugins(self, module, type, name):
        if not hasattr(module, 'autoload'):
            return False
        try:
            if isinstance(module.autoload, str):
                getattr(module, module.autoload)()
            else:
                module.autoload()

            log.info('Loaded %s: %s', type, name)
            return True
        except Exception:
            log.error('Failed loading plugin "%s": %s', module.__file__, traceback.format_exc())
            return False

    def addModule(self, priority, plugin_type, module, name):
        if priority not in self.modules:
            self.modules[priority] = {}

        module = module.lstrip('.')
        if plugin_type.startswith('couchpotato_core'):
            plugin_type = plugin_type[17:]

        self.modules[priority][module] = {
            'priority': priority,
            'module': module,
            'type': plugin_type,
            'name': name,
        }

    def loadModule(self, name):
        try:
            return importlib.import_module(name)
        except (ImportError, SyntaxError):
            log.debug('Skip loading module plugin %s: %s', name, traceback.format_exc())
            return None
        except Exception:
            raise
