// @vitest-environment node
/**
 * SEC-004 P6, AC-OPS-2: the old per-column save path shows the server's refusal as written.
 *
 * A Settings tab loaded before the upgrade still saves one column at a time through
 * `saveSingle`. After the upgrade the server refuses a combine column, and the only
 * explanation that tab can give is the text the server sent. This runs the REAL
 * `settingsPanel().saveSingle` and `toast` from partials/settings/scripts.html with only
 * `fetch`, the timers and the Alpine tick replaced, and checks that text reaches the
 * toast and the assertive live region unchanged, and that the value is left dirty.
 *
 * The text below is the one `couchpotato/core/settings.py` sends; the integration test
 * `tests/integration/test_settings_save_refuses_combine.py` pins the same words, so a
 * change on either side fails one of them.
 */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const TEMPLATE = path.resolve(__dirname, '../../../couchpotato/ui/templates/partials/settings/scripts.html');

const SERVER_TEXT = '"newznab.host" is saved together with the rest of its group, not on its own. '
  + 'Nothing was saved. Use settings.save_group, or reload the page and edit the rows there.';

function loadPanel(): any {
  const html = fs.readFileSync(TEMPLATE, 'utf8');
  const code = html.slice(html.indexOf('<script>') + '<script>'.length, html.lastIndexOf('</script>'));
  const { settingsPanel } = new Function(`${code}\nreturn { settingsPanel };`)();
  const panel = settingsPanel();
  panel.$nextTick = (callback: () => void) => callback();
  panel.$watch = () => {};
  return panel;
}

function answer(body: unknown, status = 200) {
  const sent: { url: string; init: any }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: any) => {
    sent.push({ url, init });
    return { ok: status < 400, status, json: async () => body };
  }));
  return sent;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('CP', { apiBase: '/api/placeholder-api-key' });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('a tab loaded before the upgrade saving a combine column', () => {
  it('shows the server refusal text as written, in the toast and the assertive region', async () => {
    answer({ success: false, error: SERVER_TEXT });
    const panel = loadPanel();

    await panel.saveSingle('newznab', 'host', 'https://placeholder-host.invalid');

    expect(panel.message).toBe(`Could not save host: ${SERVER_TEXT}`);
    expect(panel.messageType).toBe('error');
    expect(panel.assertiveAnnouncement).toBe(`Could not save host: ${SERVER_TEXT}`);
    expect(panel.politeAnnouncement).toBe('');
  });

  it('does not report Saved, and does not apply the value it submitted', async () => {
    answer({ success: false, error: SERVER_TEXT });
    const panel = loadPanel();
    panel.values = { newznab: { host: 'placeholder-stored-host' } };

    await panel.saveSingle('newznab', 'host', 'https://placeholder-host.invalid');

    expect(panel.lastSaved).toBe(false);
    expect(panel.saving).toBe(false);
    expect(panel.values.newznab.host).toBe('placeholder-stored-host');
  });

  it('puts the server text in the page as text, not markup', async () => {
    const markup = '<img src=x onerror=alert(1)> reload the page';
    answer({ success: false, error: markup });
    const panel = loadPanel();

    await panel.saveSingle('newznab', 'host', 'x');

    // Relayed untouched: escaping is the element's job, below.
    expect(panel.message).toBe(`Could not save host: ${markup}`);
    expect(panel.assertiveAnnouncement).toBe(`Could not save host: ${markup}`);

    // The elements that render these strings are the ones bound to them. Each must be
    // an element whose only content binding is x-text (textContent), never x-html.
    const modals = fs.readFileSync(TEMPLATE.replace('scripts.html', 'modals.html'), 'utf8');
    const element = (binding: string) => {
      const found = modals.match(new RegExp(`<div\\b[^>]*\\bx-text="${binding}"[^>]*>`, 's'));
      expect(found, `no element is bound to ${binding}`).not.toBeNull();
      return found![0];
    };
    expect(element('message')).toContain('x-show="message"');
    expect(element('assertiveAnnouncement')).toContain('aria-live="assertive"');
    for (const binding of ['message', 'assertiveAnnouncement', 'politeAnnouncement']) {
      expect(element(binding)).not.toMatch(/x-html/);
    }
    expect(modals).not.toMatch(/x-html="(message|assertiveAnnouncement|politeAnnouncement)"/);
  });
});
