import time
from couchpotato.api import addApiView, addNonBlockApiView, api, api_nonblock, run_handler


def test_add_api_view_registers_and_calls():
    calls = {}

    def handler(example=None, _request=None):
        calls['args'] = {'example': example, '_request': _request}
        return {'success': True, 'value': example}

    route = 'test.echo'
    addApiView(route, handler)

    results = {}

    def cb(res, r):
        results['res'] = res
        results['route'] = r

    # Directly invoke the async wrapper (spawns a thread)
    run_handler(route, {'example': 'x', '_request': None}, callback=cb)

    # Wait briefly for the thread
    for _ in range(50):
        if 'res' in results:
            break
        time.sleep(0.01)

    assert route in api
    assert results['route'] == route
    assert results['res'] == {'success': True, 'value': 'x'}


def test_add_nonblock_api_view_registers():
    def start(cb, last_id=None):
        pass

    def stop(cb):
        pass

    route = 'stream.updates'
    addNonBlockApiView(route, (start, stop), docs='Streaming updates')
    assert route in api_nonblock

