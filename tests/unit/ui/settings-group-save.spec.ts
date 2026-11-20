// @vitest-environment node
/**
 * SEC-004 P3: the Settings panel saves a combine group as ROWS, one request per group.
 *
 * This runs the REAL `settingsPanel()`, `combinedField()` and `buttonField()` from
 * partials/settings/scripts.html (the script block is read from the template and
 * evaluated), with only `fetch`, the timers and the Alpine magics replaced. The browser
 * behaviour (focus, live regions, layout) is the E2E suite's; this pins the logic that
 * decides what is sent, when, and what is shown, where a wrong answer would write a
 * credential against the wrong host.
 *
 * Hosts are `.invalid` and every credential is a `placeholder-` string.
 */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getVal,
  takeRow,
  restoreRow,
  shiftMarksBack,
  rowRemovedLine,
  rowRemovedAnnouncement,
  rowRestoredAnnouncement,
} from '../../../couchpotato/static/scripts/ui/settings-values.js';

const TEMPLATE = path.resolve(__dirname, '../../../couchpotato/ui/templates/partials/settings/scripts.html');

function loadComponents(): Record<string, (...args: any[]) => any> {
  const html = fs.readFileSync(TEMPLATE, 'utf8');
  const code = html.slice(html.indexOf('<script>') + '<script>'.length, html.lastIndexOf('</script>'));
  return new Function(`${code}\nreturn { settingsPanel, combinedField, buttonField };`)();
}

/** The undo window of a removal, read from the page's own named constant (8 seconds, owner decision 2026-11-18). */
function undoWindowMs(): number {
  const html = fs.readFileSync(TEMPLATE, 'utf8');
  const code = html.slice(html.indexOf('<script>') + '<script>'.length, html.lastIndexOf('</script>'));
  return new Function(`${code}\nreturn REMOVAL_UNDO_WINDOW_MS;`)();
}
const UNDO_WINDOW = 8000;

const NEWZNAB_COLUMNS = ['use', 'host', 'api_key', 'extra_score', 'custom_tag'];
const NEWZNAB_PAIRING = ['host', 'api_key', 'use'];

function newznabOptions() {
  return {
    newznab: {
      name: 'newznab',
      groups: [{
        tab: 'searcher',
        options: [
          { name: 'enabled', type: 'enabler', default: true },
          { name: 'use', default: '0,0,0,0,0,0' },
          { name: 'host', default: 'a,b,c,d,e,f' },
          { name: 'extra_score', default: '0,0,0,0,0,0' },
          { name: 'custom_tag', default: ',,,,,' },
          { name: 'api_key', type: 'combined', default: ',,,,,', combine: NEWZNAB_COLUMNS, pairing: NEWZNAB_PAIRING },
        ],
      }],
    },
    torrentpotato: {
      name: 'torrentpotato',
      groups: [{
        tab: 'searcher',
        options: [
          { name: 'use', default: '' },
          { name: 'host', default: '' },
          { name: 'seed_ratio', default: '1' },
          { name: 'seed_time', default: '40' },
          { name: 'extra_score', default: '0' },
          { name: 'pass_key', type: 'combined', default: ',', combine: ['use', 'host', 'pass_key', 'seed_ratio', 'seed_time', 'extra_score'], pairing: ['host', 'pass_key', 'use'] },
          { name: 'jackett_sync', type: 'button', button_action: 'torrentpotato.jackett_sync' },
        ],
      }],
    },
  };
}

function combinedOption(options: ReturnType<typeof newznabOptions>, section = 'newznab') {
  return options[section as 'newznab'].groups[0].options.find((option: any) => option.type === 'combined') as any;
}

type Call = { url: string; init?: any };
type Reply = { status?: number; body?: unknown; text?: string };

/** A `fetch` whose answers the test supplies, one per call, optionally held open. */
function installFetch() {
  const calls: Call[] = [];
  const replies: (Reply | Promise<Reply>)[] = [];
  let open = 0;
  let peak = 0;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: any) => {
    calls.push({ url, init });
    open += 1;
    peak = Math.max(peak, open);
    try {
      const reply = await (replies.shift() ?? { body: { success: true } });
      return {
        ok: (reply.status ?? 200) < 400,
        status: reply.status ?? 200,
        json: async () => {
          if (reply.text !== undefined) throw new SyntaxError('not json');
          return reply.body;
        },
      };
    } finally {
      open -= 1;
    }
  }));
  return {
    calls,
    replies,
    peak: () => peak,
    groupSaves: () => calls.filter((call) => call.url.includes('settings.save_group')),
    columnSaves: () => calls.filter((call) => /settings\.save\//.test(call.url)),
    body: (index: number) => JSON.parse(calls[index].init.body),
  };
}

/** The Alpine magics a real component has and a bare object does not; removeRow hands focus over with them. */
function withAlpineMagics(field: any) {
  field.$nextTick = (callback: () => void) => callback();
  field.$el = { querySelector: () => null };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function makePanel(values: Record<string, Record<string, string>>, combineState: Record<string, any>, options = newznabOptions()) {
  const { settingsPanel } = loadComponents();
  const panel = settingsPanel();
  panel.options = options;
  panel.values = values;
  panel.combineState = combineState;
  panel.$nextTick = (callback: () => void) => callback();
  panel.$watch = () => {};
  return panel;
}

const ALIGNED_VALUES = {
  newznab: {
    use: '1,0,1',
    host: 'https://placeholder-one.invalid/api,https://placeholder-two.invalid/api,https://placeholder-three.invalid/api',
    api_key: ['placeholder-key-one', 'placeholder-key-two', 'placeholder-key-three'].join(','),
    extra_score: '5,10,15',
    custom_tag: 'tag-one,tag-two,tag-three',
  },
};

function aligned(overrides: Record<string, string> = {}) {
  return makePanel({ newznab: { ...ALIGNED_VALUES.newznab, ...overrides } }, { newznab: { misaligned: false, rows: 3 } });
}

function rowsOf(panel: any, section = 'newznab') {
  return panel.groupState[section].rows;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('CP', {
    apiBase: '/api/placeholder-api-key',
    ui: {
      getVal,
      isEnabledValue: (value: unknown) => value === true || value === '1',
      buildDescription: () => '',
      takeRow,
      restoreRow,
      shiftMarksBack,
      rowRemovedLine,
      rowRemovedAnnouncement,
      rowRestoredAnnouncement,
    },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function settle() {
  await vi.advanceTimersByTimeAsync(0);
}

describe('deriving the rows from the stored values', () => {
  it('shows one row per stored row, trimmed, with every column', () => {
    const panel = aligned({ host: 'https://placeholder-one.invalid/api, https://placeholder-two.invalid/api ,https://placeholder-three.invalid/api' });

    panel.ensureGroup('newznab', combinedOption(panel.options));

    expect(rowsOf(panel)).toHaveLength(3);
    expect(rowsOf(panel)[1][1]).toBe('https://placeholder-two.invalid/api');
    expect(rowsOf(panel)[2]).toEqual(['1', 'https://placeholder-three.invalid/api', 'placeholder-key-three', '15', 'tag-three']);
  });

  it('shows a missing use cell off, as 0, and leaves a present empty one alone', () => {
    const missing = makePanel({ newznab: { ...ALIGNED_VALUES.newznab, use: '1,0' } }, { newznab: { misaligned: true, rows: 3 } });
    const empty = makePanel({ newznab: { ...ALIGNED_VALUES.newznab, use: '1,,1' } }, { newznab: { misaligned: false, rows: 3 } });

    missing.ensureGroup('newznab', combinedOption(missing.options));
    empty.ensureGroup('newznab', combinedOption(empty.options));

    expect(rowsOf(missing)[2][0]).toBe('0');
    expect(rowsOf(empty)[1][0]).toBe('');
  });

  it('supplies the declared default for a short non-pairing column and an empty cell for a short pairing one', () => {
    const panel = makePanel(
      { newznab: { use: '1,0,1', host: 'a,b,c', api_key: 'k1,k2', extra_score: '5', custom_tag: '' } },
      { newznab: { misaligned: true, rows: 3 } },
    );

    panel.ensureGroup('newznab', combinedOption(panel.options));

    expect(rowsOf(panel).map((row: string[]) => row[2])).toEqual(['k1', 'k2', '']);
    expect(rowsOf(panel).map((row: string[]) => row[3])).toEqual(['5', '0', '0']);
  });

  it('does not show surplus cells past the row count', () => {
    const panel = makePanel(
      { newznab: { ...ALIGNED_VALUES.newznab, extra_score: '0,0,0,0,0,0', custom_tag: ',,,,,' } },
      { newznab: { misaligned: false, rows: 3 } },
    );

    panel.ensureGroup('newznab', combinedOption(panel.options));

    expect(rowsOf(panel)).toHaveLength(3);
  });

  it('shows exactly one blank row for a group with nothing stored', () => {
    const panel = makePanel({ newznab: { use: '', host: '', api_key: '', extra_score: '', custom_tag: '' } }, { newznab: { misaligned: false, rows: 1 } });

    panel.ensureGroup('newznab', combinedOption(panel.options));

    expect(rowsOf(panel)).toHaveLength(1);
  });

  it('keeps one group per section, so a rebuilt field finds the same rows', () => {
    const panel = aligned();
    const option = combinedOption(panel.options);

    const first = panel.ensureGroup('newznab', option);
    first.rows[0][1] = 'https://placeholder-edited.invalid/api';

    expect(panel.ensureGroup('newznab', option)).toBe(first);
    expect(rowsOf(panel)[0][1]).toBe('https://placeholder-edited.invalid/api');
  });

  it('writes nothing on load, after the debounce, or on a re-read', async () => {
    const net = installFetch();
    const panel = aligned();
    panel.ensureGroup('newznab', combinedOption(panel.options));

    panel.reloadCleanGroups();
    await vi.advanceTimersByTimeAsync(5000);

    expect(net.calls).toEqual([]);
  });
});

describe('saving a group', () => {
  async function edited(panel = aligned()) {
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[1][1] = 'https://placeholder-edited.invalid/api';
    panel.editGroup('newznab');
    return { panel, group };
  }

  it('sends ONE JSON request for the whole group, as rows, after the debounce', async () => {
    const net = installFetch();
    await edited();

    await vi.advanceTimersByTimeAsync(499);
    expect(net.calls).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);

    expect(net.calls).toHaveLength(1);
    expect(net.calls[0].url).toBe('/api/placeholder-api-key/settings.save_group/');
    expect(net.calls[0].init.method).toBe('POST');
    expect(net.calls[0].init.headers['Content-Type']).toBe('application/json');
    const sent = net.body(0);
    expect(Object.keys(sent).sort()).toEqual(['rows', 'section']);
    expect(sent.section).toBe('newznab');
    expect(sent.rows).toHaveLength(3);
    expect(sent.rows[1]).toEqual({
      use: '0', host: 'https://placeholder-edited.invalid/api', api_key: 'placeholder-key-two', extra_score: '10', custom_tag: 'tag-two',
    });
  });

  it('never sends a per-column settings.save for a combine column', async () => {
    const net = installFetch();
    await edited();

    await vi.advanceTimersByTimeAsync(2000);

    expect(net.columnSaves()).toEqual([]);
  });

  it('sends the cells trimmed', async () => {
    const net = installFetch();
    const { group } = await edited();
    group.rows[0][1] = '  https://placeholder-spaced.invalid/api  ';
    group.rows[0][2] = ' placeholder-key-one ';

    await vi.advanceTimersByTimeAsync(500);

    expect(net.body(0).rows[0].host).toBe('https://placeholder-spaced.invalid/api');
    expect(net.body(0).rows[0].api_key).toBe('placeholder-key-one');
  });

  it('sends a burst of edits as one request carrying the last of them', async () => {
    const net = installFetch();
    const { panel, group } = await edited();
    await vi.advanceTimersByTimeAsync(300);
    group.rows[1][1] = 'https://placeholder-second.invalid/api';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(300);
    expect(net.calls).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(200);

    expect(net.calls).toHaveLength(1);
    expect(net.body(0).rows[1].host).toBe('https://placeholder-second.invalid/api');
  });

  it('keeps one request in flight and sends the LATEST rows behind it', async () => {
    const net = installFetch();
    const first = deferred<Reply>();
    net.replies.push(first.promise);
    const { panel, group } = await edited();
    await vi.advanceTimersByTimeAsync(500);
    expect(net.calls).toHaveLength(1);

    group.rows[1][1] = 'https://placeholder-later.invalid/api';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    group.rows[1][1] = 'https://placeholder-latest.invalid/api';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    expect(net.calls).toHaveLength(1);

    first.resolve({ body: { success: true } });
    await vi.advanceTimersByTimeAsync(0);

    expect(net.calls).toHaveLength(2);
    expect(net.body(1).rows[1].host).toBe('https://placeholder-latest.invalid/api');
    expect(net.peak()).toBe(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(net.calls).toHaveLength(2);
  });

  it('on success clears the dirty state, shows Saved once and keeps the saved cells as the stored ones', async () => {
    installFetch();
    const { panel, group } = await edited();

    await vi.advanceTimersByTimeAsync(500);

    expect(group.dirty).toBe(false);
    expect(panel.lastSaved).toBe(true);
    expect(panel.saving).toBe(false);
    expect(panel.values.newznab.host.split(',')[1]).toBe('https://placeholder-edited.invalid/api');
  });

  it('a save that lands behind a newer edit does not clear the dirty state', async () => {
    const net = installFetch();
    const first = deferred<Reply>();
    net.replies.push(first.promise);
    const { panel, group } = await edited();
    await vi.advanceTimersByTimeAsync(500);

    group.rows[2][1] = 'https://placeholder-newer.invalid/api';
    panel.editGroup('newznab');
    first.resolve({ body: { success: true } });
    await vi.advanceTimersByTimeAsync(0);

    expect(net.calls).toHaveLength(1);
    expect(group.dirty).toBe(true);
    expect(group.rows[2][1]).toBe('https://placeholder-newer.invalid/api');

    await vi.advanceTimersByTimeAsync(500);

    expect(net.calls).toHaveLength(2);
    expect(net.body(1).rows[2].host).toBe('https://placeholder-newer.invalid/api');
    expect(group.dirty).toBe(false);
  });

  it('shows Saving while the request is open', async () => {
    const net = installFetch();
    const held = deferred<Reply>();
    net.replies.push(held.promise);
    const { panel } = await edited();

    await vi.advanceTimersByTimeAsync(500);
    expect(panel.saving).toBe(true);
    held.resolve({ body: { success: true } });
    await vi.advanceTimersByTimeAsync(0);

    expect(panel.saving).toBe(false);
  });
});

describe('a refused or failed save', () => {
  const refusal = (...invalid: any[]) => ({ body: { success: false, error: 'A cell cannot contain a comma.', invalid } });

  async function refusedOnce(entries: any[] = [{ row: 1, column: 'host', reason: 'comma' }]) {
    const net = installFetch();
    net.replies.push(refusal(...entries));
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[1][1] = 'https://placeholder-one.invalid,https://placeholder-evil.invalid';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    return { net, panel, group };
  }

  it('keeps the rows dirty, never shows Saved and does not raise the per-column toast', async () => {
    const { panel, group } = await refusedOnce();

    expect(group.dirty).toBe(true);
    expect(panel.lastSaved).toBe(false);
    expect(panel.message).toBe('');
    expect(panel.saving).toBe(false);
  });

  it('composes the message from the structured refusal with the page\'s own row noun and field label', async () => {
    const { group } = await refusedOnce();

    expect(group.refusal).toHaveLength(1);
    expect(group.refusal[0]).toMatchObject({ row: 1, column: 'host' });
    expect(group.refusal[0].message).toBe('Row 2: the host cannot contain a comma. Remove it to save.');
  });

  it('marks every offending cell of the refusal', async () => {
    const { group } = await refusedOnce([
      { row: 1, column: 'host', reason: 'comma' }, { row: 1, column: 'api_key', reason: 'comma' },
    ]);

    expect(group.refusal.map((entry: any) => entry.column)).toEqual(['host', 'api_key']);
    expect(group.refusal[1].message).toBe('Row 2: the api key cannot contain a comma. Remove it to save.');
  });

  it('names a control character and an unstorable character for what they are', async () => {
    const { group } = await refusedOnce([
      { row: 0, column: 'host', reason: 'control_character' }, { row: 2, column: 'custom_tag', reason: 'not_encodable' },
    ]);

    expect(group.refusal[0].message).toMatch(/^Row 1: the host cannot contain a line break or other control character/);
    expect(group.refusal[1].message).toMatch(/^Row 3: the custom tag contains a character that cannot be saved/);
  });

  it('never puts a submitted value, an option key, an HTTP status or "Error:" in the message', async () => {
    const { group } = await refusedOnce();

    for (const entry of group.refusal) {
      expect(entry.message).not.toMatch(/placeholder|evil|api_key|newznab\.|HTTP|Error:|\d{3}\b/);
    }
  });

  it('falls back to the server text when the structured list is absent or the reason is unknown', async () => {
    const absent = installFetch();
    absent.replies.push({ body: { success: false, error: 'The settings could not be saved. Nothing was changed.' } });
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[0][1] = 'https://placeholder-x.invalid/api';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);

    expect(group.refusal).toEqual([]);
    expect(group.error).toBe('The settings could not be saved. Nothing was changed.');
    expect(group.dirty).toBe(true);
  });

  it('treats a reason it does not know as the fallback, not as an empty message', async () => {
    const { group } = await refusedOnce([{ row: 1, column: 'host', reason: 'something_new' }]);

    expect(group.refusal).toEqual([]);
    expect(group.error).toBe('A cell cannot contain a comma.');
  });

  it.each([
    ['the route does not exist', { body: { success: false, error: "API call doesn't exist" } }],
    ['the server answered 500 with no JSON', { status: 500, text: 'Internal Server Error' }],
    ['the server answered 500 with JSON', { status: 500, body: { success: false } }],
  ])('keeps the rows dirty and shows the failure when %s', async (_name, reply) => {
    const net = installFetch();
    net.replies.push(reply as Reply);
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[0][1] = 'https://placeholder-x.invalid/api';
    panel.editGroup('newznab');

    await vi.advanceTimersByTimeAsync(500);

    expect(group.dirty).toBe(true);
    expect(group.error).not.toBe('');
    expect(panel.lastSaved).toBe(false);
    expect(panel.assertiveAnnouncement).toBe(group.error);
  });

  it('keeps the rows dirty when the network fails', async () => {
    installFetch();
    (globalThis.fetch as any).mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[0][1] = 'https://placeholder-x.invalid/api';
    panel.editGroup('newznab');

    await vi.advanceTimersByTimeAsync(500);

    expect(group.dirty).toBe(true);
    expect(group.error).not.toBe('');
    expect(panel.lastSaved).toBe(false);
  });

  it('announces a refusal once, however many more saves it takes, and again after it has cleared', async () => {
    const net = installFetch();
    const panel = aligned();
    const spoken: string[] = [];
    let region = '';
    Object.defineProperty(panel, 'assertiveAnnouncement', {
      get: () => region,
      set: (value: string) => { region = value; if (value) spoken.push(value); },
    });
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    const refuse = async (cell: string) => {
      net.replies.push(refusal({ row: 1, column: 'host', reason: 'comma' }));
      group.rows[1][2] = cell;
      panel.editGroup('newznab');
      await vi.advanceTimersByTimeAsync(500);
    };
    const message = 'Row 2: the host cannot contain a comma. Remove it to save.';

    for (const cell of ['placeholder-x', 'placeholder-xy', 'placeholder-xyz']) await refuse(cell);
    expect(spoken).toEqual([message]);

    net.replies.push({ body: { success: true } });
    group.rows[1][2] = 'placeholder-fixed';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    expect(group.refusal).toEqual([]);
    expect(spoken).toEqual([message]);

    await refuse('placeholder-again');
    expect(spoken).toEqual([message, message]);
  });

  it('never announces Saved for a refusal', async () => {
    const { panel } = await refusedOnce();

    expect(panel.politeAnnouncement).toBe('');
    expect(panel.lastSaved).toBe(false);
  });

  it('clears the refusal and the error when a later save succeeds', async () => {
    const { net, panel, group } = await refusedOnce();
    net.replies.push({ body: { success: true } });
    group.rows[1][1] = 'https://placeholder-fixed.invalid/api';
    panel.editGroup('newznab');

    await vi.advanceTimersByTimeAsync(500);

    expect(group.refusal).toEqual([]);
    expect(group.error).toBe('');
    expect(group.dirty).toBe(false);
    expect(panel.lastSaved).toBe(true);
  });

  it('keeps a refusal across the field being rebuilt, and does not show the refused value as saved', async () => {
    const { panel } = await refusedOnce();
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    field.getPanel = () => panel;

    field.init();

    expect(field.held.refusal).toHaveLength(1);
    expect(field.held.rows[1][1]).toBe('https://placeholder-one.invalid,https://placeholder-evil.invalid');
    expect(panel.values.newznab.host).not.toContain('evil');
  });
});

describe('a correction typed while a refused save is open', () => {
  const refusal = (row: number) => ({ body: { success: false, error: 'A cell cannot contain a comma.', invalid: [{ row, column: 'host', reason: 'comma' }] } });

  it('is still sent, and its success clears the refusal', async () => {
    const net = installFetch();
    const first = deferred<Reply>();
    net.replies.push(first.promise, { body: { success: true } });
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[1][1] = 'https://placeholder-bad,https://placeholder-evil.invalid';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    group.rows[1][1] = 'https://placeholder-corrected.invalid/api';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    expect(net.calls).toHaveLength(1);

    first.resolve(refusal(1));
    await vi.advanceTimersByTimeAsync(0);

    expect(net.calls).toHaveLength(2);
    expect(net.body(1).rows[1].host).toBe('https://placeholder-corrected.invalid/api');
    expect(group.refusal).toEqual([]);
    expect(group.dirty).toBe(false);
  });
});

describe('a verdict for rows that have since changed', () => {
  it('marks no cell, and the save after it marks the right row', async () => {
    const net = installFetch();
    const first = deferred<Reply>();
    net.replies.push(first.promise, { body: { success: false, error: 'x', invalid: [{ row: 1, column: 'host', reason: 'comma' }] } });
    const panel = aligned();
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    field.getPanel = () => panel;
    withAlpineMagics(field);
    field.init();
    field.held.rows[2][1] = 'https://placeholder-bad,https://placeholder-evil.invalid';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);

    field.removeRow(0);
    // Row 3 as it was; the index 1 is valid now but names a different row.
    first.resolve({ body: { success: false, error: 'x', invalid: [{ row: 1, column: 'host', reason: 'comma' }] } });
    await vi.advanceTimersByTimeAsync(0);
    expect(field.held.refusal).toEqual([]);

    await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
    expect(field.held.refusal.map((entry: any) => entry.row)).toEqual([1]);
    expect(field.held.refusal[0].message).toMatch(/^Row 2:/);
  });

  it('a network failure for rows that have since changed shows no error, and the next save\'s verdict stands', async () => {
    const net = installFetch();
    const held = deferred<Reply>();
    const failed = held.promise;
    net.replies.push(failed, { body: { success: false, error: 'x', invalid: [{ row: 0, column: 'host', reason: 'comma' }] } });
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[0][1] = 'https://placeholder-first.invalid/api';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    group.rows[0][1] = 'https://placeholder-bad,https://placeholder-evil.invalid';
    panel.editGroup('newznab');

    (held as any).resolve(Promise.reject(new TypeError('Failed to fetch')));
    await vi.advanceTimersByTimeAsync(0);
    expect(group.error).toBe('');

    await vi.advanceTimersByTimeAsync(500);
    expect(group.refusal.map((entry: any) => entry.row)).toEqual([0]);
    expect(group.error).toBe('');
  });

  it('shows no Saved while a newer edit is still unsaved', async () => {
    const net = installFetch();
    const first = deferred<Reply>();
    net.replies.push(first.promise);
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[0][1] = 'https://placeholder-first.invalid/api';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    group.rows[0][1] = 'https://placeholder-second.invalid/api';
    panel.editGroup('newznab');

    first.resolve({ body: { success: true } });
    await vi.advanceTimersByTimeAsync(0);

    expect(panel.lastSaved).toBe(false);
    await vi.advanceTimersByTimeAsync(500);
    expect(panel.lastSaved).toBe(true);
  });

  it('keeps an earlier refusal on the row it describes when a row above it is removed', () => {
    const panel = aligned();
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    field.getPanel = () => panel;
    withAlpineMagics(field);
    field.init();
    field.held.refusal = [{ row: 2, column: 'host', reason: 'comma', message: 'Row 3: the host cannot contain a comma. Remove it to save.' }];

    field.removeRow(0);

    expect(field.held.refusal.map((entry: any) => entry.row)).toEqual([1]);
    expect(field.held.refusal[0].message).toMatch(/^Row 2:/);
  });

  it('does not announce the same refusal again when a row above it is removed and the server refuses it again', async () => {
    const net = installFetch();
    const comma = (row: number) => ({ body: { success: false, error: 'x', invalid: [{ row, column: 'host', reason: 'comma' }] } });
    net.replies.push(comma(2), comma(1));
    const panel = aligned();
    const spoken: Array<[string, boolean | undefined]> = [];
    const announce = panel.announce.bind(panel);
    panel.announce = (message: string, assertive?: boolean) => { spoken.push([message, assertive]); announce(message, assertive); };
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    field.getPanel = () => panel;
    withAlpineMagics(field);
    field.init();
    field.held.rows[2][1] = 'https://placeholder-bad,https://placeholder-evil.invalid';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);
    expect(spoken.filter(([, assertive]) => assertive)).toHaveLength(1);

    field.removeRow(0);
    await vi.advanceTimersByTimeAsync(UNDO_WINDOW);

    expect(field.held.refusal.map((entry: any) => entry.row)).toEqual([1]);
    expect(field.held.refusal[0].message).toMatch(/^Row 2:/);
    expect(spoken.filter(([, assertive]) => assertive)).toHaveLength(1);
  });

  it('drops the marks of a removed row', () => {
    const panel = aligned();
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    field.getPanel = () => panel;
    withAlpineMagics(field);
    field.init();
    field.held.refusal = [{ row: 1, column: 'host', reason: 'comma', message: 'Row 2: x' }];

    field.removeRow(1);

    expect(field.held.refusal).toEqual([]);
  });
});

describe('what describes a cell', () => {
  function fieldFor(values: Record<string, string>, misaligned: boolean) {
    // A copy: the panel keeps and writes into the values it is given.
    const panel = makePanel({ newznab: { ...values } }, { newznab: { misaligned, rows: 3 } });
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    field.getPanel = () => panel;
    field.init();
    return field;
  }

  it('is nothing for an aligned group with no refusal', () => {
    expect(fieldFor(ALIGNED_VALUES.newznab, false).describedBy(0, 1)).toBeNull();
  });

  it('is the notice while it is shown, for every cell including the switch', () => {
    const field = fieldFor(ALIGNED_VALUES.newznab, true);

    expect(field.describedBy(0, 0)).toBe('cf-notice-newznab');
    expect(field.describedBy(2, 4)).toBe('cf-notice-newznab');
  });

  it('is the notice then the refusal for a refused cell, and the notice goes when it clears', () => {
    const field = fieldFor(ALIGNED_VALUES.newznab, true);
    field.held.refusal = [{ row: 1, column: 'host', reason: 'comma', message: 'm' }];

    expect(field.describedBy(1, 1)).toBe('cf-notice-newznab cf-err-newznab-1-host');
    field.held.notice = false;
    expect(field.describedBy(1, 1)).toBe('cf-err-newznab-1-host');
  });
});

describe('an empty use cell', () => {
  it('is sent as 0 for a group that is edited, whether it was missing or present but empty', async () => {
    const net = installFetch();
    const panel = makePanel(
      { newznab: { ...ALIGNED_VALUES.newznab, use: '1,,' } },
      { newznab: { misaligned: false, rows: 3 } },
    );
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[0][1] = 'https://placeholder-edited.invalid/api';
    panel.editGroup('newznab');

    await vi.advanceTimersByTimeAsync(500);

    expect(net.body(0).rows.map((row: any) => row.use)).toEqual(['1', '0', '0']);
  });

  it('is sent as 0 when the cell is missing altogether', async () => {
    const net = installFetch();
    const panel = makePanel(
      { newznab: { ...ALIGNED_VALUES.newznab, use: '1' } },
      { newznab: { misaligned: true, rows: 3 } },
    );
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[0][1] = 'https://placeholder-edited.invalid/api';
    panel.editGroup('newznab');

    await vi.advanceTimersByTimeAsync(500);

    expect(net.body(0).rows.map((row: any) => row.use)).toEqual(['1', '0', '0']);
  });

  it('is left empty in a group whose use column is not named use', async () => {
    const net = installFetch();
    const options = {
      imdb: { name: 'imdb', groups: [{ options: [
        { name: 'automation_urls', type: 'combined', combine: ['automation_urls_use', 'automation_urls'], pairing: ['automation_urls_use', 'automation_urls'] },
      ] }] },
    };
    const panel = makePanel({ imdb: { automation_urls_use: '', automation_urls: 'https://placeholder-list.invalid/a' } }, { imdb: { misaligned: false, rows: 1 } }, options as any);
    const group = panel.ensureGroup('imdb', options.imdb.groups[0].options[0]);
    group.rows[0][1] = 'https://placeholder-list.invalid/b';
    panel.editGroup('imdb');

    await vi.advanceTimersByTimeAsync(500);

    expect(net.body(0).rows[0].automation_urls_use).toBe('');
  });

  it('is never rewritten for a group nobody edited', async () => {
    const net = installFetch();
    const panel = makePanel({ newznab: { ...ALIGNED_VALUES.newznab, use: '1,,1' } }, { newznab: { misaligned: false, rows: 3 } });
    panel.ensureGroup('newznab', combinedOption(panel.options));

    panel.reloadCleanGroups();
    await vi.advanceTimersByTimeAsync(5000);

    expect(net.calls).toEqual([]);
  });
});

describe('the misaligned notice', () => {
  it('is shown from the server flag and clears once a save of the group succeeds', async () => {
    installFetch();
    const panel = makePanel(
      { newznab: { use: '1,0', host: 'a,b,c', api_key: 'k1,k2', extra_score: '0', custom_tag: '' } },
      { newznab: { misaligned: true, rows: 3 } },
    );
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    expect(group.notice).toBe(true);

    group.rows[0][1] = 'https://placeholder-x.invalid/api';
    panel.editGroup('newznab');
    await vi.advanceTimersByTimeAsync(500);

    expect(group.notice).toBe(false);
  });

  it('is never derived in script: an aligned flag shows no notice whatever the columns look like', () => {
    const panel = makePanel(
      { newznab: { use: '1,0', host: 'a,b,c', api_key: 'k1,k2', extra_score: '0', custom_tag: '' } },
      { newznab: { misaligned: false, rows: 3 } },
    );

    expect(panel.ensureGroup('newznab', combinedOption(panel.options)).notice).toBe(false);
  });

  it('writes nothing until the user edits, even for a misaligned group', async () => {
    const net = installFetch();
    const panel = makePanel(
      { newznab: { use: '1,0', host: 'a,b,c', api_key: 'k1,k2', extra_score: '0', custom_tag: '' } },
      { newznab: { misaligned: true, rows: 3 } },
    );
    panel.ensureGroup('newznab', combinedOption(panel.options));

    await vi.advanceTimersByTimeAsync(5000);

    expect(net.calls).toEqual([]);
  });
});

describe('flushing, and re-reading', () => {
  it('flushPendingSaves sends a pending group save now and waits for it', async () => {
    const net = installFetch();
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    group.rows[0][1] = 'https://placeholder-flush.invalid/api';
    panel.editGroup('newznab');

    await panel.flushPendingSaves();

    expect(net.groupSaves()).toHaveLength(1);
    expect(group.dirty).toBe(false);
    await vi.advanceTimersByTimeAsync(2000);
    expect(net.groupSaves()).toHaveLength(1);
  });

  it('flushPendingSaves with nothing pending sends nothing', async () => {
    const net = installFetch();
    const panel = aligned();
    panel.ensureGroup('newznab', combinedOption(panel.options));

    await panel.flushPendingSaves();

    expect(net.calls).toEqual([]);
  });

  it('a re-read refreshes a clean group in place and leaves a dirty one alone', () => {
    const panel = aligned();
    const group = panel.ensureGroup('newznab', combinedOption(panel.options));
    panel.values = { newznab: { ...ALIGNED_VALUES.newznab, host: 'https://placeholder-new-one.invalid/api,https://placeholder-new-two.invalid/api,https://placeholder-new-three.invalid/api' } };
    panel.reloadCleanGroups();
    expect(group.rows[0][1]).toBe('https://placeholder-new-one.invalid/api');

    group.rows[0][1] = 'https://placeholder-mine.invalid/api';
    panel.editGroup('newznab');
    panel.values = { newznab: { ...ALIGNED_VALUES.newznab, host: 'x,y,z' } };
    panel.reloadCleanGroups();

    expect(group.rows[0][1]).toBe('https://placeholder-mine.invalid/api');
  });

  it('adds a blank row without saving, with the use switch off and the non-pairing defaults', async () => {
    const net = installFetch();
    const panel = makePanel(
      { torrentpotato: { use: '', host: '', pass_key: ',', seed_ratio: '1', seed_time: '40', extra_score: '0' } },
      { torrentpotato: { misaligned: false, rows: 2 } },
    );
    const { combinedField } = loadComponents();
    const field = combinedField('torrentpotato', combinedOption(panel.options, 'torrentpotato'));
    field.getPanel = () => panel;
    field.init();

    field.addRow();
    await vi.advanceTimersByTimeAsync(5000);

    expect(field.held.rows).toHaveLength(3);
    expect(field.held.rows[2]).toEqual(['0', '', '', '1', '40', '0']);
    expect(net.calls).toEqual([]);
  });
});

describe('a button in a section with a combine group: the rows are locked from the click until the server\'s rows are back', () => {
  const HOSTS = ['one', 'two', 'three'].map((word) => `https://placeholder-${word}.invalid/api`);
  const SYNCED = 'https://placeholder-synced.invalid/api';

  function torrentValues(hosts: string[]) {
    return {
      use: hosts.map(() => '1').join(','),
      host: hosts.join(','),
      pass_key: hosts.map((_, index) => `placeholder-pass-${index}`).join(','),
      seed_ratio: hosts.map(() => '1').join(','),
      seed_time: hosts.map(() => '40').join(','),
      extra_score: hosts.map(() => '0').join(','),
    };
  }

  /** What `GET settings/` answers once the sync has written `hosts`. */
  const serverRows = (hosts: string[]): Reply => ({
    body: {
      options: newznabOptions(),
      values: { torrentpotato: torrentValues(hosts), newznab: { ...ALIGNED_VALUES.newznab } },
      combine_state: { torrentpotato: { misaligned: false, rows: hosts.length }, newznab: { misaligned: false, rows: 3 } },
    },
  });

  function torrentPanel() {
    const panel = makePanel(
      // A copy: a save writes its rows back into the values it was given, and the shared
      // constant would carry one test's edit into the next.
      { torrentpotato: torrentValues(HOSTS), newznab: { ...ALIGNED_VALUES.newznab } },
      { torrentpotato: { misaligned: false, rows: 3 }, newznab: { misaligned: false, rows: 3 } },
    );
    const option = combinedOption(panel.options, 'torrentpotato');
    return { panel, option, group: panel.ensureGroup('torrentpotato', option) };
  }

  function fieldOf(panel: any, option: any) {
    const { combinedField } = loadComponents();
    const field = combinedField('torrentpotato', option);
    field.getPanel = () => panel;
    field.init();
    return field;
  }

  function button(panel: any) {
    const { buttonField } = loadComponents();
    const field = buttonField('torrentpotato', { button_action: 'torrentpotato.jackett_sync', name: 'jackett_sync' });
    field.getPanel = () => panel;
    return field;
  }

  const calls = (net: ReturnType<typeof installFetch>) => net.calls.map((call) => call.url.split('/').slice(-2)[0]);

  async function startedAction(extra: Array<Reply | Promise<Reply>> = []) {
    const net = installFetch();
    const action = deferred<Reply>();
    net.replies.push(action.promise, ...extra);
    const ctx = torrentPanel();
    const field = button(ctx.panel);
    const running = field.execute();
    await vi.advanceTimersByTimeAsync(0);
    return { net, action, running, field, ...ctx };
  }

  it('locks the group synchronously on the click, before anything is awaited, and says so once', () => {
    installFetch();
    const { panel, group } = torrentPanel();

    void button(panel).execute();

    expect(group.locked).toBe(true);
    expect(group.actionRunning).toBe(true);
    expect(panel.politeAnnouncement).toBe('These rows are locked while the action runs.');
  });

  for (const elapsed of [300, 1500, 6000]) {
    it(`refuses every edit while the action runs (${elapsed}ms), and sends no save for that group`, async () => {
      const { net, action, running, panel, option, group } = await startedAction();
      const field = fieldOf(panel, option);
      const before = JSON.stringify(group.rows);

      field.updateRow(0, 1, 'https://placeholder-typed.invalid/api');
      field.updateRow(0, 0, '0');
      field.addRow();
      field.removeRow(1);
      await vi.advanceTimersByTimeAsync(elapsed);
      await panel.saveGroup('torrentpotato');
      await panel.flushPendingSaves();

      expect(JSON.stringify(group.rows)).toBe(before);
      expect(group.dirty).toBe(false);
      expect(net.groupSaves()).toEqual([]);
      action.resolve({ body: { success: false, error: 'Jackett refused' } });
      await running;
    });
  }

  it('does not lock another section\'s group', async () => {
    const { net, action, running, panel } = await startedAction();
    const other = panel.ensureGroup('newznab', combinedOption(panel.options));
    other.rows[0][1] = 'https://placeholder-other.invalid/api';
    panel.editGroup('newznab');

    await vi.advanceTimersByTimeAsync(500);

    expect(net.groupSaves()).toHaveLength(1);
    expect(net.body(net.calls.length - 1).section).toBe('newznab');
    action.resolve({ body: { success: false, error: 'x' } });
    await running;
  });

  it('F1: an edit the instant the action answers is refused until the server\'s rows are shown', async () => {
    const reread = deferred<Reply>();
    const { net, action, running, panel, option, group } = await startedAction([reread.promise]);
    const field = fieldOf(panel, option);

    action.resolve({ body: { success: true, message: 'Synced' } });
    await vi.advanceTimersByTimeAsync(0);
    field.updateRow(0, 1, 'https://placeholder-too-early.invalid/api');
    expect(group.locked).toBe(true);
    expect(group.dirty).toBe(false);
    await vi.advanceTimersByTimeAsync(5000);
    expect(net.groupSaves()).toEqual([]);

    reread.resolve(serverRows([...HOSTS, SYNCED]));
    await running;

    expect(group.locked).toBe(false);
    expect(group.actionRunning).toBe(false);
    expect(group.rows).toHaveLength(4);
    expect(group.rows[3][1]).toBe(SYNCED);
    field.updateRow(0, 1, 'https://placeholder-after.invalid/api');
    await vi.advanceTimersByTimeAsync(500);
    expect(net.body(net.calls.length - 1).rows).toHaveLength(4);
  });

  it('F2: the button being torn down by a tab change does not stop the re-read', async () => {
    const { action, running, field, group } = await startedAction([serverRows([...HOSTS, SYNCED])]);
    field.getPanel = () => null;

    action.resolve({ body: { success: true, message: 'Synced' } });
    await running;

    expect(group.rows).toHaveLength(4);
    expect(group.locked).toBe(false);
  });

  it('a field rebuilt during the action finds the rows still locked, then the server\'s rows', async () => {
    const { action, running, panel, option } = await startedAction([serverRows([...HOSTS, SYNCED])]);

    const rebuilt = fieldOf(panel, option);
    expect(rebuilt.held.locked).toBe(true);
    action.resolve({ body: { success: true } });
    await running;

    expect(rebuilt.held.rows).toHaveLength(4);
    expect(rebuilt.held.locked).toBe(false);
  });

  for (const [name, reply] of [
    ['a non-JSON HTTP 500', { status: 500, text: '<html>Internal Server Error</html>' }],
    ['a thrown request error', null],
  ] as const) {
    it(`F3: ${name} may have written, so the page re-reads, shows the error, and saves only the file's rows plus the next edit`, async () => {
      const net = installFetch();
      const action = deferred<Reply>();
      net.replies.push(action.promise, serverRows([...HOSTS, SYNCED]));
      const { panel, option, group } = torrentPanel();
      const field = button(panel);
      const running = field.execute();
      await vi.advanceTimersByTimeAsync(0);

      if (reply) action.resolve(reply as Reply);
      else action.resolve(Promise.reject(new TypeError('Failed to fetch')));
      await running;

      expect(field.success).toBe(false);
      expect(field.result).not.toBe('');
      expect(field.running).toBe(false);
      expect(group.rows).toHaveLength(4);
      expect(group.locked).toBe(false);
      fieldOf(panel, option).updateRow(0, 1, 'https://placeholder-next.invalid/api');
      await vi.advanceTimersByTimeAsync(500);
      const saved = net.body(net.calls.length - 1).rows;
      expect(saved).toHaveLength(4);
      expect(saved[3].host).toBe(SYNCED);
      expect(saved[0].host).toBe('https://placeholder-next.invalid/api');
    });
  }

  it('F4: a button rebuilt mid-action is busy, and a second press sends no second action', async () => {
    const { net, action, running, panel } = await startedAction([serverRows([...HOSTS, SYNCED])]);
    const rebuilt = button(panel);

    expect(rebuilt.busy).toBe(true);
    await rebuilt.execute();
    expect(calls(net).filter((name) => name === 'torrentpotato.jackett_sync')).toHaveLength(1);

    action.resolve({ body: { success: true } });
    await running;
    expect(rebuilt.busy).toBe(false);
  });

  it('the busy state is read from the panel, not from the button that was pressed', async () => {
    const { action, running, panel } = await startedAction();
    const rebuilt = button(panel);

    expect(rebuilt.running).toBe(false);
    expect(rebuilt.busy).toBe(true);
    action.resolve({ body: { success: false, error: 'x' } });
    await running;
  });

  it('saves an edit made 100ms before the click, and one with a save in flight at the click, before the action', async () => {
    const net = installFetch();
    const inFlight = deferred<Reply>();
    net.replies.push(inFlight.promise, { body: { success: true } }, { body: { success: false, error: 'x' } });
    const { panel, option, group } = torrentPanel();
    const field = fieldOf(panel, option);
    field.updateRow(0, 1, 'https://placeholder-first.invalid/api');
    await vi.advanceTimersByTimeAsync(500);
    expect(net.groupSaves()).toHaveLength(1);
    field.updateRow(1, 1, 'https://placeholder-second.invalid/api');
    await vi.advanceTimersByTimeAsync(100);

    const running = button(panel).execute();
    field.updateRow(2, 1, 'https://placeholder-during-flush.invalid/api');
    await vi.advanceTimersByTimeAsync(0);
    inFlight.resolve({ body: { success: true } });
    await running;

    expect(calls(net)).toEqual(['settings.save_group', 'settings.save_group', 'torrentpotato.jackett_sync']);
    expect(net.body(1).rows[1].host).toBe('https://placeholder-second.invalid/api');
    expect(net.body(1).rows[2].host).toBe(HOSTS[2]);
    expect(group.rows[2][1]).toBe(HOSTS[2]);
  });

  it('g: a refused pre-action flush runs no action, unlocks, shows the refusal, and the next edit saves', async () => {
    const net = installFetch();
    net.replies.push({ body: { success: false, error: 'x', invalid: [{ row: 0, column: 'host', reason: 'comma' }] } });
    const { panel, option, group } = torrentPanel();
    group.rows[0][1] = 'https://placeholder-bad,https://placeholder-evil.invalid';
    panel.editGroup('torrentpotato');
    const field = button(panel);

    await field.execute();

    expect(calls(net)).toEqual(['settings.save_group']);
    expect(group.locked).toBe(false);
    expect(group.actionRunning).toBe(false);
    expect(group.refusal).toHaveLength(1);
    expect(field.result).not.toBe('');
    fieldOf(panel, option).updateRow(0, 1, 'https://placeholder-fixed.invalid/api');
    await vi.advanceTimersByTimeAsync(500);
    expect(net.groupSaves()).toHaveLength(2);
  });

  it('h: an action that answers success false is unlocked at once, with no re-read, rows as flushed', async () => {
    const { net, action, running, panel, option, group } = await startedAction();

    action.resolve({ body: { success: false, error: 'Jackett refused' } });
    await running;

    expect(calls(net)).toEqual(['torrentpotato.jackett_sync']);
    expect(group.locked).toBe(false);
    expect(group.rows).toHaveLength(3);
    fieldOf(panel, option).updateRow(0, 1, 'https://placeholder-next.invalid/api');
    await vi.advanceTimersByTimeAsync(500);
    expect(net.body(net.calls.length - 1).rows).toHaveLength(3);
  });

  it('i: if the re-read fails the group stays locked, says so, and nothing can be saved', async () => {
    const { net, action, running, panel, option, group } = await startedAction([{ status: 500, text: 'no' }]);

    action.resolve({ body: { success: true } });
    await running;

    expect(group.locked).toBe(true);
    expect(group.actionRunning).toBe(false);
    expect(group.reloadError).toBe('Could not reload these rows. Reload the page before changing them.');
    expect(panel.assertiveAnnouncement).toBe(group.reloadError);
    const field = fieldOf(panel, option);
    field.updateRow(0, 1, 'https://placeholder-typed.invalid/api');
    await vi.advanceTimersByTimeAsync(5000);
    await panel.saveGroup('torrentpotato');
    expect(net.groupSaves()).toEqual([]);
    expect(group.dirty).toBe(false);
  });

  it('announces the lock once, and nothing more on unlock', async () => {
    const { action, running, panel } = await startedAction([serverRows([...HOSTS, SYNCED])]);
    const spoken: string[] = [];
    Object.defineProperty(panel, 'politeAnnouncement', { get: () => '', set: (value: string) => { if (value) spoken.push(value); } });

    action.resolve({ body: { success: true } });
    await running;

    expect(spoken).toEqual([]);
  });

  describe('after a re-read that did not give the section\'s rows back', () => {
    /** One press whose action succeeds and whose re-read answers `reread`. */
    async function pressedOnce(reread: Reply | Promise<Reply>) {
      const net = installFetch();
      net.replies.push({ body: { success: true, message: 'Synced' } }, reread);
      const ctx = torrentPanel();
      const field = button(ctx.panel);
      await field.execute();
      return { net, field, ...ctx };
    }

    const FAILED_READ: Reply = { status: 500, text: 'no' };

    it('1: a second press takes the stale lock again, runs the action, re-reads, and clears the error', async () => {
      const { net, panel, group } = await pressedOnce(FAILED_READ);
      expect(group.locked).toBe(true);
      expect(group.actionRunning).toBe(false);
      const before = net.groupSaves().length;
      net.replies.push({ body: { success: true, message: 'Synced' } }, serverRows([...HOSTS, SYNCED]));
      const again = button(panel);

      await again.execute();

      expect(calls(net).filter((name) => name === 'torrentpotato.jackett_sync')).toHaveLength(2);
      expect(net.groupSaves()).toHaveLength(before);
      expect(group.rows).toHaveLength(4);
      expect(group.locked).toBe(false);
      expect(group.reloadError).toBe('');
      expect(group.stale).toBe(false);
      expect(again.success).toBe(true);
    });

    it('1: a stale group is re-read even when the second action answers success false, and never unlocks on stale rows', async () => {
      const { net, panel, group } = await pressedOnce(FAILED_READ);
      net.replies.push({ body: { success: false, error: 'Jackett refused' } }, FAILED_READ);

      await button(panel).execute();
      expect(group.locked).toBe(true);
      expect(group.reloadError).toMatch(/Could not reload/);

      net.replies.push({ body: { success: false, error: 'Jackett refused' } }, serverRows([...HOSTS, SYNCED]));
      await button(panel).execute();
      expect(group.rows).toHaveLength(4);
      expect(group.locked).toBe(false);
    });

    it('1: a second re-read that also fails leaves it locked with the error', async () => {
      const { net, panel, group } = await pressedOnce(FAILED_READ);
      net.replies.push({ body: { success: true } }, FAILED_READ);

      await button(panel).execute();

      expect(group.locked).toBe(true);
      expect(group.actionRunning).toBe(false);
      expect(group.reloadError).toMatch(/Could not reload/);
    });

    it('1: the stale group is not busy, so a pressed button is not shown as running', async () => {
      const { panel, option } = await pressedOnce(FAILED_READ);

      expect(button(panel).busy).toBe(false);
      const field = fieldOf(panel, option);
      expect(field.locked).toBe(true);
      expect(field.running).toBe(false);
    });

    it('2: aria-busy (running) is true while the action runs and false once it ends', async () => {
      const { action, running, panel, option } = await startedAction();
      const field = fieldOf(panel, option);

      expect(field.running).toBe(true);
      action.resolve({ body: { success: false, error: 'x' } });
      await running;
      expect(field.running).toBe(false);
    });

    for (const [name, body] of [
      ['an empty values object', { values: {}, combine_state: {} }],
      ['values without this section\'s combine state', { values: { torrentpotato: torrentValues(HOSTS) }, combine_state: {} }],
      ['a combine state without this section\'s values', { values: {}, combine_state: { torrentpotato: { misaligned: false, rows: 4 } } }],
    ] as const) {
      it(`3: ${name} counts as a failed re-read: stays locked, says so, replaces nothing, saves nothing`, async () => {
        const { net, panel, option, group } = await pressedOnce({ body });

        expect(group.locked).toBe(true);
        expect(group.reloadError).toMatch(/Could not reload/);
        expect(group.rows).toHaveLength(3);
        fieldOf(panel, option).updateRow(0, 1, 'https://placeholder-typed.invalid/api');
        await vi.advanceTimersByTimeAsync(5000);
        expect(net.groupSaves()).toEqual([]);
      });
    }

    it('3: a failed re-read leaves the panel\'s values as they were', async () => {
      const { panel } = await pressedOnce({ body: { values: {}, combine_state: {} } });

      expect(panel.values.torrentpotato.host).toBe(HOSTS.join(','));
    });

    it('4: a re-read that never answers fails after the timeout, instead of showing Running for ever', async () => {
      const net = installFetch();
      net.replies.push({ body: { success: true } });
      (globalThis.fetch as any).mockImplementation(async (url: string, init?: any) => {
        net.calls.push({ url, init });
        if (!url.includes('/settings/')) return { ok: true, status: 200, json: async () => ({ success: true }) };
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        });
      });
      const { panel, group } = torrentPanel();
      const field = button(panel);

      const running = field.execute();
      await vi.advanceTimersByTimeAsync(14000);
      expect(field.running).toBe(true);
      expect(group.reloadError).toBe('');
      await vi.advanceTimersByTimeAsync(1500);
      await running;

      expect(field.running).toBe(false);
      expect(group.locked).toBe(true);
      expect(group.reloadError).toMatch(/Could not reload/);
      expect(panel.assertiveAnnouncement).toBe(group.reloadError);
    });

    it('5: the button stops running even when ending the action throws', async () => {
      installFetch();
      const { panel } = torrentPanel();
      panel.endAction = async () => { throw new Error('boom'); };
      const field = button(panel);

      await field.execute().catch(() => {});

      expect(field.running).toBe(false);
    });
  });

  describe('the panel reporting a failed settings read', () => {
    for (const [name, reply] of [
      ['a JSON 401', { status: 401, body: { success: false, error: 'Unauthorized' } }],
      ['a 200 without values', { body: { success: true } }],
    ] as const) {
      it(`shows the load-failed state for ${name}`, async () => {
        installFetch().replies.push(reply as Reply);
        const { panel } = torrentPanel();
        panel.toast = vi.fn();
        panel.loadVersionInfo = vi.fn();

        await panel.init();

        expect(panel.toast).toHaveBeenCalledWith('Failed to load settings', 'error');
        expect(panel.loadVersionInfo).not.toHaveBeenCalled();
        expect(panel.loading).toBe(false);
      });
    }
  });

  it('a section with no combine group is not locked, and runs the action', async () => {
    const net = installFetch();
    net.replies.push({ body: { success: true, message: 'Done' } });
    const { panel } = torrentPanel();
    const { buttonField } = loadComponents();
    const field = buttonField('core', { button_action: 'core.something', name: 'something' });
    field.getPanel = () => panel;

    await field.execute();

    expect(calls(net)).toEqual(['core.something']);
    expect(field.busy).toBe(false);
  });
});

describe('removing a row from a combined field (SEC-004 AC-DESIGN-8, AC-A11Y-7)', () => {
  /**
   * A field over the real panel, with a stand-in for the part of the page this file does not
   * have: a root whose querySelector hands back one focus spy per selector, and a $nextTick
   * the test flushes by hand, so "after Alpine has re-rendered" is a moment the test controls.
   */
  function fieldWith(rows: number) {
    const panel = aligned();
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    const spies = new Map<string, { focus: ReturnType<typeof vi.fn> }>();
    const queued: Array<() => void> = [];
    field.getPanel = () => panel;
    field.$nextTick = (callback: () => void) => { queued.push(callback); };
    // In init() Alpine's $el is the field's root. From a click handler it is the button that
    // was pressed, which the removal has just taken out of the page: its querySelector finds
    // nothing. So the root is given to init() and $el is then swapped for the dead button.
    field.$el = {
      querySelector: (selector: string) => {
        if (!spies.has(selector)) spies.set(selector, { focus: vi.fn() });
        return spies.get(selector);
      },
    };
    field.init();
    field.$el = { querySelector: () => null };
    while (field.held.rows.length > rows) field.held.rows.pop();
    return {
      field,
      panel,
      focused: () => [...spies.entries()].filter(([, spy]) => spy.focus.mock.calls.length > 0).map(([selector]) => selector),
      render: () => { while (queued.length) queued.shift()!(); },
    };
  }

  const polite = (panel: any) => {
    // The panel's announce() clears the region then sets it on the next tick; the unit
    // harness runs $nextTick at once, so the final text is what a reader would hear.
    return panel.politeAnnouncement;
  };

  for (const [name, index, target] of [
    ['the first', 0, '[data-row-remove="0"]'],
    ['a middle', 1, '[data-row-remove="1"]'],
  ] as const) {
    it(`removing ${name} of three rows hands focus to the Remove button now at that index, after the render`, () => {
      const { field, focused, render } = fieldWith(3);

      field.removeRow(index);

      expect(field.focusTarget).toEqual({ kind: 'remove', index });
      expect(focused()).toEqual([]);
      render();
      expect(focused()).toEqual([target]);
    });
  }

  it('removing the last of three rows hands focus to the previous row\'s Remove button', () => {
    const { field, focused, render } = fieldWith(3);

    field.removeRow(2);

    expect(field.focusTarget).toEqual({ kind: 'remove', index: 1 });
    render();
    expect(focused()).toEqual(['[data-row-remove="1"]']);
  });

  for (const index of [0, 1]) {
    it(`removing row ${index + 1} of two rows leaves one row, so no Remove button: focus goes to Add`, () => {
      const { field, focused, render } = fieldWith(2);

      field.removeRow(index);

      expect(field.rows).toHaveLength(1);
      expect(field.focusTarget).toEqual({ kind: 'add' });
      render();
      expect(focused()).toEqual(['[data-row-add]']);
    });
  }

  it('the target is spent once it has been used', () => {
    const { field, render } = fieldWith(3);

    field.removeRow(0);
    render();

    expect(field.focusTarget).toBeNull();
  });

  for (const [index, text] of [[0, 'Row 1 removed. Undo is available.'], [1, 'Row 2 removed. Undo is available.'], [2, 'Row 3 removed. Undo is available.']] as const) {
    it(`announces "${text}" once, politely`, () => {
      const { field, panel, render } = fieldWith(3);
      const spoken: Array<[string, boolean | undefined]> = [];
      const announce = panel.announce.bind(panel);
      panel.announce = (message: string, assertive?: boolean) => { spoken.push([message, assertive]); announce(message, assertive); };

      field.removeRow(index);
      render();

      expect(spoken.filter(([message]) => message.startsWith('Row '))).toEqual([[text, false]]);
      expect(polite(panel)).toBe(text);
      expect(panel.assertiveAnnouncement).toBe('');
    });
  }

  for (const index of [0, 1, 2]) {
    it(`removing row ${index + 1} of three removes exactly that row, and saves the rest as one group save`, async () => {
      const net = installFetch();
      const { field } = fieldWith(3);
      const hosts = ['one', 'two', 'three'].map((word) => `https://placeholder-${word}.invalid/api`);
      const kept = hosts.filter((_, position) => position !== index);

      field.removeRow(index);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);

      expect(field.rows.map((row: string[]) => row[1])).toEqual(kept);
      expect(net.groupSaves()).toHaveLength(1);
      expect(net.body(0).rows.map((row: any) => row.host)).toEqual(kept);
    });
  }

  it('offers a Remove control only while more than one row remains', () => {
    const { field } = fieldWith(3);

    expect(field.canRemove).toBe(true);
    field.removeRow(0);
    expect(field.canRemove).toBe(true);
    field.removeRow(0);
    expect(field.rows).toHaveLength(1);
    expect(field.canRemove).toBe(false);
  });

  it('a removal on the last row does nothing: no change, no focus move, no announcement, no save', async () => {
    const net = installFetch();
    const { field, panel, focused, render } = fieldWith(1);

    field.removeRow(0);
    render();
    await vi.advanceTimersByTimeAsync(1000);

    expect(field.rows).toHaveLength(1);
    expect(field.focusTarget).toBeNull();
    expect(focused()).toEqual([]);
    expect(polite(panel)).toBe('');
    expect(net.groupSaves()).toHaveLength(0);
  });

  it('a locked group\'s removal does nothing and announces nothing', async () => {
    const net = installFetch();
    const { field, panel, focused, render } = fieldWith(3);
    field.held.locked = true;

    field.removeRow(1);
    render();
    await vi.advanceTimersByTimeAsync(1000);

    expect(field.rows).toHaveLength(3);
    expect(field.focusTarget).toBeNull();
    expect(focused()).toEqual([]);
    expect(polite(panel)).toBe('');
    expect(net.groupSaves()).toHaveLength(0);
  });
});

describe('a held key on the Remove and Add buttons (SEC-004 AC-A11Y-7)', () => {
  const press = (key: string, repeat: boolean) => ({ key, repeat, preventDefault: vi.fn() });
  function heldKeyField() {
    const panel = aligned();
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    field.getPanel = () => panel;
    return field;
  }

  it('prevents the repeat of an Enter, which would otherwise activate the next control focus lands on', () => {
    const event = press('Enter', true);

    heldKeyField().ignoreHeldKey(event);

    expect(event.preventDefault).toHaveBeenCalledTimes(1);
  });

  for (const [name, event] of [
    ['the first keydown of an Enter', press('Enter', false)],
    ['a repeated Space', press(' ', true)],
    ['a first Space', press(' ', false)],
    ['a repeated Tab, which must keep moving focus', press('Tab', true)],
    ['a first Tab', press('Tab', false)],
  ] as const) {
    it(`leaves ${name} alone`, () => {
      heldKeyField().ignoreHeldKey(event);

      expect(event.preventDefault).not.toHaveBeenCalled();
    });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Owner decision 2026-11-18: a removal waits an undo window before it is saved, and the
// way back (Undo) stays until the group is next touched. The state is on the PANEL, as the
// rows are, because the field is rebuilt on every tab change.
// ─────────────────────────────────────────────────────────────────────────────
describe('removing a row, with a way back (owner decision 2026-11-18)', () => {
  const HOSTS = ['one', 'two', 'three'].map((word) => `https://placeholder-${word}.invalid/api`);

  function fieldOver(panel = aligned()) {
    const { combinedField } = loadComponents();
    const field = combinedField('newznab', combinedOption(panel.options));
    const queued: Array<() => void> = [];
    field.getPanel = () => panel;
    field.$nextTick = (callback: () => void) => { queued.push(callback); };
    const spies = new Map<string, { focus: ReturnType<typeof vi.fn> }>();
    field.$el = {
      querySelector: (selector: string) => {
        if (!spies.has(selector)) spies.set(selector, { focus: vi.fn() });
        return spies.get(selector);
      },
    };
    field.init();
    return {
      field,
      panel,
      render: () => { while (queued.length) queued.shift()!(); },
      focused: () => [...spies.entries()].filter(([, spy]) => spy.focus.mock.calls.length > 0).map(([selector]) => selector),
    };
  }

  const hostsSent = (net: ReturnType<typeof installFetch>, call: number) => net.body(call).rows.map((row: any) => row.host);

  it('waits the named undo window, 8 seconds, and sends nothing before it ends', async () => {
    const net = installFetch();
    const { field } = fieldOver();

    field.removeRow(1);
    await vi.advanceTimersByTimeAsync(UNDO_WINDOW - 1);
    expect(net.calls).toEqual([]);

    await vi.advanceTimersByTimeAsync(1);
    expect(net.groupSaves()).toHaveLength(1);
    expect(hostsSent(net, 0)).toEqual([HOSTS[0], HOSTS[2]]);
    expect(undoWindowMs()).toBe(UNDO_WINDOW);
  });

  it('holds the removal on the panel: the row index and every cell, and the line says only the row number', () => {
    const { field, panel } = fieldOver();

    field.removeRow(1);

    const group = panel.groupState.newznab;
    expect(group.removal.index).toBe(1);
    expect(group.removal.cells).toEqual(['0', HOSTS[1], 'placeholder-key-two', '10', 'tag-two']);
    expect(field.removedLine).toBe('Row 2 removed.');
    expect(field.held).toBe(group);
  });

  for (const [name, index, rowsLeft, under] of [
    ['the first row', 0, 2, 0],
    ['a middle row', 1, 2, 1],
    ['the last row', 2, 2, 1],
  ] as const) {
    it(`draws the line under the row that took the place of ${name}: the row focus lands on, so Undo is the next Tab stop`, () => {
      const { field } = fieldOver();

      expect(field.removedAfter).toBe(-1);
      field.removeRow(index);

      expect(field.rows).toHaveLength(rowsLeft);
      expect(field.removedAfter).toBe(under);
      expect(field.focusTarget).toEqual({ kind: 'remove', index: under });
    });
  }

  it('with one row left the line is under that row, and focus goes to Add', () => {
    const { field } = fieldOver();
    field.removeRow(0);
    field.removeRow(0);

    expect(field.rows).toHaveLength(1);
    expect(field.removedAfter).toBe(0);
    expect(field.focusTarget).toEqual({ kind: 'add' });
  });

  it('keeps the removal across a rebuilt field: a second field over the same panel still offers Undo', () => {
    const { field, panel } = fieldOver();
    field.removeRow(0);

    const rebuilt = fieldOver(panel).field;

    expect(rebuilt.held.removal).not.toBeNull();
    expect(rebuilt.removedLine).toBe('Row 1 removed.');
  });

  it('says nothing about a cell value in the announcement, the line or the console', async () => {
    installFetch();
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((method) => vi.spyOn(console, method).mockImplementation(() => {}));
    const { field, panel, render } = fieldOver();
    const spoken: string[] = [];
    const announce = panel.announce.bind(panel);
    panel.announce = (message: string, assertive?: boolean) => { spoken.push(message); announce(message, assertive); };

    field.removeRow(1);
    render();
    field.undoRemoval();
    render();
    field.removeRow(2);
    await vi.advanceTimersByTimeAsync(UNDO_WINDOW);

    const everything = JSON.stringify([spoken, field.removedLine, spies.map((spy) => spy.mock.calls)]);
    for (const secret of [...HOSTS, 'placeholder-key-one', 'placeholder-key-two', 'placeholder-key-three', 'tag-one', 'tag-two', 'tag-three']) {
      expect(everything).not.toContain(secret);
    }
    spies.forEach((spy) => spy.mockRestore());
  });

  describe('Undo during the window', () => {
    it('puts the row back at its index with every cell as it was, and sends nothing, ever, when nothing else changed', async () => {
      const net = installFetch();
      const { field, panel } = fieldOver();
      const before = JSON.stringify(field.held.rows);

      field.removeRow(1);
      await vi.advanceTimersByTimeAsync(3000);
      field.undoRemoval();
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW * 3);

      expect(JSON.stringify(field.held.rows)).toBe(before);
      expect(net.calls).toEqual([]);
      expect(panel.groupState.newznab.dirty).toBe(false);
      expect(panel.groupState.newznab.timer).toBeNull();
      expect(field.held.removal).toBeNull();
    });

    for (const index of [0, 1, 2]) {
      it(`restores row ${index + 1} of three at index ${index}, and hands focus to its Remove button after the render`, () => {
        const { field, render, focused } = fieldOver();
        const before = JSON.stringify(field.held.rows);

        field.removeRow(index);
        render();
        field.undoRemoval();
        expect(field.focusTarget).toEqual({ kind: 'remove', index });
        render();

        expect(JSON.stringify(field.held.rows)).toBe(before);
        expect(focused()).toContain(`[data-row-remove="${index}"]`);
      });
    }

    it('announces "Row N restored." once, politely', () => {
      const { field, panel, render } = fieldOver();
      field.removeRow(1);
      render();
      const spoken: Array<[string, boolean | undefined]> = [];
      const announce = panel.announce.bind(panel);
      panel.announce = (message: string, assertive?: boolean) => { spoken.push([message, assertive]); announce(message, assertive); };

      field.undoRemoval();
      render();

      expect(spoken).toEqual([['Row 2 restored.', false]]);
    });

    it('sends one request when something else is also unsaved, with the restored rows and that edit', async () => {
      const net = installFetch();
      const { field, panel } = fieldOver();
      field.held.rows[2][2] = 'placeholder-key-edited';
      panel.editGroup('newznab');

      field.removeRow(0);
      field.undoRemoval();
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW * 2);

      expect(net.groupSaves()).toHaveLength(1);
      expect(hostsSent(net, 0)).toEqual(HOSTS);
      expect(net.body(0).rows[2].api_key).toBe('placeholder-key-edited');
    });

    it('is refused while the group is locked, and does nothing when there is nothing to undo', () => {
      const { field, render } = fieldOver();
      field.removeRow(1);
      render();
      field.held.locked = true;

      field.undoRemoval();
      expect(field.rows).toHaveLength(2);

      field.held.locked = false;
      field.held.removal = null;
      field.undoRemoval();
      expect(field.rows).toHaveLength(2);
      expect(field.focusTarget).toBeNull();
    });
  });

  describe('the line and Undo outlive the window (WCAG 2.2.1)', () => {
    it('are still offered after the delayed save has landed', async () => {
      installFetch();
      const { field } = fieldOver();

      field.removeRow(1);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
      await vi.advanceTimersByTimeAsync(60000);

      expect(field.held.dirty).toBe(false);
      expect(field.held.removal).not.toBeNull();
      expect(field.removedLine).toBe('Row 2 removed.');
    });

    it('Undo after the save landed puts the row back and saves the group through the normal save: one request', async () => {
      const net = installFetch();
      const { field } = fieldOver();
      field.removeRow(1);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
      expect(net.groupSaves()).toHaveLength(1);

      field.undoRemoval();
      await vi.advanceTimersByTimeAsync(500);

      expect(net.groupSaves()).toHaveLength(2);
      expect(hostsSent(net, 1)).toEqual(HOSTS);
      expect(net.body(1).rows[1].api_key).toBe('placeholder-key-two');
      expect(net.body(1).rows[1].custom_tag).toBe('tag-two');
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW * 2);
      expect(net.groupSaves()).toHaveLength(2);
      expect(field.held.removal).toBeNull();
    });

    it('Undo while the delayed save is in flight puts the row back and saves the full rows right after it', async () => {
      const net = installFetch();
      const first = deferred<Reply>();
      net.replies.push(first.promise);
      const { field } = fieldOver();
      field.removeRow(1);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
      expect(net.groupSaves()).toHaveLength(1);

      field.undoRemoval();
      await vi.advanceTimersByTimeAsync(500);
      expect(net.groupSaves()).toHaveLength(1);
      first.resolve({ body: { success: true } });
      await vi.advanceTimersByTimeAsync(0);

      expect(net.groupSaves()).toHaveLength(2);
      expect(hostsSent(net, 1)).toEqual(HOSTS);
    });
  });

  describe('when the line goes', () => {
    it('on an edit to a cell, which follows the normal 500 ms debounce and carries the removal with it in one request', async () => {
      const net = installFetch();
      const { field } = fieldOver();
      field.removeRow(0);

      field.updateRow(1, 2, 'placeholder-key-edited');
      expect(field.held.removal).toBeNull();
      await vi.advanceTimersByTimeAsync(499);
      expect(net.calls).toEqual([]);
      await vi.advanceTimersByTimeAsync(1);

      expect(net.groupSaves()).toHaveLength(1);
      expect(hostsSent(net, 0)).toEqual([HOSTS[1], HOSTS[2]]);
      expect(net.body(0).rows[1].api_key).toBe('placeholder-key-edited');
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW * 2);
      expect(net.groupSaves()).toHaveLength(1);
    });

    it('on adding a row, which saves nothing by itself, and the removal is saved when the window ends', async () => {
      const net = installFetch();
      const { field } = fieldOver();
      field.removeRow(0);

      field.addRow();

      expect(field.held.removal).toBeNull();
      expect(field.rows).toHaveLength(3);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
      expect(net.groupSaves()).toHaveLength(1);
    });

    it('on a second removal, which replaces it: only the latest is undoable and the first is committed with the next save', async () => {
      const net = installFetch();
      const { field } = fieldOver();
      field.removeRow(0);
      await vi.advanceTimersByTimeAsync(3000);

      field.removeRow(1);
      expect(field.held.removal.index).toBe(1);
      expect(field.held.removal.cells[1]).toBe(HOSTS[2]);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW - 1);
      expect(net.calls).toEqual([]);
      await vi.advanceTimersByTimeAsync(1);
      expect(hostsSent(net, 0)).toEqual([HOSTS[1]]);

      field.undoRemoval();
      await vi.advanceTimersByTimeAsync(500);

      expect(field.rows.map((row: string[]) => row[1])).toEqual([HOSTS[1], HOSTS[2]]);
      expect(hostsSent(net, 1)).toEqual([HOSTS[1], HOSTS[2]]);
    });

    it('when the group is locked for a button, and its pending removal is sent at once before the action', async () => {
      const net = installFetch();
      const { field, panel } = fieldOver();
      field.removeRow(1);

      expect(panel.lockGroup('newznab')).toBe(true);
      expect(field.held.removal).toBeNull();
      expect(await panel.flushGroupFor('newznab')).toBe(true);

      expect(net.groupSaves()).toHaveLength(1);
      expect(hostsSent(net, 0)).toEqual([HOSTS[0], HOSTS[2]]);
    });

    it('when the rows are replaced by a re-read', () => {
      const { field, panel } = fieldOver();
      field.removeRow(1);
      field.held.timer = null;
      field.held.dirty = false;

      panel.reloadCleanGroups();

      expect(field.held.removal).toBeNull();
    });
  });

  describe('a pending removal is never waited on or dropped', () => {
    it('flushPendingSaves sends it now, with the rows as on screen', async () => {
      const net = installFetch();
      const { field, panel } = fieldOver();
      field.removeRow(2);

      await panel.flushPendingSaves();

      expect(net.groupSaves()).toHaveLength(1);
      expect(hostsSent(net, 0)).toEqual([HOSTS[0], HOSTS[1]]);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW * 2);
      expect(net.groupSaves()).toHaveLength(1);
    });

    it('a Test connection press sends it first, so the test runs against the rows on screen', async () => {
      const net = installFetch();
      net.replies.push({ body: { success: true } }, { body: { success: true } });
      const { field, panel } = fieldOver();
      field.removeRow(2);

      await panel.testProvider({ section: 'newznab', list: 'nzb_providers' });

      expect(net.calls.map((call) => call.url)).toEqual([
        '/api/placeholder-api-key/settings.save_group/',
        '/api/placeholder-api-key/provider.newznab.test/',
      ]);
      expect(hostsSent(net, 0)).toEqual([HOSTS[0], HOSTS[1]]);
    });

    it('leaving the page sends it, with keepalive so the browser finishes the request', async () => {
      const net = installFetch();
      const { field, panel } = fieldOver();
      field.removeRow(2);

      panel.flushGroupsOnLeave();

      expect(net.groupSaves()).toHaveLength(1);
      expect(net.calls[0].init.keepalive).toBe(true);
      expect(hostsSent(net, 0)).toEqual([HOSTS[0], HOSTS[1]]);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW * 2);
      expect(net.groupSaves()).toHaveLength(1);
    });

    it('leaving the page sends a removal that is queued behind a save in flight, once', async () => {
      const net = installFetch();
      const first = deferred<Reply>();
      net.replies.push(first.promise);
      const { field, panel } = fieldOver();
      field.removeRow(0);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
      expect(net.groupSaves()).toHaveLength(1);
      // The first save is still in flight; the next removal's save comes due and queues behind it.
      field.removeRow(0);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
      expect(panel.groupState.newznab).toMatchObject({ saving: true, queued: true, timer: null });

      panel.flushGroupsOnLeave();

      expect(net.groupSaves()).toHaveLength(2);
      expect(net.calls[1].init.keepalive).toBe(true);
      expect(hostsSent(net, 1)).toEqual([HOSTS[2]]);
      expect(panel.groupState.newznab.queued).toBe(false);
    });

    it('leaving the page with nothing pending sends nothing, and a locked group sends nothing', () => {
      const net = installFetch();
      const { field, panel } = fieldOver();
      panel.flushGroupsOnLeave();
      field.removeRow(1);
      field.held.locked = true;

      panel.flushGroupsOnLeave();

      expect(net.calls).toEqual([]);
    });
  });

  describe('a refused or failed save, and Undo', () => {
    const comma = (row: number) => ({ body: { success: false, error: 'x', invalid: [{ row, column: 'host', reason: 'comma' }] } });

    it('moves the marks back to the rows they describe', () => {
      const { field } = fieldOver();
      field.held.refusal = [{ row: 2, column: 'host', reason: 'comma', message: 'Row 3: x' }];
      field.held.refusalKey = '2:host:comma';

      field.removeRow(0);
      expect(field.held.refusal.map((entry: any) => entry.row)).toEqual([1]);
      field.undoRemoval();

      expect(field.held.refusal.map((entry: any) => entry.row)).toEqual([2]);
      expect(field.held.refusal[0].message).toMatch(/^Row 3:/);
      expect(field.held.refusalKey).toBe('2:host:comma');
    });

    it('a removal whose save failed: Undo restores the rows the user saw and saves exactly them, once', async () => {
      const net = installFetch();
      net.replies.push({ status: 500, text: 'oops' });
      const { field } = fieldOver();
      field.removeRow(1);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
      expect(net.groupSaves()).toHaveLength(1);
      expect(field.held.error).not.toBe('');

      field.undoRemoval();
      await vi.advanceTimersByTimeAsync(500);

      expect(net.groupSaves()).toHaveLength(2);
      expect(hostsSent(net, 1)).toEqual(HOSTS);
      expect(field.held.error).toBe('');
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW * 2);
      expect(net.groupSaves()).toHaveLength(2);
    });

    it('a removal whose save was refused for another row: Undo restores the row and the next save is judged afresh', async () => {
      const net = installFetch();
      // The comma is in row 3 (index 2). With row 1 removed the server numbers it 2 (index 1); back, 3 again.
      net.replies.push(comma(2), comma(1), comma(2));
      const { field, panel } = fieldOver();
      field.held.rows[2][1] = 'https://placeholder-bad,https://placeholder-evil.invalid';
      panel.editGroup('newznab');
      await vi.advanceTimersByTimeAsync(500);

      field.removeRow(0);
      await vi.advanceTimersByTimeAsync(UNDO_WINDOW);
      expect(field.held.refusal.map((entry: any) => entry.row)).toEqual([1]);

      field.undoRemoval();
      await vi.advanceTimersByTimeAsync(500);

      expect(net.groupSaves()).toHaveLength(3);
      expect(net.body(2).rows).toHaveLength(3);
      expect(net.body(2).rows[0].host).toBe(HOSTS[0]);
      expect(field.held.refusal.map((entry: any) => entry.row)).toEqual([2]);
    });
  });
});
