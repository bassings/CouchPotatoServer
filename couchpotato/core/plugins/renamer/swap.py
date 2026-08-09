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
import uuid

# Refusals taken before anything is touched.
REFUSED_NO_SOURCE = 'refused_no_source'
REFUSED_DESTINATION_MISSING = 'refused_destination_missing'
REFUSED_DESTINATION_IS_SYMLINK = 'refused_destination_is_symlink'
REFUSED_SAME_FILE = 'refused_same_file'

# Failures after work began. The library file is intact in every one of them.
FAILED_STAGING = 'failed_staging'
FAILED_SIZE_MISMATCH = 'failed_size_mismatch'
FAILED_SWAP = 'failed_swap'

REPLACED = 'replaced'


def replace_atomically(source, destination, move, remove=os.remove):
    """Replace `destination` with `source`. Returns `(ok, reason)`.

    `move(src, dst)` is injected -- the renamer passes `moveFile`, which owns
    the copy/link/symlink modes and permission handling. `remove` is injected
    only so tests can force a cleanup failure.

    The library file at `destination` survives every path through this
    function except the successful one.
    """
    # --- refuse before touching anything -------------------------------
    if not os.path.exists(source):
        return False, REFUSED_NO_SOURCE

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

    if os.path.samefile(source, destination):
        # The shipping default `file_action = link` hardlinks the download into
        # the library, so source and destination can be the same inode. Moving
        # a file onto itself destroys it.
        return False, REFUSED_SAME_FILE

    expected_size = os.path.getsize(source)

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
        move(source, staging)
    except Exception:
        _discard_staging_if_safe(staging, source, expected_size, remove)
        return False, FAILED_STAGING

    # --- verify before the irreversible step ---------------------------
    try:
        staged_size = os.path.getsize(staging)
    except OSError:
        return False, FAILED_STAGING

    if staged_size != expected_size:
        _discard_staging_if_safe(staging, source, expected_size, remove)
        return False, FAILED_SIZE_MISMATCH

    # --- the one destructive operation ---------------------------------
    try:
        os.replace(staging, destination)
    except OSError:
        # The destination is untouched: os.replace either happened or did not.
        _discard_staging_if_safe(staging, source, expected_size, remove)
        return False, FAILED_SWAP

    return True, REPLACED


def _discard_staging_if_safe(staging, source, expected_size, remove):
    """Remove the staged file ONLY if a complete copy survives elsewhere.

    `move` may have consumed the source (a real move) or left it in place
    (copy/link). After a failure the staged file is therefore sometimes the
    only complete copy of the download in existence, and tidying it away would
    destroy what the operator just spent hours fetching -- turning a
    recoverable failure into a loss.

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
