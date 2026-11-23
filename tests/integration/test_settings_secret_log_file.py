"""SEC-006: no secret reaches the LOG FILE, whatever the outcome.

The in-memory log tests prove a record's text; the criteria say "reading the log
file", and the file goes through the real handler and `PrivacyFilter`. This test sets
up the real logging to a file (`setup_logging`), drives every outcome of the group
save through the real route and the reveal route, then reads the
FILE and asserts that none of these appears in it: a fixture key, a row host or name,
any token issued during the run, the token key's hex, or a canary placed in the
message of every exception forced into the hold and into a log call.

Placeholder values and `.invalid` hosts only.
"""
import logging
import re

import pytest

from couchpotato.core import logger as logger_module
from couchpotato.core import settings as settings_module
from couchpotato.core.settings import SECRET_MASK
from tests.helpers.combine_groups import placeholder_rows
from tests.integration.test_settings_keep_restore_route import (
    API_KEY,
    HOSTILE,
    OWN,
    URL,
    world_with,
)
from tests.unit.test_settings_keep_restore import KEYS, keep, keyed_rows, restore, with_forms

pytestmark = pytest.mark.integration

CANARY = 'canary-held-text-or-token'
TYPED = 'placeholder-typed-replacement-key'


@pytest.fixture
def file_log(tmp_path):
    root = logging.getLogger()
    before_handlers, before_level = list(root.handlers), root.level
    path = tmp_path / 'cp.log'
    logger_module.setup_logging(log_path=str(path), debug=True, console=False)
    try:
        yield path
    finally:
        for handler in list(root.handlers):
            if handler not in before_handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(before_level)


@pytest.fixture
def world(tmp_path, monkeypatch):
    with world_with(tmp_path, monkeypatch) as live:
        yield live


class Run:
    """Drives the real route and collects every token, host and name that went by."""

    def __init__(self, settings, client):
        self.settings, self.client = settings, client
        self.tokens, self.hosts, self.names, self.responses = set(), set(), set(), []

    def _note(self, response):
        self.responses.append(response)
        self.tokens.update(re.findall(r'[0-9a-f]{64}', response.text))
        return response

    def token(self, section='newznab'):
        token = self.settings._group_token(section)
        self.tokens.add(token)
        return token

    def read(self):
        return self._note(self.client.get('/api/%s/settings/' % API_KEY))

    def save(self, rows, token=None, section='newznab', headers=OWN, **extra):
        for row in rows:
            for column, value in row.items():
                if isinstance(value, str) and column in ('host',):
                    self.hosts.add(value)
                if isinstance(value, str) and column in ('custom_tag', 'name'):
                    self.names.add(value)
        body = {'section': section, 'rows': rows, **extra}
        if token is not None:
            body['token'] = token
        return self._note(self.client.post(URL, json=body, headers=headers))

    def raw(self, path, body, headers=OWN):
        return self._note(self.client.post('/api/%s/%s' % (API_KEY, path), json=body, headers=headers))


def raising(*args, **kwargs):
    raise RuntimeError(CANARY)


def drive_every_outcome(run, monkeypatch):
    settings = run.settings
    rows = keyed_rows(settings)
    run.read()
    assert run.save(rows).json() == {'success': True}                         # accepted, token-less
    first = run.token()
    reordered = with_forms([rows[2], rows[0], rows[1]], {0: keep(2), 1: keep(0), 2: keep(1)})
    assert run.save(reordered, first).json()['success'] is True               # accepted with keeps
    replaced = with_forms(rows, {0: keep(0), 1: TYPED, 2: keep(2)})
    assert run.save(replaced, run.token()).json()['success'] is True          # a replaced key
    before_removal = run.token()
    removed = run.save(with_forms(rows[:1], {0: keep(0)}), before_removal)     # a removal
    assert removed.json()['success'] is True
    restored = run.save(with_forms(rows[:2], {0: keep(0), 1: restore(before_removal, 1)}), run.token())
    assert restored.json()['success'] is True                                 # a restore
    stale = run.save(with_forms(rows[:1], {0: keep(0)}), before_removal)       # stale, with a held list
    assert stale.json()['invalid'][0]['reason'] == 'stale'
    assert stale.json()['held']
    current = run.token()
    reasons = [
        run.save(with_forms(rows, {0: keep(0)})).json(),                                       # token_missing
        run.save(with_forms(rows, {0: {'keep': True}}), current).json(),                      # bad_reference
        run.save(with_forms(rows, {0: restore('0' * 64, 0)}), current).json(),                # restore_unknown
        run.save(with_forms(rows, {0: SECRET_MASK}), current).json(),                         # masked_value
        run.save(placeholder_rows(settings.combine_groups()['imdb'], 1), 'a' * 64,
                 section='imdb').json(),                                                       # token_unexpected
    ]
    assert [r['invalid'][0]['reason'] for r in reasons] == [
        'token_missing', 'bad_reference', 'restore_unknown', 'masked_value', 'token_unexpected']
    assert run.save(with_forms(rows, {0: keep(0)}), current, headers=HOSTILE).status_code == 403   # D9
    assert run.raw('settings.save_group', {'section': 'newznab', 'rows': rows, 'extra': 1}).status_code == 400
    for number in range(6):                                                   # 18 holds: some are evicted
        run.save(keyed_rows(settings, [TYPED + str(number), KEYS[0], KEYS[2]], tag='x%d' % number), run.token())
    assert len([k for k in settings._hold._entries if k[0] == 'newznab']) == 16
    for method in ('add', 'evict', 'take', 'list_by_token', 'peek'):          # a forced raise in each
        with monkeypatch.context() as patched:
            patched.setattr(settings_module._RemovedKeyHold, method, raising)
            token = run.token()
            run.save(with_forms(keyed_rows(settings, tag='y' + method)[:1], {0: keep(0)}), token)
            reference = next(key for key in settings._hold._entries if key[0] == 'newznab')
            run.save(with_forms(keyed_rows(settings, tag='z' + method)[:2],
                                {0: keep(0), 1: restore(reference[2], reference[3])}), run.token())
            run.save(with_forms(keyed_rows(settings, tag='w' + method)[:1], {0: keep(0)}), 'f' * 64)
    current = run.token()
    body = {'section': 'newznab', 'column': 'api_key', 'row': 0, 'token': current}
    assert run.raw('settings.reveal_cell', body).json()['success'] is True          # a reveal (answered)
    for refusal in ({**body, 'column': 'host'}, {**body, 'row': 99}, {**body, 'token': '0' * 64},
                    {**body, 'section': 'core', 'column': 'password'}, {**body, 'section': 'evil\nforged'}):
        assert run.raw('settings.reveal_cell', refusal).json()['success'] is False
    assert run.raw('settings.reveal_cell', body, headers=HOSTILE).status_code == 403
    with monkeypatch.context() as patched:                                    # a handler that raises
        patched.setattr(settings_module.Settings, 'group_cells', raising)
        assert run.raw('settings.reveal_cell', body).json()['success'] is False
    real_info = settings.log.info

    def info_that_fails_for_the_key_lines(message, *args, **kwargs):
        if message.startswith(('Kept a stored key', 'Restored a removed key')):
            raise RuntimeError(CANARY)
        return real_info(message, *args, **kwargs)

    with monkeypatch.context() as patched:                                    # a forced raise in a log call
        patched.setattr(settings.log, 'info', info_that_fails_for_the_key_lines)
        changed = with_forms(keyed_rows(settings, tag='logfail')[:1], {0: keep(0)})
        run.save(changed, run.token())


def test_the_log_file_holds_no_key_host_name_token_or_canary_after_every_outcome(
        world, file_log, monkeypatch):
    settings, client = world
    run = Run(settings, client)

    drive_every_outcome(run, monkeypatch)

    text = file_log.read_text(encoding='utf-8')
    assert 'Refused a settings group save' in text, 'the file must have caught the refusals'
    assert 'Kept a stored key on a changed address' in text
    assert 'Restored a removed key' in text
    assert 'Revealed a stored key' in text
    assert 'Refused a settings reveal' in text
    assert 'RuntimeError' in text, 'the forced failures must have been logged by type'
    secrets_in_play = {key.strip() for key in KEYS} | {TYPED} | {TYPED + str(n) for n in range(6)}
    for label, values in (('key', secrets_in_play), ('host', run.hosts), ('name', run.names),
                          ('token', run.tokens), ('token key', {settings._token_key.hex()}),
                          ('canary', {CANARY}), ('caller string', {'forged'})):
        assert values, 'nothing was collected for %s' % label
        for value in values:
            assert value.strip() not in text, '%s %r reached the log file' % (label, value[:12])
