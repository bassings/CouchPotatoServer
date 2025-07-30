#!/usr/bin/env python3
"""
CouchPotato Python 2 to 3.12 Migration Script

This script automates the migration of Python 2 code to Python 3.12 compatible code,
incorporating security best practices and modern Python features.

Usage:
    python3 migrate_to_python3.py --analyze    # Analyze codebase for migration issues
    python3 migrate_to_python3.py --migrate    # Perform migration
    python3 migrate_to_python3.py --validate   # Validate migration results
"""

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


class Python3Migrator:
    """Automated Python 2 to 3.12 migration tool for CouchPotato."""
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.couchpotato_dir = self.project_root / "couchpotato"
        self.backup_dir = self.project_root / "migration_backup"
        
        # Files to exclude from migration
        self.exclude_patterns = {
            "*/libs/*",          # Third-party libraries
            "*/test_*",          # Test files (handle separately)
            "*/__pycache__/*",   # Compiled Python
            "*.pyc",
            "*.pyo",
        }
        
        # Track migration statistics
        self.stats = {
            "files_analyzed": 0,
            "files_migrated": 0,
            "urllib2_fixes": 0,
            "iteritems_fixes": 0,
            "exception_fixes": 0,
            "string_fixes": 0,
            "import_fixes": 0,
        }
    
    def should_migrate_file(self, file_path: Path) -> bool:
        """Check if file should be migrated."""
        # Only migrate Python files in couchpotato directory
        if not file_path.suffix == ".py":
            return False
        
        if not str(file_path).startswith(str(self.couchpotato_dir)):
            return False
        
        # Check exclude patterns
        for pattern in self.exclude_patterns:
            if file_path.match(pattern):
                return False
        
        return True
    
    def analyze_codebase(self) -> Dict[str, List[str]]:
        """Analyze codebase for Python 2/3 compatibility issues."""
        print("🔍 Analyzing codebase for Python 2/3 compatibility issues...")
        
        issues = {
            "urllib2_imports": [],
            "iteritems_usage": [],
            "old_exception_syntax": [],
            "basestring_usage": [],
            "print_statements": [],
            "missing_future_imports": [],
        }
        
        python_files = list(self.couchpotato_dir.rglob("*.py"))
        
        for file_path in python_files:
            if not self.should_migrate_file(file_path):
                continue
            
            self.stats["files_analyzed"] += 1
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Check for various Python 2/3 issues
                if re.search(r'import urllib2|from urllib2', content):
                    issues["urllib2_imports"].append(str(file_path))
                
                if re.search(r'\.iteritems\(\)', content):
                    issues["iteritems_usage"].append(str(file_path))
                
                if re.search(r'except\s+\w+\s*,\s*\w+:', content):
                    issues["old_exception_syntax"].append(str(file_path))
                
                if re.search(r'\bbasestring\b', content):
                    issues["basestring_usage"].append(str(file_path))
                
                if re.search(r'\bprint\s+[^(]', content):
                    issues["print_statements"].append(str(file_path))
                
                if not re.search(r'from __future__ import', content):
                    issues["missing_future_imports"].append(str(file_path))
            
            except Exception as e:
                print(f"⚠️  Error analyzing {file_path}: {e}")
        
        return issues
    
    def create_backup(self):
        """Create backup of current codebase."""
        print("💾 Creating backup of current codebase...")
        
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        
        shutil.copytree(self.couchpotato_dir, self.backup_dir / "couchpotato")
        print(f"✅ Backup created at {self.backup_dir}")
    
    def add_future_imports(self, file_path: Path) -> bool:
        """Add comprehensive future imports to Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check if future imports already exist
            if 'from __future__ import' in content:
                return False
            
            # Find the insertion point (after shebang and encoding, before other imports)
            lines = content.split('\n')
            insert_idx = 0
            
            for i, line in enumerate(lines):
                if line.startswith('#!') or line.startswith('# -*- coding'):
                    insert_idx = i + 1
                elif line.strip() and not line.startswith('#'):
                    break
            
            # Add future imports
            future_import = "from __future__ import absolute_import, division, print_function, unicode_literals"
            lines.insert(insert_idx, future_import)
            
            # Write back
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            self.stats["import_fixes"] += 1
            return True
            
        except Exception as e:
            print(f"⚠️  Error adding future imports to {file_path}: {e}")
            return False
    
    def migrate_urllib2(self, file_path: Path) -> bool:
        """Migrate urllib2 imports to urllib.request/urllib.error."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Replace urllib2 imports with urllib.request and urllib.error
            replacements = [
                (r'import urllib2\b', 'import urllib.request\nimport urllib.error'),
                (r'from urllib2 import', 'from urllib.request import'),
                (r'urllib2\.urlopen', 'urllib.request.urlopen'),
                (r'urllib2\.Request', 'urllib.request.Request'),
                (r'urllib2\.HTTPError', 'urllib.error.HTTPError'),
                (r'urllib2\.URLError', 'urllib.error.URLError'),
                (r'urllib2\.build_opener', 'urllib.request.build_opener'),
                (r'urllib2\.install_opener', 'urllib.request.install_opener'),
                (r'urllib2\.HTTPHandler', 'urllib.request.HTTPHandler'),
                (r'urllib2\.HTTPSHandler', 'urllib.request.HTTPSHandler'),
            ]
            
            for pattern, replacement in replacements:
                content = re.sub(pattern, replacement, content)
            
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.stats["urllib2_fixes"] += 1
                return True
            
            return False
            
        except Exception as e:
            print(f"⚠️  Error migrating urllib2 in {file_path}: {e}")
            return False
    
    def migrate_iteritems(self, file_path: Path) -> bool:
        """Migrate .iteritems() to use compatibility function."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Check if iteritems is used
            if not re.search(r'\.iteritems\(\)', content):
                return False
            
            # Add compatibility import if not present
            if 'from couchpotato.core.compat import iteritems' not in content:
                # Find a good place to add the import
                lines = content.split('\n')
                import_added = False
                
                for i, line in enumerate(lines):
                    if line.startswith('from couchpotato.core') or line.startswith('import'):
                        lines.insert(i, 'from couchpotato.core.compat import iteritems')
                        import_added = True
                        break
                
                if not import_added:
                    # Add after future imports
                    for i, line in enumerate(lines):
                        if 'from __future__ import' in line:
                            lines.insert(i + 1, 'from couchpotato.core.compat import iteritems')
                            import_added = True
                            break
                
                if not import_added:
                    lines.insert(0, 'from couchpotato.core.compat import iteritems')
                
                content = '\n'.join(lines)
            
            # Replace .iteritems() with iteritems()
            content = re.sub(r'(\w+)\.iteritems\(\)', r'iteritems(\1)', content)
            
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.stats["iteritems_fixes"] += 1
                return True
            
            return False
            
        except Exception as e:
            print(f"⚠️  Error migrating iteritems in {file_path}: {e}")
            return False
    
    def migrate_exception_syntax(self, file_path: Path) -> bool:
        """Migrate old-style exception syntax."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Replace old exception syntax: except Exception, e: -> except Exception as e:
            content = re.sub(
                r'except\s+([^,\s]+)\s*,\s*(\w+)\s*:',
                r'except \1 as \2:',
                content
            )
            
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.stats["exception_fixes"] += 1
                return True
            
            return False
            
        except Exception as e:
            print(f"⚠️  Error migrating exception syntax in {file_path}: {e}")
            return False
    
    def migrate_string_types(self, file_path: Path) -> bool:
        """Migrate basestring usage to compatibility function."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Check if basestring is used
            if not re.search(r'\bbasestring\b', content):
                return False
            
            # Add compatibility import if not present
            if 'from couchpotato.core.compat import string_types' not in content:
                lines = content.split('\n')
                # Add import after other compat imports or at the beginning
                for i, line in enumerate(lines):
                    if 'from couchpotato.core.compat import' in line:
                        lines[i] = line.rstrip() + ', string_types'
                        break
                else:
                    # Add new import
                    lines.insert(0, 'from couchpotato.core.compat import string_types')
                content = '\n'.join(lines)
            
            # Replace basestring with string_types
            content = re.sub(r'\bbasestring\b', 'string_types', content)
            
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.stats["string_fixes"] += 1
                return True
            
            return False
            
        except Exception as e:
            print(f"⚠️  Error migrating string types in {file_path}: {e}")
            return False
    
    def migrate_file(self, file_path: Path) -> bool:
        """Migrate a single file from Python 2 to Python 3."""
        print(f"🔄 Migrating {file_path}")
        
        changes_made = False
        
        # Apply all migrations
        changes_made |= self.add_future_imports(file_path)
        changes_made |= self.migrate_urllib2(file_path)
        changes_made |= self.migrate_iteritems(file_path)
        changes_made |= self.migrate_exception_syntax(file_path)
        changes_made |= self.migrate_string_types(file_path)
        
        if changes_made:
            self.stats["files_migrated"] += 1
        
        return changes_made
    
    def migrate_codebase(self):
        """Migrate entire codebase from Python 2 to Python 3."""
        print("🚀 Starting Python 2 to 3.12 migration...")
        
        # Create backup first
        self.create_backup()
        
        # Get all Python files to migrate
        python_files = [
            f for f in self.couchpotato_dir.rglob("*.py")
            if self.should_migrate_file(f)
        ]
        
        print(f"📝 Found {len(python_files)} files to migrate")
        
        # Migrate each file
        for file_path in python_files:
            try:
                self.migrate_file(file_path)
            except Exception as e:
                print(f"❌ Error migrating {file_path}: {e}")
        
        # Update main entry point
        self.update_entry_point()
        
        print("✅ Migration completed!")
        self.print_statistics()
    
    def update_entry_point(self):
        """Update the main CouchPotato.py entry point."""
        entry_point = self.project_root / "CouchPotato.py"
        
        if not entry_point.exists():
            return
        
        try:
            with open(entry_point, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Update shebang to python3
            content = re.sub(r'#!/usr/bin/env python2?', '#!/usr/bin/env python3', content)
            
            # Add Python version check
            version_check = '''
import sys
if sys.version_info < (3, 8):
    print("Error: Python 3.8 or higher is required")
    sys.exit(1)
'''
            
            if 'sys.version_info' not in content:
                lines = content.split('\n')
                # Insert after future imports
                for i, line in enumerate(lines):
                    if 'from __future__ import' in line:
                        lines.insert(i + 1, version_check)
                        break
                content = '\n'.join(lines)
            
            with open(entry_point, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ Updated entry point: {entry_point}")
            
        except Exception as e:
            print(f"⚠️  Error updating entry point: {e}")
    
    def validate_migration(self) -> bool:
        """Validate the migration results."""
        print("🔍 Validating migration results...")
        
        # Check for syntax errors
        python_files = [
            f for f in self.couchpotato_dir.rglob("*.py")
            if self.should_migrate_file(f)
        ]
        
        syntax_errors = []
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Try to compile the file
                compile(content, str(file_path), 'exec')
                
            except SyntaxError as e:
                syntax_errors.append((file_path, str(e)))
            except Exception as e:
                print(f"⚠️  Error validating {file_path}: {e}")
        
        if syntax_errors:
            print(f"❌ Found {len(syntax_errors)} syntax errors:")
            for file_path, error in syntax_errors:
                print(f"   {file_path}: {error}")
            return False
        
        print("✅ All files passed syntax validation!")
        
        # Run basic import test
        try:
            import_test_result = subprocess.run(
                [sys.executable, "-c", "import couchpotato"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if import_test_result.returncode == 0:
                print("✅ Basic import test passed!")
                return True
            else:
                print(f"❌ Import test failed: {import_test_result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("⚠️  Import test timed out")
            return False
        except Exception as e:
            print(f"⚠️  Error running import test: {e}")
            return False
    
    def print_statistics(self):
        """Print migration statistics."""
        print("\n📊 Migration Statistics:")
        print(f"   Files analyzed: {self.stats['files_analyzed']}")
        print(f"   Files migrated: {self.stats['files_migrated']}")
        print(f"   urllib2 fixes: {self.stats['urllib2_fixes']}")
        print(f"   iteritems fixes: {self.stats['iteritems_fixes']}")
        print(f"   Exception syntax fixes: {self.stats['exception_fixes']}")
        print(f"   String type fixes: {self.stats['string_fixes']}")
        print(f"   Future import additions: {self.stats['import_fixes']}")


def main():
    """Main entry point for the migration script."""
    parser = argparse.ArgumentParser(
        description="CouchPotato Python 2 to 3.12 Migration Tool"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze codebase for migration issues"
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Perform migration"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate migration results"
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: current directory)"
    )
    
    args = parser.parse_args()
    
    if not any([args.analyze, args.migrate, args.validate]):
        parser.error("Must specify one of --analyze, --migrate, or --validate")
    
    migrator = Python3Migrator(args.project_root)
    
    if args.analyze:
        issues = migrator.analyze_codebase()
        
        print("\n📋 Analysis Results:")
        for issue_type, files in issues.items():
            if files:
                print(f"\n{issue_type.replace('_', ' ').title()}: {len(files)} files")
                for file_path in files[:5]:  # Show first 5 files
                    print(f"   - {file_path}")
                if len(files) > 5:
                    print(f"   ... and {len(files) - 5} more")
    
    elif args.migrate:
        migrator.migrate_codebase()
    
    elif args.validate:
        success = migrator.validate_migration()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()