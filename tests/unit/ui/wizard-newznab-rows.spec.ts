// @vitest-environment node
/**
 * SEC-004 P5: the setup wizard's Newznab row logic, as pure functions.
 *
 * The wizard becomes a read-then-overwrite writer of every Newznab credential a user
 * has stored, so the part that decides WHAT is written has no DOM and no network and
 * is pinned here, exhaustively. It runs the REAL functions from wizard.html (the
 * script block is read from the template and evaluated, as settings-group-save.spec.ts
 * does for the Settings page), and it feeds them the REAL settings read: each
 * fixture is loaded into the real `Settings` and `Settings.view()` is printed by
 * tests/helpers/settings_view.py, so the Definitions' worked cases reach this code as
 * the server states them, not as a hand-written payload that could be gentler.
 *
 * Hosts are `.invalid` and every credential is a `placeholder-` string.
 */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve(__dirname, '../../..');
const TEMPLATE = path.join(ROOT, 'couchpotato/ui/templates/wizard.html');
const VENV_PYTHON = path.join(ROOT, '.venv/bin/python');
const PYTHON = process.env.PYTHON || (fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3');

type Row = Record<string, string>;
type Entry = { host: string; api_key: string; source: number | null };
type Baseline = { rows: Row[]; shown: boolean[] };
type Read = { ok: boolean; misaligned?: boolean; enabled?: boolean; rows?: Row[]; shown?: boolean[] };
type Built = { rows: Row[]; origins: (number | null)[] };

type Logic = {
  newznabReadStored: (payload: unknown) => Read;
  newznabInitialEntries: (read: Read) => Entry[];
  newznabBuildRows: (baseline: Baseline, entries: Entry[]) => Built;
  newznabRowsChanged: (baseline: Baseline, rows: Row[]) => boolean;
  newznabEntryForRow: (origins: (number | null)[], row: unknown) => number;
  newznabAfterSave: (built: Built, entries: Entry[]) => { baseline: Baseline; entries: Entry[] };
  newznabShownEnabled: (read: Read) => boolean;
};

function loadLogic(): Logic {
  const html = fs.readFileSync(TEMPLATE, 'utf8');
  const code = html.slice(html.indexOf('<script>') + '<script>'.length, html.lastIndexOf('</script>'));
  return new Function(`${code}
return { newznabReadStored, newznabInitialEntries, newznabBuildRows, newznabRowsChanged,
         newznabEntryForRow, newznabAfterSave, newznabShownEnabled };`)();
}

const logic = loadLogic();

const payloads = new Map<string, any>();
/** The real `Settings.view()` (newznab only) for a named starting configuration. */
function view(fixture: string): any {
  if (!payloads.has(fixture)) {
    payloads.set(fixture, JSON.parse(execFileSync(
      PYTHON, ['-m', 'tests.helpers.settings_view', fixture],
      { cwd: ROOT, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] },
    )));
  }
  return structuredClone(payloads.get(fixture));
}

const ALIGNED = [
  'fresh_defaults',
  'newznab_aligned',
  'newznab_wizard_written',
  'newznab_key_in_row_four',
  'newznab_untrimmed',
  'newznab_legacy_bytes',
  'newznab_two_stored',
  'newznab_interleaved',
  'newznab_hostless',
  'newznab_hostile_cells',
];
const MISALIGNED = ['newznab_misaligned_key_short', 'newznab_misaligned_use_short'];
const COLUMNS = ['use', 'host', 'api_key', 'extra_score', 'custom_tag'];
const DEFAULTS = { use: '1', extra_score: '0', custom_tag: '' };
const EMPTY_ROW = { use: '', host: '', api_key: '', extra_score: '', custom_tag: '' };

const isStored = (row: Row) => row.host.trim() !== '' && row.api_key.trim() !== '';

function start(fixture: string) {
  const read = logic.newznabReadStored(view(fixture));
  expect(read.ok, `${fixture} must read`).toBe(true);
  const baseline: Baseline = { rows: structuredClone(read.rows!), shown: structuredClone(read.shown!) };
  return { read, baseline, entries: logic.newznabInitialEntries(read) };
}

const build = (baseline: Baseline, entries: Entry[]) => logic.newznabBuildRows(baseline, entries);

describe('reading the stored rows', () => {
  it.each(ALIGNED)('%s: the rows are the real row count, all five columns, in stored order', (fixture) => {
    const payload = view(fixture);
    const read = logic.newznabReadStored(payload);

    expect(read.ok).toBe(true);
    expect(read.misaligned).toBe(false);
    expect(read.rows).toHaveLength(payload.combine_state.newznab.rows);
    for (const row of read.rows!) expect(Object.keys(row).sort()).toEqual([...COLUMNS].sort());
  });

  it('classifies the interleaved fixture: A and B are shown, the keyless defaults are not', () => {
    const { read } = start('newznab_interleaved');

    expect(read.shown).toEqual([false, true, false, true, false]);
  });

  it('classifies a hostless row that carries a key as hidden', () => {
    const { read } = start('newznab_hostless');

    expect(read.shown).toEqual([false, true, false, true]);
    expect(read.rows![2].api_key).toBe('placeholder-key-hostless');
    expect(read.rows![2].host).toBe('');
  });

  it('shows a fresh install (six keyless defaults) as one blank row and not as configured', () => {
    const { read, entries } = start('fresh_defaults');

    expect(read.rows).toHaveLength(6);
    expect(read.shown).toEqual([false, false, false, false, false, false]);
    expect(entries).toEqual([{ host: '', api_key: '', source: null }]);
    expect(logic.newznabShownEnabled(read)).toBe(false);
  });

  it('shows one entry per stored indexer in stored order, with the stored text as stored', () => {
    const { read, entries } = start('newznab_two_stored');

    expect(entries).toEqual([
      { host: read.rows![0].host, api_key: read.rows![0].api_key, source: 0 },
      { host: read.rows![1].host, api_key: read.rows![1].api_key, source: 1 },
    ]);
    expect(logic.newznabShownEnabled(read)).toBe(true);
  });

  it('shows Newznab enabled only when it is on AND an indexer is stored', () => {
    const stored = view('newznab_two_stored');
    const off = view('newznab_two_stored');
    off.values.newznab.enabled = false;
    const bare = view('fresh_defaults');

    expect(logic.newznabShownEnabled(logic.newznabReadStored(stored))).toBe(true);
    expect(logic.newznabShownEnabled(logic.newznabReadStored(off))).toBe(false);
    expect(bare.values.newznab.enabled).toBe(true);
    expect(logic.newznabShownEnabled(logic.newznabReadStored(bare))).toBe(false);
  });

  it('does not trim what it reads: a cell with spaces is shown as stored', () => {
    const { read } = start('newznab_untrimmed');

    expect(read.rows![1].host.startsWith(' ')).toBe(true);
  });

  it('reads a legacy bytes-literal group as the rows it holds', () => {
    const { read } = start('newznab_legacy_bytes');

    expect(read.rows!.map((row) => row.api_key)).toEqual(['placeholder-key-one', 'placeholder-key-two']);
  });

  it.each(MISALIGNED)('%s: a misaligned group reads as misaligned with NO rows to edit', (fixture) => {
    const read = logic.newznabReadStored(view(fixture));

    expect(read.ok).toBe(true);
    expect(read.misaligned).toBe(true);
    expect(read.rows ?? []).toEqual([]);
  });

  it('a short non-pairing column supplies its declared default, a short use cell is 0', () => {
    const payload = view('newznab_two_stored');
    payload.values.newznab.extra_score = '5';
    payload.values.newznab.custom_tag = '';
    const read = logic.newznabReadStored(payload);

    expect(read.ok).toBe(true);
    expect(read.rows![1].extra_score).toBe('0');
    expect(read.rows![1].custom_tag).toBe('');
  });

  it('a column all of whose cells are empty may be shorter than the row count (it is ignored)', () => {
    const payload = view('newznab_two_stored');
    payload.values.newznab.use = '';
    const read = logic.newznabReadStored(payload);

    expect(read.ok).toBe(true);
    expect(read.rows!.map((row) => row.use)).toEqual(['', '0']);
  });

  describe('a read that is not a complete, trustworthy answer is NOT an empty install', () => {
    const cases: [string, (payload: any) => unknown][] = [
      ['nothing at all', () => undefined],
      ['null', () => null],
      ['a string', () => 'oops'],
      ['an empty object', () => ({})],
      ['the API refusal body', () => ({ success: false, error: 'API call doesn\'t exist' })],
      ['newznab missing from values', (p) => { delete p.values.newznab; return p; }],
      ['newznab missing from combine_state', (p) => { delete p.combine_state.newznab; return p; }],
      ['values not an object', (p) => { p.values = 'x'; return p; }],
      ['combine_state absent', (p) => { delete p.combine_state; return p; }],
      ['options absent', (p) => { delete p.options; return p; }],
      ['misaligned not a boolean', (p) => { p.combine_state.newznab.misaligned = 'false'; return p; }],
      ['a row count of zero', (p) => { p.combine_state.newznab.rows = 0; return p; }],
      ['a fractional row count', (p) => { p.combine_state.newznab.rows = 2.5; return p; }],
      ['a row count that is not a number', (p) => { p.combine_state.newznab.rows = '2'; return p; }],
      ['a null cell', (p) => { p.values.newznab.host = null; return p; }],
      ['an array cell', (p) => { p.values.newznab.api_key = ['a']; return p; }],
      ['an object cell', (p) => { p.values.newznab.use = {}; return p; }],
      ['a boolean cell', (p) => { p.values.newznab.custom_tag = true; return p; }],
      ['a missing column', (p) => { delete p.values.newznab.api_key; return p; }],
      ['enabled missing', (p) => { delete p.values.newznab.enabled; return p; }],
      ['a column the wizard does not know about', (p) => {
        p.options.newznab.groups[0].options.find((o: any) => o.type === 'combined').combine.push('extra');
        return p;
      }],
      ['a column the declaration no longer has', (p) => {
        p.options.newznab.groups[0].options.find((o: any) => o.type === 'combined').combine.pop();
        return p;
      }],
      ['a stored pairing column whose count disagrees with the row count, not flagged misaligned', (p) => {
        p.values.newznab.api_key = 'placeholder-key-one';
        return p;
      }],
    ];
    it.each(cases)('%s', (_name, mutate) => {
      const payload = mutate(view('newznab_two_stored'));

      expect(logic.newznabReadStored(payload).ok).toBe(false);
    });
  });
});

describe('no change: loading and building with nothing edited changes nothing (every fixture)', () => {
  it.each(ALIGNED)('%s: the built rows ARE the baseline and no save is wanted', (fixture) => {
    const { baseline, entries } = start(fixture);
    const before = structuredClone(baseline);

    const built = build(baseline, entries);

    expect(built.rows).toEqual(baseline.rows);
    expect(logic.newznabRowsChanged(baseline, built.rows)).toBe(false);
    expect(baseline).toEqual(before);
  });

  it('building does not mutate the baseline or the entries', () => {
    const { baseline, entries } = start('newznab_interleaved');
    entries[0].host = 'https://placeholder-changed.invalid/api';
    const before = structuredClone({ baseline, entries });

    const built = build(baseline, entries);
    built.rows[0].host = 'tampered';

    expect({ baseline, entries }).toEqual(before);
  });

  it('typing and then restoring the same text is not a change', () => {
    const { baseline, entries } = start('newznab_two_stored');
    const original = entries[1].api_key;
    entries[1].api_key = original + 'x';
    entries[1].api_key = original;

    expect(logic.newznabRowsChanged(baseline, build(baseline, entries).rows)).toBe(false);
  });

  it('an added row with no URL, or a key and no URL, is not a change', () => {
    const { baseline, entries } = start('newznab_interleaved');
    entries.push({ host: '', api_key: '', source: null });
    entries.push({ host: '   ', api_key: 'placeholder-key-orphan', source: null });

    const built = build(baseline, entries);

    expect(built.rows).toEqual(baseline.rows);
    expect(logic.newznabRowsChanged(baseline, built.rows)).toBe(false);
  });

  it('padding only: a trim-only edit that stores the same text is not a change', () => {
    const { baseline, entries } = start('newznab_two_stored');
    entries[0].host = ` ${entries[0].host} `;

    expect(logic.newznabRowsChanged(baseline, build(baseline, entries).rows)).toBe(false);
  });
});

function displayedEntries(fixture: string) {
  const { baseline, entries } = start(fixture);
  return { baseline, entries, shownIndices: baseline.shown.flatMap((shown, index) => (shown ? [index] : [])) };
}

describe('editing one displayed row changes that row only (every fixture with a displayed row)', () => {
  const WITH_ROWS = ALIGNED.filter((fixture) => fixture !== 'fresh_defaults');

  for (const fixture of WITH_ROWS) {
    const { shownIndices } = displayedEntries(fixture);
    for (const at of shownIndices) {
      it(`${fixture}: a new URL in stored row ${at}: every other row is the same strings in the same place`, () => {
        const { baseline, entries } = displayedEntries(fixture);
        const entry = entries.findIndex((e) => e.source === at);
        entries[entry].host = '  https://placeholder-edited.invalid/api  ';

        const built = build(baseline, entries);

        expect(built.rows).toHaveLength(baseline.rows.length);
        baseline.rows.forEach((row, index) => {
          if (index === at) {
            expect(built.rows[index]).toEqual({
              ...row, host: 'https://placeholder-edited.invalid/api', api_key: row.api_key.trim(),
            });
          } else {
            expect(built.rows[index]).toEqual(row);
          }
        });
        expect(logic.newznabRowsChanged(baseline, built.rows)).toBe(true);
      });

      it(`${fixture}: a new key in stored row ${at} keeps its own use, extra_score and custom_tag`, () => {
        const { baseline, entries } = displayedEntries(fixture);
        const entry = entries.findIndex((e) => e.source === at);
        entries[entry].api_key = 'placeholder-key-edited';

        const built = build(baseline, entries);

        baseline.rows.forEach((row, index) => {
          expect(built.rows[index]).toEqual(index === at
            ? { ...row, host: row.host.trim(), api_key: 'placeholder-key-edited' }
            : row);
        });
      });
    }
  }

  it('an edited row is trimmed and an unedited row is sent exactly as stored, even beside it', () => {
    const { baseline, entries } = displayedEntries('newznab_untrimmed');
    expect(baseline.rows[1].host).toMatch(/^ /);
    entries[0].host = 'https://placeholder-edited.invalid/api';

    const built = build(baseline, entries);

    expect(built.rows[1]).toEqual(baseline.rows[1]);
    expect(built.rows[1].host).toBe(baseline.rows[1].host);
  });

  it('hostile cells (%, +, &, =, an encoded comma, inner spaces) in an untouched row survive byte for byte', () => {
    const { baseline, entries } = displayedEntries('newznab_hostile_cells');
    entries[2].host = 'https://placeholder-edited.invalid/api';

    const built = build(baseline, entries);

    expect(built.rows[0]).toEqual(baseline.rows[0]);
    expect(built.rows[1]).toEqual(baseline.rows[1]);
    expect(built.rows[0].api_key).toBe('placeholder%2Ckey+and&equals=');
  });

  it('an edit to A in the interleaved fixture leaves every hidden row where it was, cell for cell', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    entries[0].host = 'https://placeholder-edited.invalid/api';

    const built = build(baseline, entries);

    for (const index of [0, 2, 4]) expect(built.rows[index]).toEqual(baseline.rows[index]);
    expect(built.rows[3]).toEqual(baseline.rows[3]);
    expect(built.origins).toEqual([null, 0, null, 1, null]);
  });
});

describe('adding, removing and clearing', () => {
  it('an added row is appended after every stored row, with the documented defaults', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    entries.push({ host: '  https://placeholder-new.invalid/api ', api_key: ' placeholder-key-new ', source: null });

    const built = build(baseline, entries);

    expect(built.rows.slice(0, 5)).toEqual(baseline.rows);
    expect(built.rows[5]).toEqual({
      ...DEFAULTS, host: 'https://placeholder-new.invalid/api', api_key: 'placeholder-key-new',
    });
    expect(built.rows).toHaveLength(6);
    expect(built.origins[5]).toBe(2);
  });

  it('an added row with a URL and no key is written with an empty key', () => {
    const { baseline, entries } = displayedEntries('newznab_two_stored');
    entries.push({ host: 'https://placeholder-new.invalid/api', api_key: '', source: null });

    expect(build(baseline, entries).rows[2].api_key).toBe('');
  });

  it('removing a displayed row between hidden rows closes up as WHOLE rows', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    const kept = entries.filter((e) => e.source !== 1);

    const built = build(baseline, kept);

    expect(built.rows).toEqual([baseline.rows[0], baseline.rows[2], baseline.rows[3], baseline.rows[4]]);
    expect(built.origins).toEqual([null, null, 0, null]);
    expect(logic.newznabRowsChanged(baseline, built.rows)).toBe(true);
  });

  it('removing the first of two stored rows leaves the second with its own five cells', () => {
    const { baseline, entries } = displayedEntries('newznab_two_stored');

    const built = build(baseline, entries.slice(1));

    expect(built.rows).toEqual([baseline.rows[1]]);
  });

  it('a cleared URL is a removal: its key goes with it and later rows close up', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    entries[0].host = '   ';

    const built = build(baseline, entries);

    expect(built.rows).toEqual([baseline.rows[0], baseline.rows[2], baseline.rows[3], baseline.rows[4]]);
    expect(JSON.stringify(built.rows)).not.toContain('placeholder-key-alpha');
  });

  it('a cleared key alone is written back in place with an empty key', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    entries[1].api_key = '';

    const built = build(baseline, entries);

    expect(built.rows).toHaveLength(5);
    expect(built.rows[3]).toEqual({ ...baseline.rows[3], api_key: '' });
    expect(built.rows[1]).toEqual(baseline.rows[1]);
  });

  it('all displayed rows removed from the interleaved fixture leaves D1, D2, D3 as stored', () => {
    const { baseline } = displayedEntries('newznab_interleaved');

    const built = build(baseline, []);

    expect(built.rows).toEqual([baseline.rows[0], baseline.rows[2], baseline.rows[4]]);
    expect(built.origins).toEqual([null, null, null]);
  });

  it('every displayed row removed with nothing hidden stores ONE all-empty row, never an empty list', () => {
    const { baseline } = displayedEntries('newznab_two_stored');

    const built = build(baseline, []);

    expect(built.rows).toEqual([EMPTY_ROW]);
    expect(logic.newznabRowsChanged(baseline, built.rows)).toBe(true);
  });

  it('a hostless row (a key and no host) is never dropped, whatever else is removed', () => {
    const { baseline } = displayedEntries('newznab_hostless');

    const built = build(baseline, []);

    expect(built.rows.map((row) => row.api_key)).toContain('placeholder-key-hostless');
    expect(built.rows).toEqual([baseline.rows[0], baseline.rows[2]]);
  });

  it('fresh defaults with no URL typed: the six keyless defaults are untouched and nothing is saved', () => {
    const { baseline, entries } = displayedEntries('fresh_defaults');

    const built = build(baseline, entries);

    expect(built.rows).toEqual(baseline.rows);
    expect(logic.newznabRowsChanged(baseline, built.rows)).toBe(false);
  });

  it('fresh defaults with one indexer typed: six defaults stay, the new one is appended', () => {
    const { baseline, entries } = displayedEntries('fresh_defaults');
    entries[0] = { host: 'https://placeholder-new.invalid/api', api_key: 'placeholder-key-new', source: null };

    const built = build(baseline, entries);

    expect(built.rows.slice(0, 6)).toEqual(baseline.rows);
    expect(built.rows[6]).toEqual({ ...DEFAULTS, host: 'https://placeholder-new.invalid/api', api_key: 'placeholder-key-new' });
  });
});

describe('mapping a server row back to the row on screen', () => {
  it('maps through hidden rows: server row 3 in the interleaved fixture is the SECOND entry on screen', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    const { origins } = build(baseline, entries);

    expect(logic.newznabEntryForRow(origins, 3)).toBe(1);
    expect(logic.newznabEntryForRow(origins, 1)).toBe(0);
  });

  it('maps through a dropped blank row above: the offending row is where it is on screen', () => {
    const { baseline } = displayedEntries('fresh_defaults');
    const entries: Entry[] = [
      { host: '', api_key: '', source: null },
      { host: 'https://placeholder-new.invalid/api', api_key: 'placeholder-key-new', source: null },
    ];
    const { rows, origins } = build(baseline, entries);

    expect(rows).toHaveLength(7);
    expect(logic.newznabEntryForRow(origins, 6)).toBe(1);
  });

  it('a hidden row, an out-of-range row, null, a fraction and a string map to nothing', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    const { origins } = build(baseline, entries);

    for (const row of [0, 2, 4, 5, -1, 1.5, null, undefined, '1', NaN]) {
      expect(logic.newznabEntryForRow(origins, row), String(row)).toBe(-1);
    }
  });
});

describe('after a save: the rows written become the baseline', () => {
  it('the same entries then build to the same rows and want no second save', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    entries[0].host = ' https://placeholder-edited.invalid/api ';
    const built = build(baseline, entries);

    const next = logic.newznabAfterSave(built, entries);

    expect(next.baseline.rows).toEqual(built.rows);
    expect(build(next.baseline, next.entries).rows).toEqual(built.rows);
    expect(logic.newznabRowsChanged(next.baseline, build(next.baseline, next.entries).rows)).toBe(false);
  });

  it('edit, save, revert: the revert IS a change against what was written, and rebuilds the original rows', () => {
    const { baseline, entries } = displayedEntries('newznab_two_stored');
    const original = structuredClone(baseline.rows);
    entries[0].host = 'https://placeholder-edited.invalid/api';
    const first = build(baseline, entries);
    const next = logic.newznabAfterSave(first, entries);

    next.entries[0].host = original[0].host;
    const second = build(next.baseline, next.entries);

    expect(logic.newznabRowsChanged(next.baseline, second.rows)).toBe(true);
    expect(second.rows).toEqual(original);
  });

  it('a cleared key is still shown and a key typed into it afterwards is written, not lost', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    entries[1].api_key = '';
    const first = build(baseline, entries);
    const next = logic.newznabAfterSave(first, entries);
    expect(isStored(next.baseline.rows[3])).toBe(false);

    next.entries[1].api_key = 'placeholder-key-again';
    const second = build(next.baseline, next.entries);

    expect(second.rows[3]).toEqual({ ...baseline.rows[3], api_key: 'placeholder-key-again' });
  });

  it('a cleared key then removed on screen removes the row: a removed indexer is not left stored', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    entries[1].api_key = '';
    const first = build(baseline, entries);
    const next = logic.newznabAfterSave(first, entries);

    const second = build(next.baseline, next.entries.filter((_, index) => index !== 1));

    expect(second.rows).toHaveLength(4);
    expect(second.rows.map((row) => row.host)).not.toContain(baseline.rows[3].host);
  });

  it('removing a row, saving, and then editing the next one still maps each entry to its own row', () => {
    const { baseline, entries } = displayedEntries('newznab_interleaved');
    const kept = entries.filter((e) => e.source !== 1);
    const next = logic.newznabAfterSave(build(baseline, kept), kept);

    next.entries[0].host = 'https://placeholder-edited.invalid/api';
    const built = build(next.baseline, next.entries);

    expect(built.rows).toEqual([
      baseline.rows[0], baseline.rows[2],
      { ...baseline.rows[3], host: 'https://placeholder-edited.invalid/api' },
      baseline.rows[4],
    ]);
  });

  it('an entry whose URL was cleared and saved is no longer tied to a row', () => {
    const { baseline, entries } = displayedEntries('newznab_two_stored');
    entries[0].host = '';
    const next = logic.newznabAfterSave(build(baseline, entries), entries);

    expect(next.entries[0].source).toBeNull();
    expect(build(next.baseline, next.entries).rows).toEqual(next.baseline.rows);
  });
});

/** A small deterministic generator so a failure reproduces from its seed. */
function generator(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

describe('property: whatever is done on screen, hidden rows and untouched rows are never altered', () => {
  const WITH_ROWS = ALIGNED.filter((fixture) => fixture !== 'fresh_defaults');

  it.each(WITH_ROWS)('%s: 200 random sequences of edits, removals and additions', (fixture) => {
    const random = generator(fixture.length * 7919);
    for (let round = 0; round < 200; round += 1) {
      const { baseline, entries } = start(fixture);
      const steps = 1 + Math.floor(random() * 5);
      for (let step = 0; step < steps; step += 1) {
        const pick = Math.floor(random() * entries.length);
        const action = Math.floor(random() * 5);
        if (action === 0 && entries[pick]) { entries[pick].host = `https://placeholder-r${round}.invalid/api`; }
        else if (action === 1 && entries[pick]) { entries[pick].api_key = `placeholder-key-r${round}`; }
        else if (action === 2 && entries.length > 1) entries.splice(pick, 1);
        else if (action === 3) entries.push({ host: `https://placeholder-add${round}.invalid/api`, api_key: 'placeholder-key-add', source: null });
        else if (entries[pick]) { entries[pick].host = ''; }
      }

      const built = build(baseline, entries);

      const hiddenBefore = baseline.rows.filter((_, index) => !baseline.shown[index]);
      const synthetic = built.rows.length === 1 && built.rows[0].host === '' && built.rows[0].use === '';
      const hiddenAfter = synthetic ? [] : built.rows.filter((_, index) => built.origins[index] === null);
      expect(hiddenAfter, `${fixture} round ${round}: hidden rows`).toEqual(hiddenBefore);
      built.rows.forEach((row, index) => {
        const entryIndex = built.origins[index];
        if (entryIndex === null) return;
        const entry = entries[entryIndex];
        const own = entry.source === null ? null : baseline.rows[entry.source];
        expect(Object.keys(row).sort()).toEqual([...COLUMNS].sort());
        for (const column of ['use', 'extra_score', 'custom_tag']) {
          expect(row[column], `${fixture} round ${round}: ${column}`).toBe(own ? own[column] : (DEFAULTS as Row)[column]);
        }
        const unedited = own !== null && row.host === own.host && row.api_key === own.api_key;
        if (!unedited) expect(row.host).toBe(row.host.trim());
        expect(row.host).not.toBe('');
      });
      // Rows keep their stored order: the stored ones as a subsequence, then additions.
      const stored = built.rows.flatMap((_, index) => {
        const entryIndex = built.origins[index];
        return entryIndex !== null && entries[entryIndex].source !== null ? [entries[entryIndex].source] : [];
      });
      expect(stored, `${fixture} round ${round}: stored order`).toEqual([...stored].sort((a, b) => a! - b!));
    }
  });
});
