import configparser as ConfigParser
import os
import tempfile
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


def _strip_bytes_literal(value: str) -> str:
    """Strip Python 2 bytes literal prefix from config values (e.g. b'Horror' -> Horror)."""
    if isinstance(value, str) and value.startswith("b'") and value.endswith("'"):
        return value[2:-1]
    return value


def _resolve_saved_value(hook_result: Any, submitted: Any) -> Any:
    """Pick between a `setting.save.<section>.<option>` hook's result and the
    value the caller submitted.

    This used to be `hook_result if hook_result else submitted`, which quietly
    made it impossible for a hook to force a FALSY value: a guard returning `0`
    was discarded and the caller's original `1` stored instead. That is not
    hypothetical -- it is exactly what the auth_required lockout guard
    (`Core.guardAuthRequired`) needs to do, and measured before this change the
    guard returned 0 and config.ini still received 1.

    Two "no result" shapes have to be told apart from a deliberate falsy one:

      - `None`, the ordinary return of a handler that chose not to rewrite.
      - `[]`, which is what `fireEvent(..., single=True)` returns when NOTHING
        handles the event (`event.py`: `final = results[0] if results else []`).
        Most options have no hook at all, so this is the common case -- treating
        it as a value would write a literal empty list into config.ini for every
        setting anyone saves.

    Anything else wins, including `0` and `''`.
    """
    if hook_result is None:
        return submitted
    if isinstance(hook_result, list) and not hook_result:
        return submitted
    return hook_result


def _coerce_value(value: Any, type_name: str) -> Any:
    """Use Pydantic's type coercion to convert config values."""
    # Handle bytes from config (Python 3 compatibility)
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    if isinstance(value, str):
        value = _strip_bytes_literal(value)
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

        # section -> set(option_name) actually passed to registerDefaults on
        # THIS instance. `self.types` (class attribute, shared across every
        # Settings()) cannot answer "is this option registered": setType is
        # only called `if option.get('type')`, so a great many legitimately
        # registered options -- plain strings with no declared type -- have
        # no entry in it either, same as an orphan. This has to be instance
        # state, not a fourth class attribute alongside `options`/`types`, or
        # one test's registration would make an unrelated Settings() think an
        # orphan section was registered.
        self.registered_options = {}

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

        # Record the WHOLE option set up front, and record each name the way
        # ConfigParser will store it.
        #
        # Up front, because `loader.loadSettings` fires `settings.options`
        # (which feeds `getOptions()` -- what the UI renders) BEFORE it fires
        # `settings.register`, and `event.py` swallows a handler's exception.
        # A plugin that raises part way through the loop below would otherwise
        # leave its later options renderable but unregistered, and `getValues`
        # would show the user `*` where a real value belongs. Masking has to
        # be aligned with renderability, not with how far this loop got.
        #
        # `optionxform`, because `RawConfigParser` applies it (lower-casing,
        # by default) when it STORES an option, and `getValues` reads back
        # through `p.items()`. Recording the name as the plugin declared it
        # means the two keys never meet for any option with a capital letter,
        # and a legitimately registered field gets starred out. Nothing in the
        # tree trips this today -- all 425 in-tree options are already
        # lower-case -- but it is a defect this masking CREATED: `self.types`
        # has the same raw-key inconsistency, and before masking the only
        # consequence was a lost type declaration, not a wrong value.
        #
        # Sections are deliberately NOT folded: ConfigParser applies
        # `optionxform` to options only, so `[MyPlugin]` stays `[MyPlugin]`.
        # `str.lower` when there is no parser yet, so that this does not
        # become the one statement in the method that raises before
        # `setFile()`: `addSection` and `setDefault` both guard with
        # `if self.p and ...`, and `setType` never touches the parser at all.
        # Matching that idiom is the whole reason for the fallback.
        #
        # NO reachability is claimed for it. Measured: `settings.register` has
        # no handler until `setFile()` runs, because `addEvent` happens in
        # `connectEvents()` and only `setFile()` calls that -- so the loader,
        # the sole in-tree firer, cannot reach this early. An earlier version
        # of this comment asserted that a raise here would leave a section
        # renderable and wholly masked; the mechanism it described is real
        # (`event.py` swallows the handler exception, and `loader.loadSettings`
        # fires `settings.options` before `settings.register`) but the path to
        # trigger it is not, and a comment that sends the next reader hunting a
        # live data path that does not exist is worse than no comment.
        #
        # `str.lower` is ConfigParser's own default `optionxform`, so a direct
        # caller that does arrive early records exactly what the parser would
        # have. They differ only for a non-str name, and every one of the
        # option names declared in this tree is a string literal.
        xform = self.p.optionxform if self.p else str.lower
        self.registered_options.setdefault(section_name, set()).update(
            xform(name) for name in options
        )

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
                # Skip type coercion (there is no 'password' adapter) but NOT
                # the legacy-literal cleanup: `_strip_bytes_literal` lives
                # inside `_coerce_value`, and returning `raw_value` here handed
                # a long-lived config's `b'...'` wrapper straight to the plugin.
                # Masking a credential must not change what the plugin reads.
                return _strip_bytes_literal(raw_value)

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
            registered_in_section = self.registered_options.get(section, set())
            for option_name, option_value in self.p.items(section):
                if self.isOptionMeta(section, option_name):
                    continue

                if option_name not in registered_in_section:
                    # ORPHAN: present in config.ini, but no live plugin ever
                    # called registerDefaults for it -- typically because the
                    # plugin that used to own it was removed (Hadouken, on
                    # this branch). `getType()` falls back to 'unicode' for
                    # anything not in `self.types`, so without this branch an
                    # orphaned credential comes back verbatim.
                    #
                    # Mask on the RAW value, before any type-dependent branch
                    # below runs, and do not fall through to them. Those
                    # branches trust `getType()`, which reads `self.types` --
                    # a CLASS attribute shared by every Settings() in the
                    # process -- so an unrelated instance could have left a
                    # 'directory' type registered against this same
                    # section/option name even though THIS instance never
                    # registered it. Running `abs2chroot` on an untrusted
                    # orphan value is exactly the resolution we don't want to
                    # perform at all; masking first and `continue`-ing avoids
                    # it entirely rather than trusting stale shared state to
                    # decide.
                    masked = str(option_value)
                    values[section][option_name] = len(masked) * '*' if masked else masked
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
        """Write the settings file atomically: temp file, fsync, rename.

        The previous implementation was `open(self.file, 'w')`, which
        TRUNCATES before writing anything. If the process died or the volume
        filled between the truncate and the flush, `config.ini` was left empty
        or partial -- and it holds the api_key, the UI password, and every
        downloader and notifier credential. It is also the documented lock-out
        recovery file, so the failure destroyed the remedy along with the
        configuration. `Env.setting(attr, value=...)` calls this
        unconditionally (`environment.py:71`).

        Four details, none incidental:

        - `realpath` FIRST. `--config_file` is user-supplied and only
          `expanduser`'d (`runner.py:86`), so pointing it at a symlink is
          legitimate -- and `os.replace` onto a symlink replaces the LINK,
          orphaning the operator's real file. The old truncating write
          followed the link, so resolving here preserves existing behaviour
          rather than changing it.

        - The temp file is a SIBLING. `os.replace` is atomic only within one
          filesystem, and production bind-mounts `/config`; a temp in /tmp
          would be a different device and the rename would fail outright.

        - Mode is carried across. `mkstemp` creates 0600, so without this a
          save would silently tighten an existing 0644 file. A file that does
          not exist yet IS created 0600 deliberately: it holds credentials,
          and 0644 -- what the old code produced under a default umask -- made
          every secret in it world-readable.

        - fsync the file before the rename and the directory after it.
          Otherwise a power failure can leave the rename durable while the
          contents are not, which is the same lost-config outcome by a
          slower route.
        """
        path = os.path.realpath(self.file)
        directory = os.path.dirname(path) or '.'

        # Carry the existing file's identity across the replace.
        #
        # `os.replace` swaps in a NEW inode; the truncate-then-write this
        # replaced kept the old one, so owner, group and ACLs survived for
        # free. They have to be copied deliberately now, or a config.ini with a
        # managed group -- readable by a backup account, say -- silently
        # becomes owned by the server process on the next save.
        try:
            existing = os.stat(path)
            mode = existing.st_mode & 0o777
            owner = (existing.st_uid, existing.st_gid)
        except OSError:
            mode = 0o600
            owner = None

        # Clear the WORLD bits, always.
        #
        # Preserving the mode exactly would mean every config.ini written
        # before this change -- created 0644 by `open(file, 'w')` under a
        # default umask -- stays world-readable forever, through every
        # subsequent save. The file holds the api_key, the password hash, and
        # every downloader and notifier credential, so the fix would harden new
        # installs and do nothing for the ones that already have the problem.
        #
        # ONLY the world bits. Group access is left exactly as the operator set
        # it: backup tooling reading through a shared group is a legitimate
        # arrangement, and silently breaking it would be worse than the
        # exposure being closed.
        if mode & 0o007 and self.log:
            self.log.info('Removing world access from %s: it holds the api_key '
                          'and stored credentials (mode %o -> %o)',
                          path, mode, mode & ~0o007)
        mode &= ~0o007

        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix='.%s.' % os.path.basename(path), suffix='.tmp', dir=directory
        )
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as configfile:
                self.p.write(configfile)
                configfile.flush()
                os.fsync(configfile.fileno())

            # Best-effort: chown to a DIFFERENT uid needs privilege this
            # process will not have, but restoring the gid it already had is
            # something a member of that group can do, and that is the case
            # that actually breaks deployments. A failure here must not fail
            # the save -- the alternative is refusing to persist settings.
            #
            # NOT preserved: POSIX ACLs beyond the mode bits. Copying those
            # needs privileged xattr writes that would fail on most of the
            # setups that have them, and a half-applied ACL is worse than a
            # documented gap.
            if owner is not None:
                try:
                    os.chown(tmp_path, owner[0], owner[1])
                except OSError:
                    if self.log:
                        self.log.debug('Could not preserve owner/group on %s: %s',
                                       path, traceback.format_exc(1))

            os.chmod(tmp_path, mode)
            os.replace(tmp_path, path)
        except BaseException:
            # BaseException, not Exception: a KeyboardInterrupt or SystemExit
            # mid-write must not leave a stray `.config.ini.*.tmp` behind --
            # `config.ini.*` is exactly what a locked-out operator reaches for.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # Durability of the RENAME itself, not just the contents.
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

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

    def _parse_directories(self, value, soft_chroot):
        """Normalise a `directories` setting value and map it into the chroot.

        Extracted from saveView unchanged, so the chroot refusal below has one
        `try` around both directory branches instead of a copy in each.
        """
        import json

        # Accept either a JSON array or a plain "::" delimited string
        if isinstance(value, str) and value.strip().startswith('['):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                value = []
        elif isinstance(value, str):
            # Plain string — split on :: delimiter or treat as single path
            value = [v.strip() for v in value.split(self.directories_delimiter) if v.strip()]
        if not (value and isinstance(value, list)):
            value = []

        return self.directories_delimiter.join(map(soft_chroot.chroot2abs, value))

    def saveView(self, **kwargs):
        section = kwargs.get('section')
        option = kwargs.get('name')
        value = kwargs.get('value')

        if not self.isOptionWritable(section, option):
            self.log.warning('Option "%s.%s" isn\'t writable', section, option)
            return {'success': False}

        from couchpotato.environment import Env
        soft_chroot = Env.get('softchroot')

        # chroot2abs now refuses a value that resolves outside the soft
        # chroot instead of concatenating it through. That closes a second
        # bypass -- a chrooted user could previously save a directory of
        # `../../mnt` and have it written verbatim, after which the renamer
        # and the scanner operated outside the chroot entirely -- but it
        # means these two calls can raise, so they are handled here rather
        # than surfacing as a 500 with the path in a logged traceback.
        try:
            if self.getType(section, option) == 'directory':
                value = soft_chroot.chroot2abs(value)

            if self.getType(section, option) == 'directories':
                value = self._parse_directories(value, soft_chroot)
        except ValueError:
            self.log.warning('Refused "%s.%s": the path resolves outside the '
                             'configured soft chroot', section, option)
            return {'success': False}

        new_value = fireEvent('setting.save.%s.%s' % (section, option), value, single=True)
        # Use plain string — .encode('unicode_escape') produces bytes which ConfigParser
        # serialises as b'...' literals (Python 3 bug)
        stored = _resolve_saved_value(new_value, value)
        self.set(section, option, stored)
        self.save()

        fireEvent('setting.save.%s.%s.after' % (section, option), single=True)
        fireEvent('setting.save.%s.*.after' % section, single=True)

        # `.after`, above, is NOT "runs once, after the save" -- despite the
        # name and despite running on this line after `self.save()`.
        # `fireEvent`'s own tail (`event.py`: `if not options['is_after_event']:
        # fireEvent('%s.after' % name, is_after_event=True)`) auto-derives and
        # fires `'<name>.after'` for EVERY dispatch, including the value-hook
        # call three lines up -- so a handler on
        # `'setting.save.<section>.<option>.after'` actually runs TWICE per
        # save: once immediately after the value hook (BEFORE `self.set()` and
        # `self.save()` above), and once again here. A hook that reacts once
        # and consumes state (T14: `Core.rotateSessionSecretAfterSave`,
        # rotating the session secret only once a password change has
        # committed) sees the premature firing and never the real one --
        # measured: the secret rotated even when `self.save()` was made to
        # raise, because rotation had already happened before that line ran.
        # `.committed` is a name `fireEvent` has never auto-derived from
        # anything, so it is the only signal here guaranteed to fire exactly
        # once, and only after `self.save()` has returned without raising.
        fireEvent('setting.save.%s.%s.committed' % (section, option), single=True)

        # Report what was ACTUALLY STORED, not merely that a write happened.
        #
        # A hook may rewrite the submitted value -- `Core.guardAuthRequired`
        # turns a `1` into a `0` when no password is set, refusing to create an
        # unrecoverable lockout. Returning a bare `{'success': True}` told the
        # settings client the submitted value had been accepted, so it kept `1`
        # in local state, cleared the dirty flag, left the checkbox ticked and
        # announced "Saved" -- while the server remained public.
        return self._save_result(section, option, stored, value)

    def _save_result(self, section, option, stored, submitted):
        """The saveView response body: what was stored, and whether it differs.

        Two things this has to get right, both of which the first version got
        wrong and both of which were introduced BY the fix above:

        NEVER ECHO A SECRET. `getValues` masks `type == 'password'` options
        before they reach a client, and this path had no such mask.
        `Core.md5Password` returns `hash_password(md5(value))`, so a password
        save put the full bcrypt string in the response body -- which the
        settings client then wrote into `values.core.password` (bound to the
        visible input) and, because of the type bug below, interpolated into an
        on-screen toast. Measured: `'$2b$12$...'` in the response.

        COMPARE LIKE WITH LIKE. Every form/query POST arrives as a string
        (`dict(request.form())`, and the client explicitly does `String(value)`),
        while hooks return native types -- `guardAuthRequired` returns `int` 1,
        `checkApikey` returns a str, `md5Password` a hash. So `stored != value`
        was `1 != '1'` for the ACCEPTED case and reported `changed` on every
        successful "Require login" enable, every password save and every api-key
        regeneration -- firing a refusal toast for a save that succeeded. That
        is the same "UI states the opposite of what happened" defect the
        `changed` flag exists to prevent, reintroduced by its own implementation.

        Both sides are coerced through the option's registered type before
        comparing, so `'1'` and `1` are the same answer.
        """
        option_type = self.getType(section, option)

        def coerce(v):
            try:
                return _coerce_value(v, option_type)
            except Exception:
                # An uncoercible value is not a reason to fail the save that
                # already happened; fall back to comparing what we have.
                return v

        # Withhold unless the option is REGISTERED and registered non-secret.
        #
        # `getType` returns 'unicode' for a password option that is merely
        # missing from `self.types`, so a blocklist on `== 'password'` fails
        # OPEN for an unregistered one -- driven with `opt_type=None` against
        # the real function, the old form returned BOTH the hash and the
        # plaintext. Registration happens in `loader.run()` at startup, so a
        # shipped server is very likely fine; "very likely registered" is the
        # wrong thing for a disclosure decision to rest on.
        #
        # An allowlist of type NAMES cannot express this, because the unknown
        # case and the ordinary-string case are the same name. So the question
        # asked is "was this option registered at all", which distinguishes
        # them -- and an unregistered option withholds, costing only the
        # `changed` hint on a setting nothing declared.
        registered = option in (self.types.get(section) or {})
        if not registered or option_type == 'password':
            # NOTHING but success. Not the value, and not `changed` either.
            #
            # Reporting `changed` looked harmless and was worse than the leak it
            # replaced. `_coerce_value` has no adapter for 'password', so
            # coercion is a no-op for this type -- and `stored` is the bcrypt
            # hash from `md5Password` while `submitted` is the plaintext the
            # operator just typed. They are never equal, so `changed` was True
            # for every real password change. No type coercion can close that:
            # it is a VALUE transformation, not a type mismatch.
            #
            # The client then took `changed` as "the server stored something
            # else", fell back to the submitted value because `value` was
            # (correctly) absent, and interpolated it into an error toast -- so
            # masking the hash turned a hash disclosure into a PLAINTEXT
            # PASSWORD on screen, for six seconds, announced through the
            # assertive live region this same branch had just added.
            #
            # "Did the password change?" is not a question the client needs
            # answered, and it is not one that can be answered without comparing
            # against the secret. So it is not answered.
            return {'success': True}

        changed = coerce(stored) != coerce(submitted)

        return {
            'success': True,
            'value': stored,
            'submitted': submitted,
            'changed': changed,
        }

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
            fireEvent('database.corrupted_document', propert.get('_id'))
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
