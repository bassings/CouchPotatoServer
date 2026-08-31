"""The operator replace route must not mint its own decision-time baseline.

Critical C2 has now been reintroduced three times, each time by a change
that looked correct in isolation, so the scenario is pinned here end to end
through the real route rather than against the executor alone.

The guard being protected: before the operator's chosen file is installed
over the library copy, its size is compared against the size recorded when
the operator was SHOWN that file in the picker. If those disagree, the file
changed after they chose it and the replacement is refused.

The failure mode this file exists to catch is subtle, because the guard
still appears to be present and its unit tests still pass. If anything on
the request path records the baseline itself, the comparison becomes a
fresh stat measured against another fresh stat taken moments later. For a
file that is static, those always agree, so the guard passes for every
input and the refusal branch becomes unreachable in production.

Why "static" is the dangerous case rather than the safe one: a copy that
has STALLED partway across a mount is static. It is not growing, so two
measurements taken moments apart agree, while the file itself is a
fragment. The complete copy it replaces is then deleted, and neither copy
survives. A home media server holds the only copy of most of its library,
so this is discovered on a play attempt, long after any undo is possible.
"""
import hashlib
import os
import threading

import pytest

from tests.unit.test_replacement_operator_replay_guard import world  # noqa: F401

COMPLETE_LIBRARY_COPY = b'the complete 2160p remux' * 5000
STALLED_PARTIAL = b'partial fragment' * 10


def _sha(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestARestartedProcessCannotVouchForWhatTheOperatorChose:
    """The picker was populated, then the container restarted, so nothing in
    this process witnessed the operator's choice. Confirm must refuse.
    """

    def test_a_stalled_partial_does_not_replace_the_complete_library_copy(
        self, world,
    ):
        plugin = world['plugin']
        source, destination = world['src'], world['dst']

        with open(destination, 'wb') as fh:
            fh.write(COMPLETE_LIBRARY_COPY)
        complete_sha = _sha(destination)

        # The operator's source: a cross-mount copy that stalled partway and
        # is now static. Deliberately far smaller than what it would replace,
        # so a swap is unmistakable in the assertion below rather than a
        # judgement call about byte counts.
        with open(source, 'wb') as fh:
            fh.write(STALLED_PARTIAL)

        # The restart. The fixture's listing is discarded, which is what a
        # process restart between opening the picker and pressing Confirm
        # actually does to an in-memory baseline.
        if hasattr(plugin, '_operator_candidate_sizes'):
            del plugin._operator_candidate_sizes

        # The replacement runs on a background thread, so the request
        # returning tells us nothing. Join it, or this test would assert
        # against a swap that simply had not happened yet and would pass
        # whatever the code did.
        started = []
        real_thread = threading.Thread

        class _CapturingThread(real_thread):
            def start(self):
                started.append(self)
                super().start()

        import couchpotato.core.plugins.renamer.main as renamer_main
        renamer_main.threading.Thread = _CapturingThread
        try:
            plugin.operatorReplaceView(media_id='media-1', source='incoming.mkv')
        finally:
            renamer_main.threading.Thread = real_thread

        assert started, (
            'the route never started a replacement thread, so this test '
            'would pass without exercising the guard at all'
        )
        for thread in started:
            thread.join(timeout=30)
            assert not thread.is_alive(), 'the replacement thread did not finish'

        assert _sha(destination) == complete_sha, (
            'a stalled partial (%d bytes) replaced the complete library copy '
            '(%d bytes) with no baseline from the moment the operator chose. '
            'Something on the request path is recording the decision-time '
            'size itself, which makes the comparison a fresh stat against '
            'another fresh stat and the refusal unreachable.'
            % (len(STALLED_PARTIAL), len(COMPLETE_LIBRARY_COPY))
        )
        assert os.path.getsize(destination) == len(COMPLETE_LIBRARY_COPY)


class TestThePreviewRouteMustNotReMintTheBaseline:
    """C2, fourth recurrence, found by the PR #292 review. NOT YET FIXED.

    `_operatorReplacementPreview` calls `_listOperatorCandidates`, a thin
    wrapper over `_listOperatorCandidatesWithReason`, which unconditionally
    reassigns `self._operator_candidate_sizes`. That dict is the record of
    what the operator was shown when they chose. So a preview issued
    between the listing and the confirmation silently replaces the baseline
    with a fresh measurement, and the guard becomes a stat compared against
    another stat taken moments later, which is exactly the defect this file
    was written to pin.

    The route's own docstring calls itself read-only. It is read-only with
    respect to the library and not with respect to the safety baseline,
    which is the more important of the two.

    Why this is xfail rather than a fix. The feature ships disabled and
    unreachable (`operator_replace_enabled` defaults False in both the
    settings schema and the code fallback), so this cannot happen on a real
    installation today. It is the FOURTH time this same defect class has
    been reintroduced by an individually reasonable-looking change, and the
    project's own rule is that after three the answer is to question the
    shape rather than apply a fourth patch. Fixing it inside a release whose
    purpose is to take this path OUT of service would be the same trade that
    produced the other three.

    `strict=True` is the point of writing it this way: when the baseline is
    finally bound to the listing the operator saw, this test starts passing,
    the suite goes RED on the unexpected pass, and whoever fixed it is told
    to delete the marker. A comment in a spec cannot do that.

    See specs/FEAT-011-replace-with-this-file.md, blocking preconditions.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            'C2 recurrence 4: the preview route re-mints the decision-time '
            'baseline. Unreachable while operator_replace_enabled is off. '
            'When this passes, remove the marker and close the precondition.'
        ),
    )
    def test_a_preview_between_listing_and_confirm_does_not_rebase_the_guard(
        self, world,
    ):
        plugin = world['plugin']
        source, destination = world['src'], world['dst']

        with open(destination, 'wb') as fh:
            fh.write(COMPLETE_LIBRARY_COPY)
        complete_sha = _sha(destination)

        # The operator opens the picker while the source is still copying.
        with open(source, 'wb') as fh:
            fh.write(b'first 400MB of a NAS copy' * 40)
        plugin._listOperatorCandidatesWithReason()

        # The copy then stalls, so it is static but incomplete.
        with open(source, 'wb') as fh:
            fh.write(b'stalled fragment' * 10)

        # Anything at all issues a preview before they press Confirm. This
        # is the whole finding: it re-stats the folder and overwrites the
        # baseline with the stalled size.
        plugin._operatorReplacementPreview('media-1')

        started = []
        real_thread = threading.Thread

        class _CapturingThread(real_thread):
            def start(self):
                started.append(self)
                super().start()

        import couchpotato.core.plugins.renamer.main as renamer_main
        renamer_main.threading.Thread = _CapturingThread
        try:
            plugin.operatorReplaceView(media_id='media-1', source='incoming.mkv')
        finally:
            renamer_main.threading.Thread = real_thread
        for thread in started:
            thread.join(timeout=30)

        assert _sha(destination) == complete_sha, (
            'a preview issued between the listing and the confirmation '
            're-minted the decision-time baseline, so the stalled fragment '
            'matched its own fresh measurement and replaced the complete '
            'library copy'
        )
