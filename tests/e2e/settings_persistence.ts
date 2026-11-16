export const SETTINGS_PERSISTENCE_ANNOTATION = 'persistsSettings';

/**
 * Every settings write route a test must not reach unannounced: the per-column save and
 * the group save of a combine group's rows (SEC-004). One pattern for both, so a route
 * added to a mock or to the guard cannot be added to only one of them.
 */
export const SETTINGS_WRITE_ROUTES = /\/settings\.save(?:_group)?\//;

type Annotation = { type: string; description?: string };
export type SettingWrite = { section: string; name: string };
type SettingsSnapshot = { values?: Record<string, Record<string, unknown>> };

/** True only when a test has explicitly declared that it mutates worker settings. */
export function allowsSettingsPersistence(annotations: readonly Annotation[]): boolean {
  return annotations.some(({ type }) => type === SETTINGS_PERSISTENCE_ANNOTATION);
}

/** Diff every section/name pair, including values changed indirectly by hooks. */
export function changedSettings(before: SettingsSnapshot, after: SettingsSnapshot): SettingWrite[] {
  const pairs = new Set<string>();
  for (const snapshot of [before, after]) {
    for (const [section, values] of Object.entries(snapshot.values || {})) {
      for (const name of Object.keys(values || {})) pairs.add(`${section}\0${name}`);
    }
  }
  return [...pairs].flatMap((pair) => {
    const [section, name] = pair.split('\0');
    return JSON.stringify(before.values?.[section]?.[name])
      === JSON.stringify(after.values?.[section]?.[name]) ? [] : [{ section, name }];
  });
}

/** Encode a settings API value using the same wire format as the application. */
export function serializeSettingValue(value: unknown): string {
  if (Array.isArray(value)) return value.join('::');
  if (typeof value === 'boolean') return value ? '1' : '0';
  return String(value ?? '');
}

/**
 * Marks a test that writes a combine group (SEC-004 AC-QA-10). Such a test owns its
 * `seedConfig` value alone: the worker's server reads `config.ini` once, so a second
 * test on the same value would start from the first one's rows. Enforced statically by
 * tests/unit/e2e_seed_config_ownership.test.ts, which looks for this name.
 */
export const COMBINE_WRITER_ANNOTATION = 'writesCombineGroup';

/** Annotations for a test that writes a combine group: it persists, and says so. */
export function combineGroupWriter(): { type: string }[] {
  return [{ type: SETTINGS_PERSISTENCE_ANNOTATION }, { type: COMBINE_WRITER_ANNOTATION }];
}

export type CombineState = { misaligned: boolean; rows: number };
export type GroupRow = Record<string, string>;
type ReadSnapshot = SettingsSnapshot & {
  options?: Record<string, { groups?: { options?: { type?: string; combine?: string[] }[] }[] }>;
  combine_state?: Record<string, CombineState>;
};

/** Each combine group's ordered columns, read from the registered option declarations. */
export function combineColumns(snapshot: ReadSnapshot): Record<string, string[]> {
  const found: Record<string, string[]> = {};
  for (const [section, declared] of Object.entries(snapshot.options || {})) {
    for (const group of declared?.groups || []) {
      for (const option of group?.options || []) {
        if (option?.type === 'combined' && Array.isArray(option.combine)) found[section] = option.combine;
      }
    }
  }
  return found;
}

/** Split changed settings into combine groups (restored as rows) and everything else. */
export function splitGroupWrites(
  before: ReadSnapshot,
  changed: SettingWrite[],
): { groups: string[]; perColumn: SettingWrite[] } {
  const columns = combineColumns(before);
  const groups = new Set<string>();
  const perColumn: SettingWrite[] = [];
  for (const write of changed) {
    if (columns[write.section]?.includes(write.name)) groups.add(write.section);
    else perColumn.push(write);
  }
  return { groups: [...groups], perColumn };
}

/**
 * The rows a group save would have to write to put a combine group back, or null when
 * a group save cannot reproduce the baseline: it writes every column to exactly the
 * row count (the server's `rows`), so any column whose stored cell count differs
 * cannot be put back by one. That covers a misaligned baseline (a pairing column
 * shorter than the row count, or a non-pairing one longer by data) and an aligned one
 * with a short non-pairing column. It is NOT a second alignment rule: the server's
 * `misaligned` flag is deliberately not consulted, because every misaligned shape
 * already fails this test, so a check on the flag could never change an answer.
 * Skipped, not failed: safe only because a test that writes such a group owns its
 * worker (COMBINE_WRITER_ANNOTATION).
 */
export function baselineGroupRows(before: ReadSnapshot, section: string): GroupRow[] | null {
  const state = before.combine_state?.[section];
  const columns = combineColumns(before)[section];
  if (!state || !columns) return null;
  const cells = columns.map((column) => String(before.values?.[section]?.[column] ?? '').split(','));
  if (cells.some((column) => column.length !== state.rows)) return null;
  return Array.from({ length: state.rows }, (_, index) => Object.fromEntries(
    columns.map((column, position) => [column, cells[position][index]]),
  ));
}
