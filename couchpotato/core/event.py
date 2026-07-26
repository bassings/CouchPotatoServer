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
    # ^ the release-date lookup behind the ETA gate (BUG-017). Worked around by
    #   deriving the date from info['released'] instead of adding a handler.
    'cp.source_url',
    # ^ SourceUpdater.doUpdate() would raise AttributeError on the None this
    #   returns. Unreachable in practice -- that updater is selected only for a
    #   downloaded-source install (not Docker, not a git checkout), neither of
    #   which this project ships. Pre-existing; fix or delete that path.
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
# name for the process lifetime, not one per call. Plain set: adds and
# membership tests are atomic under the GIL, and a duplicated warning in a
# race is harmless.
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
            _warned_unhandled.add(name)
            log.warning('Event "%s" was fired but nothing handles it; it did '
                        'nothing. Either register a handler or add the name to '
                        'OPTIONAL_EVENTS in couchpotato/core/event.py.', name)
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
