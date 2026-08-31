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
