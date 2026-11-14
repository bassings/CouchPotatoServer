"""A real ``Settings`` over a temporary ``config.ini`` with the real combine groups.

SEC-004 tests drive the genuine option declarations of the five providers that
store a row per position (``combine``), registered the way the loader registers
them, so a test cannot pass against a hand-rolled stand-in that is gentler than
production. Nothing here touches a real configuration: the file lives under the
caller's ``tmp_path``.

Registration state is process-wide in the code under test (``Settings.options``
and ``Settings.types`` are class attributes, ``addApiView`` writes a module
registry, ``Settings.setFile`` subscribes to the event bus), so
``group_settings`` isolates all of it and puts it back on exit.
"""
import configparser
import contextlib
import hashlib
import logging
import threading
from pathlib import Path

from couchpotato.core.settings import Settings

SECTIONS = ('newznab', 'torrentpotato', 'imdb', 'itunes', 'letterboxd')

# Columns whose reader does arithmetic on the cell, so a placeholder must be
# numeric for the real reader to accept it.
NUMERIC_COLUMNS = ('extra_score', 'seed_ratio', 'seed_time')
HOST_COLUMNS = ('host', 'automation_urls')


def provider_configs():
    """The five real ``config`` declarations, imported lazily."""
    from couchpotato.core.media._base.providers.nzb.newznab import config as newznab
    from couchpotato.core.media._base.providers.torrent.torrentpotato import config as torrentpotato
    from couchpotato.core.media.movie.providers.automation.imdb import config as imdb
    from couchpotato.core.media.movie.providers.automation.itunes import config as itunes
    from couchpotato.core.media.movie.providers.automation.letterboxd import config as letterboxd
    return [newznab, torrentpotato, imdb, itunes, letterboxd]


def register_providers(settings):
    """Register every declaration exactly as ``Loader.loadSettings`` does."""
    for config in provider_configs():
        for section in config:
            settings.addOptions(section['name'], section)
            options = {}
            for group in section['groups']:
                for option in group['options']:
                    options[option['name']] = option
            settings.registerDefaults(section['name'], options, save=False)


@contextlib.contextmanager
def group_settings(tmp_path, monkeypatch, stored=None):
    """Yield a ``Settings`` bound to ``tmp_path/config.ini`` with the real groups.

    ``stored`` maps section -> {option: raw value} and is written to the file
    before the settings are loaded, so it is a genuine starting state that
    ``registerDefaults`` then leaves alone. The registered defaults are saved
    once, so the file on disk is the baseline every test hashes against.
    """
    import couchpotato.core.event as event_module
    from couchpotato.api import api, api_docs, api_docs_missing, api_locks

    saved = (dict(api), dict(api_locks), dict(api_docs), list(api_docs_missing))
    monkeypatch.setattr(event_module, 'events',
                        {name: list(handlers) for name, handlers in event_module.events.items()})
    monkeypatch.setattr(Settings, 'options', {})
    monkeypatch.setattr(Settings, 'types', {})

    path = tmp_path / 'config.ini'
    if stored:
        seed = configparser.RawConfigParser()
        for section, options in stored.items():
            seed.add_section(section)
            for name, value in options.items():
                seed.set(section, name, value)
        with open(path, 'w', encoding='utf-8') as handle:
            seed.write(handle)

    settings = Settings()
    settings.setFile(str(path))
    register_providers(settings)
    settings.save()
    try:
        yield settings
    finally:
        api.clear()
        api.update(saved[0])
        api_locks.clear()
        api_locks.update(saved[1])
        api_docs.clear()
        api_docs.update(saved[2])
        api_docs_missing[:] = saved[3]


def three_rows(settings, section, tag='a'):
    return placeholder_rows(settings.combine_groups()[section], 3, tag=tag)


def snapshot(settings, section):
    """(sha of the file, the group as memory holds it) before a save."""
    columns = settings.combine_groups()[section]
    return sha(settings.file), memory_group(settings, section, columns)


def assert_nothing_changed(settings, section, before):
    """Disk and memory still hold the pre-save group, even after a later save.

    The later, unrelated save is the point: a refused or failed group that only
    left the FILE alone but stayed in memory would be written out by it.
    """
    before_sha, before_memory = before
    columns = settings.combine_groups()[section]
    assert sha(settings.file) == before_sha, 'config.ini changed'
    assert memory_group(settings, section, columns) == before_memory, 'memory changed'

    settings.addSection('core')
    settings.set('core', 'zz_later_unrelated', '1')
    settings.save()
    assert stored_group(settings.file, section, columns) == before_memory, (
        'a later unrelated save wrote the refused group to disk')


def _reader_urls(settings, monkeypatch, section):
    """URLs a real automation reader fetches, with only the network call replaced."""
    from couchpotato.core.media.movie.providers.automation.imdb import IMDBWatchlist
    from couchpotato.core.media.movie.providers.automation.itunes import ITunes
    from couchpotato.core.media.movie.providers.automation.letterboxd import Letterboxd

    fetched = []
    if section == 'imdb':
        reader = IMDBWatchlist.__new__(IMDBWatchlist)
        reader.setName('IMDB:IMDBWatchlist')
        monkeypatch.setattr(reader, 'getFromURL', lambda url: fetched.append(url) or [])
    elif section == 'itunes':
        reader = ITunes.__new__(ITunes)
        monkeypatch.setattr(reader, 'getCache', lambda key, url, **kw: fetched.append(url) or '<feed/>')
    else:
        reader = Letterboxd.__new__(Letterboxd)
        monkeypatch.setattr(reader, 'getHTMLData', lambda url, **kw: fetched.append(url) or '')
    reader.getIMDBids()
    return fetched


def reader_view(settings, monkeypatch, section):
    """The rows the provider's real reader sees in `settings`.

    Newznab and torrentpotato go through their real ``getHosts``. The automation
    readers have no row object, so the view is the list of URLs the real reader
    asks for: a disabled row is skipped, which is exactly the enabler-to-URL
    pairing a misplaced cell would break.
    """
    from couchpotato.environment import Env
    monkeypatch.setattr(Env, '_settings', settings)

    if section == 'newznab':
        from couchpotato.core.media.movie.providers.nzb.newznab import Newznab
        return [(h['use'], h['host'], h['api_key'], h['extra_score'], h['custom_tag'])
                for h in Newznab.__new__(Newznab).getHosts()]
    if section == 'torrentpotato':
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        return [(h['use'], h['host'], h['pass_key'], h['name'], h['seed_ratio'],
                 h['seed_time'], h['extra_score'])
                for h in TorrentPotato.__new__(TorrentPotato).getHosts()]
    return _reader_urls(settings, monkeypatch, section)


def expected_view(section, rows):
    """What `reader_view` must return for rows that were saved as `rows`."""
    if section == 'newznab':
        return [(r['use'], r['host'], r['api_key'], int(r['extra_score']), r['custom_tag'])
                for r in rows]
    if section == 'torrentpotato':
        return [(r['use'], r['host'], r['pass_key'], r['name'], float(r['seed_ratio']),
                 int(r['seed_time']), int(r['extra_score'])) for r in rows]
    shape = {
        'imdb': '%s&start=0',
        'itunes': '%s',
        'letterboxd': 'https://letterboxd.com/%s/watchlist/page/1/',
    }[section]
    return [shape % r['automation_urls'] for r in rows if r['automation_urls_use'] == '1']


def held_by_another_thread(lock):
    """Is `lock` held by the calling thread, as another thread sees it?

    The probe thread RELEASES the lock itself if it manages to take it. A
    re-entrant lock can only be released by its owner, so a probe that took it
    and left would hold it for the rest of the process and block every later
    settings test (measured: a five hour hang).
    """
    outcome = []

    def probe():
        got = lock.acquire(blocking=False)
        try:
            outcome.append(not got)
        finally:
            if got:
                lock.release()

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join(5)
    assert outcome, 'the probe thread did not finish'
    return outcome[0]


class InstrumentedLock:
    """A re-entrant lock that can say which hold a call happened inside.

    It stands in for ``couchpotato.core.settings._PASSWORD_SAVE_LOCK``. Two
    things a barrier or a sleep cannot show deterministically:

    * ``on_outermost_release(thread_id)`` runs while the lock is STILL held, at
      the end of a thread's outermost hold. State read there is what the next
      thread to take the lock would see.
    * ``hold_of(thread_id)`` is the serial number of the outermost hold that
      thread is inside right now (None when it holds nothing), so a test can
      assert that several calls shared one continuous hold.
    """

    def __init__(self, on_outermost_release=None):
        self._lock = threading.RLock()
        self._guard = threading.Lock()
        self._depth = {}
        self._hold = {}
        self._serial = 0
        self._on_release = on_outermost_release
        self.waiting = 0

    def acquire(self, blocking=True, timeout=-1):
        with self._guard:
            self.waiting += 1
        got = self._lock.acquire(blocking, timeout)
        with self._guard:
            self.waiting -= 1
        if got:
            me = threading.get_ident()
            self._depth[me] = self._depth.get(me, 0) + 1
            if self._depth[me] == 1:
                self._serial += 1
                self._hold[me] = self._serial
        return got

    def release(self):
        me = threading.get_ident()
        self._depth[me] -= 1
        if self._depth[me] == 0:
            if self._on_release is not None:
                self._on_release(me)
            del self._hold[me]
        self._lock.release()

    def hold_of(self, thread_id):
        return self._hold.get(thread_id)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc_info):
        self.release()


class LogCapture(logging.Handler):
    """Every record from the real loggers, whatever its level.

    Not ``caplog``: the project renames the INFO level (``couchpotato/core/
    logger.py``), so ``caplog.at_level('INFO')`` captures nothing. This hangs a
    plain handler on the root logger and lowers its level for the duration.
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def at_or_above(self, levelno):
        return [r for r in self.records if r.levelno >= levelno]

    def text(self):
        return '\n'.join(r.getMessage() for r in self.records)

    def __enter__(self):
        root = logging.getLogger()
        self._root_level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(self)
        return self

    def __exit__(self, *exc_info):
        root = logging.getLogger()
        root.removeHandler(self)
        root.setLevel(self._root_level)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stored_group(path, section, columns):
    """Each column's raw stored string, read with a fresh parser."""
    parser = configparser.RawConfigParser()
    parser.read(str(path), encoding='utf-8')
    return {column: parser.get(section, column) for column in columns}


def memory_group(settings, section, columns):
    """Each column's raw value as the live parser holds it."""
    return {column: settings.p.get(section, column) for column in columns}


def placeholder_rows(columns, count, tag='a'):
    """``count`` rows with a distinct, obviously fake value in every cell."""
    rows = []
    for index in range(count):
        row = {}
        for column in columns:
            if column == 'use' or column == 'automation_urls_use':
                row[column] = str((index + 1) % 2)
            elif column in NUMERIC_COLUMNS:
                row[column] = str(index + 1)
            elif column in HOST_COLUMNS:
                row[column] = 'https://placeholder-%s-%d.invalid/path' % (tag, index)
            else:
                row[column] = 'placeholder-%s-%s-%d' % (tag, column, index)
        rows.append(row)
    return rows
