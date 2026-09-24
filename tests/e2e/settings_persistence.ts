export const SETTINGS_PERSISTENCE_ANNOTATION = 'persistsSettings';

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
