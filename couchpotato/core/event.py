import threading
import traceback

from blinker import Namespace
from couchpotato.core.helpers.variable import mergeDicts, natsortKey
from couchpotato.core.logger import CPLog


log = CPLog(__name__)

# Registry: name -> list of {handler, priority} (kept sorted by priority)
events = {}
_events_lock = threading.Lock()

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
            has_parent = hasattr(handler, 'im_self')
            parent = None
            if has_parent:
                parent = handler.__self__
                bc = hasattr(parent, 'beforeCall')
                if bc:
                    parent.beforeCall(handler)

            h = runHandler(name, handler, *args, **kwargs)

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
