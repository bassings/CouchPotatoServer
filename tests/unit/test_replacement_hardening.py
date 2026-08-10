"""Everything the B4b review found missing on the destructive path.

Seventeen findings, eight of them P1, on the one function in this project
that destroys an irreplaceable file. They were not seventeen bugs. Most of
them came from one wrong choice: `replace_atomically` staged the incoming
file with `moveFile(use_default=True)`, which honours the operator's
`default_file_action`. That mover creates links, consumes sources and logs
full paths, none of which a temporary staging file should ever involve.

So the frame changed -- staging is a plain copy, and `default_file_action` is
applied to the SOURCE after the swap, which is the only place it ever meant
anything -- and the rest are refusals that had no test to demand them.

Every test here is about what SURVIVES. A refusal that logs the right word
while deleting the file is not a refusal.
"""
import os
import shutil

import pytest

from couchpotato.core.plugins.renamer.swap import (
    FAILED_DESTINATION_CHANGED,
    REFUSED_SOURCE_CHANGED,
    REFUSED_SOURCE_IS_SYMLINK,
    REPLACED,
    identity_of,
    replace_atomically,
)

OLD = b'the library copy' * 200
NEW = b'the better copy' * 900


@pytest.fixture
def files(tmp_path):
    lib = tmp_path / 'library'
    lib.mkdir()
    dst = lib / 'movie.mkv'
    dst.write_bytes(OLD)

    dl = tmp_path / 'downloads'
    dl.mkdir()
    src = dl / 'incoming.mkv'
    src.write_bytes(NEW)
    return {'root': tmp_path, 'lib': lib, 'dl': dl,
            'src': str(src), 'dst': str(dst)}


def _stray_parts(directory):
    return [n for n in os.listdir(directory) if n.startswith('.cp-upgrade-')]


class TestASymlinkSourceIsRefused:
    """`move` renames the LINK into staging, every size check follows its
    target and passes, and `os.replace` installs a link over the complete
    library file. Cleanup then deletes the tree the link points into, so the
    library holds a broken link and the only good copy is already gone.

    Refused before any size is taken, because a size taken through a link
    describes a file other than the one being installed.
    """

    def test_the_library_file_survives_a_symlinked_source(self, files):
        real = os.path.join(str(files['dl']), 'real.mkv')
        with open(real, 'wb') as handle:
            handle.write(NEW)
        link = os.path.join(str(files['dl']), 'link.mkv')
        os.symlink(real, link)

        ok, reason = replace_atomically(link, files['dst'])

        assert (ok, reason) == (False, REFUSED_SOURCE_IS_SYMLINK)
        with open(files['dst'], 'rb') as handle:
            assert handle.read() == OLD
        assert not _stray_parts(str(files['lib']))

    def test_a_real_file_of_the_same_size_is_NOT_refused(self, files):
        """The control. Without it this guard would be indistinguishable from
        one that refuses everything."""
        ok, reason = replace_atomically(files['src'], files['dst'])
        assert (ok, reason) == (True, REPLACED)


class TestASourceThatChangedSinceTheScanIsRefused:
    """A downloader still appending between the scan and the rename produces
    a file whose quality rung was derived from an earlier, smaller version of
    itself. Replacing a complete library copy on the strength of a rung the
    bytes have not earned is irreversible.

    The measurement compared against must be the SCANNER's. Taking a fresh
    size here and comparing it with another fresh size is a comparison of a
    value with itself, which passes forever.
    """

    def test_a_source_that_grew_since_the_scan_is_refused(self, files):
        scanned = os.path.getsize(files['src'])
        with open(files['src'], 'ab') as handle:
            handle.write(b'still downloading')

        ok, reason = replace_atomically(
            files['src'], files['dst'], expected_source_size=scanned,
        )

        assert (ok, reason) == (False, REFUSED_SOURCE_CHANGED)
        with open(files['dst'], 'rb') as handle:
            assert handle.read() == OLD

    def test_an_unchanged_source_still_replaces(self, files):
        ok, reason = replace_atomically(
            files['src'], files['dst'],
            expected_source_size=os.path.getsize(files['src']),
        )
        assert (ok, reason) == (True, REPLACED)

    def test_no_recorded_size_skips_the_check_rather_than_inventing_one(self, files):
        ok, _ = replace_atomically(files['src'], files['dst'],
                                   expected_source_size=None)
        assert ok


class TestTheDestinationIsRevalidatedAtTheLastMoment:
    """The renamer lock is process-local. A second CouchPotato process against
    the same library can install a BETTER copy while this one is staging, and
    the decision authorising this swap was made about the file that used to be
    there. Without this check the approved-but-now-worse source overwrites it.
    """

    def test_a_destination_replaced_mid_stage_is_not_overwritten(self, files):
        identity = identity_of(files['dst'])
        better = b'a 2160p remux somebody else just installed' * 50

        def _stage_then_someone_else_wins(source, staging):
            shutil.copyfile(source, staging)
            with open(files['dst'], 'wb') as handle:
                handle.write(better)

        ok, reason = replace_atomically(
            files['src'], files['dst'],
            stage=_stage_then_someone_else_wins,
            destination_identity=identity,
        )

        assert (ok, reason) == (False, FAILED_DESTINATION_CHANGED)
        with open(files['dst'], 'rb') as handle:
            assert handle.read() == better, (
                "the other process's better copy was destroyed"
            )
        assert not _stray_parts(str(files['lib']))

    def test_an_untouched_destination_still_replaces(self, files):
        ok, reason = replace_atomically(
            files['src'], files['dst'],
            destination_identity=identity_of(files['dst']),
        )
        assert (ok, reason) == (True, REPLACED)

    def test_an_unreadable_destination_does_not_compare_equal(self, tmp_path):
        assert identity_of(str(tmp_path / 'nothing here')) is None


class TestTheForensicRecordHappensBeforeTheIrreversibleStep:
    def test_the_callback_runs_before_the_replace_not_after(self, files):
        seen = {}

        def _record():
            # If this ran after os.replace, the destination would already hold
            # the new bytes and this read would prove nothing.
            with open(files['dst'], 'rb') as handle:
                seen['destination_at_record_time'] = handle.read()

        ok, _ = replace_atomically(files['src'], files['dst'],
                                   about_to_replace=_record)

        assert ok
        assert seen['destination_at_record_time'] == OLD, (
            'the record was written after the file was already gone, so a '
            'crash between them leaves the deletion unexplained'
        )

    def test_a_record_that_raises_does_not_abort_the_swap(self, files):
        ok, _ = replace_atomically(
            files['src'], files['dst'],
            about_to_replace=lambda: (_ for _ in ()).throw(RuntimeError('log full')),
        )
        assert ok, 'a failed log entry blocked a replacement'


class TestStagingNeverTouchesTheSourceOrLeavesLinks:
    def test_the_source_still_exists_after_a_successful_swap(self, files):
        """The staging copy deliberately does NOT consume the source, so a
        failure between staging and swap can never leave the staged file as
        the only complete copy. Disposal is the renamer's job, afterwards."""
        assert replace_atomically(files['src'], files['dst'])[0]
        assert os.path.exists(files['src'])
        with open(files['src'], 'rb') as handle:
            assert handle.read() == NEW

    def test_the_source_is_not_a_link_to_anything_afterwards(self, files):
        assert replace_atomically(files['src'], files['dst'])[0]
        assert not os.path.islink(files['src']), (
            'staging left the download pointing at a path os.replace has '
            'already renamed away'
        )

    def test_no_staging_file_survives_a_success(self, files):
        assert replace_atomically(files['src'], files['dst'])[0]
        assert not _stray_parts(str(files['lib']))


class TestTheSwapFailureNamesTheOsCondition:
    def test_errno_and_strerror_reach_the_log(self, files, caplog, monkeypatch):
        """A read-only mount, a permissions problem and a disconnected NAS are
        three different remedies that all arrive as `failed_swap`. Without the
        OS detail the operator's only diagnostic channel cannot tell them
        apart."""
        import logging

        import couchpotato.core.plugins.renamer.swap as swap_module

        def _refuse(a, b):
            raise OSError(30, 'Read-only file system')

        monkeypatch.setattr(swap_module.os, 'replace', _refuse)

        with caplog.at_level(logging.ERROR):
            ok, reason = replace_atomically(files['src'], files['dst'])

        assert not ok
        messages = ' '.join(r.getMessage() for r in caplog.records)
        assert 'Read-only file system' in messages
        assert '30' in messages
        assert files['dst'] not in messages, 'the failure log leaked the path'


class TestAnUnestablishedBaselineRefusesRatherThanSkipping:
    """`destination_identity=None` used to mean "no check", so a caller that
    TRIED and failed to stat the destination silently disabled the one guard
    against another process replacing it mid-stage.

    That is fail-open on the path that destroys a file, in the exact place
    this module's design says to fail closed. It needed two stacked races to
    reach, which is why it survived: rare enough never to be seen, and
    reachable enough to matter once.

    A sentinel separates "did not ask" from "asked and could not answer".
    """

    def test_a_None_baseline_refuses_before_anything_is_staged(self, files):
        from couchpotato.core.plugins.renamer.swap import REFUSED_IDENTITY_UNVERIFIABLE

        ok, reason = replace_atomically(
            files['src'], files['dst'], destination_identity=None,
        )

        assert (ok, reason) == (False, REFUSED_IDENTITY_UNVERIFIABLE)
        with open(files['dst'], 'rb') as handle:
            assert handle.read() == OLD
        assert not _stray_parts(str(files['lib'])), (
            'it staged before refusing, which is work done for a swap that '
            'was never going to happen'
        )

    def test_omitting_the_argument_still_means_no_check(self, files):
        """The other half. Collapsing both into a refusal would break every
        caller that legitimately does not ask, including the swap tests."""
        ok, reason = replace_atomically(files['src'], files['dst'])
        assert (ok, reason) == (True, REPLACED)

    def test_a_real_baseline_still_revalidates(self, files):
        """And the sentinel must not have disabled the check it was added to
        protect."""
        from couchpotato.core.plugins.renamer.swap import FAILED_DESTINATION_CHANGED

        identity = identity_of(files['dst'])

        def _stage_then_someone_else_wins(source, staging):
            shutil.copyfile(source, staging)
            with open(files['dst'], 'wb') as handle:
                handle.write(b'a better copy')

        ok, reason = replace_atomically(
            files['src'], files['dst'],
            stage=_stage_then_someone_else_wins,
            destination_identity=identity,
        )
        assert (ok, reason) == (False, FAILED_DESTINATION_CHANGED)


class TestASymlinkSwappedInMidFlightCannotBeFollowed:
    """The `islink` refusal is a CHECK, and `shutil.copyfile` follows links --
    so between them sat a window where the source could become a symlink and
    be followed, on the one path that destroys an irreplaceable file.

    Staging now opens with `O_NOFOLLOW`, which closes the window rather than
    narrowing it: the kernel refuses atomically and everything after reads
    from that descriptor instead of re-resolving the name.
    """

    def test_a_source_that_becomes_a_symlink_after_the_check_is_not_followed(self, files, monkeypatch):
        import couchpotato.core.plugins.renamer.swap as swap_module

        elsewhere = os.path.join(str(files['dl']), 'somewhere-else.mkv')
        with open(elsewhere, 'wb') as handle:
            handle.write(b'not the download at all' * 100)

        real_islink = os.path.islink
        swapped = {}

        def _islink_then_swap(path):
            answer = real_islink(path)
            # Answer honestly for the check, then swap the file underneath --
            # exactly the race the O_NOFOLLOW open exists to lose safely.
            if str(path) == files['src'] and not swapped:
                swapped['yes'] = True
                os.remove(files['src'])
                os.symlink(elsewhere, files['src'])
            return answer

        monkeypatch.setattr(swap_module.os.path, 'islink', _islink_then_swap)

        ok, reason = replace_atomically(files['src'], files['dst'])

        assert swapped, 'the race was never triggered; this test proves nothing'
        assert not ok, 'a symlink swapped in mid-flight was followed and staged'
        with open(files['dst'], 'rb') as handle:
            assert handle.read() == OLD, 'the library file was replaced'
        assert not _stray_parts(str(files['lib']))

    def test_an_ordinary_file_still_stages(self, files):
        """The control: O_NOFOLLOW must not refuse a plain file."""
        ok, reason = replace_atomically(files['src'], files['dst'])
        assert (ok, reason) == (True, REPLACED)


class TestTheRevalidationIsGenuinelyTheLastThing:
    """`about_to_replace()` does I/O -- it writes a log line -- and it used to
    run BETWEEN the identity check and `os.replace`. So the callback sat
    inside the very window the check exists to close, and a concurrent writer
    landing during the log was not caught.

    Order is now announce, revalidate, replace. Announcing first means the
    record can describe a replacement that does not then happen, so the
    refusal says so explicitly: an unmatched "about to" is a worse record than
    an extra line.
    """

    def test_a_writer_that_lands_during_the_announcement_is_caught(self, files):
        from couchpotato.core.plugins.renamer.swap import FAILED_DESTINATION_CHANGED

        identity = identity_of(files['dst'])
        better = b'a 2160p remux another process just installed' * 40

        def _announce_then_someone_else_wins():
            # Exactly the window: this runs where the log line runs.
            with open(files['dst'], 'wb') as handle:
                handle.write(better)

        ok, reason = replace_atomically(
            files['src'], files['dst'],
            destination_identity=identity,
            about_to_replace=_announce_then_someone_else_wins,
        )

        assert (ok, reason) == (False, FAILED_DESTINATION_CHANGED), (
            'a writer landing during the announcement was not caught, so the '
            'check no longer covers the last moment'
        )
        with open(files['dst'], 'rb') as handle:
            assert handle.read() == better, (
                "the other process's better copy was destroyed"
            )
        assert not _stray_parts(str(files['lib']))

    def test_the_announcement_still_runs_before_the_swap(self, files):
        """It must still describe the destination as it was, not after."""
        seen = {}

        def _record():
            with open(files['dst'], 'rb') as handle:
                seen['at_record_time'] = handle.read()

        ok, _ = replace_atomically(
            files['src'], files['dst'],
            destination_identity=identity_of(files['dst']),
            about_to_replace=_record,
        )

        assert ok
        assert seen['at_record_time'] == OLD

    def test_an_aborted_replacement_says_so(self, files, caplog):
        """The cost of announcing first: the record would otherwise claim a
        replacement that never happened."""
        import logging

        def _steal():
            with open(files['dst'], 'wb') as handle:
                handle.write(b'someone else')

        with caplog.at_level(logging.WARNING):
            replace_atomically(
                files['src'], files['dst'],
                destination_identity=identity_of(files['dst']),
                about_to_replace=_steal,
            )

        assert any('did NOT happen' in r.getMessage() for r in caplog.records), (
            'the log announced a replacement and never retracted it'
        )
