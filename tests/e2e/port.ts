import net from 'node:net';
import { lookup } from 'node:dns/promises';

const DEFAULT_E2E_BASE_PORT = 5150;

/** Resolve one port in the run's E2E range and reject worker-offset overflow. */
export function resolveE2EPort(configured: string | undefined, offset = 0): number {
  const raw = configured ?? String(DEFAULT_E2E_BASE_PORT);
  if (!/^\d+$/.test(raw)) {
    throw new Error(`BASE_PORT must be an integer TCP port; received ${JSON.stringify(raw)}`);
  }
  if (!Number.isSafeInteger(offset) || offset < 0) {
    throw new Error(`E2E port offset must be a non-negative integer; received ${offset}`);
  }

  const base = Number(raw);
  const port = base + offset;
  if (!Number.isSafeInteger(base) || base < 1024 || port > 65535) {
    throw new Error(
      `BASE_PORT plus the E2E worker offset must stay between 1024 and 65535; `
      + `received BASE_PORT=${JSON.stringify(raw)}, offset=${offset}`,
    );
  }
  return port;
}

/** Refuse a port owned by another run before readiness can accept its server. */
export async function assertE2EPortAvailable(port: number, owner: string): Promise<void> {
  const addresses = await lookup('localhost', { all: true })
    .then((entries) => entries.map((entry) => entry.address))
    .catch(() => [] as string[]);

  for (const address of addresses) {
    await new Promise<void>((resolve, reject) => {
      const probe = net.connect({ port, host: address });
      let settled = false;
      const done = (err?: Error) => {
        if (settled) return;
        settled = true;
        probe.destroy();
        err ? reject(err) : resolve();
      };
      probe.setTimeout(2000);
      probe.once('connect', () => done(new Error(
        `${owner}: port ${port} is ALREADY SERVING on ${address}. `
        + `Another Playwright run, sibling worktree, or orphan owns this port; `
        + `refusing to report results against the wrong server. Set BASE_PORT `
        + `to a non-overlapping range or free the listener `
        + `(lsof -nP -iTCP:${port} -sTCP:LISTEN).`,
      )));
      // Nothing listening -- ECONNREFUSED is the expected result.
      probe.once('error', () => done());
      probe.once('timeout', () => done());
    });
  }
}
