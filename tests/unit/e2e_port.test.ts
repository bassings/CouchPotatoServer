import { createServer } from 'node:net';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import { assertE2EPortAvailable, resolveE2EPort } from '../e2e/port';

describe('E2E port allocation', () => {
  it('keeps 5150 as the local default', () => {
    expect(resolveE2EPort(undefined)).toBe(5150);
  });

  it('honours one run-specific BASE_PORT across ordinary and authenticated servers', () => {
    expect(resolveE2EPort('6180', 0)).toBe(6180);
    expect(resolveE2EPort('6180', 3)).toBe(6183);
    expect(resolveE2EPort('6180', 100)).toBe(6280);
  });

  it.each(['', 'not-a-port', '12.5', '0', '1023', '65536'])(
    'rejects invalid BASE_PORT=%j before starting a server',
    (value) => {
      expect(() => resolveE2EPort(value)).toThrow(/BASE_PORT/);
    },
  );

  it('rejects a base whose worker offset would overflow the TCP range', () => {
    expect(() => resolveE2EPort('65535', 1)).toThrow(/offset/);
  });

  it('fails loudly when a decoy server already owns the selected port', async () => {
    const decoy = createServer();
    await new Promise<void>((resolve) => decoy.listen(0, '127.0.0.1', resolve));
    const address = decoy.address();
    if (!address || typeof address === 'string') throw new Error('decoy did not bind a TCP port');

    try {
      await expect(assertE2EPortAvailable(address.port, 'test worker'))
        .rejects.toThrow(/ALREADY SERVING.*wrong server/);
    } finally {
      await new Promise<void>((resolve, reject) => decoy.close((err) => err ? reject(err) : resolve()));
    }
  });

  it('routes every E2E-owned CouchPotato server through the shared allocator and collision guard', () => {
    const e2eDir = path.resolve(__dirname, '../e2e');
    const serverOwners = readdirSync(e2eDir)
      .filter((name) => name.endsWith('.ts'))
      .map((name) => [name, readFileSync(path.join(e2eDir, name), 'utf8')] as const)
      .filter(([, source]) => source.includes("'CouchPotato.py'"));

    expect(serverOwners.length, 'no E2E-owned server processes found').toBeGreaterThan(0);
    for (const [name, source] of serverOwners) {
      expect(source, `${name} bypasses the run-specific port allocator`)
        .toMatch(/resolveE2EPort\(\s*process\.env\.BASE_PORT/);
      expect(source, `${name} can accept a server belonging to another run`)
        .toContain('await assertE2EPortAvailable(port');
    }
  });
});
