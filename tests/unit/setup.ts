/**
 * Vitest setup file for CouchPotato UI unit tests.
 * This runs before each test file.
 */

// Mock the global CP object that's used in Alpine components
(global as any).CP = {
  apiBase: '/api/test-key',
  newBase: '/',
  webBase: '/',
};

// Mock fetch for API calls
global.fetch = vi.fn().mockImplementation(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ success: true }),
  })
);

// Mock Alpine.js
(global as any).Alpine = {
  $data: vi.fn().mockReturnValue({}),
  store: vi.fn(),
  directive: vi.fn(),
  magic: vi.fn(),
  plugin: vi.fn(),
  start: vi.fn(),
};
