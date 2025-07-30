from __future__ import absolute_import, division, print_function, unicode_literals
import threading
import traceback

from axl.axel import Event
from couchpotato.core.helpers.variable import mergeDicts, natsortKey
from couchpotato.core.logger import CPLog


log = CPLog(__name__)
events = {}


def runHandler(name, handler, *args, **kwargs):
    try:
        return handler(*args, **kwargs)
    except Exception as e:
        from couchpotato.environment import Env
        # Log the error with more detail for debugging
        error_msg = str(e)
        full_trace = traceback.format_exc()
        env_info = Env.all() if not Env.get('dev') else ''
        log.error('Error in event "%s", that wasn\'t caught: %s %s %s', (name, error_msg, full_trace, env_info))
        # Also print to console for debugging in CI
        print(f"EVENT ERROR: {name} - {error_msg}")
        print(f"FULL TRACEBACK: {full_trace}")
        raise e  # Re-raise to prevent silent failures


def addEvent(name, handler, priority = 100):

    if not events.get(name):
        events[name] = []

    def createHandle(*args, **kwargs):

        h = None
        try:
            # Open handler
            has_parent = hasattr(handler, 'im_self')
            parent = None
            if has_parent:
                parent = handler.__self__
                bc = hasattr(parent, 'beforeCall')
                if bc: parent.beforeCall(handler)

            # Main event
            h = runHandler(name, handler, *args, **kwargs)

            # Close handler
            if parent and has_parent:
                ac = hasattr(parent, 'afterCall')
                if ac: parent.afterCall(handler)
        except:
            log.error('Failed creating handler %s %s: %s', (name, handler, traceback.format_exc()))

        return h

    events[name].append({
        'handler': createHandle,
        'priority': priority,
    })


def fireEvent(name, *args, **kwargs):
    if name not in events: 
        print(f"DEBUG: Event {name} not in events, returning []")
        return []

    print(f"DEBUG: Event {name} found, has {len(events[name])} handlers")
    #log.debug('Firing event %s', name)
    try:

        options = {
            'is_after_event': False,  # Fire after event
            'on_complete': False,  # onComplete event
            'single': False,  # Return single handler
            'merge': False,  # Merge items
            'in_order': False,  # Fire them in specific order, waits for the other to finish
        }

        # Check if no event handlers exist
        if name not in events or len(events[name]) == 0:
            if options.get('single'):
                return []
            else:
                return None

        # Do options
        for x in options:
            try:
                val = kwargs[x]
                del kwargs[x]
                options[x] = val
            except: pass

        if len(events[name]) == 1:

            single = None
            try:
                single = events[name][0]['handler'](*args, **kwargs)
            except:
                log.error('Failed running single event: %s', traceback.format_exc())

            # Don't load thread for single event
            result = {
                'single': (single is not None, single),
            }

        else:

            e = Event(name = name, threads = 10, exc_info = True, traceback = True)

            for event in events[name]:
                e.handle(event['handler'], priority = event['priority'])

            # Make sure only 1 event is fired at a time when order is wanted
            kwargs['event_order_lock'] = threading.RLock() if options['in_order'] or options['single'] else None
            kwargs['event_return_on_result'] = options['single']

            # Fire
            result = e(*args, **kwargs)

        result_keys = list(result.keys())  # Convert to list for Python 3
        result_keys.sort(key = natsortKey)

        if options['single'] and not options['merge']:
            results = None

            # Loop over results, stop when first not None result is found.
            for r_key in result_keys:
                r = result[r_key]
                if r[0] is True and r[1] is not None:
                    results = r[1]
                    break
                elif r[1]:
                    errorHandler(r[1])
                else:
                    log.debug('Assume disabled eventhandler for: %s', name)
            
            # Return empty list if no results found for single events
            if results is None:
                results = []

        else:
            results = []
            for r_key in result_keys:
                r = result[r_key]
                if r[0] == True and r[1]:
                    results.append(r[1])
                elif r[1]:
                    errorHandler(r[1])

            # Merge
            if options['merge'] and len(results) > 0:

                # Dict
                if isinstance(results[0], dict):
                    results.reverse()

                    merged = {}
                    for result_item in results:
                        merged = mergeDicts(merged, result_item, prepend_list = True)

                    results = merged
                # Lists
                elif isinstance(results[0], list):
                    merged = []
                    for result_item in results:
                        if result_item not in merged:
                            merged += result_item

                    results = merged

        modified_results = fireEvent('result.modify.%s' % name, results, single = True)
        if modified_results:
            log.debug('Return modified results for %s', name)
            results = modified_results

        if not options['is_after_event']:
            fireEvent('%s.after' % name, is_after_event = True)

        if options['on_complete']:
            options['on_complete']()

        return results
    except Exception:
        log.error('%s: %s', (name, traceback.format_exc()))


def fireEventAsync(*args, **kwargs):
    try:
        t = threading.Thread(target = fireEvent, args = args, kwargs = kwargs)
        t.setDaemon(True)
        t.start()
        return True
    except Exception as e:
        log.error('%s: %s', (args[0], e))


def errorHandler(error):
    etype, value, tb = error
    log.error(''.join(traceback.format_exception(etype, value, tb)))


def getEvent(name):
    return events[name]
