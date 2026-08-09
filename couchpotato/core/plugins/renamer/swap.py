"""Put a better copy in place of the one already in the library, atomically.

FEAT-009B B3b. This is the only function in the project that destroys an
irreplaceable file, so it is written to make the destructive step the LAST
thing that can happen and the only thing that is not reversible.

The shape, and why each step is where it is:

  1. refuse anything doubtful BEFORE touching the filesystem;
  2. stage the incoming copy into the DESTINATION DIRECTORY under a unique
     temporary name -- not the source directory. `os.replace` is atomic only
     within a filesystem, and on this project's target deployment the library
     and the download folder are routinely different mounts;
  3. verify the staged bytes are the size we expected;
  4. `os.replace(staging, destination)` -- one atomic operation. The old file
     ceases to exist at the same instant the new one appears. There is no
     window in which the library has neither.

`os.remove` followed by a move is never acceptable here: it opens exactly that
window, and a crash inside it loses the movie.

The cleanup rule is the subtle one. On failure the staged file is removed
**only when a complete copy still exists elsewhere**. `moveFile` may have
consumed the source (a real move) or left it (copy/link), so after a failure
the staged file is sometimes the ONLY complete copy in existence -- and
deleting it to tidy up would destroy the download the operator just made. When
that happens the function leaves it and says so.

Callers get `(ok, reason)`. Every reason is a value, not a log string, so the
decision can be asserted rather than parsed.
"""

import os
import shutil
import uuid

from couchpotato.core.logger import CPLog

log = CPLog(__name__)

# Refusals taken before anything is touched.
REFUSED_NO_SOURCE = 'refused_no_source'
REFUSED_DESTINATION_MISSING = 'refused_destination_missing'
REFUSED_DESTINATION_IS_SYMLINK = 'refused_destination_is_symlink'
REFUSED_SAME_FILE = 'refused_same_file'
# Distinct from the above: we could not determine whether they are the same
# file. Both refuse, but 'they are the same inode' and 'a stat failed' send
# an operator to different places, and guessing the reassuring one is the
# habit this module exists to avoid.
REFUSED_IDENTITY_UNVERIFIABLE = 'refused_identity_unverifiable'
# The scanner measured the source, and by the time we act it is a different
# size. A downloader still appending is the ordinary cause, and the quality
# metadata was derived from the earlier measurement, so an in-progress
# snapshot would replace a complete library copy on the strength of a rung it
# has not earned.
REFUSED_SOURCE_CHANGED = 'refused_source_changed'
# The source is itself a symlink. `move` would rename the LINK into staging,
# every size check would follow its target and pass, and `os.replace` would
# install a link over the complete library file -- then cleanup deletes the
# tree the link points into. A broken library entry, after the only good copy
# has already gone.
REFUSED_SOURCE_IS_SYMLINK = 'refused_source_is_symlink'

# Failures after work began. The library file is intact in every one of them.
FAILED_STAGING = 'failed_staging'
FAILED_SIZE_MISMATCH = 'failed_size_mismatch'
FAILED_SWAP = 'failed_swap'
# The destination is no longer the file the decision was made about. The
# renamer lock is process-local, so a second CouchPotato process sharing the
# library can install a BETTER copy while this one is staging; without this
# check the approved-but-now-worse source would overwrite it.
FAILED_DESTINATION_CHANGED = 'failed_destination_changed'

REPLACED = 'replaced'

#: Distinguishes "the caller did not ask for revalidation" from "the caller
#: asked, and could not establish a baseline". Those are opposite situations
#: and `None` conflated them: an unreadable destination at decision time
#: produced `destination_identity=None`, which silently SKIPPED the check --
#: fail-open, on the one path that destroys a file, in the exact place this
#: module's design says to fail closed.
_IDENTITY_NOT_REQUESTED = object()


def replace_atomically(source, destination, stage=None,
                       remove=os.remove, expected_source_size=None,
                       destination_identity=_IDENTITY_NOT_REQUESTED,
                       about_to_replace=None):
    """Replace `destination` with `source`. Returns `(ok, reason)`.

    `stage(src, staging)` puts the source bytes at the staging path. It
    defaults to a plain `copyfile`, and the renamer no longer overrides it.
    The default is resolved HERE rather than in the signature, so that
    `shutil.copyfile` is looked up at call time: bound as a default argument
    it would be captured at import and no test could reach the real staging
    path to break it.

    That default is a correction, and the reason is worth keeping. The renamer
    used to pass `moveFile(use_default=True)`, which honours the operator's
    `default_file_action`. Three of those modes are wrong here:

    - `symlink_reversed` and the cross-device fallback of `link` point the
      SOURCE at the staging path, and `os.replace` then renames that path
      away -- leaving a dangling link in the download folder;
    - `move` consumes the source before the irreversible step, so a failure
      between staging and swap leaves the staged file as the only complete
      copy in existence;
    - all of them log both full paths at INFO, which is what PrivacyFilter
      exists to keep out of the ring buffer.

    `default_file_action` describes how a download reaches the library. It was
    never a statement about how a temporary file is staged, and honouring it
    here bought nothing and cost all three. Copying is one extra pass over the
    bytes and leaves the source INTACT until after the swap, which on the one
    operation in this project that destroys an irreplaceable file is the trade
    to want. What happens to the source afterwards is the renamer's business,
    and it is where `default_file_action` genuinely applies.

    `expected_source_size` is the size the SCANNER measured. Passing it makes
    a source that has changed since a refusal instead of a replacement.

    `destination_identity` is `(st_dev, st_ino, st_size, st_mtime_ns)` taken
    when the decision was made, re-checked immediately before the swap.
    Passing it as None means the caller TRIED and could not stat the
    destination, which is a refusal -- not the same as omitting it.

    `about_to_replace()` is called in the last moment before the irreversible
    step, for the caller's forensic record.

    `remove` is injected only so tests can force a cleanup failure.

    The library file at `destination` survives every path through this
    function except the successful one.
    """
    if stage is None:
        stage = shutil.copyfile

    # --- refuse before touching anything -------------------------------
    if not os.path.exists(source):
        return False, REFUSED_NO_SOURCE

    # Before any size check, because every size check FOLLOWS the link and
    # would therefore pass while describing a different file.
    if os.path.islink(source):
        return False, REFUSED_SOURCE_IS_SYMLINK

    # `lexists`, not `exists`: a BROKEN symlink must be refused too. `exists`
    # follows the link and reports False, which would send us down the
    # "nothing there to replace" path and quietly write through a link whose
    # target is outside the library.
    if os.path.islink(destination):
        return False, REFUSED_DESTINATION_IS_SYMLINK

    if not os.path.exists(destination):
        # This function replaces; it does not install. A caller that reaches
        # here with no destination has mistaken the situation, and guessing
        # would turn a bug into a file operation.
        return False, REFUSED_DESTINATION_MISSING

    # The shipping default `file_action = link` hardlinks the download into
    # the library, so source and destination can be the same inode. Moving a
    # file onto itself destroys it.
    #
    # Wrapped, because `samefile` stats BOTH paths and raises OSError if
    # either has gone -- and both were checked moments ago, so this is a real
    # time-of-check/time-of-use window, not a hypothetical. An escaping
    # exception would break this function's own `(ok, reason)` contract and
    # reach the renamer as an untyped failure. If we cannot tell whether they
    # are the same file, we refuse.
    try:
        if os.path.samefile(source, destination):
            return False, REFUSED_SAME_FILE
    except OSError:
        return False, REFUSED_IDENTITY_UNVERIFIABLE

    # Guarded for the same time-of-check/time-of-use reason as `samefile`
    # above: several stat calls on the destination happen between the source's
    # existence check and this one, and an operator or another process can
    # remove it in that window. An escaping OSError would break the
    # `(ok, reason)` contract.
    # Refused before staging, not skipped at the end. A caller that asked for
    # revalidation and handed us None could not stat the destination when it
    # decided -- so there is no baseline to compare against, and proceeding
    # would mean doing the irreversible step with the one check that guards
    # concurrent replacement turned off.
    if destination_identity is not _IDENTITY_NOT_REQUESTED and destination_identity is None:
        return False, REFUSED_IDENTITY_UNVERIFIABLE

    try:
        expected_size = os.path.getsize(source)
    except OSError:
        return False, REFUSED_NO_SOURCE

    # The scanner's measurement, not a fresh one. Taking the size again here
    # and comparing it to itself is what made this check vacuous before: a
    # downloader appending between the scan and now produces two consistent
    # fresh readings and one stale quality rung.
    if expected_source_size is not None and expected_size != expected_source_size:
        return False, REFUSED_SOURCE_CHANGED

    # --- stage beside the destination ----------------------------------
    # Unique per attempt: two concurrent scans, or a previous crashed run,
    # must not collide on this name. The renamer lock (B0) makes concurrency
    # unlikely, not impossible -- a second CouchPotato process shares neither
    # its memory nor its lock.
    staging = os.path.join(
        os.path.dirname(destination),
        '.cp-upgrade-%s.part' % uuid.uuid4().hex,
    )

    try:
        stage(source, staging)
    except Exception:
        _discard_staging_if_safe(staging, source, expected_size, remove)
        return False, FAILED_STAGING

    # --- verify before the irreversible step ---------------------------
    try:
        staged_size = os.path.getsize(staging)
    except OSError:
        # Cleanup attempted here too, for consistency with every other failure
        # branch. The helper still refuses to discard the staged file when it
        # is the only complete copy, so consistency costs no safety.
        _discard_staging_if_safe(staging, source, expected_size, remove)
        return False, FAILED_STAGING

    if staged_size != expected_size:
        _discard_staging_if_safe(staging, source, expected_size, remove)
        return False, FAILED_SIZE_MISMATCH

    # --- is it still the file we decided about? ------------------------
    # Last possible moment. The renamer lock is process-local, so a second
    # CouchPotato process against the same library can have installed a better
    # copy while this one was staging -- and the decision that authorised this
    # swap was made against the file that used to be there.
    if destination_identity is not _IDENTITY_NOT_REQUESTED:
        if identity_of(destination) != tuple(destination_identity):
            _discard_staging_if_safe(staging, source, expected_size, remove)
            return False, FAILED_DESTINATION_CHANGED

    # --- the one destructive operation ---------------------------------
    if about_to_replace is not None:
        try:
            about_to_replace()
        except Exception:
            # A forensic record must never be the reason a swap fails, and it
            # must never be silent about failing either.
            log.error('Could not record the imminent replacement', exc_info=True)

    try:
        os.replace(staging, destination)
    except OSError as error:
        # The destination is untouched: os.replace either happened or did not.
        #
        # errno and strerror, no paths. A read-only mount, a permission
        # problem and a disconnected NAS are three different remedies that all
        # arrive here, and `failed_swap` alone cannot tell them apart in the
        # operator's only diagnostic channel.
        log.error(
            'The atomic swap failed: [errno %s] %s',
            error.errno, error.strerror or type(error).__name__,
        )
        _discard_staging_if_safe(staging, source, expected_size, remove)
        return False, FAILED_SWAP

    return True, REPLACED


def _discard_staging_if_safe(staging, source, expected_size, remove):
    """Remove the staged file ONLY if a complete copy survives elsewhere.

Staging is a copy now, so in this module's own flow the source is always
    still there and this check always passes. The guard stays anyway, and
    deliberately:

    `stage` is injectable. A caller that passes a consuming transfer -- which
    is exactly what the renamer used to do, and what the tests still do to
    model it -- leaves the staged file as the only complete copy of the
    download in existence after a failure. Tidying it away would destroy what
    the operator just spent hours fetching, turning a recoverable failure into
    a loss.

    A guard that is currently unreachable through one caller is not the same
    as a guard that is wrong, and this one costs a stat.

    So: only discard when the source is still there AND still whole. Anything
    else is left on disk for a human, which is untidy and recoverable, rather
    than clean and gone.
    """
    if not os.path.exists(staging):
        return
    try:
        source_intact = (
            os.path.exists(source) and os.path.getsize(source) == expected_size
        )
    except OSError:
        source_intact = False

    if not source_intact:
        return

    try:
        remove(staging)
    except OSError:
        # Leaving it is the safe failure. The destination is still intact and
        # the source is still intact; the only cost is a stray .part file.
        pass


def identity_of(path):
    """`(st_dev, st_ino, st_size, st_mtime_ns)`, or None if it cannot be read.

    None never compares equal to a real identity, so an unreadable
    destination refuses rather than resolving to "unchanged".
    """
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
