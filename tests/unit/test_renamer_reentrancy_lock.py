"""The renamer's re-entrancy guard must be an actual lock, not an unlocked
class-attribute check-then-set.

`Renamer.scan` (renamer/main.py) used to read like this:

    if self.renaming_started:
        log.info('Renamer is already running, skipping')
        return
    if not self.conf('from') and not base_folder:
        return
    self.renaming_started = True
    ...
    finally:
        self.renaming_started = False

Two threads can both pass the `if self.renaming_started` check before either
reaches the `self.renaming_started = True` set -- and the `self.conf('from')`
call sitting between them (which may hit the settings store) widens that
window further. Two concurrent scans can then both run over the same download
folder, on the code path that moves (and will soon delete) files.

AC-DATA-13 / AC-ARCH-11 (specs/FEAT-009B-UPGRADE-REPLACEMENT.md) require the
guard to be a real lock (`couchpotato.core.media_lock.media_lock`) covering
the check-and-set atomically, proven by racing two real threads against a
real filesystem -- not by asserting a lock object exists or that media_lock
was called.
"""
import threading


from couchpotato.core.plugins.renamer.main import Renamer


class _ScanEventRecorder:
    """Records every fireEvent call, and lets the FIRST `conf('from', ...)`
    call block on demand so a race between two threads can be driven
    deterministically instead of with sleeps.

    Why blocking the first `conf('from')` call proves the guard:

    In the UNFIXED code, `conf('from')` sits between the check (`if
    self.renaming_started`) and the set (`self.renaming_started = True`).
    If thread 1 is paused inside its first `conf('from')` call,
    `renaming_started` is still False -- thread 1 has not reached the set
    yet. Thread 2 then also passes the check (still False), calls `conf`
    (not blocked -- it is not the first call), sets the flag, runs the scan
    body once, and clears the flag in its own `finally`. When thread 1 is
    released it proceeds past its now-stale check, sets the flag itself, and
    runs the scan body a SECOND time -- `fireEvent('scanner.scan', ...)` is
    observed twice.

    In the FIXED code, the check-and-set happens under `media_lock` BEFORE
    any `conf()` call. By the time thread 1 ever reaches (and blocks inside)
    `conf('from')`, `renaming_started` is already True and the lock has
    already been released. Thread 2 then sees `renaming_started is True`
    under the lock and returns immediately -- it never even calls `conf`.
    So thread 2 must return promptly (never blocks on the Event at all), and
    the scan body must run exactly once.
    """

    def __init__(self, conf_values, scan_folder, raise_in_scan=False,
                 block_first_conf_call=True):
        self._conf_values = conf_values
        self._scan_folder = scan_folder
        self._raise_in_scan = raise_in_scan
        self._block_first_conf_call = block_first_conf_call

        self._first_conf_call_lock = threading.Lock()
        self._first_conf_call_claimed = False

        self.entered_conf = threading.Event()
        self.release_conf = threading.Event()

        self.scanner_scan_calls = 0
        self._calls_lock = threading.Lock()

    def conf(self, key, default=None, **kwargs):
        if key == 'from' and self._block_first_conf_call:
            is_first_call = False
            with self._first_conf_call_lock:
                if not self._first_conf_call_claimed:
                    self._first_conf_call_claimed = True
                    is_first_call = True

            if is_first_call:
                self.entered_conf.set()
                released = self.release_conf.wait(timeout=5)
                if not released:
                    raise AssertionError(
                        'release_conf was never set -- the test driver did '
                        'not release the blocked thread in time'
                    )

        return self._conf_values.get(key, default)

    def fireEvent(self, event_name, **kwargs):
        if event_name == 'scanner.scan':
            with self._calls_lock:
                self.scanner_scan_calls += 1
            if self._raise_in_scan:
                raise RuntimeError('boom: scanner.scan blew up')
            return {}
        return None


def _make_plugin(tmp_path, monkeypatch, raise_in_scan=False,
                  block_first_conf_call=True):
    plugin = Renamer.__new__(Renamer)
    recorder = _ScanEventRecorder(
        conf_values={'from': str(tmp_path)},
        scan_folder=str(tmp_path),
        raise_in_scan=raise_in_scan,
        block_first_conf_call=block_first_conf_call,
    )

    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: recorder.conf(key, default, **kw),
        raising=False,
    )
    monkeypatch.setattr(
        'couchpotato.core.plugins.renamer.main.fireEvent', recorder.fireEvent
    )
    monkeypatch.setattr(
        type(plugin), 'shuttingDown', lambda _self: False, raising=False
    )

    return plugin, recorder


class TestConcurrentScansAreMutuallyExclusive:

    def test_a_second_concurrent_scan_is_refused_not_run(self, tmp_path, monkeypatch):
        plugin, recorder = _make_plugin(tmp_path, monkeypatch)

        thread1 = threading.Thread(target=plugin.scan)
        thread1.start()

        entered = recorder.entered_conf.wait(timeout=5)
        assert entered, 'thread 1 never reached the conf("from") call -- test setup is broken'

        thread2 = threading.Thread(target=plugin.scan)
        thread2.start()

        # Thread 2 must be refused promptly by the check-and-set guard, not
        # block waiting for thread 1's scan to finish. Under the unfixed
        # code this also returns promptly (renaming_started is still False,
        # so thread 2 sails through the check) -- the real assertion is
        # further down, on how many times the scan body actually ran.
        thread2.join(timeout=2)
        assert not thread2.is_alive(), (
            'the second entrant blocked instead of being refused promptly'
        )

        recorder.release_conf.set()
        thread1.join(timeout=5)
        assert not thread1.is_alive(), 'thread 1 never completed'

        assert recorder.scanner_scan_calls == 1, (
            'the renamer scan body ran %d times for two concurrent scan() '
            'calls -- the re-entrancy guard let both threads run the scan '
            '(expected exactly 1: the second entrant should have been '
            'refused by the check-and-set before ever reaching '
            'fireEvent)' % recorder.scanner_scan_calls
        )
        assert plugin.renaming_started is False, (
            'renaming_started was left True after both scans finished'
        )


class TestTheGuardHoldsWhileFilesAreMoving:
    """The window that actually matters is the TRANSFER, not the config read.

    Review's counter-example against the first version of this test: clearing
    `renaming_started` immediately after discovery, instead of in the
    `finally`, would keep that test green while still letting a second scan
    start during group processing. The first test blocks inside
    `conf('from')`, so it proves the check-and-set is atomic and nothing more.

    This one blocks inside `_processGroup` -- with a real group returned from
    `scanner.scan`, so the renamer is genuinely mid-scan -- and asserts a
    second entrant is refused while that is happening. It is the case the
    guard exists for: the renamer is the code path that moves, and will soon
    delete, files from the library.
    """

    def test_a_second_scan_is_refused_while_a_group_is_being_processed(
        self, tmp_path, monkeypatch
    ):
        in_process = threading.Event()
        release_process = threading.Event()
        processed = []
        processed_lock = threading.Lock()

        plugin = Renamer.__new__(Renamer)

        def _fire(event_name, **kwargs):
            if event_name == 'scanner.scan':
                return {'movie-1': {'identifier': 'movie-1'}}
            return None

        def _process_group(_self, group, media_folder, release_download):
            with processed_lock:
                processed.append(group)
            in_process.set()
            assert release_process.wait(timeout=5), 'driver never released the mover'

        monkeypatch.setattr(
            type(plugin), 'conf',
            lambda _self, key, default=None, **kw: str(tmp_path) if key == 'from' else default,
            raising=False,
        )
        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.main.fireEvent', _fire
        )
        monkeypatch.setattr(type(plugin), 'shuttingDown', lambda _self: False, raising=False)
        monkeypatch.setattr(type(plugin), '_processGroup', _process_group, raising=False)

        first = threading.Thread(target=plugin.scan)
        first.start()
        assert in_process.wait(timeout=5), 'the first scan never reached _processGroup'

        # The renamer is now genuinely mid-transfer. A second caller must be
        # refused, and must be refused PROMPTLY rather than queueing behind it.
        second = threading.Thread(target=plugin.scan)
        second.start()
        second.join(timeout=2)
        assert not second.is_alive(), (
            'the second entrant blocked behind an in-flight scan instead of '
            'being refused -- the lock is being held across the whole scan'
        )

        release_process.set()
        first.join(timeout=5)
        assert not first.is_alive(), 'the first scan never completed'

        assert len(processed) == 1, (
            '_processGroup ran %d times: a second scan entered while the first '
            'was still moving files' % len(processed)
        )
        assert plugin.renaming_started is False


class TestAFailedScanDoesNotWedgeTheRenamerForever:

    def test_the_flag_clears_and_a_later_scan_still_runs(self, tmp_path, monkeypatch):
        plugin, recorder = _make_plugin(
            tmp_path, monkeypatch, raise_in_scan=True, block_first_conf_call=False
        )

        # scan() catches exceptions from the body internally (see the
        # existing `except Exception: log.error(...)` around the group
        # processing / fireEvent call), so this must not raise -- but the
        # flag must still be cleared afterward.
        plugin.scan()

        assert plugin.renaming_started is False, (
            'a failed scan left renaming_started True, permanently wedging '
            'the renamer'
        )
        assert recorder.scanner_scan_calls == 1

        # A subsequent scan must actually proceed (reach fireEvent again),
        # not be refused forever by a stuck flag.
        plugin.scan()

        assert recorder.scanner_scan_calls == 2, (
            'a scan after a prior failure was refused instead of running'
        )
        assert plugin.renaming_started is False
