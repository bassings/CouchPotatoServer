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
import os
import time

import pytest

from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.core.plugins.renamer.owner import DECLINED_NO_OWNER
from couchpotato.core.plugins.renamer.replacement import (
    DECLINED_ERROR,
    DECLINED_INCOMPLETE_EVIDENCE,
    DECLINED_MULTI_FILE_GROUP,
    DECLINED_NOT_BETTER,
    DECLINED_OUTSIDE_LIBRARY,
    DECLINED_SETTING_OFF,
    DECLINED_SIZE_CONTRADICTS_QUALITY,
    DECLINED_SOURCE_CHANGED,
    DECLINED_UNKNOWN_QUALITY,
    DECLINED_UNVERIFIED_IDENTITY,
    REPLACE,
)
import couchpotato.core.plugins.scanner.folder_scanner as folder_scanner_module
from couchpotato.core.plugins.scanner.folder_scanner import FolderScannerMixin


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
    # Backdated well outside the default 60-second settling window that
    # `checkFilesChanged` uses (couchpotato/core/plugins/base.py:352,
    # `unchanged_for=60`). A file this fixture just wrote otherwise has
    # "now" as its mtime, which is INSIDE that window by construction --
    # every test below that expects a decision to be recorded relies on
    # the settling-window guard (TestSettlingFilesBlockRecording) never
    # firing for this baseline file.
    settled_time = time.time() - 3600
    os.utime(str(src), (settled_time, settled_time))

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
    notify_calls = []

    def _fire(event, *args, **kwargs):
        if event == 'scanner.scan':
            scan_calls['scanner.scan'] += 1
            return {'group-1': _group()}
        if event == 'notify':
            # Captured, not asserted on by the original test -- this is
            # binding decision 3's out-of-band surface (item 5): one
            # fireEvent('notify', ...) per parked group, nothing more.
            notify_calls.append(kwargs if kwargs else (args[0] if args else None))
            return None
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
        'notify_calls': notify_calls,
        'group_factory': _group,
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


class TestFolderScannerNeverReducesTheScanResult:
    """AC-QA-7 (BUG-018) -- replaces the withdrawn `TestFolderScannerIsUntouched`.

    `folder_scanner.py` is shared with `manage.updateLibrary`, whose cleanup
    at `manage.py:274-275` deletes any 'done' movie absent from the scan
    result: the media document, its releases, watch history, tags, profile
    and review state, with no backup taken automatically. The class this
    replaces asserted an empty `git diff` against master as a PROXY for
    "this module must never start feeding that cleanup a false negative" --
    a proxy that only worked as long as nothing legitimate ever needed to
    change the module. BUG-018 does need to change it (the year-
    disambiguation fix for the fifth identification fallback), so the freeze
    is retired in favour of the property it always stood in for.

    The property: a group the pre-BUG-018 fallback could identify must still
    come out identified afterwards, even when the identifier it returns
    names a DIFFERENT film -- WHICH film is exactly what BUG-018 is allowed
    to change. Returning nothing at all, where the old code returned
    something, is what would starve `manage.updateLibrary` into believing a
    still-owned film is gone.

    This class drives the PRIMARY `movie.search` call site only. The
    `name_year['other']` call site (reached only when the primary query
    comes back empty) is exercised against the same candidate shapes,
    parametrized over both sites, in
    `tests/unit/test_scanner_search_year_disambiguation.py::TestTheInvariantNeverFewerIdentifiersThanBefore`
    -- duplicating that parametrization here would test the same production
    code path twice for no added protection.
    """

    @staticmethod
    def _pre_bug_018_selection(candidates):
        """The fallback's selection before BUG-018:
        `fireEvent('movie.search', ..., limit=1)`, then `movie[0]`, nothing
        else read from the result. Kept as a plain function of the
        candidate list rather than imported from production, because
        production is exactly what this guards -- importing the (now
        fixed) selection would compare it with itself and could never
        fail."""
        if not candidates:
            return None
        return candidates[0].get('imdb')

    @pytest.fixture
    def bug018_scanner(self, monkeypatch):
        plugin = FolderScannerMixin()
        monkeypatch.setattr(
            folder_scanner_module, 'get_db',
            lambda: (_ for _ in ()).throw(RuntimeError('no db in this test')),
        )
        monkeypatch.setattr(type(plugin), 'getCPImdb', lambda _s, _f: None, raising=False)
        monkeypatch.setattr(folder_scanner_module, 'getImdb', lambda path, check_inside=False: None)
        return plugin

    @pytest.mark.parametrize('candidates', [
        pytest.param(
            [{'imdb': 'tt0120762', 'year': 1998}, {'imdb': 'tt3480796', 'year': 2020}],
            id='remake_ordered_before_the_correct_film',
        ),
        pytest.param(
            [{'imdb': 'tt0058331', 'year': 1975}],
            id='single_candidate_whose_year_does_not_match',
        ),
        pytest.param(
            [{'imdb': 'ttNOYEARFIELD'}],
            id='candidate_with_no_year_field_at_all',
        ),
        # Round-one review of 0dc9e9a78 (FIX 5): every fixture above carries
        # an `imdb` key on every candidate, so none of them could ever have
        # caught FIX 1's defect -- a YEAR-MATCHING candidate with no id at
        # all starving `imdb_id` even though an older, id-bearing candidate
        # sat right next to it. Three shapes for "no id": the key absent,
        # an empty string, and an explicit `None`.
        pytest.param(
            [{'imdb': 'ttOLD', 'year': 1998}, {'year': 2020}],
            id='year_match_missing_imdb_key_entirely',
        ),
        pytest.param(
            [{'imdb': 'ttOLD', 'year': 1998}, {'imdb': '', 'year': 2020}],
            id='year_match_empty_imdb',
        ),
        pytest.param(
            [{'imdb': 'ttOLD', 'year': 1998}, {'imdb': None, 'year': 2020}],
            id='year_match_imdb_explicitly_none',
        ),
    ])
    def test_a_group_the_old_code_could_identify_is_still_identified(
        self, bug018_scanner, monkeypatch, candidates,
    ):
        name_year = {'name': 'Some Movie', 'year': 2020}
        search_q = '%(name)s %(year)s' % name_year

        def _fire(event, *args, **kwargs):
            if event == 'movie.search':
                return list(candidates) if kwargs.get('q') == search_q else []
            return None

        monkeypatch.setattr(folder_scanner_module, 'fireEvent', _fire)
        monkeypatch.setattr(
            type(bug018_scanner), 'getReleaseNameYear',
            lambda _s, i, file_name=None: dict(name_year), raising=False,
        )

        group = {
            'files': {'movie': ['/dl/Some.Movie.2020.mkv'], 'nfo': []},
            'identifiers': ['Some Movie 2020'],
            'is_dvd': False,
        }

        pre = self._pre_bug_018_selection(candidates)
        assert pre is not None, (
            'test setup error: the reference selection found nothing in %r '
            'to compare against' % candidates
        )

        result = bug018_scanner.determineMedia(group)

        assert result.get('identifier') is not None, (
            'the pre-BUG-018 selection would have identified this group as '
            '%r, but the current fallback returned no identifier at all. '
            'manage.updateLibrary deletes any "done" movie absent from the '
            'scan result -- this is exactly the data-loss shape BUG-018\'s '
            'first, withdrawn design built, and the empty-diff guard it '
            'replaced would not have caught it once folder_scanner.py was '
            'allowed to change at all.' % pre
        )


class TestDestinationChangesInvalidateTheMemory:
    """AC-QA-6 (a) and (b) / design constraint: "the destination appearing
    or disappearing" must expire a remembered refusal.

    Both scenarios below leave `world['downloads']` -- the folder the
    memory actually fingerprints -- completely untouched; only the library
    file at `world['dst']` changes. That is deliberate: it isolates the gap.
    `_folderSignature` walks `scan_folder` (the downloads folder) only, so
    today NOTHING about the destination feeds the remembered key, and a
    destination change is invisible to it.

    Sub-case (c), "a destination that did not exist and now does", is not
    exercised here: every outcome in `REMEMBER_ELIGIBLE_OUTCOMES` is reached
    only from inside `if os.path.exists(dst):` in `_moveRenamedFiles`
    (main.py), so a remembered decision can only ever have been recorded
    with the destination already present -- "appearing" cannot be a later
    transition for an entry that already exists. It collapses into the
    "changed in place" case below, which is exercised.
    """

    def test_destination_deleted_forces_a_redecide_and_files_the_download(
        self, world, caplog,
    ):
        """AC-QA-6(a), the operator's actual remedy from the production
        incident: they delete the stale library file so the download can
        finally land. This must work on the next SCHEDULED scan, with no
        restart -- a remedy that silently does nothing is worse than the
        loop, because the operator believes it is handled."""
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must park the group before this test '
            'can prove anything about invalidating that park'
        )

        os.remove(world['dst'])

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])

        assert world['scan_calls']['scanner.scan'] == 2, (
            'fireEvent("scanner.scan", ...) was not called again after the '
            'blocking library file was deleted -- the memory kept treating '
            'the group as unchanged because the destination is not part of '
            'its fingerprint, so the operator\'s remedy from the '
            'production incident (deleting the stale file) would silently '
            'do nothing until the container is restarted'
        )
        assert os.path.exists(world['dst']), (
            'the download was never filed even after the blocking '
            'destination was cleared -- "already decided" outlived its '
            'own cause'
        )
        assert open(world['dst'], 'rb').read() == world['original_src_bytes'], (
            'a file exists at the destination but its bytes are not the '
            'download -- the wrong thing landed there'
        )

    def test_destination_changed_in_place_forces_a_redecide(
        self, world, caplog,
    ):
        """AC-QA-6(b): the file at the destination path is replaced with
        different bytes at the same path, without ever disappearing. A
        signature keyed only on the downloads folder cannot see this
        either."""
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must park the group before this test '
            'can prove anything about invalidating that park'
        )

        world['dst'] and open(world['dst'], 'wb').write(
            b'a different library file entirely, same path' * 10
        )

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            world['plugin'].scan(base_folder=world['downloads'])

        assert world['scan_calls']['scanner.scan'] == 2, (
            'fireEvent("scanner.scan", ...) was not called again after the '
            'destination file at the same path was replaced with '
            'different bytes -- an in-place destination change is '
            'invisible to a signature keyed only on the downloads folder'
        )


class TestBoundedLogHoldsIndependentlyOfMemory:
    """AC-OPS-3 restated, with the memory out of the picture entirely.

    FEAT-009B already required this exact bound once (its AC-OPS-6) and
    shipped unmet -- measured at 40 records for 20 calls, growing linearly
    -- because the bound was only ever proven on a path that happened to go
    through `log_suppressed`. `_moveRenamedFiles` is also reachable through
    a TARGETED scan (`media_folder` / `release_download`), which per D8
    neither reads nor writes the memory at all, so the backstop must hold
    on its own. This test calls `_moveRenamedFiles` directly, bypassing
    `scan()` and the memory completely.
    """

    def test_an_unchanged_collision_does_not_grow_the_log_linearly(
        self, world, caplog,
    ):
        group = world['group_factory']()
        rename_files = {world['src']: world['dst']}

        with caplog.at_level(logging.INFO):
            for _ in range(20):
                world['plugin']._moveRenamedFiles(rename_files, group)

        records = [
            r for r in caplog.records if r.levelno >= logging.INFO
        ]
        assert records, (
            'the refusal never logged at all, so this run proves nothing '
            'about a bound -- the decision path itself was never reached'
        )
        assert len(records) <= 4, (
            '_moveRenamedFiles produced %d records at INFO or above for '
            '20 direct calls against one completely unchanged collision, '
            'with the per-folder memory never involved. AC-OPS-3 requires '
            'this bound to hold independently of the memory -- exactly '
            'what FEAT-009B already required and shipped unmet, measured '
            'then at 40 records for 20 calls -- because the refusal record '
            'in _moveRenamedFiles is a plain log.warning/log.info, not '
            'wrapped in the existing log_suppressed helper.' % len(records)
        )


class TestParkedGroupIsDiscoverableViaNotify:
    """Binding decision 3 / AC-OPS-5 / AC-SEC-8 (item 5): entering a parked
    state must fire exactly one fireEvent('notify', ...), using the
    existing durable notification document and the existing
    notification.list API, so the film is discoverable without reading the
    log. No new route, template or setting.

    Currently RED: nothing in the renamer fires 'notify' at all, at any
    point, so a parked film is discoverable nowhere but the log -- which is
    exactly what AC-OPS-4's bounded restatement means an operator will not
    be reading in real time.
    """

    def test_notify_fires_once_on_park_and_not_again_on_repeat_scans(
        self, world,
    ):
        for _ in range(3):
            world['plugin'].scan(base_folder=world['downloads'])

        assert world['notify_calls'], (
            'fireEvent("notify", ...) was never called across 3 scans of '
            'a group parked as declined_unverified_identity. Binding '
            'decision 3 requires exactly one notify per parked group so '
            'the film is discoverable through notification.list without '
            'reading the log; today it is discoverable nowhere but the '
            'log.'
        )
        assert len(world['notify_calls']) == 1, (
            'fireEvent("notify", ...) fired %d times across 3 scans of '
            'one unchanged parked group; it must fire exactly once, on '
            'entering the parked state, not once per scan -- otherwise '
            'this recreates the production flood in a different channel.'
            % len(world['notify_calls'])
        )


class TestNotifyNeverLeaksTheRawDownloadFolderName:
    """L1 (branch review 2026-08-31, QA/branch-review-2026-08-31-review-queue.md)
    / FEAT-012 AC-SEC-8.

    AC-SEC-8's letter is met (no token beginning "/" ever reaches the
    message), but its value is narrower than the letter suggests:
    `_notifyParked`'s title fallback is
    `getTitle(library) or group.get('dirname') or 'Unknown'`, and
    `dirname` is the raw scene-release folder name read straight off the
    operator's download folder. That fallback fires exactly when the group
    could not be identified -- which is the common case for a park, not an
    edge case -- so the folder name (source, group and quality markers
    baked into a scene-release string) leaves the machine in a
    `fireEvent('notify', ...)` payload sent to every configured
    third-party provider (Pushover, Telegram, Prowl) and is retained 28
    days in the notification document. Sending a resolved film TITLE to a
    provider is a design decision the spec records; a filesystem-derived
    folder name is a different thing nobody chose.

    Currently RED: the fallback chain includes `group.get('dirname')`, so
    an unresolvable title sends the folder name verbatim.
    """

    def test_unresolved_title_does_not_send_the_raw_download_folder_name(
        self, world,
    ):
        raw_folder_name = 'Minions.and.Monsters.2015.1080p.BluRay.x264-GRP'
        group = {
            'media': {
                '_id': 'media-unidentified',
                # Deliberately no 'titles' key anywhere reachable by
                # getTitle(): this is the "identity could not be
                # resolved" state that produces
                # declined_unverified_identity in the first place, so it
                # is the realistic case for this fallback to be reached
                # in, not a contrived one.
                'info': {'year': 2015},
            },
            'dirname': raw_folder_name,
        }

        world['plugin']._notifyParked(group, 'declined_unverified_identity')

        assert world['notify_calls'], (
            'fireEvent("notify", ...) was never called for a parked group '
            'with no resolvable title -- this test cannot prove anything '
            'about what value was sent in that message'
        )
        sent = world['notify_calls'][0]
        message = sent.get('message', '') if isinstance(sent, dict) else ''
        assert raw_folder_name not in message, (
            'the notify message for a film with no resolvable title '
            'contains the raw download folder name (%r), which leaves '
            'the machine in every configured notification provider '
            '(Pushover, Telegram, Prowl) and is retained 28 days in the '
            'notification document. A filesystem-derived scene-release '
            'string is not decision metadata and must never substitute '
            'for a title. Got message: %r' % (raw_folder_name, message)
        )


class TestRestartRedecides:
    """AC-SEC-5 / AC-SIMP-5 / item 3: a process restart is the operator's
    cheapest correct remedy, and it must re-decide -- a memory that
    survives a restart removes the one action a human would expect to
    clear a stuck state. Nothing is persisted (AC-SIMP-5): the memory is
    plain state on the `Renamer` instance, never written through `get_db()`
    or `Env`, so a freshly constructed instance -- standing in for the
    process that comes back after a restart -- must know nothing about a
    folder an EARLIER instance parked.
    """

    def test_a_freshly_constructed_renamer_redecides_a_folder_parked_by_another_instance(
        self, world,
    ):
        world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must park the group before this test '
            'can prove anything about a restart clearing it'
        )

        # Confirm the ORIGINAL instance really did park it (a second scan on
        # the same instance must stay skipped), or the "restart" half below
        # would prove nothing -- a memory that never held anything trivially
        # "survives" no restart.
        world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the original instance did not actually park the '
            'group -- it re-asked the scanner on an unchanged repeat scan, '
            'so this test cannot isolate what a restart does'
        )

        # `conf`/`shuttingDown` were monkeypatched onto the CLASS
        # (`type(plugin)`), so a second instance inherits them without
        # redoing any of that wiring -- exactly as a real restart would
        # reconstruct the plugin against the same settings.
        restarted = Renamer.__new__(Renamer)
        restarted.scan(base_folder=world['downloads'])

        assert world['scan_calls']['scanner.scan'] == 2, (
            'a freshly constructed Renamer, standing in for the process '
            'coming back after a restart, did not re-decide a folder '
            'parked by a DIFFERENT (the pre-restart) instance -- if the '
            'memory is somehow surviving across instances, a stuck '
            'refusal would outlive the one remedy an operator expects a '
            'restart to provide'
        )


class TestOnlyEligibleOutcomesAreRemembered:
    """H4 (branch review 2026-08-31) / AC-QA-9, AC-DATA-4, AC-QA-14.

    `REMEMBER_ELIGIBLE_OUTCOMES` is the one thing standing between "this
    refusal cannot change without a file or a setting moving" and "this
    refusal is transient and must be re-decided every scan" -- and nothing
    in the repo enumerated its members before this test. The branch review
    widened the frozenset to include every transient outcome, and `replace`
    itself, and the entire unit suite stayed green.

    `_processGroup` is stubbed here to hand back exactly the
    `(outcome, dst)` pair `scan()` consumes. `decide_replacement`'s own
    correctness in PRODUCING each of these outcomes from real inputs is a
    different contract, proven elsewhere against the real function; what
    this test isolates, by driving the real `scan()` around a stubbed
    result, is the SET-membership gate itself -- exactly what H4 found
    unguarded, and the only thing a widened or shrunk frozenset can break.

    `DECLINED_SIZE_CONTRADICTS_QUALITY` is asserted below as INELIGIBLE.
    That is the target shape from H5 (see the comment on
    `REMEMBER_ELIGIBLE_OUTCOMES` in `main.py`), not what ships today:
    today's frozenset still contains it, so that one parametrised case is
    RED even before H4's guard is considered on its own, and it stays RED
    until H5 lands alongside H4.
    """

    ELIGIBLE_OUTCOMES = (
        DECLINED_SETTING_OFF,
        DECLINED_UNVERIFIED_IDENTITY,
        DECLINED_MULTI_FILE_GROUP,
        DECLINED_OUTSIDE_LIBRARY,
    )

    INELIGIBLE_OUTCOMES = (
        DECLINED_UNKNOWN_QUALITY,
        DECLINED_INCOMPLETE_EVIDENCE,
        DECLINED_ERROR,
        DECLINED_SOURCE_CHANGED,
        DECLINED_NOT_BETTER,
        DECLINED_NO_OWNER,
        REPLACE,
        DECLINED_SIZE_CONTRADICTS_QUALITY,
    )

    @staticmethod
    def _stub_process_group(monkeypatch, plugin, outcome, dst):
        monkeypatch.setattr(
            type(plugin), '_processGroup',
            lambda _self, group, media_folder=None, release_download=None: [
                (outcome, dst),
            ],
            raising=False,
        )

    @pytest.mark.parametrize('outcome', ELIGIBLE_OUTCOMES)
    def test_eligible_outcome_is_remembered_and_skips_the_next_scan(
        self, world, monkeypatch, outcome,
    ):
        self._stub_process_group(monkeypatch, world['plugin'], outcome, world['dst'])

        world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must record %r before this test can '
            'prove anything about remembering it' % (outcome,)
        )

        world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            '%r is in REMEMBER_ELIGIBLE_OUTCOMES, and its cause cannot '
            'change without a file or a setting moving -- a second, '
            'completely unchanged scan must be answered from memory, not '
            're-asked from the scanner' % (outcome,)
        )

    @pytest.mark.parametrize('outcome', INELIGIBLE_OUTCOMES)
    def test_ineligible_outcome_is_never_remembered_and_redecides_every_scan(
        self, world, monkeypatch, outcome,
    ):
        self._stub_process_group(monkeypatch, world['plugin'], outcome, world['dst'])

        world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must produce %r before this test can '
            'prove anything about it never being remembered' % (outcome,)
        )

        world['plugin'].scan(base_folder=world['downloads'])
        assert world['scan_calls']['scanner.scan'] == 2, (
            '%r must never be remembered: its cause can change with '
            'neither a file nor a setting moving, so treating it as '
            'settled would let a remembered refusal outlive the thing '
            'that produced it (AC-QA-9/AC-QA-14). A completely unchanged '
            'second scan was answered from memory instead of being '
            're-decided.' % (outcome,)
        )

    def test_every_outcome_the_automatic_path_can_produce_is_covered_above(self):
        """Guards the parametrisation itself, the same way the settings
        coverage test in the sibling invalidation file does: if a new
        outcome constant is ever added to `decide_replacement`'s
        vocabulary without a case here, this fails loudly rather than the
        new outcome silently going untested for memory eligibility."""
        covered = set(self.ELIGIBLE_OUTCOMES) | set(self.INELIGIBLE_OUTCOMES)
        known = {
            REPLACE,
            DECLINED_SETTING_OFF,
            DECLINED_MULTI_FILE_GROUP,
            DECLINED_UNKNOWN_QUALITY,
            DECLINED_INCOMPLETE_EVIDENCE,
            DECLINED_ERROR,
            DECLINED_OUTSIDE_LIBRARY,
            DECLINED_SOURCE_CHANGED,
            DECLINED_UNVERIFIED_IDENTITY,
            DECLINED_SIZE_CONTRADICTS_QUALITY,
            DECLINED_NOT_BETTER,
            DECLINED_NO_OWNER,
        }
        assert covered == known, (
            'the outcome constants this test parametrises over (%r) do '
            'not match the known automatic-path vocabulary (%r) -- add a '
            'case above for the difference' % (covered, known)
        )


class TestSkipRecordDoesNotGrowLinearlyWithScanCount:
    """H7 (branch review 2026-08-31) / AC-OPS-3. The "already decided and
    unchanged; skipping the scan" record inside `scan()` is a plain
    `log.info` with no bound at all -- unlike the collision WARNING a few
    hundred lines below it (`main.py:634`), which IS wrapped in
    `log_suppressed`. Measured on the review: 100 scans of one unchanged
    parked group produced 100 records at INFO or above, and 500 scans
    produced 500 -- exactly the one-for-one growth FEAT-012 exists to
    stop, reintroduced by the fix itself.

    `TestBoundedLogHoldsIndependentlyOfMemory` above proves a DIFFERENT
    bound: the collision refusal inside `_moveRenamedFiles`, reached only
    by calling it directly so the memory is bypassed entirely. This class
    drives `scan()` itself, so it exercises the memory-HIT path that test
    deliberately never reaches, and it is left untouched.
    """

    def test_a_hundred_unchanged_scans_do_not_grow_the_skip_record_linearly(
        self, world, caplog,
    ):
        with caplog.at_level(logging.INFO):
            for _ in range(100):
                world['plugin'].scan(base_folder=world['downloads'])

        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the group must have been parked by the first scan and '
            'then answered from memory for the other 99, or this run '
            'proves nothing about the skip record -- the scanner was '
            're-asked instead'
        )

        skip_records = [
            r for r in caplog.records
            if r.levelno >= logging.INFO
            and 'already decided and unchanged' in r.getMessage()
        ]
        assert skip_records, (
            'the skip record never fired at all across 100 scans of one '
            'unchanged, parked group -- this run proves nothing about a '
            'bound because the record under test was never reached'
        )
        assert len(skip_records) <= 4, (
            '100 identical scans of one unchanged parked group produced '
            '%d "already decided and unchanged" records at INFO or '
            'above. AC-OPS-3 requires this record to be bounded the same '
            'way the collision WARNING already is (log_suppressed): a '
            'plain log.info here means the feature that exists to stop '
            'the log being churned still churns it, one record per scan, '
            'forever.' % len(skip_records)
        )


class TestDecisionMemoryStoresAreBounded:
    """M12 (branch review 2026-08-31) / AC-OPS-12, AC-DATA-11. Neither
    in-memory store this feature adds has a cap or an eviction order, and
    `_decision_memory` is keyed on `base_folder`, which `scanView` passes
    straight through from request kwargs with no validation and no
    connection to whether the scan was `targeted` (`main.py:scanView`,
    `:scan`'s `targeted = media_folder is not None or release_download is
    not None` -- `base_folder` alone does not set it). A container designed
    to run for months, fed a caller-supplied key with no cap, grows without
    bound.

    Each iteration below uses its own EMPTY directory as `base_folder`:
    `_folderSignature` only needs the directory to be walkable, and the
    fixture's own `scanner.scan` stub ignores the `folder` argument
    entirely, so this measures the memory's own bound rather than doing
    300x the filesystem work the fixture's single group scenario would
    otherwise cost.
    """

    def test_decision_memory_does_not_grow_one_for_one_with_distinct_base_folders(
        self, world, tmp_path,
    ):
        plugin = world['plugin']

        scan_count = 300
        for i in range(scan_count):
            folder = tmp_path / ('scan-folder-%d' % i)
            folder.mkdir()
            plugin.scan(base_folder=str(folder))

        memory_size = len(getattr(plugin, '_decision_memory', {}) or {})
        assert memory_size < scan_count, (
            '%d scans against %d distinct base_folder values left '
            '_decision_memory holding %d entries -- it grew one-for-one '
            'with an input the API accepts from the caller, with no '
            'stated cap or eviction order (AC-OPS-12)' % (
                scan_count, scan_count, memory_size,
            )
        )

    def test_notified_parked_does_not_grow_one_for_one_with_distinct_media_ids(
        self, world, tmp_path, monkeypatch,
    ):
        plugin = world['plugin']

        park_count = 300
        for i in range(park_count):
            plugin._notifyParked(
                {
                    'media': {
                        '_id': 'media-%d' % i,
                        'info': {'titles': ['Film %d' % i], 'year': 2020},
                    },
                },
                'declined_unverified_identity',
            )

        notified_size = len(getattr(plugin, '_notified_parked', set()) or set())
        assert notified_size < park_count, (
            '%d distinct (media, outcome) parks left _notified_parked '
            'holding %d entries -- it grows one-for-one with the number '
            'of distinct films parked over the container\'s lifetime, '
            'with no stated cap or eviction order (AC-OPS-12)' % (
                park_count, notified_size,
            )
        )


class TestFolderSignatureIsBoundedAgainstAnArbitraryCallerSuppliedFolder:
    """L2 (branch review 2026-08-31, QA/branch-review-2026-08-31-review-queue.md).

    `scanView` passes a caller-supplied `base_folder` straight through to
    `scan()`, which hands it to `_folderSignature` unconditionally --
    before this fix, an authenticated caller asking for `base_folder=/`
    made the container `os.walk` and `os.stat` the entire mounted
    filesystem, one tuple per file, before any other check ran. M12
    already bounds how many DISTINCT folders `_decision_memory` remembers,
    but that says nothing about the cost of walking any ONE of them, so a
    single request against a huge or hostile `base_folder` still needed its
    own bound.

    `FOLDER_SIGNATURE_MAX_ENTRIES` is monkeypatched down to a small number
    so this test creates a few dozen real files rather than tens of
    thousands -- the mechanism under test is "stops walking past the cap",
    which a small cap and a small tree over-cap prove identically to a
    large one.
    """

    def test_a_folder_over_the_cap_fails_open_rather_than_being_fingerprinted(
        self, world, tmp_path, monkeypatch,
    ):
        plugin = world['plugin']
        monkeypatch.setattr(type(plugin), 'FOLDER_SIGNATURE_MAX_ENTRIES', 5, raising=False)

        huge_folder = tmp_path / 'not-the-watch-folder'
        huge_folder.mkdir()
        for i in range(50):
            (huge_folder / ('file-%d.mkv' % i)).write_bytes(b'x')

        assert plugin._folderSignature(str(huge_folder)) is None, (
            'a folder holding more entries than FOLDER_SIGNATURE_MAX_ENTRIES '
            'was still fully fingerprinted -- it must fail open (None) '
            'instead, the same answer an unreadable or vanished folder '
            'already gets, so a caller-supplied base_folder pointed at a '
            'filesystem root cannot make this walk the entire mount'
        )

    def test_the_walk_stops_at_the_cap_rather_than_visiting_every_file_first(
        self, world, tmp_path, monkeypatch,
    ):
        """The previous test alone would still pass a version of this
        method that walks and `stat`s every file, THEN returns None once
        `len(entries)` is checked at the very end -- which is exactly the
        unbounded cost this fix exists to remove. This test proves the
        walk itself is cut short: `os.stat` must be called at most a
        handful of times, never once per file in a much larger tree.
        """
        plugin = world['plugin']
        monkeypatch.setattr(type(plugin), 'FOLDER_SIGNATURE_MAX_ENTRIES', 5, raising=False)

        huge_folder = tmp_path / 'not-the-watch-folder'
        huge_folder.mkdir()
        file_count = 500
        for i in range(file_count):
            (huge_folder / ('file-%d.mkv' % i)).write_bytes(b'x')

        stat_calls = {'count': 0}
        real_stat = os.stat

        def _counting_stat(path, *args, **kwargs):
            if str(path).startswith(str(huge_folder)):
                stat_calls['count'] += 1
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.main.os.stat', _counting_stat,
        )

        result = plugin._folderSignature(str(huge_folder))

        assert result is None
        assert stat_calls['count'] <= plugin.FOLDER_SIGNATURE_MAX_ENTRIES, (
            '_folderSignature called os.stat %d times against a folder '
            'holding %d files and a cap of %d -- the walk must stop AT '
            'the cap, not merely discard the result after visiting every '
            'file, or a caller-supplied base_folder pointed at a huge '
            'tree still pays the full walk cost this fix exists to avoid'
            % (stat_calls['count'], file_count, plugin.FOLDER_SIGNATURE_MAX_ENTRIES)
        )

    def test_a_folder_under_the_cap_is_still_fingerprinted_normally(
        self, world, tmp_path, monkeypatch,
    ):
        """The cap must not turn into a de facto ban on remembering any
        caller-supplied folder -- M12's own test already relies on
        `_folderSignature` working normally for small caller-supplied
        folders, so this pins that a folder comfortably under the cap is
        unaffected."""
        plugin = world['plugin']
        monkeypatch.setattr(type(plugin), 'FOLDER_SIGNATURE_MAX_ENTRIES', 5, raising=False)

        small_folder = tmp_path / 'small-watch-folder'
        small_folder.mkdir()
        (small_folder / 'movie.mkv').write_bytes(b'incoming bytes')

        result = plugin._folderSignature(str(small_folder))
        assert result is not None, (
            'a folder well under FOLDER_SIGNATURE_MAX_ENTRIES was still '
            'refused a fingerprint -- the cap must only refuse an '
            'OVERSIZED folder, never a normal one'
        )
        assert len(result) == 1


class TestSettlingFilesBlockRecording:
    """The P1 review finding: `folder_scanner.py:183-188`
    (`checkFilesChanged`, default `unchanged_for=60`,
    couchpotato/core/plugins/base.py:352) SILENTLY DROPS any group whose
    files are still settling -- it logs at info and `continue`s, so the
    dict `scanner.scan` returns simply omits that group. `_folderSignature`
    walks the same folder on disk and has no such filter, so it DOES
    include the too-new file's size and mtime.

    Consequence: a folder holding one parked collision plus a newly
    completed download gets memorised from a scan that never saw the new
    group. Once the new file's mtime stops changing, the recorded
    signature keeps matching on every later scheduled scan, so the memory
    is trusted forever and the completed film is never processed -- the
    exact production symptom (a downloaded film that never appears) this
    feature exists to fix, reintroduced by the fix itself.

    `folder_scanner.py` cannot be touched (`TestFolderScannerIsUntouched`
    above pins an empty diff against master -- it is shared with
    `manage.updateLibrary`, whose cleanup deletes any 'done' movie absent
    from the scan result), so the renamer must detect "something under
    `scan_folder` is still settling" for itself, entirely from the real
    filesystem, using the same window `checkFilesChanged` uses.

    Currently RED: nothing checks this, so a settling file changes the
    folder signature (forcing a rescan, which is unrelated to this defect)
    but does not stop the resulting decision from being recorded.
    """

    @staticmethod
    def _add_settling_file(scan_folder):
        """A second release landing in the same watch folder while still
        being written. Freshly created, its mtime is "now" -- inside the
        default 60-second settling window by construction, with no need
        to fake the clock. It is never referenced by the stubbed
        `scanner.scan` (the `world` fixture always returns the one
        `group-1` collision regardless of what is actually on disk), which
        is deliberate: this pins the RENAMER's own guard, not
        `folder_scanner`'s real drop behaviour, which is untouchable and
        already covered by the empty-diff guard above."""
        new_release = os.path.join(scan_folder, 'New.Release.2020.1080p-GRP')
        os.makedirs(new_release)
        with open(os.path.join(new_release, 'movie.mkv'), 'wb') as fh:
            fh.write(b'still being written by the download client' * 5)

    def test_a_settling_file_blocks_recording_and_forgets_any_earlier_memory(
        self, world,
    ):
        scan_folder = world['downloads']
        plugin = world['plugin']

        # Baseline: nothing under scan_folder is inside the settling
        # window (the fixture backdates `src` for exactly this reason), so
        # this scan records the decision normally -- the behaviour this
        # fix must not disturb.
        plugin.scan(base_folder=scan_folder)
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must record the decision before this '
            'test can prove anything about a later scan failing to keep '
            'or overwrite it'
        )
        assert scan_folder in plugin._decision_memory, (
            'setup: nothing was recorded after the baseline scan, so this '
            'test cannot isolate what a settling file does to that memory'
        )

        self._add_settling_file(scan_folder)

        plugin.scan(base_folder=scan_folder)
        assert world['scan_calls']['scanner.scan'] == 2, (
            'setup: adding a file changes the folder signature, so this '
            'scan must ask the scanner again regardless of the settling '
            'guard -- this assertion is not what the test is about'
        )
        assert scan_folder not in plugin._decision_memory, (
            'a folder holding a file still inside the settling window was '
            'recorded as decided. The scan that produced this answer '
            'could not have seen the group folder_scanner is still '
            'silently dropping for that file, so the decision must not be '
            'recorded, and any earlier memory for this folder must be '
            'forgotten rather than left standing -- it no longer '
            'describes what is actually on disk'
        )

        # Nothing about the folder changes between this scan and the last
        # one (the new file's mtime has not aged past the window in the
        # handful of milliseconds this test takes), so if the guard above
        # is not load-bearing, this third scan would wrongly be answered
        # from a memory entry the previous scan should not have written.
        plugin.scan(base_folder=scan_folder)
        assert world['scan_calls']['scanner.scan'] == 3, (
            'fireEvent("scanner.scan", ...) was not called a third time '
            'for an unchanged folder that still holds a file inside the '
            'settling window -- a decision was recorded for it despite '
            'the settling file, so this scan trusted a memory built from '
            'an incomplete view of the folder'
        )

    def test_a_folder_with_every_file_outside_the_window_is_still_recorded(
        self, world,
    ):
        """The settling-window guard must only refuse to record while
        something is actually settling -- it must not be satisfied by
        simply never remembering anything, which would silently disable
        the whole feature this branch exists to add."""
        scan_folder = world['downloads']
        plugin = world['plugin']

        plugin.scan(base_folder=scan_folder)
        assert world['scan_calls']['scanner.scan'] == 1, (
            'setup: the first scan must run before this test can prove '
            'anything about what it recorded'
        )
        assert scan_folder in plugin._decision_memory, (
            'a folder with every file safely outside the settling window '
            'was not recorded at all -- the settling-window guard must '
            'not disable memoisation for a folder where nothing is '
            'settling, only for the specific case where something is'
        )

        plugin.scan(base_folder=scan_folder)
        assert world['scan_calls']['scanner.scan'] == 1, (
            'a second, completely unchanged scan of a folder with no '
            'settling files re-asked the scanner -- the settling-window '
            'guard must not fire when nothing under scan_folder is '
            'actually settling'
        )
