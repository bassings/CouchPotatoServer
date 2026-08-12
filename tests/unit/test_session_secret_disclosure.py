"""The signing secret is not handed to an `api_key` holder. AC-SEC-40.

Tranche A of this PR created the hole this file closes, and it is worth being
precise about why it is worse than the defect it came from.

`ensure_session_secret` writes one `property` row whose `value` IS the HMAC key
every browser session is signed with. `db.all('id')` returns that row verbatim,
and `Database.listDocuments` iterates exactly `db.all('id')` -- so
`GET /api/<key>/database.list_documents` returned the signing secret in
cleartext to anyone holding the `api_key`. The `api_key` is embedded in every
rendered page and handed to the userscript and to every third-party script, so
"anyone holding it" is a wide set.

Before tranche A there was nothing there to leak. And unlike the `api_key`, the
secret **survives every `api_key` rotation**: an operator who suspects a leak
and rotates the key would still be running with a session-forging key in the
attacker's hands, with nothing in the UI to tell them.

The same three API views can also DESTROY it. `database.document.delete` on
that row locks every browser out until the process restarts, and
`database.document.update` can overwrite it (revoking every session) or plant a
SECOND row with the same identifier, after which the lookup returns whichever
SQLite hands back first and sessions verify or not at random.

Driven end to end through the real `/api/{route:path}` route and the real
`callApiHandler`, not by calling `Database.listDocuments` directly: the route
is what an `api_key` holder actually reaches, and a guard that lives only in
the function is one dispatch change away from being bypassed.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from couchpotato import SESSION_SECRET_PROPERTY, ensure_session_secret
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

#: 32 characters, the length a real `api_key` has, so a substring search for it
#: cannot false-negative on a short one -- but visibly fake, because a
#: realistic random value here is a gitleaks finding in the repository forever.
API_KEY = 'notarealapikey' + '0' * 18
REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeSettings(Settings):
    """The REAL `getProperty` / `setProperty` over an in-memory config.

    Subclassed rather than stubbed, for the reason
    `test_session_secret_store.py` gives: the round trip under test is the
    production one. `Settings.__init__` registers API views and events, which a
    unit test must not do, so it is replaced.
    """

    def __init__(self, data):
        from couchpotato.core.logger import CPLog
        self.data = data
        self.log = CPLog('test-settings')
        self.file = None
        self.p = None
        self.directories_delimiter = '::'

    def get(self, attr, default=None, section='core', type=None):
        return self.data.get(attr, default)

    def set(self, section, option, value):
        self.data[option] = value

    def addSection(self, section):
        pass

    def save(self):
        pass


@pytest.fixture
def env(tmp_path):
    """A real adapter, a real `Database` plugin, and the real API registry."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    db = SQLiteAdapter()
    db.create(str(tmp_path / 'db'))

    settings = FakeSettings({
        'username': 'admin',
        'password': 'stored-hash',
        'api_key': API_KEY,
        'auth_required': 1,
        'rate_limit_max': 0,
        'cors_origins': '',
    })

    Env.set('db', db)
    Env.set('settings', settings)
    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(REPO_ROOT))
    Env.set('data_dir', str(tmp_path))
    Env.set('dev', False)

    # The API views are the subject; the event registrations are not, and
    # leaking them into the process-wide registry would follow this file into
    # every other test in the run.
    with patch('couchpotato.core.database.addEvent'):
        from couchpotato.core.database import Database
        Database()

    secret = ensure_session_secret(db)

    from couchpotato import create_app
    app = create_app(API_KEY, '/')

    yield type('EnvHandle', (), {
        'db': db, 'settings': settings, 'secret': secret,
        'client': TestClient(app, follow_redirects=False),
    })

    db.close()
    api.clear()
    api.update(old_api)
    api_locks.clear()
    api_locks.update(old_locks)
    api_nonblock.clear()
    api_nonblock.update(old_nonblock)
    api_docs.clear()
    api_docs.update(old_docs)
    api_docs_missing.clear()
    api_docs_missing.extend(old_missing)


def secret_rows(db):
    """Every property row for the secret, counted via `_query_index`.

    `get()` returns the first match and hides duplicates, which is one of the
    outcomes under test here.
    """
    return [row for row in db._query_index('property', key=SESSION_SECRET_PROPERTY)
            if row.get('identifier') == SESSION_SECRET_PROPERTY]


def api_get(env, route, **params):
    response = env.client.get('/api/%s/%s' % (API_KEY, route), params=params)
    assert response.status_code == 200, response.text
    return response


class TestTheSecretIsNotListed:
    """AC-SEC-40, the disclosure half."""

    def test_list_documents_does_not_return_the_secret(self, env):
        response = api_get(env, 'database.list_documents')

        assert env.secret not in response.text, (
            'GET /api/<key>/database.list_documents returned the session '
            'signing secret in cleartext. Every api_key holder can now forge '
            'a session cookie for any lifetime, and rotating the api_key does '
            'not take that away.'
        )

    def test_filtering_to_properties_does_not_return_the_secret_either(self, env):
        """`show=property` is the shape someone LOOKING for it would send."""
        response = api_get(env, 'database.list_documents', show='property')

        assert env.secret not in response.text

    def test_the_other_property_rows_are_still_listed(self, env):
        """The guard must not be a blanket refusal to list properties.

        A redaction that swallowed the whole document type would pass the two
        tests above while making `database.list_documents` useless, and nobody
        would notice until they needed it.
        """
        env.settings.setProperty('last_backup', '2026-08-07')

        body = api_get(env, 'database.list_documents').json()
        identifiers = {doc.get('identifier') for doc in body.get('property', [])}

        assert 'last_backup' in identifiers
        assert '2026-08-07' in json.dumps(body)

    def test_the_secret_row_is_still_visible_as_a_row(self, env):
        """Redacted, not hidden.

        An operator debugging a login problem needs to see that the row EXISTS;
        what they must not see is its value. Hiding it entirely also means a
        second, duplicated secret row -- the failure `_write_session_secret`
        exists to prevent -- would be invisible from the API.
        """
        body = api_get(env, 'database.list_documents').json()
        identifiers = [doc.get('identifier') for doc in body.get('property', [])]

        assert identifiers.count(SESSION_SECRET_PROPERTY) == 1


class TestTheSecretCannotBeWrittenThroughTheApi:
    """AC-SEC-40, the integrity half."""

    def test_document_update_refuses_to_overwrite_the_secret_row(self, env):
        row_id = secret_rows(env.db)[0]['_id']
        document = json.dumps({
            '_id': row_id,
            '_t': 'property',
            'identifier': SESSION_SECRET_PROPERTY,
            'value': 'ff' * 32,
        })

        body = api_get(env, 'database.document.update', document=document).json()

        assert body['success'] is False, (
            'database.document.update overwrote the session signing secret. '
            'That silently ends every session on every device, and an attacker '
            'who chooses the value can then forge cookies at will.'
        )
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == env.secret

    def test_document_update_refuses_to_overwrite_the_secret_row_with_anything(self, env):
        """The payload does not have to CLAIM the identifier to destroy it.

        Checking only what the caller submitted leaves the whole row writable
        by `_id`: overwrite it with an unrelated document and the secret is
        gone, every session is refused, and no login can recover it because the
        request path never creates one (D2). A mutation that dropped the
        stored-row half of the guard survived until this test existed.
        """
        stored = env.db.get('id', secret_rows(env.db)[0]['_id'])
        document = json.dumps({
            '_id': stored['_id'],
            '_rev': stored['_rev'],
            '_t': 'property',
            'identifier': 'something_harmless',
            'value': 'anything at all',
        })

        body = api_get(env, 'database.document.update', document=document).json()

        assert body['success'] is False
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == env.secret, (
            'the secret row was overwritten by a document that never mentioned '
            'the session_secret identifier'
        )

    def test_an_update_is_refused_when_the_store_cannot_say_what_it_would_overwrite(self, env, monkeypatch):
        """Fails CLOSED, which is the whole reason the read is there.

        `KeyError` means "no such document", which is the ordinary
        create-through-update case and stays allowed. Anything else means we
        could not establish what we are about to overwrite -- and guessing
        "probably not the secret" costs every live session on the one install
        where it is wrong.
        """
        from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

        target = secret_rows(env.db)[0]['_id']
        real_get = SQLiteAdapter.get

        def flaky(self, index_name, key, with_doc=False):
            if index_name == 'id' and key == target:
                raise RuntimeError('database is locked')
            return real_get(self, index_name, key, with_doc=with_doc)

        monkeypatch.setattr(SQLiteAdapter, 'get', flaky)
        # No `_rev`, so the adapter falls back to an unconditional
        # last-writer-wins UPDATE: if the guard lets this through, the secret
        # row simply becomes a media document.
        body = api_get(env, 'database.document.update',
                       document=json.dumps({'_id': target, '_t': 'media'})).json()
        monkeypatch.undo()

        assert body['success'] is False
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == env.secret

    def test_document_update_refuses_to_plant_a_second_secret_row(self, env):
        """A second row with the same identifier is the worst outcome of all.

        `_session_secret_row` returns the first match SQLite hands back, so
        from that point the install signs with one value and verifies against
        whichever the query happens to return -- sessions work or not at
        random, and no log line says why.
        """
        env.settings.setProperty('decoy', 'harmless')
        decoy_id = [row for row in env.db._query_index('property', key='decoy')
                    if row.get('identifier') == 'decoy'][0]['_id']

        document = json.dumps({
            '_id': decoy_id,
            '_t': 'property',
            'identifier': SESSION_SECRET_PROPERTY,
            'value': 'ff' * 32,
        })

        body = api_get(env, 'database.document.update', document=document).json()

        assert body['success'] is False
        assert len(secret_rows(env.db)) == 1, (
            'a second property row now claims the session_secret identifier'
        )

    def test_document_delete_refuses_to_delete_the_secret_row(self, env):
        """Deleting it locks every browser out until the process restarts.

        `get_session_secret` only ever reads (D2), so there is no request path
        that regenerates one: the login page accepts the correct password and
        still issues no cookie.
        """
        row_id = secret_rows(env.db)[0]['_id']

        body = api_get(env, 'database.document.delete', id=row_id).json()

        assert body['success'] is False
        assert len(secret_rows(env.db)) == 1
        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == env.secret

    def test_an_ordinary_document_can_still_be_updated_and_deleted(self, env):
        """The negative control.

        Without this, refusing EVERY update and delete would pass every
        assertion above -- and `database.document.*` is how the corrupted-row
        recovery `reportCorrupted` (formerly `deleteCorrupted`) points the
        operator at is driven by hand.
        """
        env.settings.setProperty('last_backup', '2026-08-07')
        row = [r for r in env.db._query_index('property', key='last_backup')
               if r.get('identifier') == 'last_backup'][0]
        stored = env.db.get('id', row['_id'])
        stored['value'] = '2026-08-08'

        updated = api_get(env, 'database.document.update',
                          document=json.dumps(stored)).json()
        assert updated['success'] is True, updated

        deleted = api_get(env, 'database.document.delete', id=row['_id']).json()
        assert deleted['success'] is True, deleted
