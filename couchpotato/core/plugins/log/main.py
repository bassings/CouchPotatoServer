import os
import re
import traceback

from couchpotato.api import addApiView
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.variable import tryInt, splitString
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.environment import Env


log = CPLog(__name__)

_LOG_LEVELS = frozenset(('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'))


def _next_field(value, start):
    while start < len(value) and value[start].isspace():
        start += 1
    end = start
    while end < len(value) and not value[end].isspace():
        end += 1
    return value[start:end], end


def _is_log_date(value):
    return (
        len(value) == 5
        and value[2] == '-'
        and value[:2].isdecimal()
        and value[3:].isdecimal()
    )


def _is_log_time(value):
    return (
        len(value) == 8
        and value[2] == ':'
        and value[5] == ':'
        and value[:2].isdecimal()
        and value[3:5].isdecimal()
        and value[6:].isdecimal()
    )


def _parse_log_header(line):
    """Parse one formatter line in a bounded number of passes."""
    if not line or line[0].isspace():
        return None
    date, date_end = _next_field(line, 0)
    time, time_end = _next_field(line, date_end)
    level, level_end = _next_field(line, time_end)
    if not (_is_log_date(date) and _is_log_time(time) and level in _LOG_LEVELS):
        return None
    if level_end >= len(line) or not line[level_end].isspace():
        return None
    message_start = level_end
    while message_start < len(line) and line[message_start].isspace():
        message_start += 1
    return line[:time_end], level, line[message_start:]


class Logging(Plugin):

    def __init__(self):
        addApiView('logging.get', self.get, docs = {
            'desc': 'Get the full log file by number',
            'params': {
                'nr': {'desc': 'Number of the log to get.'}
            },
            'return': {'type': 'object', 'example': """{
    'success': True,
    'log': [{
        'time': '03-12 09:12:59',
        'type': 'INFO',
        'message': 'Log message'
    }, ..], //Log file
    'total': int, //Total log files available
}"""}
        })
        addApiView('logging.partial', self.partial, docs = {
            'desc': 'Get a partial log',
            'params': {
                'type': {'desc': 'Type of log', 'type': 'string: all(default), error, info, debug'},
                'lines': {'desc': 'Number of lines. Last to first. Default 30'},
            },
            'return': {'type': 'object', 'example': """{
    'success': True,
    'log': [{
        'time': '03-12 09:12:59',
        'type': 'INFO',
        'message': 'Log message'
    }, ..]
}"""}
        })
        addApiView('logging.clear', self.clear, docs = {
            'desc': 'Remove all the log files'
        })
        addApiView('logging.log', self.log, docs = {
            'desc': 'Log errors',
            'params': {
                'type': {'desc': 'Type of logging, default "error"'},
                '**kwargs': {'type': 'object', 'desc': 'All other params will be printed in the log string.'},
            }
        })

    def get(self, nr = 0, **kwargs):

        nr = tryInt(nr)
        current_path = None

        total = 1
        for x in range(0, 50):

            path = '%s%s' % (Env.get('log_path'), '.%s' % x if x > 0 else '')

            # Check see if the log exists
            if not os.path.isfile(path):
                total = x - 1
                break

            # Set current path
            if x is nr:
                current_path = path

        log_content = ''
        if current_path:
            f = open(current_path, 'r')
            log_content = f.read()
        logs = self.toList(log_content)

        return {
            'success': True,
            'log': logs,
            'total': total,
        }

    def partial(self, type = 'all', lines = 30, offset = 0, **kwargs):

        total_lines = tryInt(lines)
        offset = tryInt(offset)

        log_lines = []

        for x in range(0, 50):

            path = '%s%s' % (Env.get('log_path'), '.%s' % x if x > 0 else '')

            # Check see if the log exists
            if not os.path.isfile(path):
                break

            f = open(path, 'r')
            log_content = toUnicode(f.read())
            raw_lines = self.toList(log_content)
            raw_lines.reverse()

            brk = False
            for line in raw_lines:

                if type == 'all' or line.get('type') == type.upper():
                    log_lines.append(line)

                if len(log_lines) >= (total_lines + offset):
                    brk = True
                    break

            if brk:
                break

        log_lines = log_lines[offset:]
        log_lines.reverse()

        return {
            'success': True,
            'log': log_lines,
        }

    def toList(self, log_content = ''):

        log_content = toUnicode(log_content)
        # Strip ANSI escape codes if present
        log_content = re.sub(r'\x1b\[\d*m', '', log_content)

        logs = []
        # Match log lines: "MM-DD HH:MM:SS LEVEL [module] message"
        # Continuation lines (starting with whitespace) are appended to previous entry
        current_entry = None
        for line in log_content.split('\n'):
            header = _parse_log_header(line)
            if header:
                if current_entry:
                    logs.append(current_entry)
                timestamp, level, message = header
                current_entry = {
                    'time': timestamp,
                    'type': level,
                    'message': message
                }
            elif current_entry and line.strip():
                current_entry['message'] += '\n' + line

        if current_entry:
            logs.append(current_entry)

        return logs

    def clear(self, **kwargs):

        for x in range(0, 50):
            path = '%s%s' % (Env.get('log_path'), '.%s' % x if x > 0 else '')

            if not os.path.isfile(path):
                continue

            try:

                # Create empty file for current logging
                if x == 0:
                    self.createFile(path, '')
                else:
                    os.remove(path)

            except Exception:
                log.error('Couldn\'t delete file "%s": %s', path, traceback.format_exc())

        return {
            'success': True
        }

    def log(self, type = 'error', **kwargs):

        try:
            log_message = 'API log: %s' % kwargs
            try:
                getattr(log, type)(log_message)
            except Exception:
                log.error(log_message)
        except Exception:
            log.error('Couldn\'t log via API: %s', kwargs)

        return {
            'success': True
        }
