"""Read a worker's real `config.ini` back for the E2E suite (SEC-004 AC-QA-10).

    python -m tests.helpers.config_readback sha <config.ini>
    python -m tests.helpers.config_readback columns <config.ini> <section>
    python -m tests.helpers.config_readback view <config.ini> <section>
    python -m tests.helpers.config_readback enabled <config.ini> <section>

Run from the repository root and as a MODULE, never as `python tests/helpers/...`:
a script run by path puts its own directory first on `sys.path`, and that directory
holds an `http.py` that shadows the standard library's `http` package.

Each prints one JSON value. `sha` is the sha256 of the file's bytes. `columns` is
each column of a combine group as the raw stored string, which is what a test
asserts about "the file". `view` is what the provider's real reader sees
(`getHosts` for newznab and torrentpotato, the enabler-and-URL pairing for the
automation readers), from `combine_groups.reader_view`.

It never writes the file it is given. Loading a `Settings` registers every
default and saves, so `view` loads a COPY in a temporary directory: a read-back
that altered the file it was checking would make every "unchanged" assertion
meaningless.
"""
import configparser
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for entry in (REPO_ROOT, REPO_ROOT / 'libs'):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import pytest  # noqa: E402

from tests.helpers.combine_groups import SECTIONS, group_settings, reader_view  # noqa: E402


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stored(path):
    """Every section and option of the file, raw (no interpolation, no decoding)."""
    parser = configparser.RawConfigParser()
    with open(path, encoding='utf-8') as handle:
        parser.read_file(handle)
    return {section: dict(parser.items(section)) for section in parser.sections()}


def _require_group(section):
    if section not in SECTIONS:
        raise SystemExit('not a combine group: %r' % section)


def group_columns(path, section):
    """Each column of the group as the raw string stored in the file."""
    _require_group(section)
    stored = _stored(path)
    with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
        with group_settings(Path(directory), patch) as settings:
            columns = settings.combine_groups()[section]
    # A column the file does not hold is null, not an empty string: the two read
    # differently (a missing value takes its default, an empty one is one cell).
    return {column: stored.get(section, {}).get(column) for column in columns}


def group_view(path, section):
    """What the provider's real reader returns for the group stored in the file."""
    _require_group(section)
    stored = _stored(path)
    with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
        with group_settings(Path(directory), patch, stored=stored) as settings:
            return reader_view(settings, patch, section)


def _provider_for(section):
    if section == 'newznab':
        from couchpotato.core.media._base.providers.nzb.base import NZBProvider as base
        from couchpotato.core.media.movie.providers.nzb.newznab import Newznab as provider
    else:
        from couchpotato.core.media._base.providers.torrent.base import TorrentProvider as base
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato as provider
    return base, provider


def group_enabled(path, section):
    """Run the real `isEnabled` over every row the real `getHosts` returns.

    `{'reader_raises': bool, 'rows': [bool | 'raises', ...]}`. The provider is
    forced ENABLED for the call: `isEnabled` is `enabled and host and key and
    int(use)`, so with the provider off (torrentpotato ships off) it stops before
    `int(use)` and could never show the row that makes a search crash. Only
    newznab and torrentpotato have these readers.
    """
    if section not in ('newznab', 'torrentpotato'):
        raise SystemExit('no isEnabled reader for: %r' % section)
    stored = _stored(path)
    with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
        with group_settings(Path(directory), patch, stored=stored) as settings:
            from couchpotato.environment import Env
            patch.setattr(Env, '_settings', settings)
            base, provider_class = _provider_for(section)
            patch.setattr(base, 'isEnabled', lambda self, host=None: True)
            provider = provider_class.__new__(provider_class)
            try:
                hosts = provider.getHosts()
            except Exception:
                return {'reader_raises': True, 'rows': []}
            rows = []
            for host in hosts:
                try:
                    rows.append(bool(provider.isEnabled(host)))
                except Exception:
                    rows.append('raises')
            return {'reader_raises': False, 'rows': rows}


def main(argv):
    command, path, *rest = argv
    if command == 'sha':
        result = file_sha(path)
    elif command == 'columns':
        result = group_columns(path, rest[0])
    elif command == 'view':
        result = group_view(path, rest[0])
    elif command == 'enabled':
        result = group_enabled(path, rest[0])
    else:
        raise SystemExit('unknown command: %r' % command)
    json.dump(result, sys.stdout)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
