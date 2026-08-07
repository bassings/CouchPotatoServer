#!/usr/bin/env python3
"""Render every state of `/login/` to disk, through the REAL routes.

Why this exists: `login_get` redirects anyone `get_current_user` accepts, and
with `auth_required` off that is everybody -- so on the E2E instances (which
`scripts/seed_e2e_data.py` seeds with no password) the login page is
unreachable by navigation. AC-QA-27, the E2E that runs with authentication
genuinely on, is a later tranche.

Rather than skip the browser checks until then -- axe, the real bounding box of
the "Remember me" target, and reflow at 320 px -- this drives the actual
FastAPI routes with `TestClient` and writes what they return. The HTML is
byte-for-byte what the route produces; only the transport differs, and
`tests/e2e/login-page.a11y.spec.ts` serves it back at the instance's own
`/login/` URL so the relative `/static/` assets resolve against the live
server.

What that does NOT prove, stated so nobody assumes otherwise: that the route
is reachable at all with authentication on. That is AC-QA-27's job.

Usage:  render_login_states.py <output-dir>
Writes: <output-dir>/<state>.html for each state in STATES, and nothing else.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'libs'))

from fastapi.testclient import TestClient  # noqa: E402

from couchpotato.core.helpers.variable import hash_password, md5  # noqa: E402
from couchpotato.environment import Env  # noqa: E402

API_KEY = 'e2erenderkey' + '0' * 20
PASSWORD = 'hunter2'

#: name -> (method, path, form data or None)
STATES = {
    'first_visit': ('GET', '/login/', None),
    'signed_out': ('GET', '/login/?reason=signed_out', None),
    'session_ended': ('GET', '/login/?reason=session_ended', None),
    'rejected': ('POST', '/login/', {'username': 'admin', 'password': 'wrong'}),
    'empty_password': ('POST', '/login/', {'username': 'admin', 'password': ''}),
}


def main(out_dir: str) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    settings = {
        'username': 'admin',
        'password': hash_password(md5(PASSWORD)),
        'api_key': API_KEY,
        'auth_required': 1,
        'rate_limit_max': 0,
        'cors_origins': '',
        'ssl_cert': '',
        'ssl_key': '',
    }

    def setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            settings[key] = kwargs['value']
            return
        return settings.get(key, kwargs.get('default', ''))

    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(REPO_ROOT))
    Env.set('data_dir', out_dir)
    Env.set('dev', False)
    Env.setting = staticmethod(setting)

    from couchpotato import create_app
    client = TestClient(create_app(API_KEY, '/'), follow_redirects=False)

    written = {}
    for name, (method, path, data) in STATES.items():
        response = client.request(method, path, data=data)
        if response.status_code != 200:
            raise SystemExit(
                '%s %s returned %d, not the login page. The states this spec '
                'checks are produced by the real routes, so a redirect here '
                'means the route changed and the spec is measuring nothing.'
                % (method, path, response.status_code))
        target = out / ('%s.html' % name)
        target.write_text(response.text, encoding='utf-8')
        written[name] = str(target)

    print(json.dumps(written))
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
