"""Which release owns the file at a destination path?

FEAT-009B B2. A pure resolver: it reads a path, a list of release documents and
the size of the file on disk, and returns the release that demonstrably owns
that file, or a refusal reason. **Nothing calls it yet** — the replacement gate
lands in B3. That ordering is deliberate: the two withdrawn attempts at upgrade
replacement both deleted the wrong file, and the spec requires each decision
input to be correct and proven before anything acts on it.

Why the answer needs two steps rather than one, per D5 in the spec:

  - a release records the PATHS it was scanned from (`release['files']`,
    written unconditionally at `release/main.py:314`), and
  - a SIZE-derived `copy_id` (`copyIdentity`, `release/main.py:24-56`), written
    only when it could be computed.

Path alone cannot identify the owner, and `copyIdentity`'s own docstring says
why: the default rename template is `<namethe> (<year>)/<thename><cd>.<ext>`,
carrying no quality, group or source token, so **every copy of a movie renames
to the same path**. Two releases at different qualities routinely claim the
identical destination. Size is what tells them apart — two different encodes
essentially never share a byte count.

So: narrow by path, then disambiguate by size, and REFUSE on any residue. The
refusal reasons are values rather than log strings so callers can assert on the
decision instead of on prose (AC-QA-11).
"""

from couchpotato.core.helpers.variable import sp

# Outcome values. `declined_*` all mean "the library file was left alone".
OWNER_RESOLVED = 'resolved'
DECLINED_NO_OWNER = 'declined_no_owner'
DECLINED_AMBIGUOUS_OWNER = 'declined_ambiguous_owner'
DECLINED_UNVERIFIED_COPY = 'declined_unverified_copy'


def _movie_paths(release):
    """The 'movie' bucket of a release's recorded files, `sp()`-normalised.

    Only the movie bucket: a subtitle or poster sharing the folder is not
    evidence about which encode is on disk, and `copyIdentity` restricts
    itself the same way for the same reason.
    """
    files = release.get('files') or {}
    return {sp(p) for p in (files.get('movie') or [])}


def resolve_owning_release(destination, releases, size_on_disk):
    """Return `(release, outcome)` for the file at `destination`.

    `release` is None for every outcome except OWNER_RESOLVED. `size_on_disk`
    is the actual size of the file now at `destination`, or None when it could
    not be stat'ed — which is itself a refusal, never an assumption.

    The caller must treat any `declined_*` as "do not touch the library file".
    """
    target = sp(destination)

    # Checked FIRST, before any claimant counting. "Could not stat" is a
    # different refusal from "cannot tell which release owns it", and reporting
    # the wrong one sends the next operator looking in the wrong place. The
    # first version only produced UNVERIFIED on the single-claimant path, so an
    # unstattable destination with two claimants reported AMBIGUOUS instead --
    # contradicting this module's own contract.
    if size_on_disk is None:
        return None, DECLINED_UNVERIFIED_COPY

    candidates = [r for r in (releases or []) if target in _movie_paths(r)]

    if not candidates:
        # A manually placed file, or one belonging to different media. Unknown
        # never means replaceable (AC-QA-10).
        return None, DECLINED_NO_OWNER

    # A claimant with no copy_id cannot be ruled IN or OUT -- releases written
    # before FEAT-009 Part A have none. With one such claimant beside a
    # size-matching one, the first version returned the matching release as
    # resolved, and that is the dangerous shape: the legacy claimant may be the
    # real owner, so the quality we would compare against belongs to the wrong
    # release. On a path that deletes from the library, "no evidence" must
    # block the whole decision rather than lose a vote.
    unverifiable = [r for r in candidates if not r.get('copy_id')]

    if len(candidates) == 1:
        # Still verified by size. A single claimant proves which release was
        # scanned from this path, not that the bytes there now are the ones it
        # described -- the file may have been swapped since (AC-DATA-6).
        # `unverifiable` is deliberately NOT re-checked here: with one
        # candidate, a missing copy_id already makes _copy_matches false.
        # Mutation testing proved the extra clause could not fail, and a guard
        # clause nobody can break is one that only looks like protection.
        if not _copy_matches(candidates[0], size_on_disk):
            return None, DECLINED_UNVERIFIED_COPY
        return candidates[0], OWNER_RESOLVED

    if unverifiable:
        return None, DECLINED_AMBIGUOUS_OWNER

    # More than one release claims the path, which is the NORMAL case for two
    # qualities of the same movie under the default template. Size decides.
    matching = [r for r in candidates if _copy_matches(r, size_on_disk)]
    if len(matching) == 1:
        return matching[0], OWNER_RESOLVED

    # Deliberately NOT logged here. This is a pure function called once per
    # file per scan, so an unchanged ambiguous destination would emit an
    # identical record on every pass -- against the bounded-logging
    # requirement at specs/FEAT-009B-UPGRADE-REPLACEMENT.md:165. The outcome
    # value is the contract; B3's caller owns operator messaging, including
    # suppression, and under D8 it names the media identifier rather than the
    # path.
    return None, DECLINED_AMBIGUOUS_OWNER


def _copy_matches(release, size_on_disk):
    """Does this release's recorded copy identity match the bytes on disk?

    False when either side is missing. `copyIdentity` returns None when a file
    could not be stat'ed, and a release written before FEAT-009 Part A has no
    `copy_id` at all -- in both cases the honest answer is "cannot verify",
    and on a path that deletes from the library that must read as no.
    """
    if size_on_disk is None:
        return False
    copy_id = release.get('copy_id')
    if not copy_id:
        return False
    return copy_id == copy_id_for_sizes([size_on_disk])


def copy_id_for_sizes(sizes):
    """The `copyIdentity` value a single-file copy of these sizes would have.

    Mirrors `release/main.py:copyIdentity`'s format rather than importing it,
    because that function takes a scanner `files` dict and stats the
    filesystem; here the size is already known.

    The separator is a COMMA, and that is not a detail. The first version of
    this used `|`, which matches no real `copy_id` ever written -- so
    `_copy_matches` would have returned False for every release and the gate
    would have refused every replacement. Inert, and inert looks exactly like
    safe. That is precisely how withdrawn attempt #2 hid its danger.

    `test_release_owner.py` pins this against the real `copyIdentity` on a real
    file, so the two formats cannot drift apart again.
    """
    return ','.join(str(int(s)) for s in sorted(sizes))
