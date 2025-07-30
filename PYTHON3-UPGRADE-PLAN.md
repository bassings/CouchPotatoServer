# CouchPotato Python 2 → 3.12 Upgrade Plan

## Overview

This document outlines the step-by-step process to upgrade CouchPotato from Python 2 to Python 3.12 while maintaining compatibility and functionality.

## Pre-Upgrade Analysis Summary

### Current State
- **Main Entry Point**: Uses `#!/usr/bin/env python2` in `CouchPotato.py`
- **Dependencies**: Many bundled libraries in `libs/` directory already have Python 2/3 compatibility
- **Existing Compatibility**: Some files already use `from __future__ import` statements

### Identified Issues

#### 1. Import Statement Changes
**Files Affected**: Multiple downloader and notification modules

**urllib2 → urllib.request + urllib.error**
```python
# Python 2
import urllib2
urllib2.urlopen(request)
urllib2.HTTPError

# Python 3
import urllib.request, urllib.error
urllib.request.urlopen(request)
urllib.error.HTTPError
```

**ConfigParser → configparser**
```python
# Python 2
import ConfigParser
ConfigParser.RawConfigParser()

# Python 3
import configparser
configparser.RawConfigParser()
```

#### 2. String Handling
**basestring Usage**
- `couchpotato/core/media/_base/matcher/base.py:60`
- Need to replace with `str` or use `six.string_types`

**Unicode Handling**
- Many `toUnicode()` calls throughout codebase
- Need compatibility layer for Python 2/3

#### 3. Dictionary Methods
**iteritems() → items()**
- `couchpotato/core/logger.py:64`
- `couchpotato/core/media/_base/providers/torrent/hd4free.py:38`

#### 4. Exception Handling Syntax
**Old-style Exception Syntax**
```python
# Python 2
except urllib2.URLError, e:

# Python 3
except urllib2.URLError as e:
```

#### 5. Future Imports Status
Currently have minimal future imports:
- `CouchPotato.py`: `from __future__ import print_function`
- Some modules: `from __future__ import with_statement`

## Upgrade Strategy

### Phase 1: Preparation & Compatibility Layer

#### 1.1 Add Comprehensive Future Imports
Add to all main application files (not libs):
```python
from __future__ import absolute_import, division, print_function, unicode_literals
```

#### 1.2 Install Compatibility Libraries
Add to requirements or Docker:
```bash
pip install six future
```

#### 1.3 Create Compatibility Module
Create `couchpotato/core/compat.py`:
```python
import sys
import six

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

if PY3:
    import urllib.request as urllib2
    import urllib.error
    import configparser as ConfigParser
    string_types = str
    text_type = str
    binary_type = bytes
    
    def iteritems(d):
        return d.items()
else:
    import urllib2
    import ConfigParser
    string_types = basestring
    text_type = unicode
    binary_type = str
    
    def iteritems(d):
        return d.iteritems()
```

### Phase 2: Code Updates

#### 2.1 Update Entry Point
Change `CouchPotato.py`:
```bash
#!/usr/bin/env python3
```

#### 2.2 Fix Import Statements
**Priority Files to Update**:
1. `couchpotato/core/downloaders/transmission.py`
2. `couchpotato/core/downloaders/utorrent.py`
3. `couchpotato/core/downloaders/hadouken.py`
4. `couchpotato/core/notifications/emby.py`
5. `couchpotato/core/notifications/plex/server.py`
6. `couchpotato/core/settings.py`

#### 2.3 Fix Exception Handling
Update old-style exception syntax:
```python
# Before
except urllib2.URLError, e:

# After  
except urllib.error.URLError as e:
```

#### 2.4 Fix Dictionary Methods
Replace `iteritems()` with compatibility function:
```python
from couchpotato.core.compat import iteritems
# Replace: dict.iteritems()
# With: iteritems(dict)
```

#### 2.5 Fix String Types
Replace `basestring` with compatibility:
```python
from couchpotato.core.compat import string_types
# Replace: isinstance(value, basestring)
# With: isinstance(value, string_types)
```

### Phase 3: Testing & Validation

#### 3.1 Docker Testing Environment
Use the provided Docker setup with both Python versions:

```bash
# Test with Python 2
docker build -f Dockerfile.python2 -t couchpotato:py2 .

# Test with Python 3
docker build -f Dockerfile -t couchpotato:py3 .
```

#### 3.2 Test Matrix
Test all major functionality:
- [ ] Application startup
- [ ] Web interface loading
- [ ] Database operations
- [ ] Plugin loading
- [ ] Download client connections
- [ ] Notification services
- [ ] File scanning
- [ ] API endpoints

### Phase 4: Gradual Migration

#### 4.1 Branch Strategy
1. Create `python3-migration` branch
2. Make changes in small, testable chunks
3. Test each component independently
4. Merge when stable

#### 4.2 Migration Order
1. **Core components** (settings, database, logging)
2. **Plugin system** (base classes, event system)
3. **Download clients** (one at a time)
4. **Notification services** (one at a time)
5. **Web interface** (handlers, templates)
6. **Media providers** (search providers)

## Implementation Steps

### Step 1: Create Compatibility Infrastructure
```bash
# 1. Create compatibility module
touch couchpotato/core/compat.py

# 2. Add future imports to core files
find couchpotato/core -name "*.py" -type f | head -10
```

### Step 2: Systematic File Updates
Start with the most critical files:

1. `couchpotato/core/settings.py` - Configuration handling
2. `couchpotato/core/database.py` - Database operations  
3. `couchpotato/core/logger.py` - Logging system
4. `couchpotato/runner.py` - Application startup

### Step 3: Downloader Updates
Priority order based on popularity:
1. SABnzbd
2. Transmission  
3. qBittorrent
4. Deluge
5. Others

### Step 4: Notification Updates
1. Email (most critical)
2. Plex
3. Pushover
4. Others

## Risk Mitigation

### Backup Strategy
1. Full database backup before migration
2. Configuration backup
3. Docker volume snapshots

### Rollback Plan
1. Keep Python 2 Docker image available
2. Database compatibility checks
3. Configuration format validation

### Testing Checklist
- [ ] Application starts without errors
- [ ] All plugins load successfully
- [ ] Database migration works
- [ ] Configuration parsing works
- [ ] Download clients connect
- [ ] Notifications send
- [ ] Web interface responsive
- [ ] API endpoints functional
- [ ] File operations work
- [ ] Search providers functional

## Timeline Estimate

- **Phase 1 (Preparation)**: 1-2 days
- **Phase 2 (Core Updates)**: 3-5 days  
- **Phase 3 (Testing)**: 2-3 days
- **Phase 4 (Validation)**: 1-2 days

**Total Estimated Time**: 1-2 weeks of focused development

## Post-Migration Benefits

1. **Security**: Python 3.12 has latest security fixes
2. **Performance**: Better memory management and speed
3. **Maintainability**: Access to modern Python features
4. **Future-proofing**: Python 2 is end-of-life
5. **Dependencies**: Access to newer library versions

## Notes

- The bundled `libs/` directory contains many libraries with existing Python 2/3 compatibility
- Focus migration efforts on the main application code in `couchpotato/`
- Tornado web framework in libs already supports Python 3
- Use the Docker environment for safe testing and development