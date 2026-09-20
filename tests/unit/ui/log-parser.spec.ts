/** Contracts for the shared browser log parser used by both log surfaces. */
import { describe, expect, it } from 'vitest';
import { parseLogLines } from '../../../couchpotato/static/scripts/ui/log-parser.js';

describe('parseLogLines', () => {
  it('returns an empty list for a non-array payload', () => {
    expect(parseLogLines('not-an-array')).toEqual([]);
  });

  it('normalizes structured entries and extracts a bracketed source', () => {
    expect(parseLogLines([
      { time: '01-02 03:04:05', type: 'debug', message: '[ worker ] hello' },
      { time: '02-03 04:05:06', message: 'plain message' },
      { time: '03-04 05:06:07', type: 'warning' },
      { time: '04-05 06:07:08', message: 'prefix [not-a-source] remains whole' },
      { time: '05-06 07:08:09', message: '[source]no separating space' },
    ])).toEqual([
      { time: '01-02 03:04:05', type: 'DEBUG', source: 'worker', message: 'hello' },
      { time: '02-03 04:05:06', type: 'INFO', source: '', message: 'plain message' },
      { time: '03-04 05:06:07', type: 'WARNING', source: '', message: '' },
      { time: '04-05 06:07:08', type: 'INFO', source: '', message: 'prefix [not-a-source] remains whole' },
      { time: '05-06 07:08:09', type: 'INFO', source: 'source', message: 'no separating space' },
    ]);
  });

  it('parses legacy raw entries without calendar-range validation', () => {
    expect(parseLogLines([
      '01-02 03:04:05 WARNING [ source ] message',
      '99-99\t99:99:99  INFO\t[]   ',
      '12-31 23:59:59 ERROR [worker]\tpayload',
    ])).toEqual([
      { time: '01-02 03:04:05', type: 'WARNING', source: 'source', message: 'message' },
      { time: '99-99\t99:99:99', type: 'INFO', source: '', message: '' },
      { time: '12-31 23:59:59', type: 'ERROR', source: 'worker', message: 'payload' },
    ]);
  });

  it('keeps malformed raw lines whole and classifies only whole-word levels', () => {
    expect(parseLogLines([
      'bad XWARNINGY then ERROR whole',
      '01-02 03:04:05 critical [source] lower-case level',
      '01-02 03:04:05 INFO [unterminated',
      'prefixDEBUGsuffix',
      'a1-02 03:04:05 INFO [source] non-digit',
      '/1-02 03:04:05 INFO [source] punctuation digit',
      '1-02 03:04:05 INFO [source] short date field',
      '0102 03:04:05 INFO [source] missing date separator',
      '01/02 03:04:05 INFO [source] wrong date separator',
      '01-0203:04:05 INFO [source] missing date whitespace',
      '01-02 03-04:05 INFO [source] wrong time separator',
      '01-02 03:04:05INFO [source] missing level whitespace',
      '01-02 03:04:05 INFO[source] missing source whitespace',
      '01-02 03:04:05 INFO (source] missing opening bracket',
    ])).toEqual([
      { time: '', type: 'ERROR', source: '', message: 'bad XWARNINGY then ERROR whole' },
      { time: '', type: 'INFO', source: '', message: '01-02 03:04:05 critical [source] lower-case level' },
      { time: '', type: 'INFO', source: '', message: '01-02 03:04:05 INFO [unterminated' },
      { time: '', type: 'INFO', source: '', message: 'prefixDEBUGsuffix' },
      { time: '', type: 'INFO', source: '', message: 'a1-02 03:04:05 INFO [source] non-digit' },
      { time: '', type: 'INFO', source: '', message: '/1-02 03:04:05 INFO [source] punctuation digit' },
      { time: '', type: 'INFO', source: '', message: '1-02 03:04:05 INFO [source] short date field' },
      { time: '', type: 'INFO', source: '', message: '0102 03:04:05 INFO [source] missing date separator' },
      { time: '', type: 'INFO', source: '', message: '01/02 03:04:05 INFO [source] wrong date separator' },
      { time: '', type: 'INFO', source: '', message: '01-0203:04:05 INFO [source] missing date whitespace' },
      { time: '', type: 'INFO', source: '', message: '01-02 03-04:05 INFO [source] wrong time separator' },
      { time: '', type: 'INFO', source: '', message: '01-02 03:04:05INFO [source] missing level whitespace' },
      { time: '', type: 'INFO', source: '', message: '01-02 03:04:05 INFO[source] missing source whitespace' },
      { time: '', type: 'INFO', source: '', message: '01-02 03:04:05 INFO (source] missing opening bracket' },
    ]);
  });

  it('stringifies non-string legacy values exactly as before', () => {
    expect(parseLogLines([42, undefined])).toEqual([
      { time: '', type: 'INFO', source: '', message: '42' },
      { time: '', type: 'INFO', source: '', message: 'undefined' },
    ]);
  });

  it('leaves HTML-shaped source and message content as inert string values', () => {
    const source = '<img src=x onerror=globalThis.pwned=true>';
    const message = '<script>globalThis.pwned=true</script>';
    expect(parseLogLines([`01-02 03:04:05 INFO [${source}] ${message}`])).toEqual([
      { time: '01-02 03:04:05', type: 'INFO', source, message },
    ]);
  });

  it('is bounded on long matches and adversarial non-matches', { timeout: 2000 }, () => {
    const spaces = ' '.repeat(100_000);
    const hostile = `01-02 03:04:05 INFO [source]${spaces}x\ny`;
    const unterminated = `01-02 03:04:05 INFO [${'x'.repeat(100_000)}`;
    const longMessage = `01-02 03:04:05 DEBUG [source] ${'x'.repeat(100_000)}`;

    expect(parseLogLines([hostile])).toEqual([
      { time: '', type: 'INFO', source: '', message: hostile },
    ]);
    expect(parseLogLines([unterminated])).toEqual([
      { time: '', type: 'INFO', source: '', message: unterminated },
    ]);
    expect(parseLogLines([longMessage])[0]).toEqual({
      time: '01-02 03:04:05', type: 'DEBUG', source: 'source', message: 'x'.repeat(100_000),
    });
  });
});
