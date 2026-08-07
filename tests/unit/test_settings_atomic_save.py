"""T2.0: `Settings.save()` must never leave `config.ini` truncated.

The shipped implementation is:

    def save(self):
        with open(self.file, 'w', encoding='utf-8') as configfile:
            self.p.write(configfile)

`open(..., 'w')` TRUNCATES before a single byte is written. If the process dies
or the volume fills between the truncate and the flush, `config.ini` is left
empty or partial -- and that file holds the api_key, the UI password, and every
downloader and notifier credential. `docs/development-process.md` also names it
as the lock-out recovery file, so the failure destroys the remedy along with
the configuration.

`Env.setting(attr, value=...)` calls this unconditionally
(`environment.py:71`), and PR 2 is what makes it fire in bulk: forcing a
first-ever login triggers the legacy-md5-to-bcrypt rehash, which rewrites the
whole file per user.

Test 2 is the load-bearing one. It injects the failure at the point the OLD
code would already have truncated, so it cannot pass by accident on an
implementation that truncates first -- which is the difference between this
suite and one that merely round-trips.
"""
import configparser
import os
import stat
from pathlib import Path

import pytest

from couchpotato.core.settings import Settings


def _settings(path: Path) -> Settings:
    """A Settings bound to `path`, with one section written through it."""
    s = Settings()
    s.setFile(str(path))
    s.addSection('core')
    s.p.set('core', 'api_key', 'IRREPLACEABLE-KEY')
    s.p.set('core', 'password', 'hunter2-hash')
    return s


def _read(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(str(path), encoding='utf-8')
    return parser


class TestSaveRoundTrip:

    def test_values_survive_a_save_and_reload(self, tmp_path):
        target = tmp_path / 'config.ini'
        settings = _settings(target)

        settings.save()

        assert _read(target)['core']['api_key'] == 'IRREPLACEABLE-KEY'

    def test_a_second_save_replaces_rather_than_appends(self, tmp_path):
        target = tmp_path / 'config.ini'
        settings = _settings(target)
        settings.save()
        settings.p.set('core', 'api_key', 'ROTATED-KEY')

        settings.save()

        parser = _read(target)
        assert parser['core']['api_key'] == 'ROTATED-KEY'
        assert len(parser.sections()) == 1, 'the file grew instead of being replaced'


class TestSaveIsAtomic:
    """The whole point: a failed write must not destroy the existing file."""

    def test_a_failure_mid_write_leaves_the_original_intact(self, tmp_path, monkeypatch):
        """The load-bearing test.

        Injects at `ConfigParser.write`, which is called AFTER the old code has
        already truncated the target -- so an implementation that opens the
        real file with 'w' cannot pass this, and one that writes a temp file
        first cannot fail it. A disk-full or a killed process at that instant
        is the real-world shape.
        """
        target = tmp_path / 'config.ini'
        settings = _settings(target)
        settings.save()
        original = target.read_bytes()
        assert b'IRREPLACEABLE-KEY' in original, 'fixture did not write anything to protect'

        def boom(self, fp, space_around_delimiters=True):
            fp.write('[core]\napi_key = PARTIAL')   # a partial write, then death
            raise OSError(28, 'No space left on device')

        monkeypatch.setattr(configparser.RawConfigParser, 'write', boom)

        with pytest.raises(OSError):
            settings.save()

        assert target.read_bytes() == original, (
            'config.ini was modified by a save that FAILED. It holds the '
            'api_key, the UI password and every downloader credential, and it '
            'is the documented lock-out recovery file.'
        )

    def test_a_failure_leaves_no_temp_file_behind(self, tmp_path, monkeypatch):
        """`config.ini.*` is exactly what a locked-out operator reaches for."""
        target = tmp_path / 'config.ini'
        settings = _settings(target)
        settings.save()

        def boom(self, fp, space_around_delimiters=True):
            raise OSError(28, 'No space left on device')

        monkeypatch.setattr(configparser.RawConfigParser, 'write', boom)
        with pytest.raises(OSError):
            settings.save()

        strays = [p.name for p in tmp_path.iterdir() if p.name != 'config.ini']
        assert strays == [], 'a failed save left %s behind' % strays

    def test_the_file_never_disappears_during_a_save(self, tmp_path, monkeypatch):
        """There must be no window in which the path does not exist.

        A concurrent reader -- or a container healthcheck, or a restart --
        landing in a truncate-then-write window sees an empty or absent file.
        Checked from inside `ConfigParser.write`, i.e. mid-save.
        """
        target = tmp_path / 'config.ini'
        settings = _settings(target)
        settings.save()

        seen = {}
        real_write = configparser.RawConfigParser.write

        def observe(self, fp, space_around_delimiters=True):
            seen['exists'] = target.exists()
            seen['content'] = target.read_bytes() if target.exists() else b''
            return real_write(self, fp, space_around_delimiters)

        monkeypatch.setattr(configparser.RawConfigParser, 'write', observe)
        settings.save()

        assert seen['exists'], 'config.ini did not exist while a save was in flight'
        assert b'IRREPLACEABLE-KEY' in seen['content'], (
            'config.ini was already truncated while the save was in flight: a '
            'reader in that window sees an empty file'
        )


class TestSavePreservesFileProperties:

    def test_an_existing_mode_is_preserved(self, tmp_path):
        """A save must not silently change permissions in either direction."""
        target = tmp_path / 'config.ini'
        settings = _settings(target)
        settings.save()
        os.chmod(target, 0o640)

        settings.p.set('core', 'api_key', 'ROTATED')
        settings.save()

        assert stat.S_IMODE(os.stat(target).st_mode) == 0o640

    def test_a_new_file_is_not_world_readable(self, tmp_path):
        """It holds the api_key and every downloader credential."""
        target = tmp_path / 'config.ini'
        _settings(target).save()

        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert not mode & stat.S_IROTH, 'config.ini is world-readable (mode %o)' % mode

    def test_a_symlinked_config_stays_a_symlink(self, tmp_path):
        """`--config_file` is user-supplied and only `expanduser`'d, never
        resolved, so an operator can legitimately point it at a symlink.
        `os.replace` onto a symlink replaces the LINK, orphaning the real file.
        """
        real = tmp_path / 'real-config.ini'
        link = tmp_path / 'config.ini'
        settings = _settings(real)
        settings.save()
        link.symlink_to(real)

        linked = _settings(link)
        linked.p.set('core', 'api_key', 'THROUGH-THE-LINK')
        linked.save()

        assert link.is_symlink(), 'the symlink was replaced by a regular file'
        assert _read(real)['core']['api_key'] == 'THROUGH-THE-LINK', (
            'the write did not reach the symlink target'
        )


class TestSaveDoesNotSilentlyChangeFileIdentity:
    """`os.replace` creates a NEW inode; truncate-then-write reused the old one.

    That difference is the price of atomicity, and it is not free. The previous
    implementation preserved owner, group, ACLs and any hardlinks simply by
    never replacing the inode. This one has to copy those forward deliberately,
    or a config.ini with a managed owner or group -- say, group-readable by a
    backup account -- silently becomes owned by the server process on the next
    save, locking that tooling out or handing the server's primary group access
    to stored credentials.
    """

    def test_group_ownership_is_carried_across(self, tmp_path):
        """Set a NON-primary group first, or this test cannot fail.

        `mkstemp` creates the temp file with the process's PRIMARY gid. If the
        fixture leaves config.ini on that same gid, the assertion passes
        whether the code preserves anything or not -- the incidentally-passing
        shape. So the file is first chgrp'd to another group this user belongs
        to, which is exactly what a managed deployment does (group-readable by
        a backup account) and exactly what `os.replace` would silently discard.
        """
        import os as _os

        alternates = [g for g in _os.getgroups() if g != _os.getgid()]
        if not alternates:
            pytest.skip('this user belongs to no group other than its primary; '
                        'the assertion could not fail here')
        alt_gid = alternates[0]

        target = tmp_path / 'config.ini'
        settings = _settings(target)
        settings.save()
        _os.chown(target, -1, alt_gid)
        assert _os.stat(target).st_gid == alt_gid, 'fixture did not take effect'

        settings.p.set('core', 'api_key', 'ROTATED')
        settings.save()

        assert _os.stat(target).st_gid == alt_gid, (
            'the save reset the file group to the process default, discarding '
            'a deliberate ownership arrangement'
        )


class TestSaveTightensAWorldReadableConfig:
    """Preserving the mode means an ALREADY-DEPLOYED 0644 config stays 0644.

    Every config.ini written before this change was created world-readable by
    `open(file, 'w')` under a default umask -- holding the api_key, the
    password hash, and every downloader and notifier credential. Carrying the
    mode forward unchanged means those files stay world-readable forever,
    through every subsequent save, so the fix would harden new installs and do
    nothing for the ones that already have the problem.

    Only the WORLD bits are cleared. Group access is left exactly as the
    operator has it, because backup tooling reading via a shared group is a
    legitimate arrangement and silently breaking it would be a worse outcome
    than the exposure.
    """

    def test_world_readable_bits_are_removed_on_save(self, tmp_path):
        import os as _os
        import stat as _stat

        target = tmp_path / 'config.ini'
        settings = _settings(target)
        settings.save()
        _os.chmod(target, 0o644)          # what every pre-existing install has

        settings.p.set('core', 'api_key', 'ROTATED')
        settings.save()

        mode = _stat.S_IMODE(_os.stat(target).st_mode)
        assert not mode & 0o007, (
            'config.ini is still world-accessible (mode %o) after a save; it '
            'holds the api_key and every downloader credential' % mode
        )

    def test_group_access_is_left_alone(self, tmp_path):
        """0640 is a deliberate arrangement -- do not tighten it to 0600."""
        import os as _os
        import stat as _stat

        target = tmp_path / 'config.ini'
        settings = _settings(target)
        settings.save()
        _os.chmod(target, 0o640)

        settings.p.set('core', 'api_key', 'ROTATED')
        settings.save()

        assert _stat.S_IMODE(_os.stat(target).st_mode) == 0o640
