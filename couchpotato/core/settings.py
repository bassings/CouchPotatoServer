import configparser as ConfigParser
import hmac
import os
import secrets
import tempfile
import threading
import traceback
from hashlib import md5
from typing import Any, Optional

from pydantic import TypeAdapter
from CodernityDB.hash_index import HashIndex
from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent, getEvent
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.variable import mergeDicts

# Pydantic type adapters for automatic coercion
_type_adapters = {
    'bool': TypeAdapter(bool),
    'enabler': TypeAdapter(bool),
    'int': TypeAdapter(int),
    'float': TypeAdapter(float),
}

# Keep the password, durable rotation intent, secret rotation and marker clear
# as one process-local transaction. Runtime parser mutations and file saves
# share this lock, so another settings write cannot persist half-prepared auth
# state, and a later password save cannot lose its marker to an older callback.
_PASSWORD_SAVE_LOCK = threading.RLock()

#: What the settings read will show in place of a stored credential cell
#: (SEC-006). It equals its own `strip()` and its JavaScript `trim()`, holds no
#: whitespace, comma or control character, is longer than any trim could touch
#: and contains a character no key alphabet uses, so a page that sends it back
#: cannot have altered it and no real key contains it. A save of any secret cell
#: containing it is refused (`masked_value`).
SECRET_MASK = '\u2022' * 8

#: How many removed or replaced keys the server remembers per section (SEC-006
#: Design 4): process memory only, oldest first out. The one bound on the hold.
_HOLD_LIMIT_PER_SECTION = 16


class _RemovedKeyHold:
    """Keys a token-carrying save left out, kept so that one Undo can put them back.

    Keyed `(section, column, token the save carried, cell index)`; the value is the
    cell's stored text exactly. Insertion-ordered, bounded per section, never
    written anywhere and gone with the `Settings` that owns it. Callers hold
    `_PASSWORD_SAVE_LOCK`. No method formats a key or a token into anything, so no
    exception it raises can carry one.
    """

    def __init__(self):
        self._entries = {}

    def add(self, section, column, token, row, text):
        key = (section, column, token, row)
        # An existing entry is moved to the newest position, so the order stays one
        # record per key and the oldest is always the first to go.
        self._entries.pop(key, None)
        self._entries[key] = text
        self.evict(section)

    def peek(self, section, column, token, row):
        return self._entries.get((section, column, token, row))

    def take(self, section, column, token, row):
        return self._entries.pop((section, column, token, row), None)

    def list_by_token(self, section, token):
        return sorted((column, row) for (held_section, column, held_token, row) in self._entries
                      if held_section == section and held_token == token)

    def evict(self, section):
        mine = [key for key in self._entries if key[0] == section]
        for key in mine[:max(0, len(mine) - _HOLD_LIMIT_PER_SECTION)]:
            self._entries.pop(key, None)


#: Why a group save can be refused. The writer returns these codes and no
#: others (AC-ARCH-11(iii)); a client composes the text a person reads from the
#: code, the 0-based row as sent and the column name. `misaligned` is reachable
#: only through a builder (see `GroupMisaligned`), never from rows it is handed.
_GROUP_REFUSAL_TEXT = {
    'comma': 'A value contains a comma, which would split it across rows. '
             'Nothing was saved.',
    'control_character': 'A value contains a line break or another control character. '
                         'Nothing was saved.',
    'not_string': 'Every value must be text. Nothing was saved.',
    'not_encodable': 'A value contains a character that cannot be stored. '
                     'Nothing was saved.',
    'missing_column': 'A row is missing a column. Nothing was saved.',
    'unknown_column': 'A row has a column this group does not have. Nothing was saved.',
    'not_writable': 'A column of this group cannot be changed. Nothing was saved.',
    'unknown_section': 'That is not a group of settings saved as rows. Nothing was saved.',
    'malformed': 'The request was not a list of rows. Nothing was saved.',
    'misaligned': 'The stored rows do not line up. Fix them in Settings first. '
                  'Nothing was saved.',
    'token_unexpected': 'This group does not use a token. Nothing was saved.',
    'stale': 'The rows changed after this page loaded them. Nothing was saved. '
             'Reload to see the current rows.',
    'token_missing': 'This save keeps or restores a saved key but carries no token. '
                     'Nothing was saved.',
    'bad_reference': 'A kept or restored key was not named correctly. Nothing was saved.',
    'restore_unknown': 'A removed row can no longer be restored. Nothing was saved.',
    'masked_value': 'A saved key was sent back as the dots shown in its place. '
                    'Nothing was saved.',
}
GROUP_REFUSAL_REASONS = frozenset(_GROUP_REFUSAL_TEXT)

#: The text a refused reveal is told, per reason. The reasons are codes of
#: `_GROUP_REFUSAL_TEXT`; the text says nothing was revealed rather than saved.
_REVEAL_REFUSAL_TEXT = {
    'unknown_section': 'That is not a group of settings saved as rows. Nothing was revealed.',
    'bad_reference': 'That cell cannot be revealed. Nothing was revealed.',
    'token_missing': 'A token is required. Nothing was revealed.',
    'stale': 'The rows changed after this page loaded them. Nothing was revealed. '
             'Reload to see the current rows.',
    'malformed': 'The request was not a reveal of one cell. Nothing was revealed.',
}
_REVEAL_FAILED_TEXT = 'The settings could not be read. Nothing was revealed.'


#: What a per-column save of a combine column is told. It names the registered
#: column (never the caller's spelling or value), the group-save route, and what
#: a tab loaded before the upgrade should do.
_COMBINE_COLUMN_REFUSAL = (
    '"%s.%s" is saved together with the rest of its group, not on its own. '
    'Nothing was saved. Use settings.save_group, or reload the page and edit '
    'the rows there.')
_BAD_OPTION_NAME_REFUSAL = (
    'An option name cannot be empty, contain a space, a control character, "=" or ":", '
    'or start with "[", "#" or ";". Nothing was saved.')
_FLAG_NAME_REFUSAL = ('An option flag cannot be changed through settings.save. '
                      'Nothing was saved.')
_NOT_TEXT_REFUSAL = 'The section and the option name must each be text. Nothing was saved.'


def _unsafe_option_name(name):
    """Would the config parser mangle, or fail to write back, an option with this name?

    An empty name is written as `\t= value`, which reloads as a continuation of the
    previous option's value. Whitespace and C0 control characters: a trailing space reloads as a duplicate
    option and a leading one as a continuation line. `=` and `:` are delimiters the
    writer refuses (`InvalidWriteError`, after the name is already in memory, so every
    later save fails). A leading `[` can read as a section header, and a leading `#`
    or `;` reloads as a comment, so the value is silently lost.
    """
    return (not name or any(c.isspace() or ord(c) < 0x20 or c in '=:' for c in name)
            or name.startswith(('[', '#', ';')))


class GroupMisaligned(Exception):
    """Raised by a group builder that finds the stored rows misaligned.

    A builder runs under the lock, reads the stored rows and returns the rows to
    write. When the stored columns do not line up it cannot merge safely, so it
    declines with this and the writer refuses the save with `misaligned`.
    """


def _invalid(row, column, reason):
    return {'row': row, 'column': column, 'reason': reason}


def _group_refusal(problems, held=None):
    """The refusal body: the first reason's fixed text, then every offending cell.

    The text is fixed per reason so that it can never carry a submitted value.
    `held` is set only on a stale refusal: the cells held under the token it carried.
    """
    body = {'success': False,
            'error': _GROUP_REFUSAL_TEXT[problems[0]['reason']],
            'invalid': problems}
    if held is not None:
        body['held'] = held
    return body


def group_transport_refusal():
    """The refusal body for a request that was not a JSON POST of rows.

    The API dispatch (`couchpotato/__init__.py`) enforces the transport and
    answers with this, so it shares the one refusal shape the writer returns.
    """
    return _group_refusal([_invalid(None, None, 'malformed')])


def _cell_problem(cell):
    """Why this cell cannot be stored as a row's cell, or None.

    Checked on the exact value that would be written. A comma becomes a new
    position on read. A C0 control character can lose part of the value on
    reload (a continuation line that starts with `#` or `;` is a comment to the
    parser). Nothing is coerced: a list cell would be stringified into text that
    holds a comma after the comma check had passed it.
    """
    if not isinstance(cell, str):
        return 'not_string'
    if any(ord(char) < 0x20 for char in cell):
        return 'control_character'
    if ',' in cell:
        return 'comma'
    try:
        cell.encode('utf-8')
    except UnicodeEncodeError:
        # A lone surrogate is valid JSON text that the file encoding cannot hold.
        # Left alone it fails at the file write and is reported as a write
        # failure, so it is refused here as the bad input it is.
        return 'not_encodable'
    return None


def unstorable_cell(cell):
    """Why the group writer would refuse this cell, or None.

    The writer's own test, for a caller that would rather skip one bad value than
    have the whole group refused (the Jackett sync). It repeats no rule of its
    own: it asks the one the writer applies.
    """
    return _cell_problem(cell)


def _row_problems(index, row, columns, secrets=()):
    if not isinstance(row, dict):
        return [_invalid(index, None, 'malformed')]
    problems = [_invalid(index, column, 'missing_column') for column in columns if column not in row]
    # The submitted name is not echoed: a refusal never carries caller text.
    problems += [_invalid(index, None, 'unknown_column') for key in row if key not in columns]
    for column in columns:
        reason = _cell_problem(row[column]) if column in row else None
        if reason is None and column in secrets and column in row and SECRET_MASK in row[column]:
            # Only a secret column: another column may hold any text it could before.
            reason = 'masked_value'
        if reason:
            problems.append(_invalid(index, column, reason))
    return problems


def _group_problems(rows, columns, secrets=()):
    """Every reason `rows` cannot be written as the group `columns`."""
    if not isinstance(rows, list) or not rows:
        return [_invalid(None, None, 'malformed')]
    problems = []
    for index, row in enumerate(rows):
        problems.extend(_row_problems(index, row, columns, secrets))
    return problems


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
            'desc': 'Save setting to config file (settings.conf). Refuses every column '
                    'of a multi-row group (use settings.save_group), any option name with '
                    'whitespace, a control character, "=" or ":", an empty name or one starting '
                    'with "[", "#" or ";", the name of an option\'s access flag '
                    '("<option>_internal_meta", in any case), and a section or name '
                    'that is not text.',
            'params': {
                'section': {'desc': 'The section name'},
                'name': {'desc': 'The option name'},
                'value': {'desc': 'The value to save'},
            }
        })

        addApiView('settings.save_group', self.save_group_view, docs={
            'desc': 'Save every column of one multi-row settings group in one request, '
                    'or save nothing. POST only, with an application/json body of '
                    '{"section": name, "rows": [{column: text, ...}, ...]} and, '
                    'optionally, "token": the group\'s token from the settings read. A '
                    'save carrying a token is refused when the group has changed since '
                    'that token was issued, and its reply carries the fresh one. A '
                    'refusal lists each offending cell by row and column, never by value.',
            'params': {
                'section': {'desc': 'The section whose rows are saved'},
                'rows': {'desc': 'A JSON array of objects, one per row, each holding '
                                 'every column of the group as a string'},
                'token': {'desc': 'Optional. The group\'s token from the settings read'},
            },
            'return': {'type': 'object', 'example': '{"success": true}'},
        })

        addApiView('settings.reveal_cell', self.reveal_cell_view, docs={
            'desc': 'Return the stored text of ONE credential cell of a multi-row group '
                    '(a column the group declares secret). POST only, with an '
                    'application/json body of exactly {"section": name, "column": name, '
                    '"row": integer, "token": the group\'s token from the settings read}. '
                    'Gated by the API key and the Origin check. A refusal never carries '
                    'a value.',
            'params': {
                'section': {'desc': 'The section of the group'},
                'column': {'desc': 'A column the group declares secret'},
                'row': {'desc': 'The cell index within that column (a JSON integer)'},
                'token': {'desc': 'The group\'s current token'},
            },
            'return': {'type': 'object', 'example': '{"success": true, "value": "..."}'},
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

        # The key the per-group token is computed under (SEC-006). Random per
        # instance, held in memory only: it is never written, logged or returned,
        # so a token cannot be forged or carried across a restart.
        self._token_key = secrets.token_bytes(32)
        self._hold = _RemovedKeyHold()

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
            # Whether config.ini as loaded already held this option, asked before
            # the default is written: only a stored value can be a planted one.
            stored_before = bool(self.p) and self.p.has_option(section_name, option_name)
            self.setDefault(section_name, option_name, option.get('default', ''))

            # Set UI-meta for option (hidden/ro/rw)
            if option.get('ui-meta'):
                value = option.get('ui-meta').lower()
                if value in ['hidden', 'rw', 'ro']:
                    meta_option_name = option_name + self.optionMetaSuffix()
                    if value == 'hidden' and stored_before:
                        self._clear_value_without_flag(section_name, option_name, meta_option_name)
                    self._declare_flag(section_name, meta_option_name, value)
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
        with _PASSWORD_SAVE_LOCK:
            return self._set(section, option, value)

    def _set(self, section, option, value):
        if not self.isOptionWritable(section, option):
            self.log.warning('set::option "%s.%s" isn\'t writable', section, option)
            return None
        if self.isOptionMeta(section, option):
            self.log.warning('set::option "%s.%s" cancelled (META option)', section, option)
            return None
        return self.p.set(section, option, value)

    def set_internal(self, section, option, value):
        """Set an option in MEMORY ONLY, for the server's own use. True when it was set.

        `set()` refuses an option whose flag is not `rw`, which is right for the
        settings routes and wrong for a value only the server writes (a hidden
        option). This bypasses that and nothing else: an access flag
        (`<option>_internal_meta`, in any spelling) is still refused, and the
        file is not written. The caller saves once, so that this value and the
        one that caused it land in a single atomic write; a second `save()`
        here would make them two.
        """
        with _PASSWORD_SAVE_LOCK:
            if self.isOptionMeta(section, option):
                self.log.warning('set_internal::option "%s.%s" cancelled (META option)', section, option)
                return False
            self.addSection(section)
            self.p.set(section, option, value)
            return True

    def clearSessionRotationPending(self):
        """Persist an internal revocation marker without UI writeability rules.

        `set()` may silently refuse a read-only option. A marker that remains
        set blocks login, so both the post-commit hook and startup recovery
        must use this checked internal operation rather than trusting `set()`.
        """
        with _PASSWORD_SAVE_LOCK:
            return self._clearSessionRotationPending()

    def _clearSessionRotationPending(self):
        self.p.set('core', 'session_rotation_pending', '0')
        self.save()
        persisted = ConfigParser.RawConfigParser()
        with open(os.path.realpath(self.file), encoding='utf-8') as configfile:
            persisted.read_file(configfile)
        if persisted.get('core', 'session_rotation_pending', fallback=None) != '0':
            raise RuntimeError('session revocation marker was not cleared')

    def get(self, option='', section='core', default=None, type=None):
        if self.isOptionMeta(section, option):
            self.log.warning('get::option "%s.%s" cancelled (META option)', section, option)
            return None

        tp = type or self.getType(section, option)
        try:
            if tp == 'directories':
                return self.getDirectories(section, option)

            raw_value = self.p.get(section, option)

            # No password special-case. There is no 'password' adapter, so
            # `_coerce_value` falls through and does exactly one thing to it --
            # `_strip_bytes_literal` -- which is what this branch used to skip.
            # Skipping it handed a long-lived config's `b'...'` wrapper straight
            # to the plugin, so masking a credential silently broke the
            # integration it was protecting. The first fix duplicated the strip
            # here; review pointed out the branch can just go, which is smaller
            # and cannot drift from `_coerce_value` later.

            # Use Pydantic coercion for typed values
            return _coerce_value(raw_value, tp)
        except Exception:
            return default

    def delete(self, option='', section='core'):
        with _PASSWORD_SAVE_LOCK:
            return self._delete(option, section)

    def _delete(self, option, section):
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

    def _registered_ui_value(self, section, option_name, soft_chroot):
        """Render only values belonging to a registered, typed setting."""
        value = self.get(option_name, section)
        option_type = self.getType(section, option_name)

        if option_type == 'password' and value:
            return len(value) * '*'

        if option_type == 'directory' and value:
            try:
                return soft_chroot.abs2chroot(value)
            except Exception:
                return ''

        if option_type == 'directories':
            if not value:
                value = []
            try:
                return list(map(soft_chroot.abs2chroot, value))
            except Exception:
                return []

        return value

    def _option_in_read(self, section, option_name):
        """Whether `getValues` reports this option at all.

        Meta options never are. Nor is an option whose flag says it is not
        readable ('hidden'), in any section: hiding it from the rendered options
        (`getOptions`) is not enough, because this read is the one a script of
        the API key reads, and it returned a hidden option verbatim.
        """
        if self.isOptionMeta(section, option_name):
            return False
        return self.isOptionReadable(section, option_name)

    def getValues(self):
        from couchpotato.environment import Env

        values = {}
        soft_chroot = Env.get('softchroot')

        for section in self.sections():
            values[section] = {}
            registered_in_section = self.registered_options.get(section, set())
            for option_name, option_value in self.p.items(section):
                if not self._option_in_read(section, option_name):
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

                values[section][option_name] = self._registered_ui_value(
                    section, option_name, soft_chroot)

        return values

    def save(self):
        # A runtime Env.setting() writer shares this parser with saveView.
        # Without the same lock it can persist auth_required and rotation
        # intent while a password save has not yet stored its hash.
        with _PASSWORD_SAVE_LOCK:
            return self._save()

    def _save(self):
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
        with _PASSWORD_SAVE_LOCK:
            if self.p and not self.p.has_section(section):
                self.p.add_section(section)

    def setDefault(self, section, option, value):
        with _PASSWORD_SAVE_LOCK:
            if self.p and not self.p.has_option(section, option):
                self.p.set(section, option, value)

    def _declare_flag(self, section, option, value):
        """Make a DECLARED access flag equal its declared value, at every registration.

        `setDefault` only writes a missing option, so a flag overwritten before
        `settings.save` refused flag names (`rw` over `core.api_key`'s `ro`)
        stayed that way. The stored value is compared as written, so `RO` is
        rewritten as `ro`. Setting a flag to the value it already holds changes
        no byte of config.ini (the parser keeps the key's position), so the
        test here saves a parser call, not a file difference.
        """
        with _PASSWORD_SAVE_LOCK:
            if self.p and (not self.p.has_option(section, option)
                           or self.p.get(section, option) != value):
                self.p.set(section, option, value)

    def _clear_value_without_flag(self, section, option, flag):
        """Empty a hidden option's STORED value when the loaded config has no flag for it, once.

        A hidden option is written only by the server. If config.ini has a value
        for it but no flag, the file is from before the option was declared
        hidden, and this assumes whatever wrote that value was not the server: a
        caller of an older release could plant it, and it would otherwise be
        trusted. This runs in `registerDefaults`, before `_declare_flag` writes
        the flag, so a file that already has the flag is left exactly as it is,
        and the flag is in memory for any later pass, which therefore clears
        nothing. Memory only: the next save persists it. It never writes a
        non-empty value, logs only the section and option names, and never
        raises, so it cannot block a start.

        THE ASSUMPTION IS FALSE for an option that an earlier release declared
        with NO `ui-meta` at all and a later one marks `hidden`: a value a user
        entered then is emptied on every upgraded install (measured). An option
        that was `rw` or `ro` already has its flag in the file and keeps its
        value. So before marking an existing option `hidden`, migrate the value
        yourself. Declaring it `rw` or `ro` for a release first protects only
        the installs that ran that release; one that skips it loses the value
        (measured). A test fails when a `hidden` option it does not already know
        of is declared (`tests/unit/test_hidden_options_in_the_tree.py`).

        A clear that fails is logged and NOT retried at a later start: the flag
        is declared regardless, so the next start finds it. That is deliberate,
        because an undeclared flag would leave the option writable, which is
        worse than a value left in place.
        """
        try:
            with _PASSWORD_SAVE_LOCK:
                if not self.p or self.p.has_option(section, flag):
                    return
                if self.p.get(section, option, fallback='') in ('', None):
                    return
                self.p.set(section, option, '')
            self.log.info('Cleared "%s.%s": it held a value from before its access flag existed',
                          section, option)
        except Exception as error:
            self.log.warning('Could not clear "%s.%s" (%s)', section, option, type(error).__name__)

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
        # One snapshot: the lock a group write holds across its columns and its file
        # write, so values and row count can never come from two different writes.
        # Re-entrant, so a caller already holding it does not deadlock.
        with _PASSWORD_SAVE_LOCK:
            return {
                'options': self.getOptions(),
                'values': self.getValues(),
                'combine_state': self.combine_state(),
            }

    def combine_state(self):
        """Each combine group's state for the page: `{section: {'misaligned', 'rows'}}`.

        The Settings page and the wizard never re-derive alignment or the row count
        in script (Definitions): they read both from here. `misaligned` is
        `group_misaligned` and `rows` is the Definitions' row count, the number of
        rows `group_stored_rows` returns. Nothing here names a section or a column.
        """
        state = {section: {'misaligned': self.group_misaligned(section),
                           'rows': len(self.group_stored_rows(section))}
                 for section in self.combine_groups()}
        # Only a group that holds a credential has a token; the others are saved as
        # they always were and send and receive none.
        for section in self.combine_secrets():
            state[section]['token'] = self._group_token(section)
        return state

    def _group_token_input(self, section, columns, texts):
        """An unambiguous encoding of a group: section, then each column's name and text.

        Every string is framed by its byte length and the column count comes first,
        so no two different (section, names, texts) can encode to the same bytes:
        moving a character from one column's text to the next changes the framing.
        """
        def frame(text):
            data = text.encode('utf-8', 'surrogatepass')
            return len(data).to_bytes(8, 'big') + data

        parts = [frame(section), len(columns).to_bytes(8, 'big')]
        for column, text in zip(columns, texts):
            parts += [frame(column), frame(text)]
        return b''.join(parts)

    def _group_token(self, section):
        """The freshness token of a group that holds a credential, else None.

        A MAC under this instance's random key over the group as stored now. It
        changes when any column changes and for no other reason, and it is
        computed from the same stored text the group is read and written as.
        """
        if section not in self.combine_secrets():
            return None
        columns = self.combine_groups()[section]
        with _PASSWORD_SAVE_LOCK:
            texts = [self._stored_text(section, column) for column in columns]
        message = self._group_token_input(section, columns, texts)
        # The SEC-006 group freshness token, under its own per-process key. It is
        # unrelated to session signing, which lives only in couchpotato/__init__.py.
        return hmac.digest(self._token_key, message, 'sha256').hex()

    def _token_problems(self, section, token):
        """The refusal for a token that cannot be honoured, as a problem list."""
        if token is None:
            return []
        if section not in self.combine_secrets():
            return [_invalid(None, None, 'token_unexpected')]
        if not self._token_is_current(section, token):
            return [_invalid(None, None, 'stale')]
        return []

    def _token_is_current(self, section, token):
        expected = self._group_token(section)
        if expected is None or not isinstance(token, str):
            return False
        return hmac.compare_digest(token.encode('utf-8', 'replace'), expected.encode('ascii'))

    def combine_groups(self):
        """Map each section that stores rows to its ordered column names.

        A "combine" group is a set of options edited as rows but stored as one
        comma-separated list per column, paired back up by position. The only
        source of truth is the `combine` list a provider declares on a
        `type: 'combined'` option and registers through `settings.options`
        (`addOptions`), so nothing here names a section or a column.

        Naming: this and the other group methods below are snake_case, like
        `_coerce_value` and `_password_save_snapshot` and unlike the older
        camelCase methods of the class.
        """
        return {section: tuple(option['combine'])
                for section, option in self._combined_options()}

    def combine_pairing(self):
        """Map each combine group to its pairing columns (Definitions).

        The columns whose cells pair up across a row, declared once as a
        `pairing` list on the same `combined` option as `combine` and derived the
        way `combine_groups` is. A group declared without one is a programming
        error: a unit test reads each group's raw declaration for it. This method
        does not check; it falls back to every column pairing, which errs toward
        refusing and so cannot be used to detect the omission.
        """
        return {section: tuple(option.get('pairing') or option['combine'])
                for section, option in self._combined_options()}

    def combine_secrets(self):
        """Map each combine group that holds credentials to its secret columns.

        Declared once as a `secret` list on the same `combined` option as
        `combine`, and derived the way `combine_groups` is. A group that declares
        none is not listed, so it carries no token and is saved as it always was.
        """
        return {section: tuple(option['secret'])
                for section, option in self._combined_options() if option.get('secret')}

    def combine_addresses(self):
        """Map each secret column to the column its value is sent to, per group.

        The `address` list on the `combined` option runs parallel to `secret`
        (`address[n]` is where `secret[n]` is sent). A secret with no address is
        absent here; a unit sweep over the declarations fails for it.
        """
        return {section: dict(zip(option['secret'], option.get('address') or ()))
                for section, option in self._combined_options() if option.get('secret')}

    def _combined_options(self):
        """Each `(section, option)` whose option is a registered combine group."""
        found = {}
        for section_key, section in self.options.items():
            section_name = section.get('name', section_key)
            for group in section.get('groups', []):
                for option in group.get('options', []):
                    if option.get('type') == 'combined' and option.get('combine'):
                        found[section_name] = option
        return found.items()

    def group_cells(self, section):
        """Each column of a stored group as its cells (Definitions, "Cells").

        A cell is a piece of the raw stored value split on `,`. Nothing is
        trimmed and nothing is dropped, so an empty cell is a position, and an
        empty or missing stored value is one empty cell. The value is read as
        `get()` reads it (a legacy `b'...'` wrapper is stripped first). The columns are the
        group's own (`combine_groups`); a section that is not a group has none.
        """
        columns = self.combine_groups().get(section, ())
        with _PASSWORD_SAVE_LOCK:
            return {column: self._stored_text(section, column).split(',') for column in columns}

    def _stored_text(self, section, column):
        """A stored value as `get()` reads it: the same `_coerce_value`, so a legacy
        bytes-literal wrapper (`b'...'`) is stripped here exactly as it is for the
        provider's own reader. A value that was never stored is empty text."""
        if not self.p.has_option(section, column):
            return ''
        value = _coerce_value(self.p.get(section, column), self.getType(section, column))
        return value if isinstance(value, str) else str(value)

    def group_stored_rows(self, section, short_cells=None):
        """A stored group as rows (Definitions, "Row count"; AC-DATA-13).

        The row count is the largest cell count among the group's pairing columns
        (`combine_pairing`). A column shorter than that supplies
        `short_cells[column]` if the caller states one, else an empty cell for a
        pairing column and the option's declared default for any other. Cells
        beyond the row count are not rows and are not returned.
        """
        short_cells = short_cells or {}
        cells = self.group_cells(section)
        pairing_columns = self.combine_pairing().get(section, ())
        count = max((len(cells[column]) for column in pairing_columns if column in cells), default=1)
        rows = []
        for index in range(count):
            row = {}
            for column, values in cells.items():
                if index < len(values):
                    row[column] = values[index]
                elif column in short_cells:
                    row[column] = short_cells[column]
                elif column in pairing_columns:
                    row[column] = ''
                else:
                    row[column] = (self._declared_default_cells(section, column) or [''])[0]
            rows.append(row)
        return rows

    def group_misaligned(self, section):
        """Do the stored columns of a group disagree about its rows?

        The Definitions' "Misaligned group" (decision D2), for any registered
        group: ignore a pairing column whose cells are all empty (nothing in it
        can be mispaired); the group is misaligned when the remaining pairing
        columns do not all have the same cell count. A non-pairing column never
        makes it so by being shorter, or by being longer only by cells that are
        empty or hold a cell of the column's declared default; any other cell
        past the row count is data whose row cannot be identified.
        """
        cells = self.group_cells(section)
        pairing_columns = self.combine_pairing().get(section, ())
        pairing = {column: cells[column] for column in pairing_columns if column in cells}
        if len({len(values) for values in pairing.values() if any(values)}) > 1:
            return True
        count = max((len(values) for values in pairing.values()), default=1)
        for column, values in cells.items():
            allowed = {''} | set(self._declared_default_cells(section, column) or [])
            if column not in pairing and any(cell not in allowed for cell in values[count:]):
                return True
        return False

    def _declared_default_cells(self, section, column):
        """The cells of the default a provider declared for `column`, or None."""
        for group in self.options.get(section, {}).get('groups', []):
            for option in group.get('options', []):
                if option.get('name') == column and 'default' in option:
                    return str(option['default']).split(',')
        return None

    def reveal_cell_view(self, section=None, column=None, row=None, token=None, **kwargs):
        """The API view of `reveal_cell`. Anything beyond the four members is malformed."""
        if kwargs:
            return self._refuse_reveal(None, 'malformed')
        return self.reveal_cell(section, column, row, token)

    def reveal_cell(self, section, column, row, token):
        """The stored text of secret cell `row` of `column`, or a refusal with no value.

        The one place a stored credential leaves the settings. `row` is the cell index of
        the secret column itself, whether or not the group is aligned. A refusal is, in
        this order: a section that is not a registered group; a column the group does not
        declare secret; no token; a stale token; a row that is not a JSON integer or is
        outside the column. The hold is never read. Reply: `{'success': True, 'value':
        text}` and nothing else; an empty stored cell is an empty `value`.
        """
        try:
            with _PASSWORD_SAVE_LOCK:
                if not isinstance(section, str) or section not in self.combine_groups():
                    return self._refuse_reveal(None, 'unknown_section')
                if not isinstance(column, str) or column not in self.combine_secrets().get(section, ()):
                    return self._refuse_reveal(section, 'bad_reference')
                if token is None:
                    return self._refuse_reveal(section, 'token_missing')
                if not self._token_is_current(section, token):
                    return self._refuse_reveal(section, 'stale')
                cells = self.group_cells(section)[column]
                if type(row) is not int or not 0 <= row < len(cells):
                    return self._refuse_reveal(section, 'bad_reference')
                value = cells[row]
                self.log.info('Revealed a stored key: section=%s column=%s row=%d', section, column, row)
                return {'success': True, 'value': value}
        except Exception as error:
            # The type only: nothing read, held or sent is in the log or the reply.
            self.log.error('Could not reveal a stored key (%s).', type(error).__name__)
            return {'success': False, 'error': _REVEAL_FAILED_TEXT}

    def _refuse_reveal(self, section, reason):
        # A caller's section string is never logged: only a registered name is.
        self.log.warning('Refused a settings reveal: section=%s reason=%s',
                         section or 'unregistered', reason)
        return {'success': False, 'error': _REVEAL_REFUSAL_TEXT[reason],
                'invalid': [_invalid(None, None, reason)]}

    def save_group_view(self, section=None, rows=None, token=None, **kwargs):
        """The API view: a thin relay to `save_group` that adds the INFO line.

        The transport (a JSON POST of exactly `section` and `rows`) is enforced
        in the API dispatch (plus an optional `token`). Anything else reaching here
        is refused as malformed.
        """
        if kwargs:
            return self._refuse_group(None, [_invalid(None, None, 'malformed')])
        result = self.save_group(section, rows, token)
        if result.get('success'):
            self.log.info('Saved a settings group: section=%s rows=%d', section, len(rows))
        return result

    def save_group(self, section, rows, token=None):
        """Write one combine group from rows: every column, or nothing.

        `rows` is a list of dicts, each holding exactly the group's columns as
        strings, or a callable that returns such a list (a builder). A builder
        runs under the lock this method takes, so a caller can read the stored
        rows and write them in one continuous hold (AC-ARCH-11(ii)); it may
        raise `GroupMisaligned` to decline. A builder only reads and returns
        rows: the group's columns are snapshotted BEFORE it is called, so any
        write it makes to them is undone on a refusal or a failure. It must
        never call `save()` (a write to disk cannot be undone) or write outside
        the group.

        `token`, when given, is the group's token from the settings read: a save
        built on a group that has since changed is refused as `stale`, nothing
        written, and an accepted one returns `{'success': True, 'token': fresh}`.
        With no token the save behaves, and replies, exactly as it always did.

        Returns `{'success': True}`, or `{'success': False, 'error': text,
        'invalid': [{'row', 'column', 'reason'}, ...]}` for a refusal, or
        `{'success': False, 'error': text}` when the file could not be written
        or a builder raised something other than `GroupMisaligned`. It never
        raises for either, and logs the refusal (WARNING, once) or the failure
        (ERROR, once) itself, without a cell value.

        Validation comes first and mutates nothing. The parser is then written
        and saved under one hold of the lock, and put back if the save fails,
        so a failed write cannot be persisted by the next unrelated save.

        One window is accepted and is not a defect: an interrupt (a
        `BaseException`) after `os.replace` has succeeded leaves the disk
        holding the new whole group while memory is rolled back. The next save
        writes memory out and restores the disk. Both states are whole, aligned
        groups.
        """
        with _PASSWORD_SAVE_LOCK:
            return self._save_group(section, rows, token)

    def _save_group(self, section, rows, token=None):
        columns = self.combine_groups().get(section) if isinstance(section, str) else None
        if columns is None:
            # The caller's text is not logged: it is not a registered name.
            return self._refuse_group(None, [_invalid(None, None, 'unknown_section')])
        snapshot = self._group_snapshot(section, columns)
        plan = None
        try:
            rows = rows() if callable(rows) else rows
            problems, held, rows, plan = self._resolve_group_cells(section, columns, rows, token)
            if not problems:
                problems = [_invalid(None, column, 'not_writable') for column in columns
                            if not self.isOptionWritable(section, column)]
                problems += _group_problems(rows, columns, self.combine_secrets().get(section, ()))
            if problems:
                result = self._refuse_group(section, problems, held)
            else:
                result = self._write_group(section, columns, rows)
        except GroupMisaligned:
            result = self._refuse_group(section, [_invalid(None, None, 'misaligned')])
        except Exception as error:
            result = self._group_write_failed(section, error)
        except BaseException:
            self._restore_group(section, snapshot)
            raise
        if not result['success']:
            self._restore_group(section, snapshot)
            return result
        # The group is written. Nothing from here on may restore it or report a
        # failure: the file holds the new rows, so a failure reply would be a lie
        # and a restore would put the old rows back over a later unrelated save.
        # Still under the caller's hold of the lock.
        return self._after_group_written(section, token, result, plan, rows)

    @staticmethod
    def _cell_form(cell):
        """`('keep', i)`, `('restore', (token, row))` or None for a dict that is neither."""
        def index(value):
            return type(value) is int and value >= 0

        if set(cell) == {'keep'} and index(cell['keep']):
            return 'keep', cell['keep']
        reference = cell.get('restore') if set(cell) == {'restore'} else None
        if (isinstance(reference, dict) and set(reference) == {'token', 'row'}
                and isinstance(reference['token'], str) and index(reference['row'])):
            return 'restore', (reference['token'], reference['row'])
        return None

    def _resolve_group_cells(self, section, columns, rows, token):
        """Turn `keep` and `restore` cells into the text they stand for, or say why not.

        Returns `(problems, held, rows, plan)`. `rows` is the list to validate and
        write (a copy, with each form replaced by its text); `plan` is what to do
        once the write has landed. A save with no form in it passes through
        untouched: a token-less all-string save and a builder save behave as they
        always did. Order of refusals: a form that is malformed, in the wrong column
        or repeated; a restore nobody holds (decided BEFORE the token, so a restore
        whose reply was lost is not taken for a stale save); a form with no token; a
        bad token; an index outside the column. `i` is always cell `i` of the secret
        column, so a keep follows the pairing the providers already use.
        """
        secrets_ = self.combine_secrets().get(section, ())
        plan = {'kept': [], 'restored': [], 'candidates': [], 'cells': None}
        if not isinstance(rows, list):
            return (*self._token_failure(section, token), rows, plan)
        forms = []
        problems = []
        seen = set()
        for position, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for column in columns:
                cell = row.get(column)
                if not isinstance(cell, dict):
                    continue
                if column not in secrets_:
                    if 'keep' in cell or 'restore' in cell:
                        problems.append(_invalid(position, column, 'bad_reference'))
                    continue
                form = self._cell_form(cell)
                if form is None or (column,) + form in seen:
                    problems.append(_invalid(position, column, 'bad_reference'))
                    continue
                seen.add((column,) + form)
                forms.append((position, column) + form)
        if problems:
            return problems, None, rows, plan
        unknown = [_invalid(position, column, 'restore_unknown')
                   for position, column, kind, value in forms
                   if kind == 'restore' and self._hold.peek(section, column, value[0], value[1]) is None]
        if unknown:
            return unknown, None, rows, plan
        if forms and token is None:
            return [_invalid(None, None, 'token_missing')], None, rows, plan
        failure, listing = self._token_failure(section, token)
        if failure:
            return failure, listing, rows, plan
        if token is None:
            return [], None, rows, plan
        cells = self.group_cells(section)
        plan['cells'] = cells
        out = [dict(row) if isinstance(row, dict) else row for row in rows]
        kept = {column: set() for column in secrets_}
        for position, column, kind, value in forms:
            if kind == 'keep':
                if value >= len(cells[column]):
                    problems.append(_invalid(position, column, 'bad_reference'))
                    continue
                out[position][column] = cells[column][value]
                kept[column].add(value)
                plan['kept'].append((position, column, value))
            else:
                out[position][column] = self._hold.peek(section, column, value[0], value[1])
                plan['restored'].append((position, column, value))
        if problems:
            return problems, None, rows, plan
        plan['candidates'] = [(column, index, text) for column in secrets_
                              for index, text in enumerate(cells[column])
                              if text != '' and index not in kept[column]]
        return [], None, out, plan

    def _token_failure(self, section, token):
        """`(problems, held)` for a token that cannot be honoured; `held` only for `stale`."""
        problems = self._token_problems(section, token)
        if problems and problems[0]['reason'] == 'stale':
            return problems, self._stale_listing(section, token)
        return problems, None

    def _stale_listing(self, section, token):
        """The cells held under `token`, as column and index only (none for a forged token)."""
        if not isinstance(token, str):
            return []
        return [{'column': column, 'row': row} for column, row in self._hold.list_by_token(section, token)]

    def _after_group_written(self, section, token, result, plan, rows):
        """Everything that follows a landed write: the INFO lines, the hold and the reply token.

        Each step is guarded on its own and logs the exception TYPE only, so no
        failure here can turn an accepted save into a failure reply, restore the old
        rows, or put a key or token into a log. The hold is made and consumed only
        here, after the write.
        """
        if plan and plan['cells'] is not None:
            self._log_kept_and_restored(section, plan, rows)
            try:
                for _, column, (held_token, row) in plan['restored']:
                    self._hold.take(section, column, held_token, row)
                for column, index, text in plan['candidates']:
                    self._hold.add(section, column, token, index, text)
            except Exception as error:
                self.log.error('Saved the settings group "%s" but could not update the '
                               'record of removed keys (%s).', section, type(error).__name__)
        if token is not None:
            try:
                result['token'] = self._group_token(section)
            except Exception as error:
                # The reply simply carries no token: the page keeps its old one and
                # gets a clean stale refusal next time. The type only is logged.
                self.log.error('Saved the settings group "%s" but could not compute '
                               'its token (%s).', section, type(error).__name__)
        return result

    def _log_kept_and_restored(self, section, plan, rows):
        """INFO lines for a landed save: a key kept on a changed address, a key restored.

        Section, column and row only: never an address, a key or a token.
        """
        try:
            addresses = self.combine_addresses().get(section, {})
            for position, column, index in plan['kept']:
                where = addresses.get(column)
                if where is None:
                    continue
                stored = plan['cells'][where]
                before = stored[index] if index < len(stored) else ''
                if rows[position].get(where, '') != before:
                    self.log.info('Kept a stored key on a changed address: section=%s '
                                  'column=%s row=%d', section, column, position)
            for position, column, _ in plan['restored']:
                self.log.info('Restored a removed key: section=%s column=%s row=%d',
                              section, column, position)
        except Exception as error:
            self.log.error('Could not log a kept or restored key (%s).', type(error).__name__)
        return None

    def _refuse_group(self, section, problems, held=None):
        first = problems[0]
        self.log.warning('Refused a settings group save: section=%s first_row=%s '
                         'first_column=%s reason=%s offences=%d',
                         section or 'unregistered', first['row'], first['column'],
                         first['reason'], len(problems))
        return _group_refusal(problems, held)

    def _group_write_failed(self, section, error):
        self.log.error('Could not save the settings group "%s" (%s). '
                       'Nothing was changed.', section, type(error).__name__)
        return {'success': False,
                'error': 'The settings could not be saved. Nothing was changed.'}

    def _write_group(self, section, columns, rows):
        """Set every column and save once. Raises on failure; the caller restores."""
        self.addSection(section)
        for column in columns:
            self.set(section, column, ','.join(row[column] for row in rows))
        self.save()
        return {'success': True}

    def _group_snapshot(self, section, columns):
        """The group's stored strings, or None when the section does not exist yet."""
        if not self.p.has_section(section):
            return None
        return {column: self.p.get(section, column) if self.p.has_option(section, column) else None
                for column in columns}

    def _restore_group(self, section, snapshot):
        if snapshot is None:
            self.p.remove_section(section)
            return
        # A builder that removed the section must not turn a refusal into a
        # NoSectionError: put the section back so the columns can be restored.
        # Options outside the group that it removed are not undone (a builder
        # only reads; see save_group).
        if not self.p.has_section(section):
            self.p.add_section(section)
        for column, previous in snapshot.items():
            if previous is None:
                self.p.remove_option(section, column)
            else:
                self.p.set(section, column, previous)

    def combine_column(self, section, option):
        """The declared column `option` would become in `section`, or None.

        The one membership test. The name is folded the way the config parser
        folds it (`optionxform`) after `strip()`, because that is the column it
        would become: a trailing space reloads as a duplicate option and `API_KEY`
        writes `api_key`. A name that is not a string is not a member. The answer
        is the registered column, so a caller can name it without echoing what
        was submitted.
        """
        columns = self.combine_groups().get(section)
        if not columns or not isinstance(option, str):
            return None
        fold = self.p.optionxform if self.p else str.lower
        wanted = fold(option.strip())
        return next((column for column in columns if fold(column) == wanted), None)

    def is_combine_option(self, section, option):
        """Would `option` become a column of a combine group in `section`?"""
        return self.combine_column(section, option) is not None

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

    def _refuse_per_column(self, section, name):
        """The refusal for a per-column save that must not reach the file, or None.

        Two refusals, in this order. A column of a combine group is refused first,
        so `host ` in a combine section gets the combine text (the membership
        test folds `strip()`: that is the column it would become). Then any name
        holding whitespace or a C0 control character, for every section: the
        parser reloads a trailing space as a duplicate option, which stops the
        server starting, and a leading one as a continuation of the previous
        option's value.

        Both return before anything is set, hooked or saved. Neither log line nor
        either body carries the submitted value, and the combine refusal names
        the registered column rather than the caller's spelling.
        """
        if not (isinstance(section, str) and isinstance(name, str)):
            # A list (`section[0]=...`), an object, a number, or no name at all. Nothing of
            # the caller's is logged: it is not text, and may be anything.
            self.log.warning('Refused a settings save: the section or the option name '
                             'was not text')
            return {'success': False, 'error': _NOT_TEXT_REFUSAL}
        if self.isOptionMeta(section, name):
            # Before the name rule, so ` x_internal_meta` gets this text. Neither
            # the caller's spelling nor the value is logged or returned.
            self.log.warning('Refused a settings save: the option name is an access '
                             'flag (section=%.40r)', section)
            return {'success': False, 'error': _FLAG_NAME_REFUSAL}
        column = self.combine_column(section, name)
        if column is not None:
            self.log.warning('Refused a per-column save of "%s.%s": it is saved '
                             'with its group, not on its own', section, column)
            return {'success': False,
                    'error': _COMBINE_COLUMN_REFUSAL % (section, column)}
        if _unsafe_option_name(name):
            # `%r` escapes a control character, so the caller's text cannot forge a log line.
            self.log.warning('Refused a settings save: the option name is not allowed '
                             '(section=%.40r)', section)
            return {'success': False, 'error': _BAD_OPTION_NAME_REFUSAL}
        return None

    def saveView(self, **kwargs):
        refusal = self._refuse_per_column(kwargs.get('section'), kwargs.get('name'))
        if refusal is not None:
            return refusal
        # ConfigParser folds an option name (`optionxform`), but the mask check,
        # `getType`, the value hook, the events and the lock below are keyed on
        # the exact string. Hand them the name the option is stored under.
        parser = getattr(self, 'p', None)
        fold = parser.optionxform if parser else str.lower
        kwargs['name'] = fold(kwargs['name'])
        if (kwargs.get('section') == 'core'
                and kwargs.get('name') in ('password', 'auth_required')):
            with _PASSWORD_SAVE_LOCK:
                return self._saveView(**kwargs)
        if self._has_value_hook(kwargs['section'], kwargs['name']):
            # A value hook may set a companion option (a hidden option the server
            # keeps beside the one being saved). The hook, the writes and the file
            # save must be one hold of the lock, or another writer can change
            # what the hook read between its read and the save, and a failed
            # save has nothing to restore. Any option with a hook, by rule.
            with _PASSWORD_SAVE_LOCK:
                return self._saveView(**kwargs)
        return self._saveView(**kwargs)

    def _has_value_hook(self, section, option):
        return bool(getEvent('setting.save.%s.%s' % (section, option)))

    def _section_snapshot(self, section):
        """Every option of `section` as memory holds it now, or None for a missing section."""
        if not self.p.has_section(section):
            return None
        return {name: self.p.get(section, name) for name in self.p.options(section)}

    def _restore_section(self, section, snapshot):
        """Put the section back as `_section_snapshot` found it, and say nothing about the file."""
        if snapshot is None or not self.p.has_section(section):
            return
        for name in self.p.options(section):
            if name not in snapshot:
                self.p.remove_option(section, name)
        for name, value in snapshot.items():
            self.p.set(section, name, value)

    def _recover_failed_save(self, section, snapshots, stored, marker, submitted):
        """After `save()` raised: put memory back so the next writer cannot persist this attempt.

        The file is replaced whole or not at all (`_save`), so a failure that
        reaches here left it as it was. The password and `auth_required` saves
        have their own recovery, which also checks what the file holds; every
        other save restores the section it may have changed, so a companion
        option a value hook set is not written out by the next, unrelated save.
        """
        password_snapshot, auth_snapshot, section_snapshot = snapshots
        if password_snapshot is not None:
            self._recover_failed_password_save(password_snapshot, stored, marker, submitted)
        elif auth_snapshot is not None:
            self._recover_failed_auth_save(auth_snapshot[0], stored)
        else:
            self._restore_section(section, section_snapshot)

    def _password_save_snapshot(self):
        """Keep the gate and revocation marker until a new hook prepares both."""
        snapshot = {
            name: self.p.get('core', name) if self.p.has_option('core', name) else None
            for name in ('password', 'auth_required', 'session_rotation_pending')
        }
        if self.p.has_section('core'):
            self.p.remove_option('core', 'auth_required')
            self.p.remove_option('core', 'session_rotation_pending')
        return snapshot

    def _restore_password_save_snapshot(self, snapshot):
        if snapshot is None:
            return
        for name, previous in snapshot.items():
            if previous is None:
                if self.p.has_section('core'):
                    self.p.remove_option('core', name)
            else:
                self.p.set('core', name, previous)

    def _password_hook_prepared(self, submitted, new_value):
        auth_required = (self.p.get('core', 'auth_required')
                         if self.p.has_option('core', 'auth_required') else None)
        marker = (self.p.get('core', 'session_rotation_pending')
                  if self.p.has_option('core', 'session_rotation_pending') else None)
        expected = '1' if submitted else '0'
        hash_ready = (new_value == '' if not submitted else
                      isinstance(new_value, str)
                      and len(new_value) == 60
                      and new_value.startswith(('$2a$', '$2b$', '$2y$')))
        return (str(auth_required) == expected
                and str(marker) == expected and hash_ready), marker

    def _saved_option_landed(self, option, expected, marker=None):
        """Read the actual config after a save that may have raised post-commit."""
        try:
            persisted = ConfigParser.RawConfigParser()
            with open(os.path.realpath(self.file), encoding='utf-8') as configfile:
                persisted.read_file(configfile)
            landed = persisted.get('core', option, fallback=None) == str(expected)
            if marker is not None:
                landed = (landed and persisted.get(
                    'core', 'session_rotation_pending', fallback=None) == str(marker))
            return landed
        except FileNotFoundError:
            return False
        except Exception:
            # The on-disk outcome is unknown; callers must fail closed.
            return None

    def _recover_failed_password_save(self, snapshot, stored, marker, submitted):
        landed = self._saved_option_landed(
            'password', stored, marker=marker)
        if landed is False or (landed is None and not submitted):
            self._restore_password_save_snapshot(snapshot)
        elif submitted:
            self.p.set('core', 'session_rotation_pending', 1)
            self.log.error('Password settings may have committed, but '
                           'session revocation did not run. Browser '
                           'sessions are blocked until restart.')

    def _recover_failed_auth_save(self, previous, stored):
        landed = self._saved_option_landed('auth_required', stored)
        disabling = str(stored).strip().lower() in ('', '0', 'false', 'no', 'off')
        if landed is False or (landed is None and disabling):
            if previous is None:
                if self.p.has_section('core'):
                    self.p.remove_option('core', 'auth_required')
            else:
                self.p.set('core', 'auth_required', previous)

    def _masked_credential_response(self, section, option, value):
        current = self.get(option, section) if value else None
        if (value and current
                and self.getType(section, option) == 'password'
                and str(value) == len(str(current)) * '*'):
            self.log.warning(
                'Refused to save "%s.%s": the value is the displayed mask, not '
                'a credential. Clear the field and paste the real value to '
                'change it.', section, option)
            return {
                'success': False,
                'error': 'That is the masked placeholder, not the real value. '
                         'Clear the field and paste the credential to change it.',
            }
        return None

    def _normalise_saved_path(self, section, option, value):
        from couchpotato.environment import Env
        soft_chroot = Env.get('softchroot')
        try:
            option_type = self.getType(section, option)
            if option_type == 'directory':
                value = soft_chroot.chroot2abs(value)
            elif option_type == 'directories':
                value = self._parse_directories(value, soft_chroot)
        except ValueError:
            self.log.warning('Refused "%s.%s": the path resolves outside the '
                             'configured soft chroot', section, option)
            return value, {'success': False}
        return value, None

    def _prepare_saved_value(self, section, option, value):
        """Run a value hook without exposing a half-prepared auth transaction."""
        password_snapshot = None
        auth_snapshot = None
        if section == 'core' and option == 'password':
            password_snapshot = self._password_save_snapshot()
        elif (section == 'core' and option == 'auth_required'
              and getattr(self, 'p', None) is not None):
            auth_snapshot = (self.p.get('core', 'auth_required')
                             if self.p.has_option('core', 'auth_required') else None,)

        try:
            new_value = fireEvent('setting.save.%s.%s' % (section, option), value, single=True)
        except Exception:
            self._restore_password_save_snapshot(password_snapshot)
            raise

        marker = None
        if password_snapshot is not None:
            prepared, marker = self._password_hook_prepared(value, new_value)
            if not prepared:
                self._restore_password_save_snapshot(password_snapshot)
                self.log.error('Refused password save: hashing, authentication '
                               'state or durable session revocation intent '
                               'was not prepared')
                return None, None, None, None, {
                    'success': False,
                    'error': 'Password could not be saved safely. Try again.',
                }
        return new_value, password_snapshot, auth_snapshot, marker, None

    def _saveView(self, **kwargs):
        section = kwargs.get('section')
        option = kwargs.get('name')
        value = kwargs.get('value')

        if not self.isOptionWritable(section, option):
            self.log.warning('Option "%s.%s" isn\'t writable', section, option)
            return {'success': False}

        # `getValues()` returns a password-typed option as a run of asterisks,
        # and the settings form posts field values back. Without this, saving
        # the DISPLAYED mask overwrites the real credential and reports
        # success -- the user then has to re-issue it at the provider, which
        # for a tracker passkey can mean contacting staff. Irreplaceable-class
        # loss caused by opening a page and touching a field.
        #
        # The client happens not to trigger it today (the password input binds
        # `@change`, not `@input`, so an untouched field posts nothing), but
        # that is an accident of which events a browser fires -- a password
        # manager autofilling the field dispatches `change`. The guard belongs
        # here, where it does not depend on that.
        #
        # Match the mask's EXACT shape, not merely "contains an asterisk".
        # `getValues` renders it as `len(value) * '*'`, so it is always a pure
        # run of asterisks and nothing is lost by being precise.
        #
        # The first version of this guard used `'*' in value` and was a
        # security regression, which review caught. Its reasoning only
        # considered ISSUED tokens -- true that no provider here mints one
        # containing `*` -- and ignored the 19 pre-existing password options
        # that hold HUMAN-CHOSEN passwords: `core.password`, `proxy_password`,
        # every downloader and tracker login, `smtp_pass`. `*` is in the
        # default symbol set of every mainstream password generator, so
        # refusing it is refusing a routine password.
        #
        # Worse than an annoyance: `wizard.html` fires `saveSetting` without
        # reading the response, so a first-run operator choosing a password
        # with `*` would be told authentication was configured while the save
        # was refused, `Core.md5Password` never ran, `auth_required` was never
        # set -- and the instance stayed public. A credential-protecting change
        # would have created an unauthenticated server.
        #
        # Narrowed once more after review: matching "all asterisks" RESERVED a
        # valid credential value, and the field it hurts most is `core.password`
        # -- combined with the wizard discarding the response (T51), a user
        # choosing `****` would be told authentication was on while the server
        # stayed public. Reserving a value is the wrong shape when the failure
        # mode is silent.
        #
        # So compare against the mask that WOULD be rendered for the value
        # currently stored: same length, all asterisks, and something actually
        # stored. A fresh `****` password saves fine. The only residue is
        # changing an existing N-character credential to exactly N asterisks,
        # which is as close to nothing as this can get without a round-trip
        # token.
        #
        # Scope, stated so it is not mistaken for coverage: `getType` returns
        # 'unicode' for an option nobody registered, so this guard does NOT
        # fire for orphaned sections -- which `getValues` masks anyway (T31).
        # Saving a mask over an orphan therefore still writes it. Not reachable
        # from the settings page, which only renders registered options, but it
        # is reachable through the API. Deliberately not widened here: an
        # orphan's value belongs to a plugin that no longer exists.
        masked = self._masked_credential_response(section, option, value)
        if masked is not None:
            return masked

        # chroot2abs now refuses a value that resolves outside the soft
        # chroot instead of concatenating it through. That closes a second
        # bypass -- a chrooted user could previously save a directory of
        # `../../mnt` and have it written verbatim, after which the renamer
        # and the scanner operated outside the chroot entirely -- but it
        # means these two calls can raise, so they are handled here rather
        # than surfacing as a 500 with the path in a logged traceback.
        value, path_error = self._normalise_saved_path(section, option, value)
        if path_error is not None:
            return path_error

        # A password value hook also changes auth_required and the durable
        # session-rotation marker in this parser. If the atomic file save
        # fails, restore all three in memory: a later unrelated settings
        # save must not silently commit the failed password attempt.
        # Taken before the value hook runs: a hook may set a companion option.
        section_snapshot = self._section_snapshot(section) if self._has_value_hook(section, option) else None
        (new_value, password_snapshot, auth_snapshot, marker,
         refusal) = self._prepare_saved_value(section, option, value)
        if refusal is not None:
            return refusal
        # Use plain string — .encode('unicode_escape') produces bytes which ConfigParser
        # serialises as b'...' literals (Python 3 bug)
        stored = _resolve_saved_value(new_value, value)
        self.set(section, option, stored)
        try:
            self.save()
        except Exception:
            self._recover_failed_save(
                section, (password_snapshot, auth_snapshot, section_snapshot), stored, marker, value)
            raise

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
        """Is `option` the name of an option's access flag, in any spelling?

        The name is lower-cased the way the config parser stores it
        (`optionxform`): `API_KEY_INTERNAL_META` is stored as
        `api_key_internal_meta`, the real flag, so a case-sensitive suffix test
        let a caller overwrite a read-only option's flag. `strip()` is not what
        the parser does on write (a name with whitespace is refused by the
        unsafe-name rule either way); here it only decides which refusal text a
        whitespace spelling gets. A name that is not text is not a flag name.
        """
        if not isinstance(option, str):
            return False
        # `str.lower` is the parser's own `optionxform` (nothing here replaces it;
        # a test pins that). It is named directly so a parser stand-in whose
        # `optionxform` is not a real function cannot make every name a flag.
        return option.strip().lower().endswith(self.optionMetaSuffix())

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
            # Identifiers come from callers and may themselves contain
            # sensitive text. A miss does not need the name in the log.
            self.log.debug('Property not yet stored, will use default')

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
