/**
 * A fake Jackett on the loopback address, for the SEC-005 display slice (AC-PROD-3 and the
 * success half of AC-QA-19).
 *
 * The app's Sync fetches `<address>/torznab/all/api?apikey=<key>&t=indexers` and reads the
 * XML. This answers that in the shape a real Jackett uses (an `<indexers>` document, one
 * `<indexer configured="true">` per indexer with `<title>` and `<caps>`), and answers a wrong
 * or missing key the way Jackett does, with an `<error>` document. Nothing is stubbed in the
 * browser or in the app: the real server makes a real HTTP request to this one, so a Sync that
 * reaches it, and the key it carried, are observed at the far end of the wire.
 *
 * The server listens on 127.0.0.1 on a port the OS picks, is started by a test-scoped
 * fixture and is closed (with its connections) when the test ends. The key below is a
 * placeholder, not a credential.
 */
import http from 'node:http';
import type { AddressInfo } from 'node:net';

import { test as base } from './fixtures';

export { expect } from './fixtures';

/** The one key this fake accepts. */
export const FAKE_JACKETT_KEY = 'placeholder-fake-jackett-key';

/** Two configured indexers, the second without a `movie-search` element (assumed to support movies). */
const INDEXERS_XML = `<?xml version="1.0" encoding="UTF-8"?>
<indexers>
  <indexer id="fake-one" configured="true">
    <title>Fake Tracker One</title>
    <description>A fake public tracker</description>
    <type>public</type>
    <caps>
      <categories><category id="2000" name="Movies"/></categories>
      <searching>
        <search available="yes" supportedParams="q"/>
        <movie-search available="yes" supportedParams="q,imdbid"/>
      </searching>
    </caps>
  </indexer>
  <indexer id="fake-two" configured="true">
    <title>Fake Tracker Two</title>
    <description>Another fake public tracker</description>
    <type>public</type>
    <caps>
      <categories><category id="2000" name="Movies"/></categories>
      <searching>
        <search available="yes" supportedParams="q"/>
      </searching>
    </caps>
  </indexer>
</indexers>
`;

const ERROR_XML = '<?xml version="1.0" encoding="UTF-8"?>\n<error code="100" description="Invalid API Key"/>\n';

export type FakeJackettRequest = { path: string; query: string; keyAccepted: boolean };

export type FakeJackett = {
  /** `http://127.0.0.1:<port>`: what to save as the Jackett address. */
  url: string;
  /** Every request that reached it, in order. The key itself is not recorded, only whether it was right. */
  requests: FakeJackettRequest[];
};

function answer(fake: FakeJackett, request: http.IncomingMessage, response: http.ServerResponse) {
  const target = new URL(request.url ?? '/', fake.url);
  const keyAccepted = target.searchParams.get('apikey') === FAKE_JACKETT_KEY;
  fake.requests.push({ path: target.pathname, query: target.searchParams.get('t') ?? '', keyAccepted });
  if (target.pathname !== '/torznab/all/api' || target.searchParams.get('t') !== 'indexers') {
    response.writeHead(404, { 'content-type': 'text/plain' });
    response.end('not found');
    return;
  }
  response.writeHead(200, { 'content-type': 'application/xml; charset=utf-8' });
  response.end(keyAccepted ? INDEXERS_XML : ERROR_XML);
}

/** Start one, listening on the loopback address only. Close it with the returned function. */
export async function startFakeJackett(): Promise<{ fake: FakeJackett; close: () => Promise<void> }> {
  const fake: FakeJackett = { url: '', requests: [] };
  const server = http.createServer((request, response) => answer(fake, request, response));
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve());
  });
  fake.url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const close = () => new Promise<void>((resolve) => {
    server.close(() => resolve());
    server.closeAllConnections();
  });
  return { fake, close };
}

/** `test` with a `fakeJackett` fixture: started for the test, closed after it. */
export const test = base.extend<{ fakeJackett: FakeJackett }>({
  fakeJackett: async ({}, use) => {
    const { fake, close } = await startFakeJackett();
    try {
      await use(fake);
    } finally {
      await close();
    }
  },
});
