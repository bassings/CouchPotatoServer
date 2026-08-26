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
      // Reports are written to disk and go NOWHERE ELSE.
      //
      // This used to be `temporary-public-storage`, under a comment asserting
      // that nothing was sent anywhere by default -- the opposite of what the
      // value did. That phrasing is deliberately NOT reproduced here, even as
      // history: a reader skimming the block would see the reassuring claim and
      // stop, which is the whole failure being fixed. (The guard in
      // tests/unit/lighthouse_upload_stays_local.test.ts agrees -- it flagged
      // this comment when the old wording was quoted verbatim.) That target
      // POSTs the rendered HTML
      // report to a PUBLIC Google endpoint
      // (us-central1-lighthouse-infrastructure.cloudfunctions.net/saveHtmlReport)
      // and prints the returned public URL.
      //
      // The payload matters: a Lighthouse HTML report embeds full-page
      // screenshots, and the URLs collected above are the user's own library
      // on port 5050 -- this project's PRODUCTION port. Nobody opted in;
      // `npm run test:lighthouse` did it, and `npm run test:all` runs that.
      // `autorun` uploads even when assertions FAIL, so it fired most reliably
      // at the moment the operator believed the run had aborted.
      //
      // Publishing someone's media library to a third party is not undoable by
      // deleting anything here, which puts it in the irreplaceable tier of this
      // project's loss ranking. Pinned by
      // tests/unit/lighthouse_upload_stays_local.test.ts, which allowlists the
      // targets that stay on this machine rather than denylisting the ones that
      // do not -- a denylist is wrong again the day lhci adds a target, and
      // nothing announces that.
      target: 'filesystem',
      outputDir: './.lighthouseci',

      // No %%DATETIME%% on purpose. The default pattern
      // (%%HOSTNAME%%-%%PATHNAME%%-%%DATETIME%%.report.%%EXTENSION%%) gives
      // every run its own filename, and `collect`'s own cleanup only unlinks
      // `lhr-<digits>.json`/`.html` -- names this pattern never produces --
      // so datetime-stamped reports accumulate forever across every
      // `npm run test:lighthouse` invocation, unnoticed once T47 gitignored
      // this directory. Dropping %%DATETIME%% makes each run overwrite the
      // last report per URL instead, which caps the directory at roughly the
      // 4 collected URLs x 2 files (html + json) plus manifest.json. Do not
      // restore the timestamp as a "nice to keep history" convenience --
      // there is no cleanup mechanism for it, per the audit that found this.
      reportFilenamePattern: 'report-%%PATHNAME%%.%%EXTENSION%%',
    },
  },
};
