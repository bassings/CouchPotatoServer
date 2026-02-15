/**
 * Lighthouse CI configuration for CouchPotato.
 * Run with: npm run test:lighthouse
 */

module.exports = {
  ci: {
    collect: {
      // URLs to test
      url: [
        'http://localhost:5050/',
        'http://localhost:5050/available/',
        'http://localhost:5050/add/',
        'http://localhost:5050/settings/',
      ],
      
      // Number of runs per URL for consistency
      numberOfRuns: 3,
      
      // Start server command (optional - assumes server is already running)
      // startServerCommand: 'python CouchPotato.py',
      // startServerReadyPattern: 'Started server',
      // startServerReadyTimeout: 30000,
      
      // Puppeteer settings
      settings: {
        // Use mobile throttling for more realistic results
        throttlingMethod: 'simulate',
        
        // Skip some audits that don't apply
        skipAudits: [
          'uses-http2', // Local dev server doesn't use HTTP/2
          'redirects-http', // Local dev uses HTTP
        ],
      },
    },
    
    assert: {
      // Assertion levels
      preset: 'lighthouse:recommended',
      
      assertions: {
        // Performance targets
        'categories:performance': ['warn', { minScore: 0.8 }],
        
        // Accessibility targets (high priority)
        'categories:accessibility': ['error', { minScore: 0.9 }],
        
        // Best practices
        'categories:best-practices': ['warn', { minScore: 0.9 }],
        
        // SEO (lower priority for internal tool)
        'categories:seo': ['warn', { minScore: 0.8 }],
        
        // PWA (not a priority)
        'categories:pwa': 'off',
        
        // Specific audit overrides
        'color-contrast': ['warn', { minScore: 0.9 }],
        'image-alt': ['error', {}],
        'link-name': ['error', {}],
        'button-name': ['error', {}],
        
        // Performance specifics
        'first-contentful-paint': ['warn', { maxNumericValue: 3000 }],
        'largest-contentful-paint': ['warn', { maxNumericValue: 4000 }],
        'total-blocking-time': ['warn', { maxNumericValue: 500 }],
        'cumulative-layout-shift': ['warn', { maxNumericValue: 0.1 }],
        
        // Allow external resources (CDN)
        'uses-text-compression': 'off', // CDN handles this
        'render-blocking-resources': 'off', // We use CDN scripts
      },
    },
    
    upload: {
      // Don't upload to Lighthouse CI server by default
      target: 'temporary-public-storage',
    },
  },
};
