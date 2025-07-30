# CouchPotato Python 2 → 3.12 Enhanced Upgrade Plan

## Executive Summary

This enhanced upgrade plan builds upon the excellent foundation already established in `PYTHON3-UPGRADE-PLAN.md` and incorporates modern security practices, dependency management, and Python 3.12-specific optimizations. The project is well-positioned for migration with existing compatibility infrastructure and comprehensive testing frameworks.

## Current State Assessment ✅

### Strengths Identified
- **Robust Testing Infrastructure**: Complete test suite with 29 unit tests, health checks, and integration tests
- **Existing Compatibility Layer**: `couchpotato/core/compat.py` already implements Python 2/3 compatibility functions
- **Docker Infrastructure**: Both Python 2.7 and 3.12 containers ready for testing
- **Bundled Dependencies**: Many libraries (Tornado, html5lib, guessit) already Python 3 compatible
- **Systematic Planning**: Detailed migration strategy and risk mitigation already documented

### Key Issues Requiring Migration
1. **Import Statements**: 15+ files using `urllib2`, need migration to `urllib.request/urllib.error`
2. **Dictionary Iteration**: 30+ instances of `.iteritems()` requiring migration to `.items()`
3. **String Handling**: `basestring` usage and Unicode handling inconsistencies
4. **Exception Syntax**: Old-style `except Exception, e:` syntax in several files
5. **Entry Point**: Main shebang still points to `python2`

## Enhanced Migration Strategy

### Phase 1: Security & Infrastructure Hardening (Days 1-2)

#### 1.1 Security-First Dependency Analysis
```bash
# Create comprehensive dependency audit
pip-audit --requirements-file requirements-dev.txt --output audit-report.json

# Update to secure versions
pip install --upgrade six future configparser
pip install cryptography>=3.4.8  # For secure crypto operations
pip install requests>=2.28.0     # Latest security patches
```

#### 1.2 Enhanced Compatibility Layer
Extend existing `couchpotato/core/compat.py` with:
```python
# Add secure defaults for Python 3.12
import ssl
import urllib.request
import urllib.error

# Secure SSL context for Python 3.12
def create_secure_context():
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context

# Enhanced HTTP handling with security
def secure_urlopen(url, data=None, timeout=30):
    if hasattr(ssl, 'create_default_context'):
        context = create_secure_context()
        return urllib.request.urlopen(url, data=data, timeout=timeout, context=context)
    else:
        return urllib.request.urlopen(url, data=data, timeout=timeout)
```

#### 1.3 Modernize Entry Point
Update `CouchPotato.py`:
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

import sys
if sys.version_info < (3, 8):
    raise RuntimeError("Python 3.8 or higher required")
```

### Phase 2: Systematic Code Migration (Days 3-6)

#### 2.1 Priority Migration Order
Based on impact analysis and dependency graph:

**Tier 1: Core Infrastructure (Day 3)**
1. `couchpotato/core/settings.py` - Configuration system
2. `couchpotato/core/database.py` - Data persistence
3. `couchpotato/core/logger.py` - Logging framework
4. `couchpotato/runner.py` - Application bootstrap

**Tier 2: Plugin System (Day 4)**
1. `couchpotato/core/plugins/base.py` - Plugin framework
2. `couchpotato/core/event.py` - Event system
3. `couchpotato/core/_base/_core.py` - Base classes

**Tier 3: Download Clients (Day 5)**
1. `couchpotato/core/downloaders/transmission.py`
2. `couchpotato/core/downloaders/qbittorrent.py`
3. `couchpotato/core/downloaders/deluge.py`
4. `couchpotato/core/downloaders/utorrent.py`

**Tier 4: Notifications & Media (Day 6)**
1. `couchpotato/core/notifications/` - All notification modules
2. `couchpotato/core/media/` - Media handling
3. `couchpotato/core/helpers/` - Utility functions

#### 2.2 Automated Migration Tools
Create migration scripts for common patterns:

```bash
# Script: migrate_imports.py
#!/usr/bin/env python3
import re
import sys

def migrate_urllib2_imports(file_path):
    """Convert urllib2 imports to urllib.request/urllib.error"""
    replacements = [
        (r'import urllib2', 'import urllib.request\nimport urllib.error'),
        (r'urllib2\.urlopen', 'urllib.request.urlopen'),
        (r'urllib2\.Request', 'urllib.request.Request'),
        (r'urllib2\.HTTPError', 'urllib.error.HTTPError'),
        (r'urllib2\.URLError', 'urllib.error.URLError'),
    ]
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)
    
    with open(file_path, 'w') as f:
        f.write(content)

def migrate_iteritems(file_path):
    """Convert .iteritems() to .items()"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Add compat import if not present
    if 'from couchpotato.core.compat import iteritems' not in content:
        content = 'from couchpotato.core.compat import iteritems\n' + content
    
    # Replace .iteritems() with iteritems()
    content = re.sub(r'(\w+)\.iteritems\(\)', r'iteritems(\1)', content)
    
    with open(file_path, 'w') as f:
        f.write(content)
```

#### 2.3 String and Unicode Handling
Implement comprehensive string handling strategy:

```python
# Add to couchpotato/core/compat.py
def safe_decode(data, encoding='utf-8', errors='replace'):
    """Safely decode bytes to string in Python 3"""
    if isinstance(data, bytes):
        return data.decode(encoding, errors)
    return data

def safe_encode(data, encoding='utf-8', errors='replace'):
    """Safely encode string to bytes in Python 3"""
    if isinstance(data, str):
        return data.encode(encoding, errors)
    return data
```

### Phase 3: Security & Performance Optimization (Days 7-8)

#### 3.1 Dependency Security Audit
Replace or update vulnerable dependencies:

```python
# requirements-python3.txt
six>=1.16.0                    # Latest compatibility layer
future>=0.18.3                 # Python 2/3 compatibility
requests>=2.31.0               # Security patches
cryptography>=41.0.0           # Latest crypto library
tornado>=6.3.3                 # Web framework security updates
Pillow>=10.0.0                 # Image processing security
lxml>=4.9.3                    # XML processing security

# Development dependencies
pytest>=7.4.0                  # Modern testing framework
pytest-cov>=4.1.0             # Coverage reporting
black>=23.7.0                  # Code formatting
bandit>=1.7.5                  # Security linting
safety>=2.3.0                  # Vulnerability scanning
```

#### 3.2 Security Hardening
Implement security best practices:

```python
# couchpotato/core/security.py
import secrets
import hashlib
import hmac
from cryptography.fernet import Fernet

class SecurityManager:
    def __init__(self):
        self.secret_key = self._generate_secret_key()
        self.cipher = Fernet(self.secret_key)
    
    def _generate_secret_key(self):
        """Generate cryptographically secure secret key"""
        return Fernet.generate_key()
    
    def encrypt_sensitive_data(self, data):
        """Encrypt sensitive configuration data"""
        return self.cipher.encrypt(data.encode())
    
    def decrypt_sensitive_data(self, encrypted_data):
        """Decrypt sensitive configuration data"""
        return self.cipher.decrypt(encrypted_data).decode()
    
    def generate_api_key(self):
        """Generate secure API key"""
        return secrets.token_urlsafe(32)
    
    def verify_api_key(self, provided_key, stored_key_hash):
        """Verify API key using constant-time comparison"""
        return hmac.compare_digest(
            hashlib.sha256(provided_key.encode()).hexdigest(),
            stored_key_hash
        )
```

#### 3.3 Performance Optimizations for Python 3.12
Leverage Python 3.12 performance improvements:

```python
# Use pathlib for better path handling
from pathlib import Path

# Leverage dataclasses for better performance
from dataclasses import dataclass
from typing import Optional, List, Dict

@dataclass
class MovieInfo:
    title: str
    year: Optional[int] = None
    imdb_id: Optional[str] = None
    quality: Optional[str] = None
    
    def __post_init__(self):
        if self.year and self.year < 1888:  # First motion picture
            raise ValueError(f"Invalid year: {self.year}")
```

### Phase 4: Comprehensive Testing & Validation (Days 9-10)

#### 4.1 Enhanced Test Suite
Build upon existing test infrastructure:

```bash
# Create comprehensive test execution script
#!/bin/bash
# test_python3_migration.sh

echo "🧪 Running Python 3.12 Migration Test Suite"

# 1. Security vulnerability scan
echo "🔍 Security Scan..."
bandit -r couchpotato/ -f json -o security-report.json

# 2. Code quality analysis
echo "📊 Code Quality Analysis..."
flake8 couchpotato/ --count --statistics

# 3. Unit tests with coverage
echo "🔬 Unit Tests..."
python3 -m pytest couchpotato/ --cov=couchpotato --cov-report=html --cov-report=term

# 4. Integration tests
echo "🌐 Integration Tests..."
python3 run_all_tests.py

# 5. Performance benchmarks
echo "⚡ Performance Tests..."
python3 -m cProfile -o performance.prof CouchPotato.py --config test_config.ini &
sleep 30
kill $!

# 6. Memory leak detection
echo "🧠 Memory Leak Detection..."
python3 -m tracemalloc CouchPotato.py --config test_config.ini &
sleep 60
kill $!

echo "✅ Migration testing complete!"
```

#### 4.2 Compatibility Matrix Testing
Test across Python versions and platforms:

```yaml
# .github/workflows/python3-migration.yml
name: Python 3 Migration Testing
on: [push, pull_request]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        python-version: ['3.8', '3.9', '3.10', '3.11', '3.12']
        os: [ubuntu-latest, windows-latest, macos-latest]
    
    steps:
    - uses: actions/checkout@v4
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements-python3.txt
        pip install -r requirements-dev.txt
    
    - name: Run test suite
      run: python -m pytest couchpotato/ -v
    
    - name: Security scan
      run: bandit -r couchpotato/
    
    - name: Performance test
      run: python3 test_performance.py
```

### Phase 5: Production Deployment (Days 11-12)

#### 5.1 Production-Ready Docker Configuration
Enhanced Docker setup for Python 3.12:

```dockerfile
# Dockerfile.python3-production
FROM python:3.12-slim-bookworm

# Security: Run as non-root user
RUN groupadd -r couchpotato && useradd -r -g couchpotato couchpotato

# Install system dependencies with security updates
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        mediainfo \
        unrar \
        p7zip-full \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set up application directory
WORKDIR /app
COPY --chown=couchpotato:couchpotato . /app/

# Install Python dependencies with hash verification
COPY requirements-python3.txt /app/
RUN pip install --no-cache-dir --require-hashes -r requirements-python3.txt

# Security: Remove package manager
RUN apt-get remove -y apt-get && apt-get autoremove -y

# Health check with timeout
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5050/api/app.version || exit 1

USER couchpotato
EXPOSE 5050

CMD ["python3", "CouchPotato.py", "--console_log", "--config_file", "/config/settings.conf"]
```

#### 5.2 Migration Rollback Strategy
Implement comprehensive rollback procedures:

```bash
#!/bin/bash
# rollback_python2.sh

echo "🔄 Rolling back to Python 2.7..."

# 1. Stop Python 3 container
docker stop couchpotato-python3 || true

# 2. Restore Python 2 container
docker run -d --name couchpotato-python2-restore \
    -p 5050:5050 \
    -v couchpotato-config:/config \
    -v couchpotato-data:/data \
    couchpotato:python2

# 3. Verify rollback success
sleep 30
if curl -f http://localhost:5050/; then
    echo "✅ Rollback successful"
    docker rm couchpotato-python3
else
    echo "❌ Rollback failed"
    exit 1
fi
```

## Implementation Timeline

### Week 1: Foundation & Core Migration
- **Days 1-2**: Security audit, dependency updates, infrastructure hardening
- **Days 3-4**: Core system migration (settings, database, logging, plugins)
- **Days 5**: Download client migration
- **Days 6-7**: Notification and media handling migration

### Week 2: Testing & Deployment
- **Days 8-9**: Comprehensive testing, performance optimization
- **Days 10-11**: Production deployment preparation
- **Days 12**: Final validation and go-live

## Security Enhancements for Python 3.12

### 1. Secure by Default
- Enable all SSL/TLS security checks
- Use cryptographically secure random number generation
- Implement proper input validation and sanitization
- Use parameterized queries for database operations

### 2. Dependency Security
- Pin all dependency versions with hash verification
- Regular security scanning with `bandit` and `safety`
- Automated dependency update monitoring
- Container image vulnerability scanning

### 3. Runtime Security
- Run as non-root user in containers
- Implement proper file permissions
- Use security headers for web interface
- Enable security logging and monitoring

## Success Metrics

### Technical Metrics
- ✅ All 29 existing unit tests pass
- ✅ No security vulnerabilities in dependencies
- ✅ Performance equal or better than Python 2.7
- ✅ Memory usage optimization achieved
- ✅ 100% feature parity maintained

### Operational Metrics
- ✅ Zero-downtime migration capability
- ✅ Rollback procedure tested and verified
- ✅ Monitoring and alerting functional
- ✅ Documentation updated and complete

## Risk Mitigation

### High-Impact Risks
1. **Database Compatibility**: Test with database backups, implement migration scripts
2. **Plugin Breakage**: Comprehensive plugin testing, compatibility validation
3. **Performance Regression**: Benchmark before/after, optimization if needed
4. **Security Vulnerabilities**: Regular scanning, immediate patch deployment

### Medium-Impact Risks
1. **Configuration Changes**: Automated migration scripts, validation tools
2. **Third-party Integration**: API compatibility testing, fallback mechanisms
3. **User Interface Changes**: UI/UX validation, user acceptance testing

## Post-Migration Benefits

### Immediate Benefits
- **Security**: Latest Python 3.12 security features and patches
- **Performance**: 10-15% performance improvement expected
- **Maintainability**: Modern Python features and better error handling
- **Dependency Access**: Latest versions of all dependencies

### Long-term Benefits
- **Future-Proofing**: Python 2 EOL compliance
- **Community Support**: Active Python 3 ecosystem
- **Development Velocity**: Modern development tools and practices
- **Compliance**: Security and regulatory compliance improvements

## Conclusion

This enhanced upgrade plan builds upon the excellent foundation already established while incorporating modern security practices and Python 3.12-specific optimizations. The project is well-positioned for a successful migration with minimal risk and maximum benefit.

The existing compatibility infrastructure, comprehensive testing framework, and Docker-based deployment strategy provide a solid foundation for a smooth transition to Python 3.12 with enhanced security and performance characteristics.