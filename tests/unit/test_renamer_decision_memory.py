"""FEAT-012: the renamer remembers it has already looked at a file.

Step one of the TDD build. Pins the core defect from the spec's Problem
section, measured on production: a refusal that is CORRECT (the collision
really cannot be resolved automatically) gets re-decided from scratch on
every scheduled scan forever, because the code has no memory of "I already
looked at this and nothing has changed" -- only of the refusal itself, which
it re-derives every time.

Binding decision 1 (specs/FEAT-012-renamer-remembers-its-decisions.md): the
skip lives entirely in `Renamer.scan` and is evaluated BEFORE
`fireEvent('scanner.scan', ...)`. That is why this test drives the real
`Renamer.scan()` entry point rather than the lower-level
`_moveRenamedFiles` that the existing replacement tests use -- the cost this
spec removes is the folder walk and identity resolution inside
`scanner.scan` itself, not just the log line that follows it.

The scenario is the spec's own production incident: a single-file group whose
identity was never asserted (no `identity_source`), colliding with an
existing library file. That refusal is `declined_unverified_identity` and it
is correct and must keep firing -- once. Nothing here is a REPLACE scenario,
so this test needs no `upgrade_replace` wiring at all.

Currently RED: nothing remembers anything yet, so `scan()` calls
`fireEvent('scanner.scan', ...)` unconditionally on every invocation. Five
identical scans of one unchanged group currently ask the scanner five times.
"""
import logging

import pytest

from couchpotato.core.plugins.renamer.main import Renamer


@pytest.fixture(autouse=True)
def _dead_setting_flag_does_not_leak():
    """`_warned_dead_setting` is a class attribute other test modules also
    set. Restore it around this file so a leaked value in either direction
    cannot make a test in this file, or a test after it, pass for the wrong
    reason."""
    original = Renamer._warned_dead_setting
    Renamer._warned_dead_setting = True
    yield
    Renamer._warned_dead_setting = original


@pytest.fixture
def world(tmp_path, monkeypatch):
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    group_folder = downloads / 'Minions.and.Monsters.2015.1080p.BluRay.x264-GRP'
    group_folder.mkdir()
    src = group_folder / 'movie.mkv'
    src.write_bytes(b'incoming download bytes' * 100)

    library = tmp_path / 'library'
    library.mkdir()
    dst = library / 'Minions and Monsters.mkv'
    # The pre-existing library copy: this collision is what makes the group
    # "declined" rather than a plain successful move, exactly as in the
    # production incident.
    dst.write_bytes(b'existing library bytes' * 50)
    original_dst_bytes = dst.read_bytes()
    original_src_bytes = src.read_bytes()

    conf_values = {
        'to': str(library),
        # An empty folder template plus a literal file name makes the
        # destination path exactly predictable without duplicating
        # doReplace's own token-substitution logic in the fixture.
        'folder_name': '',
        'file_name': dst.name,
        'default_file_action': 'move',
        'cleanup': False,
    }

    def _group():
        return {
            'media': {
                '_id': 'media-1',
                'info': {'titles': ['Minions and Monsters'], 'year': 2015},
            },
            'meta_data': {'quality': {'identifier': '1080p', 'is_3d': False}},
            'files': {'movie': [str(src)]},
            'parentdir': str(group_folder),
            'dirname': group_folder.name,
            # Deliberately absent: no `identity_source` is exactly what
            # makes the outcome `declined_unverified_identity`, the refusal
            # the spec's production incident names by name.
        }

    scan_calls = {'scanner.scan': 0}

    def _fire(event, *args, **kwargs):
        if event == 'scanner.scan':
            scan_calls['scanner.scan'] += 1
            return {'group-1': _group()}
        return None

    monkeypatch.setattr(
        'couchpotato.core.plugins.renamer.main.fireEvent', _fire,
    )

    plugin = Renamer.__new__(Renamer)
    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: conf_values.get(key, default),
        raising=False,
    )
    monkeypatch.setattr(
        type(plugin), 'shuttingDown', lambda _self: False, raising=False,
    )

    return {
        'plugin': plugin,
        'downloads': str(downloads),
        'src': str(src),
        'dst': str(dst),
        'original_dst_bytes': original_dst_bytes,
        'original_src_bytes': original_src_bytes,
        'scan_calls': scan_calls,
    }


class TestAnUnchangedDeclinedGroupIsNotRescanned:
    """AC-QA-3 / AC-QA-4 / binding decision 1.

    The refusal must be computed once, not merely logged once: what has to
    stop is the expensive scanner walk itself, not just a repeated WARNING
    line printed from a decision that is still being remade every time.
    """

    def test_scanner_scan_is_asked_for_at_most_once_across_five_scans(
        self, world, caplog,
    ):
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                world['plugin'].scan(base_folder=world['downloads'])

        # Positive control (the spec's own instruction for every silence
        # criterion): the refusal must actually have fired at least once, or
        # "the scanner was only asked once" could pass because the decision
        # path was never reached at all -- proving nothing about a memory.
        refusals = [
            r for r in caplog.records
            if 'Destination already exists' in r.getMessage()
            and 'media-1' in r.getMessage()
        ]
        assert refusals, (
            'the refusal was never logged at all, so this run proves '
            'nothing about remembering it -- the decision path itself was '
            'never reached'
        )

        assert world['scan_calls']['scanner.scan'] == 1, (
            'fireEvent("scanner.scan", ...) was called %d times for 5 '
            'identical scans of one unchanged, already-declined group. '
            'This is the folder rescan and identity resolution the '
            'production incident paid for roughly 1,100 times over 36 '
            'hours; an unchanged, already-decided group must not trigger '
            'it again.' % world['scan_calls']['scanner.scan']
        )

        # "Already decided" must never become "already done" (AC-QA-12):
        # both the library file and the download must survive, byte for
        # byte, no matter how many times an unchanged scan runs.
        assert world['dst'] and open(world['dst'], 'rb').read() == world['original_dst_bytes'], (
            'the collided library file was modified by a scan that should '
            'only ever have refused'
        )
        assert open(world['src'], 'rb').read() == world['original_src_bytes'], (
            'the download was modified by a scan that should only ever '
            'have refused'
        )
