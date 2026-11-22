/**
 * The Settings page's own script, evaluated for a unit test.
 *
 * `partials/settings/scripts.html` holds the real `settingsPanel()`, `combinedField()` and `buttonField()`
 * and the constants they use. The script block is read from the template and run, so a test drives the
 * code the browser runs. Each call evaluates the block afresh. Shared by `settings-group-save.spec.ts` and
 * `settings-save-model.spec.ts` so that both drive the same thing the same way.
 */
import fs from 'node:fs';
import path from 'node:path';

const TEMPLATE = path.resolve(__dirname, '../../../couchpotato/ui/templates/partials/settings/scripts.html');

export type SettingsScript = {
  settingsPanel: (...args: any[]) => any;
  combinedField: (...args: any[]) => any;
  buttonField: (...args: any[]) => any;
  SAVE_WAIT_DEADLINE_MS: number;
  REMOVAL_UNDO_WINDOW_MS: number;
};

export function loadSettingsScript(): SettingsScript {
  const html = fs.readFileSync(TEMPLATE, 'utf8');
  const code = html.slice(html.indexOf('<script>') + '<script>'.length, html.lastIndexOf('</script>'));
  return new Function(
    `${code}\nreturn { settingsPanel, combinedField, buttonField, SAVE_WAIT_DEADLINE_MS, REMOVAL_UNDO_WINDOW_MS };`,
  )();
}
