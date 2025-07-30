#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
CouchPotato Test Suite Runner

Runs all tests including unit tests, integration tests, and health checks.
Perfect for validating Python 2 to 3 migration.
"""

import sys
import os
import subprocess


def run_command(cmd, description):
    """Run a command and return success status"""
    print("\n" + "="*60)
    print("Running: %s" % description)
    print("="*60)
    
    try:
        result = subprocess.call(cmd, shell=True)
        if result == 0:
            print("✓ %s - PASSED" % description)
            return True
        else:
            print("✗ %s - FAILED (exit code: %d)" % (description, result))
            return False
    except Exception as e:
        print("✗ %s - ERROR: %s" % (description, e))
        return False


def main():
    """Run all CouchPotato tests"""
    print("CouchPotato Complete Test Suite")
    print("===============================")
    print("This validates all functionality for Python 2/3 migration")
    
    # Set environment
    os.environ['PYTHONPATH'] = '/app/libs'
    
    test_commands = [
        (
            'python2 -m nose --where=couchpotato --verbosity=2 couchpotato/environment_test.py',
            "Unit Tests (Environment)"
        ),
        (
            'python2 -m nose --where=couchpotato --verbosity=2',
            "All Unit Tests"
        ),
        (
            'python2 couchpotato/simple_healthcheck.py',
            "Health Check Tests"
        ),
        (
            'python2 -m nose --where=couchpotato --with-coverage --cover-package=couchpotato --cover-erase',
            "Coverage Analysis"
        )
    ]
    
    results = []
    for cmd, description in test_commands:
        success = run_command(cmd, description)
        results.append((description, success))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = 0
    total = len(results)
    
    for description, success in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        print("%s: %s" % (description.ljust(40), status))
        if success:
            passed += 1
    
    print("\nOverall: %d/%d tests passed" % (passed, total))
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! CouchPotato is ready for Python 3 migration.")
        return 0
    else:
        print("\n❌ Some tests failed. Please fix issues before migration.")
        return 1


if __name__ == '__main__':
    sys.exit(main())