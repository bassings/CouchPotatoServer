import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Test environment
    environment: 'jsdom',
    
    // Test file patterns
    include: ['tests/unit/**/*.{test,spec}.{js,ts}'],
    
    // Setup files
    setupFiles: ['./tests/unit/setup.ts'],
    
    // Coverage configuration
    coverage: {
      reporter: ['text', 'html', 'lcov'],
      exclude: [
        'node_modules/**',
        'tests/**',
        '.config/**',
        '**/*.d.ts',
      ],
    },
    
    // Globals
    globals: true,
  },
});
