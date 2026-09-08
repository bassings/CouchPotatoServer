import threading
import traceback

from blinker import Namespace
from couchpotato.core.helpers.variable import mergeDicts, natsortKey
from couchpotato.core.logger import CPLog


log = CPLog(__name__)

# Registry: name -> list of {handler, priority} (kept sorted by priority)
events = {}
_events_lock = threading.Lock()

# Event names that are deliberately fired with no handler in this tree.
#
# fireEvent() returns [] for an unhandled name, which is indistinguishable from
# "handled, found nothing" -- so a mis-wired event does not fail, the feature
# behind it just quietly does nothing. `movie.info.release_date` sat like that
# for the life of the fork and left the release-date gate with no dates at all
# (BUG-017). Everything below is either a deliberate extension point or a
# known gap recorded here; anything else warns once at runtime and fails
# tests/unit/test_event_wiring.py.
OPTIONAL_EVENTS = frozenset({
    # Extension points with no in-tree implementation. Unhandled is harmless:
    # each caller degrades to a default rather than depending on a result.
    'cp.messages',       # broadcast messages from the (defunct) couchpotato.com
    'release.validate',  # optional custom release-name validation; contributes 0 to the score
    # Known gaps, not extension points. Listed so the audit stays green, NOT
    # because unhandled is correct here:
    'movie.info.release_date',
    # ^ the release-date lookup behind the ETA gate (BUG-017). Worked around
    #   rather than handled: MovieBase.updateReleaseDate() falls back to
    #   releaseDatesFromInfo() (media/movie/_base/main.py), which derives a
    #   theatrical date from the `released` string the info provider already
    #   stores. Landed in #201 -- before that the gate had no dates at all.
    'cp.source_url',
    # ^ SourceUpdater.doUpdate() calls .get() on what this returns, so every
    #   update attempt on a source install dies with
    #   `AttributeError: 'list' object has no attribute 'get'` -- the
    #   early-return below hands back [] before `single` is ever read, so it
    #   is an empty list, not None. This IS reachable:
    #   release-to-prod.yml attaches .tar.gz/.zip source archives to each
    #   stable release, and running one outside Docker gives no .git, which is
    #   exactly how SourceUpdater gets selected. Pre-existing and out of scope
    #   here; recorded in docs/technical-debt.md.
})

#: Names that ARE registered and that nothing dispatches. Empty until each
#: one has been adjudicated, because a list that starts populated is a list
#: nobody reads.
#:
#: Every entry carries why it is unreachable and what would make the decision
#: expire. `test_unfired_allowlist_has_no_stale_entries` fails in BOTH
#: directions: an entry that gains a dispatch, or that stops being registered,
#: breaks the build rather than sitting here describing nothing.
UNFIRED_EVENTS = frozenset({
    # ---------------------------------------------------------------
    # Reachable another way. The FEATURE works; only the addEvent() is
    # unused, so deleting the registration is safe and deleting the
    # handler is not. Expires if the other route goes away.
    # ---------------------------------------------------------------
    'media.mark_watched',
    # ^ markWatched is served as the API view '<type>.watched', registered
    #   per media type in addSingleWatchViews() (media/_base/media/main.py:786).
    'media.mark_unwatched',
    # ^ markUnwatched is served as 'media.unwatched' (main.py:95) and as
    #   '<type>.unwatched' (main.py:787).
    'media.watch_history',
    # ^ watchHistory is served as 'media.watch_history' (main.py:101) and as
    #   '<type>.watch_history' (main.py:788).
    'movie.restore_to_wanted',
    # ^ restoreToWantedView is an API view (movie/_base/main.py:126); the
    #   event registration beside it is a second door nobody opens.
    'category.all',
    # ^ Category.all is served as the API view 'category.list'
    #   (plugins/category/main.py:27), whose allView() calls self.all()
    #   directly at :41. The settings UI fetches /category.list/ on every
    #   load (partials/settings/scripts.html, three call sites). This entry
    #   was in the unreachable bucket below, which was wrong in the dangerous
    #   direction: that header reads as a licence to delete a function the
    #   category editor depends on.
    'renamer.check_snatched',
    # ^ the scheduler is handed the CALLABLE, not the name:
    #   fireEvent('schedule.interval', 'renamer.check_snatched',
    #             self.checkSnatched, ...) at renamer/main.py:235. The string
    #   is a schedule id, not a dispatch. checkSnatched does run.

    # ---------------------------------------------------------------
    # Genuinely unreachable: the handler cannot run at all. Listed so this
    # audit stays green and the decisions stay visible, NOT because any of
    # it is correct. Each expires the moment something fires it, and
    # test_unfired_allowlist_has_no_stale_entries fails then.
    # ---------------------------------------------------------------
    'renamer.before',
    # ^ ONE handler: subtitle search (plugins/subtitle.py:28). Subtitles are
    #   the most user-visible casualty of the dead chain, and an earlier
    #   version of this comment left them out entirely while attributing six
    #   handlers here that all belong to renamer.after below.
    'renamer.after',
    # ^ SIX handlers: trailers (plugins/trailer.py:17), metadata
    #   (movie/providers/metadata/base.py:22), Plex (notifications/plex/
    #   main.py:24), Synology (synoindex.py:22), custom scripts (script.py:24)
    #   and manage (manage.py:43).
    #
    #   THE reason this guard exists, for both. Nothing fires bare `renamer`,
    #   so the dispatcher never derives either hook, and all seven handlers
    #   have been silently dead since the FastAPI migration with correct
    #   plugin code behind them. See specs/RENAMER-EVENT-CHAIN.md; expires
    #   when the rename flow is ported.
    'app.test',
    # ^ Four handlers, and one is load-bearing: doSubfolderTest
    #   (plugins/file.py:39) is a 12-case truth table for isSubFolder, the
    #   function deciding whether one path sits inside another, which the
    #   renamer depends on. It has not run since the FastAPI migration.
    #   The other three are provider self-tests (quality/main.py:76,
    #   userscript/main.py:23, thepiratebay.py:44).
    'userscript.get_excludes',
    'userscript.get_includes',
    'userscript.get_version',
    # ^ Dead by design, not by accident: the userscript embed was retired in
    #   UI-CLEANUP-02 (specs/UI-CLEANUP-02-retire-userscript-embed.md), which
    #   removed the only caller. These three are the residue. Safe to delete
    #   with their handlers; kept for now because that is a separate change.
    'library.root',
    'library.title',
    'library.types',
    # ^ media/_base/library/main.py:13,17 and library/base.py:10. The library
    #   layer these belong to was largely bypassed in the FastAPI migration.
    'manage.diskspace',
    # ^ plugins/manage.py:37. getDiskSpace has no other caller, so the free
    #   space figure it computes reaches nobody.
    'media.with_identifiers',
    # ^ media/_base/media/main.py:116.
    'quality.order',
    # ^ plugins/quality/main.py:56. getOrder is unreachable; profile ordering
    #   is read from the profile records directly.
    'scanner.remove_cptag',
    # ^ plugins/scanner/api.py:10. removeCPTag IS called internally, at
    #   folder_scanner.py:723, so only the event door is unused.
    'scanner.partnumber',
    # ^ plugins/scanner/api.py:13, and NOT the same case. getPartNumber
    #   (folder_scanner.py:754) has no production caller anywhere: not this
    #   event, not a method call, only its own unit test. So multi-part
    #   detection does not run during a real scan, and a library with
    #   Movie.cd1.mkv / Movie.cd2.mkv gets no part numbering. An earlier
    #   version of this comment lumped it in with remove_cptag and said the
    #   behaviour was not missing. It is.
})

# Per-dispatch and per-setting hooks. These are opt-in by design and are
# unhandled for nearly every name they are generated for, so warning about
# them would drown the signal:
#
#   result.modify.<name>, <name>.after  -- fireEvent() derives BOTH from EVERY
#       dispatch (see the calls at the end of this module), so warning would
#       mean two useless lines per event name in the system.
#   setting.save.<section>.<option>     -- Settings.save() fires one per saved
#       option; only a handful of options have a handler, so a single settings
#       save would emit a warning per option without one.
OPTIONAL_EVENT_PREFIXES = ('result.modify.', 'setting.save.')
OPTIONAL_EVENT_SUFFIXES = ('.after',)


def _isOptionalEvent(name):
    return (name in OPTIONAL_EVENTS
            or name.startswith(OPTIONAL_EVENT_PREFIXES)
            or name.endswith(OPTIONAL_EVENT_SUFFIXES))

# Names already reported by fireEvent(); it is hot, so this is one line per
# name for the process lifetime, not one per call. Plain set rather than a
# lock: add and membership tests are atomic under CPython's GIL, and the worst
# outcome of a race is a duplicated warning line. (On a future free-threaded
# build that atomicity no longer holds -- the consequence stays a duplicate
# log line, not corruption, so this is still a fine trade there.)
#
# Set to True once the cap is reached, so that is announced exactly once.
# Going quiet without saying so would be the same silent failure this whole
# mechanism exists to prevent.
_warned_cache_full = [False]

# BOUNDED, because event names are not all internal: Search.search() fires
# `'%s.search' % media_type` where `types` comes straight off the API request,
# so a caller can mint unlimited distinct names. An unbounded set would grow
# for the life of the process on arbitrary input -- a slow memory leak plus a
# log line each. Past the cap we stop recording and stop logging; the cap is
# far above the number of real event names in the app, so genuine gaps are
# still reported.
MAX_WARNED_UNHANDLED = 500
_warned_unhandled = set()

# blinker namespace (not used for dispatch, but available for introspection)
_ns = Namespace()


def runHandler(name, handler, *args, **kwargs):
    try:
        return handler(*args, **kwargs)
    except Exception as e:
        from couchpotato.environment import Env
        error_msg = str(e)
        full_trace = traceback.format_exc()
        env_info = Env.all() if not Env.get('dev') else ''
        log.error('Error in event "%s", that wasn\'t caught: %s %s %s', name, error_msg, full_trace, env_info)
        print(f"EVENT ERROR: {name} - {error_msg}")
        print(f"FULL TRACEBACK: {full_trace}")
        raise e


def addEvent(name, handler, priority=100):
    def createHandle(*args, **kwargs):
        h = None
        try:
            # `__self__` is the Python 3 attribute holding a bound method's
            # owning instance (the Python 2 name was `im_self`, which is
            # always absent on Python 3 -- see REG-003 item 6). Detecting
            # it correctly is what lets beforeCall/afterCall populate
            # Plugin._running, which Core.initShutdown's wait loop depends
            # on to know when it's safe to shut down.
            has_parent = hasattr(handler, '__self__')
            parent = None
            if has_parent:
                parent = handler.__self__
                bc = hasattr(parent, 'beforeCall')
                if bc:
                    parent.beforeCall(handler)

            # afterCall MUST run even if the handler raises -- runHandler
            # re-raises handler exceptions by design, and beforeCall has
            # already marked `<Class>.<method>` running. Without the finally,
            # a raised handler would leak that entry in Plugin._running
            # forever, so `fireEvent('plugin.running', merge=True)` would
            # never drain and Core.initShutdown's wait loop would hang on its
            # hard 30s timeout for the rest of the process life. PR #151.
            try:
                h = runHandler(name, handler, *args, **kwargs)
            finally:
                if parent and has_parent:
                    ac = hasattr(parent, 'afterCall')
                    if ac:
                        parent.afterCall(handler)
        except Exception:
            log.error('Failed creating handler %s %s: %s', name, handler, traceback.format_exc())

        return h

    entry = {
        'handler': createHandle,
        'priority': priority,
    }

    with _events_lock:
        if name not in events:
            events[name] = []
        # Insert in sorted order by priority
        handler_list = events[name]
        handler_list.append(entry)
        handler_list.sort(key=lambda h: h['priority'])


def removeEvent(name):
    """Remove all handlers for an event name."""
    with _events_lock:
        events.pop(name, None)


def fireEvent(name, *args, **kwargs):
    # Take a snapshot of handlers under the lock
    with _events_lock:
        handlers = list(events.get(name, []))

    if not handlers:
        # Say so once. Silence here is how a dead event hides: callers cannot
        # tell "nothing handled this" from "handled, no result". Static
        # analysis covers literal names (test_event_wiring.py); this also
        # catches the templated ones ('%s.snatched' % media_type) that only
        # become concrete here.
        if not _isOptionalEvent(name) and name not in _warned_unhandled:
            if len(_warned_unhandled) < MAX_WARNED_UNHANDLED:
                _warned_unhandled.add(name)
                # %r and a length cap: `name` can be caller-derived (the
                # search API's `types` param becomes '<type>.search'), and
                # this is the first place that value reaches the log. repr()
                # escapes newlines, so a crafted name cannot forge log lines.
                log.warning('Event %r was fired but nothing handles it; it '
                            'did nothing. Either register a handler or add the '
                            'name to OPTIONAL_EVENTS in '
                            'couchpotato/core/event.py.', name[:200])
            elif not _warned_cache_full[0]:
                _warned_cache_full[0] = True
                log.warning('Reached %d distinct unhandled event names and am '
                            'no longer reporting them. Event names can be '
                            'caller-derived, so this is usually a client '
                            'sending arbitrary values rather than %d real '
                            'bugs -- but genuine unhandled events will now go '
                            'unreported until restart.',
                            MAX_WARNED_UNHANDLED, MAX_WARNED_UNHANDLED)
        return []

    try:
        options = {
            'is_after_event': False,
            'on_complete': False,
            'single': False,
            'merge': False,
            'in_order': False,
        }

        # Extract options from kwargs
        for x in list(options.keys()):
            if x in kwargs:
                options[x] = kwargs.pop(x)

        if not handlers:
            return [] if options['single'] else None

        # Handlers already sorted at registration time; no sort needed

        # Execute handlers
        results = []
        for entry in handlers:
            try:
                result = entry['handler'](*args, **kwargs)

                if result is not None:
                    results.append(result)

                # For single mode, stop at first non-None result
                if options['single'] and not options['merge'] and result is not None:
                    break
            except Exception:
                log.error('Failed running event handler: %s', traceback.format_exc())

        # Process results based on mode
        if options['single'] and not options['merge']:
            final = results[0] if results else []
        elif options['merge'] and results:
            if isinstance(results[0], dict):
                results.reverse()
                merged = {}
                for item in results:
                    merged = mergeDicts(merged, item, prepend_list=True)
                final = merged
            elif isinstance(results[0], list):
                merged = []
                for item in results:
                    if item not in merged:
                        merged += item
                final = merged
            else:
                final = results
        else:
            final = results

        # Result modifier
        modified = fireEvent('result.modify.%s' % name, final, single=True)
        if modified:
            log.debug('Return modified results for %s', name)
            final = modified

        if not options['is_after_event']:
            fireEvent('%s.after' % name, is_after_event=True)

        if options['on_complete']:
            options['on_complete']()

        return final
    except Exception:
        log.error('%s: %s', name, traceback.format_exc())
        # `[]`, not an implicit None. This function's contract is "a list of
        # handler results" -- the no-handler path above already returns `[]` --
        # and callers index it directly (`searcher.py`'s
        # `[x['_id'] for x in fireEvent('media.with_status', ...)]`). Falling
        # out of this handler with None turns a logged, recovered dispatch
        # error into a TypeError in the caller, several frames from the cause.
        # T3.4.
        return []


def fireEventAsync(*args, **kwargs):
    try:
        t = threading.Thread(target=fireEvent, args=args, kwargs=kwargs)
        t.daemon = True
        t.start()
        return True
    except Exception as e:
        log.error('%s: %s', args[0], e)


def errorHandler(error):
    etype, value, tb = error
    log.error(''.join(traceback.format_exception(etype, value, tb)))


def getEvent(name):
    with _events_lock:
        return list(events.get(name, []))
