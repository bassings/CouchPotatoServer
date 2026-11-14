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
