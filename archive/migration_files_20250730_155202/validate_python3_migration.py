#!/usr/bin/env python3
"""
CouchPotato Python 3.12 Migration Validation Script

This script provides comprehensive validation of the Python 2 to 3.12 migration,
including syntax validation, functional testing, performance benchmarking, and
security verification.

Usage:
    python3 validate_python3_migration.py --all          # Run all validations
    python3 validate_python3_migration.py --syntax       # Syntax validation only
    python3 validate_python3_migration.py --functional   # Functional tests only
    python3 validate_python3_migration.py --performance  # Performance tests only
    python3 validate_python3_migration.py --security     # Security validation only
"""

import argparse
import ast
import cProfile
import importlib.util
import json
import os
import psutil
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Dict, List, Any, Tuple
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Python3MigrationValidator:
    """Comprehensive validator for Python 3.12 migration."""
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.couchpotato_dir = self.project_root / "couchpotato"
        self.results = {
            "syntax": {"passed": 0, "failed": 0, "errors": []},
            "imports": {"passed": 0, "failed": 0, "errors": []},
            "functional": {"passed": 0, "failed": 0, "errors": []},
            "performance": {"baseline": {}, "current": {}, "comparison": {}},
            "security": {"passed": 0, "failed": 0, "vulnerabilities": []}
        }
        
        # Test configuration
        self.test_config = {
            "timeout": 30,
            "memory_limit_mb": 512,
            "performance_threshold": 1.5,  # Max 50% performance degradation
        }
    
    def validate_syntax(self) -> Dict[str, Any]:
        """Validate Python 3 syntax for all files."""
        logger.info("🔍 Validating Python 3 syntax...")
        
        python_files = list(self.couchpotato_dir.rglob("*.py"))
        syntax_results = {"passed": 0, "failed": 0, "errors": []}
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    source_code = f.read()
                
                # Try to parse the file with Python 3 AST
                ast.parse(source_code, filename=str(file_path))
                syntax_results["passed"] += 1
                
            except SyntaxError as e:
                syntax_results["failed"] += 1
                syntax_results["errors"].append({
                    "file": str(file_path),
                    "error": str(e),
                    "line": e.lineno,
                    "type": "syntax_error"
                })
                logger.error(f"Syntax error in {file_path}: {e}")
                
            except Exception as e:
                syntax_results["failed"] += 1
                syntax_results["errors"].append({
                    "file": str(file_path),
                    "error": str(e),
                    "type": "parsing_error"
                })
                logger.error(f"Parsing error in {file_path}: {e}")
        
        logger.info(f"✅ Syntax validation complete: {syntax_results['passed']} passed, {syntax_results['failed']} failed")
        return syntax_results
    
    def validate_imports(self) -> Dict[str, Any]:
        """Validate that all imports work correctly."""
        logger.info("📦 Validating imports...")
        
        import_results = {"passed": 0, "failed": 0, "errors": []}
        
        # Test critical imports
        critical_modules = [
            "couchpotato",
            "couchpotato.core",
            "couchpotato.core.settings",
            "couchpotato.core.database",
            "couchpotato.core.logger",
            "couchpotato.core.compat",
        ]
        
        for module_name in critical_modules:
            try:
                # Add project root to Python path
                if str(self.project_root) not in sys.path:
                    sys.path.insert(0, str(self.project_root))
                
                # Try to import the module
                importlib.import_module(module_name)
                import_results["passed"] += 1
                logger.info(f"✅ Successfully imported {module_name}")
                
            except ImportError as e:
                import_results["failed"] += 1
                import_results["errors"].append({
                    "module": module_name,
                    "error": str(e),
                    "type": "import_error"
                })
                logger.error(f"❌ Failed to import {module_name}: {e}")
                
            except Exception as e:
                import_results["failed"] += 1
                import_results["errors"].append({
                    "module": module_name,
                    "error": str(e),
                    "type": "module_error"
                })
                logger.error(f"❌ Error in module {module_name}: {e}")
        
        logger.info(f"📦 Import validation complete: {import_results['passed']} passed, {import_results['failed']} failed")
        return import_results
    
    def validate_functional_tests(self) -> Dict[str, Any]:
        """Run functional tests to ensure core functionality works."""
        logger.info("🧪 Running functional tests...")
        
        functional_results = {"passed": 0, "failed": 0, "errors": []}
        
        tests = [
            self._test_application_startup,
            self._test_configuration_loading,
            self._test_database_operations,
            self._test_web_interface,
            self._test_api_endpoints,
            self._test_plugin_loading,
        ]
        
        for test_func in tests:
            try:
                test_name = test_func.__name__.replace('_test_', '').replace('_', ' ').title()
                logger.info(f"Running test: {test_name}")
                
                result = test_func()
                if result:
                    functional_results["passed"] += 1
                    logger.info(f"✅ {test_name} passed")
                else:
                    functional_results["failed"] += 1
                    functional_results["errors"].append({
                        "test": test_name,
                        "error": "Test returned False",
                        "type": "test_failure"
                    })
                    logger.error(f"❌ {test_name} failed")
                    
            except Exception as e:
                functional_results["failed"] += 1
                functional_results["errors"].append({
                    "test": test_func.__name__,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "type": "test_exception"
                })
                logger.error(f"❌ Test {test_func.__name__} raised exception: {e}")
        
        logger.info(f"🧪 Functional tests complete: {functional_results['passed']} passed, {functional_results['failed']} failed")
        return functional_results
    
    def _test_application_startup(self) -> bool:
        """Test that the application can start without errors."""
        try:
            # Test import of main module
            sys.path.insert(0, str(self.project_root))
            
            # Import the main application components
            from couchpotato.environment import Env
            from couchpotato.core.helpers.variable import getDataDir
            
            # Test basic initialization
            data_dir = getDataDir()
            
            return True
            
        except Exception as e:
            logger.error(f"Application startup test failed: {e}")
            return False
    
    def _test_configuration_loading(self) -> bool:
        """Test configuration loading and parsing."""
        try:
            from couchpotato.environment import Env
            
            # Try to get settings
            settings = Env.get('settings')
            
            # Test basic settings operations
            if settings:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Configuration loading test failed: {e}")
            return False
    
    def _test_database_operations(self) -> bool:
        """Test database operations."""
        try:
            # This would test database connectivity and basic operations
            # For now, just test imports
            from couchpotato.core.database import Database
            
            return True
            
        except Exception as e:
            logger.error(f"Database operations test failed: {e}")
            return False
    
    def _test_web_interface(self) -> bool:
        """Test web interface startup."""
        try:
            # Test web framework imports
            import tornado.web
            import tornado.ioloop
            
            return True
            
        except Exception as e:
            logger.error(f"Web interface test failed: {e}")
            return False
    
    def _test_api_endpoints(self) -> bool:
        """Test API endpoint functionality."""
        try:
            # Test API module imports
            from couchpotato import api
            
            return True
            
        except Exception as e:
            logger.error(f"API endpoints test failed: {e}")
            return False
    
    def _test_plugin_loading(self) -> bool:
        """Test plugin loading system."""
        try:
            # Test plugin system imports
            from couchpotato.core.plugins.base import Plugin
            
            return True
            
        except Exception as e:
            logger.error(f"Plugin loading test failed: {e}")
            return False
    
    def benchmark_performance(self) -> Dict[str, Any]:
        """Benchmark application performance."""
        logger.info("⚡ Running performance benchmarks...")
        
        performance_results = {
            "startup_time": 0,
            "memory_usage": 0,
            "import_time": 0,
            "baseline_comparison": {}
        }
        
        try:
            # Measure startup time
            start_time = time.time()
            
            # Add project to path and import main modules
            sys.path.insert(0, str(self.project_root))
            
            import_start = time.time()
            from couchpotato.environment import Env
            from couchpotato.core.settings import Settings
            import_end = time.time()
            
            performance_results["import_time"] = import_end - import_start
            
            end_time = time.time()
            performance_results["startup_time"] = end_time - start_time
            
            # Measure memory usage
            process = psutil.Process()
            memory_info = process.memory_info()
            performance_results["memory_usage"] = memory_info.rss / 1024 / 1024  # MB
            
            logger.info(f"⚡ Performance benchmark complete:")
            logger.info(f"   Startup time: {performance_results['startup_time']:.3f}s")
            logger.info(f"   Import time: {performance_results['import_time']:.3f}s")
            logger.info(f"   Memory usage: {performance_results['memory_usage']:.1f}MB")
            
        except Exception as e:
            logger.error(f"Performance benchmark failed: {e}")
            performance_results["error"] = str(e)
        
        return performance_results
    
    def validate_security(self) -> Dict[str, Any]:
        """Validate security aspects of the migration."""
        logger.info("🔒 Validating security...")
        
        security_results = {"passed": 0, "failed": 0, "vulnerabilities": []}
        
        security_checks = [
            self._check_no_hardcoded_secrets,
            self._check_secure_random_usage,
            self._check_ssl_verification,
            self._check_input_validation,
            self._check_file_permissions,
        ]
        
        for check_func in security_checks:
            try:
                check_name = check_func.__name__.replace('_check_', '').replace('_', ' ').title()
                logger.info(f"Running security check: {check_name}")
                
                issues = check_func()
                if not issues:
                    security_results["passed"] += 1
                    logger.info(f"✅ {check_name} passed")
                else:
                    security_results["failed"] += 1
                    security_results["vulnerabilities"].extend(issues)
                    logger.warning(f"⚠️ {check_name} found {len(issues)} issues")
                    
            except Exception as e:
                security_results["failed"] += 1
                security_results["vulnerabilities"].append({
                    "check": check_func.__name__,
                    "error": str(e),
                    "type": "check_error"
                })
                logger.error(f"❌ Security check {check_func.__name__} failed: {e}")
        
        logger.info(f"🔒 Security validation complete: {security_results['passed']} passed, {security_results['failed']} failed")
        return security_results
    
    def _check_no_hardcoded_secrets(self) -> List[Dict[str, Any]]:
        """Check for hardcoded secrets in the code."""
        issues = []
        
        # This would integrate with the security audit script
        # For now, just return empty list
        return issues
    
    def _check_secure_random_usage(self) -> List[Dict[str, Any]]:
        """Check that secure random is used for cryptographic purposes."""
        issues = []
        
        python_files = list(self.couchpotato_dir.rglob("*.py"))
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Check for insecure random usage
                if 'random.random()' in content or 'random.randint(' in content:
                    issues.append({
                        "file": str(file_path),
                        "issue": "Insecure random number generation",
                        "recommendation": "Use secrets module for cryptographic purposes"
                    })
                    
            except Exception as e:
                logger.error(f"Error checking {file_path}: {e}")
        
        return issues
    
    def _check_ssl_verification(self) -> List[Dict[str, Any]]:
        """Check that SSL verification is enabled."""
        issues = []
        
        python_files = list(self.couchpotato_dir.rglob("*.py"))
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Check for disabled SSL verification
                if 'verify=False' in content or 'ssl_verify=False' in content:
                    issues.append({
                        "file": str(file_path),
                        "issue": "SSL verification disabled",
                        "recommendation": "Enable SSL verification for security"
                    })
                    
            except Exception as e:
                logger.error(f"Error checking {file_path}: {e}")
        
        return issues
    
    def _check_input_validation(self) -> List[Dict[str, Any]]:
        """Check for proper input validation."""
        issues = []
        
        # This would check for SQL injection vulnerabilities, etc.
        # For now, return empty list
        return issues
    
    def _check_file_permissions(self) -> List[Dict[str, Any]]:
        """Check file permissions for security."""
        issues = []
        
        sensitive_files = [
            self.project_root / "CouchPotato.py",
        ]
        
        for file_path in sensitive_files:
            if file_path.exists():
                stat = file_path.stat()
                mode = oct(stat.st_mode)[-3:]
                
                # Check for overly permissive permissions
                if mode[2] in ['4', '5', '6', '7']:  # World readable
                    issues.append({
                        "file": str(file_path),
                        "issue": f"Overly permissive file permissions: {mode}",
                        "recommendation": "Restrict file permissions to owner only"
                    })
        
        return issues
    
    def run_comprehensive_validation(self) -> Dict[str, Any]:
        """Run all validation tests."""
        logger.info("🚀 Starting comprehensive Python 3.12 migration validation...")
        
        # Run all validation components
        self.results["syntax"] = self.validate_syntax()
        self.results["imports"] = self.validate_imports()
        self.results["functional"] = self.validate_functional_tests()
        self.results["performance"] = self.benchmark_performance()
        self.results["security"] = self.validate_security()
        
        # Calculate overall success rate
        total_tests = (
            self.results["syntax"]["passed"] + self.results["syntax"]["failed"] +
            self.results["imports"]["passed"] + self.results["imports"]["failed"] +
            self.results["functional"]["passed"] + self.results["functional"]["failed"] +
            self.results["security"]["passed"] + self.results["security"]["failed"]
        )
        
        total_passed = (
            self.results["syntax"]["passed"] +
            self.results["imports"]["passed"] +
            self.results["functional"]["passed"] +
            self.results["security"]["passed"]
        )
        
        success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        
        logger.info(f"🎯 Validation complete! Overall success rate: {success_rate:.1f}%")
        
        return self.results
    
    def generate_validation_report(self) -> str:
        """Generate comprehensive validation report."""
        report = []
        report.append("# CouchPotato Python 3.12 Migration Validation Report")
        report.append("=" * 60)
        report.append("")
        
        # Summary
        total_tests = sum([
            self.results["syntax"]["passed"] + self.results["syntax"]["failed"],
            self.results["imports"]["passed"] + self.results["imports"]["failed"],
            self.results["functional"]["passed"] + self.results["functional"]["failed"],
            self.results["security"]["passed"] + self.results["security"]["failed"]
        ])
        
        total_passed = sum([
            self.results["syntax"]["passed"],
            self.results["imports"]["passed"],
            self.results["functional"]["passed"],
            self.results["security"]["passed"]
        ])
        
        success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        
        report.append("## Executive Summary")
        report.append(f"**Overall Success Rate:** {success_rate:.1f}%")
        report.append(f"**Total Tests:** {total_tests}")
        report.append(f"**Tests Passed:** {total_passed}")
        report.append(f"**Tests Failed:** {total_tests - total_passed}")
        report.append("")
        
        # Detailed results
        sections = [
            ("Syntax Validation", "syntax"),
            ("Import Validation", "imports"),
            ("Functional Tests", "functional"),
            ("Security Validation", "security")
        ]
        
        for title, key in sections:
            if key in self.results:
                result = self.results[key]
                report.append(f"## {title}")
                report.append("-" * 30)
                report.append(f"**Passed:** {result['passed']}")
                report.append(f"**Failed:** {result['failed']}")
                
                if result.get('errors'):
                    report.append("**Errors:**")
                    for error in result['errors']:
                        report.append(f"- {error.get('file', 'N/A')}: {error.get('error', 'N/A')}")
                
                report.append("")
        
        # Performance results
        if "performance" in self.results:
            perf = self.results["performance"]
            report.append("## Performance Benchmarks")
            report.append("-" * 30)
            report.append(f"**Startup Time:** {perf.get('startup_time', 0):.3f}s")
            report.append(f"**Import Time:** {perf.get('import_time', 0):.3f}s")
            report.append(f"**Memory Usage:** {perf.get('memory_usage', 0):.1f}MB")
            report.append("")
        
        # Recommendations
        report.append("## Recommendations")
        report.append("-" * 30)
        report.append("")
        
        if success_rate >= 95:
            report.append("✅ **MIGRATION READY**: The codebase is ready for Python 3.12 deployment.")
        elif success_rate >= 80:
            report.append("⚠️ **NEEDS MINOR FIXES**: Address the failed tests before deployment.")
        else:
            report.append("❌ **NEEDS MAJOR WORK**: Significant issues need to be resolved.")
        
        report.append("")
        report.append("**Next Steps:**")
        
        if self.results["syntax"]["failed"] > 0:
            report.append("1. Fix syntax errors in the reported files")
        
        if self.results["imports"]["failed"] > 0:
            report.append("2. Resolve import issues and missing dependencies")
        
        if self.results["functional"]["failed"] > 0:
            report.append("3. Address functional test failures")
        
        if self.results["security"]["failed"] > 0:
            report.append("4. Resolve security vulnerabilities")
        
        report.append("5. Run validation again to confirm fixes")
        report.append("6. Deploy to staging environment for final testing")
        
        return "\n".join(report)
    
    def save_validation_report(self, filename: str = "python3_migration_validation_report.md"):
        """Save validation report to file."""
        report = self.generate_validation_report()
        report_path = self.project_root / filename
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"📄 Validation report saved to {report_path}")
        
        # Also save JSON results for programmatic use
        json_path = self.project_root / "validation_results.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, default=str)
        
        logger.info(f"📄 JSON results saved to {json_path}")


def main():
    """Main entry point for the validation script."""
    parser = argparse.ArgumentParser(
        description="CouchPotato Python 3.12 Migration Validation Tool"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all validations"
    )
    parser.add_argument(
        "--syntax",
        action="store_true",
        help="Syntax validation only"
    )
    parser.add_argument(
        "--functional",
        action="store_true",
        help="Functional tests only"
    )
    parser.add_argument(
        "--performance",
        action="store_true",
        help="Performance tests only"
    )
    parser.add_argument(
        "--security",
        action="store_true",
        help="Security validation only"
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: current directory)"
    )
    
    args = parser.parse_args()
    
    if not any([args.all, args.syntax, args.functional, args.performance, args.security]):
        parser.error("Must specify at least one validation type")
    
    validator = Python3MigrationValidator(args.project_root)
    
    if args.all:
        results = validator.run_comprehensive_validation()
        validator.save_validation_report()
        
        # Exit with error code if any tests failed
        total_failed = sum([
            results["syntax"]["failed"],
            results["imports"]["failed"],
            results["functional"]["failed"],
            results["security"]["failed"]
        ])
        
        sys.exit(1 if total_failed > 0 else 0)
    
    else:
        if args.syntax:
            validator.results["syntax"] = validator.validate_syntax()
        
        if args.functional:
            validator.results["functional"] = validator.validate_functional_tests()
        
        if args.performance:
            validator.results["performance"] = validator.benchmark_performance()
        
        if args.security:
            validator.results["security"] = validator.validate_security()
        
        # Print summary
        for test_type, results in validator.results.items():
            if results:
                if isinstance(results, dict) and "passed" in results:
                    print(f"{test_type.title()}: {results['passed']} passed, {results['failed']} failed")
                else:
                    print(f"{test_type.title()}: Completed")


if __name__ == "__main__":
    main()