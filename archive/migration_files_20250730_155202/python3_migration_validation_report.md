# CouchPotato Python 3.12 Migration Validation Report
============================================================

## Executive Summary
**Overall Success Rate:** 92.7%
**Total Tests:** 275
**Tests Passed:** 255
**Tests Failed:** 20

## Syntax Validation
------------------------------
**Passed:** 251
**Failed:** 7
**Errors:**
- couchpotato/core/compat.py: unexpected indent (compat.py, line 74)
- couchpotato/core/plugins/renamer.py: invalid syntax (renamer.py, line 86)
- couchpotato/core/downloaders/utorrent.py: invalid non-printable character U+FEFF (utorrent.py, line 2)
- couchpotato/core/notifications/emby.py: multiple exception types must be parenthesized (emby.py, line 35)
- couchpotato/core/media/_base/providers/torrent/torrentleech.py: inconsistent use of tabs and spaces in indentation (torrentleech.py, line 30)
- couchpotato/core/media/movie/_base/main.py: Missing parentheses in call to 'print'. Did you mean print(...)? (main.py, line 248)
- couchpotato/core/notifications/plex/server.py: unexpected indent (server.py, line 50)

## Import Validation
------------------------------
**Passed:** 1
**Failed:** 5
**Errors:**
- N/A: cannot import name 'unquote' from 'urllib' (/opt/homebrew/Cellar/python@3.13/3.13.5/Frameworks/Python.framework/Versions/3.13/lib/python3.13/urllib/__init__.py)
- N/A: No module named 'ConfigParser'
- N/A: No module named 'CodernityDB'
- N/A: unexpected indent (compat.py, line 74)
- N/A: unexpected indent (compat.py, line 74)

## Functional Tests
------------------------------
**Passed:** 0
**Failed:** 6
**Errors:**
- N/A: Test returned False
- N/A: Test returned False
- N/A: Test returned False
- N/A: Test returned False
- N/A: Test returned False
- N/A: Test returned False

## Security Validation
------------------------------
**Passed:** 3
**Failed:** 2

## Performance Benchmarks
------------------------------
**Startup Time:** 0.000s
**Import Time:** 0.000s
**Memory Usage:** 0.0MB

## Recommendations
------------------------------

⚠️ **NEEDS MINOR FIXES**: Address the failed tests before deployment.

**Next Steps:**
1. Fix syntax errors in the reported files
2. Resolve import issues and missing dependencies
3. Address functional test failures
4. Resolve security vulnerabilities
5. Run validation again to confirm fixes
6. Deploy to staging environment for final testing